"""Turn a "create a cluster" request into a planned operation.

Everything here reads ECM's own database (the last discovery sync, the network profile, other operations) and
decides, deterministically: the node list, where each node goes, its address and its VMID. It touches neither
Proxmox nor Terraform; the operation it creates does that, after a human approves the plan.

What is checked, and why:
  * names: the cluster and every node name must be unused, so a new node can never be mistaken for the live
    cluster's, or collide with an existing VM
  * placement: the existing scoring, with the template's host and shared-storage rule on top (Milestone 0:
    a clone to another host works only when the template disk is on storage that host can read)
  * addresses and VMIDs: not in use on Proxmox or Elasticsearch, and not already promised to another create
    that discovery has not seen yet. The allocate-and-commit step runs under a database lock on Postgres, so two
    requests cannot be handed the same address.
The version is checked by the caller before this runs, because it needs the network and must not hold the lock.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.desired import (
    AllocationError,
    DesiredState,
    NodeSpec,
    PlacementConfig,
    TopologyPreset,
    allocate_addresses,
    build_desired_state,
    host_views_from_rows,
    recommend_placement,
    warnings,
)
from app.desired.network import NetworkProfile
from app.models import (
    ACTIVE_STATES,
    Cluster,
    EsNode,
    NetworkProfileRow,
    Operation,
    ProxmoxConnection,
    PveNode,
    PveStorage,
    Vm,
)
from app.network_profiles import addresses_in_use, to_domain
from app.operations import OperationConflict
from app.provisioning.operation import CREATE, DESTROY, OperationRefused, start_create
from app.provisioning.vmid import VmidError, allocate_vmids

# A create that succeeded keeps its addresses and VMIDs reserved this long, so they are not handed out again
# before discovery has had time to see the new VMs.
RESERVATION_GRACE = timedelta(hours=1)
STALE_SYNC = timedelta(minutes=30)
ALLOCATION_LOCK_KEY = 0x45434D41  # "ECMA": serialises allocation across requests on Postgres


class CreateInvalid(Exception):
    """The request cannot become a cluster as asked. The message says what to change."""


class CreateConflict(Exception):
    """The request clashes with something that already exists."""


class NodeOverride(BaseModel):
    """Per-node changes on top of a preset. Only the fields that are sent are changed."""

    model_config = ConfigDict(extra="forbid")
    cores: int | None = None
    ram_mb: int | None = None
    os_disk_gb: int | None = None
    data_disk_gb: int | None = None
    heap_mb: int | None = None
    pve_node: str | None = None  # pin to a Proxmox host
    ip: str | None = None  # a fixed address


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    preset: TopologyPreset
    data_nodes: int = Field(default=3, ge=1, le=40)
    coordinating_nodes: int = Field(default=0, ge=0, le=20)
    nodes: list[NodeSpec] | None = None  # for the custom preset only
    node_overrides: dict[str, NodeOverride] = Field(default_factory=dict)
    proxmox_connection_id: str | None = None  # optional when there is exactly one connection
    network_profile: str | None = None  # defaults to the profile named "default"
    template_vmid: int | None = None  # defaults to ECM_DEFAULT_TEMPLATE_VMID, then ECM_DEFAULT_TEMPLATE_NAME
    datastore: str | None = None  # defaults to ECM_DEFAULT_STORAGE
    pool_id: str = "ecm"
    # Plan only, and the plan can never be approved. Real creates are opt-in.
    dry_run: bool = True


@dataclass
class Resolved:
    state: DesiredState
    params: dict
    placement: dict[str, str]
    addresses: dict[str, str]
    vm_ids: dict[str, int]
    warnings: list[str] = field(default_factory=list)


# ---- small helpers --------------------------------------------------------------------------------------

def _message(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"]
                     for e in exc.errors())


def _aware(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=UTC) if moment is not None and moment.tzinfo is None else moment


def lock_allocation(db: Session) -> None:
    """Serialise allocation. The lock lasts until the transaction ends, which is when the operation that holds
    the allocated addresses and VMIDs is committed. A no-op on SQLite, which has one writer anyway."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ALLOCATION_LOCK_KEY})


# ---- what to build it from ------------------------------------------------------------------------------

def _connection(db: Session, wanted: str | None) -> ProxmoxConnection:
    if wanted:
        conn = db.get(ProxmoxConnection, wanted)
        if conn is None:
            raise CreateInvalid("that Proxmox connection does not exist")
        return conn
    conns = db.scalars(select(ProxmoxConnection).order_by(ProxmoxConnection.name)).all()
    if not conns:
        raise CreateInvalid("add a Proxmox connection before creating a cluster")
    if len(conns) > 1:
        raise CreateInvalid("there is more than one Proxmox connection; choose one with proxmox_connection_id")
    return conns[0]


def _profile(db: Session, wanted: str | None) -> NetworkProfile:
    rows = db.scalars(select(NetworkProfileRow).order_by(NetworkProfileRow.name)).all()
    if wanted or any(r.name == "default" for r in rows):
        name = wanted or "default"
        row = next((r for r in rows if r.name == name), None)
        if row is None:
            raise CreateInvalid(f"there is no network profile named {name!r}")
        return to_domain(row)
    if len(rows) == 1:
        return to_domain(rows[0])
    raise CreateInvalid("choose a network profile with network_profile")


