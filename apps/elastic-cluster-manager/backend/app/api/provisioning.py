from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit, auth, operations
from app.db import get_db
from app.desired import (
    ArtifactsApiCatalog,
    CatalogError,
    VersionCatalog,
    available_versions,
    check_target_version,
)
from app.models import User
from app.provisioning import create as plan_create
from app.provisioning.operation import OperationRefused, remove_cluster

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
        try:  # the list is cached by now, so this is not a second fetch; say which versions would work
            newest = (await run_in_threadpool(available_versions, catalog))[:6]
        except CatalogError:
            newest = []
        hint = f". Newest published: {', '.join(newest)}" if newest else ""
        raise HTTPException(422, "; ".join(problems) + hint)

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


class RemoveBody(BaseModel):
    confirm_name: str = Field(min_length=1, max_length=100)


@router.post("/{cluster_id}/remove")
def remove(cluster_id: str, body: RemoveBody, db: Session = Depends(get_db),
           user: User = Depends(auth.current_user)):
    """Remove the record of a managed cluster whose machines are gone. Refused while anything of it remains."""
    try:
        return remove_cluster(db, cluster_id=cluster_id, confirm_name=body.confirm_name, actor=user.username)
    except OperationRefused as e:
        raise HTTPException(409, str(e)) from e


versions_router = APIRouter(prefix="/api/versions", tags=["provisioning"])


@versions_router.get("")
async def list_versions(_: User = Depends(auth.current_user), catalog: VersionCatalog = Depends(get_catalog)):
    """Published Elasticsearch releases a new cluster can use (8.x and later), newest first, for the wizard."""
    try:
        every = await run_in_threadpool(available_versions, catalog)
    except CatalogError as e:
        raise HTTPException(503, f"{e}; the version list is unavailable right now") from e
    return {"versions": [v for v in every if int(v.split(".")[0]) >= 8][:40]}
