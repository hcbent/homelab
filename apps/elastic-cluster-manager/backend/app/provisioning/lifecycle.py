"""Changes to a cluster that already exists: what a person may ask for, checked against what it is now.

Each function takes the cluster's current desired state (`Cluster.desired`) and returns the parameters of the state
being asked for, or refuses with the reason in plain words. Nothing here touches Terraform, Ansible, Proxmox or
Elasticsearch: the parameters go to `start_update`, which plans them and waits for approval.
"""
import copy
from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.desired.models import DesiredState
from app.models import Cluster, PveStorage
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
