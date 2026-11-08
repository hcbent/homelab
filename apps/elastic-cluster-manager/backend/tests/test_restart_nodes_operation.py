# ruff: noqa: F811  (the fixtures are imported from the removal tests and used by name)
"""Restarting nodes as an operation: no Terraform at all, an approval that is of the exact plan, what is handed to Ansible, what a
failure leaves, and how a retry resumes. Terraform and Ansible are the usual fakes."""
from datetime import UTC

import pytest
from sqlalchemy import select

from app import operations
from app.desired.models import DesiredState
from app.models import Credential, Operation, Vm
from app.provisioning import restart as restart_module
from app.provisioning.lifecycle import RestartNodes, plan_restart_nodes
from app.provisioning.operation import OperationRefused, PreflightFailed, start_restart
from app.provisioning.restart import RestartFailed, plan_digest
from tests.test_remove_nodes import FakeEs
from tests.test_remove_nodes_operation import NAMES, approve_and_run, fail_kinds, seen, six  # noqa: F401
from tests.test_tf_operations import (  # noqa: F401  (fixtures and helpers shared with the other operation tests)
    cluster,
    conn,
    logs,
    run,
    steps,
    world,
)


def planned(session, cluster, *names, es=None):
    es = es or FakeEs(DesiredState.model_validate(cluster.desired["state"]))
    return plan_restart_nodes(session, cluster, RestartNodes(nodes=list(names) or None), es)


def restarting(session, cluster, *names, es=None):
    return start_restart(session, cluster_id=cluster.id, params=planned(session, cluster, *names, es=es), actor="admin")


# -- the sequence ---------------------------------------------------------------------------------------------------------------

def test_a_restart_has_no_terraform_step_and_waits_for_an_approval_of_the_exact_plan(session, world, six, seen):
    terraform_before = list(world.calls)
    op = run(session, world, restarting(session, six, "lab-b-05", "lab-b-06"))
    assert op.kind == "es.restart" and op.state == "pending_approval"
    assert [n for n, _ in steps(session, op)] == ["plan", "approval", "restart"]
    assert op.plan_summary["restart"] == 2 and op.plan_summary["start"] == 0 and "restart 2 nodes one at a time" in op.plan_summary["configure"]
    assert op.plan_digest == plan_digest(six.id, op.params["change"])
    assert seen == [] and world.calls == terraform_before                  # nothing asked of Ansible, and Terraform never involved


def test_approving_runs_the_playbook_with_the_plan_and_nothing_else_touches_terraform(session, world, six, seen):
    before = list(world.calls)
    op = approve_and_run(session, world, run(session, world, restarting(session, six)))
    assert op.state == "succeeded" and world.calls == before
    assert seen == [("restart", 1)]
    request = world.ansible_requests[-1]
    change = op.params["change"]
    assert request.kind == "restart"
    assert request.restart_plan == [{"name": n, "action": "restart"} for n in change["order"]]
    assert request.restart_present == change["present"] and request.restart_since == int(op.started_at.replace(tzinfo=UTC).timestamp())
    assert request.es_api_key and request.es_ca_pem and request.pve_token_secret and request.vm_ids == six.desired["vm_ids"]
    assert "every node in the plan was restarted and the cluster is green" in logs(session, op)
    assert "restarting, in this order: lab-b-06" in logs(session, op)


def test_a_node_that_is_down_is_in_the_plan_as_a_start_and_first(session, world, six):
    session.query(Vm).filter(Vm.vmid == 504).one().status = "stopped"
    session.commit()
    es = FakeEs(DesiredState.model_validate(six.desired["state"]), status="yellow")
    es.hidden = {"lab-b-05"}
    op = approve_and_run(session, world, run(session, world, restarting(session, six, "lab-b-04", "lab-b-05", es=es)))
    assert op.state == "succeeded"
    assert world.ansible_requests[-1].restart_plan == [{"name": "lab-b-05", "action": "start"},
                                                      {"name": "lab-b-04", "action": "restart"}]
    assert "lab-b-05" not in world.ansible_requests[-1].restart_present


