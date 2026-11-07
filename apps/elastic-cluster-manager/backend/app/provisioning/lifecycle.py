"""Changes to a cluster that already exists: what a person may ask for, checked against what it is now.

Each function takes the cluster's current desired state (`Cluster.desired`) and returns the parameters of the state
being asked for, or refuses with the reason in plain words. Nothing here touches Terraform, Ansible, Proxmox or
Elasticsearch: the parameters go to `start_update`, which plans them and waits for approval.
"""
import copy
import re
from collections import defaultdict
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.desired import AllocationError, TopologyPreset, allocate_addresses, warnings
from app.desired.models import DATA_ROLES, VALID_ROLES, DesiredState, NodeSpec, RolesMode
from app.desired.network import NetworkProfile
from app.discovery import factory
from app.discovery.http import DiscoveryError
from app.models import Cluster, EsNode, ProxmoxConnection, PveNode, PveStorage, Vm
from app.network_profiles import addresses_in_use
from app.provisioning.create import (
    CreateInvalid,
    _check_names,
    _placement,
    _reservations,
    _template,
)
from app.provisioning.operation import OperationRefused
from app.provisioning.vmid import VmidError, allocate_vmids

GIB = 1024 ** 3


class ExpandDisk(BaseModel):
    """Grow the data disk of some nodes, or of every node that has one, to this size."""

    model_config = ConfigDict(extra="forbid")
    data_disk_gb: int = Field(ge=10, le=65536)
    nodes: list[str] | None = Field(default=None, min_length=1)


def current_desired(cluster: Cluster) -> dict:
    """The parameters of the state the cluster is in now, or a refusal if ECM has no record of them."""
    if cluster.bootstrapped_at is None:
        raise OperationRefused("this cluster has not finished being built, so there is nothing to change yet")
    if not cluster.desired:
        raise OperationRefused("ECM has no record of this cluster's current state (it was built before ECM kept "
                               "one), so it cannot plan a change to it")
    return copy.deepcopy(cluster.desired)


def _room(db: Session, params: dict, growth_gb: dict[str, int]) -> list[str]:
    """Problems with the datastore having room for the growth. Space that ECM has not seen is not counted against it."""
    datastore = params.get("datastore_id", "tank")
    placement = params.get("placement", {})
    rows = db.scalars(select(PveStorage).where(PveStorage.name == datastore)).all()
    if not rows:
        return []
    by_host: dict[str, int] = defaultdict(int)
    for name, gb in growth_gb.items():
        by_host[placement.get(name, "")] += gb * GIB
    problems = []
    if any(r.shared for r in rows):
        free = max((r.avail or 0) for r in rows if r.shared)
        need = sum(by_host.values())
        if need > free:
            problems.append(f"the shared datastore {datastore} has {free // GIB} GiB free and this needs "
                            f"{need // GIB} GiB")
        return problems
    free_by_host = {r.node: r.avail for r in rows if r.avail is not None}
    for host, need in sorted(by_host.items()):
        free = free_by_host.get(host)
        if free is not None and need > free:
            problems.append(f"{host} has {free // GIB} GiB free on {datastore} and this needs {need // GIB} GiB there")
    return problems


