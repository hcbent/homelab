# ruff: noqa: F811  (the fixtures are imported from the removal tests and used by name)
"""Recovering lost nodes as operations: the rebuild's phases, what it asks of Ansible, how a retry resumes after the apply, and
the forget operation, whose plan is empty by design and which must still wait for an approval."""
import pytest
from sqlalchemy import select

from app import operations
from app.configmgmt import AnsibleError
from app.desired.models import DesiredState
from app.models import EsNode, Vm
from app.provisioning import operation as tfop
from app.provisioning.lifecycle import (
    ForgetNodes,
    RebuildNodes,
    plan_forget_nodes,
    plan_rebuild_nodes,
)
from app.provisioning.operation import OperationRefused, PlanRejected, start_update
from app.provisioning.runner import ApplyOutcome
from tests.test_remove_nodes import FakeEs
from tests.test_remove_nodes_operation import ADDR, NAMES, approve_and_run, fail_kinds, seen, six  # noqa: F401
from tests.test_tf_operations import (  # noqa: F401  (fixtures and helpers shared with the other operation tests)
    cluster,
    conn,
    logs,
    run,
    steps,
    with_hosts,
    world,
)

LOST = "lab-b-06"


@pytest.fixture
def lost(session, six, conn):
    """The cluster with its sixth node lost: its machine is gone from Proxmox and Elasticsearch does not report it."""
    session.query(Vm).filter(Vm.vmid == 505).delete()
    session.query(EsNode).filter(EsNode.cluster_id == six.id, EsNode.name == LOST).delete()
    session.commit()
    with_hosts(session, conn)                                          # three online hosts, shared storage and a template
    return six


def es_without(cluster, *names, status="yellow"):
    es = FakeEs(DesiredState.model_validate(cluster.desired["state"]), status=status)
    es.hidden = set(names)
    return es


def rebuilding(session, world, cluster, *names, **request):
    params = plan_rebuild_nodes(session, cluster, RebuildNodes(nodes=list(names), **request), es_without(cluster, *names))
    world.create_changes = [(ADDR(n), "create") for n in names]
    world.apply_outcome = ApplyOutcome(True, None, [ADDR(n) for n in NAMES], {})
    return start_update(session, cluster_id=cluster.id, params=params, actor="admin")


def forgetting(session, world, cluster, *names):
    params = plan_forget_nodes(session, cluster, ForgetNodes(nodes=list(names), confirm_name=cluster.name),
                               es_without(cluster, *names))
    world.create_changes = []                                         # Terraform has nothing to do: the machine is gone
    world.apply_outcome = ApplyOutcome(True, None, [ADDR(n) for n in NAMES if n not in names], {})
    return start_update(session, cluster_id=cluster.id, params=params, actor="admin")


# -- rebuilding -----------------------------------------------------------------------------------------------------------

def test_a_rebuild_makes_the_machine_again_then_configures_and_starts_only_that_node(session, world, lost, seen):
    op = run(session, world, rebuilding(session, world, lost, LOST))
    assert op.state == "pending_approval"
    assert [n for n, _ in steps(session, op)] == ["render", "init", "plan", "approval", "apply", "configure"]
    assert op.plan_summary["adds"] == 1 and "rebuild 1 lost node (lab-b-06)" in op.plan_summary["configure"]
    assert [k for k, _ in seen] == []                                  # nothing is asked of the cluster before approval

    op = approve_and_run(session, world, op)
    assert op.state == "succeeded" and world.calls.count("apply") == 2
    assert seen == [("add_node", 2)]
    request = world.ansible_requests[-1]
    assert request.kind == "add_node" and request.new_nodes == [LOST] and request.rebuild is True
    assert len(request.state.nodes) == 6 and request.es_api_key and request.ca_key_pem
    session.refresh(lost)
    assert len(lost.desired["state"]["nodes"]) == 6 and lost.desired["vm_ids"][LOST] == 505   # the record is as it was
    assert "the rebuilt nodes joined and the cluster is not red" in logs(session, op)


def test_a_rebuild_on_another_host_records_the_new_host(session, world, lost):
    other = next(h for h in ("pve1", "pve2", "pve3") if h != lost.desired["placement"][LOST])
    op = approve_and_run(session, world, run(session, world, rebuilding(session, world, lost, LOST, pve_node=other)))
    assert op.state == "succeeded"
    session.refresh(lost)
    assert lost.desired["placement"][LOST] == other


