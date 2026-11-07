import json
import stat
from datetime import UTC, datetime

import pytest

from app.configmgmt import (
    InventoryError,
    InventoryInput,
    ephemeral_inventory,
    inventory_json,
    render_inventory,
)
from app.desired import NodeSpec, RolesMode, TopologyPreset, build_desired_state
from app.desired.models import DesiredState

BOOTSTRAPPED = datetime(2026, 11, 5, tzinfo=UTC)


def three_node() -> DesiredState:
    return build_desired_state(TopologyPreset.three_node, "lab-b", "9.4.3")


def addresses(state: DesiredState) -> dict[str, str]:
    return {n.name: f"192.0.2.{10 + i}" for i, n in enumerate(state.nodes)}


def make(state: DesiredState | None = None, **kw) -> InventoryInput:
    state = state or three_node()
    base = {
        "state": state, "addresses": addresses(state), "operation_kind": "create", "bootstrapped_at": None,
        "ssh_user": "ubuntu", "ssh_key_path": "/run/ecm/ssh/github_rsa",
        "known_hosts_path": "/tmp/ecm-run/known_hosts", "search_domain": "lab.example.test",
        "artifacts_dir": "/tmp/ecm-run/artifacts",
    }
    base.update(kw)
    return InventoryInput(**base)


def hosts(inv: dict) -> dict:
    return inv["all"]["children"]["es_nodes"]["hosts"]


# ---- node.roles: same rule as the Terraform side, checked through the inventory -------------

def test_default_roles_leave_the_variable_out_entirely():
    inv = render_inventory(make())
    for host in hosts(inv).values():
        assert "es_node_roles" not in host


def test_coordinating_only_is_an_empty_list_and_custom_is_sorted():
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-c", "9.4.3",
                                data_nodes=2, coordinating_nodes=1)
    inv = render_inventory(make(state))
    by_roles = [h.get("es_node_roles", "omitted") for h in hosts(inv).values()]
    assert [] in by_roles                      # coordinating renders [], not omitted
    for roles in by_roles:
        if isinstance(roles, list) and roles:
            assert roles == sorted(roles)


def test_single_node_custom_roles_are_rendered_as_given_sorted():
    node = NodeSpec(name="solo-01", roles_mode=RolesMode.custom,
                    roles=["master", "data", "ingest"], data_disk_gb=50)
    state = DesiredState(name="solo", version="9.4.3", nodes=[node])
    inv = render_inventory(make(state))
    assert hosts(inv)["solo-01"]["es_node_roles"] == ["data", "ingest", "master"]


# ---- bootstrap: initial_master_nodes only on a first create ---------------------------------

def test_create_before_bootstrap_lists_electable_masters():
    state = three_node()
    inv = render_inventory(make(state))
    v = inv["all"]["vars"]
    assert v["es_initial_master_nodes"] == [n.name for n in state.nodes if n.is_electable]
    assert v["es_first_start"] is True
    assert v["es_allow_restart"] is True


def test_converge_never_renders_initial_master_nodes_or_allows_restarts():
    inv = render_inventory(make(operation_kind="converge", bootstrapped_at=BOOTSTRAPPED))
    v = inv["all"]["vars"]
    assert "es_initial_master_nodes" not in v
    assert v["es_first_start"] is False
    assert v["es_allow_restart"] is False


def test_create_on_a_bootstrapped_cluster_is_refused():
    with pytest.raises(InventoryError, match="already bootstrapped"):
        render_inventory(make(bootstrapped_at=BOOTSTRAPPED))


def test_single_node_uses_no_seed_hosts_no_initial_masters_and_expects_yellow():
    node = NodeSpec(name="solo-01", data_disk_gb=50)
    state = DesiredState(name="solo", version="9.4.3", nodes=[node])
    v = render_inventory(make(state))["all"]["vars"]
    assert v["es_single_node"] is True
    assert v["es_seed_hosts"] == []
    assert "es_initial_master_nodes" not in v
    assert v["es_expected_status"] == "yellow"


def test_multi_node_expects_green_and_seeds_with_addresses_not_names():
    state = three_node()
    addrs = addresses(state)
    v = render_inventory(make(state))["all"]["vars"]
    assert v["es_expected_status"] == "green"
    assert v["es_expected_nodes"] == 3
    assert v["es_seed_hosts"] == [addrs[n.name] for n in state.master_eligible_nodes]
    assert all(s.startswith("192.0.2.") for s in v["es_seed_hosts"])