def plan_expand_disk(db: Session, cluster: Cluster, request: ExpandDisk) -> dict:
    """The parameters with the chosen data disks grown. Refuses a shrink, a size that is not larger, a node that
    has no data disk, a name the cluster does not have, and a datastore without room."""
    params = current_desired(cluster)
    state = DesiredState.model_validate(params["state"])
    nodes = {n.name: n for n in state.nodes}
    chosen = request.nodes if request.nodes is not None else [n.name for n in state.nodes if n.data_disk_gb]
    unknown = sorted(set(chosen) - set(nodes))
    if unknown:
        raise OperationRefused(f"this cluster has no node named {', '.join(unknown)}")
    if not chosen:
        raise OperationRefused("this cluster has no node with a data disk")
    problems: list[str] = []
    growth: dict[str, int] = {}
    for name in chosen:
        node = nodes[name]
        if node.data_disk_gb is None:
            problems.append(f"{name} has no data disk (it holds no data)")
        elif request.data_disk_gb < node.data_disk_gb:
            problems.append(f"{name}'s data disk is {node.data_disk_gb} GB and cannot be shrunk to "
                            f"{request.data_disk_gb} GB: a disk is only ever grown")
        elif request.data_disk_gb == node.data_disk_gb:
            problems.append(f"{name}'s data disk is already {node.data_disk_gb} GB")
        else:
            growth[name] = request.data_disk_gb - node.data_disk_gb
    if problems:
        raise OperationRefused("; ".join(problems))
    problems = _room(db, params, growth)
    if problems:
        raise OperationRefused("; ".join(problems))

    before = {name: nodes[name].data_disk_gb for name in growth}
    for entry in params["state"]["nodes"]:
        if entry["name"] in growth:
            entry["data_disk_gb"] = request.data_disk_gb
    DesiredState.model_validate(params["state"])  # the grown state must still be a valid cluster
    names = ", ".join(sorted(growth))
    params["change"] = {
        "kind": "expand_disk",
        "nodes": {name: {"from_gb": before[name], "to_gb": request.data_disk_gb} for name in sorted(growth)},
        "describe": (f"grow the data disk of {names} to {request.data_disk_gb} GB and the filesystem on it; "
                     "nothing restarts"),
    }
    return params


MIB = 1024 ** 2


class ResizeNodes(BaseModel):
    """Give some nodes, or every node, a new number of cores and/or amount of RAM."""

    model_config = ConfigDict(extra="forbid")
    cores: int | None = Field(default=None, ge=1, le=64)
    ram_mb: int | None = Field(default=None, ge=2048, le=524288)
    nodes: list[str] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _something_changes(self) -> "ResizeNodes":
        if self.cores is None and self.ram_mb is None:
            raise ValueError("give a number of cores, an amount of RAM, or both")
        return self


def _memory_room(db: Session, params: dict, growth_mb: dict[str, int]) -> list[str]:
    """Problems with a host not having the memory a RAM increase needs, from the last sync. Hosts ECM has not
    seen, or whose usage it does not know, are not counted against the change."""
    placement = params.get("placement", {})
    per_host: dict[str, int] = defaultdict(int)
    for name, mb in growth_mb.items():
        per_host[placement.get(name, "")] += mb
    problems = []
    for host, need_mb in sorted(per_host.items()):
        row = db.scalars(select(PveNode).where(PveNode.name == host)).first()
        usage = (row.usage or {}) if row else {}
        total, used = usage.get("maxmem"), usage.get("mem")
        if total is None or used is None:
            continue
        free_mb = (int(total) - int(used)) // MIB
        if need_mb > free_mb:
            problems.append(f"{host} has {free_mb} MiB of memory free and this needs {need_mb} MiB more there")
    return problems


