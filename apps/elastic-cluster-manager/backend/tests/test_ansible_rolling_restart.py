"""The rolling restart playbook, run for real with ansible-playbook against a small fake that behaves like
Elasticsearch and Proxmox for the calls it makes. The fake keeps a simulated cluster (which nodes are up, what size
each runs at, the allocation setting), records every event in order, and refuses a request without the right
credentials, so the tests can say what happened, in what order, and in what state the cluster was at each step.

What these tests cannot show is how a real cluster and a real Proxmox behave: the waits, the real restart times and
whether Proxmox applies the size on the call this makes. Only a live run on a disposable cluster shows that.
"""
import json
import os
import shutil
import subprocess
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import certifi
import pytest

from app.configmgmt import InventoryInput, render_inventory
from app.desired import TopologyPreset, build_desired_state

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "infra" / "ansible"
API_KEY = "FakeEncodedEcmApiKeyForTheRollingRestartTests01"
PVE_SECRET = "fake-proxmox-token-secret-for-the-rolling-restart-01"
PVE_TOKEN_ID = "terraform@pve!ecm"

pytestmark = pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible is not installed")

RANK = {"red": 0, "yellow": 1, "green": 2}


class FakeCluster:
    """Elasticsearch and Proxmox in one: five nodes, three of them master-eligible (lab-x-01 to -03), lab-x-04 a data
    node, lab-x-05 coordinating-only. `desired` is the size a restart gives a node."""

    def __init__(self, names, vmids, hosts, desired, elected="lab-x-02"):
        self.lock = threading.Lock()
        self.names, self.vmids, self.hosts = names, vmids, hosts
        self.desired = desired                                   # name -> (cores, ram_mb)
        self.size = {n: (2, 4096) for n in names}                # what each node runs at now
        self.up = {n: True for n in names}
        self.elected = elected
        self.allocation = None
        self.never_back: set[str] = set()                        # restarted, and never rejoins
        self.task_fails: set[str] = set()                        # Proxmox reports the restart failed
        self.rejoin_polls = 0                                    # looks at _nodes/os before a restarted node is back
        self.green_after = 0                                     # looks at health, after rejoining, before green
        self.events: list[tuple] = []
        self._rebooting: dict[str, int] = {}
        self._yellow_for = 0
        self.tasks: dict[str, str] = {}

    # -- what the API says ------------------------------------------------------------------------

    def status(self) -> str:
        if not all(self.up.values()) or self._yellow_for > 0:
            return "yellow"
        return "green"

    def health(self, wait_for_status):
        with self.lock:
            status = self.status()
            if self._yellow_for > 0 and all(self.up.values()):
                self._yellow_for -= 1
            ok = wait_for_status is None or RANK[status] >= RANK[wait_for_status]
            body = {"status": status, "timed_out": not ok, "number_of_nodes": sum(self.up.values())}
            return (200 if ok else 408), body

    def nodes_os(self):
        with self.lock:
            for name in list(self._rebooting):
                if name in self.never_back:
                    continue
                self._rebooting[name] -= 1
                if self._rebooting[name] <= 0:
                    del self._rebooting[name]
                    self.up[name] = True
                    self.size[name] = self.desired[name]
                    self._yellow_for = self.green_after
                    self.events.append(("up", name))
            return {"nodes": {f"id-{n}": {"name": n, "os": {"available_processors": self.size[n][0],
                                                              "mem": {"total_in_bytes": int(self.size[n][1] * 0.97 * 1048576)}}}
                              for n in self.names if self.up[n]}}

    def reboot(self, host, vmid):
        with self.lock:
            name = next(n for n in self.names if self.hosts[n] == host and self.vmids[n] == vmid)
            self.events.append(("reboot", name, self.allocation, self.status(), sum(self.up.values())))
            upid = f"UPID:{host}:0001:{name}"
            self.tasks[upid] = name
            if name not in self.task_fails:
                self.up[name] = False
                self._rebooting[name] = self.rejoin_polls + 1
            return upid

    def task_status(self, upid):
        name = self.tasks[upid]
        exit_ok = name not in self.task_fails
        return {"data": {"status": "stopped", "exitstatus": "OK" if exit_ok else "start failed: exit code 1"}}


