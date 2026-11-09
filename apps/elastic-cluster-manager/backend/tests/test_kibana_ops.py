"""Kibana, slice 6b (docs/DESIGN_KIBANA.md): the sign-in (a new password for the elastic user, kept encrypted, shown on request with an audit
event), restarting Kibana, and removing it. The operations run against the fake Terraform and Ansible the other operation tests use."""
# ruff: noqa: F811  (the fixtures are imported from the other operation tests and used by name)
import copy
import json

import pytest
from sqlalchemy import select

from app import crypto, operations
from app.configmgmt import AnsibleOutcome
from app.desired.kibana import kibana_of
from app.models import AuditEvent, Credential, Operation, Vm
from app.provisioning import operation as tfop
from app.provisioning.kibana_ops import KibanaOpFailed, login_for_reveal
from app.provisioning.lifecycle import (
    RemoveKibana,
    plan_kibana_login,
    plan_remove_kibana,
    plan_restart_kibana,
)
from app.provisioning.operation import (
    ConfigureFailed,
    OperationRefused,
    PlanRejected,
    cluster_lifecycle,
    start_kibana_op,
    start_update,
)
from app.provisioning.ownership import created_machines
from app.provisioning.runner import ApplyOutcome
from tests.test_add_kibana import (  # noqa: F401  (fixtures and helpers shared with the Kibana tests)
    ADDRS,
    KB,
    KB_ADDR,
    TOKEN,
    H,
    api,
    approve_and_run,
    credential,
    es,
    lab_b,
    planned,
    started,
)
from tests.test_tf_operations import FakeAnsible, cluster, conn, logs, run, steps, world  # noqa: F401

PASSWORD = "Zq9-the-elastic-password-ECM-set-0001"
OLD_PASSWORD = "an-older-elastic-password-0000001"


@pytest.fixture
def kb(session, world, lab_b):
    """A built cluster that has had Kibana added (the add ran through the fakes), with the fakes ready for what comes next."""
    approve_and_run(session, world, run(session, world, started(session, lab_b)))
    session.refresh(lab_b)
    world.ansible_requests.clear()
    world.calls.clear()
    world.ansible_outcome = AnsibleOutcome(ok=True)
    return lab_b


def kibana_op(session, params):
    return start_kibana_op(session, cluster_id=params_cluster(session), params=params, actor="admin")


def params_cluster(session):
    return session.scalar(select(Operation.cluster_id).where(Operation.kind == "tf.create"))


def login_state(session, cluster):
    return json.loads(credential(session, cluster, 2) or "{}")


@pytest.fixture
def seen(monkeypatch, session, kb):
    """What the sign-in held at the moment Ansible was asked, in order: the proof that the new password is stored before the cluster has it."""
    calls: list[dict] = []
    real = FakeAnsible.run

    def spy(self, request):
        calls.append({"kind": request.kind, "stored": login_state(session, kb), "pass": request.kibana_login_pass})
        return real(self, request)
    monkeypatch.setattr(FakeAnsible, "run", spy)
    return calls


# -- the sign-in: planning -----------------------------------------------------------------------------------------------------------

def test_a_cluster_with_no_kibana_has_nothing_to_sign_in_to_restart_or_remove(session, lab_b):
    with pytest.raises(OperationRefused, match="no Kibana"):
        plan_kibana_login(session, lab_b)
    with pytest.raises(OperationRefused, match="no Kibana"):
        plan_restart_kibana(session, lab_b)
    with pytest.raises(OperationRefused, match="no Kibana"):
        plan_remove_kibana(session, lab_b, RemoveKibana(confirm_name=lab_b.name))


def test_the_sign_in_plan_warns_that_the_old_password_stops_working_and_that_ecms_key_is_not_affected(session, kb):
    change = plan_kibana_login(session, kb)["change"]
    assert change["kind"] == "reset_login" and list(change["kibana"]) == [KB]
    assert any("can no longer do so" in w and "API key" in w and "not affected" in w for w in change["warnings"])
    assert not any("replaces" in w for w in change["warnings"])                      # nothing is held yet
    assert "each time it is shown is recorded" in change["describe"]


