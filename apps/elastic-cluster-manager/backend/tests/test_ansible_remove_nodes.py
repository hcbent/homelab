"""The remove-nodes playbook (the drain before Terraform, the check after it), run for real with ansible-playbook against a
small fake that behaves like Elasticsearch for the calls it makes, built on the rolling restart's fake. The fake records
every event in order, so the tests can say what happened and in what state the cluster was.

What these tests cannot show is how a real cluster answers the node shutdown API (the shapes below are from knowledge of
it, not from a real response), how long a real drain takes, or whether Elasticsearch re-forms its voting configuration by
itself when masters leave. Only a live run on a disposable cluster shows that.
"""
import json
import os
import shutil
import subprocess
import threading
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import certifi
import pytest

from app.configmgmt import InventoryInput, render_inventory
from app.desired import TopologyPreset, build_desired_state
from tests.test_ansible_rolling_restart import API_KEY, FakeCluster, make_handler

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "infra" / "ansible"
pytestmark = pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible is not installed")
GOING = ["lab-x-07", "lab-x-08"]


class RemovalCluster(FakeCluster):
    """Six nodes that remain and two that are going. `shards` is a list of (index, shard, node, state)."""

    def __init__(self, remaining, going, shards):
        names = [*remaining, *going]
        super().__init__(names, {n: 500 + i for i, n in enumerate(names)}, dict.fromkeys(names, "pve1"),
                         {n: (2, 4096) for n in names}, elected=remaining[0])
        self.going, self.shards = set(going), shards
        self.records: dict[str, str] = {}              # node id -> the node's name, for each shutdown that was asked for
        self.drain_polls = 2                           # looks at a node's shutdown before it says COMPLETE
        self.stalled: set[str] = set()
        self.gone: set[str] = set()                    # nodes the cluster no longer has (Terraform destroyed them)
        self.status_override: str | None = None
        self._polls: dict[str, int] = {}

    def present(self):
        return [n for n in self.names if n not in self.gone]

    def health(self, wait_for_status):
        with self.lock:
            status = self.status_override or "green"
            ok = wait_for_status is None or status == "green" or wait_for_status != "green"
            return (200 if ok else 408), {"status": status, "timed_out": not ok, "number_of_nodes": len(self.present())}

    def shutdown_status(self, node_id):
        with self.lock:
            name = node_id.removeprefix("id-")
            self._polls[node_id] = self._polls.get(node_id, 0) + 1
            if name in self.stalled:
                st = {"status": "STALLED", "shard_migration": {"status": "STALLED", "shard_migrations_remaining": 3,
                                                                "explanation": "no node can take the shard logs[0]"}}
            elif self._polls[node_id] >= self.drain_polls:
                st = {"status": "COMPLETE", "shard_migration": {"status": "COMPLETE", "shard_migrations_remaining": 0}}
            else:
                st = {"status": "IN_PROGRESS", "shard_migration": {"status": "IN_PROGRESS", "shard_migrations_remaining": 2}}
            return {"nodes": [{"node_id": node_id, "type": "REMOVE", **st}]}


def make_removal_handler(cluster: RemovalCluster):
    base = make_handler(cluster)

    class Handler(base):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/_nodes", "/_nodes/shutdown", "/_cat/shards") or url.path.endswith("/shutdown"):
                if not self._authorised(url.path):
                    return
                if url.path == "/_nodes":
                    return self._send(200, {"nodes": {f"id-{n}": {"name": n} for n in cluster.present()}})
                if url.path == "/_cat/shards":
                    return self._send(200, [{"index": i, "shard": str(s), "state": st, "node": n}
                                            for i, s, n, st in cluster.shards])
                if url.path == "/_nodes/shutdown":
                    return self._send(200, {"nodes": [{"node_id": nid, "type": "REMOVE", "status": "COMPLETE"}
                                                      for nid in cluster.records]})
                return self._send(200, cluster.shutdown_status(url.path.split("/")[2]))
            return super().do_GET()

        def do_PUT(self):
            url = urlparse(self.path)
            if url.path.endswith("/shutdown"):
                if not self._authorised(url.path):
                    return
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                assert body["type"] == "remove" and body["reason"]
                node_id = url.path.split("/")[2]
                with cluster.lock:
                    cluster.records[node_id] = node_id.removeprefix("id-")
                    cluster.events.append(("shutdown", node_id.removeprefix("id-"), cluster.status_override or "green"))
                return self._send(200, {"acknowledged": True})
            return super().do_PUT()

        def do_DELETE(self):
            url = urlparse(self.path)
            if not self._authorised(url.path):
                return
            node_id = url.path.split("/")[2]
            with cluster.lock:
                cluster.events.append(("delete_shutdown", node_id.removeprefix("id-")))
                cluster.records.pop(node_id, None)
            return self._send(200, {"acknowledged": True})

    return Handler


