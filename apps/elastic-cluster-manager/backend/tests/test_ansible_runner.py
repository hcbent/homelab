"""CliAnsibleRunner against a fake ansible-playbook that records how it was called and writes whatever artifacts a
test asks for. No VM, no network, no Ansible install needed."""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.configmgmt import AnsibleError, AnsibleRequest, CliAnsibleRunner
from app.desired import TopologyPreset, build_desired_state

PASSWORD = "Zq9-fake-elastic-password-for-tests-0001"


def pem(label: str, *body: str) -> str:
    """A fake PEM block, assembled here so the source holds no literal key armor for a secret scanner to find."""
    return f"-----BEGIN {label}-----\n" + "\n".join(body) + f"\n-----END {label}-----\n"


CA_CERT = pem("CERTIFICATE", "FakeCertificateBodyLineOne0000")
CA_KEY = pem("PRIVATE KEY", "FakeKeyBodyLineOneOfTheCaKey0001", "FakeKeyBodyLineTwoOfTheCaKey0002==")
GOOD_RESULT = {"cluster_uuid": "4Et2nKICTImSzjMyH77utQ", "status": "green", "number_of_nodes": 3,
               "api_key_id": "ZSmjsaEB1M7T5v1mkNOK", "api_key_encoded": "FakeEncodedApiKeyValueForTests0001"}
RECAP = ["PLAY RECAP *********************************************************************",
         "lab-b-01                   : ok=67   changed=16   unreachable=0    failed=0    skipped=13   rescued=0",
         "lab-b-02                   : ok=47   changed=7    unreachable=0    failed=0    skipped=12   rescued=0"]

FAKE = '''#!__PY__
import json, os, pathlib, sys, time
cfg = json.loads(__CFG__)
args = sys.argv[1:]
inv = pathlib.Path(args[args.index("-i") + 1])
inventory = json.loads(inv.read_text())
extra = extra_mode = None
if "-e" in args:
    p = pathlib.Path(args[args.index("-e") + 1].lstrip("@"))
    extra, extra_mode = json.loads(p.read_text()), oct(p.stat().st_mode & 0o777)
pathlib.Path(cfg["record"]).write_text(json.dumps(dict(
    argv=args, cwd=os.getcwd(), env=dict(os.environ), inventory=inventory, run_dir=str(inv.parent),
    run_dir_mode=oct(inv.parent.stat().st_mode & 0o777), inv_mode=oct(inv.stat().st_mode & 0o777),
    extra=extra, extra_mode=extra_mode)))
art = pathlib.Path(inventory["all"]["vars"]["es_artifacts_dir"])
for name, content in cfg.get("artifacts", {}).items():
    (art / name).write_text(content)
if cfg.get("echo_extra") and extra:
    for k, v in extra.items():
        print("debug: " + k + " is " + v)
for line in cfg.get("output", []):
    print(line)
sys.stdout.flush()
if cfg.get("sleep"):
    time.sleep(cfg["sleep"])
sys.exit(cfg.get("exit", 0))
'''


def fake(tmp_path: Path, **cfg) -> tuple[str, Path]:
    record = tmp_path / "record.json"
    script = tmp_path / "fake-ansible-playbook"
    cfg = {"output": RECAP, **cfg, "record": str(record)}
    script.write_text(FAKE.replace("__PY__", sys.executable).replace("__CFG__", repr(json.dumps(cfg))))
    script.chmod(0o755)
    return str(script), record


def runner(tmp_path: Path, binary: str, **kw):
    (tmp_path / "ansible").mkdir(exist_ok=True)
    (tmp_path / "work").mkdir(exist_ok=True)
    lines: list[str] = []
    r = CliAnsibleRunner(ansible_dir=str(tmp_path / "ansible"), ssh_user="bret",
                         ssh_key_path="/run/ecm/ssh/github_rsa", binary=binary,
                         work_root=str(tmp_path / "work"), log=lines.append, **kw)
    return r, lines


def request(kind="create", **kw) -> AnsibleRequest:
    state = build_desired_state(TopologyPreset.three_node, "lab-b", "9.5.6")
    base = {"state": state, "addresses": {n.name: f"192.0.2.{10 + i}" for i, n in enumerate(state.nodes)},
            "kind": kind, "bootstrapped_at": None if kind == "create" else datetime(2026, 11, 6, tzinfo=UTC),
            "search_domain": "lab.example.test",
            "elastic_password": PASSWORD if kind == "create" else None}
    base.update(kw)
    return AnsibleRequest(**base)


