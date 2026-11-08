# ruff: noqa: F811  (the fixtures are imported from the removal tests and used by name)
"""The rules for restarting nodes: which nodes, in what order, what is done to each, and what is refused. Against the same fake
Proxmox and fake Elasticsearch as the other lifecycle tests. Nothing here restarts anything."""
import pytest

from app.models import Vm
from app.provisioning.lifecycle import RestartNodes, plan_restart_nodes
from app.provisioning.operation import OperationRefused
from tests.test_create_cluster import pve  # noqa: F401  (a fixture)
from tests.test_remove_nodes import FakeEs, built, state_of  # noqa: F401  (fixtures and a fake)


def restart(session, cluster, *names, es=None):
    es = es or FakeEs(state_of(cluster))
    return plan_restart_nodes(session, cluster, RestartNodes(nodes=list(names) or None), es)


def down(cluster, *names, status="yellow", **kw):
    """Elasticsearch as it is when these nodes are not in the cluster."""
    es = FakeEs(state_of(cluster), status=status, **kw)
    es.hidden = set(names)
    return es


def vm_row(session, cluster, name, status):
    session.add(Vm(connection_id=cluster.desired["proxmox_connection_id"], pve_node="pve1",
                   vmid=cluster.desired["vm_ids"][name], name=name, status=status))
    session.commit()


# -- the plan ---------------------------------------------------------------------------------------------------------------------

def test_every_node_is_planned_in_the_rolling_restart_order_with_the_elected_master_last(session, built):
    new = restart(session, built)                                       # no names: all of them
    change = new["change"]
    # coordinating-only (06), data nodes (04, 05), then the masters with the elected one (01) last
    assert change["order"] == ["lab-x-06", "lab-x-04", "lab-x-05", "lab-x-02", "lab-x-03", "lab-x-01"]
    assert [change["nodes"][n]["position"] for n in change["order"]] == [1, 2, 3, 4, 5, 6]
    assert {i["action"] for i in change["nodes"].values()} == {"restart"}
    assert change["kind"] == "restart_nodes" and change["present"] == sorted(n.name for n in state_of(built).nodes)
    assert any("lab-x-01 is the elected master, so it goes last" in w for w in change["warnings"])
    assert "restart 6 nodes one at a time" in change["describe"]
    assert new["state"] == built.desired["state"] and "change" not in built.desired    # the record is not touched


def test_named_nodes_are_planned_alone_and_a_different_elected_master_changes_the_order(session, built):
    new = restart(session, built, "lab-x-03", "lab-x-04", es=FakeEs(state_of(built), elected="lab-x-03"))
    assert new["change"]["order"] == ["lab-x-04", "lab-x-03"]
    assert new["change"]["nodes"]["lab-x-04"]["host"] == built.desired["placement"]["lab-x-04"]
    assert new["change"]["nodes"]["lab-x-04"]["vm_id"] == built.desired["vm_ids"]["lab-x-04"]


def test_the_host_shown_is_where_proxmox_last_saw_the_machine_not_where_ecm_first_put_it(session, built):
    recorded = built.desired["placement"]["lab-x-04"]
    row = Vm(connection_id=built.desired["proxmox_connection_id"], pve_node="pve9", vmid=built.desired["vm_ids"]["lab-x-04"],
             name="lab-x-04", status="running")
    session.add(row)
    session.commit()
    new = restart(session, built, "lab-x-04", "lab-x-05")
    assert new["change"]["nodes"]["lab-x-04"]["host"] == "pve9" != recorded              # moved: the sync saw it elsewhere
    assert new["change"]["nodes"]["lab-x-05"]["host"] == built.desired["placement"]["lab-x-05"]   # no row: the record


def test_a_node_the_only_copy_of_a_shard_is_on_gets_a_warning(session, built):
    es = FakeEs(state_of(built), shards=[("solo", 0, "lab-x-04"), ("logs", 0, "lab-x-04"), ("logs", 0, "lab-x-05")])
    new = restart(session, built, "lab-x-04", "lab-x-05", es=es)
    assert any("lab-x-04 holds the only copy of 1 shard (solo[0]); those indices are unavailable while it restarts" in w
               for w in new["change"]["warnings"])
    assert not any("lab-x-05 holds the only copy" in w for w in new["change"]["warnings"])


# -- nodes that are down -----------------------------------------------------------------------------------------------------------