def test_a_sign_in_that_is_already_held_is_said_to_be_replaced(session, kb):
    session.add(Credential(kind="es_kibana_login", name=tfop.kibana_credential_names(kb.id)[2],
                           ciphertext=crypto.encrypt(json.dumps({"username": "elastic", "current": OLD_PASSWORD, "pending": None}))))
    session.commit()
    assert any("this replaces it" in w for w in plan_kibana_login(session, kb)["change"]["warnings"])


# -- the sign-in: the operation -------------------------------------------------------------------------------------------------------

def test_the_reset_waits_for_approval_then_stores_the_password_as_pending_before_the_cluster_has_it_and_makes_it_current_when_proved(
        session, world, kb, seen):
    op = run(session, world, kibana_op(session, plan_kibana_login(session, kb)))
    assert op.state == "pending_approval" and seen == []                              # nothing was asked of the cluster before approval
    assert [n for n, _ in steps(session, op)] == ["plan", "approval", "kibana"]

    op = approve_and_run(session, world, op)
    assert op.state == "succeeded"
    (call,) = seen
    assert call["kind"] == "kibana_login" and len(call["pass"]) >= 20
    assert call["stored"]["pending"] == call["pass"] and call["stored"]["current"] is None   # stored first, and not yet the one in use
    state = login_state(session, kb)
    assert state["current"] == call["pass"] and state["pending"] is None and state["username"] == "elastic" and state["reset_at"]
    assert login_for_reveal(session, kb)["password"] == call["pass"]


def test_the_request_carries_the_machine_the_api_key_and_the_ca_and_no_other_secret(session, world, kb):
    approve_and_run(session, world, run(session, world, kibana_op(session, plan_kibana_login(session, kb))))
    (request,) = world.ansible_requests
    assert [k.name for k in request.kibana] == [KB] and request.es_api_key and request.es_ca_pem
    assert request.kibana_keys is None and request.kibana_token is None and request.ca_key_pem is None


def test_the_password_never_reaches_a_log_the_plan_the_parameters_or_the_audit_trail(session, world, kb, seen):
    op = approve_and_run(session, world, run(session, world, kibana_op(session, plan_kibana_login(session, kb))))
    password = seen[0]["pass"]
    everything = json.dumps([logs(session, op), op.plan_summary, op.params, op.result,
                             [e.details for e in session.scalars(select(AuditEvent))]], default=str)
    assert password not in everything
    assert all(password.encode() not in c.ciphertext for c in session.scalars(select(Credential)))     # and it is not stored in the clear


def test_a_failed_reset_keeps_the_password_that_was_current_and_the_new_one_pending_and_a_retry_sets_the_same_one(session, world, kb, seen):
    session.add(Credential(kind="es_kibana_login", name=tfop.kibana_credential_names(kb.id)[2],
                           ciphertext=crypto.encrypt(json.dumps({"username": "elastic", "current": OLD_PASSWORD, "pending": None,
                                                                 "reset_at": "2026-11-01T00:00:00+00:00"}))))
    session.commit()
    world.ansible_outcome = AnsibleOutcome(ok=False, error="Elasticsearch answered HTTP 403 when asked to set the elastic user's password")
    op = run(session, world, kibana_op(session, plan_kibana_login(session, kb)))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(KibanaOpFailed, match="HTTP 403.*Retry sets the same password again"):
        run(session, world, op)
    state = login_state(session, kb)
    assert state["current"] == OLD_PASSWORD and state["pending"] == seen[0]["pass"]      # still signed in as before; the new one is kept
    assert login_for_reveal(session, kb)["password"] == OLD_PASSWORD                    # and a pending password is never shown

    world.ansible_outcome = AnsibleOutcome(ok=True)
    operations.retry_operation(session, op.id)
    op = approve_and_run(session, world, run(session, world, op))
    assert op.state == "succeeded" and seen[1]["pass"] == seen[0]["pass"]               # the same password: the cluster may already have it
    assert login_state(session, kb)["current"] == seen[0]["pass"]


