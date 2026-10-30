"""Link Elasticsearch nodes to Proxmox VMs using verified evidence only.

confidence:
  verified  exactly one VM reports the node's address (guest agent or static cloud-init IP)
  probable  no address match, but exactly one VM has the same name. Never grants ownership.
  unlinked  nothing matches, or the evidence is ambiguous (several VMs claim the address)
"""
from dataclasses import dataclass, field


@dataclass
class VmView:
    key: str  # opaque id, e.g. the vms.id
    name: str | None
    ips: list[dict]  # [{"ip", "source"}]
    is_template: bool = False


@dataclass
class Link:
    vm_key: str | None
    confidence: str
    evidence: dict = field(default_factory=dict)


def link_node(node_ip: str | None, node_host: str | None, node_name: str,
              vms: list[VmView]) -> Link:
    candidates = [v for v in vms if not v.is_template]
    addrs = {a for a in (node_ip, node_host) if a}
    by_addr = []
    for v in candidates:
        for rec in v.ips:
            if rec["ip"] in addrs:
                by_addr.append((v, rec))
                break
    if len(by_addr) == 1:
        v, rec = by_addr[0]
        return Link(v.key, "verified", {"method": "ip", "ip": rec["ip"], "source": rec["source"]})
    if len(by_addr) > 1:
        return Link(None, "unlinked", {"reason": "ambiguous", "address": sorted(addrs),
                                       "candidates": sorted(v.name or v.key for v, _ in by_addr)})
    same_name = [v for v in candidates if v.name and v.name == node_name]
    if len(same_name) == 1:
        return Link(same_name[0].key, "probable",
                    {"method": "name", "note": "no address match; name match only"})
    return Link(None, "unlinked", {"reason": "no matching VM"})
