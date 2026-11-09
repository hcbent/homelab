"""Kibana at create time (docs/DESIGN_KIBANA.md, slice 6c, decision 8): the machine is planned and built in the same Terraform plan as the cluster, under
one approval, and installed once the cluster has bootstrapped. Planning is tested against the same fake Proxmox the create tests use; the operation
against the fake Terraform and Ansible of the other operation tests."""
# ruff: noqa: F811  (the fixtures are imported from the other tests and used by name)
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import crypto, operations
from app.configmgmt import AnsibleError, AnsibleOutcome
from app.desired.kibana import kibana_of
from app.models import Cluster, Credential, Operation, PveNode, Vm
from app.provisioning import operation as tfop
from app.provisioning.create import CreateInvalid, plan_kibana_machine
from app.provisioning.operation import ConfigureFailed, cluster_lifecycle, start_create
from app.provisioning.ownership import created_machines
from app.provisioning.render import RenderInput, TemplateRef, render_workspace
from app.provisioning.runner import ApplyOutcome
from tests.test_create_cluster import GIB, H, api, plan, pve, request  # noqa: F401  (pve and api are fixtures)
from tests.test_tf_operations import (  # noqa: F401  (fixtures and helpers shared with the other operation tests)
    ADDRS,
    PROFILE,
    FakeAnsible,
    cluster,
    conn,
    creates,
    good_ansible_outcome,
    logs,
    params_for,
    run,
    steps,
    world,
)

KB = "lab-b-kb-01"
KB_ADDR = f'module.node["{KB}"].proxmox_virtual_environment_vm.this'
TOKEN = "AAEAAWVsYXN0aWMva2liYW5hL0001FakeServiceTokenForTests"


# -- planning ---------------------------------------------------------------------------------------------------------------------------

def test_a_create_that_does_not_ask_for_kibana_plans_none(session, pve):
    resolved = plan(session)[2]
    assert resolved.kibana == [] and "kibana" not in resolved.params


def test_a_create_that_asks_for_kibana_plans_one_machine_with_a_host_an_address_and_a_vmid_beside_the_nodes(session, pve):
    _, op, resolved = plan(session, kibana={})
    (spec,) = resolved.kibana
    assert spec.name == KB and (spec.cores, spec.ram_mb, spec.os_disk_gb) == (2, 4096, 32) and spec.public_name is None
    assert spec.host in ("pve1", "pve2", "pve3")
    assert spec.address not in resolved.addresses.values() and spec.vm_id not in resolved.vm_ids.values()
    assert op.params["kibana"] == [spec.model_dump(mode="json")]
    for key in ("state", "placement", "addresses", "vm_ids"):                    # the nodes' own tables are exactly what they were
        assert KB not in json.dumps(op.params[key])
    assert spec.es_hosts == [f"https://{a}:9200" for a in resolved.addresses.values()]


def test_the_plan_says_one_approval_covers_both_and_that_nobody_can_sign_in_until_the_sign_in_is_set_up(session, pve):
    notes = plan(session, kibana={})[2].warnings
    assert any("same plan" in n and "one approval covers both" in n and "Create sign-in" in n for n in notes)
    assert any("no public name" in n for n in notes)
    named = plan(session, name="lab-c", kibana={"public_name": "kibana.lab.example.org"})[2]
    assert not any("no public name" in n for n in named.warnings) and named.kibana[0].public_name == "kibana.lab.example.org"


def test_the_requested_size_and_host_are_used(session, pve):
    spec = plan(session, kibana={"cores": 4, "ram_mb": 8192, "os_disk_gb": 64, "pve_node": "pve3"})[2].kibana[0]
    assert (spec.cores, spec.ram_mb, spec.os_disk_gb, spec.host) == (4, 8192, 64, "pve3")


def test_a_host_that_is_not_known_is_refused(session, pve):
    with pytest.raises(CreateInvalid, match="pve9"):
        plan(session, kibana={"pve_node": "pve9"})


def test_the_room_the_clusters_own_nodes_will_take_is_counted_before_kibana_is_placed(session, pve):
    """Each host has 20 GiB free: room for a node (8 GiB) or for Kibana (4 GiB) after the host's reserve, but not for both."""
    for row in session.scalars(select(PveNode).where(PveNode.connection_id == pve.id)):
        row.usage = {**row.usage, "mem": 167 * GIB}
    session.commit()
    assert plan(session, name="no-kb")[2].kibana == []                            # the cluster alone fits
    with pytest.raises(CreateInvalid, match=r"no host can take the Kibana machine \(pve1: not enough free RAM"):
        plan(session, name="with-kb", kibana={})                                  # with its nodes already counted, Kibana does not


