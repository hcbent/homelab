"""Terraform operations: tf.create, and tf.destroy used to clean up or tear down a create that has finished.

Phases:  render, init, plan, approval, apply, configure   (a dry run stops after plan; a destroy has no configure)

  * render, init and plan change nothing on Proxmox or any Elasticsearch cluster. `init` with the pg backend
    does create the cluster's empty state schema in ECM's own state database.
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
import json
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app import audit, crypto
from app.config import get_settings, tf_state_conninfo
from app.configmgmt import AnsibleError, AnsibleRequest, AnsibleRunner, NewCa, runner_from_settings
from app.desired.models import DesiredState
from app.desired.network import NetworkProfile
from app.discovery import factory, proxmox
from app.discovery.http import DiscoveryError
from app.models import ACTIVE_STATES, Cluster, Credential, EsNode, Operation, ProxmoxConnection, Vm
from app.operations import AwaitingApproval, create_operation, log, run_phases
from app.provisioning.plan import check_plan_safety
from app.provisioning.render import RenderError, RenderInput, TemplateRef, render_workspace
from app.provisioning.runner import CliTerraformRunner, TerraformError, TerraformRunner
from app.provisioning.workspace import existing_workspace, open_workspace

CREATE = "tf.create"
DESTROY = "tf.destroy"
PHASES = ["render", "init", "plan", "approval", "apply"]
CREATE_PHASES = [*PHASES, "configure"]  # a real create also builds the cluster on the machines it made
DRY_RUN_PHASES = ["render", "init", "plan"]  # a dry run has no approval or apply step to run
# The kind the plan safety rules and the stored plan use.
PLAN_KIND = {CREATE: "create", DESTROY: "destroy"}

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


class ConfigureFailed(Exception):
    """The machines exist but building the cluster on them failed. The VMs, the stored password and any CA that
    was made are kept; a retry resumes the configure step with them."""


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
    op = create_operation(db, CREATE, DRY_RUN_PHASES if dry_run else CREATE_PHASES, cluster_id=cluster_id,
                          params=params, actor=actor, dry_run=dry_run)
    audit.record(db, actor, "operation.start", "operation", op.id, kind=CREATE, dry_run=dry_run)
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
    cluster = _managed_cluster(db, parent.cluster_id)
    if confirm_name != cluster.name:
        raise OperationRefused("type the cluster name exactly to confirm the cleanup")
    if cluster.bootstrapped_at is not None and not confirm_data_loss:
        raise OperationRefused("this cluster has been bootstrapped: Elasticsearch is installed on its machines and "
                               "any data in it is destroyed with them. Confirm that you accept the data loss "
                               "to continue")
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
                 parent_state=parent.state, resources=len(left), bootstrapped=cluster.bootstrapped_at is not None,
                 data_loss_confirmed=bool(confirm_data_loss))
    return op


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
    if cluster.bootstrapped_at is not None:
        raise OperationRefused("this cluster has bootstrapped: tear its machines down first (cleanup), then remove it")
    ops = db.scalars(select(Operation).where(Operation.cluster_id == cluster.id)).all()
    if any(o.state in ACTIVE_STATES for o in ops):
        raise OperationRefused("an operation is still running on this cluster; wait for it to finish")
    node_names: set[str] = set()
    for op in ops:
        if op.kind != CREATE or op.dry_run:
            continue
        node_names |= {n["name"] for n in (op.params.get("state") or {}).get("nodes", [])}
        built = (op.result or {}).get("resources_in_state") or []
        torn_down = db.scalar(select(Operation.id).where(Operation.parent_op_id == op.id, Operation.kind == DESTROY,
                                                         Operation.state == "succeeded"))
        if built and not torn_down:
            raise OperationRefused("a create of this cluster built machines that have not been torn down through "
                                   f"ECM (operation {op.id}); clean it up first")
    still_there = sorted(node_names & {n for (n,) in db.execute(select(Vm.name)) if n})
    if still_there:
        raise OperationRefused(f"VMs named {', '.join(still_there)} still exist in Proxmox; remove them first")

    suffix = cluster.id
    detached = db.execute(update(Operation).where(Operation.cluster_id == cluster.id)
                          .values(cluster_id=None)).rowcount
    db.execute(delete(EsNode).where(EsNode.cluster_id == cluster.id))
    cluster.credential_id = None
    db.flush()
    db.execute(delete(Credential).where(Credential.name.in_(
        [f"es-elastic-{suffix}", f"es-ca-key-{suffix}", f"es-api-key-{suffix}"])))
    name = cluster.name
    db.delete(cluster)
    audit.record(db, actor, "cluster.remove", "cluster", suffix, name=name, operations_kept=detached)
    db.commit()
    return {"id": suffix, "name": name, "operations_kept": detached}


# ---- running them ---------------------------------------------------------------------------------------

def default_runner(line_log: Callable[[str], None]) -> TerraformRunner:
    s = get_settings()
    return CliTerraformRunner(binary=s.terraform_binary, plugin_dir=s.terraform_plugin_dir, log=line_log)


def default_ansible(line_log: Callable[[str], None]) -> AnsibleRunner:
    return runner_from_settings(get_settings(), log=line_log)


def run_operation(db: Session, op_id: str, make_runner: RunnerFactory = default_runner,
                  root: Path | None = None, make_ansible: AnsibleFactory = default_ansible) -> None:
    """Run or resume a Terraform operation. This is the body of the `tf.run` job."""
    op = db.get(Operation, op_id)
    handlers = _Handlers(db, op, make_runner, root or Path(get_settings().tf_workspace_root),
                         make_ansible).handlers()
    run_phases(db, op_id, handlers)


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
                "approval": self.approval, "apply": self.apply, "configure": self.configure}

    # -- helpers --

    def _rendered(self) -> dict[str, str]:
        conn = _connection(self.db, self.op.params)
        return render_workspace(render_input(self.op.params, self.cluster_id, conn.api_url, not conn.tls_verify))

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
            template_vmid=(params.get("template") or {}).get("vm_id"), creating=self.kind == CREATE)
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
        if outcome.ok and self.kind == DESTROY and not outcome.resources_in_state:
            self._forget_cluster()
        if not outcome.ok:
            raise ApplyFailed(f"{outcome.error}. Nothing was destroyed; {len(outcome.resources_in_state)} "
                              "resource(s) are in state. Retry re-plans and needs a new approval")


    # -- configure: build the cluster on the machines Terraform made -------------------------------------

    def _state(self) -> DesiredState:
        return DesiredState.model_validate(self.op.params["state"])

    def _configure_description(self) -> str:
        """What a create will do to the machines. Part of the approved digest. Empty when nothing is configured."""
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

    def configure(self) -> None:
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
        cluster.snapshot = cluster.last_sync_at = cluster.last_sync_error = None
        self.db.execute(delete(EsNode).where(EsNode.cluster_id == self.cluster_id))
        self.db.flush()
        for name in self._names():
            cred = self._credential(name)
            if cred is not None:
                self.db.delete(cred)
        self.db.commit()
        log(self.db, self.op.id, "the cluster's stored credentials and CA were removed with its machines")