def test_a_different_plan_has_a_different_digest_and_the_wrong_digest_is_refused(session, world, six):
    a = run(session, world, restarting(session, six, "lab-b-04"))
    digest_a = a.plan_digest
    operations.cancel_operation(session, a.id)
    b = run(session, world, restarting(session, six, "lab-b-05"))
    assert b.plan_digest != digest_a
    with pytest.raises(operations.ApprovalRefused):
        operations.approve_operation(session, b.id, digest_a, "admin")
    assert b.state == "pending_approval"


# -- failures --------------------------------------------------------------------------------------------------------------------

def test_a_failed_restart_says_what_stays_done_and_a_retry_needs_a_new_approval_and_then_resumes(session, world, six, seen):
    op = run(session, world, restarting(session, six, "lab-b-04", "lab-b-05"))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    world.fail_kinds = {"restart": "The restart stopped at lab-b-05: the node did not come back"}
    with pytest.raises(RestartFailed, match="stopped at lab-b-05.*Nodes already restarted stay restarted.*skips every node"):
        run(session, world, op)
    assert [n for n, s in steps(session, op) if s == "failed"] == ["restart"]

    world.fail_kinds = {}
    operations.retry_operation(session, op.id)
    op = run(session, world, op)
    assert op.state == "pending_approval" and op.approved_digest is None       # planned again, awaiting a new approval
    op = approve_and_run(session, world, op)
    assert op.state == "succeeded" and [k for k, _ in seen] == ["restart", "restart"]
    created = int(op.started_at.replace(tzinfo=UTC).timestamp())
    assert world.ansible_requests[-1].restart_since == created                  # still when the operation began, so a retry skips what was done


def test_the_token_must_be_able_to_power_vms_and_the_run_stops_before_asking_ansible_if_it_cannot(session, world, six, seen):
    op = run(session, world, restarting(session, six, "lab-b-04"))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    world.perms["/pool/ecm"].pop("VM.PowerMgmt")
    with pytest.raises(PreflightFailed, match="no VM.PowerMgmt on /pool/ecm, which restarting or starting a VM in it needs"):
        run(session, world, op)
    assert seen == []
    world.perms["/pool/ecm"]["VM.PowerMgmt"] = 1
    world.perms["/pool/ecm"].pop("VM.Audit")                                   # it also has to see where each VM is now
    operations.retry_operation(session, op.id)
    op = run(session, world, op)
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(PreflightFailed, match="no VM.Audit on /pool/ecm"):
        run(session, world, op)


def test_a_cluster_with_no_api_key_is_not_restarted_and_ansible_is_not_asked(session, world, six, seen):
    op = run(session, world, restarting(session, six, "lab-b-04"))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    for cred in session.scalars(select(Credential).where(Credential.kind == "es_api_key")):
        session.delete(cred)
    session.commit()
    with pytest.raises(RestartFailed, match="no API key or CA certificate.*Nothing was restarted"):
        run(session, world, op)
    assert seen == []


def test_a_machine_that_is_not_ecms_blocks_the_restart_at_the_start_and_again_before_it_runs(session, world, six, seen):
    params = planned(session, six, "lab-b-04")
    row = session.scalar(select(Vm).where(Vm.vmid == 503))
    row.name, row.tf_managed = "someone-elses", False
    session.commit()
    with pytest.raises(OperationRefused, match="a restart only touches machines ECM created.*503"):
        start_restart(session, cluster_id=six.id, params=params, actor="admin")
    row.name, row.tf_managed = "lab-b-04", True
    session.commit()
    op = run(session, world, start_restart(session, cluster_id=six.id, params=params, actor="admin"))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    row.name, row.tf_managed = "someone-elses", False                          # it changes after the approval
    session.commit()
    with pytest.raises(Exception, match="a restart only touches machines ECM created"):
        run(session, world, op)
    assert seen == []