def recorded(record: Path) -> dict:
    return json.loads(record.read_text())


def work_dir_is_empty(tmp_path: Path) -> bool:
    return list((tmp_path / "work").iterdir()) == []


CREATE_ARTIFACTS = {"result.json": json.dumps(GOOD_RESULT), "ca.crt": CA_CERT, "ca.key": CA_KEY}


# ---- the happy path ------------------------------------------------------------------------------

def test_a_create_returns_the_result_and_any_new_ca_and_the_recap(tmp_path):
    binary, record = fake(tmp_path, artifacts=CREATE_ARTIFACTS)
    r, lines = runner(tmp_path, binary)
    out = r.run(request())
    assert out.ok and out.error is None
    assert out.result.cluster_uuid == "4Et2nKICTImSzjMyH77utQ" and out.result.number_of_nodes == 3
    assert out.result.api_key_id == "ZSmjsaEB1M7T5v1mkNOK"
    assert out.result.api_key_encoded == GOOD_RESULT["api_key_encoded"]
    assert out.new_ca.cert_pem == CA_CERT and out.new_ca.key_pem == CA_KEY
    assert out.recap["lab-b-01"].ok == 67 and out.recap["lab-b-01"].changed == 16
    assert out.recap["lab-b-02"].failed == 0 and any(line.startswith("PLAY RECAP") for line in lines)
    assert recorded(record)["argv"][-1] == "playbooks/create.yml"


def test_the_playbook_runs_from_the_ansible_directory_with_its_config(tmp_path):
    binary, record = fake(tmp_path, artifacts=CREATE_ARTIFACTS)
    runner(tmp_path, binary)[0].run(request())
    rec = recorded(record)
    assert Path(rec["cwd"]).resolve() == (tmp_path / "ansible").resolve()
    assert rec["env"]["ANSIBLE_CONFIG"] == str(tmp_path / "ansible" / "ansible.cfg")
    assert rec["env"]["HOME"].startswith(rec["run_dir"])         # a home of its own, inside the private run dir


def test_a_converge_needs_no_password_and_a_check_adds_the_flags(tmp_path):
    binary, record = fake(tmp_path)
    r, _ = runner(tmp_path, binary)
    out = r.run(request("converge", check=True))
    assert out.ok and out.result is None
    rec = recorded(record)
    assert "--check" in rec["argv"] and "--diff" in rec["argv"] and rec["argv"][-1] == "playbooks/converge.yml"
    assert rec["extra"] is None and "-e" not in rec["argv"]       # no secrets, so no extra-vars file at all
    r.run(request("converge"))
    assert "--check" not in recorded(record)["argv"]


# ---- secrets never travel the wrong way -------------------------------------------------------------

def test_secrets_go_in_a_private_extra_vars_file_and_nowhere_else(tmp_path):
    binary, record = fake(tmp_path, artifacts=CREATE_ARTIFACTS)
    runner(tmp_path, binary)[0].run(request(ca_cert_pem=CA_CERT, ca_key_pem=CA_KEY))
    rec = recorded(record)
    assert rec["extra"] == {"es_elastic_password": PASSWORD, "es_ca_cert_pem": CA_CERT, "es_ca_key_pem": CA_KEY}
    assert rec["extra_mode"] == "0o600"
    everything_else = json.dumps([rec["argv"], rec["env"], rec["inventory"]])
    for secret in (PASSWORD, CA_KEY, "FakeKeyBodyLineOneOfTheCaKey0001"):
        assert secret not in everything_else


def test_the_private_run_directory_is_locked_down_and_removed_afterwards(tmp_path):
    binary, record = fake(tmp_path, artifacts=CREATE_ARTIFACTS)
    runner(tmp_path, binary)[0].run(request())
    rec = recorded(record)
    assert rec["run_dir_mode"] == "0o700" and rec["inv_mode"] == "0o600"
    assert not Path(rec["run_dir"]).exists() and work_dir_is_empty(tmp_path)


def test_ansible_never_sees_ecms_own_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ECM_MASTER_KEY", "master-key-that-must-not-leak")
    monkeypatch.setenv("ECM_ADMIN_PASSWORD_HASH", "hash-that-must-not-leak")
    monkeypatch.setenv("POSTGRES_PASSWORD", "db-password-that-must-not-leak")
    binary, record = fake(tmp_path, artifacts=CREATE_ARTIFACTS)
    runner(tmp_path, binary)[0].run(request())
    env = recorded(record)["env"]
    assert not any(k.startswith("ECM_") or k == "POSTGRES_PASSWORD" for k in env)
    assert "must-not-leak" not in json.dumps(env)


