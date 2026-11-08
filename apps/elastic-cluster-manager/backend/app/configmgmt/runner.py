"""Running Ansible: the interface the rest of ECM depends on, and the real command-line implementation.

Safety properties, each covered by a test:
  * the subprocess gets a minimal environment, never ECM's own (so the master key and admin hash cannot leak
    into Ansible or a task); only what Ansible needs is added
  * secrets (the elastic password, the cluster CA key) travel in a 0600 extra-vars file and never on the command
    line or in the inventory; every output line is redacted, and the secrets are registered for redaction
  * everything for one run lives in a private 0700 directory that is deleted afterwards, success or failure
  * a failed create can still have made the cluster CA, and certificates signed by it may already be on the VMs,
    so a new CA is returned even when the run fails: discarding it would strand those nodes
  * a create cannot be checked (check mode cannot simulate it), so --check is refused for one; a converge can be
  * a run that exceeds its time limit is interrupted (SIGINT first, so Ansible can stop cleanly) and only killed
    if it ignores that
"""
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.configmgmt.inventory import InventoryError, InventoryInput, OperationKind, inventory_json
from app.crypto import redact, register_secret
from app.desired.models import DesiredState

MIN_PASSWORD_LENGTH = 20  # the same floor the es_node role enforces
PLAYBOOKS = {"create": "playbooks/create.yml", "converge": "playbooks/converge.yml",
             "restart": "playbooks/rolling_restart.yml", "add_node": "playbooks/add_node.yml",
             "remove_drain": "playbooks/remove_nodes.yml", "remove_check": "playbooks/remove_nodes.yml"}
_RECAP = re.compile(r"^(\S+)\s*:\s*ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)")
_NEEDLES = ("fatal:", "[ERROR]", "FAILED!")


class AnsibleError(Exception):
    """Ansible could not run, or the request was refused before it started. The message is already redacted."""


@dataclass
class AnsibleRequest:
    state: DesiredState
    addresses: dict[str, str]  # node name to IPv4 address
    kind: OperationKind
    bootstrapped_at: datetime | None
    search_domain: str | None = None
    check: bool = False  # --check --diff: report what would change and change nothing (converge only)
    elastic_password: str | None = field(default=None, repr=False)  # a create needs it; it is used once
    ca_cert_pem: str | None = None  # reuse the cluster's CA when nodes need certificates
    ca_key_pem: str | None = field(default=None, repr=False)
    # A rolling restart only. It asks Elasticsearch about its health (with the ECM API key and the cluster's CA) and
    # asks Proxmox to restart each VM (with the Terraform token), so it needs where each VM is and both credentials.
    vm_ids: dict[str, int] | None = None
    placement: dict[str, str] | None = None
    es_api_key: str | None = field(default=None, repr=False)  # the encoded API key
    es_ca_pem: str | None = None  # the cluster's CA certificate (public)
    pve_api_url: str | None = None
    pve_token_id: str | None = None
    pve_token_secret: str | None = field(default=None, repr=False)
    pve_ca_pem: str | None = None  # a custom Proxmox CA, when the connection has one
    pve_verify_tls: bool = True
    # Adding nodes: the new ones. Uses es_api_key and es_ca_pem to check they joined, and the CA key and certificate
    # (ca_cert_pem, ca_key_pem) to sign their certificates.
    new_nodes: list[str] | None = None
    # Rebuilding lost nodes uses the same steps with the new nodes being the rebuilt ones, but the cluster is expected to be
    # yellow (it is missing them), so the health gates ask for yellow or better instead of green.
    rebuild: bool = False
    # A restart the operator planned (slice 5b of docs/DESIGN_RECOVERY.md): the nodes to restart or start in the order to go, as
    # {"name", "action"}; the nodes that were in the cluster when it was planned (to ask about the cluster); and when the
    # operation was made, as a Unix time, so a retry skips what it already restarted. Without a plan the restart is the one that
    # follows a resize: the nodes not yet at their target size.
    restart_plan: list[dict] | None = None
    restart_present: list[str] | None = None
    restart_since: int | None = None
    # Removing nodes: the ones going (they are not in `state`, which is what remains). Uses es_api_key and es_ca_pem to
    # drain them and, afterwards, to check the cluster is green without them.
    removing: list[str] | None = None


