"""The rules for removing nodes from a built cluster: the three refusals the plan requires (quorum, disk, the last copy
of a shard) and the others the design lists, against the same fake Proxmox the create tests use and a fake Elasticsearch
that answers the read-only calls the check makes. Nothing here drains a node or destroys a machine."""
from datetime import UTC, datetime

import pytest

from app.desired import TopologyPreset
from app.desired.models import DesiredState
from app.provisioning.lifecycle import (
    AddNodes,
    RemoveNodes,
    _quorum_problems,
    plan_add_nodes,
    plan_remove_nodes,
)
from app.provisioning.operation import OperationRefused
from app.provisioning.plan import PlanSummary, ResourceChange, check_removal_plan, node_of
from tests.test_create_cluster import plan, pve  # noqa: F401  (pve is a fixture)

GIB = 1024 ** 3


class FakeEs:
    """What the read-only calls return for a cluster whose nodes are `state.nodes`. `shards` is a list of
    (index, shard, node) started copies; `used` is GiB used per node (default 10) on a 100 GiB disk."""

    def __init__(self, state: DesiredState, shards=None, used=None, status="green", elected=None, settings=None,
                 total_gib=100):
        self.state, self.status, self.settings_body = state, status, settings or {}
        self.elected = elected or next(n.name for n in state.nodes if n.is_electable)
        self.shard_rows = [{"index": i, "shard": str(s), "prirep": "p", "state": "STARTED", "node": n, "store": str(GIB)}
                           for i, s, n in (shards or [])]
        self.used, self.total = used or {}, total_gib
        self.extra_rows: list[dict] = []
        self.hidden: set[str] = set()                     # nodes the cluster does not report (not present)

    def _present(self):
        return [n for n in self.state.nodes if n.name not in self.hidden]

    def health(self):
        return {"status": self.status, "number_of_nodes": len(self._present())}

    def nodes(self):
        return {"nodes": {f"id-{n.name}": {"name": n.name, "roles": sorted(n.effective_roles)} for n in self._present()}}

    def nodes_stats(self):
        return {"nodes": {f"id-{n.name}": {"fs": {"total": {
            "total_in_bytes": self.total * GIB,
            "available_in_bytes": (self.total - self.used.get(n.name, 10)) * GIB}}} for n in self._present()}}

    def shards_sized(self):
        return [*self.shard_rows, *self.extra_rows]

    def settings(self):
        return self.settings_body

    def master(self):
        return [{"node": self.elected}]


@pytest.fixture
def built(session, pve):  # noqa: F811
    """Three dedicated masters (lab-x-01..03), two data nodes (04, 05) and a coordinating node (06), over three hosts."""
    cluster, op, _ = plan(session, name="lab-x", preset=TopologyPreset.dedicated_masters, data_nodes=2,
                          coordinating_nodes=1, dry_run=False)
    op.state, op.finished_at = "succeeded", datetime.now(UTC)
    cluster.bootstrapped_at, cluster.desired, cluster.health_status = datetime.now(UTC), op.params, "green"
    session.commit()
    return cluster


def state_of(cluster) -> DesiredState:
    return DesiredState.model_validate(cluster.desired["state"])


def ask(session, cluster, *names, es=None, confirm=None):
    es = es or FakeEs(state_of(cluster))
    return plan_remove_nodes(session, cluster, RemoveNodes(nodes=list(names), confirm_name=confirm or cluster.name), es)


@pytest.fixture
def five_masters(session, built):
    """The test cluster's shape: three dedicated masters plus two master-eligible default-role nodes."""
    grown = plan_add_nodes(session, built, AddNodes(count=2))
    built.desired = {k: v for k, v in grown.items() if k != "change"}
    session.commit()
    return built


# -- what a removal produces ------------------------------------------------------------------------------------------

def test_removing_a_coordinating_node_takes_it_out_of_the_record_and_keeps_its_details_in_the_change(session, built):
    es = FakeEs(state_of(built), shards=[("logs", 0, "lab-x-04"), ("logs", 0, "lab-x-05")])
    new = ask(session, built, "lab-x-06", es=es)
    assert [n["name"] for n in new["state"]["nodes"]] == [f"lab-x-0{i}" for i in range(1, 6)]
    assert "lab-x-06" not in new["placement"] and "lab-x-06" not in new["addresses"] and "lab-x-06" not in new["vm_ids"]
    change = new["change"]
    assert change["kind"] == "remove_nodes" and change["removed"] == ["lab-x-06"]
    gone = change["nodes"]["lab-x-06"]
    assert gone["vm_id"] == built.desired["vm_ids"]["lab-x-06"] and gone["host"] == built.desired["placement"]["lab-x-06"]
    assert gone["address"] == built.desired["addresses"]["lab-x-06"] and gone["shards"] == 0
    assert new["node_counter"] == 6 and new["state"]["topology_preset"] == "custom"
    assert len(built.desired["state"]["nodes"]) == 6                                    # the record is not touched


