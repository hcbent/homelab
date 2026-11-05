from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, auth, operations
from app.db import get_db
from app.models import Operation, OperationLog, OperationStep, User
from app.provisioning import operation as tf

router = APIRouter(prefix="/api/operations", tags=["operations"],
                   dependencies=[Depends(auth.require_csrf_header)])


def _op(o: Operation) -> dict:
    elapsed = None
    if o.started_at:
        end = o.finished_at or __import__("datetime").datetime.now(o.started_at.tzinfo)
        elapsed = int((end - o.started_at).total_seconds())
    return {"id": o.id, "cluster_id": o.cluster_id, "kind": o.kind, "state": o.state,
            "phase": o.phase, "error": o.error, "started_at": o.started_at,
            "finished_at": o.finished_at, "elapsed_seconds": elapsed,
            "dry_run": o.dry_run, "parent_op_id": o.parent_op_id}


@router.get("")
def list_operations(db: Session = Depends(get_db), _: User = Depends(auth.current_user)):
    rows = db.scalars(select(Operation).order_by(Operation.created_at.desc()).limit(100)).all()
    return [_op(o) for o in rows]


@router.get("/{op_id}")
def get_operation(op_id: str, db: Session = Depends(get_db), _: User = Depends(auth.current_user)):
    o = db.get(Operation, op_id)
    if not o:
        raise HTTPException(404, "Operation not found")
    steps = db.scalars(select(OperationStep).where(OperationStep.operation_id == op_id)
                       .order_by(OperationStep.seq)).all()
    logs = db.scalars(select(OperationLog).where(OperationLog.operation_id == op_id)
                      .order_by(OperationLog.id)).all()
    done = sum(1 for s in steps if s.status == "done")
    return {**_op(o), "progress": {"done": done, "total": len(steps)},
            # The plan to review and the digest to approve. A dry run shows the plan but cannot be approved.
            "plan": {"digest": o.plan_digest, "summary": o.plan_summary,
                     "approvable": o.state == "pending_approval" and not o.dry_run}
            if o.plan_digest else None,
            "approval": {"digest": o.approved_digest, "by": o.approved_by, "at": o.approved_at}
            if o.approved_digest else None,
            "result": o.result,
            "steps": [{"seq": s.seq, "name": s.name, "status": s.status, "detail": s.detail}
                      for s in steps],
            "logs": [{"ts": line.ts, "stream": line.stream, "line": line.line} for line in logs]}


@router.post("/demo", status_code=202)
async def start_demo(db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    """Harmless job used to verify the worker and durable execution end to end."""
    from app.jobs import DEMO_PHASES, demo_noop
    try:
        op = operations.create_operation(db, "demo.noop", DEMO_PHASES, actor=user.username)
    except operations.OperationConflict as e:
        raise HTTPException(409, str(e)) from e
    try:
        await demo_noop.defer_async(operation_id=op.id)
    except Exception as e:
        operations.fail_operation(db, op.id, f"Could not enqueue job: {e}")
        audit.record(db, user.username, "operation.enqueue_failed", "operation", op.id)
        raise HTTPException(503, "Could not enqueue job") from e
    audit.record(db, user.username, "operation.start", "operation", op.id, kind="demo.noop")
    return {"id": op.id}


class ApproveBody(BaseModel):
    digest: str = Field(min_length=64, max_length=64)  # the digest of the plan the user reviewed


class CleanupBody(BaseModel):
    confirm_name: str = Field(min_length=1, max_length=100)


async def _enqueue(db: Session, op_id: str, user: User, trigger: str, undo) -> None:
    """Hand the operation to the worker. If that fails, `undo` puts it back so nothing is left half-started."""
    from app.jobs import tf_run
    try:
        await tf_run.defer_async(operation_id=op_id)
    except Exception as e:
        undo(db, op_id)
        audit.record(db, user.username, "operation.enqueue_failed", "operation", op_id, trigger=trigger)
        raise HTTPException(503, "Could not enqueue job") from e


def _fail(db: Session, op_id: str) -> None:
    operations.fail_operation(db, op_id, "Could not enqueue job")


@router.post("/{op_id}/approve", status_code=202)
async def approve(op_id: str, body: ApproveBody, db: Session = Depends(get_db),
                  user: User = Depends(auth.current_user)):
    """Approve the plan with this digest. Refused for a dry run, a changed plan or the wrong state."""
    try:
        op = operations.approve_operation(db, op_id, body.digest, user.username)
    except operations.ApprovalRefused as e:
        raise HTTPException(409, str(e)) from e
    audit.record(db, user.username, "operation.approve", "operation", op.id, kind=op.kind, digest=body.digest)
    await _enqueue(db, op.id, user, "approve", operations.revoke_approval)
    return {"id": op.id}


@router.post("/{op_id}/cancel")
def cancel(op_id: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    try:
        op = operations.cancel_operation(db, op_id)
    except operations.ApprovalRefused as e:
        raise HTTPException(409, str(e)) from e
    audit.record(db, user.username, "operation.cancel", "operation", op.id, kind=op.kind)
    return {"id": op.id}


@router.post("/{op_id}/retry", status_code=202)
async def retry(op_id: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    """Re-run a failed operation from its plan. Needs a new approval."""
    try:
        op = operations.retry_operation(db, op_id)
    except (operations.RetryRefused, operations.OperationConflict) as e:
        raise HTTPException(409, str(e)) from e
    audit.record(db, user.username, "operation.retry", "operation", op.id, kind=op.kind)
    await _enqueue(db, op.id, user, "retry", _fail)
    return {"id": op.id}


@router.post("/{op_id}/cleanup", status_code=202)
async def cleanup(op_id: str, body: CleanupBody, db: Session = Depends(get_db),
                  user: User = Depends(auth.current_user)):
    """Start a destroy of what a failed create left behind. It plans first and needs its own approval."""
    try:
        op = tf.start_cleanup(db, failed_op_id=op_id, confirm_name=body.confirm_name, actor=user.username)
    except tf.OperationRefused as e:
        raise HTTPException(409, str(e)) from e
    except operations.OperationConflict as e:
        raise HTTPException(409, str(e)) from e
    await _enqueue(db, op.id, user, "cleanup", _fail)
    return {"id": op.id}
