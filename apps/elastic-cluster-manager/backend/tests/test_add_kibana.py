"""Adding Kibana to a built cluster (docs/DESIGN_KIBANA.md, slice 6a): the rules, the Terraform render, the plan safety rule, who owns the
machine afterwards, and the operation end to end against the fake Terraform and Ansible the other operation tests use.

The Ansible roles that run on the Kibana machine and the live Kibana are not covered here; see test_ansible_kibana_roles.py for what runs for real.
"""
# ruff: noqa: F811  (the fixtures are imported from the other operation tests and used by name)
import copy
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import crypto, operations
from app.configmgmt import AnsibleOutcome
from app.desired.kibana import KibanaSpec, caddy_snippet, kibana_name, kibana_of
from app.desired.models import DesiredState
from app.models import Cluster, Credential, Operation, PveNode, PveStorage, Vm
from app.provisioning import operation as tfop
from app.provisioning.create import _reservations
from app.provisioning.lifecycle import AddKibana, AddNodes, plan_add_kibana, plan_add_nodes
from app.provisioning.operation import (
    ConfigureFailed,
    OperationRefused,
    PlanRejected,
    cluster_lifecycle,
    start_update,
)
from app.provisioning.ownership import created_machines, foreign_machines, machine_vm_ids
from app.provisioning.plan import PlanSummary, ResourceChange, check_add_kibana_plan
from app.provisioning.render import RenderError, RenderInput, TemplateRef, render_workspace
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

GIB = 1024 ** 3
KB = "lab-b-kb-01"
KB_ADDR = f'module.node["{KB}"].proxmox_virtual_environment_vm.this'
TOKEN = "AAEAAWVsYXN0aWMva2liYW5hL0001FakeServiceTokenForTests"


@pytest.fixture
def lab_b(session, world, cluster, conn):
    """A built three-node cluster (the create ran through the fake Terraform and Ansible) on three online hosts with room, a template
    and an ECM API key and CA on record, as a real create leaves them."""
    reach_success(session, world, cluster, conn)
    for host in ("pve1", "pve2", "pve3"):
        session.add(PveNode(connection_id=conn.id, name=host, status="online",
                            usage={"maxcpu": 40, "maxmem": 187 * GIB, "mem": 10 * GIB, "cpu": 0.1}))
        session.add(PveStorage(connection_id=conn.id, node=host, name="tank", type="nfs", shared=True, active=True,
                               total=16000 * GIB, used=100 * GIB, avail=15900 * GIB))
    session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=8000, name="ubuntu-25.04", status="stopped", is_template=True,
                   disks=[{"slot": "scsi0", "storage": "tank", "size_gb": 32}]))
    cluster.health_status = "green"
    session.commit()
    session.refresh(cluster)
    world.create_changes = [(KB_ADDR, "create")]
    world.apply_outcome = ApplyOutcome(True, None, [*ADDRS, KB_ADDR], {})
    world.ansible_outcome = AnsibleOutcome(ok=True, kibana_token=TOKEN)
    world.ansible_requests.clear()
    world.calls.clear()
    return cluster


def es(cluster, **kw):
    return FakeEs(DesiredState.model_validate(cluster.desired["state"]), **kw)


def planned(session, cluster, **kw):
    return plan_add_kibana(session, cluster, AddKibana(**kw), es(cluster))


def started(session, cluster, **kw):
    return start_update(session, cluster_id=cluster.id, params=planned(session, cluster, **kw), actor="admin")


def approve_and_run(session, world, op):
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    return run(session, world, op)


def credential(session, cluster, which):
    row = session.scalar(select(Credential).where(Credential.name == tfop.kibana_credential_names(cluster.id)[which]))
    return None if row is None else crypto.decrypt(row.ciphertext)


# -- the machine's description -----------------------------------------------------------------------------------------------

def test_a_kibana_spec_has_the_default_size_and_normalizes_its_public_name():
    spec = KibanaSpec(name=KB, vm_id=520, address="192.0.2.115", host="pve2", public_name=" Kibana.Lab.Example.org. ")
    assert (spec.cores, spec.ram_mb, spec.os_disk_gb) == (2, 4096, 32)
    assert spec.public_name == "kibana.lab.example.org" and spec.public_url == "https://kibana.lab.example.org"
    assert spec.url == "https://192.0.2.115:5601"
    assert KibanaSpec(name=KB, vm_id=520, address="192.0.2.115", host="pve2", public_name="").public_name is None


