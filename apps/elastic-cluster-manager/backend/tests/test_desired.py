from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.desired import (
    DesiredState,
    NodeSpec,
    RolesMode,
    TopologyPreset,
    build_desired_state,
    default_heap_mb,
    discovery_settings,
    node_settings,
    render_node_roles,
    warnings,
)

BOOTSTRAPPED = datetime(2026, 11, 5, tzinfo=UTC)


def three_node(**kw) -> DesiredState:
    return build_desired_state(TopologyPreset.three_node, "lab-b", "9.4.3", **kw)


# ---- node.roles: the acceptance criterion from the plan -------------------------------------

def test_default_roles_omit_node_roles_entirely():
    node = NodeSpec(name="lab-b-01", data_disk_gb=100)
    assert node.roles_mode == RolesMode.default
    assert render_node_roles(node) is None
    settings = node_settings(node, three_node())
    assert "node.roles" not in settings          # omitted, not rendered as null or as a list


def test_coordinating_only_renders_an_empty_list():
    node = NodeSpec(name="lab-b-09", roles_mode=RolesMode.coordinating)
    assert render_node_roles(node) == []
    assert node_settings(node, three_node())["node.roles"] == []


def test_custom_roles_render_as_a_sorted_explicit_list():
    node = NodeSpec(name="lab-b-04", roles_mode=RolesMode.custom, roles=["ingest", "data"],
                    data_disk_gb=50)
    assert render_node_roles(node) == ["data", "ingest"]
    assert node_settings(node, three_node())["node.roles"] == ["data", "ingest"]


def test_roles_must_match_the_mode():
    with pytest.raises(ValidationError, match="must not list roles"):
        NodeSpec(name="lab-b-01", roles=["master"], data_disk_gb=10)
    with pytest.raises(ValidationError, match="non-empty roles list"):
        NodeSpec(name="lab-b-01", roles_mode=RolesMode.custom)
    with pytest.raises(ValidationError, match="unknown Elasticsearch roles"):
        NodeSpec(name="lab-b-01", roles_mode=RolesMode.custom, roles=["wizard"])
    with pytest.raises(ValidationError, match="voting_only requires the master role"):
        NodeSpec(name="lab-b-01", roles_mode=RolesMode.custom, roles=["voting_only", "data"],
                 data_disk_gb=10)


# ---- cluster.initial_master_nodes: bootstrap only --------------------------------------------

def test_initial_master_nodes_only_on_first_create():
    state = three_node()
    first = discovery_settings(state, operation_kind="create", bootstrapped_at=None)
    assert first["cluster.initial_master_nodes"] == ["lab-b-01", "lab-b-02", "lab-b-03"]

    for kind in ("create", "update", "upgrade", "restart", "resize"):
        later = discovery_settings(state, operation_kind=kind, bootstrapped_at=BOOTSTRAPPED)
        assert "cluster.initial_master_nodes" not in later, kind
    # a non-create run before bootstrap must not bootstrap either
    assert "cluster.initial_master_nodes" not in discovery_settings(
        state, operation_kind="update", bootstrapped_at=None)


def test_initial_master_nodes_lists_only_electable_masters():
    nodes = [
        NodeSpec(name="lab-b-01", roles_mode=RolesMode.custom, roles=["master"]),
        NodeSpec(name="lab-b-02", roles_mode=RolesMode.custom, roles=["master"]),
        NodeSpec(name="lab-b-03", roles_mode=RolesMode.custom, roles=["master", "voting_only"]),
        NodeSpec(name="lab-b-04", roles_mode=RolesMode.custom, roles=["data"], data_disk_gb=50),
        NodeSpec(name="lab-b-05", roles_mode=RolesMode.coordinating),
    ]
    state = DesiredState(name="lab-b", version="9.4.3", nodes=nodes)
    got = discovery_settings(state, operation_kind="create", bootstrapped_at=None)
    assert got["cluster.initial_master_nodes"] == ["lab-b-01", "lab-b-02"]
    assert got["discovery.seed_hosts"] == ["lab-b-01", "lab-b-02", "lab-b-03"]


def test_single_node_uses_single_node_discovery_and_never_initial_masters():
    state = build_desired_state(TopologyPreset.single_node, "lab-b", "9.4.3")
    for bootstrapped in (None, BOOTSTRAPPED):
        got = discovery_settings(state, operation_kind="create", bootstrapped_at=bootstrapped)
        assert got == {"discovery.type": "single-node"}


# ---- cluster validation ----------------------------------------------------------------------

def test_valid_presets_pass_and_have_expected_shapes():
    single = build_desired_state(TopologyPreset.single_node, "lab-b", "9.4.3")
    assert len(single.nodes) == 1 and single.is_single_node
    three = three_node()
    assert [n.name for n in three.nodes] == ["lab-b-01", "lab-b-02", "lab-b-03"]
    assert all(n.is_master_eligible and n.holds_data for n in three.nodes)
    dedicated = build_desired_state(TopologyPreset.dedicated_masters, "lab-b", "9.4.3",
                                    data_nodes=2, coordinating_nodes=1)
    masters = [n for n in dedicated.nodes if n.effective_roles == {"master"}]
    assert len(masters) == 3
    assert [n.roles_mode for n in dedicated.nodes[-1:]] == [RolesMode.coordinating]
    assert not dedicated.nodes[-1].holds_data
    assert dedicated.nodes[0].data_disk_gb is None  # master-only nodes get no data disk


