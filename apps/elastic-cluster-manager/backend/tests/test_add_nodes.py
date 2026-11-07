"""The rules for adding nodes to a built cluster, against the same fake Proxmox the create tests use and a cluster planned
by the real create path (so its addresses, VMIDs and hosts are the ones a create gives)."""
from datetime import UTC, datetime

import pytest

from app.desired import TopologyPreset
from app.models import EsNode, Vm
from app.provisioning.lifecycle import AddNodes, plan_add_nodes
from app.provisioning.operation import OperationRefused
from tests.test_create_cluster import plan, pve  # noqa: F401  (pve is a fixture)


@pytest.fixture
def built(session, pve):  # noqa: F811
    """A built cluster: three dedicated masters, two data nodes and one coordinating node, spread over three hosts."""
    cluster, op, _ = plan(session, name="lab-x", preset=TopologyPreset.dedicated_masters, data_nodes=2,
                          coordinating_nodes=1, dry_run=False)
    op.state, op.finished_at = "succeeded", datetime.now(UTC)
    cluster.bootstrapped_at, cluster.desired, cluster.health_status = datetime.now(UTC), op.params, "green"
    session.commit()
    return cluster


def names(params):
    return [n["name"] for n in params["state"]["nodes"]]


def test_a_data_node_gets_the_next_name_a_host_an_address_and_a_vmid_and_copies_the_sizes_of_its_kind(session, built):
    new = plan_add_nodes(session, built, AddNodes(roles=["data", "ingest"]))
    assert names(new)[-1] == "lab-x-07" and len(names(new)) == 7
    added = next(n for n in new["state"]["nodes"] if n["name"] == "lab-x-07")
    assert (added["roles_mode"], added["roles"]) == ("custom", ["data", "ingest"])
    assert (added["cores"], added["ram_mb"], added["data_disk_gb"]) == (4, 8192, 100)       # as the existing data nodes
    change = new["change"]
    assert change["kind"] == "add_node" and change["added"] == ["lab-x-07"]
    info = change["nodes"]["lab-x-07"]
    assert info["host"] in ("pve1", "pve2", "pve3") and new["placement"]["lab-x-07"] == info["host"]
    assert info["address"] == new["addresses"]["lab-x-07"] and info["address"] not in built.desired["addresses"].values()
    assert info["vm_id"] == new["vm_ids"]["lab-x-07"] and info["vm_id"] not in built.desired["vm_ids"].values()
    assert "add 1 node (lab-x-07) with data, ingest" in change["describe"]
    assert new["state"]["topology_preset"] == "custom" and new["node_counter"] == 7
    assert len(built.desired["state"]["nodes"]) == 6                                         # the record is not touched


def test_several_nodes_of_one_kind_are_added_together_with_their_own_names_addresses_and_vmids(session, built):
    new = plan_add_nodes(session, built, AddNodes(count=3, roles=["ml"], cores=8, ram_mb=16384))
    assert names(new)[-3:] == ["lab-x-07", "lab-x-08", "lab-x-09"]
    added = new["state"]["nodes"][-3:]
    assert {(n["roles_mode"], tuple(n["roles"]), n["cores"], n["ram_mb"], n["data_disk_gb"]) for n in added} == {
        ("custom", ("ml",), 8, 16384, None)}                                                  # ml holds no data
    assert len({new["addresses"][n] for n in names(new)}) == 9 and len({new["vm_ids"][n] for n in names(new)}) == 9
    assert new["change"]["added"] == ["lab-x-07", "lab-x-08", "lab-x-09"] and new["node_counter"] == 9


def test_default_roles_and_coordinating_only_are_both_expressible(session, built):
    default = plan_add_nodes(session, built, AddNodes(count=2))                  # master-eligible: two keep the quorum rule
    assert {n["roles_mode"] for n in default["state"]["nodes"][-2:]} == {"default"}
    assert "with the default roles" in default["change"]["describe"]
    coordinating = plan_add_nodes(session, built, AddNodes(roles=[]))
    node = coordinating["state"]["nodes"][-1]
    assert node["roles_mode"] == "coordinating" and node["data_disk_gb"] is None
    assert "no roles (coordinating only)" in coordinating["change"]["describe"]


def test_a_node_number_is_never_reused(session, built):
    built.desired["node_counter"] = 12                                                       # nodes up to 12 once existed
    assert names(plan_add_nodes(session, built, AddNodes(roles=["data"])))[-1] == "lab-x-13"


def test_the_roles_must_be_real_roles_and_voting_only_needs_master():
    for bad in (["nonsense"], ["data", "data"], ["voting_only"]):
        with pytest.raises(ValueError):
            AddNodes(roles=bad)
    AddNodes(roles=["master", "voting_only"])


