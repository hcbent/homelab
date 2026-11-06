"""scripts/ecm_cli.py against a small fake ECM on localhost: what it sends, what it prints, and that the password
never appears in either output stream."""
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ecm_cli.py"
spec = importlib.util.spec_from_file_location("ecm_cli", SCRIPT)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

# A made-up login phrase; the neutral name keeps a secret scanner from mistaking this fake for a credential.
PHRASE = "correct-horse-battery-staple-9"
DIGEST = "a1" * 32


class FakeEcm:
    """Records every request. `routes[(method, path)]` is a list of (status, payload) served in order; the last
    one repeats."""

    def __init__(self):
        self.requests: list[dict] = []
        self.routes: dict[tuple[str, str], list[tuple[int, object]]] = {}
        self.url = ""

    def serve(self, method, path):
        queue = self.routes.get((method, path))
        if queue is None:
            return 404, {"detail": "not found"}
        return queue.pop(0) if len(queue) > 1 else queue[0]


def handler_for(fake: FakeEcm):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _handle(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            fake.requests.append({"method": method, "path": self.path, "body": body,
                                  "csrf": self.headers.get("x-ecm-csrf"), "cookie": self.headers.get("Cookie")})
            status, payload = fake.serve(method, self.path)
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            if self.path == "/api/auth/login" and status == 200:
                self.send_header("Set-Cookie", "ecm_session=tok123; Path=/; HttpOnly")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


@pytest.fixture
def ecm(monkeypatch):
    fake = FakeEcm()
    fake.routes[("POST", "/api/auth/login")] = [(200, {"username": "admin", "role": "admin"})]
    server = HTTPServer(("127.0.0.1", 0), handler_for(fake))
    fake.url = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ECM_URL", fake.url)
    monkeypatch.setenv("ECM_ADMIN_PASSWORD", PHRASE)
    monkeypatch.delenv("ECM_ADMIN_USERNAME", raising=False)
    yield fake
    server.shutdown()


def op(state="running", phase="plan", *, plan=None, logs=(), error=None, dry_run=False, result=None):
    return {"id": "op1", "kind": "tf.create", "state": state, "phase": phase, "error": error, "dry_run": dry_run,
            "progress": {"done": 2, "total": 6}, "result": result,
            "steps": [{"seq": 0, "name": "render", "status": "done", "detail": None}],
            "plan": plan, "logs": [{"ts": "t", "stream": "terraform", "line": line} for line in logs]}


PLAN = {"digest": DIGEST, "approvable": True,
        "summary": {"adds": 3, "updates": 0, "deletes": 0,
                    "configure": "install elasticsearch 9.5.6 on 3 nodes and start the cluster"}}
CREATED = {"cluster_id": "c1", "operation_id": "op1", "dry_run": True, "warnings": ["pve1 is over-committed"],
           "nodes": [{"name": f"lab-c-0{i}", "host": f"pve{i}", "address": f"192.168.10.11{i}", "vm_id": 502 + i}
                     for i in (1, 2, 3)]}


def run(*argv):
    return cli.main(list(argv))


def test_it_logs_in_with_the_csrf_header_and_never_prints_the_password(ecm, capsys):
    ecm.routes[("GET", "/api/operations/op1")] = [(200, op("succeeded", None, logs=["done"]))]
    assert run("show", "op1") == 0
    login, fetch = ecm.requests
    assert login["path"] == "/api/auth/login" and login["csrf"] == "1"
    assert login["body"] == {"username": "admin", "password": PHRASE}
    assert "ecm_session=tok123" in fetch["cookie"]                      # the session is reused
    out = capsys.readouterr()
    assert PHRASE not in out.out and PHRASE not in out.err


def test_a_create_is_a_dry_run_unless_real_is_given(ecm, capsys):
    ecm.routes[("POST", "/api/clusters")] = [(202, CREATED), (202, {**CREATED, "dry_run": False})]
    assert run("create", "lab-c", "9.5.6") == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "lab-c-01" in out and "192.168.10.111" in out and "over-committed" in out
    assert run("create", "lab-c", "9.5.6", "--real") == 0
    assert "REAL create" in capsys.readouterr().out
    bodies = [r["body"] for r in ecm.requests if r["path"] == "/api/clusters"]
    assert bodies[0] == {"name": "lab-c", "version": "9.5.6", "preset": "three_node", "dry_run": True}
    assert bodies[1]["dry_run"] is False and bodies[1]["name"] == "lab-c"
    assert all(r["csrf"] == "1" for r in ecm.requests)


def test_a_wrong_password_is_a_plain_error_not_a_traceback(ecm, capsys):
    ecm.routes[("POST", "/api/auth/login")] = [(401, {"detail": "Invalid credentials"})]
    assert run("show", "op1") == 1
    err = capsys.readouterr().err
    assert "401" in err and "Invalid credentials" in err and "Traceback" not in err and PHRASE not in err


def test_approve_shows_the_plan_first_and_then_posts_the_digest(ecm, capsys):
    ecm.routes[("GET", "/api/operations/op1")] = [(200, op("pending_approval", "approval", plan=PLAN))]
    ecm.routes[("POST", "/api/operations/op1/approve")] = [(202, {"id": "op1"})]
    assert run("approve", "op1", DIGEST) == 0
    out = capsys.readouterr().out
    assert "3 to add" in out and "install elasticsearch 9.5.6 on 3 nodes" in out and DIGEST in out
    paths = [(r["method"], r["path"]) for r in ecm.requests]
    assert paths.index(("GET", "/api/operations/op1")) < paths.index(("POST", "/api/operations/op1/approve"))
    assert ecm.requests[-1]["body"] == {"digest": DIGEST}


def test_a_refused_approval_prints_the_servers_reason_and_fails(ecm, capsys):
    ecm.routes[("GET", "/api/operations/op1")] = [(200, op("pending_approval", "approval", plan=PLAN))]
    ecm.routes[("POST", "/api/operations/op1/approve")] = [(409, {"detail": "the plan changed since you reviewed it"})]
    assert run("approve", "op1", "b2" * 32) == 1
    assert "the plan changed since you reviewed it" in capsys.readouterr().err


def test_watch_stops_at_the_approval_and_prints_the_exact_command_to_run(ecm, capsys):
    ecm.routes[("GET", "/api/operations/op1")] = [
        (200, op("running", "init", logs=["init ok"])),
        (200, op("pending_approval", "approval", plan=PLAN, logs=["init ok", "plan made"]))]
    assert run("watch", "op1", "--interval", "0") == 0
    out = capsys.readouterr().out
    assert "phase=init" in out and "phase=approval" in out and out.count("init ok") == 1   # each line once
    assert f"approve op1 {DIGEST}" in out


def test_a_dry_runs_plan_is_shown_as_not_approvable_and_no_approve_command_is_offered(ecm, capsys):
    plan = {**PLAN, "approvable": False}
    ecm.routes[("GET", "/api/operations/op1")] = [(200, op("pending_approval", "approval", plan=plan, dry_run=True))]
    assert run("watch", "op1", "--interval", "0") == 0
    out = capsys.readouterr().out
    assert "approvable: False" in out and "to approve" not in out


def test_watch_reports_a_failure_and_exits_nonzero(ecm, capsys):
    ecm.routes[("GET", "/api/operations/op1")] = [
        (200, op("failed", "configure", error="ansible-playbook failed: fatal: [lab-c-01]: FAILED!"))]
    assert run("watch", "op1", "--interval", "0") == 1
    assert "FAILED: ansible-playbook failed" in capsys.readouterr().out


def test_watch_prints_the_result_of_a_finished_operation(ecm, capsys):
    result = {"configured": {"cluster_uuid": "u1", "status": "green", "number_of_nodes": 3}}
    ecm.routes[("GET", "/api/operations/op1")] = [(200, op("succeeded", None, result=result))]
    assert run("watch", "op1", "--interval", "0") == 0
    assert '"status": "green"' in capsys.readouterr().out


def test_it_asks_for_the_password_when_none_is_set_and_does_not_echo_it(ecm, monkeypatch, capsys):
    monkeypatch.delenv("ECM_ADMIN_PASSWORD")
    prompts = []
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: prompts.append(prompt) or PHRASE)
    ecm.routes[("GET", "/api/operations/op1")] = [(200, op("succeeded", None))]
    assert run("show", "op1") == 0
    assert prompts == ["ECM admin password: "]
    assert ecm.requests[0]["body"]["password"] == PHRASE
    out = capsys.readouterr()
    assert PHRASE not in out.out + out.err