def test_a_cluster_name_with_no_room_for_the_suffix_is_refused_in_plain_words(session, pve):
    with pytest.raises(CreateInvalid, match="Kibana machine cannot be named or sized"):
        plan(session, name="a" * 36, kibana={})                                      # the nodes' names fit (39); Kibana's would be 42


def test_a_machine_that_already_has_kibanas_name_is_refused(session, pve):
    session.add(Vm(connection_id=pve.id, pve_node="pve1", vmid=999, name=KB, status="running"))
    session.commit()
    with pytest.raises(CreateInvalid, match=KB):
        plan(session, kibana={})


def test_the_kibana_request_is_bounded_and_takes_no_unknown_fields():
    for bad in ({"cores": 0}, {"ram_mb": 1024}, {"os_disk_gb": 8}, {"pve_node": ""}, {"count": 2}, {"public_name": "x" * 300}):
        with pytest.raises(ValidationError):
            request(kibana=bad)


def test_two_clusters_planned_back_to_back_never_share_the_kibana_address_or_vmid(session, pve):
    first = plan(session, name="lab-a", kibana={}, dry_run=False)[2]
    second = plan(session, name="lab-b", kibana={}, dry_run=False)[2]
    assert first.kibana[0].address != second.kibana[0].address and first.kibana[0].vm_id != second.kibana[0].vm_id
    taken = {*first.addresses.values(), first.kibana[0].address}
    assert not taken & {*second.addresses.values(), second.kibana[0].address}


def test_the_terraform_configuration_of_the_create_has_the_kibana_machine_in_the_same_map(session, pve):
    _, op, resolved = plan(session, kibana={}, dry_run=False)
    params = op.params
    inp = RenderInput(cluster_id="abcdef0123456789", state=resolved.state, placement=params["placement"], addresses=params["addresses"],
                      vm_ids=params["vm_ids"], profile=PROFILE.__class__.model_validate(params["profile"]),
                      template=TemplateRef("pve1", 8000), proxmox_endpoint="https://pve2.lab.example.org:8006/", kibana=kibana_of(params))
    nodes = json.loads(render_workspace(inp)["cluster.auto.tfvars.json"])["nodes"]
    assert set(nodes) == {*params["vm_ids"], KB} and nodes[KB]["data_disk_gb"] is None


# -- the endpoint ---------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def queue():
    from procrastinate import testing

    from app import jobs
    with jobs.queue.replace_connector(testing.InMemoryConnector()):
        yield


def test_the_endpoint_returns_the_planned_kibana_machine_and_refuses_a_bad_request(api, session, queue):
    body = {"name": "lab-b", "version": "9.4.3", "preset": "three_node", "template_vmid": 8000, "dry_run": False}
    bad = api.post("/api/clusters", json={**body, "kibana": {"public_name": "https://kibana.example.org"}}, headers=H)
    assert bad.status_code == 422 and "DNS name" in bad.json()["detail"]
    assert api.post("/api/clusters", json={**body, "kibana": {"cores": 0}}, headers=H).status_code == 422
    assert session.scalars(select(Operation)).all() == []                                          # a refused request leaves nothing behind
    r = api.post("/api/clusters", json={**body, "kibana": {"public_name": "kibana.lab.example.org"}}, headers=H)
    assert r.status_code == 202, r.text
    (k,) = r.json()["kibana"]
    assert k["name"] == KB and k["public_url"] == "https://kibana.lab.example.org" and k["url"].endswith(":5601") and "es_hosts" not in k
    assert [n["name"] for n in r.json()["nodes"]] == ["lab-b-01", "lab-b-02", "lab-b-03"]               # the nodes list is the nodes alone


def test_a_create_without_kibana_returns_an_empty_list(api, queue):
    r = api.post("/api/clusters", json={"name": "lab-b", "version": "9.4.3", "preset": "three_node", "template_vmid": 8000}, headers=H)
    assert r.status_code == 202 and r.json()["kibana"] == []


# -- the operation ----------------------------------------------------------------------------------------------------------------------

def kibana_params(conn):
    params = params_for(conn)
    params["kibana"] = [{"name": KB, "vm_id": 503, "address": "192.0.2.113", "host": "pve3", "cores": 2, "ram_mb": 4096, "os_disk_gb": 32,
                         "public_name": None, "es_hosts": [f"https://192.0.2.{110 + i}:9200" for i in range(3)]}]
    return params


