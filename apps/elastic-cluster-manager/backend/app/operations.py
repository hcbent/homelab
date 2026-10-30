"""Operation state machine. Phases are persisted so a job can resume after a crash."""
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crypto import redact
from app.models import ACTIVE_STATES, Operation, OperationLog, OperationStep


class OperationConflict(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def create_operation(db: Session, kind: str, phases: list[str], cluster_id: str | None = None,
                     params: dict | None = None, actor: str | None = None) -> Operation:
    op = Operation(kind=kind, cluster_id=cluster_id, params=params or {}, created_by=actor,
                   state="running", started_at=_now())
    db.add(op)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise OperationConflict(f"Cluster {cluster_id} already has an active operation") from e
    for i, name in enumerate(phases):
        db.add(OperationStep(operation_id=op.id, seq=i, name=name))
    db.commit()
    return op


def log(db: Session, op_id: str, line: str, stream: str = "app") -> None:
    db.add(OperationLog(operation_id=op_id, stream=stream, line=redact(line)))
    db.commit()


def run_phases(db: Session, op_id: str, handlers: dict[str, Callable[[], None]]) -> None:
    """Run unfinished phases in order. Completed phases are skipped, so re-running after a
    worker restart resumes where it stopped. Handlers must themselves be idempotent."""
    op = db.get(Operation, op_id)
    steps = db.scalars(select(OperationStep).where(OperationStep.operation_id == op_id)
                       .order_by(OperationStep.seq)).all()
    op.state = "running"
    db.commit()
    for step in steps:
        if step.status == "done":
            continue
        op.phase = step.name
        step.status, step.started_at = "running", _now()
        db.commit()
        try:
            handlers[step.name]()
        except Exception as e:
            step.status, step.detail = "failed", redact(str(e))
            op.state, op.error, op.finished_at = "failed", redact(str(e)), _now()
            db.commit()
            raise
        step.status, step.finished_at = "done", _now()
        db.commit()
    op.state, op.phase, op.finished_at = "succeeded", None, _now()
    db.commit()


def is_active(state: str) -> bool:
    return state in ACTIVE_STATES
