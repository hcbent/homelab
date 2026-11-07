"""Which machines ECM itself created: the source of `vms.tf_managed`.

A VM is ECM's when a real create of ECM's own recorded it in Terraform state and no teardown has removed it. The
flag is derived from those records, never from a VM's name alone, so a VM someone else makes at a VMID ECM once
used is not treated as ECM's. Discovery calls `mark_tf_managed` after each Proxmox sync, because created machines
only appear in the inventory then, and a destroy checks `foreign_machines` first (ARCHITECTURE section 4: destroy
is allowed only on resources with tf_managed true).

This module reads only the models, so discovery and the operations can both use it.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Operation, Vm

CREATE = "tf.create"
DESTROY = "tf.destroy"
UPDATE = "tf.update"
_NODE = re.compile(r'module\.node\["([^"]+)"\]')


def torn_down(db: Session, create_op_id: str) -> bool:
    """True once a destroy that was started for this create has succeeded."""
    return bool(db.scalar(select(Operation.id).where(
        Operation.parent_op_id == create_op_id, Operation.kind == DESTROY, Operation.state == "succeeded")))


def created_machines(db: Session) -> set[tuple[str, int, str]]:
    """(Proxmox connection, VMID, name) of every machine a real create left in Terraform state and nothing has torn
    down. Only machines named in the create's recorded state count, so a create that failed part-way claims just
    the VMs it actually made."""
    out: set[tuple[str, int, str]] = set()
    creates = db.scalars(select(Operation).where(Operation.kind.in_((CREATE, UPDATE)),
                                                 Operation.dry_run.is_(False))).all()
    for op in creates:
        params = op.params or {}
        # Only a change that added nodes makes machines, and once its cluster is gone (a teardown detaches the
        # operation) it makes none; a resize or a disk change names the same machines the create already did.
        if op.kind == UPDATE and ((params.get("change") or {}).get("kind") != "add_node" or op.cluster_id is None):
            continue
        conn_id, vm_ids = params.get("proxmox_connection_id"), params.get("vm_ids") or {}
        built = {m.group(1) for addr in (op.result or {}).get("resources_in_state") or []
                 if (m := _NODE.search(addr))}
        if not conn_id or not built or (op.kind == CREATE and torn_down(db, op.id)):
            continue
        out |= {(conn_id, int(vm_ids[name]), name) for name in built if name in vm_ids}
    return out - removed_machines(db)


def removed_machines(db: Session) -> set[tuple[str, int, str]]:
    """(Proxmox connection, VMID, name) of every machine a change that removed nodes has destroyed. Terraform's apply
    is what destroys them, so a removal whose apply succeeded counts even if a later step failed. They stop being ECM's
    so a stranger's VM that is later given one of those VMIDs and names is not taken for one of ours."""
    out: set[tuple[str, int, str]] = set()
    for op in db.scalars(select(Operation).where(Operation.kind == UPDATE, Operation.dry_run.is_(False))).all():
        params = op.params or {}
        change = params.get("change") or {}
        if change.get("kind") != "remove_nodes" or not (op.result or {}).get("ok"):
            continue
        gone = {m.group(1) for addr in (op.result or {}).get("resources_in_state") or [] if (m := _NODE.search(addr))}
        conn_id = params.get("proxmox_connection_id")
        out |= {(conn_id, int(info["vm_id"]), name) for name, info in (change.get("nodes") or {}).items()
                if conn_id and name not in gone}
    return out


def mark_tf_managed(db: Session, connection_id: str) -> int:
    """Set tf_managed on the inventory rows that are machines ECM created. It only ever sets the flag, so it does
    not undo a mark made some other way (adoption, later). Returns how many rows changed; the caller commits."""
    wanted = {(vmid, name) for conn, vmid, name in created_machines(db) if conn == connection_id}
    if not wanted:
        return 0
    rows = db.scalars(select(Vm).where(Vm.connection_id == connection_id,
                                       Vm.vmid.in_({vmid for vmid, _ in wanted}))).all()
    changed = 0
    for row in rows:
        if (row.vmid, row.name) in wanted and not row.tf_managed:
            row.tf_managed = True
            changed += 1
    return changed


def foreign_machines(db: Session, params: dict) -> list[str]:
    """The machines at a create's VMIDs that are not ECM's, as "VMID (name)", or [] when a destroy may go ahead.

    A VMID with no inventory row is fine: the machine is already gone, or has not been seen yet, and Terraform
    only ever destroys what its own state recorded. A row is foreign when its name is not the create's name for
    that VMID, or when it carries the right name but no create of ECM's recorded it. The flag is brought up to date
    from the records first, so a destroy right after a create does not wait for the next sync."""
    conn_id = params.get("proxmox_connection_id")
    if conn_id:
        mark_tf_managed(db, conn_id)
        db.flush()
    out: list[str] = []
    vm_ids = dict(params.get("vm_ids") or {})
    change = params.get("change") or {}
    if change.get("kind") == "remove_nodes":
        # The nodes being removed are no longer in the parameters, but they are the machines this change touches.
        vm_ids.update({name: info["vm_id"] for name, info in (change.get("nodes") or {}).items()})
    for name, vmid in vm_ids.items():
        row = db.scalar(select(Vm).where(Vm.connection_id == conn_id, Vm.vmid == int(vmid)))
        if row is not None and (row.name != name or not row.tf_managed):
            out.append(f"{row.vmid} ({row.name})")
    return out