@pytest.mark.parametrize("bad", [{"public_name": "https://kibana.example.org"}, {"public_name": "kibana.example.org:5601"},
                                 {"public_name": "has space.example.org"}, {"address": "not-an-ip"}, {"name": "Bad_Name"},
                                 {"cores": 0}, {"ram_mb": 1024}, {"os_disk_gb": 8}, {"vm_id": 0}, {"unknown": 1}])
def test_a_bad_kibana_spec_is_refused(bad):
    with pytest.raises(ValidationError):
        KibanaSpec(**{"name": KB, "vm_id": 520, "address": "192.0.2.115", "host": "pve2", **bad})


def test_the_machine_is_named_after_the_cluster_and_a_cluster_without_kibana_has_none():
    assert kibana_name("lab-b") == "lab-b-kb-01"
    assert kibana_of({}) == [] and kibana_of({"kibana": []}) == []


def test_the_caddy_snippet_verifies_kibana_through_the_cluster_ca_and_needs_a_public_name():
    spec = KibanaSpec(name=KB, vm_id=520, address="192.168.10.116", host="pve2", public_name="kibana.lab.example.org")
    snippet = caddy_snippet("lab-b", spec)
    assert snippet == ("kibana.lab.example.org {\n\treverse_proxy https://192.168.10.116:5601 {\n"
                       "\t\ttransport http { tls_trust_pool file /etc/caddy/ecm/lab-b-ca.crt }\n\t}\n}\n")
    assert "insecure" not in snippet
    assert caddy_snippet("lab-b", KibanaSpec(name=KB, vm_id=520, address="192.168.10.116", host="pve2")) is None


# -- planning ---------------------------------------------------------------------------------------------------------------------

def test_the_machine_gets_the_next_name_an_address_a_vmid_and_a_host_and_the_nodes_are_not_touched(session, lab_b):
    record = copy.deepcopy(lab_b.desired)
    params = planned(session, lab_b)
    (spec,) = kibana_of(params)
    assert spec.name == KB and (spec.cores, spec.ram_mb, spec.os_disk_gb) == (2, 4096, 32)
    assert spec.host in ("pve1", "pve2", "pve3")
    assert spec.address not in params["addresses"].values() and spec.vm_id not in params["vm_ids"].values()
    assert PROFILE.range_start <= spec.address <= PROFILE.range_end
    # Kibana is in its own list: every walk of the Elasticsearch nodes still sees exactly the nodes it saw.
    for key in ("state", "placement", "addresses", "vm_ids"):
        assert params[key] == record[key]
    assert lab_b.desired == record                              # planning changed nothing on record
    change = params["change"]
    assert change["kind"] == "add_kibana" and change["kibana_added"] == [KB]
    assert change["kibana"][KB]["url"] == spec.url
    assert "add Kibana 9.4.3 on a new machine lab-b-kb-01" in change["describe"]
    assert "No Elasticsearch node is configured or restarted" in change["describe"]


def test_the_plan_says_that_nobody_can_sign_in_yet_and_that_a_name_would_give_a_caddy_snippet(session, lab_b):
    notes = planned(session, lab_b)["change"]["warnings"]
    assert any("nobody can sign in" in n for n in notes) and any("no public name" in n for n in notes)
    named = planned(session, lab_b, public_name="kibana.lab.example.org")
    assert not any("no public name" in n for n in named["change"]["warnings"])
    assert kibana_of(named)[0].public_name == "kibana.lab.example.org"


def test_the_host_with_the_most_room_is_chosen_and_a_pinned_host_is_used_or_refused(session, lab_b, conn):
    for row in session.scalars(select(PveNode).where(PveNode.connection_id == conn.id)):
        row.usage = {**row.usage, "mem": (10 if row.name == "pve3" else 120) * GIB}
    session.commit()
    assert kibana_of(planned(session, lab_b))[0].host == "pve3"
    assert kibana_of(planned(session, lab_b, pve_node="pve1"))[0].host == "pve1"
    with pytest.raises(OperationRefused, match="pve9"):
        planned(session, lab_b, pve_node="pve9")


