"""Running Terraform: the interface the rest of ECM depends on, and the real command-line implementation.

Safety properties, each covered by a test:
  * the subprocess gets a minimal environment, never ECM's own (so the master key and admin hash cannot leak
    into Terraform or a provisioner); only the credentials the caller passes in are added
  * every output line is redacted before it is logged, and the credentials are registered for redaction
  * apply only ever applies a saved plan file, and nothing here ever destroys on failure: a failed apply
    leaves the partial state in place and reports what exists, so the operator chooses what happens next
  * a run that exceeds its time limit is interrupted (SIGINT first, so Terraform can release its lock and
    flush state), and only killed if it ignores that
"""
import json
import os
import re
import signal
import subprocess
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import unquote

from app.crypto import redact, register_secret
from app.provisioning.plan import PlanSummary, summarize_plan
from app.provisioning.workspace import PLAN_FILE, Workspace


def _url_password(value: str) -> list[str]:
    """What to mask from a URL such as postgresql://user:pw@host/db: the password as written and decoded, and
    the pieces of it a URL parser may stop at and echo back.

    This is deliberately lenient. A password with a raw # / or ? makes a strict parser see no userinfo at all,
    and Terraform then prints the part of the URL it kept, which is the start of the password. So the userinfo
    is everything up to the last @, and the password is split at the characters that end a URL component.
    """
    scheme_end = value.find("://")
    if scheme_end < 0:
        return []
    userinfo, at, _ = value[scheme_end + 3:].rpartition("@")
    if not at or ":" not in userinfo:
        return []
    password = userinfo.split(":", 1)[1]
    forms = {password, unquote(password)}  # as written, and decoded
    pieces = {piece for form in forms for piece in re.split(r"[#/?]", form)}
    return sorted(p for p in forms | pieces if p)


class TerraformError(Exception):
    """Terraform could not run or reported an error. The message is already redacted."""


@dataclass
class PlanOutcome:
    has_changes: bool
    summary: PlanSummary


@dataclass
class ApplyOutcome:
    ok: bool
    error: str | None = None
    resources_in_state: list[str] = field(default_factory=list)  # what exists now, even after a failure
    outputs: dict = field(default_factory=dict)  # non-sensitive outputs only


class TerraformRunner(Protocol):
    def init(self, ws: Workspace, env: Mapping[str, str]) -> None: ...

    def plan(self, ws: Workspace, env: Mapping[str, str], *, destroy: bool = False) -> PlanOutcome: ...

    def apply(self, ws: Workspace, env: Mapping[str, str]) -> ApplyOutcome: ...


