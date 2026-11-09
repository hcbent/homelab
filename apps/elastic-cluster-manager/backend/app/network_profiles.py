"""Stored network profiles: seeding, conversion to the validated model, and conflict detection."""
import ipaddress

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.desired.network import NetworkProfile
from app.models import Cluster, EsNode, NetworkProfileRow, Vm

# Seeded on first start so the allocator always has a profile. Everything here is editable in the UI.
DEFAULT_PROFILE = {
    "name": "default",
    "bridge": "vmbr0",
    "vlan": 10,
    "cidr": "192.168.10.0/24",
    "gateway": "192.168.10.1",
    "dns": ["192.168.10.1"],
    "search_domain": "lab.thewortmans.org",
    "range_start": "192.168.10.110",
    "range_end": "192.168.10.149",
    "dhcp_start": "192.168.10.150",
    "dhcp_end": "192.168.10.254",
}


def ensure_default(db: Session) -> None:
    """Create the default profile when none exist. Never overwrites what the user has edited."""
    if db.scalar(select(NetworkProfileRow.id).limit(1)) is None:
        db.add(NetworkProfileRow(**NetworkProfile(**DEFAULT_PROFILE).model_dump()))
        db.commit()


def to_domain(row: NetworkProfileRow) -> NetworkProfile:
    return NetworkProfile(
        name=row.name, bridge=row.bridge, vlan=row.vlan, cidr=row.cidr, gateway=row.gateway,
        dns=list(row.dns or []), search_domain=row.search_domain,
        range_start=row.range_start, range_end=row.range_end,
        dhcp_start=row.dhcp_start, dhcp_end=row.dhcp_end)


def addresses_in_use(db: Session) -> list[dict]:
    """Every address ECM has seen on a Proxmox VM or reported by an Elasticsearch node, and the address of every Kibana machine ECM recorded.
    That last source is needed because a Kibana machine is not an Elasticsearch node and its VM has no guest agent, so neither of the others
    ever reports it."""
    found: dict[str, dict] = {}
    for vm in db.scalars(select(Vm).where(Vm.is_template.is_(False))):
        for rec in vm.ips or []:
            found.setdefault(rec["ip"], {"ip": rec["ip"], "source": "proxmox",
                                         "name": vm.name or f"VM {vm.vmid}"})
    for node in db.scalars(select(EsNode)):
        if node.ip:
            found.setdefault(node.ip, {"ip": node.ip, "source": "elasticsearch", "name": node.name})
    for desired in db.scalars(select(Cluster.desired).where(Cluster.desired.is_not(None))):
        for k in (desired or {}).get("kibana") or []:
            found.setdefault(k["address"], {"ip": k["address"], "source": "ecm", "name": k["name"]})
    return list(found.values())


def conflicts_in_range(profile: NetworkProfile, in_use: list[dict]) -> list[dict]:
    """In-use addresses that fall inside the profile's allocation range, lowest first."""
    start = ipaddress.IPv4Address(profile.range_start)
    end = ipaddress.IPv4Address(profile.range_end)
    hits = []
    for item in in_use:
        try:
            addr = ipaddress.IPv4Address(item["ip"])
        except ValueError:
            continue
        if start <= addr <= end:
            hits.append((addr, item))
    return [item for _, item in sorted(hits, key=lambda x: x[0])]
