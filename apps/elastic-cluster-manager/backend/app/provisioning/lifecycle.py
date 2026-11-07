"""Changes to a cluster that already exists: what a person may ask for, checked against what it is now.

Each function takes the cluster's current desired state (`Cluster.desired`) and returns the parameters of the state
being asked for, or refuses with the reason in plain words. Nothing here touches Terraform, Ansible, Proxmox or
Elasticsearch: the parameters go to `start_update`, which plans them and waits for approval.
"""
import copy
from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.desired.models import DesiredState
from app.models import Cluster, PveNode, PveStorage
from app.provisioning.operation import OperationRefused

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
        "describe": (f"give {', '.join(sorted(changes))} {' and '.join(parts)}. Terraform changes the machines' "
                     "configuration; the new size takes effect when each machine restarts, which ECM does not "
                     "do for you yet"),
    }
    return params
