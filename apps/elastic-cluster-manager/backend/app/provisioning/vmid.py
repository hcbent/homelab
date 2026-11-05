"""Proxmox VMID allocation for new nodes."""
from collections.abc import Iterable

MIN_VMID = 100  # Proxmox does not accept lower IDs


class VmidError(Exception):
    """A VMID cannot be allocated. The message says why and what to change."""


def allocate_vmids(
    names: list[str], used: Iterable[int], start: int = 500, end: int = 599
) -> dict[str, int]:
    """Give each name the lowest free VMID in [start, end], in order.

    `used` must hold every VMID already taken on the Proxmox cluster, including stopped VMs and templates.
    Deterministic, so a plan generated from the same inputs is reproducible.
    """
    if start < MIN_VMID or end < start:
        raise VmidError(f"the VMID range {start}-{end} is invalid; it must start at {MIN_VMID} or higher")
    if len(set(names)) != len(names):
        raise VmidError("node names must be unique")
    taken = set(used)
    free = (n for n in range(start, end + 1) if n not in taken)
    result: dict[str, int] = {}
    for name in names:
        vmid = next(free, None)
        if vmid is None:
            raise VmidError(
                f"the VMID range {start}-{end} has no free ID left for {name} "
                f"({len(names)} needed). Free some IDs or widen the range")
        result[name] = vmid
    return result
