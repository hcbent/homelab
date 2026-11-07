"""Render the Ansible inventory for one run. Pure: no files written, no process run (see ephemeral_inventory).

The inventory carries everything the roles need that is NOT secret. The cluster CA and the elastic password are
never rendered here: the runner hands them to Ansible as extra vars, so they cannot end up in an inventory file.

Rules this module owns (ARCHITECTURE section 6, CLAUDE.md conventions):
  * es_node_roles is absent for default roles, [] for coordinating-only, a sorted list for custom roles. The
    values come from desired/roles.py, so the rule lives in one place.
  * es_initial_master_nodes is present only for a `create` of a cluster that has never bootstrapped.
  * Nothing here can reach Proxmox, Elasticsearch or a VM.
"""
import ipaddress
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from app.desired.models import DesiredState
from app.desired.roles import OMIT, discovery_settings, render_node_roles

OperationKind = Literal["create", "converge", "restart", "add_node", "remove_drain", "remove_check"]

_SSH_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_SAFE_PATH = re.compile(r"^/[A-Za-z0-9_./-]+$")  # absolute, nothing a shell or ssh option could misread
_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")


class InventoryError(ValueError):
    """The inputs cannot produce a safe inventory. The message says what to fix."""


@dataclass
class InventoryInput:
    state: DesiredState
    addresses: dict[str, str]  # node name to IPv4 address
    operation_kind: OperationKind
    bootstrapped_at: datetime | None
    ssh_user: str
    ssh_key_path: str  # path inside the worker; the key itself is never read or copied here
    known_hosts_path: str  # a per-run file, so a rebuilt VM at a reused address never trips an old entry
    search_domain: str | None = None
    artifacts_dir: str | None = None  # where the CA and the API key are handed back to ECM
    # A rolling restart reaches each machine through Proxmox, so it needs each node's host and VMID.
    vm_ids: dict[str, int] | None = None
    placement: dict[str, str] | None = None
    # Adding nodes: which of the nodes are the new ones. Only they are prepared, given a certificate and started.
    new_nodes: list[str] | None = None
    # Removing nodes: the ones going. They are not in `state`, which is what remains; the playbooks run on the worker and
    # ask the cluster about them by name.
    removing: list[str] | None = None


def _check(inp: InventoryInput) -> None:
    if not _SSH_USER.match(inp.ssh_user):
        raise InventoryError("ssh_user must be a plain Unix user name")
    for what, path in (("ssh_key_path", inp.ssh_key_path), ("known_hosts_path", inp.known_hosts_path),
                       ("artifacts_dir", inp.artifacts_dir)):
        if path is None and what == "artifacts_dir":
            continue
        if not _SAFE_PATH.match(path) or ".." in path.split("/"):
            raise InventoryError(f"{what} must be an absolute path of letters, digits and _ . / - only")
    if inp.search_domain is not None and not _DOMAIN.match(inp.search_domain):
        raise InventoryError("search_domain is not a valid DNS domain")
    if inp.operation_kind == "restart":
        if inp.bootstrapped_at is None:
            raise InventoryError("a rolling restart is for a cluster that has bootstrapped")
        for what, mapping in (("vm_ids", inp.vm_ids), ("placement", inp.placement)):
            gaps = sorted(n.name for n in inp.state.nodes if not mapping or n.name not in mapping)
            if gaps:
                raise InventoryError(f"a rolling restart needs {what} for every node; missing: {', '.join(gaps)}")
    if inp.operation_kind == "add_node":
        if inp.bootstrapped_at is None:
            raise InventoryError("nodes are added to a cluster that has bootstrapped")
        known = {n.name for n in inp.state.nodes}
        if not inp.new_nodes or set(inp.new_nodes) - known:
            raise InventoryError("add_node needs the names of the new nodes, and each must be a node of the cluster")
        if known <= set(inp.new_nodes):
            raise InventoryError("a cluster cannot be made of only new nodes: use a create")
        if not any(n.is_electable and n.name not in inp.new_nodes for n in inp.state.nodes):
            raise InventoryError("the cluster has no existing node that can sign the new nodes' certificates")
    if inp.operation_kind in ("remove_drain", "remove_check"):
        if inp.bootstrapped_at is None:
            raise InventoryError("nodes are removed from a cluster that has bootstrapped")
        if not inp.removing:
            raise InventoryError("removing nodes needs the names of the nodes that are going")
        still = sorted(set(inp.removing) & {n.name for n in inp.state.nodes})
        if still:
            raise InventoryError(f"the nodes being removed must not be in the state that remains: {', '.join(still)}")
        if len(inp.state.nodes) < 2:
            raise InventoryError("a cluster cannot be removed down to a single node")
    if inp.operation_kind == "create" and inp.bootstrapped_at is not None:
        raise InventoryError("this cluster has already bootstrapped; a create would re-render "
                             "cluster.initial_master_nodes and could split it. Use converge.")
    names = [n.name for n in inp.state.nodes]
    missing = [n for n in names if n not in inp.addresses]
    extra = sorted(set(inp.addresses) - set(names))
    if missing:
        raise InventoryError(f"no address for node(s): {', '.join(missing)}")
    if extra:
        raise InventoryError(f"addresses for unknown node(s): {', '.join(extra)}")
    for name, addr in inp.addresses.items():
        try:
            ipaddress.IPv4Address(addr)
        except ValueError as e:
            raise InventoryError(f"address for {name} is not an IPv4 address: {addr!r}") from e
    if len(set(inp.addresses.values())) != len(inp.addresses):
        raise InventoryError("node addresses must be unique")