def build(tmp_path: Path, phase: str, shards=None, **flags):
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-x", "9.5.6", data_nodes=2, coordinating_nodes=1)
    remaining = [n.name for n in state.nodes]
    fake = RemovalCluster(remaining, GOING, shards if shards is not None else [
        ("logs", 0, "lab-x-04", "STARTED"), ("logs", 0, "lab-x-05", "STARTED"),
        ("logs", 1, "lab-x-07", "STARTED"), ("logs", 1, "lab-x-04", "STARTED")])
    if phase == "after":
        fake.gone = set(GOING)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_removal_handler(fake))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    inv = render_inventory(InventoryInput(
        state=state, addresses={n: f"192.0.2.{10 + i}" for i, n in enumerate(remaining)},
        operation_kind="remove_drain" if phase == "drain" else "remove_check",
        bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC), ssh_user="bret", ssh_key_path="/run/ecm/ssh/k",
        known_hosts_path="/tmp/kh", removing=GOING))
    for host in inv["all"]["children"]["es_nodes"]["hosts"].values():
        host["ansible_host"] = "127.0.0.1"
    (tmp_path / "inventory.json").write_text(json.dumps(inv))
    extra = {"es_api_key": API_KEY, "es_ca_file": certifi.where(), "es_dr_scheme": "http",
             "es_dr_http_port": server.server_address[1], "es_dr_poll": 1, "es_dr_health_wait": 3, "es_dr_drain_wait": 6,
             "es_dr_phase": phase}
    (tmp_path / "extra.json").write_text(json.dumps(extra))

    def run(**more):
        env = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
        env["ANSIBLE_NOCOLOR"] = "1"
        args = ["ansible-playbook", "-i", str(tmp_path / "inventory.json"), "-e", f"@{tmp_path / 'extra.json'}"]
        for k, v in more.items():
            args += ["-e", f"{k}={v}"]
        result = subprocess.run([*args, "playbooks/remove_nodes.yml"], cwd=ANSIBLE_DIR, env=env, capture_output=True,
                                text=True, timeout=180, check=False)
        server.shutdown()
        return result

    return fake, run


def shutdowns(fake):
    return [e for e in fake.events if e[0] == "shutdown"]


# -- the drain ----------------------------------------------------------------------------------------------------------

def test_a_healthy_cluster_has_every_node_going_emptied_and_nothing_cancelled(tmp_path):
    fake, run = build(tmp_path, "drain")
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(e[1] for e in shutdowns(fake)) == GOING and all(e[2] == "green" for e in shutdowns(fake))
    assert not any(e[0] in ("delete_shutdown", "unauthorised") for e in fake.events)
    assert "no longer hold any shards" in result.stdout
    assert API_KEY not in result.stdout + result.stderr


def test_a_node_that_stalls_cancels_every_shutdown_and_says_nothing_was_destroyed(tmp_path):
    fake, run = build(tmp_path, "drain")
    fake.stalled = {"lab-x-08"}
    result = run()
    assert result.returncode != 0
    out = result.stdout
    assert "Elasticsearch could not empty every node: lab-x-08 is STALLED (no node can take the shard logs[0])" in out
    assert "Nothing was destroyed" in out and "was cancelled" in out and "Retry plans the removal again" in out
    assert sorted(e[1] for e in fake.events if e[0] == "delete_shutdown") == GOING          # both are put back, not just one
    assert not fake.records
    assert API_KEY not in out + result.stderr


def test_a_drain_that_never_finishes_cancels_too(tmp_path):
    fake, run = build(tmp_path, "drain")
    fake.drain_polls = 1000
    result = run()
    assert result.returncode != 0 and "Nothing was destroyed" in result.stdout
    assert sorted(e[1] for e in fake.events if e[0] == "delete_shutdown") == GOING