@dataclass
class BootstrapResult:
    """What a create hands back once the expected nodes joined and health reached the expected status."""
    cluster_uuid: str
    status: str
    number_of_nodes: int
    api_key_id: str
    api_key_encoded: str = field(repr=False)  # the caller stores it encrypted


@dataclass
class NewCa:
    """A CA made during this run. It must be stored: certificates signed by it may already be on the nodes."""
    cert_pem: str
    key_pem: str = field(repr=False)


@dataclass
class HostRecap:
    ok: int
    changed: int
    unreachable: int
    failed: int


@dataclass
class AnsibleOutcome:
    ok: bool
    error: str | None = None
    recap: dict[str, HostRecap] = field(default_factory=dict)
    result: BootstrapResult | None = None  # a successful create only
    new_ca: NewCa | None = None  # whenever this run made a CA, even if it then failed
    # Nodes whose configuration this run changed without restarting them (so the change waits for a restart), even if the run then failed.
    pending_restart: list[str] = field(default_factory=list)


class AnsibleRunner(Protocol):
    def run(self, request: AnsibleRequest) -> AnsibleOutcome: ...


def _register_pem(pem: str | None) -> None:
    """Redaction matches exact strings and output arrives line by line, so register the whole value and each
    line of it."""
    if not pem:
        return
    register_secret(pem)
    for line in pem.splitlines():
        if not line.startswith("-----"):
            register_secret(line.strip())


def parse_recap(lines: list[str]) -> dict[str, HostRecap]:
    recap: dict[str, HostRecap] = {}
    for line in lines:
        m = _RECAP.match(line.strip())
        if m:
            recap[m.group(1)] = HostRecap(*(int(g) for g in m.groups()[1:]))
    return recap


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