def plan_resize(db: Session, cluster: Cluster, request: ResizeNodes) -> dict:
    """The parameters with the chosen nodes resized. Refuses a single-node cluster (it would be down while its VM
    restarts), a node the cluster does not have, a node already at that size, a pinned heap that would be more than
    half of the new RAM, and a host without the memory for an increase."""
    params = current_desired(cluster)
    state = DesiredState.model_validate(params["state"])
    if state.is_single_node:
        raise OperationRefused("this is a single-node cluster: it would be down while its machine restarts, and "
                               "there is no replica to carry it, so ECM does not resize it")
    nodes = {n.name: n for n in state.nodes}
    chosen = request.nodes if request.nodes is not None else [n.name for n in state.nodes]
    unknown = sorted(set(chosen) - set(nodes))
    if unknown:
        raise OperationRefused(f"this cluster has no node named {', '.join(unknown)}")
    problems: list[str] = []
    changes: dict[str, dict] = {}
    growth: dict[str, int] = {}
    for name in chosen:
        node = nodes[name]
        cores = request.cores if request.cores is not None else node.cores
        ram = request.ram_mb if request.ram_mb is not None else node.ram_mb
        if (cores, ram) == (node.cores, node.ram_mb):
            problems.append(f"{name} already has {node.cores} cores and {node.ram_mb} MiB of RAM")
            continue
        if node.heap_mb is not None and node.heap_mb > ram // 2:
            problems.append(f"{name}'s heap is pinned at {node.heap_mb} MiB, which is more than half of {ram} MiB "
                            "of RAM; unpin or lower it first")
            continue
        entry: dict = {}
        if cores != node.cores:
            entry["cores"] = {"from": node.cores, "to": cores}
        if ram != node.ram_mb:
            entry["ram_mb"] = {"from": node.ram_mb, "to": ram}
            if ram > node.ram_mb:
                growth[name] = ram - node.ram_mb
        changes[name] = entry
    if problems:
        raise OperationRefused("; ".join(problems))
    problems = _memory_room(db, params, growth)
    if problems:
        raise OperationRefused("; ".join(problems))

    for entry in params["state"]["nodes"]:
        if entry["name"] in changes:
            entry["cores"] = request.cores if request.cores is not None else entry["cores"]
            entry["ram_mb"] = request.ram_mb if request.ram_mb is not None else entry["ram_mb"]
    DesiredState.model_validate(params["state"])  # the resized state must still be a valid cluster
    parts = []
    if request.cores is not None:
        parts.append(f"{request.cores} cores")
    if request.ram_mb is not None:
        parts.append(f"{request.ram_mb} MiB of RAM")
    params["change"] = {
        "kind": "resize",
        "nodes": {name: changes[name] for name in sorted(changes)},
        "describe": (f"give {', '.join(sorted(changes))} {' and '.join(parts)}: Terraform changes the machines' "
                     "configuration, then ECM restarts the nodes one at a time (coordinating nodes, data nodes, "
                     "then masters, the elected master last), waiting for the cluster to be green between them"),
    }
    return params


class AddNodes(BaseModel):
    """Add `count` nodes of one kind. `roles` is None for Elasticsearch's default roles (every role but voting_only), an
    empty list for a coordinating-only node, or the roles to give them. Sizes that are not given are copied from an
    existing node of the same kind."""

    model_config = ConfigDict(extra="forbid")
    count: int = Field(default=1, ge=1, le=10)
    roles: list[str] | None = None
    cores: int | None = Field(default=None, ge=1, le=64)
    ram_mb: int | None = Field(default=None, ge=2048, le=524288)
    os_disk_gb: int | None = Field(default=None, ge=16, le=2048)
    data_disk_gb: int | None = Field(default=None, ge=10, le=65536)
    pve_node: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _roles(self) -> "AddNodes":
        if self.roles is not None:
            bad = sorted(set(self.roles) - VALID_ROLES)
            if bad:
                raise ValueError("unknown Elasticsearch roles: " + ", ".join(bad))
            if len(set(self.roles)) != len(self.roles):
                raise ValueError("roles lists the same role twice")
            if "voting_only" in self.roles and "master" not in self.roles:
                raise ValueError("voting_only needs the master role")
        return self


def _holds_data(request: AddNodes) -> bool:
    return request.roles is None or bool(set(request.roles) & DATA_ROLES)


def _role_text(request: AddNodes) -> str:
    if request.roles is None:
        return "the default roles"
    return ", ".join(request.roles) if request.roles else "no roles (coordinating only)"


