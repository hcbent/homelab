"""Desired-state models for an ECM-managed Elasticsearch cluster.

Pure data and validation: no database, no Proxmox, no Terraform. Everything the later phases render
(Terraform variables, Ansible inventory, elasticsearch.yml) is derived from these models.

Role rules (ARCHITECTURE section 6):
  default       node.roles is OMITTED, so the node gets Elasticsearch's default roles
  coordinating  node.roles is an EMPTY list
  custom        node.roles is an explicit, non-empty list
"""
import ipaddress
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Roles Elasticsearch accepts in node.roles.
VALID_ROLES = frozenset({
    "master", "voting_only", "data", "data_content", "data_hot", "data_warm", "data_cold",
    "data_frozen", "ingest", "ml", "remote_cluster_client", "transform",
})
DATA_ROLES = frozenset({"data", "data_content", "data_hot", "data_warm", "data_cold", "data_frozen"})
# What a node with no node.roles setting gets. voting_only is never a default role.
DEFAULT_ROLES = VALID_ROLES - {"voting_only"}

# Settings ECM renders itself. A user-supplied value would fight the generated configuration.
MANAGED_SETTINGS = frozenset({
    "node.roles", "node.name", "cluster.name", "cluster.initial_master_nodes",
    "discovery.seed_hosts", "discovery.type", "path.data", "path.logs", "network.host",
    "network.publish_host", "xpack.security.enabled", "xpack.security.transport.ssl.enabled",
})

MIN_HEAP_MB = 512
MAX_HEAP_MB = 31 * 1024  # stay under the compressed-oops threshold
MAX_NODES = 50

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,38}[a-z0-9]$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class RolesMode(StrEnum):
    default = "default"
    coordinating = "coordinating"
    custom = "custom"


class TopologyPreset(StrEnum):
    single_node = "single_node"
    three_node = "three_node"
    dedicated_masters = "dedicated_masters"
    custom = "custom"