def make_handler(cluster: FakeCluster):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorised(self, path):
            header = self.headers.get("Authorization", "")
            if path.startswith("/api2/json/"):
                ok = header == f"PVEAPIToken={PVE_TOKEN_ID}={PVE_SECRET}"
            else:
                ok = header == f"ApiKey {API_KEY}"
            if not ok:
                cluster.events.append(("unauthorised", path))
                self._send(401, {"error": "bad credentials"})
            return ok

        def do_GET(self):
            url = urlparse(self.path)
            if not self._authorised(url.path):
                return
            query = parse_qs(url.query)
            if url.path == "/_cluster/health":
                status, body = cluster.health((query.get("wait_for_status") or [None])[0])
                return self._send(status, body)
            if url.path == "/_nodes/os":
                return self._send(200, cluster.nodes_os())
            if url.path == "/_cat/master":
                return self._send(200, [{"node": cluster.elected}])
            if url.path.startswith("/api2/json/nodes/") and url.path.endswith("/status"):
                return self._send(200, cluster.task_status(unquote(url.path.split("/tasks/")[1].rsplit("/status", 1)[0])))
            self._send(404, {"error": url.path})

        def do_PUT(self):
            url = urlparse(self.path)
            if not self._authorised(url.path):
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if url.path == "/_cluster/settings":
                value = body["persistent"]["cluster.routing.allocation.enable"]
                with cluster.lock:
                    cluster.allocation = value
                    cluster.events.append(("allocation", value))
                return self._send(200, {"acknowledged": True})
            self._send(404, {"error": url.path})

        def do_POST(self):
            url = urlparse(self.path)
            if not self._authorised(url.path):
                return
            n = int(self.headers.get("Content-Length", 0))
            if n:
                self.rfile.read(n)
            if url.path == "/_flush":
                cluster.events.append(("flush",))
                return self._send(200, {"_shards": {}})
            parts = url.path.split("/")
            if url.path.startswith("/api2/json/nodes/") and url.path.endswith("/status/reboot"):
                upid = cluster.reboot(parts[4], int(parts[6]))
                return self._send(200, {"data": upid})
            self._send(404, {"error": url.path})

    return Handler


def build(tmp_path: Path, **overrides):
    """A five-node cluster, its inventory and extra vars, and a running fake. Returns (fake, runner)."""
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-x", "9.5.6", data_nodes=1, coordinating_nodes=1)
    names = [n.name for n in state.nodes]
    for node in state.nodes:
        node.cores, node.ram_mb = 4, 8192                                    # the target; the fake starts at 2 and 4096
    vmids = {n: 500 + i for i, n in enumerate(names)}
    hosts = {n: f"pve{i % 3 + 1}" for i, n in enumerate(names)}
    desired = {n.name: (n.cores, n.ram_mb) for n in state.nodes}
    fake = FakeCluster(names, vmids, hosts, desired, **overrides)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(fake))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    inv = render_inventory(InventoryInput(
        state=state, addresses={n: f"192.0.2.{10 + i}" for i, n in enumerate(names)}, operation_kind="restart",
        bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC), ssh_user="bret", ssh_key_path="/run/ecm/ssh/k",
        known_hosts_path="/tmp/kh", vm_ids=vmids, placement=hosts))
    for host in inv["all"]["children"]["es_nodes"]["hosts"].values():
        host["ansible_host"] = "127.0.0.1"                                   # every node answers from the one fake
    (tmp_path / "inventory.json").write_text(json.dumps(inv))
    ca = Path(certifi.where())                                               # uri loads the CA file even for http
    port = server.server_address[1]
    extra = {"es_api_key": API_KEY, "es_ca_file": str(ca), "pve_api_url": f"http://127.0.0.1:{port}",
             "pve_token_id": PVE_TOKEN_ID, "pve_token_secret": PVE_SECRET, "pve_verify_tls": False,
             "es_rr_scheme": "http", "es_rr_http_port": port, "es_rr_poll": 1, "es_rr_health_wait": 2,
             "es_rr_pve_wait": 2, "es_rr_rejoin_wait": 2}
    (tmp_path / "extra.json").write_text(json.dumps(extra))

    def run(**more):
        env = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
        env["ANSIBLE_NOCOLOR"] = "1"
        args = ["ansible-playbook", "-i", str(tmp_path / "inventory.json"), "-e", f"@{tmp_path / 'extra.json'}"]
        for k, v in more.items():
            args += ["-e", f"{k}={v}"]
        result = subprocess.run([*args, "playbooks/rolling_restart.yml"], cwd=ANSIBLE_DIR, env=env,
                                capture_output=True, text=True, timeout=180, check=False)
        server.shutdown()
        return result

    return fake, run


def reboots(fake):
    return [e for e in fake.events if e[0] == "reboot"]


