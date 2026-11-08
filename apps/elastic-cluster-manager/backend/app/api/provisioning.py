from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit, auth, operations
from app.db import get_db
from app.desired import (
    ArtifactsApiCatalog,
    CatalogError,
    InstallableCatalog,
    VersionCatalog,
    available_versions,
    check_target_version,
)
from app.models import Cluster, User
from app.provisioning import create as plan_create
from app.provisioning.lifecycle import (
    AddNodes,
    ExpandDisk,
    ForgetNodes,
    RebuildNodes,
    RemoveNodes,
    ResizeNodes,
    RestartNodes,
    plan_add_nodes,
    plan_expand_disk,
    plan_forget_nodes,
    plan_rebuild_nodes,
    plan_remove_nodes,
    plan_resize,
    plan_restart_nodes,
)
from app.provisioning.operation import OperationRefused, remove_cluster, start_restart, start_update

router = APIRouter(prefix="/api/clusters", tags=["provisioning"],
                   dependencies=[Depends(auth.require_csrf_header)])

# One per process, so the lists are cached. Only releases the machines can install from apt are offered.
_catalog = InstallableCatalog(ArtifactsApiCatalog())


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


async def _plan_change(db: Session, cluster_id: str, user: User, make_params, *, reads_cluster: bool = False,
                       start=start_update) -> dict:
    """Plan a change to a built cluster from its current state and enqueue the job. Nothing changes until the plan
    is approved on its operation page. A plan that has to read the cluster over the network runs off the event loop."""
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(404, "cluster not found")
    try:
        params = await run_in_threadpool(make_params, db, cluster) if reads_cluster else make_params(db, cluster)
        op = start(db, cluster_id=cluster.id, params=params, actor=user.username)
    except (OperationRefused, operations.OperationConflict) as e:
        raise HTTPException(409, str(e)) from e
    from app.jobs import tf_run
    try:
        await tf_run.defer_async(operation_id=op.id)
    except Exception as e:
        operations.fail_operation(db, op.id, f"Could not enqueue job: {e}")
        audit.record(db, user.username, "operation.enqueue_failed", "operation", op.id, trigger="update")
        raise HTTPException(503, "Could not enqueue job") from e
    return {"operation_id": op.id, "change": params["change"]}


@router.post("/{cluster_id}/expand-disk", status_code=202)
async def expand_disk(cluster_id: str, body: ExpandDisk, db: Session = Depends(get_db),
                      user: User = Depends(auth.current_user)):
    """Plan growing the data disk of some nodes (or all that have one), and the filesystem on it. This only makes a
    plan; nothing changes until it is approved on its operation page. A disk is only ever grown."""
    return await _plan_change(db, cluster_id, user, lambda d, c: plan_expand_disk(d, c, body))


@router.post("/{cluster_id}/resize", status_code=202)
async def resize(cluster_id: str, body: ResizeNodes, db: Session = Depends(get_db),
                 user: User = Depends(auth.current_user)):
    """Plan giving some nodes (or all) a new number of cores and/or amount of RAM. This only makes a plan; nothing
    changes until it is approved on its operation page. Terraform changes the machines' configuration, but ECM does
    not restart them yet, so the new size takes effect when each one is restarted."""
    return await _plan_change(db, cluster_id, user, lambda d, c: plan_resize(d, c, body))


@router.post("/{cluster_id}/add-nodes", status_code=202)
async def add_nodes(cluster_id: str, body: AddNodes, db: Session = Depends(get_db),
                    user: User = Depends(auth.current_user)):
    """Plan adding `count` nodes of one kind: names, hosts, addresses and VMIDs are chosen and shown on the plan. This
    only makes a plan; nothing changes until it is approved on its operation page."""
    return await _plan_change(db, cluster_id, user, lambda d, c: plan_add_nodes(d, c, body))


@router.post("/{cluster_id}/remove-nodes", status_code=202)
async def remove_nodes(cluster_id: str, body: RemoveNodes, db: Session = Depends(get_db),
                       user: User = Depends(auth.current_user)):
    """Plan removing nodes. ECM first reads the cluster and refuses anything that could lose data or the quorum (too few
    master-eligible nodes, too little disk left, the last copy of a shard), with the reason. This only makes a plan; nothing
    changes until it is approved on its operation page, and then the data is moved off the nodes before their machines are
    destroyed. The cluster name must be typed in `confirm_name`."""
    return await _plan_change(db, cluster_id, user, lambda d, c: plan_remove_nodes(d, c, body), reads_cluster=True)


@router.post("/{cluster_id}/rebuild-nodes", status_code=202)
async def rebuild_nodes(cluster_id: str, body: RebuildNodes, db: Session = Depends(get_db),
                        user: User = Depends(auth.current_user)):
    """Plan putting back nodes whose machines are lost: the same names, addresses and VM IDs, each on its old host if that is
    online and placed by ECM otherwise. Refused for a node that is not lost, a red cluster or a cluster with no master. This
    only makes a plan; nothing changes until it is approved on its operation page."""
    return await _plan_change(db, cluster_id, user, lambda d, c: plan_rebuild_nodes(d, c, body), reads_cluster=True)


@router.post("/{cluster_id}/forget-nodes", status_code=202)
async def forget_nodes(cluster_id: str, body: ForgetNodes, db: Session = Depends(get_db),
                       user: User = Depends(auth.current_user)):
    """Plan taking lost nodes out of the cluster's record, destroying nothing. Refused for a node whose machine exists (use
    remove-nodes), a red cluster, or a removal that would break the quorum. The cluster name must be typed in `confirm_name`."""
    return await _plan_change(db, cluster_id, user, lambda d, c: plan_forget_nodes(d, c, body), reads_cluster=True)


@router.post("/{cluster_id}/restart-nodes", status_code=202)
async def restart_nodes(cluster_id: str, body: RestartNodes, db: Session = Depends(get_db),
                        user: User = Depends(auth.current_user)):
    """Plan restarting nodes (all of them when none are named): ECM reads the cluster, decides the order (nodes that are down are
    brought back first, then coordinating, data and master-eligible nodes, the elected master last), and refuses what cannot be done
    safely. This only makes a plan; nothing restarts until it is approved on its operation page."""
    return await _plan_change(db, cluster_id, user, lambda d, c: plan_restart_nodes(d, c, body), reads_cluster=True,
                              start=start_restart)


versions_router = APIRouter(prefix="/api/versions", tags=["provisioning"])


@versions_router.get("")
async def list_versions(_: User = Depends(auth.current_user), catalog: VersionCatalog = Depends(get_catalog)):
    """Published Elasticsearch releases a new cluster can use (8.x and later), newest first, for the wizard."""
    try:
        every = await run_in_threadpool(available_versions, catalog)
    except CatalogError as e:
        raise HTTPException(503, f"{e}; the version list is unavailable right now") from e
    return {"versions": [v for v in every if int(v.split(".")[0]) >= 8][:40]}