def test_a_size_given_in_the_request_is_used(session, lab_b):
    spec = kibana_of(planned(session, lab_b, cores=4, ram_mb=8192, os_disk_gb=64))[0]
    assert (spec.cores, spec.ram_mb, spec.os_disk_gb) == (4, 8192, 64)


def test_a_cluster_that_already_has_kibana_is_refused(session, lab_b):
    lab_b.desired = planned(session, lab_b)
    with pytest.raises(OperationRefused, match="already has Kibana"):
        planned(session, lab_b)


@pytest.mark.parametrize("status,master,message", [("red", "lab-b-01", "the cluster is red"), ("green", None, "no elected master")])
def test_a_cluster_that_cannot_make_the_token_is_refused_with_the_reason(session, lab_b, status, master, message):
    fake = es(lab_b, status=status)
    if master is None:
        fake.master = list
    with pytest.raises(OperationRefused, match=message):
        plan_add_kibana(session, lab_b, AddKibana(), fake)


def test_a_yellow_cluster_is_fine_because_only_the_token_needs_it(session, lab_b):
    assert plan_add_kibana(session, lab_b, AddKibana(), es(lab_b, status="yellow"))["change"]["kind"] == "add_kibana"


def test_a_cluster_that_is_not_built_or_has_no_record_is_refused(session, lab_b):
    fake = es(lab_b)                                             # made while the record still exists
    lab_b.desired = None
    with pytest.raises(OperationRefused, match="no record"):
        plan_add_kibana(session, lab_b, AddKibana(), fake)
    lab_b.bootstrapped_at = None
    with pytest.raises(OperationRefused, match="not finished being built"):
        plan_add_kibana(session, lab_b, AddKibana(), fake)


def test_with_no_host_that_has_room_the_refusal_says_why_for_each(session, lab_b, conn):
    for row in session.scalars(select(PveNode).where(PveNode.connection_id == conn.id)):
        row.usage = {**row.usage, "mem": 186 * GIB}
    session.commit()
    with pytest.raises(OperationRefused, match=r"no host can take the Kibana machine \(pve1: not enough free RAM"):
        planned(session, lab_b)


def test_a_name_already_taken_by_a_machine_is_refused(session, lab_b, conn):
    session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=999, name=KB, status="running"))
    session.commit()
    with pytest.raises(OperationRefused, match=KB):
        planned(session, lab_b)


def test_a_template_the_chosen_host_cannot_read_is_refused(session, lab_b, conn):
    for row in session.scalars(select(PveStorage).where(PveStorage.connection_id == conn.id)):
        row.shared = False                                       # the template's disk is now readable on its own host only
    session.commit()
    with pytest.raises(OperationRefused, match="not on shared storage"):
        planned(session, lab_b, pve_node="pve2")
    assert kibana_of(planned(session, lab_b, pve_node="pve1"))[0].host == "pve1"


def test_a_cluster_whose_name_leaves_no_room_for_the_suffix_is_refused_in_plain_words(session, lab_b):
    lab_b.desired["state"]["name"] = "a" * 38                    # 38 + "-kb-01" is longer than a machine name may be
    with pytest.raises(OperationRefused, match="name"):
        planned(session, lab_b)


def test_an_address_or_vmid_another_cluster_is_about_to_use_is_not_given_out(session, lab_b, conn):
    first = planned(session, lab_b)
    other = Cluster(name="lab-z", ownership="managed")
    session.add(other)
    session.flush()
    session.add(Operation(kind="tf.update", state="running", cluster_id=other.id, dry_run=False, created_by="admin",
                          params={**first, "kibana": first["kibana"], "change": first["change"]}))
    session.commit()
    addresses, vmids = _reservations(session, lab_b.id)
    spec = kibana_of(first)[0]
    assert spec.address in addresses and spec.vm_id in vmids     # while the update is in flight it holds both


def test_a_recorded_kibana_address_stays_taken_though_neither_proxmox_nor_elasticsearch_ever_reports_it(session, world, lab_b):
    """Kibana is not an Elasticsearch node and its VM has no guest agent, so only ECM's own record keeps its address from being given out."""
    from app.network_profiles import addresses_in_use
    approve_and_run(session, world, run(session, world, started(session, lab_b)))
    session.refresh(lab_b)
    spec = kibana_of(lab_b.desired)[0]
    assert {"ip": spec.address, "source": "ecm", "name": KB} in addresses_in_use(session)
    # so the next node added to this cluster does not get it (it is the first free address after the three nodes')
    more = plan_add_nodes(session, lab_b, AddNodes(roles=["ml"]))
    assert spec.address not in more["addresses"].values()


