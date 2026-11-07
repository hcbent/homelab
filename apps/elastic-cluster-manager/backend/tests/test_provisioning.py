import json
import shutil
import subprocess

import pytest

from app.desired import TopologyPreset, build_desired_state
from app.desired.network import NetworkProfile
from app.provisioning import hcl
from app.provisioning.render import (
    RenderError,
    RenderInput,
    TemplateRef,
    config_digest,
    render_workspace,
)
from app.provisioning.vmid import VmidError, allocate_vmids

PROFILE = NetworkProfile(
    name="default", bridge="vmbr0", vlan=10, cidr="192.0.2.0/24", gateway="192.0.2.1", dns=["192.0.2.1"],
    search_domain="lab.example.org", range_start="192.0.2.110", range_end="192.0.2.149",
    dhcp_start="192.0.2.150", dhcp_end="192.0.2.254")


def make(**kw) -> RenderInput:
    state = kw.pop("state", None) or build_desired_state(TopologyPreset.three_node, "lab-b", "9.4.3")
    names = [n.name for n in state.nodes]
    base = {
        "cluster_id": "a1b2c3d4e5f60718", "state": state,
        "placement": {n: f"pve{i % 3 + 1}" for i, n in enumerate(names)},
        "addresses": {n: f"192.0.2.{110 + i}" for i, n in enumerate(names)},
        "vm_ids": {n: 500 + i for i, n in enumerate(names)},
        "profile": PROFILE, "template": TemplateRef("pve1", 8000),
        "proxmox_endpoint": "https://pve2.lab.example.org:8006/"}
    return RenderInput(**{**base, **kw})


def tfvars(files) -> dict:
    return json.loads(files["cluster.auto.tfvars.json"])


# ---- the rendered workspace ------------------------------------------------------------------

def test_the_workspace_has_the_expected_files():
    files = render_workspace(make())
    assert sorted(files) == [
        "backend.tf", "cluster.auto.tfvars.json", "main.tf", "modules/es_node/main.tf",
        "modules/es_node/outputs.tf", "modules/es_node/variables.tf", "modules/es_node/versions.tf",
        "outputs.tf", "variables.tf", "versions.tf"]


def test_node_values_carry_placement_addresses_ids_and_sizing():
    files = render_workspace(make())
    nodes = tfvars(files)["nodes"]
    assert list(nodes) == ["lab-b-01", "lab-b-02", "lab-b-03"]
    first = nodes["lab-b-01"]
    assert first == {"node_name": "pve1", "vm_id": 500, "cores": 4, "memory_mb": 8192, "os_disk_gb": 32,
                     "data_disk_gb": 100, "address": "192.0.2.110/24", "gateway": "192.0.2.1"}
    assert nodes["lab-b-02"]["node_name"] == "pve2" and nodes["lab-b-02"]["address"] == "192.0.2.111/24"


def test_shared_settings_come_from_the_profile_pool_template_and_connection():
    v = tfvars(render_workspace(make(pool_id="ecm", datastore_id="tank", proxmox_insecure=True)))
    assert v["proxmox_endpoint"] == "https://pve2.lab.example.org:8006/" and v["proxmox_insecure"] is True
    assert v["cluster_name"] == "lab-b" and v["pool_id"] == "ecm" and v["datastore_id"] == "tank"
    assert v["template"] == {"node_name": "pve1", "vm_id": 8000}
    assert (v["bridge"], v["vlan_id"], v["dns_servers"], v["search_domain"]) == (
        "vmbr0", 10, ["192.0.2.1"], "lab.example.org")
    assert v["agent_enabled"] is False                       # off by default: apply would hang without it


def test_master_only_nodes_have_no_data_disk():
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-b", "9.4.3", data_nodes=2,
                                coordinating_nodes=1)
    nodes = tfvars(render_workspace(make(state=state)))["nodes"]
    assert [nodes[f"lab-b-0{i}"]["data_disk_gb"] for i in (1, 2, 3)] == [None, None, None]
    assert nodes["lab-b-04"]["data_disk_gb"] == 100 and nodes["lab-b-06"]["data_disk_gb"] is None


def test_a_profile_without_vlan_or_domain_renders_nulls():
    plain = PROFILE.model_copy(update={"vlan": None, "search_domain": None})
    v = tfvars(render_workspace(make(profile=plain)))
    assert v["vlan_id"] is None and v["search_domain"] is None


def test_the_state_backend_is_postgres_by_default_and_optional():
    files = render_workspace(make())
    assert 'schema_name = "tf_a1b2c3d4e5f60718"' in files["backend.tf"]
    assert 'backend "pg"' in files["backend.tf"]
    assert "backend.tf" not in render_workspace(make(state_backend="local"))