def test_only_the_machines_in_the_plan_are_checked(session, world, six):
    other = session.scalar(select(Vm).where(Vm.vmid == 500))
    other.name, other.tf_managed = "someone-elses", False                       # not in this plan
    session.commit()
    assert restarting(session, six, "lab-b-04").state == "running"


def test_a_cluster_that_has_not_finished_being_built_is_refused(session, world, six):
    params = planned(session, six, "lab-b-04")
    six.bootstrapped_at = None
    session.commit()
    with pytest.raises(OperationRefused, match="has not finished being built"):
        start_restart(session, cluster_id=six.id, params=params, actor="admin")


def test_the_restart_module_is_the_only_thing_that_handles_the_kind(session, world, six):
    assert restart_module.RestartHandlers is not None
    op = restarting(session, six, "lab-b-04")
    assert session.get(Operation, op.id).kind == "es.restart"


# -- the API ----------------------------------------------------------------------------------------------------------------------

H = {"x-ecm-csrf": "1"}


@pytest.fixture
def live(monkeypatch, six):
    from app.provisioning import lifecycle
    es = FakeEs(DesiredState.model_validate(six.desired["state"]))
    monkeypatch.setattr(lifecycle, "_read_cluster", lambda db, cluster, client=None: {
        "health": es.health(), "nodes": es.nodes()["nodes"], "stats": es.nodes_stats()["nodes"],
        "shards": es.shards_sized(), "settings": es.settings(), "master": es.master()})
    return es


def test_the_restart_endpoint_plans_and_nothing_runs_before_approval(logged_in, session, world, six, live):
    from procrastinate import testing

    from app import jobs
    with jobs.queue.replace_connector(testing.InMemoryConnector()) as q:
        r = logged_in.post(f"/api/clusters/{six.id}/restart-nodes", json={"nodes": ["lab-b-05"]}, headers=H)
        assert r.status_code == 202 and len(q.connector.jobs) == 1
    detail = logged_in.get(f"/api/operations/{r.json()['operation_id']}").json()
    assert detail["kind"] == "es.restart" and detail["change"]["kind"] == "restart_nodes"
    assert detail["change"]["order"] == ["lab-b-05"] and detail["change"]["nodes"]["lab-b-05"]["action"] == "restart"


def test_the_restart_endpoint_with_no_nodes_plans_every_node(logged_in, session, world, six, live):
    from procrastinate import testing

    from app import jobs
    with jobs.queue.replace_connector(testing.InMemoryConnector()):
        r = logged_in.post(f"/api/clusters/{six.id}/restart-nodes", json={}, headers=H)
    assert r.status_code == 202 and sorted(r.json()["change"]["order"]) == sorted(NAMES)


@pytest.mark.parametrize("body,status,text", [
    ({"nodes": ["lab-b-99"]}, 409, "no node named lab-b-99"),
    ({"nodes": []}, 422, None),
    ({"nodes": ["a", "a"]}, 422, None),
    ({"nodes": ["lab-b-05"], "extra": 1}, 422, None),
])
def test_the_restart_endpoint_refuses_a_bad_request_with_the_reason(logged_in, session, world, six, live, body, status, text):
    r = logged_in.post(f"/api/clusters/{six.id}/restart-nodes", json=body, headers=H)
    assert r.status_code == status
    if text:
        assert text in r.json()["detail"]
    assert session.scalars(select(Operation).where(Operation.kind == "es.restart")).all() == []


def test_the_restart_endpoint_needs_a_login_the_csrf_header_and_a_known_cluster(logged_in, client, session, world, six, live):
    path = f"/api/clusters/{six.id}/restart-nodes"
    assert logged_in.post("/api/clusters/nope/restart-nodes", json={}, headers=H).status_code == 404
    assert logged_in.post(path, json={}).status_code in (400, 403)
    client.cookies.clear()
    assert client.post(path, json={}, headers=H).status_code == 401


def test_a_restart_in_progress_blocks_another_operation_on_the_cluster(session, world, six):
    restarting(session, six, "lab-b-04")
    with pytest.raises(operations.OperationConflict):
        restarting(session, six, "lab-b-05")