def render_inventory(inp: InventoryInput) -> dict:
    _check(inp)
    state = inp.state
    creating_first_time = inp.operation_kind == "create" and inp.bootstrapped_at is None

    new = set(inp.new_nodes or [])
    electable = [n for n in state.nodes if n.is_electable and n.name not in new]  # an existing node signs certificates
    master_eligible = state.master_eligible_nodes
    discovery = discovery_settings(state, operation_kind=inp.operation_kind,
                                   bootstrapped_at=inp.bootstrapped_at)

    cluster_vars: dict = {
        "ansible_user": inp.ssh_user,
        "ansible_ssh_private_key_file": inp.ssh_key_path,
        # accept-new records a host on first contact and then refuses a changed key, against a per-run file.
        "ansible_ssh_common_args": ("-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new "
                                    f"-o UserKnownHostsFile={inp.known_hosts_path}"),
        "es_operation": inp.operation_kind,
        "es_version": state.version,
        "es_cluster_name": state.name,
        "es_single_node": state.is_single_node,
        # Seed hosts are addresses, not names: the DNS records for a new cluster are a manual, separate job,
        # so a name may not resolve yet. node.name still uses the name, which initial_master_nodes must match.
        "es_seed_hosts": ([] if state.is_single_node
                          else [inp.addresses[n.name] for n in master_eligible]),
        "es_expected_nodes": len(state.nodes),
        "es_expected_status": "yellow" if state.is_single_node else "green",
        "es_ca_host": electable[0].name,
        "es_first_start": creating_first_time,
        # A create starts nodes that are not running yet. Anything else must never restart a live cluster
        # on its own: ECM's lifecycle procedures own rolling restarts.
        "es_allow_restart": inp.operation_kind == "create",
    }
    if "cluster.initial_master_nodes" in discovery:
        cluster_vars["es_initial_master_nodes"] = discovery["cluster.initial_master_nodes"]
    if inp.removing:
        cluster_vars["es_removing"] = sorted(inp.removing)
    if inp.artifacts_dir is not None:
        cluster_vars["es_artifacts_dir"] = inp.artifacts_dir

    hosts: dict[str, dict] = {}
    for node in state.nodes:
        address = inp.addresses[node.name]
        dns = [node.name] + ([f"{node.name}.{inp.search_domain}"] if inp.search_domain else [])
        host: dict = {
            "ansible_host": address,
            "es_node_name": node.name,
            "es_node_ip": address,
            "es_dns_names": dns,
            "es_heap_mb": node.effective_heap_mb,
            "es_extra_settings": dict(sorted(node.extra_settings.items())),
        }
        roles = render_node_roles(node)
        if roles is not OMIT:
            host["es_node_roles"] = roles
        if node.data_disk_gb is not None:
            host["es_data_disk_gb"] = node.data_disk_gb
        if inp.operation_kind == "add_node" and node.name in inp.new_nodes:
            host["es_start_node"] = True        # a node that is not running yet is started; the others are left alone
        if inp.operation_kind == "restart":
            # The order a rolling restart goes in: nodes that only route requests, then data nodes, then the
            # master-eligible nodes (the elected master last of those, which only the running cluster knows).
            order = "master" if node.is_master_eligible else ("data" if node.effective_roles else "coordinating")
            host.update({"es_pve_node": inp.placement[node.name], "es_vmid": int(inp.vm_ids[node.name]),
                         "es_desired_cores": node.cores, "es_desired_ram_mb": node.ram_mb,
                         "es_restart_class": order})
        hosts[node.name] = host

    children: dict = {
        "es_nodes": {"hosts": hosts},
        "es_bootstrap": {"hosts": {electable[0].name: {}}},
    }
    if new:
        children["es_new_nodes"] = {"hosts": {name: {} for name in sorted(new)}}
    return {"all": {"vars": cluster_vars, "children": children}}


def inventory_json(inp: InventoryInput) -> str:
    """Byte-identical for identical inputs."""
    return json.dumps(render_inventory(inp), indent=2, sort_keys=True) + "\n"


@contextmanager
def ephemeral_inventory(inp: InventoryInput, *, parent: str | None = None) -> Iterator[Path]:
    """Write the inventory into a fresh 0700 directory, yield its path, and delete the directory afterwards."""
    text = inventory_json(inp)  # render first, so a bad input leaves nothing on disk
    root = Path(tempfile.mkdtemp(prefix="ecm-inventory-", dir=parent))  # mkdtemp creates it 0700
    try:
        os.chmod(root, 0o700)
        path = root / "inventory.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        yield path
    finally:
        shutil.rmtree(root, ignore_errors=True)
