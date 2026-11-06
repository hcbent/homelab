from collections import Counter

from app.desired import NodeSpec, RolesMode, TopologyPreset, build_desired_state
from app.desired.models import DesiredState
from app.desired.placement import (
    GIB,
    Datastore,
    HostView,
    PlacementConfig,
    host_views_from_rows,
    recommend_placement,
)


def host(name, *, mem_used_gib=10, mem_gib=187, cores=40, committed_vcpus=0, committed_mem_gib=0,
         shared=True, tank_avail_gib=16000, online=True, datastore="tank") -> HostView:
    stores = {}
    if datastore:
        stores[datastore] = Datastore(datastore, shared, tank_avail_gib * GIB, 16000 * GIB)
    return HostView(name=name, online=online, cores=cores, mem_total=mem_gib * GIB,
                    mem_used=mem_used_gib * GIB, committed_vcpus=committed_vcpus,
                    committed_mem=committed_mem_gib * GIB, datastores=stores)


def three_hosts(**kw):
    return [host("pve1", **kw), host("pve2", **kw), host("pve3", **kw)]


def three_node() -> DesiredState:
    return build_desired_state(TopologyPreset.three_node, "lab-b", "9.4.3")


# ---- anti-affinity -------------------------------------------------------------------------------

def test_three_master_eligible_nodes_land_on_three_different_hosts():
    got = recommend_placement(three_node(), three_hosts())
    assert got.ok and got.quorum_safe and got.issues == []
    assert sorted(got.hosts.values()) == ["pve1", "pve2", "pve3"]


def test_spreading_beats_a_better_score():
    hosts = [host("pve1", mem_used_gib=1), host("pve2", mem_used_gib=150), host("pve3", mem_used_gib=150)]
    got = recommend_placement(three_node(), hosts)
    assert sorted(got.hosts.values()) == ["pve1", "pve2", "pve3"]    # not three on the emptiest host


def test_a_non_master_node_prefers_the_host_with_the_most_headroom():
    nodes = [NodeSpec(name=f"lab-b-0{i}", data_disk_gb=100) for i in (1, 2, 3)]
    nodes.append(NodeSpec(name="lab-b-04", roles_mode=RolesMode.coordinating))
    state = DesiredState(name="lab-b", version="9.4.3", nodes=nodes)
    hosts = [host("pve1", mem_used_gib=100), host("pve2", mem_used_gib=100), host("pve3", mem_used_gib=5)]
    got = recommend_placement(state, hosts)
    assert got.hosts["lab-b-04"] == "pve3"


def test_existing_masters_are_taken_into_account():
    got = recommend_placement(three_node(), three_hosts(), existing_master_counts={"pve1": 2})
    assert got.ok and "pve1" not in got.hosts.values()


# ---- pinning -------------------------------------------------------------------------------------

def test_pinned_nodes_are_honoured():
    state = three_node()
    state.nodes[0].pve_node = "pve3"
    got = recommend_placement(state, three_hosts())
    assert got.hosts["lab-b-01"] == "pve3"
    assert sorted(got.hosts.values()) == ["pve1", "pve2", "pve3"]    # the others still spread


def test_a_pin_that_does_not_fit_is_an_error_naming_the_reason():
    state = three_node()
    state.nodes[0].pve_node = "pve2"
    hosts = [host("pve1"), host("pve2", mem_gib=8, mem_used_gib=1), host("pve3")]
    got = recommend_placement(state, hosts)
    assert not got.ok
    err = next(i for i in got.issues if i.node == "lab-b-01")
    assert "not enough free RAM" in err.message and "pve2" in err.message


def test_pinning_to_an_unknown_host_is_an_error():
    state = three_node()
    state.nodes[0].pve_node = "pve9"
    got = recommend_placement(state, three_hosts())
    assert not got.ok and "not a known host" in got.issues[0].message


# ---- hard limits ---------------------------------------------------------------------------------

def test_not_enough_ram_is_reported_per_host():
    got = recommend_placement(three_node(), three_hosts(mem_gib=8, mem_used_gib=1))
    assert not got.ok and got.assignments == {}
    assert all("not enough free RAM" in i.message for i in got.issues)


def test_configured_memory_counts_even_when_actual_use_is_low():
    # nothing reports as used, but running VMs have 180 GiB configured on each host
    hosts = three_hosts(mem_used_gib=1, committed_mem_gib=180)
    got = recommend_placement(three_node(), hosts)
    assert not got.ok and "not enough free RAM" in got.issues[0].message


