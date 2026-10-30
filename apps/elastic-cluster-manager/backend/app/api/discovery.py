from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, auth, crypto
from app.db import get_db
from app.discovery import sync
from app.discovery.es import is_data_node
from app.discovery.http import DiscoveryError
from app.models import (
    Cluster,
    Credential,
    EsNode,
    ProxmoxConnection,
    PveNode,
    PveStorage,
    User,
    Vm,
)

router = APIRouter(prefix="/api", tags=["discovery"],
                   dependencies=[Depends(auth.require_csrf_header)])


# ---------- Proxmox connections ----------

class ProxmoxIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    api_url: HttpUrl
    token_id: str = Field(min_length=3, description="user@realm!tokenname")
    token_secret: str = Field(min_length=8)
    verify_tls: bool = True
    ca_pem: str | None = None


def _conn(c: ProxmoxConnection) -> dict:  # never includes the secret
    return {"id": c.id, "name": c.name, "api_url": c.api_url, "token_id": c.token_id,
            "verify_tls": c.tls_verify, "last_sync_at": c.last_sync_at,
            "last_sync_error": c.last_sync_error}


@router.get("/proxmox")
def list_connections(db: Session = Depends(get_db), _: User = Depends(auth.current_user)):
    return [_conn(c) for c in db.scalars(select(ProxmoxConnection).order_by(ProxmoxConnection.name))]


@router.post("/proxmox", status_code=201)
def add_connection(body: ProxmoxIn, db: Session = Depends(get_db),
                   user: User = Depends(auth.current_user)):
    if db.scalar(select(ProxmoxConnection).where(ProxmoxConnection.name == body.name)):
        raise HTTPException(409, "A connection with that name exists")
    cred = Credential(kind="proxmox_token", name=f"proxmox:{body.name}",
                      ciphertext=crypto.encrypt(body.token_secret))
    db.add(cred)
    db.flush()
    conn = ProxmoxConnection(name=body.name, api_url=str(body.api_url).rstrip("/"),
                             token_id=body.token_id, credential_id=cred.id,
                             tls_verify=body.verify_tls, tls_ca_pem=body.ca_pem)
    db.add(conn)
    db.commit()
    audit.record(db, user.username, "proxmox.add", "proxmox_connection", conn.id, name=body.name,
                 tls_verify=body.verify_tls)
    return _conn(conn)


@router.post("/proxmox/{conn_id}/sync")
def sync_connection(conn_id: str, db: Session = Depends(get_db), _: User = Depends(auth.current_user)):
    conn = db.get(ProxmoxConnection, conn_id)
    if not conn:
        raise HTTPException(404, "Not found")
    try:
        sync.sync_proxmox(db, conn)
    except DiscoveryError as e:
        raise HTTPException(502, str(e)) from e
    return _conn(conn)


@router.get("/infrastructure")
def infrastructure(db: Session = Depends(get_db), _: User = Depends(auth.current_user)):
    """Proxmox-reported state."""
    vms = db.scalars(select(Vm).order_by(Vm.pve_node, Vm.vmid)).all()
    linked = {n.vm_id: (n.cluster_id, n.link_confidence) for n in db.scalars(select(EsNode))
              if n.vm_id}
    return {
        "connections": [_conn(c) for c in db.scalars(select(ProxmoxConnection))],
        "nodes": [{"name": n.name, "status": n.status, "usage": n.usage, "networks": n.networks,
                   "connection_id": n.connection_id}
                  for n in db.scalars(select(PveNode).order_by(PveNode.name))],
        "storages": [{"node": s.node, "name": s.name, "type": s.type, "content": s.content,
                      "shared": s.shared, "active": s.active, "total": s.total, "used": s.used,
                      "avail": s.avail}
                     for s in db.scalars(select(PveStorage).order_by(PveStorage.node, PveStorage.name))],
        "templates": [_vm(v, linked) for v in vms if v.is_template],
        "vms": [_vm(v, linked) for v in vms if not v.is_template],
    }


def _vm(v: Vm, linked: dict) -> dict:
    cluster_id, conf = linked.get(v.id, (None, None))
    return {"id": v.id, "pve_node": v.pve_node, "vmid": v.vmid, "name": v.name, "status": v.status,
            "cpu_cores": v.cpu_cores, "memory_mb": v.memory_mb, "disks": v.disks, "nets": v.nets,
            "ips": v.ips, "usage": v.usage, "tf_managed": v.tf_managed,
            "es_cluster_id": cluster_id, "es_link": conf}


# ---------- Elasticsearch clusters ----------

class RegisterIn(BaseModel):
    name: str | None = None
    urls: list[HttpUrl] = Field(min_length=1)
    api_key: str = Field(min_length=8, description="Encoded Elasticsearch API key")
    verify_tls: bool = True
    ca_pem: str | None = None


def _storage_summary(nodes: list[EsNode]) -> dict:
    total = sum(n.disk_total_bytes or 0 for n in nodes)
    avail = sum(n.disk_avail_bytes or 0 for n in nodes)
    return {"total_bytes": total, "used_bytes": total - avail,
            "used_pct": round(100 * (total - avail) / total, 1) if total else None}


