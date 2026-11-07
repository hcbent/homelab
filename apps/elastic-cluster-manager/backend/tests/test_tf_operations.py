"""Terraform operations wired to the operation state machine, driven by a fake TerraformRunner.

The fake writes a plan file whose bytes depend on what it plans, so the digests behave like the real thing:
a different plan gives a different digest.
"""
import json
import re
from dataclasses import dataclass, field

import httpx
import pytest
from sqlalchemy import select

from app import config, crypto, operations
from app.configmgmt import AnsibleError, AnsibleOutcome, BootstrapResult, HostRecap, NewCa
from app.desired import TopologyPreset, build_desired_state
from app.desired.network import NetworkProfile
from app.discovery import factory
from app.models import (
    AuditEvent,
    Cluster,
    Credential,
    Operation,
    OperationLog,
    OperationStep,
    ProxmoxConnection,
)
from app.provisioning import operation as tfop
from app.provisioning.operation import (
    ApplyFailed,
    ApplyRefused,
    OperationRefused,
    PlanRejected,
    PreflightFailed,
    run_operation,
    start_cleanup,
    start_create,
)
from app.provisioning.plan import summarize_plan
from app.provisioning.runner import ApplyOutcome, PlanOutcome, TerraformError
from app.provisioning.workspace import StalePlan

PROFILE = NetworkProfile(
    name="default", bridge="vmbr0", vlan=10, cidr="192.0.2.0/24", gateway="192.0.2.1", dns=["192.0.2.1"],
    search_domain="lab.example.org", range_start="192.0.2.110", range_end="192.0.2.149")
SECRET = "pve-token-secret-0123456789"
NODES = ["lab-b-01", "lab-b-02", "lab-b-03"]
ADDRS = [f'module.node["{n}"].proxmox_virtual_environment_vm.node' for n in NODES]


# What the token Terraform uses may do on the fake Proxmox, in the shape /access/permissions reports it.
GOOD_PERMS = {"/pool/ecm": {"VM.Allocate": 1, "VM.Audit": 1}, "/storage/tank": {"Datastore.AllocateSpace": 1},
              "/vms/8000": {"VM.Clone": 1}}


def creates(addresses):
    return [(a, "create") for a in addresses]


def pem(label, body):
    """A fake PEM block assembled here so the source holds no literal key armor for a secret scanner to find."""
    return f"-----BEGIN {label}-----\n{body}\n-----END {label}-----\n"


CA_CERT = pem("CERTIFICATE", "FakeCaCertificateBody0000")
CA_KEY = pem("PRIVATE KEY", "FakeCaKeyBodyForTests000000001")
API_KEY = "FakeEncodedApiKeyForTests0000000001"


def good_ansible_outcome():
    return AnsibleOutcome(
        ok=True, recap={n: HostRecap(40, 8, 0, 0) for n in NODES},
        result=BootstrapResult("4Et2nKICTImSzjMyH77utQ", "green", 3, "ZSmjsaEB1M7T5v1mkNOK", API_KEY),
        new_ca=NewCa(CA_CERT, CA_KEY))


@dataclass
class World:
    """What the fake Terraform does, and a record of what it was asked to do."""
    root: object
    create_changes: list = field(default_factory=lambda: creates(ADDRS))
    destroy_changes: list = field(default_factory=lambda: [(a, "delete") for a in ADDRS])
    apply_outcome: ApplyOutcome = field(default_factory=lambda: ApplyOutcome(True, None, list(ADDRS), {"ips": 3}))
    init_error: str | None = None
    calls: list = field(default_factory=list)
    envs: list = field(default_factory=list)
    perms: dict = field(default_factory=lambda: {k: dict(v) for k, v in GOOD_PERMS.items()})
    proxmox_status: int = 200
    proxmox_down: bool = False
    proxmox_seen: list = field(default_factory=list)
    # What the fake Ansible does: the outcome it returns (or the error it raises), and the requests it was given.
    ansible_outcome: AnsibleOutcome = field(default_factory=good_ansible_outcome)
    ansible_error: str | None = None
    ansible_requests: list = field(default_factory=list)

    def factory(self, line_log):
        return FakeRunner(line_log, self)

    def ansible_factory(self, line_log):
        return FakeAnsible(line_log, self)


class FakeAnsible:
    def __init__(self, line_log, world):
        self.log, self.w = line_log, world

    def run(self, request):
        self.w.ansible_requests.append(request)
        self.log("PLAY RECAP *****")
        if self.w.ansible_error:
            raise AnsibleError(self.w.ansible_error)
        return self.w.ansible_outcome


class FakeRunner:
    def __init__(self, line_log, world):
        self.log, self.w = line_log, world

    def init(self, ws, env):
        self.w.calls.append("init")
        self.w.envs.append(dict(env))
        if self.w.init_error:
            raise TerraformError(self.w.init_error)

    def plan(self, ws, env, *, destroy=False):
        self.w.calls.append("plan-destroy" if destroy else "plan")
        changes = self.w.destroy_changes if destroy else self.w.create_changes
        ws.discard_plan()
        ws.plan_path.write_bytes(json.dumps([destroy, changes]).encode())
        summary = summarize_plan({"resource_changes": [{"address": a, "change": {"actions": [act]}}
                                                       for a, act in changes]})
        return PlanOutcome(has_changes=not summary.is_empty, summary=summary)

    def apply(self, ws, env):
        self.w.calls.append("apply")
        return self.w.apply_outcome


@pytest.fixture
def world(session, tmp_path, monkeypatch):
    monkeypatch.setenv("ECM_TF_STATE_URL", "postgresql://tf:statepw1234@db/tfstate")
    config.get_settings.cache_clear()
    w = World(root=tmp_path / "clusters")

    def proxmox(request):                      # the pre-flight asks Proxmox what the token may do
        w.proxmox_seen.append((request.method, request.url.path, request.headers.get("authorization")))
        if w.proxmox_down:
            raise httpx.ConnectError("no route to host")
        if w.proxmox_status != 200:
            return httpx.Response(w.proxmox_status, json={"errors": "permission check failed"})
        return httpx.Response(200, json={"data": w.perms})

    monkeypatch.setattr(factory, "transport", httpx.MockTransport(proxmox))
    return w


@pytest.fixture
def conn(session):
    cred = Credential(kind="proxmox", name="pve", ciphertext=crypto.encrypt(SECRET))
    session.add(cred)
    session.flush()
    c = ProxmoxConnection(name="pve", api_url="https://pve2.lab.example.org:8006/", token_id="ecm@pve!tf",
                          credential_id=cred.id)
    session.add(c)
    session.commit()
    return c


