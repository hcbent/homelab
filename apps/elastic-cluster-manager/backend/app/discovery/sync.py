"""Pull observed state into the database. Strictly read-only toward Proxmox and Elasticsearch."""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import redact
from app.discovery import correlate, es, proxmox
from app.discovery.factory import es_client, proxmox_client
from app.discovery.http import DiscoveryError
from app.models import Cluster, EsNode, ProxmoxConnection, PveNode, PveStorage, Vm


def _now() -> datetime:
    return datetime.now(UTC)


class IdentityMismatch(Exception):
    pass


# --- Proxmox ---------------------------------------------------------------

def sync_proxmox(db: Session, conn: ProxmoxConnection, client=None) -> None:
    try:
        snap = proxmox.collect(client or proxmox_client(db, conn))
    except DiscoveryError as e:
        conn.last_sync_error = redact(str(e))
        db.commit()
        raise
    now = _now()

    existing = {n.name: n for n in db.scalars(select(PveNode).where(PveNode.connection_id == conn.id))}
    for n in snap.nodes:
        row = existing.pop(n["node"], None) or PveNode(connection_id=conn.id, name=n["node"])
        row.status = n.get("status")
        row.usage = {k: n.get(k) for k in ("cpu", "maxcpu", "mem", "maxmem", "uptime")}
        row.networks = snap.networks.get(n["node"], [])
        row.observed_at = now
        db.add(row)
    for gone in existing.values():
        db.delete(gone)

    old_st = {(s.node, s.name): s for s in db.scalars(select(PveStorage).where(PveStorage.connection_id == conn.id))}
    for s in snap.storages:
        row = old_st.pop((s["node"], s["storage"]), None) or PveStorage(
            connection_id=conn.id, node=s["node"], name=s["storage"])
        row.type, row.content = s.get("type"), s.get("content")
        row.shared, row.active = bool(s.get("shared")), bool(s.get("active"))
        row.total, row.used, row.avail = s.get("total"), s.get("used"), s.get("avail")
        row.observed_at = now
        db.add(row)
    for gone in old_st.values():
        db.delete(gone)

    old_vm = {v.vmid: v for v in db.scalars(select(Vm).where(Vm.connection_id == conn.id))}
    for v in snap.vms:
        row = old_vm.pop(v.vmid, None) or Vm(connection_id=conn.id, vmid=v.vmid)
        row.pve_node, row.name, row.status, row.is_template = v.pve_node, v.name, v.status, v.is_template
        row.cpu_cores, row.memory_mb = v.cpu_cores, v.memory_mb
        row.disks, row.nets, row.ips, row.usage, row.config = v.disks, v.nets, v.ips, v.usage, v.config
        row.observed_at = now
        db.add(row)
    for gone in old_vm.values():
        db.delete(gone)

    conn.last_sync_at, conn.last_sync_error = now, None
    db.commit()
    for cluster in db.scalars(select(Cluster)):
        relink(db, cluster)


# --- Elasticsearch ---------------------------------------------------------

def sync_cluster(db: Session, cluster: Cluster, client=None) -> None:
    """Refresh a registered cluster. The cluster UUID must match what we registered."""
    try:
        snap = _collect_any(db, cluster, client)
        if cluster.es_cluster_uuid and snap.cluster_uuid != cluster.es_cluster_uuid:
            raise IdentityMismatch(
                f"Endpoint now reports cluster {snap.cluster_uuid}, expected {cluster.es_cluster_uuid}")
    except (DiscoveryError, IdentityMismatch) as e:
        cluster.last_sync_error = redact(str(e))
        db.commit()
        raise
    apply_snapshot(db, cluster, snap)


def _collect_any(db: Session, cluster: Cluster, client=None) -> es.ClusterSnapshot:
    if client is not None:
        return es.collect(client)
    last: Exception | None = None
    for url in cluster.endpoint_urls or []:
        try:
            return es.collect(es_client(db, cluster, url))
        except DiscoveryError as e:
            last = e
    raise last or DiscoveryError("No endpoints configured")


def apply_snapshot(db: Session, cluster: Cluster, snap: es.ClusterSnapshot) -> None:
    cluster.es_cluster_uuid = snap.cluster_uuid
    cluster.es_version, cluster.health_status = snap.version, snap.status
    cluster.snapshot = snap.detail
    existing = {n.es_node_id: n for n in db.scalars(select(EsNode).where(EsNode.cluster_id == cluster.id))}
    for n in snap.nodes:
        row = existing.pop(n.es_node_id, None) or EsNode(cluster_id=cluster.id, es_node_id=n.es_node_id)
        for attr in ("name", "ip", "host", "version", "roles", "attributes", "heap_used_pct",
                     "heap_max_bytes", "disk_total_bytes", "disk_avail_bytes", "shard_count"):
            setattr(row, attr, getattr(n, attr))
        db.add(row)
    for gone in existing.values():
        db.delete(gone)
    cluster.last_sync_at, cluster.last_sync_error = _now(), None
    db.commit()
    relink(db, cluster)


def relink(db: Session, cluster: Cluster) -> None:
    vms = [correlate.VmView(v.id, v.name, v.ips, v.is_template) for v in db.scalars(select(Vm))]
    for node in db.scalars(select(EsNode).where(EsNode.cluster_id == cluster.id)):
        link = correlate.link_node(node.ip, node.host, node.name, vms)
        node.vm_id, node.link_confidence, node.link_evidence = link.vm_key, link.confidence, link.evidence
    db.commit()


# --- Registration ----------------------------------------------------------

class AlreadyRegistered(Exception):
    pass


def register_cluster(db: Session, *, name: str | None, urls: list[str], credential_id: str,
                     tls_verify: bool, tls_ca_pem: str | None) -> Cluster:
    """Connect, verify identity, and record a discovered cluster. Never needs Terraform ownership."""
    probe = Cluster(name=name or "pending", endpoint_urls=urls, credential_id=credential_id,
                    tls_verify=tls_verify, tls_ca_pem=tls_ca_pem)
    snap = _collect_any(db, probe)
    if db.scalar(select(Cluster).where(Cluster.es_cluster_uuid == snap.cluster_uuid)):
        raise AlreadyRegistered(snap.cluster_uuid)
    probe.name = name or snap.cluster_name
    probe.ownership = "discovered"
    db.add(probe)
    db.flush()
    apply_snapshot(db, probe, snap)
    return probe


def sync_everything(db: Session) -> dict:
    """Used by the periodic job. One failure never stops the others."""
    errors = {}
    for conn in db.scalars(select(ProxmoxConnection)):
        try:
            sync_proxmox(db, conn)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            conn.last_sync_error = errors[f"proxmox:{conn.name}"] = redact(str(e))
            db.commit()
    for cluster in db.scalars(select(Cluster)):
        try:
            sync_cluster(db, cluster)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            cluster.last_sync_error = errors[f"cluster:{cluster.name}"] = redact(str(e))
            db.commit()
    return errors
