"""Read-only Proxmox VE API client and normalisation of what it reports."""
import re
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from app.crypto import register_secret
from app.discovery.http import DiscoveryError, InsufficientRights, build_client, get_json

_DISK_KEY = re.compile(r"^(scsi|virtio|sata|ide)\d+$")
_NET_KEY = re.compile(r"^net\d+$")
_IPCONFIG_KEY = re.compile(r"^ipconfig\d+$")
_SECRET_KEYS = ("cipassword", "sshkeys", "password")  # never stored
_POOL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


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

    def permissions(self) -> dict:
        """What this token may do, as {path: {privilege: 1}}. Always allowed, and read-only."""
        return self._get("/access/permissions", "read the token's permissions")

    def pool_member_ids(self, pool_id: str) -> set[int]:
        """VMIDs of the VMs in a pool. Needs Pool.Audit on it."""
        if not _POOL_ID.match(pool_id):
            raise DiscoveryError(f"{pool_id!r} is not a valid pool id")
        data = self._get(f"/pools/{pool_id}", f"read pool {pool_id}")
        members = data.get("members", []) if isinstance(data, dict) else []
        return {int(m["vmid"]) for m in members if isinstance(m, dict) and m.get("vmid") is not None}

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


def has_privilege(perms: dict, path: str, privilege: str) -> bool:
    """Whether the token holds a privilege on a path.

    Proxmox reports the effective privileges per path. A path that is listed is authoritative, so an explicit
    entry on /pool/ecm replaces what / grants (it does not add to it). Only a path that is not listed falls back
    to its nearest listed parent.
    """
    parts = [p for p in path.strip("/").split("/") if p]
    for depth in range(len(parts), -1, -1):
        here = "/" + "/".join(parts[:depth])
        if here in perms:
            return privilege in (perms[here] or {})
    return False


# Rights that let a token change permissions or system settings. Terraform needs none of them.
_TOO_BROAD = ("Permissions.Modify", "User.Modify", "Sys.Modify")


def vm_rights_outside_the_pool(perms: dict, pool_id: str, members: Callable[[], set[int]] | None = None) -> list[str]:
    """Paths other than the pool where the token can create VMs (VM.Allocate).

    A VM in the pool shows up at /vms/<id> with the pool's rights, so those are fine. The pool's members are only
    fetched, through `members`, when a per-VM path has to be judged; if they cannot be read, per-VM paths are
    ignored rather than guessed at, so structural grants (/, /pool, another pool, a storage) are what get flagged.
    """
    inside = f"/pool/{pool_id}"
    paths = sorted(p for p, privs in perms.items()
                   if "VM.Allocate" in (privs or {}) and p != inside and not p.startswith(inside + "/"))
    per_vm = [p for p in paths if re.fullmatch(r"/vms/\d+", p)]
    outside = [p for p in paths if p not in per_vm]
    if per_vm and members is not None:
        try:
            member_ids = members()
        except DiscoveryError:
            return outside
        outside += [p for p in per_vm if int(p.rsplit("/", 1)[1]) not in member_ids]
    return sorted(outside)


def check_terraform_rights(perms: dict, pool_id: str, datastore: str,
                           members: Callable[[], set[int]] | None = None) -> tuple[list[str], list[str]]:
    """(problems that make the token unusable for creating VMs, advice that does not block it).

    The one hard requirement is creating VMs in the pool, which is where ECM puts everything it makes (a token
    with rights on single VMIDs loses them when a VM is destroyed; see spike/FINDINGS.md). The rest is advice,
    because the exact set Terraform needs depends on the VM configuration and Proxmox version.
    """
    problems: list[str] = []
    advice: list[str] = []
    if not has_privilege(perms, f"/pool/{pool_id}", "VM.Allocate"):
        problems.append(f"it cannot create VMs in the pool '{pool_id}' (no VM.Allocate on /pool/{pool_id}); "
                        "check that the pool exists and the token has rights on it")
    if not has_privilege(perms, f"/storage/{datastore}", "Datastore.AllocateSpace"):
        advice.append(f"it has no Datastore.AllocateSpace on /storage/{datastore}, so creating disks there will fail")
    outside = vm_rights_outside_the_pool(perms, pool_id, members)
    if outside:
        shown = ", ".join(outside[:5]) + (f" and {len(outside) - 5} more" if len(outside) > 5 else "")
        advice.append(f"it can also create VMs outside the pool '{pool_id}' (VM.Allocate on {shown}); a token "
                      "limited to the pool is safer")
    broad = [p for p in _TOO_BROAD if has_privilege(perms, "/", p)]
    if broad:
        advice.append(f"it can also change permissions or system settings ({', '.join(broad)}); Terraform does not "
                      "need that, so a narrower token is safer")
    return problems, advice


def preflight_problems(perms: dict, *, pool_id: str, datastore: str, template_vmid: int | None,
                       creating: bool, resizing: bool = False, restarting: bool = False) -> list[str]:
    """What the token lacks for the operation about to be planned. Empty means it can proceed.

    A plan only reads, so it cannot notice lost write rights; an apply would then fail part way and leave partial
    resources. Creating needs VM.Allocate on the pool, space on the datastore and VM.Clone on the template. Removing
    needs only VM.Allocate on the pool, so a teardown is not refused for rights it never uses.
    """
    problems: list[str] = []
    if restarting:
        # Restarting or starting a node only powers its VM off and on, so that is the one right it needs.
        if not has_privilege(perms, f"/pool/{pool_id}", "VM.PowerMgmt"):
            problems.append(f"no VM.PowerMgmt on /pool/{pool_id}, which restarting or starting a VM in it needs")
        return problems
    if resizing:
        # Changing a VM's CPU or memory, and the restart that applies it, are done on the VMs in the pool.
        for privilege in ("VM.Config.CPU", "VM.Config.Memory", "VM.PowerMgmt"):
            if not has_privilege(perms, f"/pool/{pool_id}", privilege):
                problems.append(f"no {privilege} on /pool/{pool_id}, which a resize needs on the VMs in it")
    if not has_privilege(perms, f"/pool/{pool_id}", "VM.Allocate"):
        problems.append(f"no VM.Allocate on /pool/{pool_id} (does the pool exist, and does the token have rights on it?)")
    if creating:
        if not has_privilege(perms, f"/storage/{datastore}", "Datastore.AllocateSpace"):
            problems.append(f"no Datastore.AllocateSpace on /storage/{datastore}")
        if template_vmid is not None and not has_privilege(perms, f"/vms/{template_vmid}", "VM.Clone"):
            problems.append(f"no VM.Clone on the template /vms/{template_vmid}")
    return problems


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