class CliAnsibleRunner:
    def __init__(
        self,
        ansible_dir: str,
        ssh_user: str,
        ssh_key_path: str,
        binary: str = "ansible-playbook",
        work_root: str | None = None,
        log: Callable[[str], None] | None = None,
        timeout: float = 3600,
        interrupt_grace: float = 30,
    ):
        self.ansible_dir = ansible_dir
        self.ssh_user = ssh_user
        self.ssh_key_path = ssh_key_path
        self.binary = binary
        self.work_root = work_root
        self.log = log or (lambda line: None)
        self.timeout = timeout
        self.interrupt_grace = interrupt_grace

    # ---- the interface --------------------------------------------------------------------------

    def run(self, request: AnsibleRequest) -> AnsibleOutcome:
        self._check_request(request)
        for secret in (request.elastic_password, request.ca_key_pem, request.es_api_key, request.pve_token_secret):
            if secret:
                register_secret(secret)
        _register_pem(request.ca_key_pem)

        run_dir = Path(tempfile.mkdtemp(prefix="ecm-ansible-", dir=self.work_root))
        try:
            os.chmod(run_dir, 0o700)
            artifacts = run_dir / "artifacts"
            artifacts.mkdir(mode=0o700)
            (run_dir / "home").mkdir(mode=0o700)
            (run_dir / "tmp").mkdir(mode=0o700)

            inventory = run_dir / "inventory.json"
            try:
                _write_private(inventory, inventory_json(InventoryInput(
                    state=request.state, addresses=request.addresses, operation_kind=request.kind,
                    bootstrapped_at=request.bootstrapped_at, ssh_user=self.ssh_user,
                    ssh_key_path=self.ssh_key_path, known_hosts_path=str(run_dir / "known_hosts"),
                    search_domain=request.search_domain, artifacts_dir=str(artifacts),
                    vm_ids=request.vm_ids, placement=request.placement, new_nodes=request.new_nodes,
                    removing=request.removing)))
            except InventoryError as exc:
                raise AnsibleError(str(exc)) from exc

            args = [self.binary, "-i", str(inventory)]
            secrets = self._secret_vars(request)
            secrets.update(self._restart_vars(request, run_dir))
            secrets.update(self._join_vars(request, run_dir))
            secrets.update(self._removal_vars(request, run_dir))
            if secrets:
                extra = run_dir / "extra-vars.json"
                _write_private(extra, json.dumps(secrets))
                args += ["-e", f"@{extra}"]
            if request.check:
                args += ["--check", "--diff"]
            args.append(PLAYBOOKS[request.kind])

            code, tail, recap_lines = self._execute(args, self._env(run_dir))
            recap = parse_recap(recap_lines)
            new_ca = self._read_new_ca(artifacts)
            pending = self._read_pending(artifacts)
            if code != 0:
                return AnsibleOutcome(False, self._failure(tail), recap, None, new_ca, pending)
            result = None
            if request.kind == "create":
                try:
                    result = self._read_result(artifacts / "result.json")
                except AnsibleError as exc:
                    return AnsibleOutcome(False, str(exc), recap, None, new_ca, pending)
            return AnsibleOutcome(True, None, recap, result, new_ca, pending)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    # ---- request checks and inputs --------------------------------------------------------------

    @staticmethod
    def _check_request(request: AnsibleRequest) -> None:
        if request.kind == "create":
            if request.check:
                raise AnsibleError("a create cannot be checked: check mode cannot simulate it. "
                                   "Use a dry-run Terraform plan, or converge --check on a finished cluster.")
            if not request.elastic_password or len(request.elastic_password) < MIN_PASSWORD_LENGTH:
                raise AnsibleError(f"a create needs an elastic password of at least {MIN_PASSWORD_LENGTH} "
                                   "characters")
        if bool(request.ca_cert_pem) != bool(request.ca_key_pem):
            raise AnsibleError("pass the cluster CA certificate and key together, or neither")
        if request.kind == "add_node":
            if request.check:
                raise AnsibleError("adding nodes cannot be checked: check mode cannot simulate it")
            missing = [name for name, value in (
                ("the names of the new nodes", request.new_nodes), ("the ECM API key", request.es_api_key),
                ("the cluster's CA certificate", request.es_ca_pem or request.ca_cert_pem),
                ("the cluster's CA key, to sign the new nodes' certificates", request.ca_key_pem)) if not value]
            if missing:
                raise AnsibleError("adding nodes needs " + ", ".join(missing))
        if request.kind in ("remove_drain", "remove_check"):
            if request.check:
                raise AnsibleError("removing nodes cannot be checked: check mode cannot simulate it")
            missing = [name for name, value in (
                ("the names of the nodes being removed", request.removing), ("the ECM API key", request.es_api_key),
                ("the cluster's CA certificate", request.es_ca_pem)) if not value]
            if missing:
                raise AnsibleError("removing nodes needs " + ", ".join(missing))
        if request.kind == "restart":
            if request.check:
                raise AnsibleError("a rolling restart cannot be checked: check mode cannot simulate it")
            missing = [name for name, value in (
                ("the ECM API key", request.es_api_key), ("the cluster's CA certificate", request.es_ca_pem),
                ("the Proxmox API address", request.pve_api_url), ("the Proxmox token id", request.pve_token_id),
                ("the Proxmox token secret", request.pve_token_secret), ("each node's VMID", request.vm_ids),
                ("each node's Proxmox host", request.placement)) if not value]
            if missing:
                raise AnsibleError("a rolling restart needs " + ", ".join(missing))
            if not str(request.pve_api_url).startswith("https://"):
                raise AnsibleError("the Proxmox API address must start with https://")
            if request.restart_plan is not None and not (request.restart_plan and request.restart_present
                                                         and request.restart_since):
                raise AnsibleError("a planned restart needs the plan, the nodes that were in the cluster when it was made, "
                                   "and when the operation began")

    @staticmethod
    def _secret_vars(request: AnsibleRequest) -> dict[str, str]:
        out: dict[str, str] = {}
        if request.kind == "create" and request.elastic_password:
            out["es_elastic_password"] = request.elastic_password
        if request.ca_cert_pem and request.ca_key_pem:
            out["es_ca_cert_pem"] = request.ca_cert_pem
            out["es_ca_key_pem"] = request.ca_key_pem
        return out

    @staticmethod
    def _restart_vars(request: AnsibleRequest, run_dir: Path) -> dict[str, str | bool]:
        """What a rolling restart needs beyond the inventory: the two credentials, and the CA files it checks them
        against. The certificates are public and go in files in the private run directory; the credentials go in
        the extra-vars file with the other secrets."""
        if request.kind != "restart":
            return {}
        es_ca = run_dir / "es-ca.crt"
        _write_private(es_ca, request.es_ca_pem or "")
        out: dict[str, str | bool] = {
            "es_api_key": request.es_api_key or "", "es_ca_file": str(es_ca),
            "pve_api_url": (request.pve_api_url or "").rstrip("/"), "pve_token_id": request.pve_token_id or "",
            "pve_token_secret": request.pve_token_secret or "", "pve_verify_tls": request.pve_verify_tls,
        }
        if request.pve_ca_pem:
            pve_ca = run_dir / "pve-ca.crt"
            _write_private(pve_ca, request.pve_ca_pem)
            out["pve_ca_file"] = str(pve_ca)
        if request.restart_plan is not None:
            out.update({"es_restart_plan": request.restart_plan, "es_restart_present": request.restart_present or [],
                        "es_restart_since": request.restart_since or 0})
        return out

    @staticmethod
    def _join_vars(request: AnsibleRequest, run_dir: Path) -> dict[str, str]:
        """What adding nodes needs beyond the inventory: the API key to ask the cluster whether they joined, the CA it
        is checked against (a public file in the private run directory), and which hosts the first-boot wait covers."""
        if request.kind != "add_node":
            return {}
        ca = run_dir / "es-ca.crt"
        _write_private(ca, request.es_ca_pem or request.ca_cert_pem or "")
        return {"es_api_key": request.es_api_key or "", "es_ca_file": str(ca), "first_boot_hosts": "es_new_nodes",
                "es_jc_min_status": "yellow" if request.rebuild else "green"}

    @staticmethod
    def _removal_vars(request: AnsibleRequest, run_dir: Path) -> dict[str, str]:
        """What removing nodes needs beyond the inventory: the API key, the CA it is checked against (a public file in the
        private run directory) and which half of the work this run is, the drain before Terraform or the check after."""
        if request.kind not in ("remove_drain", "remove_check"):
            return {}
        ca = run_dir / "es-ca.crt"
        _write_private(ca, request.es_ca_pem or "")
        return {"es_api_key": request.es_api_key or "", "es_ca_file": str(ca),
                "es_dr_phase": "drain" if request.kind == "remove_drain" else "after"}

    def _env(self, run_dir: Path) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(run_dir / "home"),
            "LC_ALL": "C.UTF-8",
            "ANSIBLE_CONFIG": str(Path(self.ansible_dir) / "ansible.cfg"),
            "ANSIBLE_LOCAL_TEMP": str(run_dir / "tmp"),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_FORCE_COLOR": "0",
            "ANSIBLE_DEPRECATION_WARNINGS": "False",
        }
        if "ANSIBLE_COLLECTIONS_PATH" in os.environ:
            env["ANSIBLE_COLLECTIONS_PATH"] = os.environ["ANSIBLE_COLLECTIONS_PATH"]
        return env

    # ---- process plumbing -----------------------------------------------------------------------

    def _execute(self, args: list[str], env: dict[str, str]) -> tuple[int, list[str], list[str]]:
        """Run Ansible, streaming redacted lines to the log. Returns (exit code, last lines, recap lines)."""
        try:
            proc = subprocess.Popen(args, cwd=self.ansible_dir, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)
        except FileNotFoundError as exc:
            raise AnsibleError(f"the ansible-playbook binary was not found ({self.binary})") from exc

        timed_out = threading.Event()

        def interrupt() -> None:
            timed_out.set()
            proc.send_signal(signal.SIGINT)
            killer = threading.Timer(self.interrupt_grace, proc.kill)
            killer.daemon = True
            killer.start()

        timer = threading.Timer(self.timeout, interrupt)
        timer.daemon = True
        timer.start()
        tail: deque[str] = deque(maxlen=60)
        recap_lines: list[str] = []
        in_recap = False
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = redact(raw.rstrip("\n"))
                tail.append(line)
                self.log(line)
                if line.startswith("PLAY RECAP"):
                    in_recap = True
                elif in_recap:
                    recap_lines.append(line)
            code = proc.wait()
        finally:
            timer.cancel()
        if timed_out.is_set():
            raise AnsibleError(f"ansible-playbook timed out after {self.timeout:g}s and was interrupted")
        return code, list(tail), recap_lines

    @staticmethod
    def _failure(tail: list[str]) -> str:
        hits = [line.strip() for line in tail if any(n in line for n in _NEEDLES)]
        detail = " | ".join(h[:600] for h in hits[-3:]) if hits else " ".join(tail[-5:])
        return f"ansible-playbook failed: {detail}".strip()

    # ---- what the run hands back ----------------------------------------------------------------

    @staticmethod
    def _read_new_ca(artifacts: Path) -> NewCa | None:
        cert, key = artifacts / "ca.crt", artifacts / "ca.key"
        if not (cert.is_file() and key.is_file()):
            return None
        ca = NewCa(cert.read_text(), key.read_text())
        _register_pem(ca.key_pem)
        return ca

    @staticmethod
    def _read_pending(artifacts: Path) -> list[str]:
        """The nodes the run left waiting for a restart: one `pending-<node>` marker file each (roles/es_node/handlers). A marker is
        only a name, so it is checked to look like one before it is believed."""
        names = []
        for marker in sorted(artifacts.glob("pending-*")):
            name = marker.name.removeprefix("pending-")
            if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", name):
                names.append(name)
        return names

    @staticmethod
    def _read_result(path: Path) -> BootstrapResult:
        try:
            data = json.loads(path.read_text())
            result = BootstrapResult(
                cluster_uuid=data["cluster_uuid"], status=data["status"],
                number_of_nodes=data["number_of_nodes"], api_key_id=data["api_key_id"],
                api_key_encoded=data["api_key_encoded"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AnsibleError("the create finished but did not hand back a usable result.json") from exc
        valid = (all(isinstance(v, str) and v for v in (result.cluster_uuid, result.status, result.api_key_id,
                                                        result.api_key_encoded))
                 and isinstance(result.number_of_nodes, int) and not isinstance(result.number_of_nodes, bool)
                 and result.number_of_nodes >= 1)
        if not valid:
            raise AnsibleError("the create's result.json is missing a field or has one of the wrong type")
        register_secret(result.api_key_encoded)
        return result


def runner_from_settings(settings: Settings, log: Callable[[str], None] | None = None) -> CliAnsibleRunner:
    """The runner the worker uses: the playbooks, SSH user and key path all come from ECM's settings."""
    return CliAnsibleRunner(ansible_dir=settings.ansible_dir, ssh_user=settings.ssh_user,
                            ssh_key_path=settings.ssh_key_path, log=log)