def test_every_node_is_restarted_in_order_masters_last_with_allocation_restricted_around_each(tmp_path):
    fake, run = build(tmp_path)
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    # coordinating-only first, then data, then master-eligible nodes with the elected master (lab-x-02) last
    assert [e[1] for e in reboots(fake)] == ["lab-x-05", "lab-x-04", "lab-x-01", "lab-x-03", "lab-x-02"]
    for _, name, allocation, status, nodes_up in reboots(fake):
        assert (allocation, status, nodes_up) == ("primaries", "green", 5), name   # held steady around every restart
    assert fake.allocation is None and fake.size == fake.desired
    # for each node: restrict, flush, restart, rejoin, allow again, in that order, before the next node starts
    trace = [f"allocation={e[1]}" if e[0] == "allocation" else e[0]
             for e in fake.events if e[0] in ("allocation", "flush", "reboot", "up")]
    assert trace == ["allocation=primaries", "flush", "reboot", "up", "allocation=None"] * 5
    assert not any(e[0] == "unauthorised" for e in fake.events)
    assert API_KEY not in result.stdout + result.stderr and PVE_SECRET not in result.stdout + result.stderr


def test_nodes_already_at_their_target_size_are_skipped_so_a_retry_resumes(tmp_path):
    fake, run = build(tmp_path)
    for name in ("lab-x-05", "lab-x-04", "lab-x-01", "lab-x-02"):
        fake.size[name] = fake.desired[name]                                  # done by an earlier run
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert [e[1] for e in reboots(fake)] == ["lab-x-03"]


def test_when_every_node_is_at_its_target_size_nothing_is_restarted_or_changed(tmp_path):
    fake, run = build(tmp_path)
    fake.size = dict(fake.desired)
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "nothing to restart" in result.stdout
    assert reboots(fake) == [] and not any(e[0] in ("allocation", "flush") for e in fake.events)


def test_a_cluster_that_is_not_green_with_every_node_present_is_left_alone(tmp_path):
    fake, run = build(tmp_path)
    fake.up["lab-x-03"] = False                                               # a node is already down
    result = run()
    assert result.returncode != 0
    assert "before any node is restarted" in result.stdout and "4 nodes" in result.stdout
    assert reboots(fake) == [] and not any(e[0] in ("allocation", "flush") for e in fake.events)


def test_a_node_that_never_comes_back_stops_the_run_and_allocation_stays_restricted_with_a_warning(tmp_path):
    fake, run = build(tmp_path)
    fake.size["lab-x-05"] = fake.desired["lab-x-05"]                          # an earlier run did this one
    fake.never_back = {"lab-x-04"}
    result = run()
    assert result.returncode != 0
    assert [e[1] for e in reboots(fake)] == ["lab-x-04"]                      # and nothing after the one that failed
    assert fake.allocation == "primaries"                                     # not every node is present, so it is left
    out = result.stdout
    assert "stopped at lab-x-04" in out and "still restricted to primaries" in out
    assert "Nodes restarted before this one stay restarted" in out
    assert API_KEY not in out + result.stderr and PVE_SECRET not in out + result.stderr


def test_a_restart_proxmox_reports_failed_stops_the_run_and_allocation_is_allowed_again(tmp_path):
    fake, run = build(tmp_path)
    fake.size["lab-x-05"] = fake.desired["lab-x-05"]
    fake.task_fails = {"lab-x-04"}                                            # the node stays up; the restart failed
    result = run()
    assert result.returncode != 0
    assert [e[1] for e in reboots(fake)] == ["lab-x-04"]
    assert fake.allocation is None                                            # every node is present, so it is restored
    assert "stopped at lab-x-04" in result.stdout and "Shard allocation was allowed again" in result.stdout


def test_a_restarted_node_is_waited_for_and_so_is_green_before_the_next(tmp_path):
    fake, run = build(tmp_path)
    for name in ("lab-x-05", "lab-x-04", "lab-x-01"):
        fake.size[name] = fake.desired[name]
    fake.rejoin_polls = 1                                                     # one extra look before a node is back
    fake.green_after = 1                                                      # and one before the cluster is green
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert [e[1] for e in reboots(fake)] == ["lab-x-03", "lab-x-02"]
    assert all(status == "green" for _, _, _, status, _ in reboots(fake))     # never started on a cluster that was not


def test_the_wrong_credentials_are_refused_and_nothing_is_changed(tmp_path):
    fake, run = build(tmp_path)
    result = run(es_api_key="a-wrong-key")
    assert result.returncode != 0
    assert reboots(fake) == [] and any(e[0] == "unauthorised" for e in fake.events)
    assert "a-wrong-key" not in result.stdout + result.stderr


def test_the_playbook_passes_a_syntax_check(tmp_path):
    inventory = tmp_path / "inventory.ini"
    inventory.write_text("[es_nodes]\nnode1 ansible_host=192.0.2.10\nnode2 ansible_host=192.0.2.11\n")
    result = subprocess.run(["ansible-playbook", "--syntax-check", "-i", str(inventory),
                             "playbooks/rolling_restart.yml"], cwd=ANSIBLE_DIR, capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stderr
