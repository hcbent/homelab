"""The planned restart (the operator chooses the nodes, ECM plans the order): the rolling restart playbook run for real against a
small fake of Elasticsearch and Proxmox, built on the resize restart's fake. The fake keeps each node's uptime, so "this operation
already restarted it" can be tested, and a VM that is stopped, so "start it, don't restart it" can.

What these tests cannot show is how a real Proxmox starts a stopped VM, how long a real node takes to join, and whether a real
cluster's `_nodes/stats/jvm` gives the uptime field the way the fake does. Only a live run shows that."""
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import certifi
import pytest

from app.configmgmt import InventoryInput, render_inventory
from app.desired import TopologyPreset, build_desired_state
from tests.test_ansible_rolling_restart import (
    API_KEY,
    PVE_SECRET,
    PVE_TOKEN_ID,
    FakeCluster,
    make_handler,
)

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "infra" / "ansible"
pytestmark = pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible is not installed")
LONG_UP = 10 * 24 * 3600 * 1000          # a node that has been up for ten days, in milliseconds


class PlannedCluster(FakeCluster):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.uptime = dict.fromkeys(self.names, LONG_UP)
        self.stopped: set[str] = set()                         # nodes whose VM is stopped in Proxmox
        self._seen_up = 0

    def advance(self):
        """Let restarting nodes come back (the base class does it when something asks about the nodes)."""
        self.nodes_os()
        with self.lock:
            for e in self.events[self._seen_up:]:
                if e[0] == "up":
                    self.uptime[e[1]] = 3000                    # three seconds: it has just restarted
            self._seen_up = len(self.events)

    def start(self, host, vmid):
        with self.lock:
            name = next(n for n in self.names if self.hosts[n] == host and self.vmids[n] == vmid)
            self.events.append(("start", name, self.allocation, self.status()))
            upid = f"UPID:{host}:0002:{name}"
            self.tasks[upid] = name
            self.stopped.discard(name)
            self._rebooting[name] = 1
            return upid


def make_planned_handler(cluster: PlannedCluster):
    base = make_handler(cluster)

    class Handler(base):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/_nodes", "/_nodes/stats/jvm") or url.path.endswith("/status/current"):
                if not self._authorised(url.path):
                    return
                cluster.advance()
                if url.path == "/_nodes":
                    return self._send(200, {"nodes": {f"id-{n}": {"name": n} for n in cluster.names if cluster.up[n]}})
                if url.path == "/_nodes/stats/jvm":
                    return self._send(200, {"nodes": {f"id-{n}": {"name": n, "jvm": {"uptime_in_millis": cluster.uptime[n]}}
                                                      for n in cluster.names if cluster.up[n]}})
                parts = unquote(url.path).split("/")
                name = next(n for n in cluster.names if cluster.hosts[n] == parts[4] and cluster.vmids[n] == int(parts[6]))
                return self._send(200, {"data": {"status": "stopped" if name in cluster.stopped else "running"}})
            return super().do_GET()

        def do_POST(self):
            url = urlparse(self.path)
            if url.path.endswith("/status/start"):
                if not self._authorised(url.path):
                    return
                parts = url.path.split("/")
                return self._send(200, {"data": cluster.start(parts[4], int(parts[6]))})
            return super().do_POST()

    return Handler


NAMES = ["lab-x-01", "lab-x-02", "lab-x-03", "lab-x-04", "lab-x-05"]       # 01-03 masters, 04 data, 05 coordinating


