"""Terraform operations: tf.create, and tf.destroy used to clean up or tear down a create that has finished.

Phases:  render, init, plan, approval, apply   (a dry run stops after plan)

  * render, init and plan change nothing on Proxmox or any Elasticsearch cluster. `init` with the pg backend
    does create the cluster's empty state schema in ECM's own state database.
  * plan stores a digest that covers the operation kind, the rendered configuration and the plan file. The
    operation then pauses in `pending_approval` and the job ends; no worker is held while a person decides.
  * approval is a click on that digest (operations.approve_operation). It enqueues the same job, which resumes.
  * apply re-checks the stored plan against the files on disk and against the approved digest, then applies
    that saved plan file and nothing else.

Nothing here destroys on failure. A failed create keeps its partial state and records what exists. Cleaning
it up, or tearing down a create that succeeded, is a separate tf.destroy operation that a person starts by
typing the cluster name, that has its own plan and its own approval, and that may only delete resources the
create recorded in state.
"""
import json
from collections.abc import Callable, Mapping
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, crypto
from app.config import get_settings, tf_state_conninfo
from app.desired.models import DesiredState
from app.desired.network import NetworkProfile
from app.models import Cluster, Credential, Operation, ProxmoxConnection
from app.operations import AwaitingApproval, create_operation, log, run_phases
from app.provisioning.plan import check_plan_safety
from app.provisioning.render import RenderError, RenderInput, TemplateRef, render_workspace
from app.provisioning.runner import CliTerraformRunner, TerraformError, TerraformRunner
from app.provisioning.workspace import existing_workspace, open_workspace

CREATE = "tf.create"
DESTROY = "tf.destroy"
PHASES = ["render", "init", "plan", "approval", "apply"]
DRY_RUN_PHASES = ["render", "init", "plan"]  # a dry run has no approval or apply step to run
# The kind the plan safety rules and the stored plan use.
PLAN_KIND = {CREATE: "create", DESTROY: "destroy"}

RunnerFactory = Callable[[Callable[[str], None]], TerraformRunner]


class OperationRefused(Exception):
    """A Terraform operation cannot be started. The message says why and is safe to show."""


class PlanRejected(Exception):
    """The plan does more than this kind of operation may do. It is never offered for approval."""


class ApplyRefused(Exception):
    """Apply did not start because the plan is stale or does not match the approval."""


class ApplyFailed(Exception):
    """Terraform started the apply and it failed. Partial state is kept; nothing was destroyed."""


# ---- inputs ---------------------------------------------------------------------------------------------

def render_input(params: dict, cluster_id: str, endpoint: str, insecure: bool) -> RenderInput:
    """Rebuild the render input from the parameters stored on the operation."""
    return RenderInput(
        cluster_id=cluster_id,
        state=DesiredState.model_validate(params["state"]),
        placement=params["placement"], addresses=params["addresses"], vm_ids=params["vm_ids"],
        profile=NetworkProfile.model_validate(params["profile"]),
        template=TemplateRef(params["template"]["node_name"], params["template"]["vm_id"]),
        proxmox_endpoint=endpoint, proxmox_insecure=insecure,
        datastore_id=params.get("datastore_id", "tank"), pool_id=params.get("pool_id", "ecm"),
        cpu_type=params.get("cpu_type", "host"))


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
    op = create_operation(db, CREATE, DRY_RUN_PHASES if dry_run else PHASES, cluster_id=cluster_id,
                          params=params, actor=actor, dry_run=dry_run)
    audit.record(db, actor, "operation.start", "operation", op.id, kind=CREATE, dry_run=dry_run)
    return op


def start_cleanup(db: Session, *, create_op_id: str, confirm_name: str, actor: str) -> Operation:
    """Create the destroy operation that removes what a create made: the partial result of one that failed, or
    everything a create that succeeded built.

    Allowed only for a finished tf.create whose apply left resources in state, on a managed cluster, once, and
    only after the person types the cluster name. The plan it produces can delete nothing the create did not
    record (see _outside_the_create), and it needs its own approval.
    """
    parent = db.get(Operation, create_op_id)
    if parent is None or parent.kind != CREATE:
        raise OperationRefused("cleanup applies to a create operation")
    if parent.state not in ("failed", "succeeded"):
        raise OperationRefused(f"the create is {parent.state}; it can be cleaned up once it has finished")
    cluster = _managed_cluster(db, parent.cluster_id)
    if confirm_name != cluster.name:
        raise OperationRefused("type the cluster name exactly to confirm the cleanup")
    if db.scalar(select(Operation.id).where(Operation.parent_op_id == parent.id, Operation.kind == DESTROY,
                                            Operation.state == "succeeded")):
        raise OperationRefused("this create has already been cleaned up")
    left = (parent.result or {}).get("resources_in_state") or []
    if not left:
        raise OperationRefused("the create left nothing in Terraform state, so there is nothing to clean up")
    _check_params(db, cluster.id, parent.params)
    op = create_operation(db, DESTROY, PHASES, cluster_id=cluster.id, params=parent.params, actor=actor,
                          parent_op_id=parent.id)
    audit.record(db, actor, "operation.start", "operation", op.id, kind=DESTROY, parent=parent.id,
                 parent_state=parent.state, resources=len(left))
    return op


