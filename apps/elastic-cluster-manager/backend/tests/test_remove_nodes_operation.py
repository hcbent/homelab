"""Removing nodes as an operation: the phases and their order, what is drained before Terraform destroys anything, what a
failure leaves behind, how a retry resumes, and who counts as ECM's afterwards. Terraform and Ansible are the same fakes
the other operation tests use; the cluster's answers come from the fake Elasticsearch of the rules tests."""
# ruff: noqa: F811  (the fixtures are imported from the other operation tests and used by name)
import copy
from datetime import UTC

import pytest
from sqlalchemy import select

from app import operations
from app.configmgmt import AnsibleError, AnsibleOutcome
from app.desired import TopologyPreset, build_desired_state
from app.desired.models import DesiredState
from app.models import Cluster, EsNode, Operation, Vm
from app.provisioning import operation as tfop
from app.provisioning.lifecycle import RemoveNodes, plan_remove_nodes
from app.provisioning.operation import OperationRefused, PlanRejected, start_update
from app.provisioning.ownership import created_machines
from app.provisioning.runner import ApplyOutcome
from tests.test_remove_nodes import FakeEs
from tests.test_tf_operations import (  # noqa: F401  (fixtures and helpers shared with the other operation tests)
    ADDRS,
    PROFILE,
    FakeAnsible,
    cluster,
    conn,
    logs,
    reach_success,
    run,
    steps,
    world,
)

NAMES = [f"lab-b-0{i}" for i in range(1, 7)]
ADDR = 'module.node["{}"].proxmox_virtual_environment_vm.node'.format


@pytest.fixture
def six(session, world, cluster, conn):
    """A built cluster of six nodes: masters 01-03, data 04-05, coordinating 06. Its recorded state is the six."""
    reach_success(session, world, cluster, conn)
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-b", "9.4.3", data_nodes=2, coordinating_nodes=1)
    cluster.desired = {
        "state": state.model_dump(mode="json"),
        "placement": {n: f"pve{i % 3 + 1}" for i, n in enumerate(NAMES)},
        "addresses": {n: f"192.0.2.{110 + i}" for i, n in enumerate(NAMES)},
        "vm_ids": {n: 500 + i for i, n in enumerate(NAMES)},
        "profile": PROFILE.model_dump(mode="json"), "template": {"node_name": "pve1", "vm_id": 8000},
        "proxmox_connection_id": conn.id, "node_counter": 6}
    cluster.health_status = "green"
    for i, n in enumerate(NAMES):
        session.add(Vm(connection_id=conn.id, pve_node=f"pve{i % 3 + 1}", vmid=500 + i, name=n, status="running",
                       tf_managed=True))
        session.add(EsNode(cluster_id=cluster.id, es_node_id=f"id-{n}", name=n))
    session.commit()
    return cluster


def removing(session, world, cluster, *names):
    """A remove-nodes update, planned and waiting for approval."""
    state = DesiredState.model_validate(cluster.desired["state"])
    params = plan_remove_nodes(session, cluster, RemoveNodes(nodes=list(names), confirm_name=cluster.name),
                               FakeEs(state))
    world.create_changes = [(ADDR(n), "delete") for n in names]
    world.apply_outcome = ApplyOutcome(True, None, [ADDR(n) for n in NAMES if n not in names], {})
    return start_update(session, cluster_id=cluster.id, params=params, actor="admin")


def approve_and_run(session, world, op):
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    return run(session, world, op)


@pytest.fixture
def seen(monkeypatch):
    """What Ansible was asked, in order, with how many Terraform applies had happened by then."""
    calls: list[tuple[str, int]] = []
    real = FakeAnsible.run

    def spy(self, request):
        calls.append((request.kind, self.w.calls.count("apply")))
        if request.kind in self.w.fail_kinds:
            raise AnsibleError(self.w.fail_kinds[request.kind])
        return real(self, request)
    monkeypatch.setattr(FakeAnsible, "run", spy)
    return calls


@pytest.fixture(autouse=True)
def fail_kinds(world):
    world.fail_kinds = {}


# -- the sequence -------------------------------------------------------------------------------------------------------

