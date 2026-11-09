"""The desired state of a cluster's Kibana machines (docs/DESIGN_KIBANA.md).

A Kibana machine is not an Elasticsearch node, so it is not in `DesiredState.nodes`: the quorum, restart and removal rules walk
that list and must never see it. It is kept beside the state, in the cluster's parameters, as `params["kibana"]` (a list, so more
than one can come later; this phase allows one), and is only merged in when the Terraform configuration is rendered.

Pure data and validation: no database, no Proxmox, no Terraform.
"""
import ipaddress
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import _NAME_RE

DEFAULT_CORES = 2
DEFAULT_RAM_MB = 4096
DEFAULT_OS_DISK_GB = 32
KIBANA_PORT = 5601
MAX_KIBANA_PER_CLUSTER = 1          # one in this phase (decision 1); the data model is a list
# A DNS name: labels of letters, digits and hyphens, none starting or ending with a hyphen, at most 253 characters in all.
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")


class KibanaRequest(BaseModel):
    """What a person may ask for when Kibana is added, whether to a built cluster or as part of creating one. Everything is optional: the machine is
    2 cores, 4 GiB and a 32 GB disk with no data disk, on the online host with the most room, reached by its address until it has a public name."""

    model_config = ConfigDict(extra="forbid")
    cores: int | None = Field(default=None, ge=1, le=64)
    ram_mb: int | None = Field(default=None, ge=2048, le=524288)
    os_disk_gb: int | None = Field(default=None, ge=16, le=2048)
    pve_node: str | None = Field(default=None, min_length=1, max_length=100)
    public_name: str | None = Field(default=None, max_length=253)


class KibanaSpec(BaseModel):
    """One Kibana machine. `host`, `vm_id` and `address` are what ECM chose when the machine was planned."""

    model_config = ConfigDict(extra="forbid")

    name: str
    vm_id: int = Field(ge=1)
    address: str
    host: str = Field(min_length=1, max_length=100)
    cores: int = Field(default=DEFAULT_CORES, ge=1, le=64)
    ram_mb: int = Field(default=DEFAULT_RAM_MB, ge=2048, le=524288)    # Kibana is a Node.js process that wants about 1 GiB of its own
    os_disk_gb: int = Field(default=DEFAULT_OS_DISK_GB, ge=16, le=2048)
    public_name: str | None = None                                   # what a browser calls it, if it has a name (decision 5)
    # The Elasticsearch addresses its kibana.yml was last written with. Empty when unknown (a Kibana recorded before this was kept), which
    # is never reported as out of date. Compared with the cluster's current nodes to tell the operator Kibana needs a restart.
    es_hosts: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError("must be 2-40 characters: lowercase letters, digits and hyphens, "
                             "starting with a letter and not ending with a hyphen")
        return v

    @field_validator("address")
    @classmethod
    def _address(cls, v: str) -> str:
        try:
            return str(ipaddress.IPv4Address(v))
        except ValueError as e:
            raise ValueError("must be an IPv4 address") from e

    @field_validator("public_name")
    @classmethod
    def _public_name(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = v.strip().lower().rstrip(".")
        if not _HOSTNAME.match(v):
            raise ValueError("must be a DNS name such as kibana.example.org (no scheme, port or path)")
        return v

    @property
    def public_url(self) -> str | None:
        return f"https://{self.public_name}" if self.public_name else None

    @property
    def url(self) -> str:
        """Where the worker reaches it, and where a person goes when there is no public name."""
        return f"https://{self.address}:{KIBANA_PORT}"


def kibana_name(cluster_name: str, number: int = 1) -> str:
    """`<cluster>-kb-01`. It must still be a valid machine name, which limits how long a cluster's name may be."""
    return f"{cluster_name}-kb-{number:02d}"


def kibana_of(params: dict) -> list[KibanaSpec]:
    """The Kibana machines recorded in a cluster's parameters (none for a cluster that has no Kibana or predates it)."""
    return [KibanaSpec.model_validate(k) for k in params.get("kibana") or []]


def caddy_snippet(cluster_name: str, spec: KibanaSpec) -> str | None:
    """The Caddyfile block that would put this Kibana behind Caddy, or None while it has no public name. ECM only shows it, never applies
    it. Caddy trusts Kibana through the cluster's CA, so TLS is verified end to end and `tls_insecure_skip_verify` is never used."""
    if not spec.public_name:
        return None
    return (f"{spec.public_name} {{\n"
            f"\treverse_proxy {spec.url} {{\n"
            f"\t\ttransport http {{ tls_trust_pool file /etc/caddy/ecm/{cluster_name}-ca.crt }}\n"
            "\t}\n"
            "}\n")