def test_an_unreachable_ecm_is_a_plain_error(monkeypatch, capsys):
    monkeypatch.setenv("ECM_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ECM_ADMIN_PASSWORD", PHRASE)
    assert run("show", "op1") == 1
    assert "could not reach" in capsys.readouterr().err


def test_retry_posts_to_the_retry_endpoint_and_says_an_approval_does_not_carry_over(ecm, capsys):
    ecm.routes[("POST", "/api/operations/op1/retry")] = [(202, {"id": "op1"})]
    assert run("retry", "op1") == 0
    assert ecm.requests[-1]["method"] == "POST" and ecm.requests[-1]["path"] == "/api/operations/op1/retry"
    assert "approve again" in capsys.readouterr().out


def test_retry_of_an_operation_that_cannot_be_retried_shows_the_reason(ecm, capsys):
    ecm.routes[("POST", "/api/operations/op1/retry")] = [(409, {"detail": "only a failed operation can be retried"})]
    assert run("retry", "op1") == 1
    assert "only a failed operation can be retried" in capsys.readouterr().err


def test_cleanup_sends_the_typed_name_and_only_accepts_data_loss_when_asked(ecm, capsys):
    ecm.routes[("POST", "/api/operations/op1/cleanup")] = [(202, {"id": "op2"})]
    assert run("cleanup", "op1", "lab-c") == 0
    assert ecm.requests[-1]["body"] == {"confirm_name": "lab-c", "confirm_data_loss": False}
    assert "destroys nothing until approved" in capsys.readouterr().out
    assert run("cleanup", "op1", "lab-c", "--data-loss") == 0
    assert ecm.requests[-1]["body"] == {"confirm_name": "lab-c", "confirm_data_loss": True}


def test_a_refused_cleanup_shows_why(ecm, capsys):
    ecm.routes[("POST", "/api/operations/op1/cleanup")] = [(409, {"detail": "this cluster has been bootstrapped"})]
    assert run("cleanup", "op1", "lab-c") == 1
    assert "has been bootstrapped" in capsys.readouterr().err