def test_one_bootstrap_host_which_is_an_electable_master():
    state = three_node()
    inv = render_inventory(make(state))
    boot = inv["all"]["children"]["es_bootstrap"]["hosts"]
    assert list(boot) == [inv["all"]["vars"]["es_ca_host"]]
    assert next(iter(boot)) in {n.name for n in state.nodes if n.is_electable}


# ---- per-node values ------------------------------------------------------------------------

def test_host_vars_carry_address_names_heap_and_disk():
    state = three_node()
    inv = render_inventory(make(state))
    node = state.nodes[0]
    h = hosts(inv)[node.name]
    assert h["ansible_host"] == h["es_node_ip"] == addresses(state)[node.name]
    assert h["es_dns_names"] == [node.name, f"{node.name}.lab.example.test"]
    assert h["es_heap_mb"] == node.effective_heap_mb
    assert h["es_data_disk_gb"] == node.data_disk_gb


def test_no_search_domain_means_short_names_only():
    h = next(iter(hosts(render_inventory(make(search_domain=None))).values()))
    assert h["es_dns_names"] == [h["es_node_name"]]


def test_a_node_without_a_data_disk_has_no_disk_variable():
    node = NodeSpec(name="lab-b-09", roles_mode=RolesMode.coordinating)
    base = three_node()
    state = DesiredState(name="lab-b", version="9.4.3", nodes=[*base.nodes, node])
    assert "es_data_disk_gb" not in hosts(render_inventory(make(state)))["lab-b-09"]


# ---- connection and secrets -----------------------------------------------------------------

def test_ssh_settings_use_the_given_key_only_and_a_per_run_known_hosts():
    v = render_inventory(make())["all"]["vars"]
    assert v["ansible_user"] == "ubuntu"
    assert v["ansible_ssh_private_key_file"] == "/run/ecm/ssh/github_rsa"
    assert "IdentitiesOnly=yes" in v["ansible_ssh_common_args"]
    assert "UserKnownHostsFile=/tmp/ecm-run/known_hosts" in v["ansible_ssh_common_args"]
    assert "StrictHostKeyChecking=no" not in v["ansible_ssh_common_args"].replace(
        "accept-new", "")


def test_no_credential_ever_appears_in_the_inventory():
    text = inventory_json(make()).lower()
    for word in ("password", "begin ", "private key", "secret", "ca_key", "api_key"):
        assert word not in text.replace("ansible_ssh_private_key_file", "")


def test_output_is_deterministic():
    assert inventory_json(make()) == inventory_json(make())


@pytest.mark.parametrize("field,value", [
    ("ssh_user", "root; id"),
    ("ssh_user", ""),
    ("ssh_key_path", "relative/key"),
    ("ssh_key_path", "/run/ecm/key with space"),
    ("ssh_key_path", "/run/../etc/key"),
    ("known_hosts_path", "/tmp/x -o ProxyCommand=evil"),
    ("artifacts_dir", "/tmp/a'b"),
    ("search_domain", "bad domain"),
])
def test_unsafe_connection_inputs_are_refused(field, value):
    with pytest.raises(InventoryError):
        render_inventory(make(**{field: value}))


def test_address_problems_are_refused():
    state = three_node()
    good = addresses(state)
    first = state.nodes[0].name
    with pytest.raises(InventoryError, match="no address"):
        render_inventory(make(addresses={k: v for k, v in good.items() if k != first}))
    with pytest.raises(InventoryError, match="unknown node"):
        render_inventory(make(addresses={**good, "ghost": "192.0.2.99"}))
    with pytest.raises(InventoryError, match="not an IPv4"):
        render_inventory(make(addresses={**good, first: "not-an-ip"}))
    dup = dict(good)
    dup[state.nodes[1].name] = good[first]
    with pytest.raises(InventoryError, match="unique"):
        render_inventory(make(addresses=dup))


# ---- the ephemeral directory ----------------------------------------------------------------

def test_ephemeral_inventory_is_private_and_removed_afterwards(tmp_path):
    with ephemeral_inventory(make(), parent=str(tmp_path)) as path:
        assert path.is_file()
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert json.loads(path.read_text())["all"]["vars"]["es_cluster_name"] == "lab-b"
        root = path.parent
    assert not root.exists()


def test_ephemeral_inventory_is_removed_even_if_the_run_fails(tmp_path):
    root = None
    with pytest.raises(RuntimeError), ephemeral_inventory(make(), parent=str(tmp_path)) as path:
        root = path.parent
        raise RuntimeError("playbook failed")
    assert root is not None and not root.exists()


def test_a_bad_input_leaves_nothing_on_disk(tmp_path):
    with pytest.raises(InventoryError), ephemeral_inventory(
            make(ssh_user="bad user"), parent=str(tmp_path)):
        pass
    assert list(tmp_path.iterdir()) == []