@pytest.fixture
def cluster(session):
    c = Cluster(name="lab-b", ownership="managed")
    session.add(c)
    session.commit()
    return c


def params_for(conn, ram_mb=None):
    state = build_desired_state(TopologyPreset.three_node, "lab-b", "9.4.3")
    if ram_mb:
        for n in state.nodes:
            n.ram_mb = ram_mb
    return {
        "state": state.model_dump(mode="json"),
        "placement": {n: f"pve{i % 3 + 1}" for i, n in enumerate(NODES)},
        "addresses": {n: f"192.0.2.{110 + i}" for i, n in enumerate(NODES)},
        "vm_ids": {n: 500 + i for i, n in enumerate(NODES)},
        "profile": PROFILE.model_dump(mode="json"),
        "template": {"node_name": "pve1", "vm_id": 8000},
        "proxmox_connection_id": conn.id,
    }


def begin(session, cluster, conn, **kw):
    return start_create(session, cluster_id=cluster.id, params=params_for(conn), actor="admin", **kw)


def run(session, world, op):
    run_operation(session, op.id, world.factory, world.root, world.ansible_factory)
    session.refresh(op)
    return op


def steps(session, op):
    return [(s.name, s.status) for s in session.scalars(
        select(OperationStep).where(OperationStep.operation_id == op.id).order_by(OperationStep.seq))]


def workspace_file(world, cluster, name):
    return world.root / cluster.id / "tf" / name


def reach_failed_apply(session, world, cluster, conn):
    """A create whose apply fails after making two of the three VMs."""
    world.apply_outcome = ApplyOutcome(False, "terraform apply failed: Error: clone timed out", ADDRS[:2])
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(ApplyFailed):
        run(session, world, op)
    return op


# ---- the approval gate ---------------------------------------------------------------------------------

def test_create_pauses_at_a_plan_and_applies_only_after_approval(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn))
    assert op.state == "pending_approval" and op.phase == "approval"
    assert steps(session, op) == [("render", "done"), ("init", "done"), ("plan", "done"),
                                  ("approval", "waiting"), ("apply", "pending"), ("configure", "pending")]
    assert op.plan_digest and op.plan_summary["adds"] == 3 and op.plan_summary["deletes"] == 0
    assert "apply" not in world.calls

    run(session, world, op)                                  # a second look changes nothing
    assert op.state == "pending_approval" and "apply" not in world.calls

    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    op = run(session, world, op)
    assert op.state == "succeeded" and world.calls == ["init", "plan", "apply"]
    assert op.approved_by == "admin" and op.approved_digest == op.plan_digest
    assert op.result["resources_in_state"] == ADDRS and op.result["outputs"] == {"ips": 3}
    assert not workspace_file(world, cluster, "plan.tfplan").exists()        # an approval covers one apply


def test_apply_refuses_to_run_without_an_approval(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn))
    handlers = tfop._Handlers(session, op, world.factory, world.root)
    with pytest.raises(ApplyRefused):
        handlers.apply()
    assert "apply" not in world.calls


def test_only_the_digest_the_user_reviewed_can_be_approved(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn))
    for wrong in ("0" * 64, "", op.plan_digest[:-1] + ("0" if op.plan_digest[-1] != "0" else "1")):
        with pytest.raises(operations.ApprovalRefused):
            operations.approve_operation(session, op.id, wrong, "admin")
    session.refresh(op)
    assert op.state == "pending_approval" and op.approved_digest is None

    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(operations.ApprovalRefused):                          # a second click is refused
        operations.approve_operation(session, op.id, op.plan_digest, "admin")


def test_an_edited_configuration_has_a_different_digest_and_cannot_be_approved_by_accident(
        session, world, cluster, conn):
    first = run(session, world, begin(session, cluster, conn))
    reviewed = first.plan_digest
    operations.cancel_operation(session, first.id)

    edited = start_create(session, cluster_id=cluster.id, params=params_for(conn, ram_mb=16384), actor="admin")
    edited = run(session, world, edited)
    assert edited.plan_digest != reviewed
    with pytest.raises(operations.ApprovalRefused):
        operations.approve_operation(session, edited.id, reviewed, "admin")


def test_a_configuration_changed_after_approval_is_not_applied(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    path = workspace_file(world, cluster, "cluster.auto.tfvars.json")
    path.write_text(path.read_text().replace('"memory_mb": 8192', '"memory_mb": 65536'))
    with pytest.raises(StalePlan, match="configuration changed"):
        run(session, world, op)
    assert op.state == "failed" and "apply" not in world.calls


def test_a_plan_file_changed_after_approval_is_not_applied(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    workspace_file(world, cluster, "plan.tfplan").write_bytes(b"something else")
    with pytest.raises(StalePlan, match="plan file changed"):
        run(session, world, op)
    assert "apply" not in world.calls


def test_a_different_plan_stored_after_approval_is_not_applied(session, world, cluster, conn):
    """The plan on disk matches its own record, but it is not the plan the user approved."""
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")

    from app.provisioning.workspace import existing_workspace
    ws = existing_workspace(world.root, cluster.id)
    world.create_changes = creates(ADDRS[:1])                # a smaller plan, regenerated after the approval
    outcome = world.factory(lambda _: None).plan(ws, {})
    ws.save_plan("create", tfop._Handlers(session, op, world.factory, world.root)._rendered(), outcome.summary)

    with pytest.raises(ApplyRefused, match="not the one that was approved"):
        run(session, world, op)
    assert "apply" not in world.calls


def test_a_missing_plan_record_is_never_treated_as_nothing_to_do(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn))
    op.plan_summary = None                                   # plan data lost
    session.commit()
    handlers = tfop._Handlers(session, op, world.factory, world.root)
    with pytest.raises(operations.AwaitingApproval):
        handlers.approval()                                  # still asks for approval, does not skip it


def test_a_plan_with_no_changes_needs_no_approval(session, world, cluster, conn):
    world.create_changes = [(a, "no-op") for a in ADDRS]
    op = run(session, world, begin(session, cluster, conn))
    assert op.state == "succeeded" and "apply" not in world.calls


# ---- dry run ---------------------------------------------------------------------------------------------

def test_a_dry_run_produces_a_reviewable_plan_that_cannot_be_approved(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn, dry_run=True))
    assert op.state == "succeeded" and op.dry_run
    assert steps(session, op) == [("render", "done"), ("init", "done"), ("plan", "done")]
    assert op.plan_digest and op.plan_summary["adds"] == 3
    with pytest.raises(operations.ApprovalRefused, match="dry run"):
        operations.approve_operation(session, op.id, op.plan_digest, "admin")
    assert "apply" not in world.calls