def test_a_first_reset_that_fails_leaves_nothing_to_show(session, world, kb):
    world.ansible_error = "ansible-playbook was not found"
    op = run(session, world, kibana_op(session, plan_kibana_login(session, kb)))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(KibanaOpFailed, match="ansible-playbook was not found"):
        run(session, world, op)
    assert login_for_reveal(session, kb) is None
    assert cluster_lifecycle(session, kb)["kibana"]["login"]["set"] is False


def test_the_operation_needs_the_api_key_and_the_ca_and_changes_nothing_without_them(session, world, kb):
    op = run(session, world, kibana_op(session, plan_kibana_login(session, kb)))
    for row in session.scalars(select(Credential).where(Credential.kind == "es_api_key")):
        session.delete(row)
    session.commit()
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(KibanaOpFailed, match="no API key or CA certificate.*Nothing was changed"):
        run(session, world, op)
    assert world.ansible_requests == []


def test_a_different_plan_cannot_ride_on_an_approval(session, world, kb):
    op = run(session, world, kibana_op(session, plan_kibana_login(session, kb)))
    digest = op.plan_digest
    op.params = {**op.params, "change": {**op.params["change"], "kind": "restart_kibana"}}        # the plan is changed after it was shown
    session.commit()
    operations.approve_operation(session, op.id, digest, "admin")
    from app.provisioning.operation import ApplyRefused
    with pytest.raises(ApplyRefused):
        run(session, world, op)
    assert world.ansible_requests == []


def test_a_kibana_machine_that_is_not_ecms_blocks_the_operation(session, world, kb, conn):
    vmid = kibana_of(kb.desired)[0].vm_id
    session.add(Vm(connection_id=kb.desired["proxmox_connection_id"], pve_node="pve1", vmid=vmid, name="someone-elses",
                   status="running", tf_managed=False))
    session.commit()
    with pytest.raises(OperationRefused, match="only touches machines ECM created"):
        kibana_op(session, plan_kibana_login(session, kb))


# -- the panel never carries the password -----------------------------------------------------------------------------------------------

def test_the_panel_says_whether_a_sign_in_is_set_and_never_carries_it(session, world, kb, seen):
    assert cluster_lifecycle(session, kb)["kibana"]["login"] == {"set": False, "reset_at": None, "last": None}
    op = approve_and_run(session, world, run(session, world, kibana_op(session, plan_kibana_login(session, kb))))
    panel = cluster_lifecycle(session, kb)["kibana"]
    assert panel["login"]["set"] is True and panel["login"]["reset_at"] and panel["login"]["last"]["operation_id"] == op.id
    assert panel["login"]["last"]["state"] == "succeeded"
    assert seen[0]["pass"] not in json.dumps(cluster_lifecycle(session, kb))


# -- the reveal endpoint ----------------------------------------------------------------------------------------------------------------------

def test_the_reveal_returns_the_username_and_password_and_records_every_view(api, session, world, kb, seen):
    approve_and_run(session, world, run(session, world, kibana_op(session, plan_kibana_login(session, kb))))
    first = api.post(f"/api/clusters/{kb.id}/kibana-login/reveal", headers=H)
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    assert first.json()["username"] == "elastic" and first.json()["password"] == seen[0]["pass"]
    assert api.post(f"/api/clusters/{kb.id}/kibana-login/reveal", headers=H).status_code == 200
    views = [e for e in session.scalars(select(AuditEvent)) if e.action == "kibana.login.reveal"]
    assert len(views) == 2 and {e.actor for e in views} == {"admin"} and views[0].target_id == kb.id
    assert all(seen[0]["pass"] not in json.dumps(e.details) for e in views)                 # the audit trail says who, never what


def test_there_is_nothing_to_reveal_before_a_sign_in_is_set_and_a_view_that_shows_nothing_is_not_recorded(api, session, kb):
    r = api.post(f"/api/clusters/{kb.id}/kibana-login/reveal", headers=H)
    assert r.status_code == 409 and "Create sign-in" in r.json()["detail"]
    assert [e for e in session.scalars(select(AuditEvent)) if e.action == "kibana.login.reveal"] == []