# ---- running them ---------------------------------------------------------------------------------------

def default_runner(line_log: Callable[[str], None]) -> TerraformRunner:
    s = get_settings()
    return CliTerraformRunner(binary=s.terraform_binary, plugin_dir=s.terraform_plugin_dir, log=line_log)


def run_operation(db: Session, op_id: str, make_runner: RunnerFactory = default_runner,
                  root: Path | None = None) -> None:
    """Run or resume a Terraform operation. This is the body of the `tf.run` job."""
    op = db.get(Operation, op_id)
    handlers = _Handlers(db, op, make_runner, root or Path(get_settings().tf_workspace_root)).handlers()
    run_phases(db, op_id, handlers)


class _Handlers:
    def __init__(self, db: Session, op: Operation, make_runner: RunnerFactory, root: Path):
        self.db, self.op, self.root = db, op, root
        self.kind = op.kind
        self.plan_kind = PLAN_KIND[op.kind]
        self.cluster_id = op.cluster_id or ""
        self.runner = make_runner(lambda line: log(db, op.id, line, "terraform"))

    def handlers(self) -> dict[str, Callable[[], None]]:
        return {"render": self.render, "init": self.init, "plan": self.plan,
                "approval": self.approval, "apply": self.apply}

    # -- helpers --

    def _rendered(self) -> dict[str, str]:
        conn = _connection(self.db, self.op.params)
        return render_workspace(render_input(self.op.params, self.cluster_id, conn.api_url, not conn.tls_verify))

    def _env(self) -> Mapping[str, str]:
        """The only credentials Terraform gets: the Proxmox token and the state database.

        The token is the connection's own Terraform token when it has one (narrow, pool-scoped), and otherwise the
        discovery token, so connections set up before the split keep working.
        """
        conn = _connection(self.db, self.op.params)
        separate = bool(conn.terraform_credential_id and conn.terraform_token_id)
        credential_id = conn.terraform_credential_id if separate else conn.credential_id
        token_id = conn.terraform_token_id if separate else conn.token_id
        secret = crypto.decrypt(self.db.get(Credential, credential_id).ciphertext)
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
        ws = existing_workspace(self.root, self.cluster_id)
        outcome = self.runner.plan(ws, self._env(), destroy=self.kind == DESTROY)
        problems = check_plan_safety(outcome.summary, self.plan_kind)
        if self.kind == DESTROY:
            problems += self._outside_the_create(outcome.summary)
        if problems:
            ws.discard_plan()
            raise PlanRejected("; ".join(problems))
        stored = ws.save_plan(self.plan_kind, self._rendered(), outcome.summary)
        op = self._fresh()
        op.plan_digest = stored.approval_digest
        op.plan_summary = {**outcome.summary.to_json(), "has_changes": not outcome.summary.is_empty}
        self.db.commit()
        log(self.db, op.id, f"plan {stored.approval_digest}: {outcome.summary.adds} to add, "
                            f"{outcome.summary.updates} to change, {outcome.summary.deletes} to destroy")

    def _outside_the_create(self, summary) -> list[str]:
        """A cleanup may only delete what the create it belongs to recorded in state."""
        parent = self.db.get(Operation, self.op.parent_op_id or "")
        mine = set((parent.result or {}).get("resources_in_state") or []) if parent else set()
        return [f"cleanup would delete {c.address}, which that create did not make"
                for c in summary.changes if c.action == "delete" and c.address not in mine]

    def _nothing_to_do(self) -> bool:
        """True only when a plan was recorded and it has no changes. A missing plan is never 'nothing to do':
        that would skip the approval gate."""
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
            return
        if op.dry_run or not op.approved_digest:
            raise ApplyRefused("apply needs an approved plan")
        ws = existing_workspace(self.root, self.cluster_id)
        stored = ws.verify_for_apply(self.plan_kind)  # raises StalePlan if anything changed since the plan
        if stored.approval_digest != op.approved_digest:
            raise ApplyRefused("the plan on disk is not the one that was approved; plan again")
        log(self.db, op.id, f"applying approved plan {op.approved_digest}")
        outcome = self.runner.apply(ws, self._env())
        op.result = {"ok": outcome.ok, "error": outcome.error, "resources_in_state": outcome.resources_in_state,
                     "outputs": json.loads(json.dumps(outcome.outputs, default=str))}
        self.db.commit()
        ws.discard_plan()  # the plan is spent: an approval covers one apply, never a second
        if not outcome.ok:
            raise ApplyFailed(f"{outcome.error}. Nothing was destroyed; {len(outcome.resources_in_state)} "
                              "resource(s) are in state. Retry re-plans and needs a new approval")
