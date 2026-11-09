"""Terraform operations: tf.create, and tf.destroy used to clean up or tear down a create that has finished.

Phases:  render, init, plan, approval, apply, configure   (a dry run stops after plan; a destroy has no configure)

  * render, init and plan change nothing on Proxmox or any Elasticsearch cluster. `init` with the pg backend
    does create the cluster's empty state schema in ECM's own state database. A dry run on a cluster made only
    for it plans on local state instead, and is removed with that cluster and its workspace when it ends.
  * plan stores a digest that covers the operation kind, the rendered configuration and the plan file. The
    operation then pauses in `pending_approval` and the job ends; no worker is held while a person decides.
  * approval is a click on that digest (operations.approve_operation). It enqueues the same job, which resumes.
  * apply re-checks the stored plan against the files on disk and against the approved digest, then applies
    that saved plan file and nothing else.
  * configure runs Ansible's create on the machines apply just made: it installs the pinned Elasticsearch
    version, forms the cluster and waits for green. The same approval covers it, because the digest includes
    "install elasticsearch <version> on <n> nodes". It is skipped once the cluster has bootstrapped. The elastic
    password is made here, kept encrypted only until the bootstrap succeeds, and then deleted; the cluster CA key
    and an API key are kept encrypted. A new CA is stored even when the run fails, because certificates signed by
    it may already be on the machines, and a retry hands it back so no second CA is made.

Nothing here destroys on failure. A failed create keeps its partial state and records what exists. Cleaning
it up, or tearing down a create that succeeded, is a separate tf.destroy operation that a person starts by
typing the cluster name, that has its own plan and its own approval, and that may only delete resources the
create recorded in state.
"""
import copy
import json
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app import audit, crypto
from app.config import get_settings, tf_state_conninfo
from app.configmgmt import (
    AnsibleError,
    AnsibleRequest,
    AnsibleRunner,
    KibanaHost,
    NewCa,
    runner_from_settings,
)
from app.desired.kibana import caddy_snippet, kibana_of
from app.desired.models import DesiredState
from app.desired.network import NetworkProfile
from app.discovery import factory, proxmox
from app.discovery.http import DiscoveryError
from app.models import ACTIVE_STATES, Cluster, Credential, EsNode, Operation, ProxmoxConnection, Vm
from app.operations import AwaitingApproval, create_operation, log, run_phases
from app.provisioning.ownership import foreign_machines, machine_vm_ids
from app.provisioning.ownership import torn_down as _torn_down
from app.provisioning.plan import (
    check_add_kibana_plan,
    check_forget_plan,
    check_plan_safety,
    check_rebuild_plan,
    check_removal_plan,
    node_of,
)
from app.provisioning.render import RenderError, RenderInput, TemplateRef, render_workspace
from app.provisioning.runner import CliTerraformRunner, TerraformError, TerraformRunner
from app.provisioning.workspace import existing_workspace, open_workspace, remove_workspace

CREATE = "tf.create"
DESTROY = "tf.destroy"
UPDATE = "tf.update"
PHASES = ["render", "init", "plan", "approval", "apply"]
CREATE_PHASES = [*PHASES, "configure"]  # a real create also builds the cluster on the machines it made
DRY_RUN_PHASES = ["render", "init", "plan"]  # a dry run has no approval or apply step to run
# The kind the plan safety rules and the stored plan use.
UPDATE_PHASES = [*PHASES, "configure"]  # a change to a built cluster ends with a converge of its nodes
# A resize applies the new size with Terraform, writes the new heap with a converge, then restarts the nodes one at a
# time (docs/DESIGN_RESIZE.md). The converge restarts nothing, so a bigger heap sits unused until a node restarts.
RESIZE_PHASES = [*PHASES, "configure", "restart"]
# Removing nodes empties them first (Elasticsearch moves their shards away while they still run), and only then lets
# Terraform destroy the machines (docs/DESIGN_REMOVE_NODE.md). The drain is after the approval, since it changes the
# cluster, and before the apply, since a machine must be empty when it goes.
REMOVE_PHASES = ["render", "init", "plan", "approval", "drain", "apply", "configure"]
# Restarting nodes has no Terraform step: the plan is the list of nodes and what is done to each, and the approval is of that exact list
# (docs/DESIGN_RECOVERY.md, slice 5b). It is its own kind so an empty Terraform plan, which skips the approval, can never carry it.
RESTART = "es.restart"
RESTART_NODES_PHASES = ["plan", "approval", "restart"]
PLAN_KIND = {CREATE: "create", DESTROY: "destroy", UPDATE: "update"}

RunnerFactory = Callable[[Callable[[str], None]], TerraformRunner]
AnsibleFactory = Callable[[Callable[[str], None]], AnsibleRunner]
ES_HTTP_PORT = 9200


class OperationRefused(Exception):
    """A Terraform operation cannot be started. The message says why and is safe to show."""


class PlanRejected(Exception):
    """The plan does more than this kind of operation may do. It is never offered for approval."""


class PreflightFailed(Exception):
    """The token Terraform uses cannot do what this operation needs. Found before a plan is made, so nothing
    reaches the approval step and no apply can fail half way for want of a permission."""


class ApplyRefused(Exception):
    """Apply did not start because the plan is stale or does not match the approval."""


class ApplyFailed(Exception):
    """Terraform started the apply and it failed. Partial state is kept; nothing was destroyed."""


class RestartFailed(Exception):
    """The rolling restart stopped. The nodes already restarted stay restarted; a retry resumes with the rest."""


class DrainFailed(Exception):
    """The nodes could not be emptied. Nothing was destroyed and the shutdowns were cancelled."""


class ConfigureFailed(Exception):
    """The machines exist but building the cluster on them failed. The VMs, the stored password and any CA that
    was made are kept; a retry resumes the configure step with them."""


# ---- inputs ---------------------------------------------------------------------------------------------

def render_input(params: dict, cluster_id: str, endpoint: str, insecure: bool,
                 state_backend: Literal["pg", "local"] = "pg") -> RenderInput:
    """Rebuild the render input from the parameters stored on the operation."""
    return RenderInput(
        cluster_id=cluster_id, state_backend=state_backend,
        state=DesiredState.model_validate(params["state"]),
        placement=params["placement"], addresses=params["addresses"], vm_ids=params["vm_ids"],
        profile=NetworkProfile.model_validate(params["profile"]),
        template=TemplateRef(params["template"]["node_name"], params["template"]["vm_id"]),
        proxmox_endpoint=endpoint, proxmox_insecure=insecure,
        datastore_id=params.get("datastore_id", "tank"), pool_id=params.get("pool_id", "ecm"),
        cpu_type=params.get("cpu_type", "host"), kibana=kibana_of(params))


def kibana_credential_names(cluster_id: str) -> tuple[str, str]:
    """The stored service-account token and the three encryption keys of a cluster's Kibana (both encrypted, both redacted from logs)."""
    return (f"es-kibana-token-{cluster_id}", f"es-kibana-keys-{cluster_id}")


def _connection(db: Session, params: dict) -> ProxmoxConnection:
    conn = db.get(ProxmoxConnection, params.get("proxmox_connection_id") or "")
    if conn is None:
        raise OperationRefused("the Proxmox connection for this operation no longer exists")
    return conn


