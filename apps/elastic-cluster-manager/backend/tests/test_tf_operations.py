"""Terraform operations wired to the operation state machine, driven by a fake TerraformRunner.

The fake writes a plan file whose bytes depend on what it plans, so the digests behave like the real thing:
a different plan gives a different digest.
"""
import contextlib
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
GOOD_PERMS = {"/pool/ecm": {"VM.Allocate": 1, "VM.Audit": 1, "VM.Config.CPU": 1, "VM.Config.Memory": 1,
                            "VM.PowerMgmt": 1},
              "/storage/tank": {"Datastore.AllocateSpace": 1},
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
    restart_error: str | None = None                      # only the rolling restart fails
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
        if request.kind == "restart" and self.w.restart_error:
            raise AnsibleError(self.w.restart_error)
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
    old_id = cluster.id
    teardown = finish_teardown(session, world, created)
    assert teardown.state == "succeeded"

    assert session.get(Cluster, old_id) is None                                # the record went with the machines
    for kind in ("es_api_key", "es_ca_key", "es_elastic"):
        assert credentials(session, kind) == []
    assert "removed with its machines" in logs(session, teardown)

    again = Cluster(name="lab-b", ownership="managed")                         # the same name, as a create makes it
    session.add(again)
    session.commit()
    world.apply_outcome = ApplyOutcome(True, None, list(ADDRS), {})
    world.ansible_outcome = good_ansible_outcome()
    recreated = reach_success(session, world, again, conn)
    assert recreated.state == "succeeded" and len(world.ansible_requests) == 2
    second = world.ansible_requests[1]
    assert second.ca_cert_pem is None and second.elastic_password != first_password   # a fresh CA and password
    assert again.id != old_id


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

    remaining = [n.name for n in session.scalars(select(EsNode).order_by(EsNode.name))]
    assert remaining == ["es01", "es02"]                         # lab-b's own were removed, the others' were not
    assert session.get(Cluster, other.id) is not None


# ---- removing the record of a cluster whose machines are gone --------------------------------------------------

def remove(session, cluster, name="lab-b"):
    from app.provisioning.operation import remove_cluster
    return remove_cluster(session, cluster_id=cluster.id, confirm_name=name, actor="admin")


def test_a_teardown_removes_the_record_and_keeps_the_history(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    cluster_id = cluster.id
    other = Cluster(name="other", ownership="discovered")
    session.add(other)
    session.commit()
    ops = session.scalars(select(Operation).where(Operation.cluster_id == cluster_id)).all()

    teardown = finish_teardown(session, world, created)

    assert teardown.state == "succeeded"
    assert session.get(Cluster, cluster_id) is None and session.get(Cluster, other.id) is not None
    assert session.get(Operation, created.id).cluster_id is None                  # the history stays, detached
    assert session.get(Operation, teardown.id).cluster_id is None
    event = session.scalars(select(AuditEvent).where(AuditEvent.action == "cluster.remove")).one()
    assert event.details["name"] == "lab-b" and event.details["reason"] == "teardown"
    assert event.details["operation"] == teardown.id and event.details["operations_kept"] == len(ops) + 1
    assert "record was removed" in logs(session, teardown)


def test_a_teardown_that_fails_keeps_the_record(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin",
                             confirm_data_loss=True)
    teardown = run(session, world, teardown)
    world.apply_outcome = ApplyOutcome(False, "terraform apply failed: Error: VM is locked", ADDRS[:1])
    operations.approve_operation(session, teardown.id, teardown.plan_digest, "admin")
    with pytest.raises(ApplyFailed):
        run(session, world, teardown)
    assert session.get(Cluster, cluster.id) is not None                        # machines remain, so does the record


def test_a_failed_create_that_never_bootstrapped_is_removed_when_it_is_cleaned_up(session, world, cluster, conn):
    world.ansible_error = "the ansible-playbook binary was not found"
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(tfop.ConfigureFailed):
        run(session, world, op)                                                # the VMs exist, nothing bootstrapped
    cluster_id = cluster.id
    assert finish_teardown(session, world, op).state == "succeeded"
    assert session.get(Cluster, cluster_id) is None


def test_a_teardown_keeps_the_record_and_says_why_when_a_machine_still_carries_a_name_of_it(
        session, world, cluster, conn):
    from app.models import Vm
    created = reach_success(session, world, cluster, conn)
    session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=777, name="lab-b-01", status="running"))
    session.commit()                                  # another VMID, so the destroyed machine's row is not this one

    teardown = finish_teardown(session, world, created)

    assert teardown.state == "succeeded" and session.get(Cluster, cluster.id) is not None
    assert "the cluster's record was kept" in logs(session, teardown) and "lab-b-01" in logs(session, teardown)
    got = lifecycle(session, cluster)
    assert got["teardown_of"] is None and got["can_remove"] is False and "lab-b-01" in got["remove_blocker"]
    session.delete(session.scalar(select(Vm).where(Vm.vmid == 777)))
    session.commit()                                  # the next sync no longer finds it
    assert lifecycle(session, cluster)["can_remove"] is True
    out = remove(session, cluster)                    # now it can go by hand, and the history is kept
    assert out["name"] == "lab-b" and out["operations_kept"] >= 2
    assert session.get(Operation, created.id).cluster_id is None


def test_a_cluster_that_never_built_anything_can_be_removed(session, world, cluster, conn):
    assert remove(session, cluster)["name"] == "lab-b"


