"""The worker image's pins agree with the code, the compose file wires the right stages, and Terraform accepts the
plugin directory layout the image uses. The image itself is not built here."""
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.desired import TopologyPreset, build_desired_state
from app.desired.network import NetworkProfile
from app.provisioning import hcl
from app.provisioning.render import RenderInput, TemplateRef, render_workspace
from app.provisioning.runner import CliTerraformRunner
from app.provisioning.workspace import open_workspace

BACKEND = Path(__file__).parents[1]
DOCKERFILE = (BACKEND / "Dockerfile").read_text()
COMPOSE = (BACKEND.parent / "deploy" / "docker-compose.yml").read_text()
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def arg(name: str) -> str:
    m = re.search(rf"^ARG {name}=(\S+)$", DOCKERFILE, re.MULTILINE)
    assert m, f"Dockerfile has no ARG {name}"
    return m.group(1)


def stage(name: str) -> str:
    """The text of one Dockerfile stage."""
    parts = re.split(r"^(?=FROM )", DOCKERFILE, flags=re.MULTILINE)
    found = [p for p in parts if re.match(rf"FROM \S+ AS {name}\b", p)]
    assert len(found) == 1, f"expected one stage named {name}"
    return found[0]


# ---- pins -----------------------------------------------------------------------------------------------

def test_the_vendored_provider_is_the_version_the_rendered_config_pins():
    assert arg("PROVIDER_VERSION") == hcl.PROVIDER_VERSION


@pytest.mark.parametrize("name", ["TERRAFORM_SHA256_AMD64", "TERRAFORM_SHA256_ARM64",
                                  "PROVIDER_SHA256_AMD64", "PROVIDER_SHA256_ARM64"])
def test_every_download_has_a_pinned_sha256(name):
    assert HEX64.match(arg(name))


def test_the_two_architectures_do_not_share_a_checksum():
    assert arg("TERRAFORM_SHA256_AMD64") != arg("TERRAFORM_SHA256_ARM64")
    assert arg("PROVIDER_SHA256_AMD64") != arg("PROVIDER_SHA256_ARM64")


def test_the_pinned_terraform_satisfies_the_rendered_requirement():
    assert re.search(r'required_version\s*=\s*">= 1\.6"', hcl.VERSIONS_TF)
    major, minor, *_ = (int(x) for x in arg("TERRAFORM_VERSION").split("."))
    assert (major, minor) >= (1, 6)


def test_downloads_are_https_only_and_go_through_the_verifying_helper():
    tools = stage("tools")
    urls = re.findall(r'"(https?://[^"]+)"', tools)
    assert urls and all(u.startswith("https://") for u in urls)
    assert tools.count("fetch_tool.py fetch") == 2          # nothing is fetched with curl or pip, unverified
    assert "curl" not in tools and "wget" not in tools and "ADD http" not in DOCKERFILE


def test_an_unknown_architecture_stops_the_build():
    assert "unsupported or unset TARGETARCH" in stage("tools") and "exit 1" in stage("tools")


# ---- which image gets what ------------------------------------------------------------------------------

def test_only_the_worker_stage_has_terraform_and_the_default_stage_is_the_lean_one():
    assert "COPY --from=tools" in stage("worker") and "COPY --from=tools" not in stage("app")
    assert re.findall(r"^FROM \S+ AS (\w+)", DOCKERFILE, re.MULTILINE)[-1] == "app"
    assert "USER ecm" in stage("worker") and "USER ecm" in stage("app")        # neither runs as root


def test_the_worker_points_the_app_at_the_vendored_provider_and_a_workspace_the_app_user_owns():
    worker = stage("worker")
    assert "ECM_TERRAFORM_PLUGIN_DIR=/opt/ecm/terraform-providers" in worker
    assert "ECM_TF_WORKSPACE_ROOT=/data/clusters" in worker
    assert "chown ecm /data/clusters" in worker


def test_the_build_checks_as_the_app_user_that_terraform_can_read_its_provider_and_write_workspaces():
    """The check must run after USER ecm, so it tests what the running worker will be able to do."""
    after_user = stage("worker").split("USER ecm", 1)[1]
    assert "terraform version" in after_user and "-name '*.zip' -readable" in after_user
    assert "test -w /data/clusters" in after_user


def test_compose_builds_the_worker_from_the_worker_stage_and_the_rest_from_the_lean_one():
    for service, target in (("migrate", "app"), ("api", "app"), ("worker", "worker")):
        block = re.search(rf"^  {service}:\n(.*?)(?=^  \w|\Z)", COMPOSE, re.MULTILINE | re.DOTALL).group(1)
        assert f"target: {target}" in block, service
    worker = re.search(r"^  worker:\n(.*?)(?=^  \w|\Z)", COMPOSE, re.MULTILINE | re.DOTALL).group(1)
    assert "ECM_TF_STATE_URL" in worker and "clusters:/data/clusters" in worker
    api = re.search(r"^  api:\n(.*?)(?=^  \w|\Z)", COMPOSE, re.MULTILINE | re.DOTALL).group(1)
    assert "ECM_TF_STATE_URL" not in api and "ECM_TF_STATE_SSLMODE" not in api   # only the worker holds these
    assert "ECM_TF_STATE_SSLMODE" in worker