def test_the_provider_is_pinned_to_an_exact_version():
    assert 'version = "0.119.0"' in render_workspace(make())["versions.tf"]
    assert hcl.PROVIDER_VERSION == "0.119.0"


# ---- safety --------------------------------------------------------------------------------------

def test_no_secret_or_token_appears_anywhere_in_the_output():
    blob = "\n".join(render_workspace(make()).values()).lower()
    for word in ("secret", "password", "api_token=", "token_secret", "ssh-rsa", "private key"):
        assert word not in blob, word
    # the token is only ever named as the environment variable the runner supplies
    assert "PROXMOX_VE_API_TOKEN" in render_workspace(make())["versions.tf"]
    assert "=" not in render_workspace(make())["versions.tf"].split("PROXMOX_VE_API_TOKEN")[1].split("\n")[0]


def test_cluster_data_never_enters_the_hcl_text_except_the_schema_name():
    files = render_workspace(make())
    hcl_files = {p: c for p, c in files.items() if p.endswith(".tf") and p != "backend.tf"}
    for path, content in hcl_files.items():
        for needle in ("lab-b", "192.0.2.", "pve1", "a1b2c3d4"):
            assert needle not in content, (path, needle)
    # and the static files are identical whatever the cluster is
    other = render_workspace(make(state=build_desired_state(TopologyPreset.single_node, "zz", "9.5.6"),
                                  cluster_id="ffffffffffff0000"))
    for path, content in hcl_files.items():
        assert other[path] == content


def test_the_module_names_its_provider_source():
    # found by running terraform init: without this, Terraform looks for hashicorp/proxmox, which does not exist
    files = render_workspace(make())
    assert 'source = "bpg/proxmox"' in files["modules/es_node/versions.tf"]
    assert "version" not in files["modules/es_node/versions.tf"]      # the root pins the version


def test_the_clone_block_and_agent_default_reflect_the_spike_findings():
    module = render_workspace(make())["modules/es_node/main.tf"]
    assert "clone {" in module and "full         = true" in module
    assert 'tags      = sort(["ecm", var.cluster_name])' in module     # Proxmox returns tags sorted
    assert "pool_id   = var.pool_id" in module                          # rights live on the pool
    assert "ignore_changes" not in module                               # create-only configuration


def test_output_is_deterministic_and_the_digest_changes_with_the_config():
    a, b = render_workspace(make()), render_workspace(make())
    assert a == b and list(a) == sorted(a)
    assert config_digest(a) == config_digest(b)
    c = render_workspace(make(addresses={"lab-b-01": "192.0.2.120", "lab-b-02": "192.0.2.111",
                                         "lab-b-03": "192.0.2.112"}))
    assert config_digest(c) != config_digest(a)
    assert len(config_digest(a)) == 64


# ---- input validation ----------------------------------------------------------------------------

def bad(**kw):
    with pytest.raises(RenderError) as e:
        render_workspace(make(**kw))
    return str(e.value)


def test_missing_or_extra_per_node_values_are_reported():
    base = make()
    names = [n.name for n in base.state.nodes]
    assert "no placement for node(s): lab-b-03" in bad(placement={k: "pve1" for k in names[:2]})
    assert "no address for node(s): lab-b-02" in bad(
        addresses={names[0]: "192.0.2.110", names[2]: "192.0.2.112"})
    assert "VMID given for unknown node(s): ghost" in bad(vm_ids={**base.vm_ids, "ghost": 599})


def test_ids_addresses_and_names_are_checked():
    names = ["lab-b-01", "lab-b-02", "lab-b-03"]
    assert "VMIDs must be unique" in bad(vm_ids={n: 500 for n in names})
    assert "VMIDs must be 100 or higher" in bad(vm_ids={"lab-b-01": 99, "lab-b-02": 501, "lab-b-03": 502})
    assert "outside the profile network" in bad(
        addresses={"lab-b-01": "198.51.100.5", "lab-b-02": "192.0.2.111", "lab-b-03": "192.0.2.112"})
    assert "not an IPv4 address" in bad(
        addresses={"lab-b-01": "nope", "lab-b-02": "192.0.2.111", "lab-b-03": "192.0.2.112"})
    assert "addresses must be unique" in bad(addresses={n: "192.0.2.111" for n in names})


@pytest.mark.parametrize("field,value,match", [
    ("cluster_id", "XYZ", "cluster_id must be"),
    ("cluster_id", "a1b2c3d4'; drop", "cluster_id must be"),
    ("pool_id", 'ecm" {', "not a valid Proxmox name"),
    ("datastore_id", "ta nk", "not a valid Proxmox name"),
    ("proxmox_endpoint", "http://pve:8006", "must be an https URL"),
    ("proxmox_endpoint", "pve2:8006", "must be an https URL"),
])
def test_unsafe_scalar_inputs_are_rejected(field, value, match):
    assert match in bad(**{field: value})