def _summary(c: Cluster, nodes: list[EsNode], vms: dict[str, Vm]) -> dict:
    heaps = [n.heap_used_pct for n in nodes if n.heap_used_pct is not None]
    hosts = sorted({vms[n.vm_id].pve_node for n in nodes if n.vm_id in vms})
    return {
        "id": c.id, "name": c.name, "uuid": c.es_cluster_uuid, "version": c.es_version,
        "health": c.health_status, "ownership": c.ownership,
        "nodes": len(nodes), "data_nodes": sum(1 for n in nodes if is_data_node(n.roles)),
        "infrastructure": {"proxmox_hosts": hosts,
                           "verified_links": sum(1 for n in nodes if n.link_confidence == "verified"),
                           "total_nodes": len(nodes)},
        "storage": _storage_summary(nodes),
        "jvm_heap_used_pct": round(sum(heaps) / len(heaps), 1) if heaps else None,
        "jvm_heap_max_pct": max(heaps) if heaps else None,
        "last_sync_at": c.last_sync_at, "last_sync_error": c.last_sync_error,
    }


@router.get("/clusters")
def list_clusters(db: Session = Depends(get_db), _: User = Depends(auth.current_user)):
    vms = {v.id: v for v in db.scalars(select(Vm))}
    out = []
    for c in db.scalars(select(Cluster).order_by(Cluster.name)):
        nodes = db.scalars(select(EsNode).where(EsNode.cluster_id == c.id)).all()
        out.append(_summary(c, nodes, vms))
    return out


@router.post("/clusters/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    name = body.name or "pending"
    cred = Credential(kind="es_api_key", name=f"es:{name}:{crypto.generate_key()[:8]}",
                      ciphertext=crypto.encrypt(body.api_key))
    db.add(cred)
    db.flush()
    try:
        cluster = sync.register_cluster(
            db, name=body.name, urls=[str(u).rstrip("/") for u in body.urls], credential_id=cred.id,
            tls_verify=body.verify_tls, tls_ca_pem=body.ca_pem)
    except sync.AlreadyRegistered as e:
        db.rollback()
        raise HTTPException(409, "That cluster is already registered") from e
    except DiscoveryError as e:
        db.rollback()
        raise HTTPException(502, f"Could not reach cluster: {e}") from e
    audit.record(db, user.username, "cluster.register", "cluster", cluster.id, name=cluster.name,
                 tls_verify=body.verify_tls)
    vms = {v.id: v for v in db.scalars(select(Vm))}
    nodes = db.scalars(select(EsNode).where(EsNode.cluster_id == cluster.id)).all()
    return _summary(cluster, nodes, vms)


@router.get("/clusters/{cluster_id}")
def cluster_detail(cluster_id: str, db: Session = Depends(get_db), _: User = Depends(auth.current_user)):
    c = db.get(Cluster, cluster_id)
    if not c:
        raise HTTPException(404, "Cluster not found")
    nodes = db.scalars(select(EsNode).where(EsNode.cluster_id == c.id).order_by(EsNode.name)).all()
    vms = {v.id: v for v in db.scalars(select(Vm))}
    snap = c.snapshot or {}
    return {
        **_summary(c, nodes, vms),
        # Three distinct sources of truth; never merged.
        "elasticsearch": {"health": snap.get("health"), "shards": snap.get("shards"),
                          "settings": snap.get("settings")},
        "proxmox": {"vms": [_vm(vms[n.vm_id], {n.vm_id: (c.id, n.link_confidence)})
                            for n in nodes if n.vm_id in vms]},
        "desired": {"managed": c.ownership in ("managed", "adopted"),
                    "note": "Not managed: this application holds no desired state for it yet."
                    if c.ownership == "discovered" else None},
        "node_list": [{
            "id": n.id, "name": n.name, "ip": n.ip, "version": n.version, "roles": n.roles,
            "attributes": n.attributes, "heap_used_pct": n.heap_used_pct,
            "heap_max_bytes": n.heap_max_bytes, "disk_total_bytes": n.disk_total_bytes,
            "disk_avail_bytes": n.disk_avail_bytes, "shard_count": n.shard_count,
            "link": {"confidence": n.link_confidence, "evidence": n.link_evidence,
                     "vm": ({"pve_node": vms[n.vm_id].pve_node, "vmid": vms[n.vm_id].vmid,
                             "name": vms[n.vm_id].name, "cpu_cores": vms[n.vm_id].cpu_cores,
                             "memory_mb": vms[n.vm_id].memory_mb, "disks": vms[n.vm_id].disks}
                            if n.vm_id in vms else None)}} for n in nodes],
    }


@router.post("/clusters/{cluster_id}/sync")
def sync_one(cluster_id: str, db: Session = Depends(get_db), _: User = Depends(auth.current_user)):
    c = db.get(Cluster, cluster_id)
    if not c:
        raise HTTPException(404, "Cluster not found")
    try:
        sync.sync_cluster(db, c)
    except (DiscoveryError, sync.IdentityMismatch) as e:
        raise HTTPException(502, str(e)) from e
    return {"ok": True, "last_sync_at": c.last_sync_at}