def test_the_reveal_needs_a_session_the_csrf_header_and_a_cluster(api, session, kb):
    from fastapi.testclient import TestClient

    from app.main import app
    assert api.post(f"/api/clusters/{kb.id}/kibana-login/reveal").status_code == 403
    assert api.post("/api/clusters/nope/kibana-login/reveal", headers=H).status_code == 404
    with TestClient(app) as anonymous:
        assert anonymous.post(f"/api/clusters/{kb.id}/kibana-login/reveal", headers=H).status_code == 401


def test_the_plan_endpoints_for_the_sign_in_and_the_restart_enqueue_the_job(api, session, kb):
    for path, kind in (("kibana-login", "reset_login"), ("restart-kibana", "restart_kibana")):
        r = api.post(f"/api/clusters/{kb.id}/{path}", headers=H)
        assert r.status_code == 202 and r.json()["change"]["kind"] == kind, r.text
        op = session.get(Operation, r.json()["operation_id"])
        assert op.kind == "es.kibana"
        op.state = "cancelled"                                                                 # free the cluster for the next plan
        session.commit()


# -- restarting --------------------------------------------------------------------------------------------------------------------------------

def test_the_restart_plan_shows_the_addresses_before_and_after_and_says_when_nothing_changed(session, kb):
    params = plan_restart_kibana(session, kb)
    info = params["change"]["kibana"][KB]
    assert info["es_hosts_before"] == kibana_of(kb.desired)[0].es_hosts and info["es_hosts_after"] == info["es_hosts_before"]
    assert any("already uses these nodes" in w for w in params["change"]["warnings"])
    assert "briefly disconnected" in params["change"]["describe"]


def test_the_panel_says_kibana_is_out_of_date_when_the_nodes_it_was_given_are_not_the_clusters_now(session, world, kb):
    assert cluster_lifecycle(session, kb)["kibana"]["machines"][0]["hosts_out_of_date"] is False
    desired = copy.deepcopy(kb.desired)
    desired["kibana"][0]["es_hosts"] = ["https://192.0.2.99:9200"]                           # a node that has since gone
    kb.desired = desired
    session.commit()
    assert cluster_lifecycle(session, kb)["kibana"]["machines"][0]["hosts_out_of_date"] is True

    op = approve_and_run(session, world, run(session, world, kibana_op(session, plan_restart_kibana(session, kb))))
    assert op.state == "succeeded"
    session.refresh(kb)
    assert kibana_of(kb.desired)[0].es_hosts == op.params["change"]["kibana"][KB]["es_hosts_after"]
    assert cluster_lifecycle(session, kb)["kibana"]["machines"][0]["hosts_out_of_date"] is False


def test_a_kibana_recorded_before_the_list_was_kept_is_not_reported_out_of_date(session, kb):
    desired = copy.deepcopy(kb.desired)
    desired["kibana"][0]["es_hosts"] = []
    kb.desired = desired
    session.commit()
    assert cluster_lifecycle(session, kb)["kibana"]["machines"][0]["hosts_out_of_date"] is False


def test_the_restart_asks_only_for_the_machine_and_touches_no_elasticsearch_node(session, world, kb):
    approve_and_run(session, world, run(session, world, kibana_op(session, plan_restart_kibana(session, kb))))
    (request,) = world.ansible_requests
    assert request.kind == "restart_kibana" and [k.name for k in request.kibana] == [KB]
    assert request.kibana_login_pass is None and request.kibana_keys is None and "terraform" not in " ".join(world.calls)
    assert world.calls == []                                                                  # Terraform was not involved at all