def test_the_request_is_bounded_and_takes_no_unknown_fields():
    for bad in ({"cores": 0}, {"ram_mb": 1024}, {"os_disk_gb": 8}, {"pve_node": ""}, {"public_name": "x" * 300}, {"count": 2}):
        with pytest.raises(ValueError):
            AddKibana(**bad)


# -- the Terraform configuration --------------------------------------------------------------------------------------------

def render_input(params, **over):
    return RenderInput(
        cluster_id="abcdef0123456789", state=DesiredState.model_validate(params["state"]), placement=params["placement"],
        addresses=params["addresses"], vm_ids=params["vm_ids"], profile=PROFILE, template=TemplateRef("pve1", 8000),
        proxmox_endpoint="https://pve2.lab.example.org:8006/", kibana=kibana_of(params), **over)


def tfvars(params, **over):
    return json.loads(render_workspace(render_input(params, **over))["cluster.auto.tfvars.json"])


def test_the_kibana_machine_is_one_more_entry_of_the_same_terraform_map_with_no_data_disk(session, lab_b):
    params = planned(session, lab_b)
    nodes = tfvars(params)["nodes"]
    spec = kibana_of(params)[0]
    assert set(nodes) == {*params["vm_ids"], KB}
    assert nodes[KB] == {"node_name": spec.host, "vm_id": spec.vm_id, "cores": 2, "memory_mb": 4096, "os_disk_gb": 32,
                         "data_disk_gb": None, "address": f"{spec.address}/24", "gateway": "192.0.2.1"}
    without = {k: v for k, v in params.items() if k != "kibana"}
    assert {k: v for k, v in nodes.items() if k != KB} == tfvars(without)["nodes"]       # the nodes' entries are unchanged


def test_a_cluster_without_kibana_renders_exactly_as_before(session, lab_b):
    files = render_workspace(render_input({k: v for k, v in lab_b.desired.items() if k != "kibana"}))
    assert KB not in files["cluster.auto.tfvars.json"]


@pytest.mark.parametrize("over,message", [
    ({"name": "lab-b-01"}, "has the name of another machine"),
    ({"vm_id": 500}, "is used by another machine"),
    ({"vm_id": 50}, "must be 100 or higher"),
    ({"address": "192.0.2.110"}, "is used by another machine"),
    ({"address": "10.9.9.9"}, "is outside the profile network"),
    ({"host": "bad host"}, "not a valid Proxmox host name"),
])
def test_a_kibana_machine_that_clashes_with_a_node_or_leaves_the_network_is_not_rendered(session, lab_b, over, message):
    params = planned(session, lab_b)
    params["kibana"][0].update(over)
    with pytest.raises(RenderError, match=message):
        render_workspace(render_input(params))


# -- the plan safety rule -------------------------------------------------------------------------------------------------------

def changes(*pairs):
    return PlanSummary([ResourceChange(a, act) for a, act in pairs])


def test_a_plan_that_creates_only_the_kibana_machine_is_safe():
    assert check_add_kibana_plan(changes((KB_ADDR, "create")), frozenset({KB})) == []
    assert check_add_kibana_plan(changes((KB_ADDR, "create"), (ADDRS[0], "update")), frozenset({KB})) == []   # a change is tolerated


@pytest.mark.parametrize("summary,message", [
    (changes((KB_ADDR, "create"), ('module.node["lab-b-07"].x.y', "create")), "would create module.node"),
    (changes((KB_ADDR, "create"), (ADDRS[0], "delete")), "would delete"),
    (changes((KB_ADDR, "create"), (ADDRS[0], "replace")), "would replace"),
    (changes((KB_ADDR, "replace")), "would replace"),
    (changes(), "does not create a machine for lab-b-kb-01"),
    (changes((ADDRS[0], "update")), "does not create a machine for lab-b-kb-01"),
])
def test_a_plan_that_does_anything_else_is_rejected(summary, message):
    assert any(message in p for p in check_add_kibana_plan(summary, frozenset({KB})))


# -- the operation ----------------------------------------------------------------------------------------------------------------