def test_a_data_node_with_a_replicated_shard_can_go_and_the_plan_says_how_much_data_moves(session, five_masters):
    es = FakeEs(state_of(five_masters), shards=[("logs", 0, "lab-x-04"), ("logs", 0, "lab-x-05")])
    new = ask(session, five_masters, "lab-x-04", es=es)
    assert new["change"]["nodes"]["lab-x-04"]["shards"] == 1 and new["change"]["nodes"]["lab-x-04"]["data_bytes"] == GIB


def test_a_two_data_node_cluster_cannot_lose_one_while_a_shard_has_two_copies(session, built):
    es = FakeEs(state_of(built), shards=[("logs", 0, "lab-x-04"), ("logs", 0, "lab-x-05")])
    with pytest.raises(OperationRefused, match=r"logs keep more copies of each shard than the 1 data node"):
        ask(session, built, "lab-x-04", es=es)


def test_the_elected_master_may_be_removed_with_a_warning_when_others_remain(session, five_masters):
    es = FakeEs(state_of(five_masters), elected="lab-x-07")
    new = ask(session, five_masters, "lab-x-07", "lab-x-08", es=es)
    assert any("lab-x-07 is the elected master" in w for w in new["change"]["warnings"])


# -- the nodes and the confirmation -----------------------------------------------------------------------------------

def test_the_cluster_name_must_be_typed_and_the_nodes_must_exist(session, built):
    with pytest.raises(OperationRefused, match="type the cluster name exactly"):
        ask(session, built, "lab-x-06", confirm="lab")
    with pytest.raises(OperationRefused, match="no node named lab-x-99"):
        ask(session, built, "lab-x-99")


def test_a_node_cannot_be_listed_twice():
    with pytest.raises(ValueError, match="twice"):
        RemoveNodes(nodes=["a", "a"], confirm_name="x")


def test_a_cluster_that_is_not_built_or_has_no_record_is_refused(session, built):
    es = FakeEs(state_of(built))
    built.desired = None
    with pytest.raises(OperationRefused, match="no record"):
        ask(session, built, "lab-x-06", es=es)
    built.desired, built.bootstrapped_at = {"state": {}}, None
    with pytest.raises(OperationRefused, match="has not finished being built"):
        ask(session, built, "lab-x-06", es=es)


# -- refusal 1: quorum -------------------------------------------------------------------------------------------------

def test_removing_a_master_from_three_is_refused_because_fewer_than_three_would_remain(session, built):
    with pytest.raises(OperationRefused, match="only 2 master-eligible nodes would remain"):
        ask(session, built, "lab-x-01")


def test_the_message_says_it_is_the_only_master_when_it_is(session, built):
    state = state_of(built)
    solo = state.model_copy(update={"nodes": [n for n in state.nodes if n.name not in ("lab-x-02", "lab-x-03")]})
    problems = _quorum_problems(solo, [solo.nodes[0]], {})      # not reachable through the API: the rule reads numbers
    assert "it is the only master-eligible node" in problems[0]


def test_one_master_of_five_is_refused_wherever_it_is_because_a_host_would_hold_too_many(session, five_masters):
    for name in ("lab-x-01", "lab-x-07", "lab-x-08"):
        with pytest.raises(OperationRefused, match="would hold 2 of the 4 master-eligible nodes that remain"):
            ask(session, five_masters, name)


def test_two_masters_of_five_are_accepted_when_three_remain_on_three_hosts(session, five_masters):
    new = ask(session, five_masters, "lab-x-07", "lab-x-08")
    left = DesiredState.model_validate(new["state"])
    assert [n.name for n in left.master_eligible_nodes] == ["lab-x-01", "lab-x-02", "lab-x-03"]
    assert set(new["change"]["removed"]) == {"lab-x-07", "lab-x-08"}


def test_taking_half_or_more_of_the_masters_out_at_once_is_refused(session, five_masters):
    with pytest.raises(OperationRefused, match="only 2 master-eligible nodes would remain"):
        ask(session, five_masters, "lab-x-01", "lab-x-02", "lab-x-07")
    state = state_of(five_masters)
    six = state.model_copy(update={"nodes": [*state.nodes, state.nodes[-1].model_copy(update={"name": "lab-x-09"})]})
    gone = [n for n in six.nodes if n.name in ("lab-x-01", "lab-x-02", "lab-x-03")]     # 3 of 6 masters: left is 3
    assert "fewer than half" in _quorum_problems(six, gone, {})[0]