def test_the_gate_holds_even_if_a_dry_run_is_forced_into_pending_approval(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn, dry_run=True))
    op.state = "pending_approval"
    session.commit()
    with pytest.raises(operations.ApprovalRefused, match="dry run"):
        operations.approve_operation(session, op.id, op.plan_digest, "admin")


# ---- what a plan may contain -----------------------------------------------------------------------------

@pytest.mark.parametrize("action", ["delete", "update", "replace"])
def test_a_create_plan_that_touches_existing_resources_is_rejected(session, world, cluster, conn, action):
    world.create_changes = creates(ADDRS[:2]) + [("module.node.proxmox_virtual_environment_vm.keep", action)]
    op = begin(session, cluster, conn)
    with pytest.raises(PlanRejected, match="keep"):
        run(session, world, op)
    assert op.state == "failed" and op.plan_digest is None
    assert not workspace_file(world, cluster, "plan.tfplan").exists()
    with pytest.raises(operations.ApprovalRefused):
        operations.approve_operation(session, op.id, "0" * 64, "admin")


# ---- failure, retry and cleanup --------------------------------------------------------------------------

def test_a_failed_apply_destroys_nothing_and_records_what_exists(session, world, cluster, conn):
    op = reach_failed_apply(session, world, cluster, conn)
    assert op.state == "failed" and "clone timed out" in op.error
    assert op.result["resources_in_state"] == ADDRS[:2] and op.result["ok"] is False
    assert not any("destroy" in c for c in world.calls)
    assert steps(session, op)[-2:] == [("apply", "failed"), ("configure", "pending")]
    assert not workspace_file(world, cluster, "plan.tfplan").exists()


def test_a_retry_after_a_failed_apply_re_plans_and_needs_a_new_approval(session, world, cluster, conn):
    op = reach_failed_apply(session, world, cluster, conn)
    old_digest = op.approved_digest
    world.create_changes = creates(ADDRS[2:])                # only the missing VM is left to create
    world.apply_outcome = ApplyOutcome(True, None, list(ADDRS), {})

    operations.retry_operation(session, op.id)
    session.refresh(op)
    assert op.state == "running" and op.approved_digest is None and op.plan_digest is None
    assert op.result["resources_in_state"] == ADDRS[:2]      # kept: cleanup is scoped to it
    assert steps(session, op)[:2] == [("render", "done"), ("init", "done")]
    assert [s for _, s in steps(session, op)[2:]] == ["pending"] * 4

    op = run(session, world, op)
    assert op.state == "pending_approval" and world.calls.count("apply") == 1
    assert op.plan_digest != old_digest and op.plan_summary["adds"] == 1
    with pytest.raises(operations.ApprovalRefused):
        operations.approve_operation(session, op.id, old_digest, "admin")

    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    op = run(session, world, op)
    assert op.state == "succeeded" and world.calls.count("apply") == 2
    assert world.calls.count("init") == 1                    # finished phases are not run again


def test_a_retry_before_the_plan_resumes_without_repeating_finished_phases(session, world, cluster, conn):
    world.init_error = "could not reach the state database"
    op = begin(session, cluster, conn)
    with pytest.raises(TerraformError):
        run(session, world, op)
    assert steps(session, op)[:3] == [("render", "done"), ("init", "failed"), ("plan", "pending")]

    world.init_error = None
    operations.retry_operation(session, op.id)
    op = run(session, world, op)
    assert op.state == "pending_approval"


def test_only_a_failed_operation_can_be_retried(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn))
    with pytest.raises(operations.RetryRefused):
        operations.retry_operation(session, op.id)


def test_a_retry_is_refused_while_another_operation_is_active_on_the_cluster(session, world, cluster, conn):
    failed = reach_failed_apply(session, world, cluster, conn)
    start_create(session, cluster_id=cluster.id, params=params_for(conn), actor="admin")
    with pytest.raises(operations.OperationConflict):
        operations.retry_operation(session, failed.id)
    session.refresh(failed)
    assert failed.state == "failed"


def test_cleanup_is_a_separate_approved_destroy_limited_to_what_the_create_left(session, world, cluster, conn):
    failed = reach_failed_apply(session, world, cluster, conn)
    world.destroy_changes = [(a, "delete") for a in ADDRS[:2]]

    with pytest.raises(OperationRefused, match="type the cluster name"):
        start_cleanup(session, create_op_id=failed.id, confirm_name="nope", actor="admin")
    cleanup = start_cleanup(session, create_op_id=failed.id, confirm_name="lab-b", actor="admin")
    assert cleanup.kind == "tf.destroy" and cleanup.parent_op_id == failed.id

    cleanup = run(session, world, cleanup)
    assert cleanup.state == "pending_approval" and world.calls[-1] == "plan-destroy"
    assert cleanup.plan_summary["deletes"] == 2 and cleanup.plan_summary["adds"] == 0
    assert world.calls.count("apply") == 1                   # only the failed create's apply so far

    world.apply_outcome = ApplyOutcome(True, None, [], {})
    operations.approve_operation(session, cleanup.id, cleanup.plan_digest, "admin")
    cleanup = run(session, world, cleanup)
    assert cleanup.state == "succeeded" and world.calls.count("apply") == 2


def test_cleanup_refuses_a_plan_that_deletes_something_the_create_did_not_make(session, world, cluster, conn):
    failed = reach_failed_apply(session, world, cluster, conn)
    world.destroy_changes = [(a, "delete") for a in ADDRS[:2]] + [("proxmox_virtual_environment_vm.es01", "delete")]
    cleanup = start_cleanup(session, create_op_id=failed.id, confirm_name="lab-b", actor="admin")
    with pytest.raises(PlanRejected, match="es01"):
        run(session, world, cleanup)
    assert cleanup.state == "failed" and cleanup.plan_digest is None


def test_cleanup_waits_for_the_create_to_finish_and_needs_something_left_to_remove(session, world, cluster, conn):
    ok = run(session, world, begin(session, cluster, conn))
    with pytest.raises(OperationRefused, match="once it has finished"):
        start_cleanup(session, create_op_id=ok.id, confirm_name="lab-b", actor="admin")
    operations.cancel_operation(session, ok.id)

    world.init_error = "boom"
    early = begin(session, cluster, conn)
    with pytest.raises(TerraformError):
        run(session, world, early)
    with pytest.raises(OperationRefused, match="nothing to clean up"):
        start_cleanup(session, create_op_id=early.id, confirm_name="lab-b", actor="admin")