class CliTerraformRunner:
    def __init__(
        self,
        binary: str = "terraform",
        plugin_dir: str | None = None,
        log: Callable[[str], None] | None = None,
        lock_timeout: str = "60s",
        parallelism: int = 2,
        plan_timeout: float = 600,
        apply_timeout: float = 3600,
        interrupt_grace: float = 30,
    ):
        self.binary = binary
        self.plugin_dir = plugin_dir
        self.log = log or (lambda line: None)
        self.lock_timeout = lock_timeout
        self.parallelism = parallelism
        self.plan_timeout = plan_timeout
        self.apply_timeout = apply_timeout
        self.interrupt_grace = interrupt_grace

    # ---- process plumbing -----------------------------------------------------------------------

    def _env(self, ws: Workspace, extra: Mapping[str, str]) -> dict[str, str]:
        for value in extra.values():
            register_secret(value)  # anything Terraform echoes back is masked
            for part in _url_password(value):
                register_secret(part)  # and so is the password on its own, in case only a piece is echoed
        home = ws.dir / ".tfhome"
        home.mkdir(exist_ok=True)
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(home),
            "TF_IN_AUTOMATION": "1",
            "TF_INPUT": "0",
            "CHECKPOINT_DISABLE": "1",  # no version-check or telemetry calls
        }
        env.update(extra)
        return env

    def _run(self, args: list[str], ws: Workspace, env: dict[str, str], timeout: float) -> tuple[int, list[str]]:
        """Run Terraform, streaming redacted lines to the log. Returns (exit code, last lines)."""
        try:
            proc = subprocess.Popen([self.binary, *args], cwd=ws.dir, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)
        except FileNotFoundError as exc:
            raise TerraformError(f"the terraform binary was not found ({self.binary})") from exc

        timed_out = threading.Event()

        def interrupt() -> None:
            timed_out.set()
            proc.send_signal(signal.SIGINT)  # lets Terraform release its lock and write state
            killer = threading.Timer(self.interrupt_grace, proc.kill)
            killer.daemon = True
            killer.start()

        timer = threading.Timer(timeout, interrupt)
        timer.daemon = True
        timer.start()
        tail: deque[str] = deque(maxlen=40)
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = redact(raw.rstrip("\n"))
                tail.append(line)
                self.log(line)
            code = proc.wait()
        finally:
            timer.cancel()
        if timed_out.is_set():
            raise TerraformError(f"terraform {args[0]} timed out after {timeout:g}s and was interrupted")
        return code, list(tail)

    def _capture(self, args: list[str], ws: Workspace, env: dict[str, str], timeout: float = 120) -> str:
        """Run a read-only command and return its output without logging it (it can be large JSON)."""
        try:
            out = subprocess.run([self.binary, *args], cwd=ws.dir, env=env, capture_output=True, text=True,
                                 timeout=timeout, check=False)
        except FileNotFoundError as exc:
            raise TerraformError(f"the terraform binary was not found ({self.binary})") from exc
        except subprocess.TimeoutExpired as exc:
            raise TerraformError(f"terraform {args[0]} timed out") from exc
        if out.returncode != 0:
            raise TerraformError(redact(f"terraform {args[0]} failed: {out.stderr.strip()[-500:]}"))
        return out.stdout

    @staticmethod
    def _failure(command: str, tail: list[str]) -> TerraformError:
        errors = [line for line in tail if "Error" in line]
        detail = " ".join(errors[-3:]) if errors else " ".join(tail[-5:])
        return TerraformError(f"terraform {command} failed: {detail}".strip())

    # ---- the interface --------------------------------------------------------------------------

    def init(self, ws: Workspace, env: Mapping[str, str]) -> None:
        full = self._env(ws, env)
        args = ["init", "-input=false", "-no-color"]
        if self.plugin_dir:
            args += [f"-plugin-dir={self.plugin_dir}"]  # a vendored provider; nothing is downloaded
        code, tail = self._run(args, ws, full, self.plan_timeout)
        if code != 0:
            raise self._failure("init", tail)

    def plan(self, ws: Workspace, env: Mapping[str, str], *, destroy: bool = False) -> PlanOutcome:
        full = self._env(ws, env)
        ws.discard_plan()
        args = ["plan", "-input=false", "-no-color", f"-lock-timeout={self.lock_timeout}",
                "-detailed-exitcode", f"-out={PLAN_FILE}"]
        if destroy:
            args.append("-destroy")
        code, tail = self._run(args, ws, full, self.plan_timeout)
        if code not in (0, 2):  # 0 = nothing to do, 2 = changes
            raise self._failure("plan", tail)
        shown = self._capture(["show", "-json", "-no-color", PLAN_FILE], ws, full)
        return PlanOutcome(has_changes=code == 2, summary=summarize_plan(json.loads(shown)))

    def apply(self, ws: Workspace, env: Mapping[str, str]) -> ApplyOutcome:
        """Apply the saved plan file. Never destroys anything if it fails."""
        full = self._env(ws, env)
        code, tail = self._run(
            ["apply", "-input=false", "-no-color", f"-lock-timeout={self.lock_timeout}",
             f"-parallelism={self.parallelism}", PLAN_FILE],
            ws, full, self.apply_timeout)
        in_state = self._state_resources(ws, full)
        if code != 0:
            return ApplyOutcome(False, str(self._failure("apply", tail)), in_state)
        return ApplyOutcome(True, None, in_state, self._outputs(ws, full))

    def _state_resources(self, ws: Workspace, env: dict[str, str]) -> list[str]:
        try:
            return sorted(line for line in self._capture(["state", "list", "-no-color"], ws, env).splitlines()
                          if line.strip())
        except TerraformError:
            return []  # an empty or unreadable state is reported as nothing known, never as an error

    def _outputs(self, ws: Workspace, env: dict[str, str]) -> dict:
        try:
            raw = json.loads(self._capture(["output", "-json", "-no-color"], ws, env) or "{}")
        except (TerraformError, json.JSONDecodeError):
            return {}
        return {name: o.get("value") for name, o in raw.items() if not o.get("sensitive")}
