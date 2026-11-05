"""Read-only Proxmox VE API client and normalisation of what it reports."""
import re
from dataclasses import dataclass, field

import httpx

from app.crypto import register_secret
from app.discovery.http import DiscoveryError, InsufficientRights, build_client, get_json

_DISK_KEY = re.compile(r"^(scsi|virtio|sata|ide)\d+$")
_NET_KEY = re.compile(r"^net\d+$")
_IPCONFIG_KEY = re.compile(r"^ipconfig\d+$")
_SECRET_KEYS = ("cipassword", "sshkeys", "password")  # never stored


class ProxmoxClient:
    def __init__(self, api_url: str, token_id: str, token_secret: str, *, verify: bool = True,
                 ca_pem: str | None = None, transport: httpx.BaseTransport | None = None):
        register_secret(token_secret)
        self._http = build_client(
            api_url.rstrip("/") + "/api2/json",
            {"Authorization": f"PVEAPIToken={token_id}={token_secret}"},
            verify=verify, ca_pem=ca_pem, transport=transport)

    def _get(self, path: str, what: str):
        return get_json(self._http, path, what)["data"]

    def nodes(self) -> list[dict]:
        return self._get("/nodes", "list nodes")

    def vms(self, node: str) -> list[dict]:
        return self._get(f"/nodes/{node}/qemu", f"list VMs on {node}")

    def vm_config(self, node: str, vmid: int) -> dict:
        return self._get(f"/nodes/{node}/qemu/{vmid}/config", f"VM {vmid} config")

    def vm_agent_interfaces(self, node: str, vmid: int) -> list[dict]:
        """Guest-agent interfaces. Empty when the agent isn't running (Proxmox answers 500)."""
        try:
            data = self._get(f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces",
                             f"VM {vmid} agent")
        except DiscoveryError:
            return []
        return data.get("result", []) if isinstance(data, dict) else []

    def storages(self, node: str) -> list[dict]:
        return self._get(f"/nodes/{node}/storage", f"storage on {node}")

    def networks(self, node: str) -> list[dict]:
        return self._get(f"/nodes/{node}/network", f"network on {node}")


@dataclass
class VmInfo:
    pve_node: str
    vmid: int
    name: str | None
    status: str | None
    is_template: bool
    cpu_cores: int | None
    memory_mb: int | None
    disks: list[dict]
    nets: list[dict]
    ips: list[dict]  # [{"ip", "source": "guest-agent"|"cloud-init"}]
    usage: dict
    config: dict


@dataclass
class InfraSnapshot:
    nodes: list[dict] = field(default_factory=list)
    vms: list[VmInfo] = field(default_factory=list)
    storages: list[dict] = field(default_factory=list)  # each has "node"
    networks: dict[str, list[dict]] = field(default_factory=dict)  # node -> devices


def _kv(value: str) -> dict:
    out = {}
    for i, part in enumerate(value.split(",")):
        k, sep, v = part.partition("=")
        out[k if sep else f"_{i}"] = v if sep else k
    return out


def _size_gb(size: str | None) -> float | None:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KMGT])", size or "")
    if not m:
        return None
    return float(m.group(1)) * {"K": 1 / 1024**2, "M": 1 / 1024, "G": 1, "T": 1024}[m.group(2)]


def parse_disks(cfg: dict) -> list[dict]:
    disks = []
    for key, val in sorted(cfg.items()):
        if not _DISK_KEY.match(key) or not isinstance(val, str):
            continue
        parts = _kv(val)
        if parts.get("media") == "cdrom" or "cloudinit" in val.split(",")[0]:
            continue
        first = val.split(",")[0]
        storage = first.split(":")[0] if ":" in first else None
        disks.append({"slot": key, "storage": storage, "volume": first,
                      "size_gb": _size_gb(parts.get("size"))})
    return disks


def parse_nets(cfg: dict) -> list[dict]:
    nets = []
    for key, val in sorted(cfg.items()):
        if _NET_KEY.match(key) and isinstance(val, str):
            parts = _kv(val)
            model = next((k for k in parts if k in ("virtio", "e1000", "rtl8139", "vmxnet3")), None)
            nets.append({"slot": key, "model": model, "mac": parts.get(model) if model else None,
                         "bridge": parts.get("bridge"),
                         "vlan": int(parts["tag"]) if "tag" in parts else None})
    return nets