def test_a_node_with_a_stopped_vm_is_started_and_goes_first_even_when_named_last(session, built):
    vm_row(session, built, "lab-x-04", "stopped")
    new = restart(session, built, "lab-x-05", "lab-x-04", es=down(built, "lab-x-04"))
    assert new["change"]["order"] == ["lab-x-04", "lab-x-05"]
    assert (new["change"]["nodes"]["lab-x-04"]["action"], new["change"]["nodes"]["lab-x-05"]["action"]) == ("start", "restart")
    assert new["change"]["describe"].startswith("bring back lab-x-04, which is not in the cluster, then restart 1 node one at a time (lab-x-05)")


def test_a_node_that_is_not_in_the_cluster_but_whose_vm_runs_is_restarted(session, built):
    vm_row(session, built, "lab-x-04", "running")
    new = restart(session, built, "lab-x-04", es=down(built, "lab-x-04"))
    assert new["change"]["nodes"]["lab-x-04"]["action"] == "restart" and new["change"]["order"] == ["lab-x-04"]
    assert new["change"]["describe"] == "bring back lab-x-04, which is not in the cluster"      # only a node that is down: no cautions about masters


def test_a_red_cluster_allows_starting_the_nodes_that_are_down_and_nothing_else(session, built):
    vm_row(session, built, "lab-x-04", "stopped")
    assert restart(session, built, "lab-x-04", es=down(built, "lab-x-04", status="red"))["change"]["order"] == ["lab-x-04"]
    with pytest.raises(OperationRefused, match="the cluster is red, so no node is restarted: start the nodes that are down first"):
        restart(session, built, "lab-x-04", "lab-x-05", es=down(built, "lab-x-04", status="red"))


# -- refusals ---------------------------------------------------------------------------------------------------------------------

def test_a_node_that_is_not_in_the_cluster_and_has_no_machine_is_lost_not_restarted(session, built):
    with pytest.raises(OperationRefused, match=r"lab-x-04 is not in the cluster and its machine \(VM 503\) is not in Proxmox: it is lost"):
        restart(session, built, "lab-x-04", es=down(built, "lab-x-04"))


def test_a_vmid_that_now_belongs_to_another_machine_is_refused(session, built):
    vm_row(session, built, "lab-x-04", "running")
    row = session.query(Vm).filter(Vm.vmid == built.desired["vm_ids"]["lab-x-04"]).one()
    row.name = "stranger"
    session.commit()
    with pytest.raises(OperationRefused, match="which was lab-x-04's, now belongs to a machine named stranger"):
        restart(session, built, "lab-x-04", es=down(built, "lab-x-04"))


def test_another_node_being_down_must_be_named_too(session, built):
    with pytest.raises(OperationRefused, match="Elasticsearch does not report lab-x-05, which are not in this request"):
        restart(session, built, "lab-x-04", es=down(built, "lab-x-05"))


def test_a_yellow_cluster_with_nothing_down_is_refused_and_a_cluster_with_no_master_too(session, built):
    with pytest.raises(OperationRefused, match="the cluster is yellow, and a node is restarted only from a green cluster"):
        restart(session, built, "lab-x-04", es=FakeEs(state_of(built), status="yellow"))
    es = FakeEs(state_of(built))
    es.elected = ""
    with pytest.raises(OperationRefused, match="no elected master.*quorum loss"):
        restart(session, built, "lab-x-04", es=es)


def test_unknown_duplicate_and_single_node_requests_are_refused(session, built):
    with pytest.raises(OperationRefused, match="no node named lab-x-99"):
        restart(session, built, "lab-x-99")
    with pytest.raises(ValueError, match="twice"):
        RestartNodes(nodes=["a", "a"])
    with pytest.raises(ValueError):
        RestartNodes(nodes=[])
    state = state_of(built)
    only = state.nodes[0].model_copy(update={"roles_mode": "default", "roles": [], "data_disk_gb": 100})
    es = FakeEs(state)
    built.desired = {**built.desired, "state": state.model_copy(update={"nodes": [only]}).model_dump(mode="json")}
    with pytest.raises(OperationRefused, match="single-node cluster: it would be down while its machine restarts"):
        restart(session, built, "lab-x-01", es=es)


def test_a_cluster_ecm_cannot_reach_is_refused(session, built):
    built.credential_id, built.endpoint_urls = None, None
    with pytest.raises(OperationRefused, match="no way to reach this cluster"):
        plan_restart_nodes(session, built, RestartNodes(nodes=["lab-x-04"]))