def _like(existing: list[NodeSpec], request: AddNodes) -> NodeSpec | None:
    """An existing node of the same kind, to copy sizes from: the same roles if there is one, else one that also does
    (or does not) hold data."""
    wanted = frozenset() if request.roles == [] else (
        None if request.roles is None else frozenset(request.roles))
    for node in existing:
        if wanted is not None and node.effective_roles == wanted:
            return node
        if wanted is None and node.roles_mode == RolesMode.default:
            return node
    holds = _holds_data(request)
    return next((n for n in existing if n.holds_data == holds), None)


def plan_add_nodes(db: Session, cluster: Cluster, request: AddNodes) -> dict:
    """The parameters with `count` new nodes added: next names, placed with every existing node pinned where it is (so
    the master quorum rule is checked for the whole cluster), with an address and a VMID each. Refuses a single-node
    cluster (it cannot be grown), a cluster that was not green and complete at its last sync, a node that cannot be
    placed or would break the quorum rule, and anything the create path would refuse."""
    params = current_desired(cluster)
    state = DesiredState.model_validate(params["state"])
    if state.is_single_node:
        raise OperationRefused("this is a single-node cluster, started in a mode that cannot take other nodes, so "
                               "nodes cannot be added to it")
    if cluster.health_status not in (None, "green"):
        raise OperationRefused(f"the cluster was {cluster.health_status} at its last sync; it must be green before a "
                               "node is added")
    seen = len(db.scalars(select(EsNode.id).where(EsNode.cluster_id == cluster.id)).all())
    if seen and seen != len(state.nodes):
        raise OperationRefused(f"ECM saw {seen} of this cluster's {len(state.nodes)} nodes at its last sync; every "
                               "node must be present before a node is added")

    like = _like(state.nodes, request)
    holds_data = _holds_data(request)
    cores = request.cores or (like.cores if like else 4)
    ram_mb = request.ram_mb or (like.ram_mb if like else 8192)
    os_disk = request.os_disk_gb or (like.os_disk_gb if like else 32)
    data_disk = None
    if holds_data:
        data_disk = request.data_disk_gb or next((n.data_disk_gb for n in state.nodes if n.data_disk_gb), 100)
    elif request.data_disk_gb:
        raise OperationRefused("these roles hold no data, so they get no data disk; leave the data disk empty")

    # Numbers only go up: a node's number is not reused, even after the node is gone.
    numbered = [int(m.group(1)) for n in state.nodes if (m := re.match(rf"^{re.escape(state.name)}-(\d+)$", n.name))]
    counter = max([int(params.get("node_counter", 0)), *numbered])
    mode = (RolesMode.default if request.roles is None else
            RolesMode.coordinating if request.roles == [] else RolesMode.custom)
    try:
        new_nodes = [NodeSpec(
            name=f"{state.name}-{counter + i + 1:02d}", roles_mode=mode, roles=list(request.roles or []),
            cores=cores, ram_mb=ram_mb, os_disk_gb=os_disk, data_disk_gb=data_disk, pve_node=request.pve_node)
            for i in range(request.count)]
    except ValidationError as exc:
        raise OperationRefused("; ".join(e["msg"] for e in exc.errors())) from exc

    pinned = [n.model_copy(update={"pve_node": params["placement"][n.name]}) for n in state.nodes]
    try:
        grown = DesiredState(name=state.name, version=state.version, topology_preset=TopologyPreset.custom,
                             nodes=[*pinned, *new_nodes], network_profile=state.network_profile)
    except ValidationError as exc:
        raise OperationRefused("; ".join(e["msg"] for e in exc.errors())) from exc

    conn = db.get(ProxmoxConnection, params.get("proxmox_connection_id") or "")
    if conn is None:
        raise OperationRefused("the Proxmox connection this cluster was built on no longer exists")
    settings = get_settings()
    datastore = params.get("datastore_id", settings.default_storage)
    try:
        _check_names(db, SimpleNamespace(nodes=new_nodes))      # only the names matter, not the cluster's rules
        template = _template(db, conn, (params.get("template") or {}).get("vm_id"))
        placement = _placement(db, conn, grown, datastore, template,
                               exclude_vms=frozenset(n.name for n in state.nodes))
        profile = NetworkProfile.model_validate(params["profile"])
        reserved_addresses, reserved_vmids = _reservations(db, None)
        in_use = ({a["ip"] for a in addresses_in_use(db)} | reserved_addresses | set(params["addresses"].values()))
        addresses = allocate_addresses(profile, new_nodes, in_use)
        used_vmids = ({v for (v,) in db.execute(select(Vm.vmid).where(Vm.connection_id == conn.id))}
                      | reserved_vmids | {int(v) for v in params["vm_ids"].values()})
        vm_ids = allocate_vmids([n.name for n in new_nodes], used_vmids, settings.vmid_range_start,
                                settings.vmid_range_end)
    except (CreateInvalid, AllocationError, VmidError) as exc:
        raise OperationRefused(str(exc)) from exc

    notes = list(warnings(grown)) + [i.message for i in placement.issues if i.severity == "warning"]
    names = [n.name for n in new_nodes]
    params["state"] = grown.model_dump(mode="json")
    params["placement"] = {**params["placement"], **{n: placement.hosts[n] for n in names}}
    params["addresses"] = {**params["addresses"], **addresses}
    params["vm_ids"] = {**params["vm_ids"], **{n: int(v) for n, v in vm_ids.items()}}
    params["node_counter"] = counter + request.count
    params["change"] = {
        "kind": "add_node", "added": names, "warnings": notes,
        "nodes": {n.name: {"host": placement.hosts[n.name], "address": addresses[n.name], "vm_id": int(vm_ids[n.name]),
                           "roles": _role_text(request), "cores": n.cores, "ram_mb": n.ram_mb,
                           "data_disk_gb": n.data_disk_gb} for n in new_nodes},
        "describe": (f"add {request.count} node{'s' if request.count != 1 else ''} ({', '.join(names)}) with "
                     f"{_role_text(request)}: Terraform makes the machine{'s' if request.count != 1 else ''}, then ECM "
                     "configures and starts only the new nodes and checks they joined and the cluster is green"),
    }
    return params