def test_a_cluster_that_is_not_green_drains_nothing(tmp_path):
    fake, run = build(tmp_path, "drain")
    fake.status_override = "yellow"
    result = run()
    assert result.returncode != 0 and "so no node was drained" in result.stdout and "yellow" in result.stdout
    assert not shutdowns(fake)


def test_a_shard_whose_last_copy_is_on_a_node_going_stops_the_drain_before_it_starts(tmp_path):
    fake, run = build(tmp_path, "drain", shards=[("logs", 0, "lab-x-04", "STARTED"), ("solo", 0, "lab-x-07", "STARTED")])
    result = run()
    assert result.returncode != 0
    assert "1 shard would have no copy left (solo[0])" in " ".join(result.stdout.split())
    assert "Nothing was destroyed" in result.stdout
    assert not shutdowns(fake)


def test_a_shard_that_is_not_started_stops_the_drain_too(tmp_path):
    fake, run = build(tmp_path, "drain", shards=[("logs", 0, "lab-x-04", "STARTED"), ("logs", 0, "lab-x-05", "UNASSIGNED")])
    result = run()
    assert result.returncode != 0 and "not started" in result.stdout
    assert not shutdowns(fake)


def test_nodes_that_are_already_gone_need_no_drain_so_a_retry_after_the_apply_passes(tmp_path):
    fake, run = build(tmp_path, "drain")
    fake.gone = set(GOING)
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "there is nothing to drain" in result.stdout.replace("\n", " ")
    assert not shutdowns(fake)


def test_one_node_gone_and_one_still_there_drains_only_the_one_that_is_there(tmp_path):
    fake, run = build(tmp_path, "drain")
    fake.gone = {"lab-x-07"}
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert [e[1] for e in shutdowns(fake)] == ["lab-x-08"]


def test_the_wrong_credentials_are_refused_and_said_so(tmp_path):
    fake, run = build(tmp_path, "drain")
    result = run(es_api_key="a-wrong-key")
    assert result.returncode != 0 and any(e[0] == "unauthorised" for e in fake.events)
    assert "a-wrong-key" not in result.stdout + result.stderr
    assert not shutdowns(fake)


# -- the check afterwards ---------------------------------------------------------------------------------------------

def test_after_the_machines_are_gone_a_green_cluster_passes_and_the_leftover_records_are_cleared(tmp_path):
    fake, run = build(tmp_path, "after")
    fake.records = {"id-lab-x-07": "lab-x-07", "id-lab-x-08": "lab-x-08", "id-lab-x-02": "lab-x-02"}   # 02 is still a member
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(e[1] for e in fake.events if e[0] == "delete_shutdown") == GOING          # never a member's record
    assert "id-lab-x-02" in fake.records


def test_after_a_cluster_that_still_counts_a_removed_node_fails_and_clears_nothing(tmp_path):
    fake, run = build(tmp_path, "after")
    fake.gone = {"lab-x-07"}                                                                  # 08 is still being counted
    result = run()
    assert result.returncode != 0 and "not green with the 6 nodes that remain" in result.stdout.replace("\n", " ")
    assert not any(e[0] == "delete_shutdown" for e in fake.events)


def test_after_a_cluster_that_is_not_green_fails(tmp_path):
    fake, run = build(tmp_path, "after")
    fake.status_override = "yellow"
    result = run()
    assert result.returncode != 0 and "yellow" in result.stdout


def test_the_playbook_passes_a_syntax_check_for_both_kinds_of_inventory(tmp_path):
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-x", "9.5.6", data_nodes=2, coordinating_nodes=1)
    names = [n.name for n in state.nodes]
    for kind in ("remove_drain", "remove_check"):
        inv = render_inventory(InventoryInput(
            state=state, addresses={n: f"192.0.2.{10 + i}" for i, n in enumerate(names)}, operation_kind=kind,
            bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC), ssh_user="bret", ssh_key_path="/run/ecm/ssh/k",
            known_hosts_path="/tmp/kh", removing=GOING))
        assert inv["all"]["vars"]["es_removing"] == GOING and inv["all"]["vars"]["es_expected_nodes"] == 6
        (tmp_path / "inventory.json").write_text(json.dumps(inv))
        result = subprocess.run(["ansible-playbook", "--syntax-check", "-i", str(tmp_path / "inventory.json"),
                                 "playbooks/remove_nodes.yml"], cwd=ANSIBLE_DIR, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