def test_the_removal_waits_for_approval_then_drains_before_terraform_destroys_and_checks_afterwards(
        session, world, six, seen):
    op = run(session, world, removing(session, world, six, "lab-b-05", "lab-b-06"))
    assert op.state == "pending_approval"
    assert [n for n, _ in steps(session, op)] == ["render", "init", "plan", "approval", "drain", "apply", "configure"]
    assert op.plan_summary["deletes"] == 2 and op.plan_summary["adds"] == 0
    assert "remove 2 nodes (lab-b-05, lab-b-06)" in op.plan_summary["configure"]
    assert [kind for kind, _ in seen] == ["create"][:0]                  # nothing was asked of the cluster before approval

    op = approve_and_run(session, world, op)
    assert op.state == "succeeded"
    # drained while one apply (the create) had run; no converge, because neither node was master-eligible (see below)
    assert seen == [("remove_drain", 1), ("remove_check", 2)]
    drain = world.ansible_requests[-2]
    assert drain.kind == "remove_drain" and drain.removing == ["lab-b-05", "lab-b-06"]
    assert [n.name for n in drain.state.nodes] == NAMES[:4] and set(drain.addresses) == set(NAMES[:4])
    assert drain.es_api_key and drain.es_ca_pem
    assert [r.kind for r in world.ansible_requests[-2:]] == ["remove_drain", "remove_check"]
    assert "no remaining node's configuration refers to the nodes that left" in logs(session, op)
    assert "the cluster is green with the nodes that remain" in logs(session, op)


def test_a_finished_removal_is_the_clusters_new_state_and_the_machines_leave_the_inventory(session, world, six, conn):
    op = approve_and_run(session, world, run(session, world, removing(session, world, six, "lab-b-05", "lab-b-06")))
    session.refresh(six)
    assert [n["name"] for n in six.desired["state"]["nodes"]] == NAMES[:4]
    assert not {"lab-b-05", "lab-b-06"} & (set(six.desired["vm_ids"]) | set(six.desired["addresses"]) | set(six.desired["placement"]))
    assert "change" not in six.desired and six.desired["node_counter"] == 6
    left = {v.name for v in session.scalars(select(Vm).where(Vm.connection_id == conn.id))}
    assert left == set(NAMES[:4])
    assert {n.name for n in session.scalars(select(EsNode).where(EsNode.cluster_id == six.id))} == set(NAMES[:4])
    assert "removed from the inventory (2 machines)" in logs(session, op)


def test_the_removed_machines_stop_being_ecms_and_a_removed_number_is_not_handed_out_again(session, world, six, conn):
    assert (conn.id, 504, "lab-b-05") not in created_machines(session)       # not recorded by the create (it made three)
    op = approve_and_run(session, world, run(session, world, removing(session, world, six, "lab-b-06")))
    assert (conn.id, 505, "lab-b-06") not in created_machines(session)
    assert op.params["node_counter"] == 6


def test_a_machine_that_is_not_ecms_blocks_the_removal_of_that_node(session, world, six, conn):
    row = session.scalar(select(Vm).where(Vm.vmid == 505))
    row.name, row.tf_managed = "someone-elses", False                       # a stranger now has the VMID
    session.commit()
    state = DesiredState.model_validate(six.desired["state"])
    params = plan_remove_nodes(session, six, RemoveNodes(nodes=["lab-b-06"], confirm_name="lab-b"), FakeEs(state))
    with pytest.raises(OperationRefused, match="only touches machines ECM created.*505 \\(someone-elses\\)"):
        start_update(session, cluster_id=six.id, params=params, actor="admin")


# -- the plan -----------------------------------------------------------------------------------------------------------

def test_a_plan_that_would_delete_a_node_that_was_not_named_is_rejected_before_any_approval(session, world, six, seen):
    op = removing(session, world, six, "lab-b-06")
    world.create_changes = [(ADDR("lab-b-06"), "delete"), (ADDR("lab-b-05"), "delete")]
    with pytest.raises(PlanRejected, match="must only delete the machines asked for.*lab-b-05"):
        run(session, world, op)
    assert seen == [] and op.state == "failed"


def test_a_plan_with_nothing_to_delete_is_rejected_because_approving_it_would_remove_nothing(session, world, six):
    op = removing(session, world, six, "lab-b-06")
    world.create_changes = []
    with pytest.raises(PlanRejected, match="does not delete lab-b-06"):
        run(session, world, op)


# -- failures and retries -----------------------------------------------------------------------------------------------