def test_nothing_is_provisioned_or_cleaned_up_on_a_cluster_ecm_did_not_create(session, world, conn):
    for ownership in ("discovered", "adopted"):
        live = Cluster(name=f"live-{ownership}", ownership=ownership)
        session.add(live)
        session.commit()
        with pytest.raises(OperationRefused, match="not managed"):
            start_create(session, cluster_id=live.id, params=params_for(conn), actor="admin")


def test_bad_parameters_are_refused_up_front_with_a_plain_message(session, world, cluster, conn):
    bad = params_for(conn)
    bad["vm_ids"]["lab-b-01"] = 7
    with pytest.raises(OperationRefused, match="VMIDs must be 100 or higher"):
        start_create(session, cluster_id=cluster.id, params=bad, actor="admin")
    assert session.scalar(select(Operation)) is None


# ---- cancel, credentials, audit --------------------------------------------------------------------------

def test_a_cancelled_plan_frees_the_cluster_and_a_late_job_cannot_revive_it(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn))
    operations.cancel_operation(session, op.id)
    session.refresh(op)
    assert op.state == "cancelled" and op.finished_at
    run_operation(session, op.id, world.factory, world.root, world.ansible_factory)   # a stray job
    session.refresh(op)
    assert op.state == "cancelled" and "apply" not in world.calls
    with pytest.raises(operations.ApprovalRefused):
        operations.approve_operation(session, op.id, op.plan_digest, "admin")
    begin(session, cluster, conn)                                            # the cluster is free again


def test_terraform_gets_only_the_proxmox_token_and_the_state_url(session, world, cluster, conn):
    run(session, world, begin(session, cluster, conn))
    assert world.envs and set(world.envs[0]) == {"PROXMOX_VE_API_TOKEN", "PG_CONN_STR"}
    assert world.envs[0]["PROXMOX_VE_API_TOKEN"] == f"ecm@pve!tf={SECRET}"
    stored = json.dumps([o.params for o in session.scalars(select(Operation))])
    logs = " ".join(line.line for line in session.scalars(select(OperationLog)))
    assert SECRET not in stored and SECRET not in logs


def test_terraform_cannot_run_without_a_state_database(session, world, cluster, conn, monkeypatch):
    monkeypatch.setenv("ECM_TF_STATE_URL", "")
    config.get_settings.cache_clear()
    with pytest.raises(TerraformError, match="ECM_TF_STATE_URL"):
        run(session, world, begin(session, cluster, conn))


# ---- the HTTP layer --------------------------------------------------------------------------------------

H = {"x-ecm-csrf": "1"}


def pending(session, world, cluster, conn, **kw):
    return run(session, world, begin(session, cluster, conn, **kw))


def test_approve_endpoint_records_the_approval_and_enqueues_the_job(logged_in, session, world, cluster, conn):
    from procrastinate import testing

    from app import jobs
    op = pending(session, world, cluster, conn)
    detail = logged_in.get(f"/api/operations/{op.id}").json()
    assert detail["plan"] == {"digest": op.plan_digest, "summary": op.plan_summary, "approvable": True}

    with jobs.queue.replace_connector(testing.InMemoryConnector()) as q:
        r = logged_in.post(f"/api/operations/{op.id}/approve", json={"digest": op.plan_digest}, headers=H)
        assert r.status_code == 202
        assert [j["task_name"] for j in q.connector.jobs.values()] == ["tf.run"]
    session.refresh(op)
    assert op.state == "running" and op.approved_by == "admin"
    audit = [(e.action, e.details.get("digest")) for e in session.scalars(select(AuditEvent))]
    assert ("operation.approve", op.plan_digest) in audit


def test_approve_endpoint_refuses_a_wrong_digest_and_a_dry_run(logged_in, session, world, cluster, conn):
    op = pending(session, world, cluster, conn)
    r = logged_in.post(f"/api/operations/{op.id}/approve", json={"digest": "0" * 64}, headers=H)
    assert r.status_code == 409 and "changed" in r.json()["detail"]
    r = logged_in.post(f"/api/operations/{op.id}/approve", json={"digest": "short"}, headers=H)
    assert r.status_code == 422
    operations.cancel_operation(session, op.id)

    dry = pending(session, world, cluster, conn, dry_run=True)
    assert logged_in.get(f"/api/operations/{dry.id}").json()["plan"]["approvable"] is False
    r = logged_in.post(f"/api/operations/{dry.id}/approve", json={"digest": dry.plan_digest}, headers=H)
    assert r.status_code == 409 and "dry run" in r.json()["detail"]


def test_approve_endpoint_needs_a_session_and_the_csrf_header(client, session, world, cluster, conn):
    op = pending(session, world, cluster, conn)
    body = {"digest": op.plan_digest}
    assert client.post(f"/api/operations/{op.id}/approve", json=body, headers=H).status_code == 401
    session.refresh(op)
    assert op.state == "pending_approval"


def test_a_failed_enqueue_takes_the_approval_back(logged_in, session, world, cluster, conn, monkeypatch):
    from app import jobs

    async def boom(**_):
        raise RuntimeError("queue down")

    monkeypatch.setattr(jobs.tf_run, "defer_async", boom)
    op = pending(session, world, cluster, conn)
    r = logged_in.post(f"/api/operations/{op.id}/approve", json={"digest": op.plan_digest}, headers=H)
    assert r.status_code == 503
    session.refresh(op)
    assert op.state == "pending_approval" and op.approved_digest is None and op.approved_by is None


def test_cancel_retry_and_cleanup_endpoints(logged_in, session, world, cluster, conn):
    from procrastinate import testing

    from app import jobs
    waiting = pending(session, world, cluster, conn)
    assert logged_in.post(f"/api/operations/{waiting.id}/retry", headers=H).status_code == 409
    assert logged_in.post(f"/api/operations/{waiting.id}/cancel", headers=H).status_code == 200
    assert logged_in.post(f"/api/operations/{waiting.id}/cancel", headers=H).status_code == 409

    failed = reach_failed_apply(session, world, cluster, conn)
    with jobs.queue.replace_connector(testing.InMemoryConnector()) as q:
        r = logged_in.post(f"/api/operations/{failed.id}/cleanup", json={"confirm_name": "wrong"}, headers=H)
        assert r.status_code == 409 and not q.connector.jobs
        r = logged_in.post(f"/api/operations/{failed.id}/cleanup", json={"confirm_name": "lab-b"}, headers=H)
        assert r.status_code == 202 and len(q.connector.jobs) == 1
        cleanup_id = r.json()["id"]
    assert logged_in.get(f"/api/operations/{cleanup_id}").json()["parent_op_id"] == failed.id

    assert logged_in.post(f"/api/operations/{failed.id}/retry", headers=H).status_code == 409   # cleanup is active
    operations.fail_operation(session, cleanup_id, "stop")
    with jobs.queue.replace_connector(testing.InMemoryConnector()) as q:
        assert logged_in.post(f"/api/operations/{failed.id}/retry", headers=H).status_code == 202
        assert len(q.connector.jobs) == 1