def test_adding_kibana_waits_for_approval_then_builds_only_the_kibana_machine(session, world, lab_b, conn):
    op = run(session, world, started(session, lab_b))
    assert op.state == "pending_approval" and world.ansible_requests == []        # nothing was asked of Ansible before approval
    assert [n for n, _ in steps(session, op)] == ["render", "init", "plan", "approval", "apply", "configure"]
    assert op.plan_summary["adds"] == 1 and op.plan_summary["deletes"] == 0
    assert "add Kibana 9.4.3 on a new machine lab-b-kb-01" in op.plan_summary["configure"]

    op = approve_and_run(session, world, op)
    assert op.state == "succeeded"
    (request,) = world.ansible_requests
    assert request.kind == "add_kibana" and request.bootstrapped_at is not None
    assert [(k.name, k.public_url) for k in request.kibana] == [(KB, None)]
    assert request.kibana_token is None                                             # the first run: none yet, the run makes one
    assert set(request.kibana_keys) == {"security", "saved_objects", "reporting"}
    assert all(len(v) >= 32 for v in request.kibana_keys.values()) and len(set(request.kibana_keys.values())) == 3
    assert request.es_api_key and request.es_ca_pem and request.ca_key_pem          # the token call, the check and the certificate
    assert [n.name for n in request.state.nodes] == ["lab-b-01", "lab-b-02", "lab-b-03"]   # the Elasticsearch nodes are unchanged
    assert "Kibana is running and reports itself available" in logs(session, op)


def test_what_ansible_made_is_kept_encrypted_and_the_recorded_state_gains_only_the_kibana_machine(session, world, lab_b):
    before = copy.deepcopy(lab_b.desired)
    op = approve_and_run(session, world, run(session, world, started(session, lab_b)))
    session.refresh(lab_b)
    assert credential(session, lab_b, 0) == TOKEN
    keys = json.loads(credential(session, lab_b, 1))
    assert set(keys) == {"security", "saved_objects", "reporting"} and keys == {k: v for k, v in world.ansible_requests[0].kibana_keys.items()}
    for secret in (TOKEN, *keys.values()):
        raw = [c.ciphertext for c in session.scalars(select(Credential))]
        assert all(secret.encode() not in blob for blob in raw)                    # not stored in the clear
    assert [k["name"] for k in lab_b.desired["kibana"]] == [KB] and "change" not in lab_b.desired
    for key in ("state", "placement", "addresses", "vm_ids"):
        assert lab_b.desired[key] == before[key]
    assert op.params["change"]["kind"] == "add_kibana"


def test_a_failed_configure_keeps_the_machine_the_token_and_the_keys_and_a_retry_reuses_all_three(session, world, lab_b):
    world.ansible_outcome = AnsibleOutcome(ok=False, error="Kibana did not become available: lab-b-kb-01 is degraded", kibana_token=TOKEN)
    op = run(session, world, started(session, lab_b))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(ConfigureFailed, match="did not become available.*retry runs the configuration again with the same token"):
        run(session, world, op)
    session.refresh(lab_b)
    assert credential(session, lab_b, 0) == TOKEN                                  # stored even though the run failed
    first_keys = json.loads(credential(session, lab_b, 1))
    assert [k["name"] for k in lab_b.desired["kibana"]] == [KB]                      # the machine exists, so it is on record

    operations.retry_operation(session, op.id)
    world.create_changes = []                                                        # Terraform already made the machine
    world.ansible_outcome = AnsibleOutcome(ok=True)                                  # this run makes no token of its own
    op = run(session, world, op)
    assert op.state == "succeeded"                                                   # an empty plan needs no second approval
    second = world.ansible_requests[-1]
    assert second.kibana_token == TOKEN and second.kibana_keys == first_keys         # the same token and the same keys, none made again
    assert world.calls.count("apply") == 1                                           # the machine was made once


def test_a_plan_that_would_also_touch_a_node_is_rejected_before_anyone_can_approve_it(session, world, lab_b):
    world.create_changes = [(KB_ADDR, "create"), (ADDRS[0], "delete")]
    with pytest.raises(PlanRejected, match="would delete"):
        run(session, world, started(session, lab_b))


def test_a_cluster_without_an_api_key_or_ca_is_not_configured_and_the_machine_is_kept(session, world, lab_b):
    op = run(session, world, started(session, lab_b))
    for row in session.scalars(select(Credential).where(Credential.kind == "es_ca_key")):
        session.delete(row)
    session.commit()
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(ConfigureFailed, match="cannot make Kibana's token.*machine is kept"):
        run(session, world, op)
    session.refresh(lab_b)
    assert [k["name"] for k in lab_b.desired["kibana"]] == [KB]