def _check_params(db: Session, cluster_id: str, params: dict) -> None:
    """Fail early, with a plain message, instead of inside a job."""
    conn = _connection(db, params)
    try:
        render_workspace(render_input(params, cluster_id, conn.api_url, not conn.tls_verify))
    except (RenderError, KeyError, ValueError) as e:
        raise OperationRefused(f"the cluster configuration cannot be rendered: {e}") from e


def _managed_cluster(db: Session, cluster_id: str | None) -> Cluster:
    cluster = db.get(Cluster, cluster_id) if cluster_id else None
    if cluster is None:
        raise OperationRefused("cluster not found")
    if cluster.ownership != "managed":
        # Discovered and adopted clusters, and every VM discovery found, are never provisioned or cleaned up here.
        raise OperationRefused(f"this cluster is {cluster.ownership}, not managed by ECM; "
                               "Terraform operations only run on clusters ECM created")
    return cluster


# ---- starting operations --------------------------------------------------------------------------------

def start_create(db: Session, *, cluster_id: str, params: dict, actor: str, dry_run: bool = False) -> Operation:
    """Create the operation for a new cluster. The caller enqueues the `tf.run` job for it.

    `params` holds the desired state, placement, addresses, VMIDs, network profile, template and Proxmox
    connection chosen in the wizard. They are checked here by rendering the configuration.
    """
    _managed_cluster(db, cluster_id)
    _check_params(db, cluster_id, params)
    op = create_operation(db, CREATE, DRY_RUN_PHASES if dry_run else CREATE_PHASES, cluster_id=cluster_id,
                          params=params, actor=actor, dry_run=dry_run)
    audit.record(db, actor, "operation.start", "operation", op.id, kind=CREATE, dry_run=dry_run)
    return op


def start_update(db: Session, *, cluster_id: str, params: dict, actor: str) -> Operation:
    """Create the operation that changes a built cluster to the state in `params` (see lifecycle.py).

    The parameters are the cluster's current desired state with the change made. Terraform may create or change
    resources for this, never delete or replace them (see plan.py), the plan needs its own approval, and when
    Terraform has applied it the cluster's desired state becomes these parameters. The caller enqueues the job.
    """
    cluster = _managed_cluster(db, cluster_id)
    if cluster.bootstrapped_at is None:
        raise OperationRefused("this cluster has not finished being built, so there is nothing to change yet")
    _check_params(db, cluster.id, params)
    foreign = foreign_machines(db, params)
    if foreign:
        raise OperationRefused("a change only touches machines ECM created, and these are not: " + ", ".join(foreign))
    phases = {"resize": RESIZE_PHASES, "remove_nodes": REMOVE_PHASES}.get((params.get("change") or {}).get("kind"),
                                                                           UPDATE_PHASES)
    op = create_operation(db, UPDATE, phases, cluster_id=cluster.id, params=params, actor=actor)
    audit.record(db, actor, "operation.start", "operation", op.id, kind=UPDATE, change=params.get("change"))
    return op


def start_restart(db: Session, *, cluster_id: str, params: dict, actor: str) -> Operation:
    """Create the operation that restarts the nodes in `params["change"]` (see lifecycle.plan_restart_nodes). Only the machines it will
    restart are checked for being ECM's. The caller enqueues the job."""
    cluster = _managed_cluster(db, cluster_id)
    if cluster.bootstrapped_at is None:
        raise OperationRefused("this cluster has not finished being built, so there is nothing to restart yet")
    change = params.get("change") or {}
    mine = {"proxmox_connection_id": params.get("proxmox_connection_id"),
            "vm_ids": {n: info["vm_id"] for n, info in (change.get("nodes") or {}).items()}}
    foreign = foreign_machines(db, mine)
    if foreign:
        raise OperationRefused("a restart only touches machines ECM created, and these are not: " + ", ".join(foreign))
    op = create_operation(db, RESTART, RESTART_NODES_PHASES, cluster_id=cluster.id, params=params, actor=actor)
    audit.record(db, actor, "operation.start", "operation", op.id, kind=RESTART, change=change)
    return op


def start_cleanup(db: Session, *, create_op_id: str, confirm_name: str, actor: str,
                  confirm_data_loss: bool = False) -> Operation:
    """Create the destroy operation that removes what a create made: the partial result of one that failed, or
    everything a create that succeeded built.

    Allowed only for a finished tf.create whose apply left resources in state, on a managed cluster, once, and
    only after the person types the cluster name. The plan it produces can delete nothing the create did not
    record (see _outside_the_create), and it needs its own approval. A cluster that has bootstrapped has
    Elasticsearch on its machines and may hold data, so its teardown also needs the data loss accepted.
    """
    parent = db.get(Operation, create_op_id)
    if parent is None or parent.kind != CREATE:
        raise OperationRefused("cleanup applies to a create operation")
    if parent.state not in ("failed", "succeeded"):
        raise OperationRefused(f"the create is {parent.state}; it can be cleaned up once it has finished")
    if parent.dry_run:
        raise OperationRefused("a dry run made nothing, so there is nothing to clean up")
    if parent.cluster_id is None:
        # A teardown removes the cluster's record and detaches its operations, so a create with no cluster has
        # already been cleaned up (or its cluster was removed by hand once nothing was left).
        raise OperationRefused("this create has already been cleaned up: its cluster was removed")
    cluster = _managed_cluster(db, parent.cluster_id)
    if confirm_name != cluster.name:
        raise OperationRefused("type the cluster name exactly to confirm the cleanup")
    if cluster.bootstrapped_at is not None and not confirm_data_loss:
        raise OperationRefused("this cluster has been bootstrapped: Elasticsearch is installed on its machines and "
                               "any data in it is destroyed with them. Confirm that you accept the data loss "
                               "to continue")
    if _torn_down(db, parent.id):
        raise OperationRefused("this create has already been cleaned up")
    left = (parent.result or {}).get("resources_in_state") or []
    if not left:
        raise OperationRefused("the create left nothing in Terraform state, so there is nothing to clean up")
    _check_params(db, cluster.id, parent.params)
    foreign = foreign_machines(db, parent.params)
    if foreign:
        raise OperationRefused("a teardown only destroys machines ECM created, and these are not: "
                               + ", ".join(foreign))
    op = create_operation(db, DESTROY, PHASES, cluster_id=cluster.id, params=cluster.desired or parent.params,
                          actor=actor, parent_op_id=parent.id)
    audit.record(db, actor, "operation.start", "operation", op.id, kind=DESTROY, parent=parent.id,
                 parent_state=parent.state, resources=len(left), bootstrapped=cluster.bootstrapped_at is not None,
                 data_loss_confirmed=bool(confirm_data_loss))
    return op