# ---- tearing down a create that succeeded --------------------------------------------------------------

def reach_success(session, world, cluster, conn):
    """A real create that was approved and applied."""
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    return run(session, world, op)


def finish_teardown(session, world, create):
    teardown = start_cleanup(session, create_op_id=create.id, confirm_name="lab-b", actor="admin",
                          confirm_data_loss=True)
    teardown = run(session, world, teardown)
    world.apply_outcome = ApplyOutcome(True, None, [], {})
    operations.approve_operation(session, teardown.id, teardown.plan_digest, "admin")
    return run(session, world, teardown)


def test_a_create_that_succeeded_can_be_torn_down_with_the_same_guards(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    assert created.state == "succeeded" and created.result["resources_in_state"] == ADDRS

    with pytest.raises(OperationRefused, match="type the cluster name"):
        start_cleanup(session, create_op_id=created.id, confirm_name="nope", actor="admin")
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin",
                          confirm_data_loss=True)
    assert teardown.kind == "tf.destroy" and teardown.parent_op_id == created.id

    teardown = run(session, world, teardown)
    assert teardown.state == "pending_approval" and world.calls[-1] == "plan-destroy"
    assert teardown.plan_summary["deletes"] == 3 and teardown.plan_summary["adds"] == 0
    assert world.calls.count("apply") == 1                    # nothing is destroyed until it is approved

    world.apply_outcome = ApplyOutcome(True, None, [], {})
    operations.approve_operation(session, teardown.id, teardown.plan_digest, "admin")
    teardown = run(session, world, teardown)
    assert teardown.state == "succeeded" and teardown.result["resources_in_state"] == []
    assert world.calls.count("apply") == 2

    started = [e for e in session.scalars(select(AuditEvent).where(AuditEvent.action == "operation.start"))
               if e.details.get("kind") == "tf.destroy"]
    assert started[0].details["parent_state"] == "succeeded" and started[0].details["resources"] == 3


def test_a_create_cannot_be_torn_down_twice(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    assert finish_teardown(session, world, created).state == "succeeded"
    with pytest.raises(OperationRefused, match="already been cleaned up"):
        start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin",
                          confirm_data_loss=True)


def test_tearing_down_a_successful_create_is_still_limited_to_what_it_made(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    world.destroy_changes = [(a, "delete") for a in ADDRS] + [("proxmox_virtual_environment_vm.es01", "delete")]
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin",
                          confirm_data_loss=True)
    with pytest.raises(PlanRejected, match="es01"):
        run(session, world, teardown)
    assert teardown.state == "failed" and teardown.plan_digest is None
    assert world.calls.count("apply") == 1                    # and nothing was destroyed


def test_a_dry_run_has_nothing_to_tear_down(session, world, cluster, conn):
    dry = run(session, world, begin(session, cluster, conn, dry_run=True))
    assert dry.state == "succeeded"
    with pytest.raises(OperationRefused, match="nothing to clean up"):
        start_cleanup(session, create_op_id=dry.id, confirm_name="lab-b", actor="admin")


def test_the_cleanup_endpoint_tears_down_a_successful_create(logged_in, session, world, cluster, conn):
    from procrastinate import testing

    from app import jobs
    created = reach_success(session, world, cluster, conn)
    with jobs.queue.replace_connector(testing.InMemoryConnector()) as q:
        r = logged_in.post(f"/api/operations/{created.id}/cleanup",
                           json={"confirm_name": "lab-b", "confirm_data_loss": True}, headers=H)
        assert r.status_code == 202 and len(q.connector.jobs) == 1
    detail = logged_in.get(f"/api/operations/{r.json()['id']}").json()
    assert detail["kind"] == "tf.destroy" and detail["parent_op_id"] == created.id


# ---- the pre-flight: the token must still have the rights before anything is planned ------------------------

def test_a_plan_first_checks_the_token_with_one_read_only_request(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn))
    assert op.state == "pending_approval"
    assert [(m, p) for m, p, _ in world.proxmox_seen] == [("GET", "/api2/json/access/permissions")]
    assert any("has the rights this operation needs" in line.line for line in session.scalars(select(OperationLog)))


def test_rights_inherited_from_a_parent_path_count(session, world, cluster, conn):
    world.perms = {"/": {"VM.Allocate": 1, "VM.Clone": 1, "Datastore.AllocateSpace": 1}}
    assert run(session, world, begin(session, cluster, conn)).state == "pending_approval"


@pytest.mark.parametrize("missing, text", [
    ("/pool/ecm", "VM.Allocate on /pool/ecm"),
    ("/storage/tank", "Datastore.AllocateSpace on /storage/tank"),
    ("/vms/8000", "VM.Clone on the template /vms/8000")])
def test_a_create_is_refused_before_planning_when_the_token_lacks_a_right(session, world, cluster, conn, missing, text):
    del world.perms[missing]
    op = begin(session, cluster, conn)
    with pytest.raises(PreflightFailed, match=re.escape(text)):
        run(session, world, op)
    assert op.state == "failed" and op.plan_digest is None and "Fix its permissions" in op.error
    assert world.calls == ["init"]                                # nothing was planned, and nothing could be approved


def test_a_pool_that_lost_its_rights_is_caught_before_the_plan(session, world, cluster, conn):
    """For example a pool that was recreated by hand, which drops its permissions."""
    world.perms = {}
    with pytest.raises(PreflightFailed, match="does the pool exist"):
        run(session, world, begin(session, cluster, conn))


def test_a_dry_run_is_checked_too(session, world, cluster, conn):
    del world.perms["/pool/ecm"]
    with pytest.raises(PreflightFailed):
        run(session, world, begin(session, cluster, conn, dry_run=True))


def test_a_teardown_needs_only_the_right_to_manage_vms_in_the_pool(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    world.perms = {"/pool/ecm": {"VM.Allocate": 1}}             # no storage or template rights: it does not need them
    teardown = run(session, world, start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin",
                          confirm_data_loss=True))
    assert teardown.state == "pending_approval" and world.calls[-1] == "plan-destroy"