def test_an_ansible_error_is_reported_as_a_failed_configure_with_the_machine_kept(session, world, lab_b):
    world.ansible_error = "ansible-playbook was not found"
    op = run(session, world, started(session, lab_b))
    operations.approve_operation(session, op.id, op.plan_digest, "admin")
    with pytest.raises(ConfigureFailed, match="ansible-playbook was not found.*machine is kept"):
        run(session, world, op)


def test_the_plan_checks_the_terraform_token_can_make_a_machine(session, world, lab_b):
    world.perms = {k: v for k, v in world.perms.items() if k != "/vms/8000"}          # it may no longer clone the template
    with pytest.raises(tfop.PreflightFailed, match="missing rights"):
        run(session, world, started(session, lab_b))


# -- whose machine it is -----------------------------------------------------------------------------------------------------------

def test_a_kibana_machine_is_ecms_once_its_apply_recorded_it_and_nothing_else_at_that_vmid_is(session, world, lab_b, conn):
    assert not any(name == KB for _, _, name in created_machines(session))
    op = approve_and_run(session, world, run(session, world, started(session, lab_b)))
    vmid = int(kibana_of(op.params)[0].vm_id)
    assert (conn.id, vmid, KB) in created_machines(session)
    assert machine_vm_ids(lab_b.desired)[KB] == vmid

    session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=vmid, name="someone-elses", status="running", tf_managed=False))
    session.commit()
    assert foreign_machines(session, lab_b.desired) == [f"{vmid} (someone-elses)"]
    with pytest.raises(OperationRefused, match="only touches machines ECM created"):
        start_update(session, cluster_id=lab_b.id, params=copy.deepcopy(lab_b.desired) | {"change": {"kind": "resize"}}, actor="admin")


def test_a_later_change_to_the_nodes_keeps_the_kibana_machine_in_the_terraform_configuration(session, world, lab_b):
    approve_and_run(session, world, run(session, world, started(session, lab_b)))
    session.refresh(lab_b)
    params = copy.deepcopy(lab_b.desired)
    assert KB in tfvars(params)["nodes"]                                           # a resize or add-node plan would not delete it


def test_a_teardown_destroys_kibana_with_the_cluster_and_forgets_its_credentials_and_machine(session, world, lab_b, conn):
    from tests.test_tf_operations import finish_teardown
    created = session.scalar(select(Operation).where(Operation.kind == "tf.create"))
    approve_and_run(session, world, run(session, world, started(session, lab_b)))
    session.refresh(lab_b)
    vmid = int(lab_b.desired["kibana"][0]["vm_id"])
    session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=vmid, name=KB, status="running", tf_managed=True))
    session.commit()
    cluster_id = lab_b.id
    world.destroy_changes = [(a, "delete") for a in (*ADDRS, KB_ADDR)]
    teardown = finish_teardown(session, world, created)
    assert teardown.state == "succeeded" and teardown.plan_summary["deletes"] == 4        # three nodes and the Kibana machine
    assert session.get(Cluster, cluster_id) is None
    assert session.scalars(select(Credential).where(Credential.name.in_(tfop.kibana_credential_names(cluster_id)))).all() == []
    assert session.scalar(select(Vm).where(Vm.connection_id == conn.id, Vm.vmid == vmid)) is None
    assert "removed with its machines" in logs(session, teardown)


# -- what the cluster page shows ----------------------------------------------------------------------------------------------------

def test_the_panel_offers_add_kibana_until_there_is_one_and_then_shows_it_with_its_caddy_snippet(session, world, lab_b):
    panel = cluster_lifecycle(session, lab_b)["kibana"]
    assert panel["can_add"] is True and panel["machines"] == [] and panel["last_add"] is None and panel["ca_available"] is True

    op = started(session, lab_b, public_name="kibana.lab.example.org")
    assert cluster_lifecycle(session, lab_b)["kibana"]["can_add"] is False             # an operation is running: not offered again
    approve_and_run(session, world, run(session, world, op))
    session.refresh(lab_b)
    panel = cluster_lifecycle(session, lab_b)["kibana"]
    (machine,) = panel["machines"]
    assert panel["can_add"] is False and machine["name"] == KB and machine["public_url"] == "https://kibana.lab.example.org"
    assert machine["caddy_snippet"].startswith("kibana.lab.example.org {") and "lab-b-ca.crt" in machine["caddy_snippet"]
    assert panel["last_add"]["state"] == "succeeded" and panel["last_add"]["operation_id"] == op.id
    for secret in (TOKEN, *json.loads(credential(session, lab_b, 1)).values()):
        assert secret not in json.dumps(cluster_lifecycle(session, lab_b))             # no secret is ever sent to the page