def build(tmp_path: Path, plan, present=None, since_age=3600, **flags):
    """A five-node cluster, a fake for it, and a runner for the planned restart. `plan` is a list of (name, action)."""
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-x", "9.5.6", data_nodes=1, coordinating_nodes=1)
    names = [n.name for n in state.nodes]
    vmids = {n: 500 + i for i, n in enumerate(names)}
    hosts = {n: f"pve{i % 3 + 1}" for i, n in enumerate(names)}
    fake = PlannedCluster(names, vmids, hosts, {n.name: (n.cores, n.ram_mb) for n in state.nodes}, **flags)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_planned_handler(fake))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    inv = render_inventory(InventoryInput(
        state=state, addresses={n: f"192.0.2.{10 + i}" for i, n in enumerate(names)}, operation_kind="restart",
        bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC), ssh_user="bret", ssh_key_path="/run/ecm/ssh/k",
        known_hosts_path="/tmp/kh", vm_ids=vmids, placement=hosts))
    for host in inv["all"]["children"]["es_nodes"]["hosts"].values():
        host["ansible_host"] = "127.0.0.1"
    (tmp_path / "inventory.json").write_text(json.dumps(inv))
    port = server.server_address[1]
    extra = {"es_api_key": API_KEY, "es_ca_file": certifi.where(), "pve_api_url": f"http://127.0.0.1:{port}",
             "pve_token_id": PVE_TOKEN_ID, "pve_token_secret": PVE_SECRET, "pve_verify_tls": False,
             "es_rr_scheme": "http", "es_rr_http_port": port, "es_rr_poll": 1, "es_rr_health_wait": 3,
             "es_rr_pve_wait": 3, "es_rr_rejoin_wait": 3,
             "es_restart_plan": [{"name": n, "action": a} for n, a in plan],
             "es_restart_present": present if present is not None else [n for n in names if n not in
                                                                         {p for p, a in plan if a == "start"}],
             "es_restart_since": int(time.time()) - since_age}
    (tmp_path / "extra.json").write_text(json.dumps(extra))

    def run(**more):
        env = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
        env["ANSIBLE_NOCOLOR"] = "1"
        args = ["ansible-playbook", "-i", str(tmp_path / "inventory.json"), "-e", f"@{tmp_path / 'extra.json'}"]
        for k, v in more.items():
            args += ["-e", f"{k}={v}"]
        result = subprocess.run([*args, "playbooks/rolling_restart.yml"], cwd=ANSIBLE_DIR, env=env, capture_output=True,
                                text=True, timeout=180, check=False)
        server.shutdown()
        return result

    return fake, run


def done(fake, kind):
    return [e[1] for e in fake.events if e[0] == kind]


# -- restarting nodes the cluster has --------------------------------------------------------------------------------------

def test_the_named_nodes_are_restarted_in_the_planned_order_with_allocation_restricted_around_each(tmp_path):
    fake, run = build(tmp_path, [("lab-x-05", "restart"), ("lab-x-04", "restart"), ("lab-x-01", "restart")])
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert done(fake, "reboot") == ["lab-x-05", "lab-x-04", "lab-x-01"]              # exactly the order given, nothing else
    for _, name, allocation, status, nodes_up in (e for e in fake.events if e[0] == "reboot"):
        assert (allocation, status, nodes_up) == ("primaries", "green", 5), name
    trace = [f"allocation={e[1]}" if e[0] == "allocation" else e[0]
             for e in fake.events if e[0] in ("allocation", "flush", "reboot", "up")]
    assert trace == ["allocation=primaries", "flush", "reboot", "up", "allocation=None"] * 3
    assert fake.allocation is None and not any(e[0] == "unauthorised" for e in fake.events)
    assert API_KEY not in result.stdout + result.stderr and PVE_SECRET not in result.stdout + result.stderr


def test_a_node_that_was_restarted_since_the_operation_began_is_skipped_so_a_retry_resumes(tmp_path):
    fake, run = build(tmp_path, [("lab-x-05", "restart"), ("lab-x-04", "restart"), ("lab-x-01", "restart")])
    fake.uptime["lab-x-05"] = 60_000                                  # up for a minute, and the operation is an hour old
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert done(fake, "reboot") == ["lab-x-04", "lab-x-01"]
    assert "lab-x-05 was already restarted since this operation began, so it is skipped" in " ".join(result.stdout.split())


def test_a_node_that_has_been_up_longer_than_the_operation_has_existed_is_restarted_not_skipped(tmp_path):
    fake, run = build(tmp_path, [("lab-x-05", "restart")], since_age=120)
    fake.uptime["lab-x-05"] = 3 * 3600 * 1000                         # three hours: older than the two-minute-old operation
    assert run().returncode == 0 and done(fake, "reboot") == ["lab-x-05"]