def test_vcpu_overcommit_limit():
    hosts = three_hosts(cores=4, committed_vcpus=8)         # 4 cores x 2.0 = 8, already full
    got = recommend_placement(three_node(), hosts)
    assert not got.ok and "not enough vCPU room" in got.issues[0].message
    relaxed = recommend_placement(three_node(), hosts, PlacementConfig(cpu_overcommit=4.0))
    assert relaxed.ok


def test_shared_datastore_is_counted_once_across_hosts():
    # each node needs 132 GiB (32 OS + 100 data); one shared pool with 250 GiB fits only one of them
    got = recommend_placement(three_node(), three_hosts(tank_avail_gib=250, shared=True))
    assert not got.ok and len(got.assignments) == 1
    assert all("not enough free disk" in i.message for i in got.issues)


def test_host_local_datastores_are_counted_per_host():
    got = recommend_placement(three_node(), three_hosts(tank_avail_gib=150, shared=False))
    assert got.ok and len(got.assignments) == 3


def test_coordinating_nodes_need_only_their_os_disk():
    nodes = [NodeSpec(name=f"lab-b-0{i}", data_disk_gb=10) for i in (1, 2, 3)]
    nodes.append(NodeSpec(name="lab-b-04", roles_mode=RolesMode.coordinating, os_disk_gb=40))
    state = DesiredState(name="lab-b", version="9.4.3", nodes=nodes)
    # 3 x (32+10) + 40 = 166 GiB on one shared pool: 170 fits, 160 does not
    assert recommend_placement(state, three_hosts(tank_avail_gib=170)).ok
    assert not recommend_placement(state, three_hosts(tank_avail_gib=160)).ok


def test_offline_hosts_and_missing_datastores_are_skipped():
    hosts = [host("pve1"), host("pve2", online=False), host("pve3", datastore=None)]
    got = recommend_placement(three_node(), hosts)
    assert set(got.hosts.values()) == {"pve1"}               # only pve1 qualifies; every node lands there
    assert not got.quorum_safe                                 # all three masters share pve1
    state = three_node()
    state.nodes[0].pve_node = "pve3"
    err = recommend_placement(state, hosts)
    assert any("is not available on this host" in i.message for i in err.issues)


# ---- the quorum rule -----------------------------------------------------------------------------

def test_two_hosts_for_three_masters_is_refused_because_losing_one_breaks_the_quorum():
    hosts = [host("pve1"), host("pve2"), host("pve3", online=False)]
    got = recommend_placement(three_node(), hosts)
    assert not got.ok and not got.quorum_safe
    message = next(i.message for i in got.issues if i.severity == "error")
    assert "would hold 2 of 3 master-eligible nodes" in message and "break the master quorum" in message
    assert "At least 3 hosts" in message


def test_a_single_host_is_refused_too():
    got = recommend_placement(three_node(), [host("pve1")])
    assert not got.ok and not got.quorum_safe
    assert any("would hold 3 of 3" in i.message for i in got.issues)


def test_a_host_that_cannot_take_a_master_makes_the_refusal_say_why_so_machines_can_be_moved():
    hosts = [host("pve1", mem_used_gib=186), host("pve2"), host("pve3")]
    got = recommend_placement(three_node(), hosts)
    assert not got.ok
    message = next(i.message for i in got.issues if i.severity == "error")
    assert "pve1 could not take one: not enough free RAM" in message
    assert "Free capacity on another host" in message
    assert "lab-b-0" in message                              # the nodes that would share a host are named


def test_pinning_two_masters_to_one_host_is_refused():
    state = three_node()
    state.nodes[0].pve_node = state.nodes[1].pve_node = "pve1"
    got = recommend_placement(state, three_hosts())
    assert not got.ok
    assert "(lab-b-01, lab-b-02)" in next(i.message for i in got.issues if i.severity == "error")


def test_five_masters_may_share_a_host_when_losing_it_keeps_a_quorum():
    nodes = [NodeSpec(name=f"lab-b-0{i}", data_disk_gb=100) for i in range(1, 6)]
    state = DesiredState(name="lab-b", version="9.4.3", nodes=nodes)
    got = recommend_placement(state, three_hosts())
    assert got.ok and got.quorum_safe                        # 2 + 2 + 1: losing any one host leaves 3 of 5
    assert sorted(Counter(got.hosts.values()).values()) == [1, 2, 2]
    assert any(i.severity == "warning" and "share a host" in i.message for i in got.issues)