def test_a_drain_that_fails_destroys_nothing_keeps_the_record_and_a_retry_needs_a_new_approval(
        session, world, six, seen):
    op = run(session, world, removing(session, world, six, "lab-b-05", "lab-b-06"))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    world.ansible_outcome = AnsibleOutcome(False, "ansible-playbook failed: Elasticsearch could not empty every node: "
                                                  "lab-b-05 is STALLED (no node can take the shard logs[0]).")
    with pytest.raises(tfop.DrainFailed, match="STALLED.*Nothing was destroyed; Retry plans the removal again"):
        run(session, world, op)
    assert world.calls.count("apply") == 1 and op.state == "failed"             # only the create ever applied
    assert [n for n, s in steps(session, op) if s == "failed"] == ["drain"]
    session.refresh(six)
    assert len(six.desired["state"]["nodes"]) == 6 and "lab-b-05" in six.desired["vm_ids"]

    world.ansible_outcome = AnsibleOutcome(True)
    operations.retry_operation(session, op.id)
    op = run(session, world, op)
    assert op.state == "pending_approval" and op.approved_digest is None        # planned again, awaiting a new approval
    assert approve_and_run(session, world, op).state == "succeeded"


def test_an_error_before_the_drain_could_start_is_also_nothing_destroyed(session, world, six, seen):
    op = run(session, world, removing(session, world, six, "lab-b-06"))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    world.fail_kinds = {"remove_drain": "removing nodes needs the ECM API key"}
    with pytest.raises(tfop.DrainFailed, match="needs the ECM API key. Nothing was destroyed"):
        run(session, world, op)
    assert world.calls.count("apply") == 1


def test_a_cluster_with_no_api_key_is_not_drained_and_ansible_is_not_asked(session, world, six, seen):
    from app.models import Credential
    op = run(session, world, removing(session, world, six, "lab-b-06"))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    for cred in session.scalars(select(Credential).where(Credential.kind == "es_api_key")):
        session.delete(cred)
    session.commit()
    with pytest.raises(tfop.DrainFailed, match="no API key or CA certificate.*Nothing was destroyed"):
        run(session, world, op)
    assert seen == [] and world.calls.count("apply") == 1


def test_a_failed_check_after_the_machines_are_gone_keeps_the_new_state_and_a_retry_does_not_apply_again(
        session, world, six, seen):
    op = run(session, world, removing(session, world, six, "lab-b-05", "lab-b-06"))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    world.fail_kinds = {"remove_check": "the cluster was not green"}
    with pytest.raises(tfop.ConfigureFailed, match="not green. The machines are gone; retry runs the check again"):
        run(session, world, op)
    session.refresh(six)
    assert len(six.desired["state"]["nodes"]) == 4 and world.calls.count("apply") == 2   # the machines are gone: that is the state

    world.fail_kinds = {}
    world.create_changes = []                                           # Terraform now matches; there is nothing left to delete
    operations.retry_operation(session, op.id)
    op = run(session, world, op)
    assert op.state == "succeeded" and world.calls.count("apply") == 2   # no second apply
    kinds = [k for k, _ in seen]
    assert kinds == ["remove_drain", "remove_check", "remove_drain", "remove_check"]
    assert "nothing to apply" in logs(session, op)


def test_a_failed_apply_keeps_the_nodes_in_the_record_and_a_retry_plans_again(session, world, six, seen):
    op = run(session, world, removing(session, world, six, "lab-b-06"))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    world.apply_outcome = ApplyOutcome(False, "terraform apply failed: timed out", [ADDR(n) for n in NAMES])
    with pytest.raises(tfop.ApplyFailed):
        run(session, world, op)
    session.refresh(six)
    assert len(six.desired["state"]["nodes"]) == 6                      # nothing was destroyed, so nothing is forgotten
    assert session.scalar(select(Vm).where(Vm.vmid == 505)) is not None


def test_the_removal_is_refused_at_plan_time_if_the_cluster_is_busy_with_another_operation(session, world, six):
    removing(session, world, six, "lab-b-06")                           # the first one is running
    with pytest.raises(operations.OperationConflict):
        removing(session, world, six, "lab-b-05")