# ---- a rolling restart --------------------------------------------------------------------------------------

def test_a_restart_inventory_names_each_nodes_proxmox_host_vmid_and_target_size():
    from datetime import UTC, datetime

    from app.configmgmt import InventoryInput, render_inventory
    state = build_desired_state(TopologyPreset.three_node, "lab-b", "9.5.6")
    names = [n.name for n in state.nodes]
    inv = render_inventory(InventoryInput(
        state=state, addresses={n: f"192.0.2.{10 + i}" for i, n in enumerate(names)}, operation_kind="restart",
        bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC), ssh_user="bret", ssh_key_path="/run/ecm/ssh/k",
        known_hosts_path="/tmp/kh", vm_ids={n: 500 + i for i, n in enumerate(names)},
        placement={n: f"pve{i + 1}" for i, n in enumerate(names)}))
    hosts = inv["all"]["children"]["es_nodes"]["hosts"]
    assert hosts["lab-b-03"]["es_pve_node"] == "pve3" and hosts["lab-b-03"]["es_vmid"] == 502
    assert hosts["lab-b-01"]["es_desired_cores"] == 4 and hosts["lab-b-01"]["es_desired_ram_mb"] == 8192
    assert "es_initial_master_nodes" not in inv["all"]["vars"] and inv["all"]["vars"]["es_allow_restart"] is False


def test_other_kinds_do_not_carry_the_restart_variables():
    from datetime import UTC, datetime

    from app.configmgmt import InventoryInput, render_inventory
    state = build_desired_state(TopologyPreset.three_node, "lab-b", "9.5.6")
    inv = render_inventory(InventoryInput(
        state=state, addresses={n.name: f"192.0.2.{10 + i}" for i, n in enumerate(state.nodes)},
        operation_kind="converge", bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC), ssh_user="bret",
        ssh_key_path="/run/ecm/ssh/k", known_hosts_path="/tmp/kh"))
    host = inv["all"]["children"]["es_nodes"]["hosts"]["lab-b-01"]
    assert not any(k in host for k in ("es_pve_node", "es_vmid", "es_desired_cores", "es_desired_ram_mb"))


def test_a_restart_needs_a_bootstrapped_cluster_and_a_host_and_vmid_for_every_node():
    from datetime import UTC, datetime

    from app.configmgmt import InventoryError, InventoryInput, render_inventory
    state = build_desired_state(TopologyPreset.three_node, "lab-b", "9.5.6")
    names = [n.name for n in state.nodes]
    base = {"state": state, "addresses": {n: f"192.0.2.{10 + i}" for i, n in enumerate(names)},
            "operation_kind": "restart", "ssh_user": "bret", "ssh_key_path": "/run/ecm/ssh/k",
            "known_hosts_path": "/tmp/kh"}
    good = {"vm_ids": {n: 500 + i for i, n in enumerate(names)}, "placement": {n: "pve1" for n in names}}
    with pytest.raises(InventoryError, match="has bootstrapped"):
        render_inventory(InventoryInput(**base, bootstrapped_at=None, **good))
    with pytest.raises(InventoryError, match="vm_ids for every node; missing: lab-b-03"):
        render_inventory(InventoryInput(**base, bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC),
                                        vm_ids={n: 500 for n in names[:2]}, placement=good["placement"]))
    with pytest.raises(InventoryError, match="placement for every node"):
        render_inventory(InventoryInput(**base, bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC),
                                        vm_ids=good["vm_ids"], placement=None))


def test_a_restart_inventory_classes_each_node_for_the_order_masters_last():
    from datetime import UTC, datetime

    from app.configmgmt import InventoryInput, render_inventory
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-x", "9.5.6", data_nodes=2, coordinating_nodes=1)
    names = [n.name for n in state.nodes]
    inv = render_inventory(InventoryInput(
        state=state, addresses={n: f"192.0.2.{10 + i}" for i, n in enumerate(names)}, operation_kind="restart",
        bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC), ssh_user="bret", ssh_key_path="/run/ecm/ssh/k",
        known_hosts_path="/tmp/kh", vm_ids={n: 500 + i for i, n in enumerate(names)},
        placement={n: "pve1" for n in names}))
    hosts = inv["all"]["children"]["es_nodes"]["hosts"]
    assert {n: hosts[n]["es_restart_class"] for n in names} == {
        "lab-x-01": "master", "lab-x-02": "master", "lab-x-03": "master",
        "lab-x-04": "data", "lab-x-05": "data", "lab-x-06": "coordinating"}