@pytest.mark.parametrize("what,message", [
    ("wrong name", "type the cluster name"),
    ("discovered", "not managed by ECM"),
    ("bootstrapped", "has bootstrapped"),
    ("running", "still running"),
    ("not torn down", "have not been torn down"),
])
def test_a_removal_is_refused_while_anything_of_the_cluster_remains(session, world, cluster, conn, what, message):
    target, name = cluster, "lab-b"
    if what == "wrong name":
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
    with pytest.raises(OperationRefused, match=message):
        remove(session, target, name)
    assert session.get(Cluster, target.id) is not None                         # nothing was removed


def test_the_remove_endpoint_refuses_with_the_reason_and_removes_when_nothing_is_left(
        logged_in, session, world, cluster, conn):
    r = logged_in.post(f"/api/clusters/{cluster.id}/remove", json={"confirm_name": "wrong"}, headers=H)
    assert r.status_code == 409 and "type the cluster name" in r.json()["detail"]
    r = logged_in.post(f"/api/clusters/{cluster.id}/remove", json={"confirm_name": "lab-b"}, headers=H)
    assert r.status_code == 200 and r.json()["name"] == "lab-b"
    assert logged_in.post(f"/api/clusters/{cluster.id}/remove", json={"confirm_name": "lab-b"},
                          headers=H).status_code == 409                       # already gone


def test_a_teardown_drops_the_stored_proxmox_rows_of_the_machines_it_destroyed(session, world, cluster, conn):
    """Found on infra: after a teardown the destroyed machines' rows stayed in the inventory until the next Proxmox
    sync, which blocked removing the cluster's record and creating the same name again."""
    from app.models import Vm
    created = reach_success(session, world, cluster, conn)
    for name, vmid in created.params["vm_ids"].items():
        session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=int(vmid), name=name, status="running"))
    session.add(Vm(connection_id=conn.id, pve_node="pve2", vmid=999, name="unrelated", status="running"))
    session.commit()

    teardown = finish_teardown(session, world, created)

    left = sorted(n for (n,) in session.execute(select(Vm.name)))
    assert left == ["unrelated"]                                      # ours are gone, the other VM is untouched
    assert "3 destroyed machines dropped from the Proxmox inventory" in logs(session, teardown)
    assert session.get(Cluster, cluster.id) is None                   # and with them gone the record could go too


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
                   "bootstrapped": True, "can_remove": False,
                   "data_disks": {n: 100 for n in NODES}, "can_change": True,
                   "sizes": {n: {"cores": 4, "ram_mb": 8192} for n in NODES},
                   "remove_blocker": "this cluster has bootstrapped: tear its machines down first (cleanup), then remove it"}


def test_while_an_operation_runs_nothing_is_offered_and_it_is_named(session, world, cluster, conn):
    planned = begin(session, cluster, conn)                     # planned, waiting to run
    got = lifecycle(session, cluster)
    assert got["busy_operation_id"] == planned.id and got["teardown_of"] is None and got["nodes"] == []
    assert got["can_remove"] is False


def test_a_cluster_that_never_built_anything_offers_the_removal_and_nothing_to_tear_down(
        session, world, cluster, conn):
    got = lifecycle(session, cluster)
    assert got["teardown_of"] is None and got["nodes"] == [] and got["can_remove"] is True
    assert got["bootstrapped"] is False and got["busy_operation_id"] is None and got["remove_blocker"] is None


def test_a_cluster_with_machines_left_by_a_failed_create_is_told_why_it_cannot_be_removed(
        session, world, cluster, conn):
    world.ansible_error = "the ansible-playbook binary was not found"
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(tfop.ConfigureFailed):
        run(session, world, op)
    assert "have not been torn down" in lifecycle(session, cluster)["remove_blocker"]


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


def test_an_operation_still_names_its_cluster_after_a_teardown_removed_it(logged_in, session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    teardown = finish_teardown(session, world, created)
    assert session.get(Cluster, cluster.id) is None
    for op in (created, teardown):
        got = logged_in.get(f"/api/operations/{op.id}").json()
        assert got["cluster_id"] is None and got["cluster_name"] == "lab-b"
    assert {o["cluster_name"] for o in logged_in.get("/api/operations").json()} == {"lab-b"}


# ---- vms.tf_managed: which machines ECM created -------------------------------------------------------------

def vm_rows(session, conn, ids, **names):
    """Inventory rows for a create's machines, as a Proxmox sync would leave them (unmarked)."""
    from app.models import Vm
    for name, vmid in ids.items():
        session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=int(vmid), name=names.get(name, name),
                       status="running"))
    session.commit()


def flags(session):
    from app.models import Vm
    return {name: managed for name, managed in session.execute(select(Vm.name, Vm.tf_managed))}


def test_machines_a_create_made_are_marked_and_an_unrelated_vm_is_not(session, world, cluster, conn):
    from app.models import Vm
    from app.provisioning.ownership import mark_tf_managed
    created = reach_success(session, world, cluster, conn)
    vm_rows(session, conn, created.params["vm_ids"])
    session.add(Vm(connection_id=conn.id, pve_node="pve2", vmid=999, name="unrelated", status="running"))
    session.commit()
    assert set(flags(session).values()) == {False}                  # a sync leaves them unmarked

    assert mark_tf_managed(session, conn.id) == 3
    session.commit()

    assert flags(session) == {"lab-b-01": True, "lab-b-02": True, "lab-b-03": True, "unrelated": False}
    assert mark_tf_managed(session, conn.id) == 0                   # nothing more to change