def _removal_blocker(db: Session, cluster: Cluster, tearing_down: Operation | None = None) -> str | None:
    """Why the record of this managed cluster cannot be removed yet, or None when nothing of it is left.

    `tearing_down` is the destroy operation that is itself asking, from its last step: it is still running, but
    for this purpose it has already torn its create down."""
    if cluster.bootstrapped_at is not None:
        return "this cluster has bootstrapped: tear its machines down first (cleanup), then remove it"
    ops = db.scalars(select(Operation).where(Operation.cluster_id == cluster.id)).all()
    if any(o.state in ACTIVE_STATES and o is not tearing_down and o.id != getattr(tearing_down, "id", None)
           for o in ops):
        return "an operation is still running on this cluster; wait for it to finish"
    node_names: set[str] = set()
    for op in ops:
        if op.kind != CREATE or op.dry_run:
            continue
        node_names |= {n["name"] for n in (op.params.get("state") or {}).get("nodes", [])}
        built = (op.result or {}).get("resources_in_state") or []
        if built and not _torn_down(db, op.id) and not (tearing_down is not None
                                                       and tearing_down.parent_op_id == op.id):
            return ("a create of this cluster built machines that have not been torn down through "
                    f"ECM (operation {op.id}); clean it up first")
    still_there = sorted(node_names & {n for (n,) in db.execute(select(Vm.name)) if n})
    if still_there:
        return f"VMs named {', '.join(still_there)} still exist in Proxmox; remove them first"
    return None


def cluster_lifecycle(db: Session, cluster: Cluster) -> dict:
    """What can be done to a cluster now, for the UI. It reads the same rules start_cleanup and remove_cluster
    enforce, so the page does not offer what the API would refuse; those two still check for themselves.

    `teardown_of` is the create operation a teardown would clean up: the newest real create that finished with
    machines in Terraform state and has not been torn down. `nodes` names the machines it would destroy.
    """
    if cluster.ownership != "managed":
        return {"managed": False}
    ops = db.scalars(select(Operation).where(Operation.cluster_id == cluster.id)
                     .order_by(Operation.created_at.desc())).all()
    busy = next((o for o in ops if o.state in ACTIVE_STATES), None)
    target = next((o for o in ops if o.kind == CREATE and not o.dry_run and o.state in ("failed", "succeeded")
                   and (o.result or {}).get("resources_in_state") and not _torn_down(db, o.id)), None)
    names = [n["name"] for n in ((target.params or {}).get("state") or {}).get("nodes", [])] if target else []
    recorded = ((cluster.desired or {}).get("state") or {}).get("nodes", []) if cluster.bootstrapped_at else []
    data_disks = {n["name"]: n["data_disk_gb"] for n in recorded if n.get("data_disk_gb")}
    sizes = {n["name"]: {"cores": n["cores"], "ram_mb": n["ram_mb"]} for n in recorded}
    placement = (cluster.desired or {}).get("placement") or {}
    members = ({n.name: n for n in DesiredState.model_validate(cluster.desired["state"]).nodes}
               if cluster.desired and cluster.bootstrapped_at else {})
    # What the Remove nodes panel offers: each node's roles, where it runs and whether it counts towards the quorum.
    seen = {r.name for r in db.scalars(select(EsNode).where(EsNode.cluster_id == cluster.id))}
    machines = {(v.vmid, v.name): v.status for v in db.scalars(select(Vm).where(
        Vm.connection_id == (cluster.desired or {}).get("proxmox_connection_id")))}
    vm_ids = (cluster.desired or {}).get("vm_ids") or {}
    # What the last syncs saw of each node, for the Recovery panel: whether its machine is in Proxmox and whether
    # Elasticsearch reports it. A node with neither is lost.
    node_state = {name: {"machine": (int(vm_ids[name]), name) in machines if name in vm_ids else None,
                         "in_cluster": name in seen,
                         # what Proxmox last said the machine was doing (running, stopped), when it has one
                         "vm_status": machines.get((int(vm_ids[name]), name)) if name in vm_ids else None}
                  for name in members}
    roles = {name: {"roles": sorted(n.effective_roles), "master_eligible": n.is_master_eligible,
                    "holds_data": n.holds_data, "host": placement.get(name)} for name, n in members.items()}
    blocker = _removal_blocker(db, cluster)
    conn = db.get(ProxmoxConnection, (cluster.desired or {}).get("proxmox_connection_id") or "")
    return {
        "managed": True,
        # when the Proxmox inventory the node states below come from was last read
        "proxmox_synced_at": conn.last_sync_at.isoformat() if conn is not None and conn.last_sync_at else None,
        "busy_operation_id": busy.id if busy else None,
        "teardown_of": target.id if target and not busy else None,
        "nodes": names if target and not busy else [],
        "bootstrapped": cluster.bootstrapped_at is not None,
        # nodes ECM wrote a configuration change to without restarting them, so the change is waiting for a restart
        "pending_restart": sorted(n for n in (cluster.pending_restart or {}) if n in members),
        # What the cluster is now and whether a change can be planned: each data node's disk, from the recorded state
        "data_disks": data_disks,
        "sizes": sizes,
        "node_roles": roles,
        "node_state": node_state,
        "kibana": _kibana_panel(cluster, ops, busy),
        "can_change": bool(cluster.desired) and cluster.bootstrapped_at is not None and busy is None,
        "can_remove": blocker is None,
        # why the record cannot go yet, for when nothing else is offered
        "remove_blocker": blocker,
    }


def _kibana_panel(cluster: Cluster, ops: list[Operation], busy: Operation | None) -> dict:
    """What the Kibana panel shows: the machines on record, the Caddy snippet for each (shown, never applied), and how the last Add Kibana
    ended. That operation includes the health check, so a succeeded one means Kibana reported itself available when it finished."""
    recorded = kibana_of(cluster.desired or {}) if cluster.bootstrapped_at else []
    last = next((o for o in ops if o.kind == UPDATE and not o.dry_run
                 and (o.params.get("change") or {}).get("kind") == "add_kibana"), None)
    return {
        "machines": [{**k.model_dump(mode="json"), "url": k.url, "public_url": k.public_url,
                      "caddy_snippet": caddy_snippet(cluster.name, k)} for k in recorded],
        "can_add": bool(cluster.desired) and cluster.bootstrapped_at is not None and busy is None and not recorded,
        "ca_available": bool(cluster.tls_ca_pem),
        "last_add": ({"operation_id": last.id, "state": last.state,
                      "finished_at": last.finished_at.isoformat() if last.finished_at else None} if last else None),
    }


def remove_cluster(db: Session, *, cluster_id: str, confirm_name: str, actor: str) -> dict:
    """Remove the record of a managed cluster whose machines are gone, so it stops cluttering the list.

    Only a cluster ECM created can be removed here, only after its name is typed, and only when nothing is left of
    it: no operation running, every create that built something torn down through ECM, no VM in Proxmox still
    carrying one of its node names, and no bootstrap recorded. Its operations are kept, detached from the cluster,
    because they are the history of what ECM did; its observed nodes and any stored credentials go with it.
    """
    cluster = _managed_cluster(db, cluster_id)
    if confirm_name != cluster.name:
        raise OperationRefused("type the cluster name exactly to confirm the removal")
    blocker = _removal_blocker(db, cluster)
    if blocker:
        raise OperationRefused(blocker)

    return _delete_record(db, cluster, actor)


def _delete_record(db: Session, cluster: Cluster, actor: str, **why: object) -> dict:
    """Delete the cluster's row, its observed nodes and its stored credentials. Its operations are kept, detached,
    because they are the history of what ECM did. The caller has already checked nothing of it is left."""
    suffix = cluster.id
    detached = db.execute(update(Operation).where(Operation.cluster_id == cluster.id)
                          .values(cluster_id=None)).rowcount
    db.execute(delete(EsNode).where(EsNode.cluster_id == cluster.id))
    cluster.credential_id = None
    db.flush()
    db.execute(delete(Credential).where(Credential.name.in_(
        [f"es-elastic-{suffix}", f"es-ca-key-{suffix}", f"es-api-key-{suffix}", *kibana_credential_names(suffix)])))
    name = cluster.name
    db.delete(cluster)
    audit.record(db, actor, "cluster.remove", "cluster", suffix, name=name, operations_kept=detached, **why)
    db.commit()
    return {"id": suffix, "name": name, "operations_kept": detached}


