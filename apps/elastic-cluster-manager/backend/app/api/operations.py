from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, auth, operations
from app.db import get_db
from app.models import Operation, OperationLog, OperationStep, User

router = APIRouter(prefix="/api/operations", tags=["operations"],
                   dependencies=[Depends(auth.require_csrf_header)])


def _op(o: Operation) -> dict:
    elapsed = None
    if o.started_at:
        end = o.finished_at or __import__("datetime").datetime.now(o.started_at.tzinfo)
        elapsed = int((end - o.started_at).total_seconds())
    return {"id": o.id, "cluster_id": o.cluster_id, "kind": o.kind, "state": o.state,
            "phase": o.phase, "error": o.error, "started_at": o.started_at,
            "finished_at": o.finished_at, "elapsed_seconds": elapsed}


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
