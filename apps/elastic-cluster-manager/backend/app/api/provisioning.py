from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app import audit, auth, operations
from app.db import get_db
from app.desired import ArtifactsApiCatalog, CatalogError, VersionCatalog, check_target_version
from app.models import User
from app.provisioning import create as plan_create
from app.provisioning.operation import OperationRefused

router = APIRouter(prefix="/api/clusters", tags=["provisioning"],
                   dependencies=[Depends(auth.require_csrf_header)])

_catalog = ArtifactsApiCatalog()  # one per process, so the version list is cached


def get_catalog() -> VersionCatalog:
    return _catalog


@router.post("", status_code=202)
async def create_cluster(body: plan_create.CreateRequest, db: Session = Depends(get_db),
                         user: User = Depends(auth.current_user),
                         catalog: VersionCatalog = Depends(get_catalog)):
    """Plan a new ECM-managed cluster. A dry run (the default) produces a plan that can be reviewed but never
    approved; send `dry_run: false` to get a plan that can be approved and applied."""
    # The version list needs the network, so it is checked before the allocation lock is taken, off the event loop.
    try:
        problems = await run_in_threadpool(check_target_version, body.version, catalog)
    except CatalogError as e:
        raise HTTPException(503, f"{e}; the version cannot be verified right now") from e
    if problems:
        raise HTTPException(422, "; ".join(problems))

    try:
        cluster, op, resolved = plan_create.create_cluster_operation(db, body, user.username)
    except plan_create.CreateInvalid as e:
        raise HTTPException(422, str(e)) from e
    except (plan_create.CreateConflict, operations.OperationConflict) as e:
        raise HTTPException(409, str(e)) from e
    except OperationRefused as e:
        raise HTTPException(422, str(e)) from e

    from app.jobs import tf_run
    try:
        await tf_run.defer_async(operation_id=op.id)
    except Exception as e:
        operations.fail_operation(db, op.id, f"Could not enqueue job: {e}")
        audit.record(db, user.username, "operation.enqueue_failed", "operation", op.id, trigger="create")
        raise HTTPException(503, "Could not enqueue job") from e
    return {
        "cluster_id": cluster.id, "operation_id": op.id, "dry_run": op.dry_run,
        "nodes": [{"name": n.name, "host": resolved.placement[n.name], "address": resolved.addresses[n.name],
                   "vm_id": resolved.vm_ids[n.name]} for n in resolved.state.nodes],
        "warnings": resolved.warnings,
    }