def static_ips(cfg: dict) -> list[str]:
    ips = []
    for key, val in cfg.items():
        if _IPCONFIG_KEY.match(key) and isinstance(val, str):
            ip = _kv(val).get("ip", "")
            if ip and ip not in ("dhcp", "manual"):
                ips.append(ip.split("/")[0])
    return ips


def _usable(ip: str) -> bool:
    return not (ip.startswith(("127.", "169.254.", "fe80:")) or ip == "::1")


# Interfaces created by container runtimes and hypervisors inside a guest. Their addresses (for example the
# 172.17.0.1 gateway of docker0) describe an internal network, not the machine, so they must never be used as
# evidence that a VM runs a given Elasticsearch node. Matching on the interface name avoids assuming an
# address range, since a LAN may legitimately use 172.16.0.0/12.
_VIRTUAL_IFACE_PREFIXES = ("lo", "docker", "br-", "veth", "virbr", "cni", "flannel", "cali", "cilium",
                           "podman", "weave", "lxcbr", "kube-", "tunl")


def is_virtual_interface(name: str | None) -> bool:
    n = (name or "").lower()
    return n == "lo" or n.startswith(_VIRTUAL_IFACE_PREFIXES[1:])


def check_node_usage(nodes: list[dict]) -> None:
    """Refuse a token that cannot audit the nodes.

    For a node the token has no Sys.Audit right on, Proxmox still lists the node and its status but leaves out its
    CPU and memory. If that holds for every online node, the token cannot be used for discovery or placement, and a
    sync would replace the stored picture with a nearly empty one. A single node without figures is tolerated: it may
    simply have just booted.
    """
    online = [n for n in nodes if n.get("status") == "online"]
    if online and not any(n.get("maxcpu") is not None and n.get("maxmem") is not None for n in online):
        raise InsufficientRights(
            "Proxmox reports no CPU or memory for any online node, so this API token cannot audit them; it needs "
            "the Sys.Audit privilege, for example the PVEAuditor role on /")


def collect(client: ProxmoxClient) -> InfraSnapshot:
    snap = InfraSnapshot()
    snap.nodes = client.nodes()
    check_node_usage(snap.nodes)  # before anything is stored: a refused sync leaves the last good data alone
    for n in snap.nodes:
        node = n["node"]
        if n.get("status") != "online":
            continue
        snap.networks[node] = client.networks(node)
        snap.storages += [{**s, "node": node} for s in client.storages(node)]
        for v in client.vms(node):
            vmid = int(v["vmid"])
            cfg = {k: val for k, val in client.vm_config(node, vmid).items()
                   if not any(s in k.lower() for s in _SECRET_KEYS)}
            is_template = bool(v.get("template"))
            ips: dict[str, str] = {ip: "cloud-init" for ip in static_ips(cfg)}
            if v.get("status") == "running" and not is_template:
                for iface in client.vm_agent_interfaces(node, vmid):
                    if is_virtual_interface(iface.get("name")):
                        continue
                    for a in iface.get("ip-addresses", []):
                        ip = a.get("ip-address", "")
                        if _usable(ip):
                            ips[ip] = "guest-agent"  # agent evidence outranks configuration
            cores = (int(cfg["cores"]) * int(cfg.get("sockets", 1))) if "cores" in cfg else None
            snap.vms.append(VmInfo(
                pve_node=node, vmid=vmid, name=v.get("name") or cfg.get("name"),
                status=v.get("status"), is_template=is_template, cpu_cores=cores,
                memory_mb=int(cfg["memory"]) if "memory" in cfg else None,
                disks=parse_disks(cfg), nets=parse_nets(cfg),
                ips=[{"ip": ip, "source": src} for ip, src in ips.items()],
                usage={k: v.get(k) for k in ("cpu", "mem", "maxmem", "maxdisk", "uptime")},
                config=cfg))
    return snap
