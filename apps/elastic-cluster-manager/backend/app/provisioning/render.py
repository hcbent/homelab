"""Render a Terraform workspace for creating a cluster. Pure: no files written, no process run.

Output is {relative path: file content}. Static HCL comes from hcl.py; everything specific to the cluster is
data in cluster.auto.tfvars.json, serialised with sorted keys so the same inputs always give byte-identical
output (and so a plan can be tied to the exact configuration that produced it).

This is a CREATE configuration. Adopting an existing VM needs a separate, generated configuration without a
clone block (see spike/FINDINGS.md).
"""
import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from app.desired.kibana import KibanaSpec
from app.desired.models import DesiredState
from app.desired.network import NetworkProfile, cloud_init_ipv4
from app.provisioning import hcl
from app.provisioning.vmid import MIN_VMID

_CLUSTER_ID = re.compile(r"^[a-f0-9]{8,32}$")
_PVE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_BRIDGE = re.compile(r"^[a-z][a-z0-9]{0,14}$")
_CPU_TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")  # host, x86-64-v2-AES, Skylake-Server, custom-x
MODULE_DIR = "modules/es_node"


class RenderError(ValueError):
    """The inputs cannot produce a safe configuration. The message says what to fix."""


@dataclass(frozen=True)
class TemplateRef:
    node_name: str
    vm_id: int


@dataclass
class RenderInput:
    cluster_id: str  # hex id; names the Postgres schema that holds the Terraform state
    state: DesiredState
    placement: dict[str, str]  # node name to Proxmox host
    addresses: dict[str, str]  # node name to IPv4 address
    vm_ids: dict[str, int]  # node name to VMID
    profile: NetworkProfile
    template: TemplateRef
    proxmox_endpoint: str
    proxmox_insecure: bool = False
    datastore_id: str = "tank"
    pool_id: str = "ecm"
    agent_enabled: bool = False
    cpu_type: str = "host"
    state_backend: Literal["pg", "local"] = "pg"
    # Kibana machines (docs/DESIGN_KIBANA.md). They are not Elasticsearch nodes, so they have their own list and are only merged into
    # the module's map here; every check above on placement, address and VMID covers the nodes alone.
    kibana: list[KibanaSpec] = field(default_factory=list)


def _check(inp: RenderInput) -> None:
    if not _CLUSTER_ID.match(inp.cluster_id):
        raise RenderError("cluster_id must be 8 to 32 lowercase hex characters")
    for what, value in (("pool_id", inp.pool_id), ("datastore_id", inp.datastore_id),
                        ("template host", inp.template.node_name)):
        if not _PVE_NAME.match(value):
            raise RenderError(f"{what} {value!r} is not a valid Proxmox name")
    if not _CPU_TYPE.match(inp.cpu_type):
        raise RenderError(f"cpu_type {inp.cpu_type!r} is not a valid Proxmox CPU type such as host or x86-64-v2-AES")
    if not _BRIDGE.match(inp.profile.bridge):
        raise RenderError(f"bridge {inp.profile.bridge!r} is not a valid Linux bridge name")
    url = urlparse(inp.proxmox_endpoint)
    if url.scheme != "https" or not url.hostname:
        raise RenderError("proxmox_endpoint must be an https URL")
    if inp.template.vm_id < MIN_VMID:
        raise RenderError(f"the template VMID must be {MIN_VMID} or higher")

    names = [n.name for n in inp.state.nodes]
    for what, mapping in (("placement", inp.placement), ("address", inp.addresses), ("VMID", inp.vm_ids)):
        missing = [n for n in names if n not in mapping]
        extra = sorted(set(mapping) - set(names))
        if missing:
            raise RenderError(f"no {what} for node(s): {', '.join(missing)}")
        if extra:
            raise RenderError(f"{what} given for unknown node(s): {', '.join(extra)}")
    for node, host in inp.placement.items():
        if not _PVE_NAME.match(host):
            raise RenderError(f"{node}: {host!r} is not a valid Proxmox host name")

    ids = list(inp.vm_ids.values())
    if len(set(ids)) != len(ids):
        raise RenderError("VMIDs must be unique")
    low = sorted(n for n, v in inp.vm_ids.items() if v < MIN_VMID)
    if low:
        raise RenderError(f"VMIDs must be {MIN_VMID} or higher: {', '.join(low)}")
    net = inp.profile.network
    for node, ip in inp.addresses.items():
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError as exc:
            raise RenderError(f"{node}: {ip!r} is not an IPv4 address") from exc
        if addr not in net:
            raise RenderError(f"{node}: {ip} is outside the profile network {net}")
    if len(set(inp.addresses.values())) != len(inp.addresses):
        raise RenderError("node addresses must be unique")
    _check_kibana(inp, net)


