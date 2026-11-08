"""Keeping ECM's record of where each machine is in line with where Proxmox says it is.

A cluster's desired state records the Proxmox host each node's machine was made on (`placement`). A VM can be moved after that, by hand
or by HA when a host reboots or is put in maintenance, and then the record is wrong: found when a restart called Proxmox on the recorded
host and was told the VM's configuration file did not exist there. The operator's decision (2026-11-08) is that the record always
follows reality, so after each Proxmox sync this makes `placement` say where the inventory last saw each machine.

It matches on VM ID and name together, so a different machine that has taken over a VM ID is never followed, and it leaves a node
with no machine in the inventory (lost) alone. It reads only the models, like ownership.py, so discovery can call it.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Cluster, Vm


def follow_hosts(db: Session, connection_id: str) -> list[dict]:
    """Update each managed, built cluster on this Proxmox connection so its recorded placement matches the inventory. Returns what changed,
    as {cluster_id, cluster, node, was, now}; the caller commits and records it."""
    changes: list[dict] = []
    for cluster in db.scalars(select(Cluster).where(Cluster.ownership == "managed")):
        desired = cluster.desired
        if not desired or desired.get("proxmox_connection_id") != connection_id:
            continue
        placement = dict(desired.get("placement") or {})
        moved = False
        for name, vmid in (desired.get("vm_ids") or {}).items():
            row = db.scalar(select(Vm).where(Vm.connection_id == connection_id, Vm.vmid == int(vmid)))
            if row is None or row.name != name or not row.pve_node or placement.get(name) == row.pve_node:
                continue
            changes.append({"cluster_id": cluster.id, "cluster": cluster.name, "node": name,
                            "was": placement.get(name), "now": row.pve_node})
            placement[name] = row.pve_node
            moved = True
        if moved:
            cluster.desired = {**desired, "placement": placement}      # a new dict, so the change is saved
    return changes