def test_a_failed_restart_keeps_the_recorded_list_and_a_retry_runs_it_again(session, world, kb):
    before = kibana_of(kb.desired)[0].es_hosts
    desired = copy.deepcopy(kb.desired)
    desired["kibana"][0]["es_hosts"] = ["https://192.0.2.99:9200"]
    kb.desired = desired
    session.commit()
    world.ansible_outcome = AnsibleOutcome(ok=False, error="Kibana did not become available: lab-b-kb-01 is degraded")
    op = run(session, world, kibana_op(session, plan_restart_kibana(session, kb)))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(KibanaOpFailed, match="degraded.*retry rewrites it and restarts again"):
        run(session, world, op)
    session.refresh(kb)
    assert kibana_of(kb.desired)[0].es_hosts == ["https://192.0.2.99:9200"]                  # not claimed to be applied

    world.ansible_outcome = AnsibleOutcome(ok=True)
    operations.retry_operation(session, op.id)
    assert approve_and_run(session, world, run(session, world, op)).state == "succeeded"
    session.refresh(kb)
    assert kibana_of(kb.desired)[0].es_hosts == before


# -- removing -----------------------------------------------------------------------------------------------------------------------------------

def removing(session, world, kb, confirm=None):
    params = plan_remove_kibana(session, kb, RemoveKibana(confirm_name=confirm or kb.name))
    world.create_changes = [(KB_ADDR, "delete")]
    world.apply_outcome = ApplyOutcome(True, None, list(ADDRS), {})
    return start_update(session, cluster_id=kb.id, params=params, actor="admin")


def test_removing_needs_the_cluster_name_typed_and_changes_the_plan_by_taking_kibana_out_of_the_parameters(session, kb):
    with pytest.raises(OperationRefused, match="type the cluster name exactly"):
        plan_remove_kibana(session, kb, RemoveKibana(confirm_name="nope"))
    params = plan_remove_kibana(session, kb, RemoveKibana(confirm_name=kb.name))
    assert params["kibana"] == [] and len(kb.desired["kibana"]) == 1                          # the record is not touched
    change = params["change"]
    assert change["kind"] == "remove_kibana" and change["kibana_removed"] == [KB] and change["kibana"][KB]["vm_id"]
    assert any("saved objects stay in Elasticsearch" in w and "encryption keys" in w for w in change["warnings"])


def test_removal_destroys_exactly_the_kibana_machine_after_approval_then_deletes_the_token_and_keeps_the_keys_and_the_sign_in(
        session, world, kb, conn):
    keys = credential(session, kb, 1)
    approve_and_run(session, world, run(session, world, kibana_op(session, plan_kibana_login(session, kb))))
    login = credential(session, kb, 2)
    vmid = kibana_of(kb.desired)[0].vm_id
    session.add(Vm(connection_id=kb.desired["proxmox_connection_id"], pve_node="pve3", vmid=vmid, name=KB, status="running", tf_managed=True))
    session.commit()
    assert (kb.desired["proxmox_connection_id"], vmid, KB) in created_machines(session)
    world.calls.clear()

    op = run(session, world, removing(session, world, kb))
    assert op.state == "pending_approval" and op.plan_summary["deletes"] == 1 and op.plan_summary["adds"] == 0
    assert world.calls.count("apply") == 0                                                    # nothing is destroyed before approval
    op = approve_and_run(session, world, op)
    assert op.state == "succeeded" and world.calls.count("apply") == 1
    request = world.ansible_requests[-1]
    assert request.kind == "remove_kibana" and [k.name for k in request.kibana] == [KB]

    session.refresh(kb)
    assert kb.desired["kibana"] == [] and "change" not in kb.desired
    assert credential(session, kb, 0) is None                                                 # the token is gone from ECM
    assert credential(session, kb, 1) == keys and credential(session, kb, 2) == login         # the keys and the sign-in stay
    assert session.scalar(select(Vm).where(Vm.vmid == vmid)) is None                          # forgotten at once, not at the next sync
    assert (kb.desired["proxmox_connection_id"], vmid, KB) not in created_machines(session)   # no longer ECM's: a stranger's VM there is not taken for ours
    assert "service token was deleted" in logs(session, op)