def test_other_changes_keep_their_phases(session, world, six):
    from app.provisioning.lifecycle import ExpandDisk, plan_expand_disk
    params = plan_expand_disk(session, six, ExpandDisk(data_disk_gb=500))
    op = start_update(session, cluster_id=six.id, params=params, actor="admin")
    assert [n for n, _ in steps(session, op)] == ["render", "init", "plan", "approval", "apply", "configure"]
    assert session.get(Cluster, six.id) is not None


# -- the API ------------------------------------------------------------------------------------------------------------

H = {"x-ecm-csrf": "1"}


@pytest.fixture
def live(monkeypatch, six):
    """The cluster answers the plan's read with the fake Elasticsearch."""
    from app.provisioning import lifecycle
    es = FakeEs(DesiredState.model_validate(six.desired["state"]))
    monkeypatch.setattr(lifecycle, "_read_cluster", lambda db, cluster, client=None: {
        "health": es.health(), "nodes": es.nodes()["nodes"], "stats": es.nodes_stats()["nodes"],
        "shards": es.shards_sized(), "settings": es.settings(), "master": es.master()})
    return es


def test_the_remove_nodes_endpoint_plans_and_shows_where_each_node_is_and_what_it_holds(
        logged_in, session, world, six, live):
    from procrastinate import testing

    from app import jobs
    with jobs.queue.replace_connector(testing.InMemoryConnector()) as q:
        r = logged_in.post(f"/api/clusters/{six.id}/remove-nodes",
                           json={"nodes": ["lab-b-05", "lab-b-06"], "confirm_name": "lab-b"}, headers=H)
        assert r.status_code == 202 and len(q.connector.jobs) == 1
    detail = logged_in.get(f"/api/operations/{r.json()['operation_id']}").json()
    assert detail["change"]["kind"] == "remove_nodes" and sorted(detail["change"]["nodes"]) == ["lab-b-05", "lab-b-06"]
    assert all(n["host"] and n["address"] and n["vm_id"] for n in detail["change"]["nodes"].values())
    session.refresh(six)
    assert len(six.desired["state"]["nodes"]) == 6                          # nothing changes before approval


@pytest.mark.parametrize("body,status,text", [
    ({"nodes": ["lab-b-06"], "confirm_name": "wrong"}, 409, "type the cluster name exactly"),
    ({"nodes": ["lab-b-99"], "confirm_name": "lab-b"}, 409, "no node named lab-b-99"),
    ({"nodes": ["lab-b-01"], "confirm_name": "lab-b"}, 409, "only 2 master-eligible nodes would remain"),
    ({"nodes": [], "confirm_name": "lab-b"}, 422, None),
    ({"nodes": ["a", "a"], "confirm_name": "lab-b"}, 422, None),
    ({"nodes": ["lab-b-06"]}, 422, None),
    ({"nodes": ["lab-b-06"], "confirm_name": "lab-b", "extra": 1}, 422, None),
])
def test_the_remove_nodes_endpoint_refuses_a_bad_request_with_the_reason(
        logged_in, session, world, six, live, body, status, text):
    r = logged_in.post(f"/api/clusters/{six.id}/remove-nodes", json=body, headers=H)
    assert r.status_code == status
    if text:
        assert text in r.json()["detail"]
    assert session.scalars(select(Operation).where(Operation.kind == "tf.update")).all() == []


def test_the_remove_nodes_endpoint_needs_a_login_the_csrf_header_and_a_known_cluster(
        logged_in, client, session, world, six, live):
    path, body = f"/api/clusters/{six.id}/remove-nodes", {"nodes": ["lab-b-06"], "confirm_name": "lab-b"}
    assert logged_in.post("/api/clusters/nope/remove-nodes", json=body, headers=H).status_code == 404
    assert logged_in.post(path, json=body).status_code in (400, 403)
    client.cookies.clear()
    assert client.post(path, json=body, headers=H).status_code == 401


def test_the_cluster_page_data_lists_each_nodes_roles_and_host_for_the_panel(logged_in, session, world, six):
    data = logged_in.get(f"/api/clusters/{six.id}").json()["lifecycle"]
    roles = data["node_roles"]
    assert sorted(roles) == NAMES and roles["lab-b-01"]["master_eligible"] and not roles["lab-b-01"]["holds_data"]
    assert roles["lab-b-04"]["holds_data"] and not roles["lab-b-04"]["master_eligible"]
    assert roles["lab-b-06"]["roles"] == [] and roles["lab-b-06"]["host"] == "pve3"