# ---- the plugin directory layout, against the real Terraform CLI ----------------------------------------

@pytest.mark.skipif(not shutil.which("terraform"), reason="terraform is not installed")
def test_terraform_installs_the_provider_from_the_layout_the_image_uses(tmp_path):
    platform = json.loads(subprocess.run(["terraform", "version", "-json"], capture_output=True, text=True,
                                         check=True).stdout)["platform"]
    version = hcl.PROVIDER_VERSION
    # The destination path is read out of the Dockerfile, so this tests the layout the image really builds.
    template = re.search(r'"/out/providers/(\S+?)"', stage("tools")).group(1)
    relative = template.replace("${PROVIDER_VERSION}", version).replace("linux_${TARGETARCH}", platform)
    assert "$" not in relative, relative
    plugins = tmp_path / "providers"
    packed = plugins / relative
    packed.parent.mkdir(parents=True)
    with zipfile.ZipFile(packed, "w") as z:                  # a stand-in: init installs it but does not run it
        z.writestr(f"terraform-provider-proxmox_v{version}", b"not a real provider")

    state = build_desired_state(TopologyPreset.single_node, "lab-c", "9.4.3")
    names = [n.name for n in state.nodes]
    files = render_workspace(RenderInput(
        cluster_id="0123456789abcdef", state=state, placement={n: "pve1" for n in names},
        addresses={n: "192.0.2.110" for n in names}, vm_ids={n: 500 for n in names},
        profile=NetworkProfile(name="default", cidr="192.0.2.0/24", gateway="192.0.2.1", dns=["192.0.2.1"],
                               range_start="192.0.2.110", range_end="192.0.2.149"),
        template=TemplateRef("pve1", 8000), proxmox_endpoint="https://pve1.example.org:8006/",
        state_backend="local"))
    ws = open_workspace(tmp_path / "ws", "0123456789abcdef", files)

    lines: list[str] = []
    CliTerraformRunner(plugin_dir=str(plugins), log=lines.append).init(ws, {})

    assert any(f"bpg/proxmox v{version}" in line or f"v{version}" in line for line in lines)
    assert (ws.dir / ".terraform" / "providers" / "registry.terraform.io" / "bpg" / "proxmox" / version).is_dir()
    lock = (ws.dir / ".terraform.lock.hcl").read_text()
    assert f'version     = "{version}"' in lock


@pytest.mark.skipif(not shutil.which("terraform"), reason="terraform is not installed")
def test_init_with_a_plugin_dir_does_not_reach_for_the_network_when_the_provider_is_missing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    state = build_desired_state(TopologyPreset.single_node, "lab-c", "9.4.3")
    names = [n.name for n in state.nodes]
    files = render_workspace(RenderInput(
        cluster_id="0123456789abcdef", state=state, placement={n: "pve1" for n in names},
        addresses={n: "192.0.2.110" for n in names}, vm_ids={n: 500 for n in names},
        profile=NetworkProfile(name="default", cidr="192.0.2.0/24", gateway="192.0.2.1", dns=["192.0.2.1"],
                               range_start="192.0.2.110", range_end="192.0.2.149"),
        template=TemplateRef("pve1", 8000), proxmox_endpoint="https://pve1.example.org:8006/",
        state_backend="local"))
    ws = open_workspace(tmp_path / "ws", "0123456789abcdef", files)
    from app.provisioning.runner import TerraformError
    with pytest.raises(TerraformError):                       # fails closed instead of downloading
        CliTerraformRunner(plugin_dir=str(empty), log=lambda _: None).init(ws, {})


# ---- Ansible in the worker -------------------------------------------------------------------------------

LOCK = (BACKEND / "docker" / "ansible-requirements.txt").read_text()
REQUIREMENTS_IN = (BACKEND / "docker" / "ansible-requirements.in").read_text()
COLLECTIONS_YML = (BACKEND.parent / "infra" / "ansible" / "requirements.yml").read_text()


def lock_blocks() -> dict[str, str]:
    """Each pinned package in the lock file, with the text up to the next package."""
    parts = re.split(r"^(?=[A-Za-z0-9_.-]+==)", LOCK, flags=re.MULTILINE)
    return {p.split("==", 1)[0].lower(): p for p in parts if re.match(r"[A-Za-z0-9_.-]+==", p)}