def test_a_cluster_cannot_be_shrunk_to_one_node(session, built):
    state = state_of(built)
    assert "single node" in _quorum_problems(state, state.nodes[:-1], {})[0]


def test_a_cluster_left_with_no_data_node_is_refused(session, built):
    with pytest.raises(OperationRefused, match="at least one node that holds data"):
        ask(session, built, "lab-x-04", "lab-x-05")


# -- refusal 2: disk -------------------------------------------------------------------------------------------------

def test_data_that_will_not_fit_below_the_low_watermark_is_refused_with_the_figures(session, built):
    es = FakeEs(state_of(built), used={"lab-x-04": 60, "lab-x-05": 70})                  # 130 GiB to hold on one 100 GiB disk
    with pytest.raises(OperationRefused, match=r"the 60\.0 GiB on the removed nodes would take them to 130%, past the 85%"):
        ask(session, built, "lab-x-04", es=es)


def test_data_that_fits_is_accepted_and_the_clusters_own_watermark_is_used(session, built):
    es = FakeEs(state_of(built), used={"lab-x-04": 30, "lab-x-05": 40})                 # 70 of 100 after: 70%
    ask(session, built, "lab-x-04", es=es)
    es = FakeEs(state_of(built), used={"lab-x-04": 30, "lab-x-05": 40}, settings={"persistent": {
        "cluster.routing.allocation.disk.watermark.low": "60%"}})
    with pytest.raises(OperationRefused, match="past the 60% low disk watermark"):
        ask(session, built, "lab-x-04", es=es)


def test_a_watermark_in_bytes_is_not_understood_so_the_default_is_used_and_the_plan_says_so(session, built):
    es = FakeEs(state_of(built), settings={"persistent": {"cluster.routing.allocation.disk.watermark.low": "100gb"}})
    new = ask(session, built, "lab-x-04", es=es)
    assert any("ECM cannot read as a share of a disk" in w for w in new["change"]["warnings"])


# -- refusal 3: the last copy of a shard --------------------------------------------------------------------------------

def test_the_only_copy_of_a_shard_on_a_node_being_removed_is_refused_and_named(session, built):
    es = FakeEs(state_of(built), shards=[("logs", 0, "lab-x-04"), ("logs", 0, "lab-x-05"), ("solo", 0, "lab-x-04")])
    with pytest.raises(OperationRefused, match=r"the only copy of 1 shard is on a node being removed \(solo\[0\]\)"):
        ask(session, built, "lab-x-04", es=es)


def test_removing_both_nodes_that_hold_the_two_copies_of_a_shard_is_refused_too(session, five_masters):
    state = state_of(five_masters)
    es = FakeEs(state, shards=[("logs", 0, "lab-x-07"), ("logs", 0, "lab-x-08")])
    with pytest.raises(OperationRefused, match=r"logs\[0\]"):
        ask(session, five_masters, "lab-x-07", "lab-x-08", es=es)


def test_more_copies_than_data_nodes_would_remain_is_refused(session, five_masters):
    state = state_of(five_masters)
    data = [n.name for n in state.nodes if n.holds_data]                                  # 04, 05, 07, 08
    es = FakeEs(state, shards=[("wide", 0, n) for n in data])                              # four copies of one shard
    with pytest.raises(OperationRefused, match=r"wide keep more copies of each shard than the 2 data nodes"):
        ask(session, five_masters, "lab-x-07", "lab-x-08", es=es)


def test_a_shard_that_is_not_started_refuses_the_removal(session, built):
    es = FakeEs(state_of(built))
    es.extra_rows = [{"index": "logs", "shard": "0", "prirep": "r", "state": "UNASSIGNED", "node": None, "store": None}]
    with pytest.raises(OperationRefused, match=r"1 shard copy is not started \(logs\[0\]\)"):
        ask(session, built, "lab-x-06", es=es)


# -- the cluster as it is now, and the other refusals --------------------------------------------------------------------

def test_a_cluster_that_is_not_green_or_is_missing_a_node_is_refused(session, built):
    with pytest.raises(OperationRefused, match="the cluster is yellow"):
        ask(session, built, "lab-x-06", es=FakeEs(state_of(built), status="yellow"))
    es = FakeEs(state_of(built))
    es.hidden = {"lab-x-05"}
    with pytest.raises(OperationRefused, match="has 5 nodes and ECM expects 6"):
        ask(session, built, "lab-x-06", es=es)