# ---- running them ---------------------------------------------------------------------------------------

def default_runner(line_log: Callable[[str], None]) -> TerraformRunner:
    s = get_settings()
    return CliTerraformRunner(binary=s.terraform_binary, plugin_dir=s.terraform_plugin_dir, log=line_log,
                              parallelism=s.tf_parallelism)


def default_ansible(line_log: Callable[[str], None]) -> AnsibleRunner:
    return runner_from_settings(get_settings(), log=line_log)


def run_operation(db: Session, op_id: str, make_runner: RunnerFactory = default_runner,
                  root: Path | None = None, make_ansible: AnsibleFactory = default_ansible) -> None:
    """Run or resume a Terraform operation. This is the body of the `tf.run` job."""
    op = db.get(Operation, op_id)
    if op.kind == RESTART:
        from app.provisioning.restart import (
            RestartHandlers,  # imported here: it needs this module whole
        )
        run_phases(db, op_id, RestartHandlers(db, op, make_ansible).handlers())
        return
    workspace_root = root or Path(get_settings().tf_workspace_root)
    handlers = _Handlers(db, op, make_runner, workspace_root, make_ansible).handlers()
    try:
        run_phases(db, op_id, handlers)
    finally:
        if op.dry_run:
            _drop_dry_run_stub(db, op_id, workspace_root)


def _drop_dry_run_stub(db: Session, op_id: str, root: Path) -> None:
    """A dry run leaves nothing behind but its own operation. Planning needs a cluster row (its id names the
    Terraform workspace and state), and for a name ECM has not seen that row is made just for the dry run. Once
    the dry run is over, succeeded or failed, that stub is removed, or an abandoned wizard would leave an empty
    managed cluster in the list. A cluster with any real operation of its own is never touched, and the dry run's
    record stays, detached, with the cluster's name in its parameters."""
    db.expire_all()
    op = db.get(Operation, op_id)
    if op is None or op.cluster_id is None or op.state not in ("succeeded", "failed"):
        return
    cluster = db.get(Cluster, op.cluster_id)
    if cluster is None or cluster.ownership != "managed" or cluster.bootstrapped_at is not None:
        return
    ops = db.scalars(select(Operation).where(Operation.cluster_id == cluster.id)).all()
    if any(not o.dry_run or (o.id != op.id and o.state in ACTIVE_STATES) for o in ops):
        return
    cluster_id = cluster.id
    _delete_record(db, cluster, op.created_by or "worker", reason="dry run", operation=op.id)
    remove_workspace(root, cluster_id)