def test_a_create_that_failed_part_way_claims_only_the_machines_it_made(session, world, cluster, conn):
    from app.provisioning.ownership import mark_tf_managed
    failed = reach_failed_apply(session, world, cluster, conn)       # two of the three VMs exist
    vm_rows(session, conn, failed.params["vm_ids"])
    assert mark_tf_managed(session, conn.id) == 2
    assert sorted(n for n, managed in flags(session).items() if managed) == ["lab-b-01", "lab-b-02"]


def test_a_dry_run_and_a_torn_down_create_claim_nothing(session, world, cluster, conn):
    from app.provisioning.ownership import created_machines
    dry = run(session, world, begin(session, cluster, conn, dry_run=True))
    assert dry.state == "succeeded" and created_machines(session) == set()
    other = Cluster(name="lab-b", ownership="managed")
    session.add(other)
    session.commit()
    created = reach_success(session, world, other, conn)
    assert len(created_machines(session)) == 3
    assert finish_teardown(session, world, created).state == "succeeded"
    assert created_machines(session) == set()


def fixture_proxmox(logged_in, session, monkeypatch):
    """The fixture Proxmox, registered and ready to sync. Its VM 301 is named fxa-01."""
    from app.discovery import factory
    from app.models import ProxmoxConnection
    from tests.fixtures.transport import FixtureTransport
    monkeypatch.setattr(factory, "transport", FixtureTransport())
    added = logged_in.post("/api/proxmox", json={"name": "lab", "api_url": "https://pve.test:8006",
                                                 "token_id": "ro@pve!ecm", "token_secret": "fixture-pve-secret-value"},
                           headers=H).json()
    return session.get(ProxmoxConnection, added["id"])


def a_create_that_made(session, cluster, conn, name, vmid):
    session.add(Operation(kind="tf.create", state="succeeded", cluster_id=cluster.id, dry_run=False,
                          params={"proxmox_connection_id": conn.id, "vm_ids": {name: vmid}},
                          result={"resources_in_state": [f'module.node["{name}"].proxmox_virtual_environment_vm.node']}))
    session.commit()


def test_a_sync_marks_the_machines_a_create_made_and_nothing_else(logged_in, session, cluster, monkeypatch):
    from app.discovery import sync
    pve = fixture_proxmox(logged_in, session, monkeypatch)
    a_create_that_made(session, cluster, pve, "fxa-01", 301)
    sync.sync_proxmox(session, pve)
    assert [n for n, managed in flags(session).items() if managed] == ["fxa-01"]


def test_a_sync_clears_the_mark_when_a_different_vm_has_the_id_of_one_ecm_made(
        logged_in, session, cluster, monkeypatch):
    """ECM made lab-x-01 at VMID 301. If that machine is replaced out-of-band by another VM at 301, the row's name
    changes on the next sync and the stale mark must not carry over to the stranger."""
    from app.discovery import sync
    from app.models import Vm
    pve = fixture_proxmox(logged_in, session, monkeypatch)
    sync.sync_proxmox(session, pve)                                    # row 301 exists, named fxa-01
    a_create_that_made(session, cluster, pve, "lab-x-01", 301)
    row = session.scalar(select(Vm).where(Vm.vmid == 301))
    row.name, row.tf_managed = "lab-x-01", True                        # as it was while ECM's machine had the id
    session.commit()

    sync.sync_proxmox(session, pve)                                    # the fixture now reports fxa-01 at 301

    assert flags(session)["fxa-01"] is False and session.scalar(select(Vm).where(Vm.vmid == 301)).name == "fxa-01"