def test_every_ansible_package_is_pinned_and_has_file_hashes():
    blocks = lock_blocks()
    assert {"ansible-core", "ansible-runner", "cryptography", "jinja2"} <= set(blocks)
    for name, block in blocks.items():
        hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", block)
        assert hashes, f"{name} has no hash in the lock file"
    assert "git+" not in LOCK and "http://" not in LOCK and "https://" not in LOCK.replace("# ", "")


def test_the_direct_requirements_are_exact_pins_and_the_lock_agrees_with_them():
    direct = re.findall(r"^([A-Za-z0-9_.-]+)==(\S+)$", REQUIREMENTS_IN, flags=re.MULTILINE)
    assert {n for n, _ in direct} == {"ansible-core", "ansible-runner"}
    for name, version in direct:
        assert re.search(rf"^{re.escape(name)}=={re.escape(version)}\b", LOCK, flags=re.MULTILINE), name


def test_ansible_is_installed_only_from_the_hash_locked_file_into_its_own_venv():
    ansible = stage("ansible")
    assert "python -m venv /opt/ansible" in ansible
    assert "--require-hashes" in ansible and "--no-deps" in ansible
    assert "-r /tmp/ansible-requirements.txt" in ansible
    assert "pip install" not in ansible.replace("/opt/ansible/bin/pip install --no-cache-dir --require-hashes "
                                                "--no-deps -r /tmp/ansible-requirements.txt", "")


@pytest.mark.parametrize("name", ["ANSIBLE_POSIX_SHA256", "COMMUNITY_GENERAL_SHA256"])
def test_every_collection_has_a_pinned_sha256(name):
    assert HEX64.match(arg(name))


def test_collections_go_through_the_verifying_helper_over_https_and_match_the_playbook_requirements():
    ansible = stage("ansible")
    assert ansible.count("fetch_tool.py fetch") == 2
    assert 'galaxy="https://' in ansible and "http://" not in ansible and "curl" not in ansible
    for collection, version_arg in (("ansible.posix", "ANSIBLE_POSIX_VERSION"),
                                    ("community.general", "COMMUNITY_GENERAL_VERSION")):
        m = re.search(rf"name: {re.escape(collection)}\s+version: (\S+)", COLLECTIONS_YML)
        assert m, f"{collection} is not pinned in infra/ansible/requirements.yml"
        assert arg(version_arg) == m.group(1), collection


def test_only_the_worker_has_ansible_and_ssh_and_the_lean_images_do_not():
    worker = stage("worker")
    assert "COPY --from=ansible /opt/ansible /opt/ansible" in worker
    assert "COPY --from=ecm_ansible . /opt/ecm/ansible" in worker
    assert "openssh-client" in worker and "--no-install-recommends" in worker
    for lean in (stage("base"), stage("app")):
        assert "ansible" not in lean.lower() and "openssh" not in lean


def test_the_venv_is_never_put_ahead_of_the_apps_python_on_the_path():
    worker = stage("worker")
    assert not re.search(r"PATH=\S*/opt/ansible/bin", worker)
    linked = re.search(r"for tool in ([^;]+?); do", worker).group(1).split()
    assert sorted(linked) == ["ansible", "ansible-galaxy", "ansible-playbook", "ansible-runner"]
    assert "ANSIBLE_COLLECTIONS_PATH=/opt/ansible/collections" in worker
    assert "ECM_ANSIBLE_DIR=/opt/ecm/ansible" in worker


def test_the_build_proves_as_the_app_user_that_ansible_ssh_and_the_playbooks_work():
    after_user = stage("worker").split("USER ecm", 1)[1]
    for needle in ("ansible-playbook --version", "ansible-runner --version", "ssh -V",
                   "ansible.posix", "community.general", "playbooks/create.yml", "playbooks/converge.yml"):
        assert needle in after_user, needle
    assert after_user.count("--syntax-check") == 2


def test_compose_gives_only_the_worker_the_playbooks():
    for service in ("migrate", "api", "web"):
        block = re.search(rf"^  {service}:\n(.*?)(?=^  \w|\Z)", COMPOSE, re.MULTILINE | re.DOTALL).group(1)
        assert "ecm_ansible" not in block, service
    worker = re.search(r"^  worker:\n(.*?)(?=^  \w|\Z)", COMPOSE, re.MULTILINE | re.DOTALL).group(1)
    assert re.search(r"additional_contexts:\s+ecm_ansible: \.\./infra/ansible", worker)
    assert (BACKEND.parent / "infra" / "ansible" / "playbooks" / "create.yml").is_file()


def test_compose_passes_the_terraform_parallelism_to_the_worker_with_a_safe_default():
    assert "ECM_TF_PARALLELISM: ${ECM_TF_PARALLELISM:-2}" in COMPOSE
    assert "ECM_TF_PARALLELISM" in (BACKEND.parent / "deploy" / ".env.example").read_text()