# -- removing nodes (docs/DESIGN_REMOVE_NODE.md) ------------------------------------------------------------------

LOW_WATERMARK = 0.85            # Elasticsearch's default; used when the cluster's own setting cannot be read
_TIERS = ("data_content", "data_hot", "data_warm", "data_cold", "data_frozen")
_SOFT_ROLES = ("ml", "ingest", "transform", "remote_cluster_client")   # losing the last one is a warning, not a refusal
_SHOWN = 5                      # how many shards or indices a refusal names before it says "and N more"


class RemoveNodes(BaseModel):
    """Remove these nodes. The cluster name is typed as a confirmation, as for a teardown: the machines and their data
    disks are destroyed and that cannot be undone."""

    model_config = ConfigDict(extra="forbid")
    nodes: list[str] = Field(min_length=1, max_length=20)
    confirm_name: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _distinct(self) -> "RemoveNodes":
        if len(set(self.nodes)) != len(self.nodes):
            raise ValueError("the same node is listed twice")
        return self


def _some(items: list[str]) -> str:
    return ", ".join(items[:_SHOWN]) + (f" and {len(items) - _SHOWN} more" if len(items) > _SHOWN else "")


def _read_cluster(db: Session, cluster: Cluster, client=None) -> dict:
    """What the cluster reports right now, with GET requests only. Refuses if ECM cannot reach it: a removal is never
    planned from the last sync alone, because shards move between syncs."""
    def read(c) -> dict:
        return {"health": c.health(), "nodes": c.nodes().get("nodes", {}), "stats": c.nodes_stats().get("nodes", {}),
                "shards": c.shards_sized(), "settings": c.settings(), "master": c.master()}
    if client is not None:
        return read(client)
    if not cluster.credential_id or not cluster.endpoint_urls:
        raise OperationRefused("ECM has no way to reach this cluster, so it cannot check that a node can be removed")
    last: Exception | None = None
    for url in cluster.endpoint_urls:
        try:
            return read(factory.es_client(db, cluster, url))
        except DiscoveryError as exc:
            last = exc
    raise OperationRefused(f"ECM could not read the cluster to check the removal ({last}); try again when it answers")