def test_secrets_an_ansible_task_echoes_are_redacted_from_the_log(tmp_path):
    binary, _ = fake(tmp_path, artifacts=CREATE_ARTIFACTS, echo_extra=True)
    r, lines = runner(tmp_path, binary)
    r.run(request(ca_cert_pem=CA_CERT, ca_key_pem=CA_KEY))
    text = "\n".join(lines)
    assert "[REDACTED]" in text
    for leaked in (PASSWORD, "FakeKeyBodyLineOneOfTheCaKey0001", "FakeKeyBodyLineTwoOfTheCaKey0002"):
        assert leaked not in text


def test_secrets_do_not_appear_in_the_repr_of_a_request_or_an_outcome(tmp_path):
    binary, _ = fake(tmp_path, artifacts=CREATE_ARTIFACTS)
    req = request(ca_cert_pem=CA_CERT, ca_key_pem=CA_KEY)
    out = runner(tmp_path, binary)[0].run(req)
    text = repr(req) + repr(out)
    for secret in (PASSWORD, GOOD_RESULT["api_key_encoded"], "FakeKeyBodyLineOneOfTheCaKey0001"):
        assert secret not in text


# ---- failures --------------------------------------------------------------------------------------

def test_a_failed_create_still_returns_the_ca_it_made_and_names_the_failure(tmp_path):
    fail = ["TASK [es_bootstrap : Invalidate an earlier ECM API key]",
            'fatal: [lab-b-01]: FAILED! => {"msg": "Status code was 503 and not [200]"}',
            "PLAY RECAP *****",
            "lab-b-01                   : ok=67   changed=16   unreachable=0    failed=1    skipped=13   rescued=0"]
    binary, _ = fake(tmp_path, artifacts={"ca.crt": CA_CERT, "ca.key": CA_KEY}, output=fail, exit=2)
    out = runner(tmp_path, binary)[0].run(request())
    assert not out.ok and out.result is None
    assert "fatal: [lab-b-01]" in out.error and "503" in out.error
    assert out.new_ca is not None and out.new_ca.key_pem == CA_KEY     # the nodes' certificates need this CA
    assert out.recap["lab-b-01"].failed == 1
    assert work_dir_is_empty(tmp_path)


def test_a_failed_converge_has_no_ca_and_no_result(tmp_path):
    binary, _ = fake(tmp_path, output=["fatal: [lab-b-02]: UNREACHABLE! => {}"], exit=4)
    out = runner(tmp_path, binary)[0].run(request("converge"))
    assert not out.ok and out.new_ca is None and out.result is None and "UNREACHABLE" in out.error


@pytest.mark.parametrize("content", [
    "not json",
    json.dumps({k: v for k, v in GOOD_RESULT.items() if k != "api_key_encoded"}),
    json.dumps({**GOOD_RESULT, "number_of_nodes": "3"}),
    json.dumps({**GOOD_RESULT, "number_of_nodes": True}),
    json.dumps({**GOOD_RESULT, "number_of_nodes": 0}),
    json.dumps({**GOOD_RESULT, "cluster_uuid": ""}),
    json.dumps([GOOD_RESULT]),
])
def test_a_create_without_a_usable_result_is_not_a_success(tmp_path, content):
    binary, _ = fake(tmp_path, artifacts={"result.json": content, "ca.crt": CA_CERT, "ca.key": CA_KEY})
    out = runner(tmp_path, binary)[0].run(request())
    assert not out.ok and out.result is None and "result.json" in out.error
    assert out.new_ca is not None                                       # still returned, still needed


def test_a_create_that_hands_back_no_result_at_all_is_not_a_success(tmp_path):
    binary, _ = fake(tmp_path)
    out = runner(tmp_path, binary)[0].run(request())
    assert not out.ok and "result.json" in out.error


def test_a_run_past_its_time_limit_is_interrupted_and_cleaned_up(tmp_path):
    binary, record = fake(tmp_path, sleep=30)
    r, _ = runner(tmp_path, binary, timeout=0.5, interrupt_grace=5)
    with pytest.raises(AnsibleError, match="timed out"):
        r.run(request())
    assert not Path(recorded(record)["run_dir"]).exists() and work_dir_is_empty(tmp_path)


def test_a_missing_binary_is_reported_clearly_and_leaves_nothing_behind(tmp_path):
    r, _ = runner(tmp_path, "/nonexistent/ansible-playbook")
    with pytest.raises(AnsibleError, match="not found"):
        r.run(request())
    assert work_dir_is_empty(tmp_path)