# -- the HTTP layer -------------------------------------------------------------------------------------------------------------------

H = {"x-ecm-csrf": "1"}


@pytest.fixture
def api(logged_in, lab_b, monkeypatch):
    from procrastinate import testing

    from app import jobs
    from app.api.provisioning import get_catalog
    from app.desired import StaticCatalog
    from app.main import app
    from app.provisioning import lifecycle
    app.dependency_overrides[get_catalog] = lambda: StaticCatalog(["9.4.3"])
    monkeypatch.setattr(lifecycle.factory, "es_client", lambda db, cluster, url: es(lab_b))
    with jobs.queue.replace_connector(testing.InMemoryConnector()):
        yield logged_in
    app.dependency_overrides.pop(get_catalog, None)


def test_the_endpoint_plans_adding_kibana_and_enqueues_the_job(api, session, lab_b):
    r = api.post(f"/api/clusters/{lab_b.id}/add-kibana", json={"public_name": "kibana.lab.example.org"}, headers=H)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["change"]["kind"] == "add_kibana" and body["change"]["kibana"][KB]["public_url"] == "https://kibana.lab.example.org"
    op = session.get(Operation, body["operation_id"])
    assert op.kind == "tf.update" and op.state != "succeeded" and op.params["kibana"][0]["name"] == KB


def test_the_endpoint_refuses_with_the_reason_and_needs_the_csrf_header_and_a_session(api, client, lab_b):
    assert api.post(f"/api/clusters/{lab_b.id}/add-kibana", json={}, headers=H).status_code == 202
    again = api.post(f"/api/clusters/{lab_b.id}/add-kibana", json={}, headers=H)
    assert again.status_code == 409 and "already" in again.json()["detail"]
    assert api.post(f"/api/clusters/{lab_b.id}/add-kibana", json={}).status_code == 403
    assert api.post(f"/api/clusters/{lab_b.id}/add-kibana", json={"count": 2}, headers=H).status_code == 422
    assert api.post("/api/clusters/nope/add-kibana", json={}, headers=H).status_code == 404


def test_a_version_the_repository_cannot_supply_is_refused_before_a_plan_is_made(api, session, lab_b):
    from app.api.provisioning import get_catalog
    from app.desired import StaticCatalog
    from app.main import app
    app.dependency_overrides[get_catalog] = lambda: StaticCatalog(["9.3.1"])             # the cluster's 9.4.3 is not on the list
    r = api.post(f"/api/clusters/{lab_b.id}/add-kibana", json={}, headers=H)
    assert r.status_code == 409 and "Kibana cannot be installed" in r.json()["detail"]
    assert session.scalars(select(Operation).where(Operation.cluster_id == lab_b.id, Operation.kind == "tf.update")).all() == []


def test_the_cluster_ca_certificate_can_be_downloaded_by_a_signed_in_user_only(api, client, lab_b):
    r = api.get(f"/api/clusters/{lab_b.id}/ca.crt")
    assert r.status_code == 200 and r.text == lab_b.tls_ca_pem and r.headers["content-type"].startswith("application/x-pem-file")
    assert "lab-b-ca.crt" in r.headers["content-disposition"]
    assert api.get("/api/clusters/nope/ca.crt").status_code == 404
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as anonymous:
        assert anonymous.get(f"/api/clusters/{lab_b.id}/ca.crt").status_code == 401


def test_the_operation_start_is_audited(session, world, lab_b):
    started(session, lab_b)
    from app.models import AuditEvent
    events = [e for e in session.scalars(select(AuditEvent)) if e.action == "operation.start" and (e.details.get("change") or {}).get("kind") == "add_kibana"]
    assert len(events) == 1
    assert TOKEN not in json.dumps(events[0].details)