def test_a_plan_that_would_also_touch_a_node_or_create_anything_is_rejected_before_anyone_can_approve_it(session, world, kb):
    op = removing(session, world, kb)
    world.create_changes = [(KB_ADDR, "delete"), (ADDRS[0], "delete")]
    with pytest.raises(PlanRejected, match="must only delete the machines asked for"):
        run(session, world, op)


def test_a_plan_that_leaves_the_machine_alone_is_rejected_because_approving_it_would_not_remove_it(session, world, kb):
    op = removing(session, world, kb)
    world.create_changes = [(ADDRS[0], "update")]
    with pytest.raises(PlanRejected, match="does not delete lab-b-kb-01"):
        run(session, world, op)


def test_a_failed_token_deletion_leaves_the_machine_gone_and_a_retry_finishes_without_a_new_apply(session, world, kb):
    world.ansible_outcome = AnsibleOutcome(ok=False, error="Elasticsearch answered HTTP 403 when asked to delete the Kibana token")
    op = run(session, world, removing(session, world, kb))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(ConfigureFailed, match="HTTP 403.*The machine is gone; retry deletes the token again"):
        run(session, world, op)
    session.refresh(kb)
    assert kb.desired["kibana"] == [] and credential(session, kb, 0) == TOKEN                 # gone from the record, token kept until deleted
    applies = world.calls.count("apply")

    world.ansible_outcome = AnsibleOutcome(ok=True)
    world.create_changes = []                                                                  # Terraform finds the machine already gone
    operations.retry_operation(session, op.id)
    op = run(session, world, op)
    assert op.state == "succeeded" and world.calls.count("apply") == applies                  # an empty plan needs no second approval
    assert credential(session, kb, 0) is None


def test_after_a_removal_the_cluster_can_have_kibana_added_again_and_it_reads_the_old_saved_objects_with_the_same_keys(session, world, kb):
    keys = credential(session, kb, 1)
    approve_and_run(session, world, run(session, world, removing(session, world, kb)))
    session.refresh(kb)
    assert cluster_lifecycle(session, kb)["kibana"]["can_add"] is True
    world.create_changes = [(KB_ADDR, "create")]
    world.apply_outcome = ApplyOutcome(True, None, [*ADDRS, KB_ADDR], {})
    world.ansible_outcome = AnsibleOutcome(ok=True, kibana_token=TOKEN)
    world.ansible_requests.clear()
    approve_and_run(session, world, run(session, world, started(session, kb)))
    assert json.dumps(world.ansible_requests[-1].kibana_keys, sort_keys=True) == json.dumps(json.loads(keys), sort_keys=True)


def test_a_removed_kibanas_address_is_free_again(session, world, kb):
    from app.network_profiles import addresses_in_use
    address = kibana_of(kb.desired)[0].address
    assert any(a["ip"] == address for a in addresses_in_use(session))
    approve_and_run(session, world, run(session, world, removing(session, world, kb)))
    assert not any(a["ip"] == address for a in addresses_in_use(session))


def test_removal_is_refused_through_the_endpoint_without_the_name_and_plans_with_it(api, session, kb):
    assert api.post(f"/api/clusters/{kb.id}/remove-kibana", json={"confirm_name": "nope"}, headers=H).status_code == 409
    assert api.post(f"/api/clusters/{kb.id}/remove-kibana", json={}, headers=H).status_code == 422
    r = api.post(f"/api/clusters/{kb.id}/remove-kibana", json={"confirm_name": kb.name}, headers=H)
    assert r.status_code == 202 and r.json()["change"]["kind"] == "remove_kibana"
    assert session.get(Operation, r.json()["operation_id"]).kind == "tf.update"


def test_a_teardown_still_deletes_every_kibana_credential_including_the_sign_in(session, world, kb):
    approve_and_run(session, world, run(session, world, kibana_op(session, plan_kibana_login(session, kb))))
    names = tfop.kibana_credential_names(kb.id)
    assert all(session.scalar(select(Credential).where(Credential.name == n)) is not None for n in names)
    tfop._delete_record(session, kb, "admin")
    assert session.scalars(select(Credential).where(Credential.name.in_(names))).all() == []