def _low_watermark(settings: dict) -> tuple[float, str | None]:
    """The disk low watermark as a share of a disk, and a note when it could not be read. A percentage or a ratio is
    understood; a size in bytes is not, and then the default is used and the plan says so."""
    key = "cluster.routing.allocation.disk.watermark.low"
    raw = (settings.get("transient", {}) or {}).get(key) or (settings.get("persistent", {}) or {}).get(key)
    if raw is None:
        return LOW_WATERMARK, None
    text = str(raw).strip()
    try:
        value = float(text[:-1]) / 100 if text.endswith("%") else float(text)
        if 0 < value <= 1:
            return value, None
    except ValueError:
        pass
    return LOW_WATERMARK, (f"the cluster's low disk watermark is set to {raw!r}, which ECM cannot read as a share of a "
                           f"disk, so the check used {LOW_WATERMARK:.0%}")


def _master_spread_problem(remaining: list[NodeSpec], placement: dict[str, str]) -> str | None:
    """The reverse of the add-node rule: after masters leave, no host may hold more than the cluster can lose with it."""
    masters = [n for n in remaining if n.is_master_eligible]
    survivable = (len(masters) - 1) // 2
    per_host: dict[str, int] = defaultdict(int)
    for n in masters:
        per_host[placement.get(n.name, "")] += 1
    worst = max(per_host.items(), key=lambda kv: kv[1], default=("", 0))
    if worst[1] > survivable:
        return (f"{worst[0]} would hold {worst[1]} of the {len(masters)} master-eligible nodes that remain, and a "
                f"cluster of {len(masters)} survives losing at most {survivable} at once, so losing that host would "
                "break the quorum. Spread them over more hosts first, or remove a different set")
    return None


def _quorum_problems(state: DesiredState, removing: list[NodeSpec], placement: dict[str, str]) -> list[str]:
    names = {n.name for n in removing}
    remaining = [n for n in state.nodes if n.name not in names]
    masters_now = state.master_eligible_nodes
    gone = [n for n in removing if n.is_master_eligible]
    problems: list[str] = []
    if len(remaining) < 2:
        problems.append("this would leave a single node, and a cluster cannot be turned into a single-node cluster "
                        "while it runs")
        return problems
    left = len(masters_now) - len(gone)
    if gone and left < 3:
        what = ("it is the only master-eligible node" if len(masters_now) <= 1 else
                f"only {left} master-eligible node{'s' if left != 1 else ''} would remain")
        problems.append(f"removing {_some([n.name for n in gone])} would break the quorum: {what}, and a cluster "
                        "needs at least 3 to survive losing one")
    elif gone and len(gone) * 2 >= len(masters_now):
        problems.append(f"removing {len(gone)} of the {len(masters_now)} master-eligible nodes at once is refused: "
                        "Elasticsearch can only take fewer than half of them out together")
    elif gone:
        spread = _master_spread_problem(remaining, placement)
        if spread:
            problems.append(spread)
    return problems


