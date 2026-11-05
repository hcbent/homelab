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

    def factory(self, line_log):
        return FakeRunner(line_log, self)


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
    run_operation(session, op.id, world.factory, world.root)
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
                                  ("approval", "waiting"), ("apply", "pending")]
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
    assert steps(session, op)[-1] == ("apply", "failed")
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
    assert [s for _, s in steps(session, op)[2:]] == ["pending"] * 3

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
    run_operation(session, op.id, world.factory, world.root)                 # a stray job
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
    teardown = start_cleanup(session, create_op_id=create.id, confirm_name="lab-b", actor="admin")
    teardown = run(session, world, teardown)
    world.apply_outcome = ApplyOutcome(True, None, [], {})
    operations.approve_operation(session, teardown.id, teardown.plan_digest, "admin")
    return run(session, world, teardown)


def test_a_create_that_succeeded_can_be_torn_down_with_the_same_guards(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    assert created.state == "succeeded" and created.result["resources_in_state"] == ADDRS

    with pytest.raises(OperationRefused, match="type the cluster name"):
        start_cleanup(session, create_op_id=created.id, confirm_name="nope", actor="admin")
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin")
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
        start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin")


def test_tearing_down_a_successful_create_is_still_limited_to_what_it_made(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    world.destroy_changes = [(a, "delete") for a in ADDRS] + [("proxmox_virtual_environment_vm.es01", "delete")]
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin")
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
        r = logged_in.post(f"/api/operations/{created.id}/cleanup", json={"confirm_name": "lab-b"}, headers=H)
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
    teardown = run(session, world, start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin"))
    assert teardown.state == "pending_approval" and world.calls[-1] == "plan-destroy"


def test_a_teardown_is_refused_when_even_the_pool_right_is_gone(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    world.perms = {}
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin")
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
