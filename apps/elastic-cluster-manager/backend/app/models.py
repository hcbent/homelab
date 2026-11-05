import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    """Users and a role column exist from day one so RBAC can be added later."""

    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Credential(Base):
    """Encrypted secrets (Proxmox tokens, ES API keys, SSH keys). Never returned by the API."""

    __tablename__ = "credentials"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(100), unique=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Cluster(Base):
    """Minimal for now; discovery (phase 3) extends this."""

    __tablename__ = "clusters"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(100))
    es_cluster_uuid: Mapped[str | None] = mapped_column(String(64), unique=True)
    ownership: Mapped[str] = mapped_column(String(16), default="discovered")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Elasticsearch-reported state (refreshed by sync)
    es_version: Mapped[str | None] = mapped_column(String(32))
    health_status: Mapped[str | None] = mapped_column(String(16))
    snapshot: Mapped[dict | None] = mapped_column(JSON)  # health, shards, settings
    # How to reach it
    endpoint_urls: Mapped[list | None] = mapped_column(JSON)
    credential_id: Mapped[str | None] = mapped_column(ForeignKey("credentials.id"))
    tls_verify: Mapped[bool] = mapped_column(Boolean, default=True)
    tls_ca_pem: Mapped[str | None] = mapped_column(Text)  # public CA cert, not a secret
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(Text)


class ProxmoxConnection(Base):
    """One Proxmox API endpoint. A clustered PVE exposes all its nodes through one endpoint."""

    __tablename__ = "proxmox_connections"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    api_url: Mapped[str] = mapped_column(String(255))
    token_id: Mapped[str] = mapped_column(String(255))  # user@realm!name, not secret
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.id"))
    tls_verify: Mapped[bool] = mapped_column(Boolean, default=True)
    tls_ca_pem: Mapped[str | None] = mapped_column(Text)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PveNode(Base):
    __tablename__ = "pve_nodes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    connection_id: Mapped[str] = mapped_column(ForeignKey("proxmox_connections.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(16))
    usage: Mapped[dict] = mapped_column(JSON, default=dict)  # cpu, maxcpu, mem, maxmem, ...
    networks: Mapped[list] = mapped_column(JSON, default=list)  # bridges/VLAN devices
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("connection_id", "name"),)


class PveStorage(Base):
    __tablename__ = "pve_storages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    connection_id: Mapped[str] = mapped_column(ForeignKey("proxmox_connections.id", ondelete="CASCADE"))
    node: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str | None] = mapped_column(String(32))
    content: Mapped[str | None] = mapped_column(String(255))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    total: Mapped[int | None] = mapped_column(BigInteger)
    used: Mapped[int | None] = mapped_column(BigInteger)
    avail: Mapped[int | None] = mapped_column(BigInteger)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("connection_id", "node", "name"),)


class Vm(Base):
    """Proxmox-reported VM. tf_managed is False until adoption/provisioning says otherwise."""

    __tablename__ = "vms"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    connection_id: Mapped[str] = mapped_column(ForeignKey("proxmox_connections.id", ondelete="CASCADE"))
    pve_node: Mapped[str] = mapped_column(String(100))
    vmid: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(16))
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    cpu_cores: Mapped[int | None] = mapped_column(Integer)
    memory_mb: Mapped[int | None] = mapped_column(Integer)
    disks: Mapped[list] = mapped_column(JSON, default=list)
    nets: Mapped[list] = mapped_column(JSON, default=list)
    ips: Mapped[list] = mapped_column(JSON, default=list)  # [{"ip":..., "source":...}]
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # secrets stripped
    tf_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("connection_id", "vmid"),)


class EsNode(Base):
    __tablename__ = "es_nodes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"))
    es_node_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64))
    host: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(32))
    roles: Mapped[list] = mapped_column(JSON, default=list)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    heap_used_pct: Mapped[int | None] = mapped_column(Integer)
    heap_max_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_avail_bytes: Mapped[int | None] = mapped_column(BigInteger)
    shard_count: Mapped[int] = mapped_column(Integer, default=0)
    # Correlation to a Proxmox VM; only "verified" is ever trusted.
    vm_id: Mapped[str | None] = mapped_column(ForeignKey("vms.id", ondelete="SET NULL"))
    link_confidence: Mapped[str] = mapped_column(String(16), default="unlinked")
    link_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("cluster_id", "es_node_id"),)


class NetworkProfileRow(Base):
    """A network ECM may place nodes on, and the address range it may allocate from. Editable in the UI."""

    __tablename__ = "network_profiles"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    bridge: Mapped[str] = mapped_column(String(32), default="vmbr0")
    vlan: Mapped[int | None] = mapped_column(Integer)
    cidr: Mapped[str] = mapped_column(String(18))
    gateway: Mapped[str] = mapped_column(String(15))
    dns: Mapped[list] = mapped_column(JSON, default=list)
    search_domain: Mapped[str | None] = mapped_column(String(253))
    range_start: Mapped[str] = mapped_column(String(15))
    range_end: Mapped[str] = mapped_column(String(15))
    dhcp_start: Mapped[str | None] = mapped_column(String(15))
    dhcp_end: Mapped[str | None] = mapped_column(String(15))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


ACTIVE_STATES = ("pending_approval", "running")
_ACTIVE_SQL = text("state IN ('pending_approval', 'running')")


class Operation(Base):
    __tablename__ = "operations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    cluster_id: Mapped[str | None] = mapped_column(ForeignKey("clusters.id"))
    kind: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default="running")
    phase: Mapped[str | None] = mapped_column(String(100))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # At most one active mutating operation per cluster, enforced by the database.
    __table_args__ = (
        Index(
            "uq_operations_one_active_per_cluster",
            "cluster_id",
            unique=True,
            postgresql_where=_ACTIVE_SQL,
            sqlite_where=_ACTIVE_SQL,
        ),
    )


class OperationStep(Base):
    __tablename__ = "operation_steps"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    operation_id: Mapped[str] = mapped_column(ForeignKey("operations.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(Text)


class OperationLog(Base):
    __tablename__ = "operation_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("operations.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    stream: Mapped[str] = mapped_column(String(16), default="app")
    line: Mapped[str] = mapped_column(Text)


class AuditEvent(Base):
    """Insert-only by convention: no code path updates or deletes rows."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
