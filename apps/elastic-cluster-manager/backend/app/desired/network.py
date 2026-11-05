"""Network profiles and static address allocation for new nodes.

A profile describes one network (bridge, VLAN, subnet, gateway, DNS) and the pool of addresses ECM may hand out.
The pool must be a range the DHCP server never serves; ECM cannot check that, so the range is configuration the
operator owns.

Allocation is pure and deterministic. The caller supplies every address already in use (ECM's own allocations,
addresses seen on Proxmox VMs, addresses reported by Elasticsearch nodes), so this module needs no database.
IPv4 only.
"""
import ipaddress
import re
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import NodeSpec

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,38}[a-z0-9]$")
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class AllocationError(Exception):
    """An address cannot be allocated. The message says why and what to change."""


def _v4(text: str, what: str) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(text)
    except ValueError as exc:
        raise ValueError(f"{what} must be an IPv4 address, got {text!r}") from exc


class NetworkProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    bridge: str = "vmbr0"
    vlan: int | None = Field(default=None, ge=1, le=4094)
    cidr: str
    gateway: str
    dns: list[str] = Field(default_factory=list)
    search_domain: str | None = None
    range_start: str
    range_end: str
    # Optional: the addresses the DHCP server hands out. When set, the allocation range must stay clear of it.
    dhcp_start: str | None = None
    dhcp_end: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError("must be 2-40 characters: lowercase letters, digits and hyphens")
        return v

    @field_validator("search_domain")
    @classmethod
    def _domain(cls, v: str | None) -> str | None:
        if v is not None and not _DOMAIN_RE.match(v):
            raise ValueError("must be a valid DNS domain such as lab.example.org")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "NetworkProfile":
        try:
            net = ipaddress.IPv4Network(self.cidr, strict=True)
        except ValueError as exc:
            raise ValueError(f"cidr must be an IPv4 network such as 192.0.2.0/24: {exc}") from exc
        if net.prefixlen > 29:
            raise ValueError("the network is too small; use a /29 or larger")
        gw = _v4(self.gateway, "gateway")
        start, end = _v4(self.range_start, "range_start"), _v4(self.range_end, "range_end")
        dns = [_v4(d, "dns") for d in self.dns]

        if gw not in net or gw in (net.network_address, net.broadcast_address):
            raise ValueError(f"gateway {gw} must be a host address inside {net}")
        for what, addr in (("range_start", start), ("range_end", end)):
            if addr not in net or addr in (net.network_address, net.broadcast_address):
                raise ValueError(f"{what} {addr} must be a host address inside {net}")
        if start > end:
            raise ValueError("range_start must not be after range_end")
        if start <= gw <= end:
            raise ValueError(f"the allocation range {start}-{end} must not include the gateway {gw}")
        for d in dns:
            if d in net and start <= d <= end:
                raise ValueError(f"the allocation range must not include the DNS server {d}")
        if (self.dhcp_start is None) != (self.dhcp_end is None):
            raise ValueError("set both dhcp_start and dhcp_end, or neither")
        if self.dhcp_start is not None and self.dhcp_end is not None:
            ds, de = _v4(self.dhcp_start, "dhcp_start"), _v4(self.dhcp_end, "dhcp_end")
            for what, addr in (("dhcp_start", ds), ("dhcp_end", de)):
                if addr not in net:
                    raise ValueError(f"{what} {addr} must be inside {net}")
            if ds > de:
                raise ValueError("dhcp_start must not be after dhcp_end")
            if start <= de and ds <= end:
                raise ValueError(
                    f"the allocation range {start}-{end} overlaps the DHCP range {ds}-{de}; "
                    f"ECM would hand out addresses that DHCP may also assign")
        return self

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.IPv4Network(self.cidr)

    @property
    def pool_size(self) -> int:
        return int(ipaddress.IPv4Address(self.range_end)) - int(ipaddress.IPv4Address(self.range_start)) + 1


def _pool(profile: NetworkProfile) -> Iterable[ipaddress.IPv4Address]:
    start, end = int(ipaddress.IPv4Address(profile.range_start)), int(ipaddress.IPv4Address(profile.range_end))
    for n in range(start, end + 1):
        yield ipaddress.IPv4Address(n)


def allocate_addresses(
    profile: NetworkProfile, nodes: list[NodeSpec], in_use: Iterable[str] = ()
) -> dict[str, str]:
    """Give every node an address, returning {node name: ip} in node order.

    Nodes with a fixed ip keep it. It must be inside the subnet, must not be the gateway, network or broadcast
    address, and must not already be in use. Other nodes get the lowest free address in the pool.
    """
    net = profile.network
    reserved = {net.network_address, net.broadcast_address, ipaddress.IPv4Address(profile.gateway)}
    dhcp = None
    if profile.dhcp_start and profile.dhcp_end:
        dhcp = (ipaddress.IPv4Address(profile.dhcp_start), ipaddress.IPv4Address(profile.dhcp_end))
    taken = {ipaddress.IPv4Address(a) for a in in_use if _is_v4(a)}
    result: dict[str, ipaddress.IPv4Address] = {}

    for node in nodes:
        if node.ip is None:
            continue
        addr = ipaddress.IPv4Address(node.ip)
        if addr not in net:
            raise AllocationError(f"{node.name}: {addr} is outside the profile network {net}")
        if addr in reserved:
            raise AllocationError(f"{node.name}: {addr} is the network, broadcast or gateway address")
        if dhcp and dhcp[0] <= addr <= dhcp[1]:
            raise AllocationError(f"{node.name}: {addr} is inside the DHCP range "
                                  f"{dhcp[0]}-{dhcp[1]} and could be handed to another device")
        if addr in taken:
            raise AllocationError(f"{node.name}: {addr} is already in use")
        taken.add(addr)
        result[node.name] = addr

    free = (a for a in _pool(profile) if a not in taken and a not in reserved)
    for node in nodes:
        if node.ip is not None:
            continue
        addr = next(free, None)
        if addr is None:
            needed = sum(1 for n in nodes if n.ip is None)
            raise AllocationError(
                f"the address range {profile.range_start}-{profile.range_end} has no free address left "
                f"for {node.name} ({needed} needed, {profile.pool_size} in the pool). "
                f"Free some addresses or widen the range")
        result[node.name] = addr
        taken.add(addr)

    return {n.name: str(result[n.name]) for n in nodes}


def _is_v4(text: str) -> bool:
    try:
        ipaddress.IPv4Address(text)
    except ValueError:
        return False
    return True


def cloud_init_ipv4(profile: NetworkProfile, ip: str) -> dict:
    """The values Terraform's cloud-init block needs for one node."""
    return {
        "address": f"{ip}/{profile.network.prefixlen}",
        "gateway": profile.gateway,
        "dns": list(profile.dns),
        "search_domain": profile.search_domain,
        "bridge": profile.bridge,
        "vlan": profile.vlan,
    }
