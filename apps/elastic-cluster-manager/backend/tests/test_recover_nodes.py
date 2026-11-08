"""The rules for recovering lost nodes: rebuilding a node whose machine is gone, and forgetting one that will not come back.
Same fake Proxmox and fake Elasticsearch as the removal tests. Nothing here makes a machine or changes a cluster."""
# ruff: noqa: F811  (the fixtures are imported from the removal tests and used by name)
import pytest

from app.desired.models import DesiredState
from app.models import PveNode, Vm
from app.provisioning.lifecycle import (
    ForgetNodes,
    RebuildNodes,
    plan_forget_nodes,
    plan_rebuild_nodes,
)
from app.provisioning.operation import OperationRefused
from app.provisioning.plan import PlanSummary, ResourceChange, check_forget_plan, check_rebuild_plan
from tests.test_create_cluster import pve  # noqa: F401  (a fixture)
from tests.test_remove_nodes import FakeEs, built, five_masters, state_of  # noqa: F401  (fixtures and a fake)


def lost_es(cluster, *lost, **kw):
    """Elasticsearch as it is when these nodes are gone: it does not report them, and the cluster is yellow."""
    es = FakeEs(state_of(cluster), status=kw.pop("status", "yellow"), **kw)
    es.hidden = set(lost)
    return es


def rebuild(session, cluster, *names, es=None, **request):
    return plan_rebuild_nodes(session, cluster, RebuildNodes(nodes=list(names), **request),
                              es or lost_es(cluster, *names))


def forget(session, cluster, *names, es=None, confirm=None):
    return plan_forget_nodes(session, cluster, ForgetNodes(nodes=list(names), confirm_name=confirm or cluster.name),
                             es or lost_es(cluster, *names))


# -- rebuilding ---------------------------------------------------------------------------------------------------------

def test_a_lost_node_is_rebuilt_where_it_was_with_the_same_name_address_vmid_and_roles(session, built):
    new = rebuild(session, built, "lab-x-06")
    assert new["state"] == built.desired["state"] and new["vm_ids"] == built.desired["vm_ids"]
    assert new["addresses"] == built.desired["addresses"] and new["placement"] == built.desired["placement"]
    change = new["change"]
    assert change["kind"] == "rebuild_nodes" and change["rebuilt"] == ["lab-x-06"]
    node = change["nodes"]["lab-x-06"]
    assert node["host"] == built.desired["placement"]["lab-x-06"] and node["moved"] is False
    assert node["address"] == built.desired["addresses"]["lab-x-06"] and node["vm_id"] == built.desired["vm_ids"]["lab-x-06"]
    assert "rebuild 1 lost node (lab-x-06)" in change["describe"]
    assert "data disks start empty" in change["describe"]


def test_a_host_can_be_chosen_and_the_change_says_the_node_moved(session, built):
    old = built.desired["placement"]["lab-x-06"]
    other = next(h for h in ("pve1", "pve2", "pve3") if h != old)
    new = rebuild(session, built, "lab-x-06", pve_node=other)
    assert new["placement"]["lab-x-06"] == other and new["change"]["nodes"]["lab-x-06"]["moved"] is True
    assert f"lab-x-06 goes to {other}, not {old} where it was" in new["change"]["warnings"]
    assert built.desired["placement"]["lab-x-06"] == old                                    # the record is not touched


def test_a_node_whose_old_host_is_not_online_is_placed_elsewhere(session, built):
    built.desired = {**built.desired, "placement": {**built.desired["placement"], "lab-x-06": "pve9"}}   # a host not online
    new = rebuild(session, built, "lab-x-06")
    assert new["placement"]["lab-x-06"] in ("pve1", "pve2", "pve3") and new["change"]["nodes"]["lab-x-06"]["moved"] is True


def test_a_master_whose_host_died_is_rebuilt_on_a_host_that_already_has_one_with_a_warning(session, built):
    """Three masters on three hosts: with one host gone, a rebuilt master has to share a host with another, and losing that host
    would break the quorum. Recovery wins over the spread (the operator's decision): ECM says so, and allows it."""
    dead = built.desired["placement"]["lab-x-03"]
    for host in session.query(PveNode).filter(PveNode.name == dead):
        host.status = "offline"
    session.commit()
    new = rebuild(session, built, "lab-x-03", "lab-x-06")
    hosts = new["placement"]
    assert hosts["lab-x-03"] != dead and hosts["lab-x-03"] in (hosts["lab-x-01"], hosts["lab-x-02"])
    warning = next(w for w in new["change"]["warnings"] if "would hold 2 of 3 master-eligible nodes" in w)
    assert "This is allowed because the cluster is being recovered" in warning
    assert new["change"]["nodes"]["lab-x-03"]["moved"] is True