class _Handlers:
    def __init__(self, db: Session, op: Operation, make_runner: RunnerFactory, root: Path,
                 make_ansible: AnsibleFactory = default_ansible):
        self.db, self.op, self.root = db, op, root
        self.kind = op.kind
        self.plan_kind = PLAN_KIND[op.kind]
        self.cluster_id = op.cluster_id or ""
        self.runner = make_runner(lambda line: log(db, op.id, line, "terraform"))
        self.ansible = make_ansible(lambda line: log(db, op.id, line, "ansible"))

    def handlers(self) -> dict[str, Callable[[], None]]:
        return {"render": self.render, "init": self.init, "plan": self.plan,
                "approval": self.approval, "apply": self.apply, "configure": self.configure,
                "restart": self.restart, "drain": self.drain}

    # -- helpers --

    def _rendered(self) -> dict[str, str]:
        conn = _connection(self.db, self.op.params)
        return render_workspace(render_input(self.op.params, self.cluster_id, conn.api_url, not conn.tls_verify,
                                             state_backend="local" if self._plans_for_a_stub() else "pg"))

    def _plans_for_a_stub(self) -> bool:
        """True for a dry run on a cluster made just for it: there is no state to read, so it plans against local
        state and leaves no schema in the state database. Any real operation on the cluster, even a failed one,
        may have left state, so then the dry run reads it from the database like everything else does."""
        if not self.op.dry_run:
            return False
        cluster = self.db.get(Cluster, self.cluster_id)
        if cluster is None or cluster.bootstrapped_at is not None:
            return False
        ops = self.db.scalars(select(Operation).where(Operation.cluster_id == self.cluster_id)).all()
        return all(o.dry_run for o in ops)

    def _proxmox_token(self) -> tuple[str, str]:
        conn = _connection(self.db, self.op.params)
        separate = bool(conn.terraform_credential_id and conn.terraform_token_id)
        credential_id = conn.terraform_credential_id if separate else conn.credential_id
        token_id = conn.terraform_token_id if separate else conn.token_id
        return token_id, crypto.decrypt(self.db.get(Credential, credential_id).ciphertext)

    def _preflight(self) -> None:
        """Check, with one read-only request, that the token Terraform will use has the rights this needs."""
        conn = _connection(self.db, self.op.params)
        token_id, secret = self._proxmox_token()
        params = self.op.params
        try:
            perms = factory.proxmox_client_for(conn, token_id, secret).permissions()
        except DiscoveryError as e:
            if e.status in (401, 403):
                raise PreflightFailed(f"Proxmox rejected the token Terraform uses ({e}); replace it, then retry") from e
            raise PreflightFailed(f"could not reach Proxmox to check the token's rights ({e}); retry when it is "
                                  "reachable") from e
        problems = proxmox.preflight_problems(
            perms, pool_id=params.get("pool_id", "ecm"), datastore=params.get("datastore_id", "tank"),
            template_vmid=(params.get("template") or {}).get("vm_id"),
            # Adding a node or Kibana clones a VM, so it needs what a create needs.
            creating=self.kind == CREATE or (self.kind == UPDATE and (params.get("change") or {}).get("kind")
                                             in ("add_node", "rebuild_nodes", "add_kibana")),
            resizing=self.kind == UPDATE and (params.get("change") or {}).get("kind") == "resize")
        if problems:
            raise PreflightFailed(f"the token Terraform uses is missing rights this operation needs: "
                                  f"{'; '.join(problems)}. Fix its permissions in Proxmox, then retry")
        log(self.db, self.op.id, "the token Terraform uses has the rights this operation needs")

    def _env(self) -> Mapping[str, str]:
        """The only credentials Terraform gets: the Proxmox token and the state database.

        The token is the connection's own Terraform token when it has one (narrow, pool-scoped), and otherwise the
        discovery token, so connections set up before the split keep working.
        """
        token_id, secret = self._proxmox_token()
        state_url = tf_state_conninfo(get_settings())
        if not state_url:
            raise TerraformError("Terraform state has nowhere to live: set ECM_TF_STATE_URL, or run ECM on PostgreSQL")
        return {"PROXMOX_VE_API_TOKEN": f"{token_id}={secret}", "PG_CONN_STR": state_url}

    def _fresh(self) -> Operation:
        self.db.refresh(self.op)
        return self.op

    # -- phases --

    def render(self) -> None:
        open_workspace(self.root, self.cluster_id, self._rendered())

    def init(self) -> None:
        self.runner.init(existing_workspace(self.root, self.cluster_id), self._env())

    def plan(self) -> None:
        self._preflight()  # before anything is planned: a plan only reads, so it cannot see lost write rights
        ws = existing_workspace(self.root, self.cluster_id)
        outcome = self.runner.plan(ws, self._env(), destroy=self.kind == DESTROY)
        kind = self._change_kind()
        if kind == "remove_nodes":
            problems = self._removal_problems(outcome.summary)
        elif kind == "rebuild_nodes":
            problems = self._rebuild_problems(outcome.summary)
        elif kind == "forget_nodes":
            problems = check_forget_plan(outcome.summary, frozenset(self._change_nodes("removed")))
        elif kind == "add_kibana":
            problems = self._kibana_problems(outcome.summary)
        else:
            problems = check_plan_safety(outcome.summary, self.plan_kind)
        if self.kind == DESTROY:
            problems += self._outside_the_create(outcome.summary)
        if problems:
            ws.discard_plan()
            raise PlanRejected("; ".join(problems))
        configure = self._configure_description()
        stored = ws.save_plan(self.plan_kind, self._rendered(), outcome.summary, configure=configure)
        op = self._fresh()
        op.plan_digest = stored.approval_digest
        op.plan_summary = {**outcome.summary.to_json(), "has_changes": not outcome.summary.is_empty,
                           "configure": configure or None}
        self.db.commit()
        log(self.db, op.id, f"plan {stored.approval_digest}: {outcome.summary.adds} to add, "
                            f"{outcome.summary.updates} to change, {outcome.summary.deletes} to destroy")

    def _change_kind(self) -> str | None:
        return (self.op.params.get("change") or {}).get("kind") if self.kind == UPDATE else None

    def _change_nodes(self, key: str) -> list[str]:
        """The node names a change lists under `key` (removed, rebuilt or added), or [] when it is another kind of change."""
        return list((self.op.params.get("change") or {}).get(key) or []) if self.kind == UPDATE else []

    def _already_made(self, key: str) -> bool:
        """True when an earlier apply of this operation made every machine it names under `key` (rebuilt, kibana_added): the result is
        kept across a retry and lists them in the state it recorded. Then the plan has nothing to create, which is right."""
        result = self.op.result or {}
        have = {node_of(a) for a in result.get("resources_in_state") or []}
        return bool(result.get("ok")) and set(self._change_nodes(key)) <= have

    def _kibana_problems(self, summary) -> list[str]:
        if summary.is_empty and self._already_made("kibana_added"):
            return []
        return check_add_kibana_plan(summary, frozenset(self._change_nodes("kibana_added")))

    def _rebuild_problems(self, summary) -> list[str]:
        if summary.is_empty and self._already_made("rebuilt"):
            return []
        return check_rebuild_plan(summary, frozenset(self._change_nodes("rebuilt")))

    def _removing(self) -> list[str]:
        """The nodes this operation removes, or [] when it is not a removal."""
        change = (self.op.params.get("change") or {}) if self.kind == UPDATE else {}
        return list(change.get("removed") or []) if change.get("kind") == "remove_nodes" else []

    def _already_removed(self) -> bool:
        """True when an earlier apply of this operation destroyed every machine it names: the result is kept across a
        retry, and none of them is in the state it recorded. Then the plan has nothing to delete, which is right."""
        result = self.op.result or {}
        left = {node_of(a) for a in result.get("resources_in_state") or []}
        return bool(result.get("ok")) and not (set(self._removing()) & left)

    def _removal_problems(self, summary) -> list[str]:
        if summary.is_empty and self._already_removed():
            return []
        return check_removal_plan(summary, frozenset(self._removing()))

    def _outside_the_create(self, summary) -> list[str]:
        """A cleanup may only delete what ECM recorded in this cluster's state: what its create recorded, and what any
        later change to it (a node added) recorded when it applied. Each apply records the whole state list, so the
        newest one covers the older ones; both are read so a failed later apply cannot narrow it."""
        parent = self.db.get(Operation, self.op.parent_op_id or "")
        mine = set((parent.result or {}).get("resources_in_state") or []) if parent else set()
        if parent is not None and parent.cluster_id:
            later = self.db.scalars(select(Operation).where(
                Operation.cluster_id == parent.cluster_id, Operation.kind == UPDATE, Operation.dry_run.is_(False))).all()
            for op in later:
                mine |= set((op.result or {}).get("resources_in_state") or [])
        return [f"cleanup would delete {c.address}, which ECM did not record making"
                for c in summary.changes if c.action == "delete" and c.address not in mine]

    def _nothing_to_do(self) -> bool:
        """True only when a plan was recorded and it has no changes. A missing plan is never 'nothing to do':
        that would skip the approval gate."""
        if self._change_kind() == "forget_nodes":
            return False        # the plan is empty by design, and dropping nodes from the record is still approved
        summary = self._fresh().plan_summary
        return summary is not None and summary.get("has_changes") is False

    def approval(self) -> None:
        if self._nothing_to_do():
            log(self.db, self.op.id, "the plan has no changes, so there is nothing to approve")
            return
        op = self._fresh()
        if op.dry_run:
            raise ApplyRefused("a dry run can never be approved")
        if op.approved_digest is None:
            raise AwaitingApproval()
        if op.approved_digest != op.plan_digest:
            raise ApplyRefused("the approval is for a different plan; plan again")

    def apply(self) -> None:
        op = self._fresh()
        if self._nothing_to_do():
            log(self.db, op.id, "nothing to apply")
            self._adopt_params()  # Terraform already matches what was asked for
            self._forget_removed()
            return
        if op.dry_run or not op.approved_digest:
            raise ApplyRefused("apply needs an approved plan")
        ws = existing_workspace(self.root, self.cluster_id)
        stored = ws.verify_for_apply(self.plan_kind)  # raises StalePlan if anything changed since the plan
        if stored.approval_digest != op.approved_digest:
            raise ApplyRefused("the plan on disk is not the one that was approved; plan again")
        if self.kind in (DESTROY, UPDATE):
            foreign = foreign_machines(self.db, op.params)
            if foreign:
                raise ApplyRefused("a teardown only destroys machines ECM created, and these are not: "
                                   + ", ".join(foreign))
        log(self.db, op.id, f"applying approved plan {op.approved_digest}")
        outcome = self.runner.apply(ws, self._env())
        op.result = {"ok": outcome.ok, "error": outcome.error, "resources_in_state": outcome.resources_in_state,
                     "outputs": json.loads(json.dumps(outcome.outputs, default=str))}
        self.db.commit()
        ws.discard_plan()  # the plan is spent: an approval covers one apply, never a second
        if outcome.ok and self.kind == DESTROY and not outcome.resources_in_state:
            self._forget_cluster()
        if outcome.ok and self.kind == UPDATE:
            self._adopt_params()
            self._forget_removed()
        if not outcome.ok:
            raise ApplyFailed(f"{outcome.error}. Nothing was destroyed; {len(outcome.resources_in_state)} "
                              "resource(s) are in state. Retry re-plans and needs a new approval")


    # -- configure: build the cluster on the machines Terraform made -------------------------------------

    def _state(self) -> DesiredState:
        return DesiredState.model_validate(self.op.params["state"])

    def _configure_description(self) -> str:
        """What a create will do to the machines. Part of the approved digest. Empty when nothing is configured."""
        if self.kind == UPDATE:
            return str((self.op.params.get("change") or {}).get("describe") or "")
        if self.kind != CREATE:
            return ""
        state = self._state()
        n = len(state.nodes)
        return f"install elasticsearch {state.version} on {n} node{'s' if n != 1 else ''} and start the cluster"

    def _credential(self, name: str) -> Credential | None:
        return self.db.scalar(select(Credential).where(Credential.name == name))

    def _store(self, kind: str, name: str, value: str) -> Credential:
        cred = self._credential(name)
        if cred is None:
            cred = Credential(kind=kind, name=name, ciphertext=crypto.encrypt(value))
            self.db.add(cred)
        else:
            cred.ciphertext, cred.rotated_at = crypto.encrypt(value), datetime.now(UTC)
        self.db.flush()
        return cred

    def _names(self) -> tuple[str, str, str]:
        return (f"es-elastic-{self.cluster_id}", f"es-ca-key-{self.cluster_id}", f"es-api-key-{self.cluster_id}")

    def _elastic_password(self) -> str:
        """The elastic user's first password. Made once and kept encrypted until the bootstrap succeeds, so a
        retry after a crash hands Ansible the same one: the first start has already put it in the keystore."""
        name = self._names()[0]
        cred = self._credential(name)
        if cred is not None:
            value = crypto.decrypt(cred.ciphertext)
        else:
            value = secrets.token_urlsafe(32)
            self._store("es_elastic", name, value)
            self.db.commit()
        crypto.register_secret(value)
        return value

    def _stored_ca(self, cluster: Cluster) -> tuple[str | None, str | None]:
        key = self._credential(self._names()[1])
        if cluster.tls_ca_pem and key is not None:
            return cluster.tls_ca_pem, crypto.decrypt(key.ciphertext)
        return None, None

    def _store_ca(self, cluster: Cluster, ca: NewCa) -> None:
        self._store("es_ca_key", self._names()[1], ca.key_pem)
        cluster.tls_ca_pem = ca.cert_pem  # the certificate is public; the key is only in the credential
        self.db.commit()
        log(self.db, self.op.id, "the cluster CA was stored (encrypted)")

    def _adopt_params(self) -> None:
        """Terraform now has what this update asked for, so that is the cluster's desired state, even if the
        converge that follows fails: the next change must start from what is really there."""
        if self.kind != UPDATE:
            return
        cluster = self.db.get(Cluster, self.cluster_id)
        cluster.desired = {k: copy.deepcopy(v) for k, v in self.op.params.items() if k != "change"}
        self.db.commit()

    def _converge(self) -> None:
        """Bring the nodes in line with the change Terraform made. A converge never restarts a node."""
        cluster = self.db.get(Cluster, self.cluster_id)
        params = self.op.params
        profile = NetworkProfile.model_validate(params["profile"])
        ca_cert, ca_key = self._stored_ca(cluster)
        request = AnsibleRequest(
            state=self._state(), addresses=params["addresses"], kind="converge",
            bootstrapped_at=cluster.bootstrapped_at, search_domain=profile.search_domain,
            ca_cert_pem=ca_cert, ca_key_pem=ca_key)
        log(self.db, self.op.id, f"configuring: {self._configure_description()}")
        kept = "What Terraform changed is kept; retry runs the converge again"
        try:
            outcome = self.ansible.run(request)
        except AnsibleError as e:
            raise ConfigureFailed(f"{e}. {kept}") from e
        if outcome.new_ca is not None:
            self._store_ca(cluster, outcome.new_ca)
        self._note_pending(cluster, outcome.pending_restart)          # even if the run then failed: the files were written
        if not outcome.ok:
            raise ConfigureFailed(f"{outcome.error or 'the converge failed'}. {kept}")
        log(self.db, self.op.id, "the change is applied on every node")

    def _note_pending(self, cluster: Cluster, names: list[str]) -> None:
        """Remember which nodes this run left with a configuration change that only a restart applies, so the Restart nodes panel can say
        so. An entry is dropped when the node is seen to have restarted since (the sync checks its uptime) or when ECM restarts it."""
        if not names:
            return
        now = datetime.now(UTC).isoformat()
        cluster.pending_restart = {**(cluster.pending_restart or {}), **dict.fromkeys(names, now)}
        self.db.commit()
        log(self.db, self.op.id, f"{', '.join(names)} {'is' if len(names) == 1 else 'are'} now waiting for a restart to apply the change")

    def _converge_if_a_master_left(self) -> None:
        """After nodes leave, bring the remaining nodes' configuration in line, but only when something in it refers to a node that left. The
        only such thing is the seed list, which names the master-eligible nodes; taking out a data, ingest, ML or coordinating node
        changes nothing a remaining node's configuration says, so a converge would only rewrite whatever else had drifted. A node whose
        record has no flag (an operation planned before this was known) is treated as master-eligible, which runs the converge."""
        change = self.op.params.get("change") or {}
        if any(info.get("master_eligible", True) for info in (change.get("nodes") or {}).values()):
            log(self.db, self.op.id, "a master-eligible node left the seed lists, so the remaining nodes are brought in line")
            self._converge()
            return
        log(self.db, self.op.id, "no remaining node's configuration refers to the nodes that left (only master-eligible nodes are in the "
                                 "seed lists), so nothing is reconfigured")

    def restart(self) -> None:
        """Restart the nodes that are not yet at their new size, one at a time (playbooks/rolling_restart.yml). It
        asks Elasticsearch about the cluster with ECM's API key and asks Proxmox to restart each VM with the
        Terraform token, and a node already at its target size is skipped, so a retry resumes where it stopped."""
        cluster = self.db.get(Cluster, self.cluster_id)
        params = self.op.params
        conn = _connection(self.db, params)
        api_key = self._credential(self._names()[2])
        if api_key is None or not cluster.tls_ca_pem:
            raise RestartFailed("ECM has no API key or CA certificate for this cluster, so it cannot check the "
                                "cluster's health between restarts")
        token_id, token_secret = self._proxmox_token()
        profile = NetworkProfile.model_validate(params["profile"])
        request = AnsibleRequest(
            state=self._state(), addresses=params["addresses"], kind="restart",
            bootstrapped_at=cluster.bootstrapped_at, search_domain=profile.search_domain,
            vm_ids=params["vm_ids"], placement=params["placement"],
            es_api_key=crypto.decrypt(api_key.ciphertext), es_ca_pem=cluster.tls_ca_pem,
            pve_api_url=conn.api_url, pve_token_id=token_id, pve_token_secret=token_secret,
            pve_ca_pem=conn.tls_ca_pem, pve_verify_tls=conn.tls_verify)
        log(self.db, self.op.id, "restarting the nodes one at a time, masters last")
        resumes = "Nodes already restarted stay restarted; retry resumes with the nodes not yet at their new size"
        try:
            outcome = self.ansible.run(request)
        except AnsibleError as e:
            raise RestartFailed(f"{e}. {resumes}") from e
        if not outcome.ok:
            raise RestartFailed(f"{outcome.error or 'the rolling restart failed'}. {resumes}")
        log(self.db, self.op.id, "every node runs at its new size and the cluster is green")

    def _removal_request(self, kind: str) -> AnsibleRequest:
        """The request for the drain or the check after it. The state and addresses are what REMAINS; the names of the
        nodes going are in `removing`. It needs ECM's API key and the cluster's CA to ask the cluster."""
        cluster = self.db.get(Cluster, self.cluster_id)
        params = self.op.params
        api_key = self._credential(self._names()[2])
        if api_key is None or not cluster.tls_ca_pem:
            raise DrainFailed("ECM has no API key or CA certificate for this cluster, so it cannot ask the cluster to "
                              "move the data off the nodes. Nothing was destroyed")
        profile = NetworkProfile.model_validate(params["profile"])
        return AnsibleRequest(
            state=self._state(), addresses=params["addresses"], kind=kind, bootstrapped_at=cluster.bootstrapped_at,
            search_domain=profile.search_domain, removing=self._removing(),
            es_api_key=crypto.decrypt(api_key.ciphertext), es_ca_pem=cluster.tls_ca_pem)

    def drain(self) -> None:
        """Have Elasticsearch move every shard off the nodes being removed, while they still run (playbooks/
        remove_nodes.yml, phase drain). Nothing is destroyed here; if the nodes cannot be emptied the playbook cancels the
        shutdowns and stops. A node that is already gone is skipped, so a retry after the apply passes this step."""
        log(self.db, self.op.id, f"asking Elasticsearch to move the data off {', '.join(self._removing())}")
        try:
            outcome = self.ansible.run(self._removal_request("remove_drain"))
        except AnsibleError as e:
            raise DrainFailed(f"{e}. Nothing was destroyed") from e
        if not outcome.ok:
            raise DrainFailed(f"{outcome.error or 'the nodes could not be emptied'}. Nothing was destroyed; Retry plans "
                              "the removal again and needs a new approval")
        log(self.db, self.op.id, "the nodes hold no shards, so they can be destroyed")

    def _removal_check(self) -> None:
        """After Terraform destroyed the machines: the cluster must be green with the nodes that remain (playbooks/
        remove_nodes.yml, phase after), and the leftover shutdown records are cleared."""
        kept = "The machines are gone; retry runs the check again"
        try:
            outcome = self.ansible.run(self._removal_request("remove_check"))
        except (AnsibleError, DrainFailed) as e:
            raise ConfigureFailed(f"{e}. {kept}") from e
        if not outcome.ok:
            raise ConfigureFailed(f"{outcome.error or 'the cluster is not green without the removed nodes'}. {kept}")
        log(self.db, self.op.id, "the cluster is green with the nodes that remain")

    def _forget_removed(self) -> None:
        """Drop the stored rows of the machines and nodes this removal destroyed, rather than waiting for the next sync,
        so the inventory does not show a machine that is gone. A row is matched on connection, VMID and name together, so
        a different VM that reuses a VMID is never touched; if a machine somehow still exists the next sync adds it back."""
        change = (self.op.params.get("change") or {}) if self.kind == UPDATE else {}
        if change.get("kind") not in ("remove_nodes", "forget_nodes"):
            return
        conn_id = self.op.params.get("proxmox_connection_id")
        names = list(change.get("removed") or [])
        gone = sum(self.db.execute(delete(Vm).where(Vm.connection_id == conn_id, Vm.vmid == int(info["vm_id"]),
                                                    Vm.name == name)).rowcount
                   for name, info in (change.get("nodes") or {}).items())
        self.db.execute(delete(EsNode).where(EsNode.cluster_id == self.cluster_id, EsNode.name.in_(names)))
        cluster = self.db.get(Cluster, self.cluster_id)
        if cluster is not None and cluster.pending_restart:
            left = {n: t for n, t in cluster.pending_restart.items() if n not in names}
            cluster.pending_restart = left or None
        self.db.commit()
        log(self.db, self.op.id, f"{', '.join(names)} removed from the inventory ({gone} machine{'s' if gone != 1 else ''})")

    def _add_nodes(self, rebuild: bool = False) -> None:
        """Configure and start only the nodes this change added, then check that they joined and the cluster is green
        (playbooks/add_node.yml). The existing nodes are not touched. It needs ECM's API key (to ask the cluster) and
        the cluster's CA (to sign the new nodes' certificates)."""
        cluster = self.db.get(Cluster, self.cluster_id)
        params = self.op.params
        api_key = self._credential(self._names()[2])
        ca_cert, ca_key = self._stored_ca(cluster)
        if api_key is None or ca_cert is None or ca_key is None:
            raise ConfigureFailed("ECM has no API key or CA for this cluster, so it cannot sign the new nodes' "
                                  "certificates or check that they joined. The new machines are kept")
        profile = NetworkProfile.model_validate(params["profile"])
        request = AnsibleRequest(
            state=self._state(), addresses=params["addresses"], kind="add_node",
            bootstrapped_at=cluster.bootstrapped_at, search_domain=profile.search_domain,
            new_nodes=self._change_nodes("rebuilt" if rebuild else "added"), rebuild=rebuild,
            es_api_key=crypto.decrypt(api_key.ciphertext), es_ca_pem=ca_cert, ca_cert_pem=ca_cert, ca_key_pem=ca_key)
        log(self.db, self.op.id, f"configuring: {self._configure_description()}")
        kept = "The new machines are kept; retry runs the configuration again, which is safe to repeat"
        try:
            outcome = self.ansible.run(request)
        except AnsibleError as e:
            raise ConfigureFailed(f"{e}. {kept}") from e
        if not outcome.ok:
            raise ConfigureFailed(f"{outcome.error or 'adding the nodes failed'}. {kept}")
        log(self.db, self.op.id, "the rebuilt nodes joined and the cluster is not red" if rebuild
            else "the new nodes joined and the cluster is green")

    def _kibana_keys(self) -> dict[str, str]:
        """The three encryption keys that protect Kibana's saved objects (alerting connectors, API keys). Made once per cluster and kept
        encrypted, so a replacement Kibana is given the same ones and can still read what the old one saved; losing them loses those
        objects, so a backup of ECM's database is their backup."""
        name = kibana_credential_names(self.cluster_id)[1]
        cred = self._credential(name)
        if cred is not None:
            keys = json.loads(crypto.decrypt(cred.ciphertext))
        else:
            keys = {part: secrets.token_urlsafe(48) for part in ("security", "saved_objects", "reporting")}
            self._store("es_kibana_keys", name, json.dumps(keys))
            self.db.commit()
        for value in keys.values():
            crypto.register_secret(value)
        return keys

    def _add_kibana(self) -> None:
        """Install and start Kibana on the machine this change made, and check it reports itself available (playbooks/add_kibana.yml).
        No Elasticsearch node is configured or restarted. It needs ECM's API key (to ask for the service token and to ask Kibana its
        status) and the cluster's CA (to sign Kibana's certificate)."""
        cluster = self.db.get(Cluster, self.cluster_id)
        params = self.op.params
        api_key = self._credential(self._names()[2])
        ca_cert, ca_key = self._stored_ca(cluster)
        if api_key is None or ca_cert is None or ca_key is None:
            raise ConfigureFailed("ECM has no API key or CA for this cluster, so it cannot make Kibana's token, sign its certificate "
                                  "or check it. The new machine is kept")
        profile = NetworkProfile.model_validate(params["profile"])
        wanted = set(self._change_nodes("kibana_added"))
        hosts = [KibanaHost(name=k.name, address=k.address, public_url=k.public_url)
                 for k in kibana_of(params) if k.name in wanted]
        token_name = kibana_credential_names(self.cluster_id)[0]
        held = self._credential(token_name)
        request = AnsibleRequest(
            state=self._state(), addresses=params["addresses"], kind="add_kibana",
            bootstrapped_at=cluster.bootstrapped_at, search_domain=profile.search_domain, kibana=hosts,
            kibana_token=crypto.decrypt(held.ciphertext) if held is not None else None, kibana_keys=self._kibana_keys(),
            es_api_key=crypto.decrypt(api_key.ciphertext), es_ca_pem=ca_cert, ca_cert_pem=ca_cert, ca_key_pem=ca_key)
        log(self.db, self.op.id, f"configuring: {self._configure_description()}")
        kept = "The new machine is kept; retry runs the configuration again with the same token and keys, which is safe to repeat"
        try:
            outcome = self.ansible.run(request)
        except AnsibleError as e:
            raise ConfigureFailed(f"{e}. {kept}") from e
        if outcome.kibana_token:
            # Even when the run then failed: the cluster will not show this token again, and a retry must not make a second one.
            self._store("es_kibana_token", token_name, outcome.kibana_token)
            self.db.commit()
            log(self.db, self.op.id, "Kibana's service-account token was stored (encrypted)")
        if not outcome.ok:
            raise ConfigureFailed(f"{outcome.error or 'adding Kibana failed'}. {kept}")
        log(self.db, self.op.id, "Kibana is running and reports itself available")

    def configure(self) -> None:
        if self.kind == UPDATE:
            kind = (self.op.params.get("change") or {}).get("kind")
            if kind == "add_node":
                self._add_nodes()
            elif kind == "rebuild_nodes":
                self._add_nodes(rebuild=True)
            elif kind == "add_kibana":
                self._add_kibana()
            elif kind == "remove_nodes":
                self._converge_if_a_master_left()
                self._removal_check()
            elif kind == "forget_nodes":
                self._converge_if_a_master_left()   # nodes that were already gone; there is nothing to check afterwards
            else:
                self._converge()
            return
        cluster = self.db.get(Cluster, self.cluster_id)
        if cluster.bootstrapped_at is not None:
            log(self.db, self.op.id, "the cluster has already bootstrapped; nothing to configure")
            return
        params = self.op.params
        state = self._state()
        profile = NetworkProfile.model_validate(params["profile"])
        ca_cert, ca_key = self._stored_ca(cluster)
        request = AnsibleRequest(
            state=state, addresses=params["addresses"], kind="create", bootstrapped_at=None,
            search_domain=profile.search_domain, elastic_password=self._elastic_password(),
            ca_cert_pem=ca_cert, ca_key_pem=ca_key)
        log(self.db, self.op.id, f"configuring: {self._configure_description()}")
        try:
            outcome = self.ansible.run(request)
        except AnsibleError as e:
            raise ConfigureFailed(str(e)) from e
        if outcome.new_ca is not None:
            self._store_ca(cluster, outcome.new_ca)  # even when the run failed: the nodes may already trust it
        if not outcome.ok or outcome.result is None:
            raise ConfigureFailed(f"{outcome.error or 'the create handed back no result'}. The machines, the "
                                  "stored password and any CA are kept; retry resumes the configure step")
        result = outcome.result
        api_key = self._store("es_api_key", self._names()[2], result.api_key_encoded)
        cluster.credential_id = api_key.id
        cluster.es_cluster_uuid = result.cluster_uuid
        cluster.es_version = state.version
        cluster.health_status = result.status
        cluster.endpoint_urls = [f"https://{params['addresses'][n.name]}:{ES_HTTP_PORT}" for n in state.nodes]
        cluster.tls_verify = True
        cluster.bootstrapped_at = datetime.now(UTC)
        cluster.desired = copy.deepcopy(params)
        elastic = self._credential(self._names()[0])
        if elastic is not None:
            self.db.delete(elastic)  # used once, to bootstrap; ECM reaches the cluster with the API key from now on
        op = self._fresh()
        op.result = {**(op.result or {}), "configured": {"cluster_uuid": result.cluster_uuid,
                                                         "status": result.status,
                                                         "number_of_nodes": result.number_of_nodes}}
        self.db.commit()
        log(self.db, op.id, f"the cluster bootstrapped: {result.number_of_nodes} nodes, {result.status}")

    def _forget_cluster(self) -> None:
        """A teardown removed every machine, so nothing of the cluster is left to reach or to trust. Clearing this
        lets the same name be created again and bootstrap from scratch. The nodes discovery last saw go too:
        they are only ever pruned by a successful sync, and with no endpoints none can run, so they would stay
        on the dashboard as nodes of a cluster whose machines no longer exist."""
        cluster = self.db.get(Cluster, self.cluster_id)
        cluster.bootstrapped_at = cluster.es_cluster_uuid = cluster.credential_id = None
        cluster.tls_ca_pem = cluster.endpoint_urls = cluster.health_status = cluster.es_version = None
        cluster.snapshot = cluster.last_sync_at = cluster.last_sync_error = cluster.desired = None
        self.db.execute(delete(EsNode).where(EsNode.cluster_id == self.cluster_id))
        gone = self._forget_machines()
        self.db.flush()
        for name in (*self._names(), *kibana_credential_names(self.cluster_id)):
            cred = self._credential(name)
            if cred is not None:
                self.db.delete(cred)
        self.db.commit()
        log(self.db, self.op.id, "the cluster's stored credentials and CA were removed with its machines"
            + (f", and {gone} destroyed machine{'s' if gone != 1 else ''} dropped from the Proxmox inventory" if gone else ""))
        self._remove_record()

    def _remove_record(self) -> None:
        """Tearing a cluster down removes ECM's record of it too: with its machines gone there is nothing left for
        the record to describe. It stays only if something still blocks it (a VM that carries one of its names), and
        the log says what. The operations are kept, detached from the cluster, as the history."""
        cluster = self.db.get(Cluster, self.cluster_id)
        if cluster is None:
            return
        blocker = _removal_blocker(self.db, cluster, tearing_down=self._fresh())
        if blocker:
            log(self.db, self.op.id, f"the cluster's record was kept: {blocker}")
            return
        out = _delete_record(self.db, cluster, self.op.created_by or "worker", reason="teardown",
                             operation=self.op.id)
        log(self.db, self.op.id, f"the cluster's record was removed; its {out['operations_kept']} operations are "
                                 "kept as history")

    def _forget_machines(self) -> int:
        """Drop the stored Proxmox rows of the machines this teardown destroyed. Only a Proxmox sync removes them
        otherwise, and until it runs (every few minutes) the old names block removing the cluster's record and
        creating the same name again. A row is matched on connection, name and VMID together, so a different VM
        that reuses a VMID is never touched; if a machine somehow still exists, the next sync adds it back."""
        params = self.op.params or {}
        conn_id = params.get("proxmox_connection_id")
        gone = 0
        for name, vmid in machine_vm_ids(params).items():
            gone += self.db.execute(delete(Vm).where(Vm.connection_id == conn_id, Vm.vmid == int(vmid),
                                                     Vm.name == name)).rowcount
        return gone