def edit_params(session, op, change):
    """Change an operation's parameters and save them: a JSON column is only saved when it is assigned, not when it is edited in place."""
    params = copy.deepcopy(op.params)
    change(params)
    op.params = params
    session.commit()


# -- the converge after a removal runs only when a master-eligible node left ----------------------------------------------------------

def test_taking_out_a_master_eligible_node_does_run_the_converge_since_it_leaves_the_seed_lists(session, world, six, seen):
    """`discovery.seed_hosts` names the master-eligible nodes, so only their leaving changes what the others' configuration says. The rules
    allow removing a master only from a cluster with more than three, so the flag is set on the plan here, as a plan for such a cluster has it."""
    op = removing(session, world, six, "lab-b-05", "lab-b-06")
    edit_params(session, op, lambda p: p["change"]["nodes"]["lab-b-05"].__setitem__("master_eligible", True))
    assert "then the nodes that remain are brought in line" not in op.params["change"]["describe"]      # the flag was edited, the text was not
    op = approve_and_run(session, world, run(session, world, op))
    assert op.state == "succeeded"
    assert [k for k, _ in seen] == ["remove_drain", "converge", "remove_check"]
    assert "a master-eligible node left the seed lists, so the remaining nodes are brought in line" in logs(session, op)


def test_a_plan_made_before_the_flag_existed_runs_the_converge_to_be_safe(session, world, six, seen):
    op = removing(session, world, six, "lab-b-06")
    edit_params(session, op, lambda p: [info.pop("master_eligible") for info in p["change"]["nodes"].values()])
    approve_and_run(session, world, run(session, world, op))
    assert [k for k, _ in seen] == ["remove_drain", "converge", "remove_check"]


def test_the_plan_says_whether_the_remaining_nodes_will_be_reconfigured(session, world, six):
    quiet = removing(session, world, six, "lab-b-06").params["change"]
    assert "brought in line" not in quiet["describe"] and quiet["nodes"]["lab-b-06"]["master_eligible"] is False
    assert quiet["describe"].endswith("then ECM checks the cluster is green with the nodes that remain")


def test_a_converge_that_changed_a_node_without_restarting_it_leaves_that_node_waiting_for_a_restart(session, world, six, seen):
    op = removing(session, world, six, "lab-b-05", "lab-b-06")
    edit_params(session, op, lambda p: p["change"]["nodes"]["lab-b-05"].__setitem__("master_eligible", True))   # so the converge runs
    world.ansible_outcome = AnsibleOutcome(True, pending_restart=["lab-b-01", "lab-b-02"])
    op = approve_and_run(session, world, run(session, world, op))
    assert op.state == "succeeded"
    session.refresh(six)
    assert sorted(six.pending_restart) == ["lab-b-01", "lab-b-02"] and all(six.pending_restart.values())
    assert "lab-b-01, lab-b-02 are now waiting for a restart to apply the change" in logs(session, op)


def test_a_converge_that_fails_after_writing_files_still_records_what_it_changed(session, world, six, seen):
    from app.provisioning.lifecycle import ExpandDisk, plan_expand_disk
    params = plan_expand_disk(session, six, ExpandDisk(data_disk_gb=500))        # an update whose first Ansible call is the converge
    op = start_update(session, cluster_id=six.id, params=params, actor="admin")
    world.create_changes = [(ADDR("lab-b-04"), "update"), (ADDR("lab-b-05"), "update")]
    world.apply_outcome = ApplyOutcome(True, None, [ADDR(n) for n in NAMES], {})
    op = run(session, world, op)
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    world.ansible_outcome = AnsibleOutcome(False, "ansible-playbook failed: a later host failed", pending_restart=["lab-b-03"])
    with pytest.raises(tfop.ConfigureFailed):
        run(session, world, op)
    session.refresh(six)
    assert list(six.pending_restart) == ["lab-b-03"]                             # the file was written on it before the run failed


def test_removing_a_node_forgets_that_it_was_waiting(session, world, six):
    from datetime import datetime
    six.pending_restart = {"lab-b-06": datetime.now(UTC).isoformat(), "lab-b-01": datetime.now(UTC).isoformat()}
    session.commit()
    approve_and_run(session, world, run(session, world, removing(session, world, six, "lab-b-06")))
    session.refresh(six)
    assert list(six.pending_restart) == ["lab-b-01"]