def test_roles_that_hold_no_data_refuse_a_data_disk_and_roles_that_do_get_a_default_one(session, built):
    with pytest.raises(OperationRefused, match="hold no data, so they get no data disk"):
        plan_add_nodes(session, built, AddNodes(roles=["ml"], data_disk_gb=200))
    new = plan_add_nodes(session, built, AddNodes(roles=["data_hot"]))
    assert new["state"]["nodes"][-1]["data_disk_gb"] == 100


def test_a_pinned_host_is_used_and_an_unknown_one_is_refused(session, built):
    assert plan_add_nodes(session, built, AddNodes(roles=["data"], pve_node="pve3"))["placement"]["lab-x-07"] == "pve3"
    with pytest.raises(OperationRefused):
        plan_add_nodes(session, built, AddNodes(roles=["data"], pve_node="pve9"))


def test_one_more_master_on_three_hosts_with_three_masters_is_refused_because_four_need_four_hosts(session, built):
    with pytest.raises(OperationRefused, match="At least 4 hosts must each take master-eligible nodes"):
        plan_add_nodes(session, built, AddNodes())                    # default roles are master-eligible: a fourth master


def test_a_master_that_would_break_the_quorum_rule_is_refused_with_the_reason(session, built):
    # Four master-eligible nodes allow one per host; a fourth on a host that already holds one is refused.
    holder = built.desired["placement"]["lab-x-01"]
    with pytest.raises(OperationRefused, match="master"):
        plan_add_nodes(session, built, AddNodes(roles=["master"], pve_node=holder))


def test_an_even_number_of_masters_is_allowed_with_a_warning(session, built):
    new = plan_add_nodes(session, built, AddNodes(count=3, roles=["master"]))               # six masters, two per host
    assert any("even number" in w for w in new["change"]["warnings"])
    hosts = [new["placement"][n] for n in names(new) if n in new["change"]["added"] or n in names(built.desired)[:3]]
    assert max(hosts.count(h) for h in set(hosts)) == 2


def test_a_cluster_that_is_not_green_or_not_complete_at_its_last_sync_is_refused(session, built):
    built.health_status = "yellow"
    with pytest.raises(OperationRefused, match="was yellow at its last sync"):
        plan_add_nodes(session, built, AddNodes())
    built.health_status = "green"
    for i in range(1, 5):
        session.add(EsNode(cluster_id=built.id, es_node_id=f"id{i}", name=f"lab-x-0{i}"))
    session.commit()
    with pytest.raises(OperationRefused, match="saw 4 of this cluster's 6 nodes"):
        plan_add_nodes(session, built, AddNodes())


def test_a_single_node_cluster_cannot_be_grown(session, pve):  # noqa: F811
    cluster, op, _ = plan(session, name="solo", preset=TopologyPreset.single_node, dry_run=False)
    cluster.bootstrapped_at, cluster.desired = datetime.now(UTC), op.params
    session.commit()
    with pytest.raises(OperationRefused, match="single-node cluster.*cannot take other nodes"):
        plan_add_nodes(session, cluster, AddNodes())


def test_an_address_or_vmid_held_by_another_cluster_is_not_given_out(session, built):
    resolved = plan(session, name="lab-y", preset=TopologyPreset.three_node, dry_run=False)[2]   # in flight
    new = plan_add_nodes(session, built, AddNodes(roles=["data"]))
    assert new["addresses"]["lab-x-07"] not in resolved.addresses.values()
    assert new["vm_ids"]["lab-x-07"] not in resolved.vm_ids.values()


def test_a_name_already_taken_by_a_machine_is_refused(session, built):
    session.add(Vm(connection_id=built.desired["proxmox_connection_id"], pve_node="pve1", vmid=999,
                   name="lab-x-07", status="running"))
    session.commit()
    with pytest.raises(OperationRefused, match="lab-x-07"):
        plan_add_nodes(session, built, AddNodes())


def test_a_cluster_that_is_not_built_cannot_have_nodes_added(session, pve):  # noqa: F811
    cluster = plan(session, name="half", preset=TopologyPreset.three_node, dry_run=False)[0]
    with pytest.raises(OperationRefused, match="not finished being built"):
        plan_add_nodes(session, cluster, AddNodes())


def test_the_request_is_bounded():
    for bad in ({"count": 0}, {"count": 11}, {"cores": 0}, {"ram_mb": 1024}, {"pve_node": ""}):
        with pytest.raises(ValueError):
            AddNodes(**bad)