def _build_state(req: CreateRequest, profile: NetworkProfile) -> DesiredState:
    try:
        if req.preset == TopologyPreset.custom:
            if not req.nodes:
                raise CreateInvalid("the custom preset needs a nodes list")
            state = DesiredState(name=req.name, version=req.version, topology_preset=req.preset,
                                 nodes=req.nodes, network_profile=profile.name)
        else:
            if req.nodes:
                raise CreateInvalid("a nodes list is only for the custom preset; use node_overrides to adjust "
                                    "a preset")
            state = build_desired_state(req.preset, req.name, req.version, data_nodes=req.data_nodes,
                                        coordinating_nodes=req.coordinating_nodes,
                                        network_profile=profile.name)
        unknown = sorted(set(req.node_overrides) - {n.name for n in state.nodes})
        if unknown:
            raise CreateInvalid(f"node_overrides names nodes that do not exist: {', '.join(unknown)}")
        nodes = [NodeSpec.model_validate({**n.model_dump(),
                                          **req.node_overrides[n.name].model_dump(exclude_unset=True)})
                 if n.name in req.node_overrides else n for n in state.nodes]
        return DesiredState(name=state.name, version=state.version, topology_preset=state.topology_preset,
                            nodes=nodes, network_profile=profile.name)
    except ValidationError as exc:
        raise CreateInvalid(_message(exc)) from exc
    except ValueError as exc:
        raise CreateInvalid(str(exc)) from exc


def _cluster_for(db: Session, name: str) -> Cluster | None:
    """The planned cluster this name refers to, or None. A name is reusable only while nothing was applied, so
    a dry run can be followed by the real create under the same name."""
    same = db.scalars(select(Cluster).where(Cluster.name == name)).all()
    if not same:
        return None
    if len(same) > 1 or same[0].ownership != "managed":
        raise CreateConflict(f"a cluster named {name!r} already exists")
    cluster = same[0]
    for op in db.scalars(select(Operation).where(Operation.cluster_id == cluster.id)):
        if op.state in ACTIVE_STATES:
            raise CreateConflict(f"{name!r} has an operation in progress; finish or cancel it first")
        nothing_applied = op.dry_run or op.state == "cancelled" or (op.state == "failed" and not op.result)
        if not nothing_applied:
            raise CreateConflict(
                f"a create for {name!r} already ran and may have made VMs; retry or clean it up from its "
                "operation, or choose another name")
    return cluster


def _check_names(db: Session, state: DesiredState) -> None:
    taken = {n for (n,) in db.execute(select(Vm.name)) if n} | {n for (n,) in db.execute(select(EsNode.name)) if n}
    clash = sorted(n.name for n in state.nodes if n.name in taken)
    if clash:
        raise CreateInvalid(f"these node names are already used by a VM or an Elasticsearch node: "
                            f"{', '.join(clash)}. Choose another cluster name")


# ---- Proxmox facts --------------------------------------------------------------------------------------

def _template(db: Session, conn: ProxmoxConnection, vmid: int | None) -> Vm:
    settings = get_settings()
    vmid = vmid if vmid is not None else settings.default_template_vmid
    templates = db.scalars(select(Vm).where(Vm.connection_id == conn.id, Vm.is_template.is_(True))).all()
    if vmid is not None:
        found = [t for t in templates if t.vmid == vmid]
        what = f"VMID {vmid}"
    elif settings.default_template_name:
        found = [t for t in templates if t.name == settings.default_template_name]
        what = f"name {settings.default_template_name!r}"
    else:
        raise CreateInvalid("no template: send template_vmid, or set ECM_DEFAULT_TEMPLATE_VMID")
    if len(found) != 1:
        raise CreateInvalid(f"no single template with {what} is known on this Proxmox connection; check the "
                            "template exists and that discovery has synced")
    return found[0]


def _placement(db: Session, conn: ProxmoxConnection, state: DesiredState, datastore: str, template: Vm):
    nodes = [{"name": n.name, "status": n.status, "usage": n.usage}
             for n in db.scalars(select(PveNode).where(PveNode.connection_id == conn.id))]
    if not nodes:
        raise CreateInvalid("no Proxmox hosts are known yet; run a sync on the Proxmox connection first")
    store_rows = list(db.scalars(select(PveStorage).where(PveStorage.connection_id == conn.id)))
    storages = [{"node": s.node, "name": s.name, "shared": s.shared, "active": s.active, "total": s.total,
                 "avail": s.avail} for s in store_rows]
    vms = [{"pve_node": v.pve_node, "status": v.status, "is_template": v.is_template, "cpu_cores": v.cpu_cores,
            "memory_mb": v.memory_mb}
           for v in db.scalars(select(Vm).where(Vm.connection_id == conn.id))]
    result = recommend_placement(state, host_views_from_rows(nodes, storages, vms),
                                 PlacementConfig(datastore=datastore))
    errors = [(f"{i.node}: " if i.node else "") + i.message for i in result.issues if i.severity == "error"]
    if errors:
        raise CreateInvalid("the nodes cannot be placed: " + "; ".join(errors))

    # A clone to another host reads the template's disks from that host, so they must be on shared storage.
    readable = {(s.node, s.name) for s in store_rows if s.shared and s.active}
    unreadable = []
    for node, host in sorted(result.hosts.items()):
        if host == template.pve_node:
            continue
        for disk in template.disks or []:
            if disk.get("storage") and (host, disk["storage"]) not in readable:
                unreadable.append(f"{node} on {host} (template disk on {disk['storage']!r})")
    if unreadable:
        raise CreateInvalid(
            f"the template is on {template.pve_node}, and its disk is not on shared storage that these hosts "
            f"can read: {'; '.join(unreadable)}. Put those nodes on {template.pve_node} with pve_node, or "
            "use a template whose disk is on shared storage")
    return result


