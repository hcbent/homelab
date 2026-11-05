"""Operation state machine. Phases are persisted so a job can resume after a crash."""
import hmac
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crypto import redact
from app.models import ACTIVE_STATES, Operation, OperationLog, OperationStep


class OperationConflict(Exception):
    pass


class AwaitingApproval(Exception):
    """Raised by a phase handler that needs a human decision. The operation pauses in `pending_approval`
    without failing and without holding a worker; approving it enqueues the job again."""


class ApprovalRefused(Exception):
    """The approval was not accepted. The message says why and is safe to show."""


class RetryRefused(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def create_operation(db: Session, kind: str, phases: list[str], cluster_id: str | None = None,
                     params: dict | None = None, actor: str | None = None, dry_run: bool = False,
                     parent_op_id: str | None = None) -> Operation:
    op = Operation(kind=kind, cluster_id=cluster_id, params=params or {}, created_by=actor,
                   state="running", started_at=_now(), dry_run=dry_run, parent_op_id=parent_op_id)
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
    if op.state == "cancelled":
        return  # a stray or late job must never revive a cancelled operation
    steps = db.scalars(select(OperationStep).where(OperationStep.operation_id == op_id)
                       .order_by(OperationStep.seq)).all()
    if op.state != "pending_approval":  # only approve_operation moves an operation out of that state
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
        except AwaitingApproval:
            step.status, op.state = "waiting", "pending_approval"
            db.commit()
            return
        except Exception as e:
            step.status, step.detail = "failed", redact(str(e))
            op.state, op.error, op.finished_at = "failed", redact(str(e)), _now()
            db.commit()
            raise
        step.status, step.finished_at = "done", _now()
        db.commit()
    op.state, op.phase, op.finished_at = "succeeded", None, _now()
    db.commit()


def fail_operation(db: Session, op_id: str, message: str) -> None:
    """Mark an operation failed outside run_phases (e.g. the job could not be enqueued)."""
    op = db.get(Operation, op_id)
    op.state, op.error, op.finished_at = "failed", redact(message), _now()
    db.commit()


def is_active(state: str) -> bool:
    return state in ACTIVE_STATES


# ---- approval, cancel and retry ---------------------------------------------------------------------------

def approve_operation(db: Session, op_id: str, digest: str, actor: str) -> Operation:
    """Record the approval of the plan with this digest and let the operation continue.

    The digest is the one the user was shown. It must equal the digest of the plan now stored on the operation,
    so a plan that was regenerated or edited after the user looked at it cannot be approved by accident. The
    state change is a single conditional UPDATE, so two clicks cannot both succeed.
    """
    op = db.get(Operation, op_id)
    if op is None:
        raise ApprovalRefused("operation not found")
    if op.dry_run:
        raise ApprovalRefused("this is a dry run: its plan can be reviewed but never approved")
    if op.state != "pending_approval":
        raise ApprovalRefused(f"the operation is {op.state}, not waiting for approval")
    if not op.plan_digest or not hmac.compare_digest(op.plan_digest, digest):
        raise ApprovalRefused("the plan changed since you reviewed it, or this is not its digest; "
                              "review the current plan and approve again")
    claimed = db.execute(
        update(Operation)
        .where(Operation.id == op_id, Operation.state == "pending_approval", Operation.dry_run.is_(False),
               Operation.plan_digest == digest)
        .values(state="running", approved_digest=digest, approved_by=actor, approved_at=_now())
    ).rowcount
    db.commit()
    if claimed != 1:
        raise ApprovalRefused("the operation changed while approving; review the current plan and try again")
    db.refresh(op)
    return op


def revoke_approval(db: Session, op_id: str) -> None:
    """Undo an approval whose job could not be enqueued, so the user can approve again."""
    db.execute(update(Operation).where(Operation.id == op_id, Operation.state == "running")
               .values(state="pending_approval", approved_digest=None, approved_by=None, approved_at=None))
    db.commit()


def cancel_operation(db: Session, op_id: str) -> Operation:
    """Cancel an operation that is waiting for approval. Nothing is running, so nothing needs to stop."""
    op = db.get(Operation, op_id)
    if op is None or op.state != "pending_approval":
        raise ApprovalRefused("only an operation waiting for approval can be cancelled")
    claimed = db.execute(
        update(Operation).where(Operation.id == op_id, Operation.state == "pending_approval")
        .values(state="cancelled", finished_at=_now(), phase=None)).rowcount
    db.execute(update(OperationStep).where(OperationStep.operation_id == op_id,
                                           OperationStep.status.in_(("waiting", "pending")))
               .values(status="cancelled"))
    db.commit()
    if claimed != 1:
        raise ApprovalRefused("the operation changed while cancelling")
    db.refresh(op)
    return op


def retry_operation(db: Session, op_id: str) -> Operation:
    """Re-run a failed operation. An approval never survives a retry.

    Phases before the plan are read-only and resume where they stopped. If the failure was at or after the
    plan, the retry starts again from the plan: after a partial apply the saved plan is stale, and the plan the
    user approved was for a different state of the world. The new plan gets a new digest and needs a new
    approval. `result` is kept, because cleanup of a failed create is scoped to what the last apply left.
    """
    op = db.get(Operation, op_id)
    if op is None or op.state != "failed":
        raise RetryRefused("only a failed operation can be retried")
    steps = db.scalars(select(OperationStep).where(OperationStep.operation_id == op_id)
                       .order_by(OperationStep.seq)).all()
    failed = next((s for s in steps if s.status != "done"), None)
    if failed is None:
        raise RetryRefused("the operation has no unfinished phase to retry")
    plan_seq = next((s.seq for s in steps if s.name == "plan"), failed.seq)
    restart_from = min(failed.seq, plan_seq)
    for step in steps:
        if step.seq >= restart_from:
            step.status, step.started_at, step.finished_at, step.detail = "pending", None, None, None
    op.state, op.error, op.phase, op.finished_at = "running", None, None, None
    op.plan_digest = op.plan_summary = None
    op.approved_digest = op.approved_by = op.approved_at = None
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise OperationConflict(f"Cluster {op.cluster_id} already has an active operation") from e
    return op