def plan_remove_nodes(db: Session, cluster: Cluster, request: RemoveNodes, client=None) -> dict:
    """The parameters with these nodes taken out, after refusing anything that could lose data or the quorum.

    The rules that need no cluster read come first (the name, the nodes, the quorum), then a live read of the cluster
    (green, every node present, where each shard copy is, how full each disk is) decides the rest. `client` is for
    tests; in use it is built from the cluster's stored key and endpoints. Nothing is changed here."""
    params = current_desired(cluster)
    if request.confirm_name != cluster.name:
        raise OperationRefused("type the cluster name exactly to confirm the removal")
    state = DesiredState.model_validate(params["state"])
    if state.is_single_node:
        raise OperationRefused("this is a single-node cluster; there is no node to remove from it")
    by_name = {n.name: n for n in state.nodes}
    unknown = sorted(set(request.nodes) - set(by_name))
    if unknown:
        raise OperationRefused(f"this cluster has no node named {', '.join(unknown)}")
    removing = [by_name[n] for n in sorted(request.nodes)]
    removing_names = {n.name for n in removing}
    remaining = [n for n in state.nodes if n.name not in removing_names]

    problems = _quorum_problems(state, removing, params.get("placement", {}))
    if not problems:
        try:
            DesiredState(name=state.name, version=state.version, topology_preset=TopologyPreset.custom,
                         nodes=remaining, network_profile=state.network_profile)
        except ValidationError as exc:
            problems = [e["msg"].removeprefix("Value error, ") for e in exc.errors()]
    if problems:
        raise OperationRefused("; ".join(problems))

    view = _read_cluster(db, cluster, client)
    notes, per_node = _check_live(state, removing, remaining, view)
    # The placement, addresses and VMIDs of the removed machines leave the record; the plan page and the ownership
    # check read them from the change, which is the only place they are kept.
    numbered = [int(m.group(1)) for n in state.nodes if (m := re.match(rf"^{re.escape(state.name)}-(\d+)$", n.name))]
    params["state"] = DesiredState(
        name=state.name, version=state.version, topology_preset=TopologyPreset.custom, nodes=remaining,
        network_profile=state.network_profile).model_dump(mode="json")
    detail = {}
    for n in removing:
        detail[n.name] = {"host": params["placement"].get(n.name), "address": params["addresses"].get(n.name),
                          "vm_id": int(params["vm_ids"][n.name]), "roles": ", ".join(sorted(n.effective_roles)) or
                          "none (coordinating only)", "cores": n.cores, "ram_mb": n.ram_mb,
                          "data_disk_gb": n.data_disk_gb, **per_node.get(n.name, {"shards": 0, "data_bytes": 0})}
    for table in ("placement", "addresses", "vm_ids"):
        params[table] = {k: v for k, v in params[table].items() if k not in removing_names}
    params["node_counter"] = max([int(params.get("node_counter", 0)), *numbered])
    names = [n.name for n in removing]
    params["change"] = {
        "kind": "remove_nodes", "removed": names, "warnings": notes, "nodes": detail,
        "describe": (f"remove {len(names)} node{'s' if len(names) != 1 else ''} ({', '.join(names)}): "
                     "Elasticsearch moves their shards to the other nodes, then Terraform destroys the machines and "
                     "their disks, then ECM checks the cluster is green with the nodes that remain"),
    }
    return params