def _reservations(db: Session, own_cluster: str | None) -> tuple[set[str], set[int]]:
    """Addresses and VMIDs promised to other real creates that discovery may not show yet."""
    now = datetime.now(UTC)
    ops = db.scalars(select(Operation).where(Operation.kind.in_((CREATE, DESTROY)))).all()
    cleaned = {o.parent_op_id for o in ops if o.kind == DESTROY and o.state == "succeeded"}
    addresses: set[str] = set()
    vmids: set[int] = set()
    for op in ops:
        if op.kind != CREATE or op.dry_run or op.cluster_id == own_cluster:
            continue
        finished = _aware(op.finished_at)
        holds = (op.state in ACTIVE_STATES
                 or (op.state == "failed" and bool(op.result) and op.id not in cleaned)
                 or (op.state == "succeeded" and finished is not None and now - finished < RESERVATION_GRACE))
        if holds:
            addresses.update((op.params.get("addresses") or {}).values())
            vmids.update(int(v) for v in (op.params.get("vm_ids") or {}).values())
    return addresses, vmids


# ---- the whole thing ------------------------------------------------------------------------------------

def resolve(db: Session, req: CreateRequest, own_cluster: str | None = None) -> Resolved:
    """Decide everything about the new cluster. Raises CreateInvalid or CreateConflict, never touches anything."""
    settings = get_settings()
    conn = _connection(db, req.proxmox_connection_id)
    profile = _profile(db, req.network_profile)
    state = _build_state(req, profile)
    _check_names(db, state)
    template = _template(db, conn, req.template_vmid)
    datastore = req.datastore or settings.default_storage
    placement = _placement(db, conn, state, datastore, template)

    reserved_addresses, reserved_vmids = _reservations(db, own_cluster)
    in_use = {a["ip"] for a in addresses_in_use(db)} | reserved_addresses
    try:
        addresses = allocate_addresses(profile, state.nodes, in_use)
        used_vmids = {v for (v,) in db.execute(select(Vm.vmid).where(Vm.connection_id == conn.id))} | reserved_vmids
        vm_ids = allocate_vmids([n.name for n in state.nodes], used_vmids,
                                settings.vmid_range_start, settings.vmid_range_end)
    except (AllocationError, VmidError) as exc:
        raise CreateInvalid(str(exc)) from exc

    notes = list(warnings(state)) + [i.message for i in placement.issues if i.severity == "warning"]
    synced = _aware(conn.last_sync_at)
    if conn.last_sync_error:
        notes.append(f"the last Proxmox sync failed ({conn.last_sync_error}); placement uses older data")
    elif synced is None or datetime.now(UTC) - synced > STALE_SYNC:
        notes.append("Proxmox has not been synced in over 30 minutes; placement may be out of date")

    params = {
        "state": state.model_dump(mode="json"), "placement": placement.hosts, "addresses": addresses,
        "vm_ids": vm_ids, "profile": profile.model_dump(mode="json"),
        "template": {"node_name": template.pve_node, "vm_id": template.vmid},
        "proxmox_connection_id": conn.id, "datastore_id": datastore, "pool_id": req.pool_id,
    }
    return Resolved(state, params, placement.hosts, addresses, vm_ids, notes)


def create_cluster_operation(db: Session, req: CreateRequest, actor: str) -> tuple[Cluster, Operation, Resolved]:
    """Allocate, then record the planned cluster and its operation in one transaction.

    The caller enqueues the job. By the time this returns, the operation (and the addresses and VMIDs in its
    params) is committed, so the next request sees them as taken.
    """
    lock_allocation(db)
    cluster = _cluster_for(db, req.name)
    resolved = resolve(db, req, own_cluster=cluster.id if cluster else None)
    try:
        if cluster is None:
            cluster = Cluster(name=req.name, ownership="managed")
            db.add(cluster)
            db.flush()
        op = start_create(db, cluster_id=cluster.id, params=resolved.params, actor=actor, dry_run=req.dry_run)
    except (OperationRefused, OperationConflict):
        db.rollback()
        raise
    return cluster, op, resolved
