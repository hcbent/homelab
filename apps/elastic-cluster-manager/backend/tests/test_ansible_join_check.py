"""The checks around adding nodes, run for real with ansible-playbook against the same kind of fake Elasticsearch as the
rolling restart's tests. They cover what runs on the worker: that the cluster is green with all its existing nodes before
a new node is started, and that the new nodes joined and the cluster is green afterwards. The plays that run on the new
machines over SSH (first boot, packages, certificate, start) are existing roles that a create already exercises; only a live
run shows them working on a new node.
"""
import json
import os
import shutil
import subprocess
import threading
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

import certifi
import pytest

from app.configmgmt import InventoryInput, render_inventory
from app.desired import TopologyPreset, build_desired_state
from tests.test_ansible_rolling_restart import API_KEY, FakeCluster, make_handler

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "infra" / "ansible"
pytestmark = pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible is not installed")
NEW = "lab-x-06"


def build(tmp_path: Path, phase: str):
    """A six-node cluster whose sixth node is new: absent for the 'before' phase, started but not yet joined for 'after'."""
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-x", "9.5.6", data_nodes=2, coordinating_nodes=1)
    names = [n.name for n in state.nodes]
    desired = {n.name: (n.cores, n.ram_mb) for n in state.nodes}
    present = names if phase == "after" else [n for n in names if n != NEW]
    fake = FakeCluster(present, {n: 500 + i for i, n in enumerate(present)}, dict.fromkeys(present, "pve1"),
                       {n: desired[n] for n in present})
    if phase == "after":
        fake.up[NEW] = False
        fake.joining[NEW] = 2                                  # it joins on the second health look
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(fake))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    inv = render_inventory(InventoryInput(
        state=state, addresses={n: f"192.0.2.{10 + i}" for i, n in enumerate(names)}, operation_kind="add_node",
        bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC), ssh_user="bret", ssh_key_path="/run/ecm/ssh/k",
        known_hosts_path="/tmp/kh", new_nodes=[NEW]))
    for host in inv["all"]["children"]["es_nodes"]["hosts"].values():
        host["ansible_host"] = "127.0.0.1"
    (tmp_path / "inventory.json").write_text(json.dumps(inv))
    port = server.server_address[1]
    extra = {"es_api_key": API_KEY, "es_ca_file": certifi.where(), "es_jc_scheme": "http", "es_jc_http_port": port,
             "es_jc_poll": 1, "es_jc_wait": 3, "es_join_phase": phase}
    (tmp_path / "extra.json").write_text(json.dumps(extra))

    def run(**more):
        env = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
        env["ANSIBLE_NOCOLOR"] = "1"
        args = ["ansible-playbook", "-i", str(tmp_path / "inventory.json"), "-e", f"@{tmp_path / 'extra.json'}"]
        for k, v in more.items():
            args += ["-e", f"{k}={v}"]
        result = subprocess.run([*args, "playbooks/join_check.yml"], cwd=ANSIBLE_DIR, env=env, capture_output=True,
                                text=True, timeout=120, check=False)
        server.shutdown()
        return result

    return fake, run


def test_before_a_healthy_cluster_with_all_its_existing_nodes_passes(tmp_path):
    fake, run = build(tmp_path, "before")
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(e[0] == "unauthorised" for e in fake.events)
    assert API_KEY not in result.stdout + result.stderr


def test_before_a_cluster_with_a_node_missing_stops_the_run_before_anything_is_started(tmp_path):
    fake, run = build(tmp_path, "before")
    fake.up["lab-x-03"] = False
    result = run()
    assert result.returncode != 0
    assert "Before the new nodes were started" in result.stdout and "Nothing was started" in result.stdout
    assert "4 nodes" in result.stdout


def test_after_a_new_node_that_joins_and_a_green_cluster_passes(tmp_path):
    fake, run = build(tmp_path, "after")
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert ("joined", NEW) in fake.events                      # it did not start joined: the check waited for it


def test_after_a_new_node_that_never_joins_fails_naming_it_and_says_the_machines_are_kept(tmp_path):
    fake, run = build(tmp_path, "after")
    fake.never_back = {NEW}
    result = run()
    assert result.returncode != 0
    out = result.stdout
    assert "The new nodes did not all join" in out and NEW in out and "5 of 6 nodes" in out
    assert "The machines are kept" in out and "safe to repeat" in out
    assert API_KEY not in out + result.stderr


def test_the_wrong_credentials_are_refused_and_said_so(tmp_path):
    fake, run = build(tmp_path, "before")
    result = run(es_api_key="a-wrong-key")
    assert result.returncode != 0 and any(e[0] == "unauthorised" for e in fake.events)
    assert "a-wrong-key" not in result.stdout + result.stderr


def test_the_add_node_playbook_passes_a_syntax_check_with_a_rendered_inventory(tmp_path):
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-x", "9.5.6", data_nodes=2, coordinating_nodes=1)
    names = [n.name for n in state.nodes]
    inv = render_inventory(InventoryInput(
        state=state, addresses={n: f"192.0.2.{10 + i}" for i, n in enumerate(names)}, operation_kind="add_node",
        bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC), ssh_user="bret", ssh_key_path="/run/ecm/ssh/k",
        known_hosts_path="/tmp/kh", new_nodes=[NEW]))
    (tmp_path / "inventory.json").write_text(json.dumps(inv))
    result = subprocess.run(["ansible-playbook", "--syntax-check", "-i", str(tmp_path / "inventory.json"),
                             "playbooks/add_node.yml"], cwd=ANSIBLE_DIR, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_the_node_role_starts_a_node_only_when_it_is_told_it_is_new():
    tasks = (ANSIBLE_DIR / "roles" / "es_node" / "tasks" / "main.yml").read_text()
    handlers = (ANSIBLE_DIR / "roles" / "es_node" / "handlers" / "main.yml").read_text()
    assert tasks.count("es_allow_restart | bool or es_start_node | default(false) | bool") == 2
    assert "when: es_allow_restart | bool or es_start_node | default(false) | bool" in handlers
    assert "when: not (es_allow_restart | bool or es_start_node | default(false) | bool)" in handlers