def test_a_teardown_is_refused_while_another_vm_has_one_of_the_creates_ids(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    ids = created.params["vm_ids"]
    first = next(iter(ids))
    vm_rows(session, conn, ids, **{first: "someone-elses"})
    with pytest.raises(OperationRefused, match=r"only destroys machines ECM created.*\(someone-elses\)"):
        start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin", confirm_data_loss=True)


def test_a_teardown_right_after_a_create_marks_the_machines_first_instead_of_waiting_for_a_sync(
        session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    vm_rows(session, conn, created.params["vm_ids"])                   # seen by a sync, not yet marked
    assert finish_teardown(session, world, created).state == "succeeded"


def test_a_machine_with_the_right_name_that_no_create_made_blocks_a_teardown(session, world, cluster, conn):
    """A failed create that never made lab-b-03 must not destroy a lab-b-03 someone else has at that id."""
    failed = reach_failed_apply(session, world, cluster, conn)         # made lab-b-01 and lab-b-02 only
    vm_rows(session, conn, failed.params["vm_ids"])
    with pytest.raises(OperationRefused, match=r"2 \(lab-b-03\)|\(lab-b-03\)"):
        start_cleanup(session, create_op_id=failed.id, confirm_name="lab-b", actor="admin")


def test_the_destroy_checks_again_just_before_it_applies(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin",
                             confirm_data_loss=True)
    teardown = run(session, world, teardown)                           # planned, waiting for approval
    first = next(iter(created.params["vm_ids"]))
    vm_rows(session, conn, created.params["vm_ids"], **{first: "someone-elses"})   # a sync saw a stranger meanwhile
    operations.approve_operation(session, teardown.id, teardown.plan_digest, "admin")
    with pytest.raises(tfop.ApplyRefused, match="only destroys machines ECM created"):
        run(session, world, teardown)
    assert world.calls.count("apply") == 1                             # only the create's apply ever ran


# ---- a dry run leaves nothing behind but its own record ----------------------------------------------------

def test_a_dry_run_removes_the_cluster_made_for_it_and_keeps_its_own_record(session, world, cluster, conn):
    cluster_id = cluster.id
    dry = run(session, world, begin(session, cluster, conn, dry_run=True))

    assert dry.state == "succeeded" and dry.plan_digest                      # it planned, and the plan is still there
    assert session.get(Cluster, cluster_id) is None                          # but no empty cluster is left behind
    assert dry.cluster_id is None and dry.params["state"]["name"] == "lab-b"
    assert not (world.root / cluster_id).exists()                            # nor its workspace files
    event = session.scalars(select(AuditEvent).where(AuditEvent.action == "cluster.remove")).one()
    assert event.details["reason"] == "dry run" and event.details["operation"] == dry.id


def test_a_failed_dry_run_removes_its_cluster_too_and_cannot_be_retried(session, world, cluster, conn):
    world.init_error = "terraform init failed: registry unreachable"
    dry = begin(session, cluster, conn, dry_run=True)
    cluster_id = cluster.id
    with pytest.raises(Exception, match="init failed"):
        run(session, world, dry)
    session.refresh(dry)
    assert dry.state == "failed" and session.get(Cluster, cluster_id) is None
    with pytest.raises(operations.RetryRefused, match="a dry run is not retried"):
        operations.retry_operation(session, dry.id)


def test_a_dry_run_never_touches_a_cluster_that_has_real_history(session, world, cluster, conn):
    failed = reach_failed_apply(session, world, cluster, conn)                # a real create that left machines
    cluster_id = cluster.id
    dry = run(session, world, begin(session, cluster, conn, dry_run=True))
    assert dry.state == "succeeded"
    assert session.get(Cluster, cluster_id) is not None and dry.cluster_id == cluster_id
    assert (world.root / cluster_id).is_dir()                                 # its workspace, with state, stays
    assert session.get(Operation, failed.id).cluster_id == cluster_id


def test_a_dry_run_on_a_stub_plans_on_local_state_and_anything_else_on_the_database(
        session, world, cluster, conn, monkeypatch):
    seen = []
    real = tfop.render_input

    def spy(*args, **kwargs):
        seen.append(kwargs.get("state_backend", "pg"))
        return real(*args, **kwargs)
    monkeypatch.setattr(tfop, "render_input", spy)

    stub_dry = begin(session, cluster, conn, dry_run=True)
    seen.clear()                              # begin() renders once to check the parameters; only the job's renders count
    run(session, world, stub_dry)
    assert seen and set(seen) == {"local"}    # no schema is made in the state database for it

    kept = Cluster(name="lab-c", ownership="managed")
    session.add(kept)
    session.commit()
    planned = begin(session, kept, conn)      # a real operation: state may exist, so the database holds it
    seen.clear()
    run(session, world, planned)
    assert seen and set(seen) == {"pg"}

    operations.cancel_operation(session, planned.id)
    later_dry = begin(session, kept, conn, dry_run=True)   # a dry run on a cluster that has a real operation
    seen.clear()
    run(session, world, later_dry)
    assert seen and set(seen) == {"pg"}


def test_dry_runs_for_the_same_new_name_never_pile_up_clusters(session, world, conn):
    for _ in range(3):
        stub = Cluster(name="lab-b", ownership="managed")                     # as a create request makes it
        session.add(stub)
        session.commit()
        assert run(session, world, begin(session, stub, conn, dry_run=True)).state == "succeeded"
    assert session.scalars(select(Cluster)).all() == []
    assert len(session.scalars(select(Operation).where(Operation.dry_run.is_(True))).all()) == 3


# ---- the desired state a cluster has now -----------------------------------------------------------------------

def test_a_create_that_bootstraps_records_its_parameters_as_the_clusters_desired_state(
        session, world, cluster, conn):
    assert cluster.desired is None
    created = reach_success(session, world, cluster, conn)
    session.refresh(cluster)
    assert cluster.desired == created.params
    cluster.desired["state"]["nodes"][0]["data_disk_gb"] = 999            # a later change must not rewrite history
    assert created.params["state"]["nodes"][0]["data_disk_gb"] != 999


def test_a_create_that_did_not_bootstrap_leaves_no_desired_state(session, world, cluster, conn):
    world.ansible_error = "the ansible-playbook binary was not found"
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(tfop.ConfigureFailed):
        run(session, world, op)
    session.refresh(cluster)
    assert cluster.desired is None


def test_a_teardown_starts_from_the_desired_state_not_from_the_creates_old_parameters(
        session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    session.refresh(cluster)
    changed = {**cluster.desired, "pool_id": "a-changed-pool"}
    cluster.desired = changed
    session.commit()
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin",
                             confirm_data_loss=True)
    assert teardown.params["pool_id"] == "a-changed-pool" and created.params.get("pool_id") != "a-changed-pool"


# ---- tf.update: changing a cluster that is built --------------------------------------------------------------

def an_update(session, world, cluster, size=200):
    """A grown-disk update of a built cluster, planned and waiting for approval."""
    from app.provisioning.lifecycle import ExpandDisk, plan_expand_disk
    from app.provisioning.operation import start_update
    session.refresh(cluster)
    params = plan_expand_disk(session, cluster, ExpandDisk(data_disk_gb=size))
    world.create_changes = [(a, "update") for a in ADDRS]                    # Terraform changes each disk in place
    return run(session, world, start_update(session, cluster_id=cluster.id, params=params, actor="admin"))


def test_an_update_plans_waits_for_approval_applies_and_converges_without_a_restart(
        session, world, cluster, conn):
    reach_success(session, world, cluster, conn)
    update = an_update(session, world, cluster)
    assert update.kind == "tf.update" and update.state == "pending_approval"
    assert update.plan_summary["updates"] == 3 and update.plan_summary["adds"] == 0
    assert "grow the data disk" in update.plan_summary["configure"]
    assert world.calls.count("apply") == 1                                   # only the create's apply so far

    operations.approve_operation(session, update.id, update.plan_digest, "admin")
    update = run(session, world, update)

    assert update.state == "succeeded" and world.calls.count("apply") == 2
    request = world.ansible_requests[-1]
    assert request.kind == "converge" and request.check is False and request.bootstrapped_at is not None
    assert {n.data_disk_gb for n in request.state.nodes} == {200}            # the converge sees the new size
    assert request.ca_cert_pem and request.elastic_password is None          # the cluster's CA, no password
    session.refresh(cluster)
    assert {n["data_disk_gb"] for n in cluster.desired["state"]["nodes"]} == {200}
    assert "change" not in cluster.desired                                   # a description, not state
    event = session.scalars(select(AuditEvent).where(AuditEvent.action == "operation.start")
                            .order_by(AuditEvent.id.desc())).first()
    assert event.details["kind"] == "tf.update" and event.details["change"]["kind"] == "expand_disk"


def test_an_update_that_would_delete_or_replace_anything_is_rejected_and_changes_nothing(
        session, world, cluster, conn):
    reach_success(session, world, cluster, conn)
    session.refresh(cluster)
    before = {n["data_disk_gb"] for n in cluster.desired["state"]["nodes"]}
    from app.provisioning.lifecycle import ExpandDisk, plan_expand_disk
    from app.provisioning.operation import start_update
    params = plan_expand_disk(session, cluster, ExpandDisk(data_disk_gb=200))
    world.create_changes = [(ADDRS[0], "update"), (ADDRS[1], "replace")]     # a disk that forces a new VM
    update = start_update(session, cluster_id=cluster.id, params=params, actor="admin")
    with pytest.raises(PlanRejected, match="must not touch existing resources.*replace"):
        run(session, world, update)
    assert update.state == "failed" and update.plan_digest is None
    assert world.calls.count("apply") == 1
    session.refresh(cluster)
    assert {n["data_disk_gb"] for n in cluster.desired["state"]["nodes"]} == before


def test_a_failed_converge_keeps_what_terraform_changed_and_a_retry_runs_it_again(session, world, cluster, conn):
    reach_success(session, world, cluster, conn)
    update = an_update(session, world, cluster)
    operations.approve_operation(session, update.id, update.plan_digest, "admin")
    world.ansible_error = "the ansible-playbook binary was not found"
    with pytest.raises(tfop.ConfigureFailed, match="What Terraform changed is kept"):
        run(session, world, update)
    session.refresh(cluster)
    assert {n["data_disk_gb"] for n in cluster.desired["state"]["nodes"]} == {200}   # Terraform has it, so it is the state

    world.ansible_error = None
    world.create_changes = []                                                # the retry's plan sees nothing left to do
    operations.retry_operation(session, update.id)
    update = run(session, world, update)
    assert update.state == "succeeded" and world.calls.count("apply") == 2           # not applied a second time
    assert [r.kind for r in world.ansible_requests] == ["create", "converge", "converge"]


def test_an_update_whose_plan_is_empty_skips_approval_and_still_converges(session, world, cluster, conn):
    """A disk someone already grew by hand: Terraform matches, but the filesystem may still need growing."""
    reach_success(session, world, cluster, conn)
    from app.provisioning.lifecycle import ExpandDisk, plan_expand_disk
    from app.provisioning.operation import start_update
    params = plan_expand_disk(session, cluster, ExpandDisk(data_disk_gb=200))
    world.create_changes = []
    update = run(session, world, start_update(session, cluster_id=cluster.id, params=params, actor="admin"))
    assert update.state == "succeeded" and world.calls.count("apply") == 1
    assert world.ansible_requests[-1].kind == "converge"
    session.refresh(cluster)
    assert {n["data_disk_gb"] for n in cluster.desired["state"]["nodes"]} == {200}


def test_an_update_is_refused_on_a_cluster_that_is_not_built_or_has_foreign_machines(session, world, cluster, conn):
    from app.models import Vm
    from app.provisioning.operation import start_update
    params = params_for(conn)
    with pytest.raises(OperationRefused, match="not finished being built"):
        start_update(session, cluster_id=cluster.id, params=params, actor="admin")
    reach_success(session, world, cluster, conn)
    first_vmid = int(next(iter(params["vm_ids"].values())))
    session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=first_vmid, name="someone-elses", status="running"))
    session.commit()
    with pytest.raises(OperationRefused, match="only touches machines ECM created.*someone-elses"):
        start_update(session, cluster_id=cluster.id, params=params, actor="admin")