@pytest.fixture
def seen(monkeypatch, world):
    """What Ansible is asked and what it answers, by kind: the create builds the cluster; adding Kibana makes the token."""
    answers = {"create": good_ansible_outcome(), "add_kibana": AnsibleOutcome(ok=True, kibana_token=TOKEN)}
    asked: list = []

    def fake_run(self, request):
        asked.append(request)
        self.log("PLAY RECAP *****")
        outcome = answers[request.kind]
        if isinstance(outcome, str):
            raise AnsibleError(outcome)
        return outcome
    monkeypatch.setattr(FakeAnsible, "run", fake_run)
    world.create_changes = creates([*ADDRS, KB_ADDR])
    world.apply_outcome = ApplyOutcome(True, None, [*ADDRS, KB_ADDR], {})
    return type("Seen", (), {"answers": answers, "asked": asked})


def begin(session, cluster, conn):
    return start_create(session, cluster_id=cluster.id, params=kibana_params(conn), actor="admin")


def approve_and_run(session, world, op):
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    return run(session, world, op)


def credential(session, cluster, which):
    row = session.scalar(select(Credential).where(Credential.name == tfop.kibana_credential_names(cluster.id)[which]))
    return None if row is None else crypto.decrypt(row.ciphertext)


def test_the_plan_has_one_more_machine_and_the_approval_covers_installing_kibana_too(session, world, cluster, conn, seen):
    op = run(session, world, begin(session, cluster, conn))
    assert op.state == "pending_approval" and seen.asked == []
    assert op.plan_summary["adds"] == 4                                                  # three nodes and the Kibana machine
    assert [n for n, _ in steps(session, op)] == ["render", "init", "plan", "approval", "apply", "configure"]
    text = op.plan_summary["configure"]
    assert "install elasticsearch 9.4.3 on 3 nodes and start the cluster" in text
    assert f"then install Kibana 9.4.3 on {KB} (2 cores, 4096 MiB, a 32 GB disk) and check it reports itself available" in text


def test_a_create_with_and_without_kibana_have_different_digests_so_one_cannot_be_approved_as_the_other(session, world, cluster, conn, seen):
    with_kb = run(session, world, begin(session, cluster, conn))
    other = Cluster(name="lab-z", ownership="managed")
    session.add(other)
    session.commit()
    world.create_changes = creates(ADDRS)
    without = run(session, world, start_create(session, cluster_id=other.id, params=params_for(conn), actor="admin"))
    assert with_kb.plan_digest != without.plan_digest


def test_after_approval_the_cluster_is_built_first_and_then_kibana_is_installed_on_the_machine_the_same_plan_made(session, world, cluster, conn, seen):
    op = approve_and_run(session, world, run(session, world, begin(session, cluster, conn)))
    assert op.state == "succeeded" and world.calls.count("apply") == 1                  # one apply made all four machines
    assert [r.kind for r in seen.asked] == ["create", "add_kibana"]
    request = seen.asked[1]
    assert [k.name for k in request.kibana] == [KB] and request.bootstrapped_at is not None
    assert request.es_api_key and request.es_ca_pem and request.ca_key_pem                # what the new cluster just stored
    assert request.kibana_token is None and set(request.kibana_keys) == {"security", "saved_objects", "reporting"}
    assert [n.name for n in request.state.nodes] == ["lab-b-01", "lab-b-02", "lab-b-03"]
    assert op.result["kibana_added"] is True and op.result["configured"]["status"] == "green"
    assert "the cluster is built; now adding Kibana" in logs(session, op)
    session.refresh(cluster)
    assert [k["name"] for k in cluster.desired["kibana"]] == [KB] and cluster.bootstrapped_at is not None
    assert credential(session, cluster, 0) == TOKEN and set(json.loads(credential(session, cluster, 1))) == {"security", "saved_objects", "reporting"}


def test_the_kibana_machine_is_ecms_and_the_panel_says_how_it_was_added(session, world, cluster, conn, seen):
    op = approve_and_run(session, world, run(session, world, begin(session, cluster, conn)))
    session.refresh(cluster)
    assert (conn.id, 503, KB) in created_machines(session)
    panel = cluster_lifecycle(session, cluster)["kibana"]
    assert [m["name"] for m in panel["machines"]] == [KB] and panel["can_add"] is False
    assert panel["last_add"] == {"operation_id": op.id, "state": "succeeded", "finished_at": panel["last_add"]["finished_at"]}