# ---- requests that are refused before anything runs -------------------------------------------------

@pytest.mark.parametrize("kw,message", [
    ({"elastic_password": None}, "elastic password"),
    ({"elastic_password": "short"}, "elastic password"),
    ({"check": True}, "cannot be checked"),
    ({"ca_cert_pem": CA_CERT}, "together"),
    ({"ca_key_pem": CA_KEY}, "together"),
    ({"bootstrapped_at": datetime(2026, 11, 6, tzinfo=UTC)}, "already bootstrapped"),
])
def test_a_bad_create_request_is_refused_before_ansible_starts(tmp_path, kw, message):
    binary, record = fake(tmp_path)
    r, _ = runner(tmp_path, binary)
    with pytest.raises(AnsibleError, match=message):
        r.run(request(**kw))
    assert not record.exists() and work_dir_is_empty(tmp_path)


def test_a_supplied_ca_reaches_a_converge_as_extra_vars_only(tmp_path):
    binary, record = fake(tmp_path)
    out = runner(tmp_path, binary)[0].run(request("converge", ca_cert_pem=CA_CERT, ca_key_pem=CA_KEY))
    rec = recorded(record)
    assert out.ok and out.new_ca is None
    assert rec["extra"] == {"es_ca_cert_pem": CA_CERT, "es_ca_key_pem": CA_KEY}


def test_the_worker_builds_its_runner_from_settings():
    from app.config import Settings
    from app.configmgmt import runner_from_settings
    r = runner_from_settings(Settings(ssh_user="bret", ssh_key_path="/run/ecm/ssh/github_rsa",
                                      ansible_dir="/opt/ecm/ansible"))
    assert (r.ssh_user, r.ssh_key_path, r.ansible_dir) == ("bret", "/run/ecm/ssh/github_rsa", "/opt/ecm/ansible")
    assert r.binary == "ansible-playbook"


# ---- a rolling restart -----------------------------------------------------------------------------------------

API_KEY = "FakeEncodedEcmApiKeyForTheRestartTests0001"
PVE_SECRET = "fake-proxmox-terraform-token-secret-0001"
PVE_CA = pem("CERTIFICATE", "FakeProxmoxCaCertificateBody0001")


def restart_request(**kw) -> AnsibleRequest:
    names = ["lab-b-01", "lab-b-02", "lab-b-03"]
    base = {"vm_ids": {n: 500 + i for i, n in enumerate(names)}, "placement": dict(zip(names, ["pve1", "pve2", "pve3"])),
            "es_api_key": API_KEY, "es_ca_pem": CA_CERT, "pve_api_url": "https://pve.example.test:8006/",
            "pve_token_id": "terraform@pve!ecm", "pve_token_secret": PVE_SECRET}
    base.update(kw)
    return request("restart", **base)


def test_a_restart_gets_each_nodes_host_and_vmid_in_the_inventory_and_the_credentials_only_in_the_private_file(tmp_path):
    binary, record = fake(tmp_path)
    runner(tmp_path, binary)[0].run(restart_request(pve_ca_pem=PVE_CA))
    rec = recorded(record)
    assert rec["argv"][-1] == "playbooks/rolling_restart.yml" and "--check" not in rec["argv"]
    host = rec["inventory"]["all"]["children"]["es_nodes"]["hosts"]["lab-b-02"]
    assert (host["es_pve_node"], host["es_vmid"], host["es_desired_cores"], host["es_desired_ram_mb"]) == (
        "pve2", 501, 4, 8192)
    extra = rec["extra"]
    assert extra["es_api_key"] == API_KEY and extra["pve_token_secret"] == PVE_SECRET
    assert extra["pve_api_url"] == "https://pve.example.test:8006"                  # no trailing slash
    assert extra["pve_token_id"] == "terraform@pve!ecm" and extra["pve_verify_tls"] is True
    assert rec["extra_mode"] == "0o600"
    everything_else = json.dumps([rec["argv"], rec["env"], rec["inventory"]])
    assert API_KEY not in everything_else and PVE_SECRET not in everything_else


def test_the_ca_files_a_restart_checks_against_are_written_private_and_removed_with_the_run(tmp_path):
    binary, record = fake(tmp_path)
    runner(tmp_path, binary)[0].run(restart_request(pve_ca_pem=PVE_CA))
    extra = recorded(record)["extra"]
    assert Path(extra["es_ca_file"]).name == "es-ca.crt" and Path(extra["pve_ca_file"]).name == "pve-ca.crt"
    assert work_dir_is_empty(tmp_path)                                               # all of it gone afterwards