def test_a_teardown_is_refused_when_even_the_pool_right_is_gone(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    world.perms = {}
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin",
                          confirm_data_loss=True)
    with pytest.raises(PreflightFailed):
        run(session, world, teardown)
    assert "plan-destroy" not in world.calls


def test_a_rejected_token_and_an_unreachable_proxmox_fail_the_plan_clearly_and_a_retry_checks_again(
        session, world, cluster, conn):
    world.proxmox_status = 401
    op = begin(session, cluster, conn)
    with pytest.raises(PreflightFailed, match="rejected the token Terraform uses"):
        run(session, world, op)

    world.proxmox_status = 200                                  # the rights are fixed; retry checks again
    operations.retry_operation(session, op.id)
    op = run(session, world, op)
    assert op.state == "pending_approval" and len(world.proxmox_seen) == 2
    operations.cancel_operation(session, op.id)

    world.proxmox_down = True
    with pytest.raises(PreflightFailed, match="could not reach Proxmox to check"):
        run(session, world, begin(session, cluster, conn))


def test_the_preflight_uses_the_token_terraform_will_use(session, world, cluster, conn):
    cred = Credential(kind="proxmox_token", name="tf", ciphertext=crypto.encrypt("terraform-secret-1111"))
    session.add(cred)
    session.flush()
    conn.terraform_credential_id, conn.terraform_token_id = cred.id, "tf@pve!terraform"
    session.commit()
    run(session, world, begin(session, cluster, conn))
    assert world.proxmox_seen[0][2] == "PVEAPIToken=tf@pve!terraform=terraform-secret-1111"


# ---- configure: building the cluster on the machines Terraform made ------------------------------------------

def logs(session, op):
    return "\n".join(line.line for line in session.scalars(select(OperationLog).where(OperationLog.operation_id == op.id)))


def credentials(session, kind):
    return list(session.scalars(select(Credential).where(Credential.kind == kind)))


def test_a_real_create_has_a_configure_phase_and_a_dry_run_and_a_destroy_do_not(session, world, cluster, conn):
    real = begin(session, cluster, conn)
    assert [n for n, _ in steps(session, real)][-1] == "configure"
    operations.cancel_operation(session, run(session, world, real).id)
    dry = begin(session, cluster, conn, dry_run=True)
    assert "configure" not in [n for n, _ in steps(session, dry)]
    assert run(session, world, dry).state == "succeeded"       # finished, so it no longer holds the cluster
    created = reach_success(session, world, cluster, conn)
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin",
                             confirm_data_loss=True)
    assert "configure" not in [n for n, _ in steps(session, teardown)]


def test_the_plan_says_what_will_be_installed(session, world, cluster, conn):
    op = run(session, world, begin(session, cluster, conn))
    assert op.plan_summary["configure"] == "install elasticsearch 9.4.3 on 3 nodes and start the cluster"


def test_what_will_be_configured_is_part_of_the_approved_digest():
    import hashlib

    from app.provisioning.workspace import StoredPlan
    base = {"operation_kind": "create", "digest": "d" * 64, "plan_sha256": "p" * 64, "files": [], "summary": {},
            "created_at": "t"}
    plain = StoredPlan(**base)
    legacy = hashlib.sha256()
    for part in ("create", "d" * 64, "p" * 64):
        legacy.update(part.encode() + b"\0")
    assert plain.approval_digest == legacy.hexdigest()            # nothing to configure: exactly the old digest
    one = StoredPlan(**base, configure="install elasticsearch 9.4.3 on 3 nodes and start the cluster")
    other = StoredPlan(**base, configure="install elasticsearch 9.5.6 on 3 nodes and start the cluster")
    assert len({plain.approval_digest, one.approval_digest, other.approval_digest}) == 3


def test_a_create_builds_the_cluster_and_keeps_only_what_ecm_needs(session, world, cluster, conn):
    op = reach_success(session, world, cluster, conn)
    assert op.state == "succeeded" and all(status == "done" for _, status in steps(session, op))

    (request,) = world.ansible_requests
    assert request.kind == "create" and request.bootstrapped_at is None and not request.check
    assert len(request.elastic_password) >= 20 and request.search_domain == "lab.example.org"
    assert request.addresses == params_for(conn)["addresses"]
    assert request.ca_cert_pem is None and request.ca_key_pem is None          # the first run makes the CA

    session.refresh(cluster)
    assert cluster.bootstrapped_at is not None and cluster.es_cluster_uuid == "4Et2nKICTImSzjMyH77utQ"
    assert cluster.es_version == "9.4.3" and cluster.health_status == "green" and cluster.tls_verify is True
    assert cluster.endpoint_urls == [f"https://192.0.2.{110 + i}:9200" for i in range(3)]
    assert cluster.tls_ca_pem == CA_CERT                                       # the certificate is public

    api_key = session.get(Credential, cluster.credential_id)
    assert api_key.kind == "es_api_key" and crypto.decrypt(api_key.ciphertext) == API_KEY
    (ca_key,) = credentials(session, "es_ca_key")
    assert crypto.decrypt(ca_key.ciphertext) == CA_KEY
    assert API_KEY.encode() not in api_key.ciphertext and CA_KEY.encode() not in ca_key.ciphertext
    assert credentials(session, "es_elastic") == []                            # used once, then discarded

    assert op.result["configured"] == {"cluster_uuid": "4Et2nKICTImSzjMyH77utQ", "status": "green",
                                       "number_of_nodes": 3}
    visible = json.dumps([op.result, op.params, op.plan_summary]) + logs(session, op)
    for secret in (request.elastic_password, API_KEY, "FakeCaKeyBodyForTests000000001"):
        assert secret not in visible