def test_a_failure_installing_kibana_keeps_the_built_cluster_the_machine_and_the_token_and_a_retry_skips_the_cluster_build(
        session, world, cluster, conn, seen):
    seen.answers["add_kibana"] = AnsibleOutcome(ok=False, error="Kibana did not become available: lab-b-kb-01 is degraded", kibana_token=TOKEN)
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(ConfigureFailed, match="did not become available.*retry runs the configuration again with the same token and keys"):
        run(session, world, op)
    session.refresh(cluster)
    assert cluster.bootstrapped_at is not None and cluster.credential_id is not None             # the cluster is built and usable
    assert [k["name"] for k in cluster.desired["kibana"]] == [KB]                                  # the machine is on record
    assert credential(session, cluster, 0) == TOKEN
    keys = credential(session, cluster, 1)
    assert "kibana_added" not in (session.get(Operation, op.id).result or {})
    panel = cluster_lifecycle(session, cluster)["kibana"]
    assert panel["last_add"]["state"] == "failed" and panel["last_add"]["operation_id"] == op.id   # the panel points at the operation to retry

    seen.answers["add_kibana"] = AnsibleOutcome(ok=True)
    world.create_changes = []                                                                       # the machines exist; planning again finds nothing
    operations.retry_operation(session, op.id)
    op = run(session, world, op)
    assert op.state == "succeeded" and world.calls.count("apply") == 1                              # nothing applied twice; no second approval
    assert [r.kind for r in seen.asked] == ["create", "add_kibana", "add_kibana"]                    # the cluster was NOT built again
    again = seen.asked[2]
    assert again.kibana_token == TOKEN and json.dumps(again.kibana_keys, sort_keys=True) == json.dumps(json.loads(keys), sort_keys=True)
    assert op.result["kibana_added"] is True and "already bootstrapped" in logs(session, op)


def test_an_ansible_error_during_the_kibana_step_is_a_failed_configure_not_a_failed_cluster(session, world, cluster, conn, seen):
    seen.answers["add_kibana"] = "ansible-playbook was not found"
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(ConfigureFailed, match="ansible-playbook was not found"):
        run(session, world, op)
    session.refresh(cluster)
    assert cluster.bootstrapped_at is not None


def test_a_create_that_never_bootstrapped_never_reaches_kibana(session, world, cluster, conn, seen):
    seen.answers["create"] = AnsibleOutcome(ok=False, error="the nodes did not form a cluster")
    op = run(session, world, begin(session, cluster, conn))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(ConfigureFailed):
        run(session, world, op)
    assert [r.kind for r in seen.asked] == ["create"]
    session.refresh(cluster)
    assert cluster.bootstrapped_at is None and credential(session, cluster, 0) is None


def test_the_teardown_names_the_kibana_machine_destroys_it_with_the_cluster_and_forgets_everything_of_it(session, world, cluster, conn, seen):
    from tests.test_tf_operations import finish_teardown
    created = approve_and_run(session, world, run(session, world, begin(session, cluster, conn)))
    session.add(Vm(connection_id=conn.id, pve_node="pve3", vmid=503, name=KB, status="running", tf_managed=True))
    session.commit()
    session.refresh(cluster)
    assert KB in cluster_lifecycle(session, cluster)["nodes"]                                       # the panel names what a teardown destroys
    cluster_id = cluster.id
    world.destroy_changes = [(a, "delete") for a in (*ADDRS, KB_ADDR)]
    teardown = finish_teardown(session, world, created)
    assert teardown.state == "succeeded" and teardown.plan_summary["deletes"] == 4
    assert session.get(Cluster, cluster_id) is None
    assert session.scalars(select(Credential).where(Credential.name.in_(tfop.kibana_credential_names(cluster_id)))).all() == []
    assert session.scalar(select(Vm).where(Vm.connection_id == conn.id, Vm.vmid == 503)) is None


def test_the_plan_that_would_touch_anything_but_creates_is_still_rejected(session, world, cluster, conn, seen):
    from app.provisioning.operation import PlanRejected
    world.create_changes = [*creates([*ADDRS, KB_ADDR]), (ADDRS[0], "delete")]
    with pytest.raises(PlanRejected, match="would delete"):
        run(session, world, begin(session, cluster, conn))


def test_the_helper_is_the_one_add_kibana_uses_so_both_paths_give_the_same_machine(session, pve):
    from app.desired.kibana import KibanaRequest
    from app.provisioning.create import _profile, _template
    resolved = plan(session, kibana={})[2]
    spec = plan_kibana_machine(session, conn=pve, template=_template(session, pve, 8000), profile=_profile(session, None), datastore="tank",
                               state=resolved.state, node_addresses=resolved.addresses, node_vm_ids=resolved.vm_ids, request=KibanaRequest(),
                               taken_addresses={resolved.kibana[0].address}, taken_vmids={resolved.kibana[0].vm_id})
    assert spec.name == KB and (spec.cores, spec.ram_mb, spec.os_disk_gb) == (2, 4096, 32)
    assert spec.address != resolved.kibana[0].address and spec.vm_id != resolved.kibana[0].vm_id     # what the cluster already holds is skipped