def _check_live(state: DesiredState, removing: list[NodeSpec], remaining: list[NodeSpec],
                view: dict) -> tuple[list[str], dict[str, dict]]:
    """The rules that need the cluster as it is now. Returns the warnings and, per removed node, the shards and bytes it
    holds; raises OperationRefused listing every problem found."""
    names = {n.name for n in removing}
    health, live = view["health"], view["nodes"]
    problems: list[str] = []
    if health.get("status") != "green":
        problems.append(f"the cluster is {health.get('status')}; it must be green before a node is removed")
    present = {info.get("name"): nid for nid, info in live.items()}
    if health.get("number_of_nodes") != len(state.nodes) or set(present) != {n.name for n in state.nodes}:
        problems.append(f"the cluster has {health.get('number_of_nodes')} nodes and ECM expects {len(state.nodes)}; "
                        "every node must be present before one is removed")
    if problems:
        raise OperationRefused("; ".join(problems))

    roles = {info["name"]: set(info.get("roles", [])) for info in live.values()}
    stats = {live[nid]["name"]: ((st.get("fs") or {}).get("total") or {}) for nid, st in view["stats"].items() if nid in live}
    shards = view["shards"]
    notes: list[str] = []

    stuck = [f"{s['index']}[{s['shard']}]" for s in shards if s.get("state") != "STARTED"]
    if stuck:
        problems.append(f"{len(stuck)} shard cop{'ies are' if len(stuck) != 1 else 'y is'} not started "
                        f"({_some(stuck)}); a node is removed only from a cluster with every shard in place")

    copies: dict[tuple, list[str]] = defaultdict(list)
    per_node: dict[str, dict] = {n: {"shards": 0, "data_bytes": 0} for n in names}
    for s in shards:
        if s.get("state") == "STARTED" and s.get("node"):
            copies[(s["index"], s["shard"])].append(s["node"])
        if s.get("node") in per_node:
            per_node[s["node"]]["shards"] += 1
            per_node[s["node"]]["data_bytes"] += int(s.get("store") or 0)

    only_copy = sorted(f"{i}[{sh}]" for (i, sh), where in copies.items() if set(where) <= names)
    if only_copy:
        problems.append(f"the only copy of {len(only_copy)} shard{'s' if len(only_copy) != 1 else ''} is on a node being "
                        f"removed ({_some(only_copy)}); add a replica to each of those indices first, or keep the node")

    data_left = [n for n in remaining if roles.get(n.name, set()) & DATA_ROLES]
    crowded = sorted({i for (i, _), where in copies.items() if len(where) > len(data_left)})
    if crowded:
        problems.append(f"{_some(crowded)} keep more copies of each shard than the {len(data_left)} data "
                        f"node{'s' if len(data_left) != 1 else ''} that would remain, so the cluster would stay yellow")

    left_roles = set().union(*(roles.get(n.name, set()) for n in remaining)) if remaining else set()

    def covered(role: str) -> bool:
        return role in left_roles or (role in _TIERS and role != "data_frozen" and "data" in left_roles)
    for n in removing:
        lost = sorted(r for r in roles.get(n.name, set()) & DATA_ROLES if not covered(r))
        if lost and per_node[n.name]["shards"]:
            problems.append(f"{n.name} is the last node with the {', '.join(lost)} role and holds shards, which would "
                            "have no node of that tier to go to")
        elif lost:       # holds nothing, so nothing is stranded; a default-role node always has the tiers no one uses
            notes.append(f"no node with the {', '.join(lost)} role would remain")
    for role in _SOFT_ROLES:
        if any(role in roles.get(n.name, set()) for n in removing) and role not in left_roles:
            notes.append(f"no node with the {role} role would remain")

    low, note = _low_watermark(view["settings"])
    if note:
        notes.append(note)
    def used(name: str) -> int:
        t = stats.get(name, {})
        return int(t.get("total_in_bytes", 0)) - int(t.get("available_in_bytes", 0))
    moving = sum(used(n.name) for n in removing if roles.get(n.name, set()) & DATA_ROLES)
    room = sum(int(stats.get(n.name, {}).get("total_in_bytes", 0)) for n in data_left)
    already = sum(used(n.name) for n in data_left)
    if room and already + moving > low * room:
        gib = 1024 ** 3
        problems.append(f"the data nodes that would remain have {already / gib:.1f} GiB used of {room / gib:.1f} GiB, "
                        f"and the {moving / gib:.1f} GiB on the removed nodes would take them to "
                        f"{(already + moving) / room:.0%}, past the {low:.0%} low disk watermark")
    elif not room and moving:
        problems.append("ECM could not read the disk size of the data nodes that would remain")

    if problems:
        raise OperationRefused("; ".join(problems))
    elected = ((view["master"] or [{}])[0]).get("node")
    if elected in names:
        notes.append(f"{elected} is the elected master, so a new master is elected when it goes (a few seconds)")
    return notes, per_node