def _check_kibana(inp: RenderInput, net) -> None:
    """A Kibana machine shares the module's map with the nodes, so its name, VMID and address must not clash with theirs."""
    taken_names = {n.name for n in inp.state.nodes}
    taken_ids = set(inp.vm_ids.values())
    taken_addresses = set(inp.addresses.values())
    seen: set[str] = set()
    for k in inp.kibana:
        if k.name in taken_names or k.name in seen:
            raise RenderError(f"the Kibana machine {k.name} has the name of another machine in this cluster")
        seen.add(k.name)
        if not _PVE_NAME.match(k.host):
            raise RenderError(f"{k.name}: {k.host!r} is not a valid Proxmox host name")
        if k.vm_id < MIN_VMID:
            raise RenderError(f"the VMID of {k.name} must be {MIN_VMID} or higher")
        if k.vm_id in taken_ids:
            raise RenderError(f"the VMID of {k.name} ({k.vm_id}) is used by another machine in this cluster")
        taken_ids.add(k.vm_id)
        if ipaddress.IPv4Address(k.address) not in net:
            raise RenderError(f"{k.name}: {k.address} is outside the profile network {net}")
        if k.address in taken_addresses:
            raise RenderError(f"the address of {k.name} ({k.address}) is used by another machine in this cluster")
        taken_addresses.add(k.address)


def _tfvars(inp: RenderInput) -> dict:
    nodes = {}
    for node in inp.state.nodes:
        net = cloud_init_ipv4(inp.profile, inp.addresses[node.name])
        nodes[node.name] = {
            "node_name": inp.placement[node.name],
            "vm_id": inp.vm_ids[node.name],
            "cores": node.cores,
            "memory_mb": node.ram_mb,
            "os_disk_gb": node.os_disk_gb,
            "data_disk_gb": node.data_disk_gb,
            "address": net["address"],
            "gateway": net["gateway"],
        }
    for k in inp.kibana:
        net = cloud_init_ipv4(inp.profile, k.address)
        nodes[k.name] = {
            "node_name": k.host, "vm_id": k.vm_id, "cores": k.cores, "memory_mb": k.ram_mb, "os_disk_gb": k.os_disk_gb,
            "data_disk_gb": None, "address": net["address"], "gateway": net["gateway"],
        }
    return {
        "proxmox_endpoint": inp.proxmox_endpoint,
        "proxmox_insecure": inp.proxmox_insecure,
        "cluster_name": inp.state.name,
        "pool_id": inp.pool_id,
        "template": {"node_name": inp.template.node_name, "vm_id": inp.template.vm_id},
        "datastore_id": inp.datastore_id,
        "bridge": inp.profile.bridge,
        "vlan_id": inp.profile.vlan,
        "dns_servers": list(inp.profile.dns),
        "search_domain": inp.profile.search_domain,
        "agent_enabled": inp.agent_enabled,
        "cpu_type": inp.cpu_type,
        "nodes": nodes,
    }


def render_workspace(inp: RenderInput) -> dict[str, str]:
    """The files of the Terraform workspace for creating this cluster."""
    _check(inp)
    files = {
        "versions.tf": hcl.VERSIONS_TF,
        "variables.tf": hcl.VARIABLES_TF,
        "main.tf": hcl.MAIN_TF,
        "outputs.tf": hcl.OUTPUTS_TF,
        f"{MODULE_DIR}/main.tf": hcl.MODULE_MAIN_TF,
        f"{MODULE_DIR}/variables.tf": hcl.MODULE_VARIABLES_TF,
        f"{MODULE_DIR}/versions.tf": hcl.MODULE_VERSIONS_TF,
        f"{MODULE_DIR}/outputs.tf": hcl.MODULE_OUTPUTS_TF,
        "cluster.auto.tfvars.json": json.dumps(_tfvars(inp), indent=2, sort_keys=True) + "\n",
    }
    if inp.state_backend == "pg":
        files["backend.tf"] = hcl.BACKEND_PG_TF.format(schema=f"tf_{inp.cluster_id}")
    return dict(sorted(files.items()))


def config_digest(files: dict[str, str]) -> str:
    """A stable fingerprint of a rendered workspace, to tie a stored plan to the exact config behind it."""
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.encode())
        h.update(b"\0")
        h.update(files[path].encode())
        h.update(b"\0")
    return h.hexdigest()