def default_heap_mb(ram_mb: int) -> int:
    """Heap is half of RAM, capped below the compressed-oops threshold."""
    return min(ram_mb // 2, MAX_HEAP_MB)


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    roles_mode: RolesMode = RolesMode.default
    roles: list[str] = Field(default_factory=list)
    cores: int = Field(default=4, ge=1, le=64)
    ram_mb: int = Field(default=8192, ge=2048, le=524288)
    os_disk_gb: int = Field(default=32, ge=16, le=2048)
    data_disk_gb: int | None = Field(default=None, ge=10, le=65536)
    heap_mb: int | None = None  # None means "recompute from RAM"
    pve_node: str | None = None  # optional pin to a Proxmox host
    ip: str | None = None
    extra_settings: dict[str, str | int | bool] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError("must be 2-40 characters: lowercase letters, digits and hyphens, "
                             "starting with a letter and not ending with a hyphen")
        return v

    @field_validator("ip")
    @classmethod
    def _ip(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            return str(ipaddress.IPv4Address(v))
        except ValueError as e:
            raise ValueError("must be an IPv4 address") from e

    @field_validator("extra_settings")
    @classmethod
    def _extra(cls, v: dict) -> dict:
        clash = sorted(set(v) & MANAGED_SETTINGS)
        if clash:
            raise ValueError("these settings are managed by ECM and cannot be set here: "
                             + ", ".join(clash))
        return v

    @model_validator(mode="after")
    def _roles_and_disks(self) -> "NodeSpec":
        if self.roles_mode == RolesMode.custom:
            if not self.roles:
                raise ValueError("roles_mode 'custom' needs a non-empty roles list; "
                                 "use 'coordinating' for a node with no roles")
            bad = sorted(set(self.roles) - VALID_ROLES)
            if bad:
                raise ValueError("unknown Elasticsearch roles: " + ", ".join(bad))
            if len(set(self.roles)) != len(self.roles):
                raise ValueError("roles contains duplicates")
        elif self.roles:
            raise ValueError(f"roles_mode '{self.roles_mode.value}' must not list roles; "
                             "the roles setting is omitted (default) or empty (coordinating)")
        if "voting_only" in self.roles and "master" not in self.roles:
            raise ValueError("voting_only requires the master role")
        if self.holds_data and self.data_disk_gb is None:
            raise ValueError("a node that holds data needs data_disk_gb")
        if self.heap_mb is not None:
            if self.heap_mb < MIN_HEAP_MB:
                raise ValueError(f"heap_mb must be at least {MIN_HEAP_MB}")
            if self.heap_mb > self.ram_mb // 2:
                raise ValueError("heap_mb must not exceed half of ram_mb")
            if self.heap_mb > MAX_HEAP_MB:
                raise ValueError(f"heap_mb must not exceed {MAX_HEAP_MB} (31 GB)")
        return self

    @property
    def effective_roles(self) -> frozenset[str]:
        if self.roles_mode == RolesMode.default:
            return DEFAULT_ROLES
        if self.roles_mode == RolesMode.coordinating:
            return frozenset()
        return frozenset(self.roles)

    @property
    def is_master_eligible(self) -> bool:
        return "master" in self.effective_roles

    @property
    def is_electable(self) -> bool:
        """Master-eligible and able to be elected (voting_only nodes vote but are never elected)."""
        return self.is_master_eligible and "voting_only" not in self.effective_roles

    @property
    def holds_data(self) -> bool:
        return bool(self.effective_roles & DATA_ROLES)

    @property
    def effective_heap_mb(self) -> int:
        return self.heap_mb if self.heap_mb is not None else default_heap_mb(self.ram_mb)


class DesiredState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    topology_preset: TopologyPreset = TopologyPreset.custom
    nodes: list[NodeSpec]
    network_profile: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError("must be 2-40 characters: lowercase letters, digits and hyphens, "
                             "starting with a letter and not ending with a hyphen")
        return v

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        m = _VERSION_RE.match(v)
        if not m:
            raise ValueError("must look like 9.4.3 (major.minor.patch)")
        if int(m.group(1)) < 8:
            raise ValueError("only Elasticsearch 8.x and later are supported")
        return v

    @model_validator(mode="after")
    def _cluster_rules(self) -> "DesiredState":
        if not self.nodes:
            raise ValueError("a cluster needs at least one node")
        if len(self.nodes) > MAX_NODES:
            raise ValueError(f"at most {MAX_NODES} nodes are supported")
        names = [n.name for n in self.nodes]
        dup = sorted({x for x in names if names.count(x) > 1})
        if dup:
            raise ValueError("node names must be unique: " + ", ".join(dup))
        ips = [n.ip for n in self.nodes if n.ip]
        dup_ip = sorted({x for x in ips if ips.count(x) > 1})
        if dup_ip:
            raise ValueError("node addresses must be unique: " + ", ".join(dup_ip))

        eligible = [n for n in self.nodes if n.is_master_eligible]
        if not any(n.is_electable for n in self.nodes):
            raise ValueError("the cluster needs at least one master-eligible node that is not "
                             "voting_only")
        if len(self.nodes) > 1 and len(eligible) < 3:
            raise ValueError("a multi-node cluster needs at least 3 master-eligible nodes, "
                             f"found {len(eligible)}; fewer cannot survive losing one")
        if not any(n.holds_data for n in self.nodes):
            raise ValueError("the cluster needs at least one node that holds data")
        return self

    @property
    def is_single_node(self) -> bool:
        return len(self.nodes) == 1

    @property
    def master_eligible_nodes(self) -> list[NodeSpec]:
        return [n for n in self.nodes if n.is_master_eligible]


def warnings(state: DesiredState) -> list[str]:
    """Advisory findings. They never block a cluster, but the UI should show them."""
    out: list[str] = []
    eligible = state.master_eligible_nodes
    if len(eligible) > 1 and len(eligible) % 2 == 0:
        out.append(f"{len(eligible)} master-eligible nodes is an even number; an odd number "
                   "tolerates the same failures with one node less")
    hosts: dict[str, list[str]] = {}
    for n in eligible:
        if n.pve_node:
            hosts.setdefault(n.pve_node, []).append(n.name)
    for host, members in sorted(hosts.items()):
        if len(members) > 1:
            out.append(f"master-eligible nodes {', '.join(sorted(members))} are pinned to the same "
                       f"Proxmox host ({host}); losing it would break the master quorum")
    if state.is_single_node:
        out.append("a single-node cluster has no replicas and reports yellow health")
    return out