def test_a_bad_bridge_template_or_host_is_rejected():
    assert "not a valid Linux bridge name" in bad(
        profile=PROFILE.model_copy(update={"bridge": "vmbr0; rm"}))
    assert "template VMID must be 100 or higher" in bad(template=TemplateRef("pve1", 5))
    names = ["lab-b-01", "lab-b-02", "lab-b-03"]
    assert "not a valid Proxmox host name" in bad(placement={n: "pve 1" for n in names})


# ---- VMID allocation -----------------------------------------------------------------------------

def test_vmids_are_the_lowest_free_ids_in_order():
    assert allocate_vmids(["a", "b", "c"], used=[]) == {"a": 500, "b": 501, "c": 502}
    assert allocate_vmids(["a", "b", "c"], used=[500, 502, 8000]) == {"a": 501, "b": 503, "c": 504}


def test_vmid_allocation_is_deterministic_and_respects_the_range():
    assert allocate_vmids(["a"], used=[], start=700, end=700) == {"a": 700}
    assert allocate_vmids(["a", "b"], used=[]) == allocate_vmids(["a", "b"], used=[])


def test_vmid_errors_say_what_to_change():
    with pytest.raises(VmidError, match="no free ID left for c"):
        allocate_vmids(["a", "b", "c"], used=[], start=500, end=501)
    with pytest.raises(VmidError, match="widen the range"):
        allocate_vmids(["a"], used=[500], start=500, end=500)
    with pytest.raises(VmidError, match="must start at 100"):
        allocate_vmids(["a"], used=[], start=50, end=60)
    with pytest.raises(VmidError, match="invalid"):
        allocate_vmids(["a"], used=[], start=600, end=500)
    with pytest.raises(VmidError, match="unique"):
        allocate_vmids(["a", "a"], used=[])


# ---- real Terraform, when it is installed ---------------------------------------------------------

terraform = shutil.which("terraform")


def write(tmp_path, files):
    for path, content in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


@pytest.mark.skipif(not terraform, reason="terraform is not installed")
def test_rendered_hcl_is_terraform_fmt_clean(tmp_path):
    write(tmp_path, render_workspace(make()))
    out = subprocess.run([terraform, "fmt", "-check", "-recursive", "-diff", str(tmp_path)],
                         capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stdout + out.stderr


@pytest.mark.skipif(not terraform, reason="terraform is not installed")
def test_rendered_workspace_validates(tmp_path):
    write(tmp_path, render_workspace(make(state_backend="local")))
    init = subprocess.run([terraform, "init", "-backend=false", "-input=false", "-no-color"], cwd=tmp_path,
                          capture_output=True, text=True, timeout=180, check=False)
    if init.returncode != 0:
        pytest.skip("the provider could not be installed here: " + init.stderr.strip().splitlines()[-1])
    out = subprocess.run([terraform, "validate", "-no-color"], cwd=tmp_path, capture_output=True,
                         text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stdout + out.stderr


# ---- the CPU type ----------------------------------------------------------------------------------

def test_the_cpu_type_defaults_to_host_and_reaches_the_cpu_block():
    files = render_workspace(make())
    assert tfvars(files)["cpu_type"] == "host"
    assert "    type  = var.cpu_type\n" in files["modules/es_node/main.tf"]
    assert "  cpu_type      = var.cpu_type\n" in files["main.tf"]                   # the root hands it to the module


def test_the_cpu_type_can_be_chosen_and_changes_the_digest():
    default, chosen = render_workspace(make()), render_workspace(make(cpu_type="x86-64-v2-AES"))
    assert tfvars(chosen)["cpu_type"] == "x86-64-v2-AES"
    assert config_digest(default) != config_digest(chosen)                          # so an approval cannot carry over


@pytest.mark.parametrize("cpu_type", ["", "host; rm -rf /", "two words", "-leading", "x" * 65, 'a"b'])
def test_an_unsafe_cpu_type_is_rejected(cpu_type):
    with pytest.raises(RenderError, match="cpu_type"):
        render_workspace(make(cpu_type=cpu_type))


def test_the_cpu_type_never_enters_the_hcl_text():
    files = render_workspace(make(cpu_type="Skylake-Server"))
    assert all("Skylake-Server" not in text for path, text in files.items() if path.endswith(".tf"))


def test_a_vm_is_never_restarted_by_terraform_as_a_side_effect_of_an_update():
    """A restart is ECM's rolling restart, one node at a time. Terraform restarting VMs by itself, two at a time,
    could take the master quorum down."""
    from app.provisioning.hcl import MODULE_MAIN_TF
    assert "reboot_after_update = false" in MODULE_MAIN_TF