def test_a_master_put_on_a_host_that_already_has_one_by_choice_is_allowed_with_the_same_warning(session, built):
    other = built.desired["placement"]["lab-x-02"]                                        # another master's host
    new = rebuild(session, built, "lab-x-01", pve_node=other)
    warnings = new["change"]["warnings"]
    assert any("would hold 2 of 3 master-eligible nodes" in w and "being recovered" in w for w in warnings)
    assert not any("pinned to the same Proxmox host" in w for w in warnings)               # the older warning said the same, with less reason
    assert len([w for w in warnings if "master" in w and "host" in w and "pve" in w]) == 1


def test_several_lost_nodes_are_rebuilt_together_and_a_node_that_is_not_lost_is_refused_with_why(session, built):
    new = rebuild(session, built, "lab-x-05", "lab-x-06")
    assert new["change"]["rebuilt"] == ["lab-x-05", "lab-x-06"]
    session.add(Vm(connection_id=built.desired["proxmox_connection_id"], pve_node="pve1",
                   vmid=built.desired["vm_ids"]["lab-x-06"], name="lab-x-06", status="stopped"))
    session.commit()
    with pytest.raises(OperationRefused, match=r"lab-x-06's machine \(VM 505\) exists in Proxmox and is stopped.*not rebuilt"):
        rebuild(session, built, "lab-x-06")


def test_a_vmid_that_now_belongs_to_another_machine_and_a_node_the_cluster_still_has_are_refused(session, built):
    vmid = built.desired["vm_ids"]["lab-x-06"]
    session.add(Vm(connection_id=built.desired["proxmox_connection_id"], pve_node="pve1", vmid=vmid, name="stranger",
                   status="running"))
    session.commit()
    with pytest.raises(OperationRefused, match="VM ID 505, which was lab-x-06's, now belongs to a machine named stranger"):
        rebuild(session, built, "lab-x-06")
    with pytest.raises(OperationRefused, match="lab-x-05 is in the cluster: Elasticsearch reports it"):
        rebuild(session, built, "lab-x-05", "lab-x-06", es=lost_es(built, "lab-x-06"))


def test_a_red_cluster_is_refused_and_the_unassigned_primaries_are_named(session, built):
    es = lost_es(built, "lab-x-06", status="red")
    es.extra_rows = [{"index": "logs", "shard": "0", "prirep": "p", "state": "UNASSIGNED", "node": None, "store": None},
                     {"index": "logs", "shard": "0", "prirep": "r", "state": "UNASSIGNED", "node": None, "store": None}]
    with pytest.raises(OperationRefused, match=r"the cluster is red: 1 primary shard is not assigned \(logs\[0\]\).*snapshot"):
        rebuild(session, built, "lab-x-06", es=es)
    with pytest.raises(OperationRefused, match="the cluster is red"):
        forget(session, built, "lab-x-06", es=es)


def test_a_cluster_with_no_master_and_one_missing_another_node_are_refused(session, built):
    es = lost_es(built, "lab-x-06")
    es.elected = ""
    with pytest.raises(OperationRefused, match="no elected master.*quorum loss"):
        rebuild(session, built, "lab-x-06", es=es)
    es = lost_es(built, "lab-x-05", "lab-x-06")                                           # 05 is missing too and not named
    with pytest.raises(OperationRefused, match="does not report lab-x-05, which are not among the nodes being recovered"):
        rebuild(session, built, "lab-x-06", es=es)


def test_a_single_node_cluster_an_unknown_node_and_a_duplicate_are_refused(session, built):
    with pytest.raises(OperationRefused, match="no node named lab-x-99"):
        rebuild(session, built, "lab-x-99")
    with pytest.raises(ValueError, match="twice"):
        RebuildNodes(nodes=["a", "a"])
    state, es = state_of(built), lost_es(built, "lab-x-01")
    only = state.nodes[0].model_copy(update={"roles_mode": "default", "roles": [], "data_disk_gb": 100})
    built.desired = {**built.desired, "state": state.model_copy(update={"nodes": [only]}).model_dump(mode="json")}
    with pytest.raises(OperationRefused, match="single-node cluster"):
        rebuild(session, built, "lab-x-01", es=es)


# -- forgetting ---------------------------------------------------------------------------------------------------------

def test_forgetting_a_lost_node_drops_it_from_the_record_and_keeps_its_details_in_the_change(session, built):
    new = forget(session, built, "lab-x-06")
    assert [n["name"] for n in new["state"]["nodes"]] == [f"lab-x-0{i}" for i in range(1, 6)]
    assert all("lab-x-06" not in new[t] for t in ("placement", "addresses", "vm_ids"))
    change = new["change"]
    assert change["kind"] == "forget_nodes" and change["removed"] == ["lab-x-06"]
    assert change["nodes"]["lab-x-06"]["vm_id"] == built.desired["vm_ids"]["lab-x-06"] and new["node_counter"] == 6
    assert "nothing is destroyed" in change["describe"] and len(built.desired["state"]["nodes"]) == 6