def live_roles(state, **roles):
    """The state as the cluster reports it, with some nodes given other roles (the record is not touched)."""
    return state.model_copy(update={"nodes": [
        n.model_copy(update={"roles_mode": "custom", "roles": roles[n.name]}) if n.name in roles else n
        for n in state.nodes]})


def test_the_last_node_with_a_data_tier_is_refused(session, five_masters):
    live = live_roles(state_of(five_masters), **{"lab-x-04": ["data_hot"], "lab-x-05": ["data_cold"],
                                                  "lab-x-07": ["data_hot"], "lab-x-08": ["data_hot"]})
    shards = [("logs", 0, "lab-x-05"), ("logs", 0, "lab-x-04")]
    with pytest.raises(OperationRefused, match="lab-x-05 is the last node with the data_cold role and holds shards"):
        ask(session, five_masters, "lab-x-05", es=FakeEs(live, shards=shards))
    # with no shards on it nothing is stranded, so it is only a warning
    new = ask(session, five_masters, "lab-x-05", es=FakeEs(live))
    assert "no node with the data_cold role would remain" in new["change"]["warnings"]
    # a node with the general `data` role holds every tier, so the same removal is fine when one remains
    only_cold = live_roles(state_of(five_masters), **{"lab-x-05": ["data_cold"]})   # 04, 07 and 08 keep `data`
    assert not any("data_cold" in w for w in ask(session, five_masters, "lab-x-05", es=FakeEs(only_cold, shards=shards))
                   ["change"]["warnings"])


def test_the_last_node_with_a_soft_role_only_warns(session, built):
    live = live_roles(state_of(built), **{"lab-x-06": ["ml"]})
    new = ask(session, built, "lab-x-06", es=FakeEs(live))
    assert "no node with the ml role would remain" in new["change"]["warnings"]


def test_a_cluster_ecm_cannot_reach_is_refused(session, built):
    built.credential_id, built.endpoint_urls = None, None
    with pytest.raises(OperationRefused, match="no way to reach this cluster"):
        plan_remove_nodes(session, built, RemoveNodes(nodes=["lab-x-06"], confirm_name="lab-x"))


# -- the plan rule ------------------------------------------------------------------------------------------------------

def summary(*pairs):
    return PlanSummary([ResourceChange(a, act) for a, act in pairs])


def test_a_node_is_matched_by_its_whole_instance_name_never_by_a_prefix():
    assert node_of('module.node["lab-x-1"].proxmox_virtual_environment_vm.this') == "lab-x-1"
    assert node_of('module.node["lab-x-10"].proxmox_virtual_environment_vm.this') == "lab-x-10"
    assert node_of('module.node["lab-x-1"]') == "lab-x-1" and node_of("proxmox_virtual_environment_pool.ecm") is None


def test_a_plan_that_deletes_exactly_the_named_node_passes():
    p = summary(('module.node["lab-x-06"].proxmox_virtual_environment_vm.this', "delete"),
                ('module.node["lab-x-01"].proxmox_virtual_environment_vm.this', "update"))
    assert check_removal_plan(p, frozenset({"lab-x-06"})) == []


def test_a_plan_that_deletes_a_node_that_was_not_named_or_replaces_or_creates_is_refused():
    out = check_removal_plan(summary(('module.node["lab-x-06"].vm', "delete"), ('module.node["lab-x-05"].vm', "delete"),
                                     ('module.node["lab-x-04"].vm', "replace"), ('module.node["lab-x-09"].vm', "create")),
                             frozenset({"lab-x-06"}))
    assert len(out) == 3 and any("delete" in o and "lab-x-05" in o for o in out)


def test_a_plan_that_does_not_delete_a_named_node_or_has_no_changes_is_refused():
    assert "does not delete lab-x-06" in check_removal_plan(summary(), frozenset({"lab-x-06"}))[0]
    p = summary(('module.node["lab-x-06"].vm', "delete"))
    assert check_removal_plan(p, frozenset({"lab-x-06", "lab-x-0"}))[0].startswith("the plan does not delete lab-x-0")


def test_a_node_whose_name_starts_with_a_named_one_is_not_deleted_by_naming_the_shorter():
    p = summary(('module.node["lab-x-10"].vm', "delete"))
    out = check_removal_plan(p, frozenset({"lab-x-1"}))
    assert any("lab-x-10" in o for o in out) and any("does not delete lab-x-1" in o for o in out)