def test_the_destroy_after_an_update_still_removes_everything(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    update = an_update(session, world, cluster)
    operations.approve_operation(session, update.id, update.plan_digest, "admin")
    assert run(session, world, update).state == "succeeded"
    cluster_id = cluster.id
    assert finish_teardown(session, world, created).state == "succeeded"
    assert session.get(Cluster, cluster_id) is None


def test_the_expand_disk_endpoint_makes_a_plan_for_approval_and_enqueues_it(logged_in, session, world, cluster, conn):
    from procrastinate import testing

    from app import jobs
    reach_success(session, world, cluster, conn)
    with jobs.queue.replace_connector(testing.InMemoryConnector()) as q:
        r = logged_in.post(f"/api/clusters/{cluster.id}/expand-disk", json={"data_disk_gb": 200}, headers=H)
        assert r.status_code == 202 and len(q.connector.jobs) == 1
    body = r.json()
    assert set(body["change"]["nodes"]) == {"lab-b-01", "lab-b-02", "lab-b-03"}
    detail = logged_in.get(f"/api/operations/{body['operation_id']}").json()
    assert detail["kind"] == "tf.update" and detail["cluster_id"] == cluster.id and detail["dry_run"] is False
    session.refresh(cluster)
    assert {n["data_disk_gb"] for n in cluster.desired["state"]["nodes"]} == {100}   # nothing changes before approval


@pytest.mark.parametrize("body,status,text", [
    ({"data_disk_gb": 50}, 409, "cannot be shrunk"),
    ({"data_disk_gb": 100}, 409, "already 100 GB"),
    ({"data_disk_gb": 200, "nodes": ["nope"]}, 409, "no node named nope"),
    ({"data_disk_gb": 5}, 422, None),
    ({"data_disk_gb": 200, "extra": 1}, 422, None),
])
def test_the_expand_disk_endpoint_refuses_a_bad_request_with_the_reason(
        logged_in, session, world, cluster, conn, body, status, text):
    reach_success(session, world, cluster, conn)
    r = logged_in.post(f"/api/clusters/{cluster.id}/expand-disk", json=body, headers=H)
    assert r.status_code == status
    if text:
        assert text in r.json()["detail"]
    assert session.scalars(select(Operation).where(Operation.kind == "tf.update")).all() == []


def test_the_expand_disk_endpoint_needs_a_login_the_csrf_header_and_a_known_cluster(
        logged_in, client, session, world, cluster, conn):
    reach_success(session, world, cluster, conn)
    path = f"/api/clusters/{cluster.id}/expand-disk"
    assert logged_in.post("/api/clusters/nope/expand-disk", json={"data_disk_gb": 200}, headers=H).status_code == 404
    assert logged_in.post(path, json={"data_disk_gb": 200}).status_code in (400, 403)      # no CSRF header
    client.cookies.clear()
    assert client.post(path, json={"data_disk_gb": 200}, headers=H).status_code == 401


def test_the_expand_disk_endpoint_refuses_a_cluster_with_an_operation_running(logged_in, session, world, cluster, conn):
    reach_success(session, world, cluster, conn)
    update = an_update(session, world, cluster)                           # planned and waiting: it is active
    assert update.state == "pending_approval"
    r = logged_in.post(f"/api/clusters/{cluster.id}/expand-disk", json={"data_disk_gb": 300}, headers=H)
    assert r.status_code == 409 and "already has an active operation" in r.json()["detail"]


def test_the_lifecycle_says_what_can_be_changed_and_why_not_while_an_operation_runs(session, world, cluster, conn):
    assert lifecycle(session, cluster)["can_change"] is False and lifecycle(session, cluster)["data_disks"] == {}
    reach_success(session, world, cluster, conn)
    assert lifecycle(session, cluster)["can_change"] is True
    update = an_update(session, world, cluster)                              # planned, waiting for approval
    got = lifecycle(session, cluster)
    assert got["can_change"] is False and got["busy_operation_id"] == update.id
    operations.approve_operation(session, update.id, update.plan_digest, "admin")
    run(session, world, update)
    got = lifecycle(session, cluster)
    assert got["can_change"] is True and set(got["data_disks"].values()) == {200}   # the new size, once applied


# ---- resizing CPU and RAM ---------------------------------------------------------------------------------------

def a_resize(session, world, cluster, **sizes):
    from app.provisioning.lifecycle import ResizeNodes, plan_resize
    from app.provisioning.operation import start_update
    session.refresh(cluster)
    params = plan_resize(session, cluster, ResizeNodes(**sizes))
    world.create_changes = [(a, "update") for a in ADDRS]
    return run(session, world, start_update(session, cluster_id=cluster.id, params=params, actor="admin"))


def test_a_resize_applies_the_new_size_then_converges_then_restarts_the_nodes(session, world, cluster, conn):
    reach_success(session, world, cluster, conn)
    update = a_resize(session, world, cluster, cores=8, ram_mb=16384)
    assert update.state == "pending_approval" and update.plan_summary["updates"] == 3
    assert "then ECM restarts the nodes one at a time" in update.plan_summary["configure"]
    assert [name for name, _ in steps(session, update)] == [
        "render", "init", "plan", "approval", "apply", "configure", "restart"]

    operations.approve_operation(session, update.id, update.plan_digest, "admin")
    update = run(session, world, update)

    assert update.state == "succeeded" and world.calls.count("apply") == 2
    assert [r.kind for r in world.ansible_requests] == ["create", "converge", "restart"]
    converge, restart = world.ansible_requests[1:]
    assert {(n.cores, n.ram_mb) for n in converge.state.nodes} == {(8, 16384)}   # the converge writes the new heap
    assert restart.kind == "restart" and restart.check is False and restart.elastic_password is None
    assert restart.vm_ids == update.params["vm_ids"] and restart.placement == update.params["placement"]
    assert restart.es_api_key == API_KEY and restart.es_ca_pem == CA_CERT        # ECM's own key and the cluster's CA
    assert restart.pve_api_url == conn.api_url and restart.pve_token_secret == SECRET
    session.refresh(cluster)
    assert {(n["cores"], n["ram_mb"]) for n in cluster.desired["state"]["nodes"]} == {(8, 16384)}
    assert "change" not in cluster.desired
    assert "every node runs at its new size" in logs(session, update)


def test_a_resize_whose_plan_would_replace_a_machine_is_rejected_and_changes_nothing(session, world, cluster, conn):
    from app.provisioning.lifecycle import ResizeNodes, plan_resize
    from app.provisioning.operation import start_update
    reach_success(session, world, cluster, conn)
    session.refresh(cluster)
    params = plan_resize(session, cluster, ResizeNodes(cores=8))
    world.create_changes = [(ADDRS[0], "replace")]                          # the provider rebuilds the VM instead
    update = start_update(session, cluster_id=cluster.id, params=params, actor="admin")
    with pytest.raises(PlanRejected, match="must not touch existing resources.*replace"):
        run(session, world, update)
    assert world.calls.count("apply") == 1
    session.refresh(cluster)
    assert {n["cores"] for n in cluster.desired["state"]["nodes"]} == {4}


def test_the_resize_endpoint_makes_a_plan_and_the_operation_shows_what_was_asked(
        logged_in, session, world, cluster, conn):
    from procrastinate import testing

    from app import jobs
    reach_success(session, world, cluster, conn)
    with jobs.queue.replace_connector(testing.InMemoryConnector()) as q:
        r = logged_in.post(f"/api/clusters/{cluster.id}/resize", json={"cores": 8, "nodes": ["lab-b-01"]}, headers=H)
        assert r.status_code == 202 and len(q.connector.jobs) == 1
    detail = logged_in.get(f"/api/operations/{r.json()['operation_id']}").json()
    assert detail["kind"] == "tf.update" and detail["change"]["kind"] == "resize"
    assert detail["change"]["nodes"] == {"lab-b-01": {"cores": {"from": 4, "to": 8}}}
    session.refresh(cluster)
    assert {n["cores"] for n in cluster.desired["state"]["nodes"]} == {4}   # nothing changes before approval


@pytest.mark.parametrize("body,status,text", [
    ({"cores": 4}, 409, "already has 4 cores"),
    ({"cores": 8, "nodes": ["nope"]}, 409, "no node named nope"),
    ({}, 422, None),
    ({"cores": 0}, 422, None),
    ({"cores": 8, "extra": 1}, 422, None),
])
def test_the_resize_endpoint_refuses_a_bad_request_with_the_reason(
        logged_in, session, world, cluster, conn, body, status, text):
    reach_success(session, world, cluster, conn)
    r = logged_in.post(f"/api/clusters/{cluster.id}/resize", json=body, headers=H)
    assert r.status_code == status
    if text:
        assert text in r.json()["detail"]
    assert session.scalars(select(Operation).where(Operation.kind == "tf.update")).all() == []


def test_the_resize_endpoint_needs_a_login_the_csrf_header_and_a_known_cluster(
        logged_in, client, session, world, cluster, conn):
    reach_success(session, world, cluster, conn)
    path = f"/api/clusters/{cluster.id}/resize"
    assert logged_in.post("/api/clusters/nope/resize", json={"cores": 8}, headers=H).status_code == 404
    assert logged_in.post(path, json={"cores": 8}).status_code in (400, 403)
    client.cookies.clear()
    assert client.post(path, json={"cores": 8}, headers=H).status_code == 401


def test_a_failed_rolling_restart_stops_the_operation_and_a_retry_runs_the_rest_without_applying_again(
        session, world, cluster, conn):
    reach_success(session, world, cluster, conn)
    update = a_resize(session, world, cluster, cores=8)
    operations.approve_operation(session, update.id, update.plan_digest, "admin")
    world.restart_error = "The rolling restart stopped at lab-b-02: the cluster was not green"
    with pytest.raises(tfop.RestartFailed, match="stopped at lab-b-02.*Nodes already restarted stay restarted"):
        run(session, world, update)
    assert update.state == "failed" and world.calls.count("apply") == 2
    session.refresh(cluster)
    assert {n["cores"] for n in cluster.desired["state"]["nodes"]} == {8}      # Terraform has it, so it is the state

    world.restart_error = None
    world.create_changes = []                                                  # the retry's plan sees nothing to do
    operations.retry_operation(session, update.id)
    update = run(session, world, update)
    assert update.state == "succeeded" and world.calls.count("apply") == 2     # not applied a second time
    assert [r.kind for r in world.ansible_requests] == ["create", "converge", "restart", "converge", "restart"]


def test_a_resize_is_refused_at_plan_time_when_the_token_cannot_change_or_restart_the_vms(
        session, world, cluster, conn):
    from app.provisioning.lifecycle import ResizeNodes, plan_resize
    from app.provisioning.operation import start_update
    reach_success(session, world, cluster, conn)
    session.refresh(cluster)
    params = plan_resize(session, cluster, ResizeNodes(cores=8))
    world.perms["/pool/ecm"].pop("VM.PowerMgmt")
    update = start_update(session, cluster_id=cluster.id, params=params, actor="admin")
    with pytest.raises(PreflightFailed, match="no VM.PowerMgmt on /pool/ecm, which a resize needs"):
        run(session, world, update)
    assert world.calls.count("apply") == 1                                     # nothing was applied


def test_a_disk_change_does_not_need_the_rights_to_change_cpu_or_restart_a_vm(session, world, cluster, conn):
    reach_success(session, world, cluster, conn)
    for privilege in ("VM.PowerMgmt", "VM.Config.CPU", "VM.Config.Memory"):
        world.perms["/pool/ecm"].pop(privilege)
    assert an_update(session, world, cluster).state == "pending_approval"      # planned, not refused


def test_a_resize_cannot_restart_a_cluster_ecm_holds_no_api_key_for(session, world, cluster, conn):
    reach_success(session, world, cluster, conn)
    update = a_resize(session, world, cluster, cores=8)
    operations.approve_operation(session, update.id, update.plan_digest, "admin")
    for cred in session.scalars(select(Credential).where(Credential.kind == "es_api_key")):
        session.delete(cred)
    session.commit()
    with pytest.raises(tfop.RestartFailed, match="no API key or CA certificate"):
        run(session, world, update)


# ---- what a node added later changes in what already exists ------------------------------------------------------

NEW_ADDR = 'module.node["lab-b-04"].proxmox_virtual_environment_vm.node'


def an_added_node(session, cluster, conn, state="succeeded", with_result=True, change_kind="add_node"):
    """An add-node update's record, as a successful one leaves it: the whole state list in its result."""
    from datetime import UTC, datetime
    params = params_for(conn)
    params["addresses"]["lab-b-04"] = "192.0.2.118"
    params["vm_ids"]["lab-b-04"] = 509
    params["change"] = {"kind": change_kind}
    op = Operation(kind="tf.update", state=state, cluster_id=cluster.id, dry_run=False, params=params,
                   finished_at=datetime.now(UTC),
                   result={"resources_in_state": [*ADDRS, NEW_ADDR]} if with_result else None)
    session.add(op)
    session.commit()
    return op


def test_a_node_being_added_holds_its_address_and_vmid_like_a_create_does(session, world, cluster, conn):
    from app.provisioning.create import _reservations
    other = Cluster(name="lab-z", ownership="managed")
    session.add(other)
    session.commit()
    an_added_node(session, cluster, conn, state="running")
    addresses, vmids = _reservations(session, own_cluster=other.id)
    assert "192.0.2.118" in addresses and 509 in vmids


def test_a_removed_cluster_or_a_change_that_added_no_node_holds_nothing(session, world, cluster, conn):
    from app.provisioning.create import _reservations
    other = Cluster(name="lab-z", ownership="managed")
    session.add(other)
    session.commit()
    resized = an_added_node(session, cluster, conn, state="succeeded", change_kind="resize")
    detached = an_added_node(session, cluster, conn, state="running")
    detached.cluster_id = None
    session.commit()
    addresses, vmids = _reservations(session, own_cluster=other.id)
    assert "192.0.2.118" not in addresses and 509 not in vmids
    assert resized.params["vm_ids"]["lab-b-04"] == 509                          # the data was there, and was ignored


def test_a_teardown_may_delete_a_node_that_a_later_change_added(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    an_added_node(session, cluster, conn)
    world.destroy_changes = [(a, "delete") for a in [*ADDRS, NEW_ADDR]]
    assert finish_teardown(session, world, created).state == "succeeded"


def test_a_teardown_still_refuses_to_delete_something_nobody_recorded(session, world, cluster, conn):
    created = reach_success(session, world, cluster, conn)
    an_added_node(session, cluster, conn)
    world.destroy_changes = [(a, "delete") for a in [*ADDRS, NEW_ADDR]] + [("proxmox_virtual_environment_vm.es01", "delete")]
    teardown = start_cleanup(session, create_op_id=created.id, confirm_name="lab-b", actor="admin",
                             confirm_data_loss=True)
    with pytest.raises(PlanRejected, match="es01.*ECM did not record making"):
        run(session, world, teardown)


def test_a_node_an_add_node_update_made_is_marked_as_ecms_and_stops_being_once_its_cluster_is_gone(
        session, world, cluster, conn):
    from app.provisioning.ownership import created_machines
    reach_success(session, world, cluster, conn)
    update = an_added_node(session, cluster, conn)
    assert (conn.id, 509, "lab-b-04") in created_machines(session)
    update.cluster_id = None                                                    # a teardown detached it
    session.commit()
    assert (conn.id, 509, "lab-b-04") not in created_machines(session)


def test_an_add_node_that_applied_nothing_and_a_resize_claim_no_new_machine(session, world, cluster, conn):
    from app.provisioning.ownership import created_machines
    reach_success(session, world, cluster, conn)
    an_added_node(session, cluster, conn, with_result=False)                    # failed before it made the VM
    an_added_node(session, cluster, conn, change_kind="resize")
    assert (conn.id, 509, "lab-b-04") not in created_machines(session)


def test_placement_leaves_a_clusters_own_machines_out_of_what_the_hosts_carry(session, world, cluster, conn, monkeypatch):
    from app.discovery import factory as _factory  # noqa: F401  (imported so the fixtures' patches are in place)
    from app.models import PveNode, Vm
    from app.provisioning import create
    from app.provisioning.create import _placement
    session.add(PveNode(connection_id=conn.id, name="pve1", status="online",
                        usage={"maxcpu": 16, "cpu": 0.1, "maxmem": 64 * 1024 ** 3, "mem": 8 * 1024 ** 3}))
    for vmid, name in ((500, "lab-b-01"), (800, "template"), (900, "someone-elses")):
        session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=vmid, name=name, status="running",
                       is_template=name == "template", cpu_cores=4, memory_mb=8192))
    session.commit()
    seen = []
    real = create.host_views_from_rows
    monkeypatch.setattr(create, "host_views_from_rows",
                        lambda nodes, storages, vms: (seen.append(sorted(v["memory_mb"] for v in vms)), real(nodes, storages, vms))[1])
    template = session.scalar(select(Vm).where(Vm.name == "template"))
    state = build_desired_state(TopologyPreset.single_node, "lab-b", "9.4.3")
    for excluded in (frozenset(), frozenset({"lab-b-01"})):
        with contextlib.suppress(Exception):      # placing may fail for lack of storage rows; only what was passed matters
            _placement(session, conn, state, "tank", template, exclude_vms=excluded)
    assert len(seen) == 2 and len(seen[0]) == len(seen[1]) + 1                  # one machine fewer was charged