def test_a_failed_configure_keeps_the_ca_and_the_password_and_a_retry_resumes_with_them(session, world, cluster, conn):
    world.ansible_outcome = AnsibleOutcome(
        ok=False, error="ansible-playbook failed: fatal: [lab-b-01]: FAILED! => 503", new_ca=NewCa(CA_CERT, CA_KEY))
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(tfop.ConfigureFailed, match="503"):
        run(session, world, op)
    assert op.state == "failed" and "retry resumes the configure step" in op.error
    assert steps(session, op)[-2:] == [("apply", "done"), ("configure", "failed")]

    session.refresh(cluster)
    assert cluster.bootstrapped_at is None and cluster.es_cluster_uuid is None and cluster.credential_id is None
    assert cluster.tls_ca_pem == CA_CERT                                       # kept: the nodes may already trust it
    (ca_key,) = credentials(session, "es_ca_key")
    assert crypto.decrypt(ca_key.ciphertext) == CA_KEY
    (elastic,) = credentials(session, "es_elastic")
    first_password = world.ansible_requests[0].elastic_password
    assert crypto.decrypt(elastic.ciphertext) == first_password

    operations.retry_operation(session, op.id)
    world.create_changes = []                                  # the VMs exist now, so planning again finds no changes
    world.ansible_outcome = AnsibleOutcome(ok=True, recap={}, new_ca=None, result=good_ansible_outcome().result)
    op = run(session, world, op)
    assert op.state == "succeeded" and world.calls.count("apply") == 1        # the VMs were not applied again

    again = world.ansible_requests[1]
    assert again.elastic_password == first_password                            # the keystore already holds it
    assert again.ca_cert_pem == CA_CERT and again.ca_key_pem == CA_KEY         # no second CA is made
    session.refresh(cluster)
    assert cluster.bootstrapped_at is not None and credentials(session, "es_elastic") == []


def test_a_failed_configure_can_be_cleaned_up_without_accepting_data_loss(session, world, cluster, conn):
    world.ansible_error = "the ansible-playbook binary was not found (ansible-playbook)"
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(tfop.ConfigureFailed, match="not found"):
        run(session, world, op)
    session.refresh(cluster)
    assert cluster.bootstrapped_at is None and len(credentials(session, "es_elastic")) == 1
    cleanup = start_cleanup(session, create_op_id=op.id, confirm_name="lab-b", actor="admin")   # nothing to lose
    assert cleanup.kind == "tf.destroy"


def test_an_already_bootstrapped_cluster_is_never_configured_again(session, world, cluster, conn):
    from datetime import UTC, datetime
    cluster.bootstrapped_at = datetime(2026, 11, 6, tzinfo=UTC)
    session.commit()
    op = reach_success(session, world, cluster, conn)
    assert op.state == "succeeded" and world.ansible_requests == []
    assert "already bootstrapped" in logs(session, op)


def test_tearing_down_a_bootstrapped_cluster_needs_the_data_loss_accepted(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    with pytest.raises(OperationRefused, match="data in it is destroyed"):
        start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin")
    assert session.scalar(select(Operation).where(Operation.kind == "tf.destroy")) is None   # nothing was started
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin",
                             confirm_data_loss=True)
    audit = session.scalars(select(AuditEvent).where(AuditEvent.target_id == teardown.id)).one()
    assert audit.details["bootstrapped"] is True and audit.details["data_loss_confirmed"] is True