def test_a_restart_without_a_custom_proxmox_ca_names_none(tmp_path):
    binary, record = fake(tmp_path)
    runner(tmp_path, binary)[0].run(restart_request(pve_verify_tls=False))
    extra = recorded(record)["extra"]
    assert "pve_ca_file" not in extra and extra["pve_verify_tls"] is False


def test_both_credentials_are_redacted_from_the_log_if_a_task_echoes_them(tmp_path):
    binary, _ = fake(tmp_path, echo_extra=True)
    r, lines = runner(tmp_path, binary)
    r.run(restart_request())
    text = "\n".join(lines)
    assert "[REDACTED]" in text and API_KEY not in text and PVE_SECRET not in text


@pytest.mark.parametrize("kw,message", [
    ({"check": True}, "cannot be checked"),
    ({"es_api_key": None}, "the ECM API key"),
    ({"pve_token_secret": None}, "the Proxmox token secret"),
    ({"es_ca_pem": None}, "the cluster's CA certificate"),
    ({"vm_ids": None}, "each node's VMID"),
    ({"placement": None}, "each node's Proxmox host"),
    ({"pve_api_url": "http://pve.example.test:8006"}, "must start with https://"),
])
def test_a_bad_restart_request_is_refused_before_ansible_starts(tmp_path, kw, message):
    binary, record = fake(tmp_path)
    r, _ = runner(tmp_path, binary)
    with pytest.raises(AnsibleError, match=message):
        r.run(restart_request(**kw))
    assert not record.exists() and work_dir_is_empty(tmp_path)


def test_credentials_do_not_appear_in_the_repr_of_a_restart_request():
    text = repr(restart_request())
    assert API_KEY not in text and PVE_SECRET not in text


# ---- adding nodes ------------------------------------------------------------------------------------------------

def add_request(**kw) -> AnsibleRequest:
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-x", "9.5.6", data_nodes=2, coordinating_nodes=1)
    base = {"state": state, "addresses": {n.name: f"192.0.2.{10 + i}" for i, n in enumerate(state.nodes)},
            "kind": "add_node", "bootstrapped_at": datetime(2026, 11, 6, tzinfo=UTC), "new_nodes": ["lab-x-06"],
            "es_api_key": API_KEY, "es_ca_pem": CA_CERT, "ca_cert_pem": CA_CERT, "ca_key_pem": CA_KEY}
    base.update(kw)
    return AnsibleRequest(**base)


def test_adding_nodes_marks_them_in_the_inventory_and_keeps_every_secret_in_the_private_file(tmp_path):
    binary, record = fake(tmp_path)
    runner(tmp_path, binary)[0].run(add_request())
    rec = recorded(record)
    assert rec["argv"][-1] == "playbooks/add_node.yml" and "--check" not in rec["argv"]
    assert rec["inventory"]["all"]["children"]["es_new_nodes"] == {"hosts": {"lab-x-06": {}}}
    extra = rec["extra"]
    assert extra["es_api_key"] == API_KEY and extra["first_boot_hosts"] == "es_new_nodes"
    assert extra["es_ca_cert_pem"] == CA_CERT and extra["es_ca_key_pem"] == CA_KEY     # to sign their certificates
    assert Path(extra["es_ca_file"]).name == "es-ca.crt" and rec["extra_mode"] == "0o600"
    everything_else = json.dumps([rec["argv"], rec["env"], rec["inventory"]])
    for secret in (API_KEY, CA_KEY, "FakeKeyBodyLineOneOfTheCaKey0001"):
        assert secret not in everything_else
    assert work_dir_is_empty(tmp_path)


@pytest.mark.parametrize("kw,message", [
    ({"check": True}, "cannot be checked"),
    ({"new_nodes": None}, "the names of the new nodes"),
    ({"es_api_key": None}, "the ECM API key"),
    ({"ca_cert_pem": None, "ca_key_pem": None, "es_ca_pem": None}, "the cluster's CA certificate"),
    ({"ca_key_pem": None, "ca_cert_pem": None, "es_ca_pem": CA_CERT}, "the cluster's CA key"),
])
def test_a_bad_add_node_request_is_refused_before_ansible_starts(tmp_path, kw, message):
    binary, record = fake(tmp_path)
    r, _ = runner(tmp_path, binary)
    with pytest.raises(AnsibleError, match=message):
        r.run(add_request(**kw))
    assert not record.exists() and work_dir_is_empty(tmp_path)