def test_multi_node_needs_three_master_eligible_nodes():
    nodes = [NodeSpec(name=f"lab-b-0{i}", data_disk_gb=50) for i in (1, 2)]
    with pytest.raises(ValidationError, match="at least 3 master-eligible"):
        DesiredState(name="lab-b", version="9.4.3", nodes=nodes)


def test_cluster_needs_an_electable_master_and_a_data_node():
    only_voting = [NodeSpec(name="lab-b-01", roles_mode=RolesMode.custom,
                            roles=["master", "voting_only", "data"], data_disk_gb=50)]
    with pytest.raises(ValidationError, match="not voting_only"):
        DesiredState(name="lab-b", version="9.4.3", nodes=only_voting)
    no_data = [NodeSpec(name=f"lab-b-0{i}", roles_mode=RolesMode.custom, roles=["master"])
               for i in (1, 2, 3)]
    with pytest.raises(ValidationError, match="holds data"):
        DesiredState(name="lab-b", version="9.4.3", nodes=no_data)


def test_names_versions_and_addresses_are_validated():
    ok = [NodeSpec(name="lab-b-01", data_disk_gb=50)]
    for bad in ("Lab", "a", "-lab", "lab-", "lab_b", "x" * 41):
        with pytest.raises(ValidationError):
            DesiredState(name=bad, version="9.4.3", nodes=ok)
    for bad in ("9.4", "latest", "7.17.0", "9.4.3-SNAPSHOT"):
        with pytest.raises(ValidationError):
            DesiredState(name="lab-b", version=bad, nodes=ok)
    with pytest.raises(ValidationError, match="IPv4"):
        NodeSpec(name="lab-b-01", data_disk_gb=50, ip="999.1.1.1")
    dup = [NodeSpec(name="lab-b-01", data_disk_gb=50), NodeSpec(name="lab-b-01", data_disk_gb=50),
           NodeSpec(name="lab-b-03", data_disk_gb=50)]
    with pytest.raises(ValidationError, match="unique"):
        DesiredState(name="lab-b", version="9.4.3", nodes=dup)
    same_ip = [NodeSpec(name=f"lab-b-0{i}", data_disk_gb=50, ip="192.168.10.211") for i in (1, 2, 3)]
    with pytest.raises(ValidationError, match="addresses must be unique"):
        DesiredState(name="lab-b", version="9.4.3", nodes=same_ip)


def test_data_holding_nodes_need_a_data_disk():
    with pytest.raises(ValidationError, match="needs data_disk_gb"):
        NodeSpec(name="lab-b-01")                        # default roles hold data
    NodeSpec(name="lab-b-01", roles_mode=RolesMode.coordinating)   # coordinating does not


def test_heap_rules_and_default():
    assert default_heap_mb(8192) == 4096                  # half of RAM
    assert default_heap_mb(131072) == 31 * 1024           # capped at 31 GB
    assert NodeSpec(name="lab-b-01", data_disk_gb=50, ram_mb=8192).effective_heap_mb == 4096
    assert NodeSpec(name="lab-b-01", data_disk_gb=50, ram_mb=8192, heap_mb=2048).effective_heap_mb == 2048
    with pytest.raises(ValidationError, match="half of ram_mb"):
        NodeSpec(name="lab-b-01", data_disk_gb=50, ram_mb=8192, heap_mb=6000)
    with pytest.raises(ValidationError, match="at least 512"):
        NodeSpec(name="lab-b-01", data_disk_gb=50, heap_mb=256)
    with pytest.raises(ValidationError, match="31 GB"):
        NodeSpec(name="lab-b-01", data_disk_gb=50, ram_mb=131072, heap_mb=40000)


def test_user_settings_cannot_override_managed_ones():
    with pytest.raises(ValidationError, match="managed by ECM"):
        NodeSpec(name="lab-b-01", data_disk_gb=50,
                 extra_settings={"node.roles": "master", "cluster.initial_master_nodes": "x"})
    ok = NodeSpec(name="lab-b-01", data_disk_gb=50, extra_settings={"indices.query.bool.max_clause_count": 2048})
    assert node_settings(ok, three_node())["indices.query.bool.max_clause_count"] == 2048


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        NodeSpec(name="lab-b-01", data_disk_gb=50, colour="blue")


def test_warnings_for_even_masters_shared_hosts_and_single_node():
    even = [NodeSpec(name=f"lab-b-0{i}", data_disk_gb=50) for i in range(1, 5)]
    assert any("even number" in w for w in warnings(DesiredState(name="lab-b", version="9.4.3", nodes=even)))
    pinned = [NodeSpec(name=f"lab-b-0{i}", data_disk_gb=50, pve_node="pve1" if i < 3 else "pve2")
              for i in (1, 2, 3)]
    got = warnings(DesiredState(name="lab-b", version="9.4.3", nodes=pinned))
    assert any("same Proxmox host (pve1)" in w for w in got)
    single = build_desired_state(TopologyPreset.single_node, "lab-b", "9.4.3")
    assert any("yellow" in w for w in warnings(single))
    assert warnings(three_node()) == []


def test_state_round_trips_through_json():
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-b", "9.4.3", data_nodes=2)
    assert DesiredState.model_validate_json(state.model_dump_json()) == state


def test_custom_preset_has_no_template():
    with pytest.raises(ValueError, match="no template"):
        build_desired_state(TopologyPreset.custom, "lab-b", "9.4.3")
    with pytest.raises(ValueError, match="at least one data node"):
        build_desired_state(TopologyPreset.dedicated_masters, "lab-b", "9.4.3", data_nodes=0)
