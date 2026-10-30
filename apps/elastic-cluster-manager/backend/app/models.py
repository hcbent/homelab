import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, text
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