def test_a_cluster_that_is_not_green_with_every_node_is_left_alone_when_the_plan_only_restarts(tmp_path):
    fake, run = build(tmp_path, [("lab-x-05", "restart")])
    fake.up["lab-x-03"] = False                                       # a node is down and not in the plan
    result = run()
    assert result.returncode != 0
    assert "before restarting lab-x-05" in result.stdout and "4 nodes" in result.stdout
    assert done(fake, "reboot") == [] and not any(e[0] in ("allocation", "flush") for e in fake.events)


def test_a_node_that_never_comes_back_stops_the_run_and_says_what_stays_restarted(tmp_path):
    fake, run = build(tmp_path, [("lab-x-05", "restart"), ("lab-x-04", "restart"), ("lab-x-01", "restart")])
    fake.never_back = {"lab-x-04"}
    result = run()
    assert result.returncode != 0
    assert done(fake, "reboot") == ["lab-x-05", "lab-x-04"]           # nothing after the one that failed
    out = result.stdout
    assert "The restart stopped at lab-x-04" in out and "still restricted to primaries" in out
    assert "Retry skips every node this operation has already restarted" in out
    assert fake.allocation == "primaries"


# -- starting a node that is down ---------------------------------------------------------------------------------------------

def test_a_node_that_is_down_with_a_stopped_vm_is_started_first_and_the_rest_are_restarted_after_it(tmp_path):
    fake, run = build(tmp_path, [("lab-x-04", "start"), ("lab-x-05", "restart"), ("lab-x-01", "restart")])
    fake.up["lab-x-04"] = False
    fake.stopped = {"lab-x-04"}
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert done(fake, "start") == ["lab-x-04"] and done(fake, "reboot") == ["lab-x-05", "lab-x-01"]
    order = [e[0] for e in fake.events if e[0] in ("start", "reboot")]
    assert order == ["start", "reboot", "reboot"]                      # the down node comes back before anything is restarted
    start = next(e for e in fake.events if e[0] == "start")
    assert start[2] is None                                            # a start does not restrict shard allocation
    assert all(e[2] == "primaries" for e in fake.events if e[0] == "reboot")
    assert fake.allocation is None and all(fake.up.values())


def test_a_node_that_is_down_but_whose_vm_is_running_is_restarted_not_started(tmp_path):
    fake, run = build(tmp_path, [("lab-x-04", "start")])               # planned as a start, but the VM is running now
    fake.up["lab-x-04"] = False
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert done(fake, "reboot") == ["lab-x-04"] and done(fake, "start") == []
    assert fake.up["lab-x-04"] and fake.allocation is None


def test_a_cluster_that_does_not_answer_stops_the_run_before_anything_is_started(tmp_path):
    fake, run = build(tmp_path, [("lab-x-04", "start")])
    fake.up["lab-x-04"] = False
    fake.stopped = {"lab-x-04"}
    result = run(es_api_key="a-wrong-key")
    assert result.returncode != 0 and any(e[0] == "unauthorised" for e in fake.events)
    assert done(fake, "start") == []
    assert "a-wrong-key" not in result.stdout + result.stderr


def test_the_playbook_needs_a_plan_that_names_someone_to_ask(tmp_path):
    fake, run = build(tmp_path, [("lab-x-05", "restart")], present=[])
    result = run()
    assert result.returncode != 0 and "needs the plan, the nodes that were in the cluster" in " ".join(result.stdout.split())
    assert done(fake, "reboot") == []


def test_the_playbook_passes_a_syntax_check_with_a_plan(tmp_path):
    _fake, run = build(tmp_path, [("lab-x-05", "restart")])
    args = ["ansible-playbook", "--syntax-check", "-i", str(tmp_path / "inventory.json"), "-e", f"@{tmp_path / 'extra.json'}",
            "playbooks/rolling_restart.yml"]
    result = subprocess.run(args, cwd=ANSIBLE_DIR, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert parse_qs("a=1") == {"a": ["1"]}                              # parse_qs is imported for the fake's sake
    run()