def test_a_plan_that_creates_nothing_is_rejected_because_the_machine_is_still_there(session, world, lost, seen):
    op = rebuilding(session, world, lost, LOST)
    world.create_changes = []
    with pytest.raises(PlanRejected, match="does not create a machine for lab-b-06, so Terraform believes it exists"):
        run(session, world, op)
    assert seen == [] and world.calls.count("apply") == 1


def test_a_plan_that_would_delete_something_is_rejected(session, world, lost):
    op = rebuilding(session, world, lost, LOST)
    world.create_changes = [(ADDR(LOST), "create"), (ADDR("lab-b-05"), "delete")]
    with pytest.raises(PlanRejected, match="must only create the machines asked for.*lab-b-05"):
        run(session, world, op)


def test_a_failed_join_keeps_the_machine_and_a_retry_does_not_make_it_again(session, world, lost, seen):
    op = run(session, world, rebuilding(session, world, lost, LOST))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    world.fail_kinds = {"add_node": "The new nodes did not all join: lab-b-06"}
    with pytest.raises(tfop.ConfigureFailed, match="did not all join.*The new machines are kept"):
        run(session, world, op)
    assert world.calls.count("apply") == 2                              # the machine was made

    world.fail_kinds = {}
    world.create_changes = []                                           # Terraform now matches: nothing left to create
    operations.retry_operation(session, op.id)
    op = run(session, world, op)
    assert op.state == "succeeded" and world.calls.count("apply") == 2   # no second apply
    assert [k for k, _ in seen] == ["add_node", "add_node"]


def test_a_failed_apply_is_not_mistaken_for_a_finished_one_on_retry(session, world, lost):
    op = run(session, world, rebuilding(session, world, lost, LOST))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    world.apply_outcome = ApplyOutcome(False, "terraform apply failed: clone timed out", [ADDR(n) for n in NAMES[:5]])
    with pytest.raises(tfop.ApplyFailed):
        run(session, world, op)
    world.create_changes = []                                           # an empty plan after a FAILED apply is still refused
    operations.retry_operation(session, op.id)
    with pytest.raises(PlanRejected, match="does not create a machine for lab-b-06"):
        run(session, world, op)


def test_a_machine_that_is_not_ecms_blocks_the_rebuild(session, world, lost, conn):
    session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=505, name="someone-elses", status="running",
                   tf_managed=False))
    session.commit()
    with pytest.raises(OperationRefused, match="now belongs to a machine named someone-elses"):
        plan_rebuild_nodes(session, lost, RebuildNodes(nodes=[LOST]), es_without(lost, LOST))


# -- forgetting -----------------------------------------------------------------------------------------------------------

def test_a_forget_waits_for_approval_even_though_its_plan_has_nothing_to_do(session, world, lost, seen):
    op = run(session, world, forgetting(session, world, lost, LOST))
    assert op.state == "pending_approval" and op.plan_summary["has_changes"] is False
    assert [n for n, _ in steps(session, op)] == ["render", "init", "plan", "approval", "apply", "configure"]
    assert world.calls.count("apply") == 1 and seen == []              # an empty plan must not skip the approval

    op = approve_and_run(session, world, op)
    assert op.state == "succeeded"
    assert seen == [("converge", 2)]                                    # the remaining nodes are brought in line; no drain
    session.refresh(lost)
    assert [n["name"] for n in lost.desired["state"]["nodes"]] == NAMES[:5]
    assert LOST not in lost.desired["vm_ids"] and LOST not in lost.desired["addresses"]
    assert session.scalar(select(Vm).where(Vm.vmid == 505)) is None
    assert "lab-b-06 removed from the inventory" in logs(session, op)


def test_a_forget_plan_that_would_delete_a_machine_is_rejected_and_says_to_remove_it(session, world, lost):
    op = forgetting(session, world, lost, LOST)
    world.create_changes = [(ADDR(LOST), "delete")]
    with pytest.raises(PlanRejected, match="the machine of lab-b-06 still exists, so use Remove nodes"):
        run(session, world, op)
    assert world.calls.count("apply") == 1


