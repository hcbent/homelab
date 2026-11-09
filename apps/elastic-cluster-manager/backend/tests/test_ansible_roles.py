"""Checks on the Ansible tree that need no VM. They cannot show the roles work on a host; only a run can."""
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.configmgmt import InventoryInput, KibanaHost, ephemeral_inventory
from app.desired import TopologyPreset, build_desired_state

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "infra" / "ansible"
KIBANA_KINDS = ("add_kibana", "restart_kibana", "kibana_login", "remove_kibana")
FORBIDDEN_IN_NAMES = ("secret", "token", "password")  # the parent .gitignore silently ignores these


def _inventory(kind: str) -> InventoryInput:
    state = build_desired_state(TopologyPreset.three_node, "lab-b", "9.4.3")
    return InventoryInput(
        state=state,
        addresses={n.name: f"192.0.2.{10 + i}" for i, n in enumerate(state.nodes)},
        operation_kind=kind,
        bootstrapped_at=None if kind == "create" else datetime(2026, 11, 5, tzinfo=UTC),
        ssh_user="ubuntu", ssh_key_path="/run/ecm/ssh/github_rsa",
        known_hosts_path="/tmp/ecm-run/known_hosts", artifacts_dir="/tmp/ecm-run/artifacts",
        kibana=[KibanaHost("lab-b-kb-01", "192.0.2.50")] if kind in KIBANA_KINDS else None,
    )


def test_no_file_in_the_ansible_tree_has_a_name_the_gitignore_would_hide():
    names = [p.name.lower() for p in ANSIBLE_DIR.rglob("*") if p.is_file()]
    assert names, "the Ansible tree is missing"
    bad = [n for n in names if any(word in n for word in FORBIDDEN_IN_NAMES)]
    assert bad == []


@pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible is not installed")
@pytest.mark.parametrize("kind", ["create", "converge", *KIBANA_KINDS])
def test_playbooks_pass_a_syntax_check_with_a_rendered_inventory(kind, tmp_path):
    with ephemeral_inventory(_inventory(kind), parent=str(tmp_path)) as inv:
        result = subprocess.run(
            ["ansible-playbook", "--syntax-check", "-i", str(inv), f"playbooks/{kind}.yml"],
            cwd=ANSIBLE_DIR, capture_output=True, text=True, timeout=120, check=False,
            env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin", "HOME": str(tmp_path),
                 "ANSIBLE_LOCAL_TEMP": str(tmp_path / "tmp")},
        )
    assert result.returncode == 0, result.stderr


def test_the_role_that_starts_nodes_never_restarts_without_the_flag():
    handlers = (ANSIBLE_DIR / "roles/es_node/handlers/main.yml").read_text()
    assert "when: es_allow_restart | bool" in handlers
    tasks = (ANSIBLE_DIR / "roles/es_node/tasks/main.yml").read_text()
    assert "state: restarted" not in tasks   # only the gated handler may restart


def test_os_base_installs_the_guest_agent():
    defaults = (ANSIBLE_DIR / "roles/os_base/defaults/main.yml").read_text()
    assert "qemu-guest-agent" in defaults