def test_four_masters_on_three_hosts_are_refused_because_two_of_four_is_not_a_majority():
    nodes = [NodeSpec(name=f"lab-b-0{i}", data_disk_gb=100) for i in range(1, 5)]
    state = DesiredState(name="lab-b", version="9.4.3", nodes=nodes)
    got = recommend_placement(state, three_hosts())
    assert not got.ok and not got.quorum_safe                # 2 + 1 + 1: losing the first leaves 2 of 4
    assert "would hold 2 of 4" in next(i.message for i in got.issues if i.severity == "error")


def test_nodes_that_are_not_master_eligible_are_not_subject_to_the_rule():
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-b", "9.4.3", data_nodes=5)
    got = recommend_placement(state, three_hosts())
    assert got.ok and got.quorum_safe                        # the masters spread; the data nodes pile up freely
    masters = [n.name for n in state.nodes if n.is_master_eligible]
    assert len({got.hosts[n] for n in masters}) == 3


# ---- determinism and ordering --------------------------------------------------------------------

def test_result_is_deterministic_and_independent_of_host_order():
    a = recommend_placement(three_node(), three_hosts())
    b = recommend_placement(three_node(), list(reversed(three_hosts())))
    assert a.hosts == b.hosts
    assert recommend_placement(three_node(), three_hosts()).hosts == a.hosts


def test_assignments_follow_the_node_order():
    got = recommend_placement(three_node(), three_hosts())
    assert list(got.assignments) == ["lab-b-01", "lab-b-02", "lab-b-03"]


# ---- building host views from stored rows --------------------------------------------------------

def test_host_views_from_stored_rows():
    nodes = [
        {"name": "pve1", "status": "online", "usage": {"cpu": 0.1, "maxcpu": 40, "mem": 10 * GIB,
                                                       "maxmem": 187 * GIB}},
        {"name": "pve2", "status": "online", "usage": {}},                 # no usage: unknown capacity
        {"name": "pve3", "status": "offline", "usage": {"maxcpu": 40, "maxmem": 187 * GIB}},
    ]
    storages = [
        {"node": "pve1", "name": "tank", "shared": True, "active": True, "avail": 100 * GIB,
         "total": 200 * GIB},
        {"node": "pve1", "name": "dead", "shared": False, "active": False, "avail": 1, "total": 1},
    ]
    vms = [
        {"pve_node": "pve1", "status": "running", "cpu_cores": 8, "memory_mb": 16384},
        {"pve_node": "pve1", "status": "stopped", "cpu_cores": 16, "memory_mb": 32768},
        {"pve_node": "pve1", "status": "running", "cpu_cores": 4, "memory_mb": 4096, "is_template": True},
    ]
    views = {h.name: h for h in host_views_from_rows(nodes, storages, vms)}
    p1 = views["pve1"]
    assert p1.online and p1.cores == 40 and p1.committed_vcpus == 8       # only the running, non-template VM
    assert p1.committed_mem == 16384 * 1024 * 1024
    assert list(p1.datastores) == ["tank"] and p1.datastores["tank"].shared   # inactive storage dropped
    assert views["pve2"].online and not views["pve2"].usage_known     # listed, but its capacity is unknown
    assert not views["pve3"].online


# ---- saying why a host was not used --------------------------------------------------------------------

def test_a_host_that_took_nothing_says_why():
    hosts = [host("pve1", mem_used_gib=186), host("pve2"), host("pve3")]
    got = recommend_placement(three_node(), hosts)
    assert "pve1" not in got.hosts.values()
    assert any("not enough free RAM" in why for why in got.excluded["pve1"])


def test_a_host_that_was_used_is_not_listed_even_if_it_refused_a_later_node():
    """pve1 has room for one master but not for the coordinating node after it, so it refuses once and is used."""
    state = build_desired_state(TopologyPreset.three_node, "lab-b", "9.4.3", coordinating_nodes=1)
    hosts = [host("pve1", mem_gib=12, mem_used_gib=1), host("pve2"), host("pve3")]
    got = recommend_placement(state, hosts)
    assert got.ok and "pve1" in got.hosts.values()                    # it took a master...
    assert got.hosts["lab-b-04"] != "pve1"                            # ...but could not take the fourth node
    assert got.excluded == {}                                         # so it is not reported as unused


def test_an_offline_host_is_reported_as_offline():
    got = recommend_placement(three_node(), [host("pve1"), host("pve2"), host("pve3", online=False)])
    assert got.excluded == {"pve3": ["host is offline"]}