def test_a_forgotten_machine_is_no_longer_ecms_and_a_stranger_at_its_vmid_blocks_the_forget(session, world, lost, conn):
    from app.provisioning.ownership import created_machines
    approve_and_run(session, world, run(session, world, forgetting(session, world, lost, LOST)))
    assert (conn.id, 505, LOST) not in created_machines(session)
    session.refresh(lost)
    params = {**lost.desired}
    params["change"] = {"kind": "forget_nodes", "removed": ["lab-b-05"],
                        "nodes": {"lab-b-05": {"vm_id": 504}}}
    row = session.scalar(select(Vm).where(Vm.vmid == 504))
    row.name, row.tf_managed = "someone-elses", False                    # a stranger now has lab-b-05's VM ID
    session.commit()
    with pytest.raises(OperationRefused, match="only touches machines ECM created.*504"):
        start_update(session, cluster_id=lost.id, params=params, actor="admin")


# -- the API and the cluster page's data -----------------------------------------------------------------------------------

H = {"x-ecm-csrf": "1"}


@pytest.fixture
def live(monkeypatch, lost):
    from app.provisioning import lifecycle
    es = es_without(lost, LOST)
    monkeypatch.setattr(lifecycle, "_read_cluster", lambda db, cluster, client=None: {
        "health": es.health(), "nodes": es.nodes()["nodes"], "stats": es.nodes_stats()["nodes"],
        "shards": es.shards_sized(), "settings": es.settings(), "master": es.master()})
    return es


def test_the_rebuild_endpoint_plans_and_nothing_changes_before_approval(logged_in, session, world, lost, live):
    from procrastinate import testing

    from app import jobs
    with jobs.queue.replace_connector(testing.InMemoryConnector()) as q:
        r = logged_in.post(f"/api/clusters/{lost.id}/rebuild-nodes", json={"nodes": [LOST]}, headers=H)
        assert r.status_code == 202 and len(q.connector.jobs) == 1
    detail = logged_in.get(f"/api/operations/{r.json()['operation_id']}").json()
    assert detail["change"]["kind"] == "rebuild_nodes" and detail["change"]["rebuilt"] == [LOST]
    assert detail["change"]["nodes"][LOST]["vm_id"] == 505 and detail["change"]["nodes"][LOST]["host"]


def test_the_forget_endpoint_needs_the_cluster_name_and_refuses_a_node_whose_machine_exists(
        logged_in, session, world, lost, live, conn):
    path = f"/api/clusters/{lost.id}/forget-nodes"
    r = logged_in.post(path, json={"nodes": [LOST], "confirm_name": "wrong"}, headers=H)
    assert r.status_code == 409 and "type the cluster name exactly" in r.json()["detail"]
    assert logged_in.post(path, json={"nodes": [LOST]}, headers=H).status_code == 422
    session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=505, name=LOST, status="running"))
    session.commit()
    r = logged_in.post(path, json={"nodes": [LOST], "confirm_name": "lab-b"}, headers=H)
    assert r.status_code == 409 and "exists in Proxmox" in r.json()["detail"]


def test_the_recovery_endpoints_refuse_a_bad_request_and_need_a_login(logged_in, client, session, world, lost, live):
    assert logged_in.post(f"/api/clusters/{lost.id}/rebuild-nodes", json={"nodes": []}, headers=H).status_code == 422
    assert logged_in.post(f"/api/clusters/{lost.id}/rebuild-nodes", json={"nodes": ["lab-b-99"]}, headers=H).status_code == 409
    assert logged_in.post("/api/clusters/nope/rebuild-nodes", json={"nodes": [LOST]}, headers=H).status_code == 404
    assert logged_in.post(f"/api/clusters/{lost.id}/rebuild-nodes", json={"nodes": [LOST]}).status_code in (400, 403)
    client.cookies.clear()
    assert client.post(f"/api/clusters/{lost.id}/rebuild-nodes", json={"nodes": [LOST]}, headers=H).status_code == 401


def test_the_cluster_page_data_says_which_nodes_have_a_machine_and_are_in_the_cluster(logged_in, session, world, lost):
    state = logged_in.get(f"/api/clusters/{lost.id}").json()["lifecycle"]["node_state"]
    assert state[LOST] == {"machine": False, "in_cluster": False, "vm_status": None}
    assert state["lab-b-05"] == {"machine": True, "in_cluster": True, "vm_status": "running"}
    assert AnsibleError                                                  # imported for the shared fixtures' sake