def test_forgetting_needs_the_cluster_name_a_lost_node_and_the_quorum(session, built):
    with pytest.raises(OperationRefused, match="type the cluster name exactly"):
        forget(session, built, "lab-x-06", confirm="lab")
    with pytest.raises(OperationRefused, match="only 2 master-eligible nodes would remain"):
        forget(session, built, "lab-x-01")
    session.add(Vm(connection_id=built.desired["proxmox_connection_id"], pve_node="pve1",
                   vmid=built.desired["vm_ids"]["lab-x-06"], name="lab-x-06", status="running"))
    session.commit()
    with pytest.raises(OperationRefused, match=r"exists in Proxmox and is running.*not in the cluster is started or restarted "
                                               r"with Restart nodes first.*Remove nodes needs every node present"):
        forget(session, built, "lab-x-06")                                               # down: Remove nodes cannot take it out
    with pytest.raises(OperationRefused, match=r"lab-x-05 is in the cluster.*a node that is in the cluster is taken out with Remove nodes"):
        forget(session, built, "lab-x-05", es=FakeEs(state_of(built)))                    # in the cluster: it can


def test_the_host_spread_rule_applies_to_forgetting_a_master(session, five_masters):
    es = lost_es(five_masters, "lab-x-07")
    with pytest.raises(OperationRefused, match="would hold 2 of the 4 master-eligible nodes that remain"):
        forget(session, five_masters, "lab-x-07", es=es)


# -- the plan rules -----------------------------------------------------------------------------------------------------

def summary(*pairs):
    return PlanSummary([ResourceChange(a, act) for a, act in pairs])


def test_a_plan_that_creates_exactly_the_named_machines_passes_and_other_changes_are_refused():
    vm = 'module.node["lab-x-06"].proxmox_virtual_environment_vm.node'
    other = 'module.node["lab-x-01"].proxmox_virtual_environment_vm.node'
    assert check_rebuild_plan(summary((vm, "create"), (other, "update")), frozenset({"lab-x-06"})) == []
    out = check_rebuild_plan(summary((vm, "create"), (other, "delete"), ('module.node["lab-x-09"].vm', "create"),
                                     ('module.node["lab-x-02"].vm', "replace")), frozenset({"lab-x-06"}))
    assert len(out) == 3 and all("must only create the machines asked for" in o for o in out)


def test_a_rebuild_plan_that_creates_nothing_is_refused_because_the_machine_exists():
    out = check_rebuild_plan(summary(), frozenset({"lab-x-06"}))
    assert "does not create a machine for lab-x-06, so Terraform believes it exists" in out[0]
    assert check_rebuild_plan(summary(('module.node["lab-x-06"].vm', "update")), frozenset({"lab-x-06"}))


def test_a_forget_plan_must_touch_no_machine_and_says_to_remove_one_that_exists():
    assert check_forget_plan(summary(), frozenset({"lab-x-06"})) == []
    assert check_forget_plan(summary(('module.node["lab-x-01"].vm', "update")), frozenset({"lab-x-06"})) == []
    out = check_forget_plan(summary(('module.node["lab-x-06"].vm', "delete")), frozenset({"lab-x-06"}))
    assert "the machine of lab-x-06 still exists, so use Remove nodes" in out[0]
    out = check_forget_plan(summary(('module.node["lab-x-05"].vm', "delete"), ('module.node["lab-x-09"].vm', "create")),
                            frozenset({"lab-x-06"}))
    assert len(out) == 2 and all("must not touch any machine" in o for o in out)


def test_the_join_check_asks_for_yellow_only_when_rebuilding(tmp_path):
    from app.configmgmt.runner import AnsibleRequest, CliAnsibleRunner
    base = {"state": DesiredState.model_validate(state_of_fixture()), "addresses": {}, "kind": "add_node",
            "bootstrapped_at": None}
    for sub, rebuild_flag, want in (("a", True, "yellow"), ("b", False, "green")):
        (tmp_path / sub).mkdir()
        got = CliAnsibleRunner._join_vars(AnsibleRequest(**base, rebuild=rebuild_flag), tmp_path / sub)
        assert got["es_jc_min_status"] == want


def state_of_fixture():
    from app.desired import TopologyPreset, build_desired_state
    return build_desired_state(TopologyPreset.dedicated_masters, "lab-x", "9.5.6", data_nodes=2,
                               coordinating_nodes=1).model_dump(mode="json")