def test_a_complete_teardown_forgets_the_cluster_so_the_same_name_bootstraps_again(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    first_password = world.ansible_requests[0].elastic_password
    teardown = finish_teardown(session, world, created)
    assert teardown.state == "succeeded"

    session.refresh(cluster)
    assert cluster.bootstrapped_at is None and cluster.es_cluster_uuid is None and cluster.credential_id is None
    assert cluster.tls_ca_pem is None and cluster.endpoint_urls is None and cluster.health_status is None
    for kind in ("es_api_key", "es_ca_key", "es_elastic"):
        assert credentials(session, kind) == []
    assert "removed with its machines" in logs(session, teardown)

    world.apply_outcome = ApplyOutcome(True, None, list(ADDRS), {})
    world.ansible_outcome = good_ansible_outcome()
    recreated = reach_success(session, world, cluster, conn)                   # the same name, built again
    assert recreated.state == "succeeded" and len(world.ansible_requests) == 2
    second = world.ansible_requests[1]
    assert second.ca_cert_pem is None and second.elastic_password != first_password   # a fresh CA and password


def test_the_cleanup_endpoint_refuses_a_bootstrapped_cluster_until_the_data_loss_is_accepted(
        logged_in, session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    r = logged_in.post(f"/api/operations/{created.id}/cleanup", json={"confirm_name": "lab-b"}, headers=H)
    assert r.status_code == 409 and "data" in r.json()["detail"]


def test_the_stored_plan_carries_what_will_be_configured_and_the_digest_covers_it(session, world, cluster, conn):
    from app.provisioning.workspace import existing_workspace
    op = run(session, world, begin(session, cluster, conn))
    stored = existing_workspace(world.root, cluster.id).load_plan()
    assert stored.configure == "install elasticsearch 9.4.3 on 3 nodes and start the cluster"
    assert stored.approval_digest == op.plan_digest


def test_a_complete_teardown_also_removes_the_nodes_discovery_last_saw_for_that_cluster_only(
        session, world, cluster, conn):
    """Found on infra: after a teardown the dashboard still listed the destroyed cluster's nodes, because only a
    successful sync prunes them and a cluster with no endpoints cannot sync."""
    from datetime import UTC, datetime

    from app.models import EsNode
    created = reach_success(session, world, cluster, conn)
    cluster.snapshot, cluster.last_sync_at = {"status": "green"}, datetime(2026, 11, 6, tzinfo=UTC)
    other = Cluster(name="other", ownership="discovered")
    session.add(other)
    session.flush()
    for owner, names in ((cluster, NODES), (other, ["es01", "es02"])):
        for n in names:
            session.add(EsNode(cluster_id=owner.id, es_node_id=f"id-{n}", name=n))
    session.commit()

    assert finish_teardown(session, world, created).state == "succeeded"

    session.refresh(cluster)
    remaining = [n.name for n in session.scalars(select(EsNode).order_by(EsNode.name))]
    assert remaining == ["es01", "es02"]                         # lab-b's own were removed, the others' were not
    assert cluster.snapshot is None and cluster.last_sync_at is None and cluster.last_sync_error is None


# ---- removing the record of a cluster whose machines are gone --------------------------------------------------

def torn_down(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    assert finish_teardown(session, world, created).state == "succeeded"
    return created


def remove(session, cluster, name="lab-b"):
    from app.provisioning.operation import remove_cluster
    return remove_cluster(session, cluster_id=cluster.id, confirm_name=name, actor="admin")


def test_a_torn_down_cluster_can_be_removed_and_its_history_is_kept(session, world, cluster, conn):
    created = torn_down(session, world, cluster, conn)
    cluster_id = cluster.id
    other = Cluster(name="other", ownership="discovered")
    session.add(other)
    session.add(Credential(kind="es_ca_key", name=f"es-ca-key-{cluster_id}", ciphertext=b"left over"))
    session.commit()
    ops = session.scalars(select(Operation).where(Operation.cluster_id == cluster_id)).all()

    out = remove(session, cluster)

    assert out == {"id": cluster_id, "name": "lab-b", "operations_kept": len(ops)} and len(ops) >= 2
    assert session.get(Cluster, cluster_id) is None and session.get(Cluster, other.id) is not None
    kept = session.get(Operation, created.id)
    assert kept is not None and kept.cluster_id is None                        # the history stays, detached
    assert session.scalar(select(Credential).where(Credential.name == f"es-ca-key-{cluster_id}")) is None
    event = session.scalars(select(AuditEvent).where(AuditEvent.action == "cluster.remove")).one()
    assert event.details["name"] == "lab-b" and event.details["operations_kept"] == len(ops)


def test_a_cluster_that_never_built_anything_can_be_removed(session, world, cluster, conn):
    assert run(session, world, begin(session, cluster, conn, dry_run=True)).state == "succeeded"
    assert remove(session, cluster)["name"] == "lab-b"


@pytest.mark.parametrize("what,message", [
    ("wrong name", "type the cluster name"),
    ("discovered", "not managed by ECM"),
    ("bootstrapped", "has bootstrapped"),
    ("running", "still running"),
    ("not torn down", "have not been torn down"),
    ("vm exists", "still exist in Proxmox"),
])
def test_a_removal_is_refused_while_anything_of_the_cluster_remains(session, world, cluster, conn, what, message):
    target, name = cluster, "lab-b"
    if what == "wrong name":
        torn_down(session, world, cluster, conn)
        name = "nope"
    elif what == "discovered":
        target = Cluster(name="found", ownership="discovered")
        session.add(target)
        session.commit()
        name = "found"
    elif what == "bootstrapped":
        reach_success(session, world, cluster, conn)
    elif what == "running":
        begin(session, cluster, conn)                           # planned, not yet run
    elif what == "not torn down":
        world.ansible_error = "the ansible-playbook binary was not found"
        op = run(session, world, begin(session, cluster, conn))
        operations.approve_operation(session, op.id, op.plan_digest, "admin")
        with pytest.raises(tfop.ConfigureFailed):
            run(session, world, op)                             # the VMs exist, nothing bootstrapped
    elif what == "vm exists":
        torn_down(session, world, cluster, conn)
        from app.models import Vm
        session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=500, name="lab-b-01", status="running"))
        session.commit()
    with pytest.raises(OperationRefused, match=message):
        remove(session, target, name)
    assert session.get(Cluster, target.id) is not None                         # nothing was removed


def test_the_remove_endpoint_refuses_with_the_reason_and_removes_when_nothing_is_left(
        logged_in, session, world, cluster, conn):
    torn_down(session, world, cluster, conn)
    r = logged_in.post(f"/api/clusters/{cluster.id}/remove", json={"confirm_name": "wrong"}, headers=H)
    assert r.status_code == 409 and "type the cluster name" in r.json()["detail"]
    r = logged_in.post(f"/api/clusters/{cluster.id}/remove", json={"confirm_name": "lab-b"}, headers=H)
    assert r.status_code == 200 and r.json()["name"] == "lab-b"
    assert logged_in.post(f"/api/clusters/{cluster.id}/remove", json={"confirm_name": "lab-b"},
                          headers=H).status_code == 409                       # already gone


# ---- what the cluster page may offer ----------------------------------------------------------------------

def lifecycle(session, cluster):
    from app.provisioning.operation import cluster_lifecycle
    session.refresh(cluster)
    return cluster_lifecycle(session, cluster)


def test_a_discovered_cluster_has_no_lifecycle(session):
    found = Cluster(name="found", ownership="discovered")
    session.add(found)
    session.commit()
    from app.provisioning.operation import cluster_lifecycle
    assert cluster_lifecycle(session, found) == {"managed": False}


def test_a_built_cluster_offers_a_teardown_of_its_create_and_names_the_machines_and_the_data_loss(
        session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    got = lifecycle(session, cluster)
    assert got == {"managed": True, "busy_operation_id": None, "teardown_of": created.id, "nodes": NODES,
                   "bootstrapped": True, "can_remove": False}


def test_while_an_operation_runs_nothing_is_offered_and_it_is_named(session, world, cluster, conn):
    planned = begin(session, cluster, conn)                     # planned, waiting to run
    got = lifecycle(session, cluster)
    assert got["busy_operation_id"] == planned.id and got["teardown_of"] is None and got["nodes"] == []
    assert got["can_remove"] is False


def test_after_a_teardown_only_the_removal_is_offered(session, world, cluster, conn):
    torn_down(session, world, cluster, conn)
    got = lifecycle(session, cluster)
    assert got["teardown_of"] is None and got["nodes"] == [] and got["can_remove"] is True
    assert got["bootstrapped"] is False and got["busy_operation_id"] is None


def test_a_failed_create_that_left_machines_offers_a_teardown_without_a_data_loss_warning(
        session, world, cluster, conn):
    world.ansible_error = "the ansible-playbook binary was not found"
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(tfop.ConfigureFailed):
        run(session, world, op)                                 # the VMs exist, nothing bootstrapped
    got = lifecycle(session, cluster)
    assert got["teardown_of"] == op.id and got["nodes"] == NODES and got["bootstrapped"] is False
    assert got["can_remove"] is False                           # machines exist, so it cannot be removed yet


def test_a_cluster_that_never_built_anything_offers_only_the_removal(session, world, cluster, conn):
    assert run(session, world, begin(session, cluster, conn, dry_run=True)).state == "succeeded"
    got = lifecycle(session, cluster)
    assert got["teardown_of"] is None and got["can_remove"] is True


def test_the_cluster_detail_carries_the_lifecycle_and_what_it_offers_is_what_the_api_accepts(
        logged_in, session, world, cluster, conn):
    from procrastinate import testing

    from app import jobs
    created = reach_success(session, world, cluster, conn)
    detail = logged_in.get(f"/api/clusters/{cluster.id}").json()
    assert detail["lifecycle"]["teardown_of"] == created.id
    with jobs.queue.replace_connector(testing.InMemoryConnector()):
        r = logged_in.post(f"/api/operations/{detail['lifecycle']['teardown_of']}/cleanup",
                           json={"confirm_name": "lab-b", "confirm_data_loss": detail["lifecycle"]["bootstrapped"]},
                           headers=H)
    assert r.status_code == 202
    after = logged_in.get(f"/api/clusters/{cluster.id}").json()["lifecycle"]
    assert after["busy_operation_id"] == r.json()["id"] and after["teardown_of"] is None
