"""The real Terraform CLI, driven against throwaway configurations that need no provider and no network."""
import shutil
import time

import pytest

from app.provisioning.plan import check_plan_safety
from app.provisioning.runner import CliTerraformRunner, TerraformError
from app.provisioning.workspace import open_workspace

pytestmark = pytest.mark.skipif(not shutil.which("terraform"), reason="terraform is not installed")

ID = "0123456789abcdef"
GOOD = {"main.tf": '''
resource "terraform_data" "x" {
  input = "hello"
}

output "greeting" {
  value = terraform_data.x.output
}

output "hidden" {
  value     = "shh"
  sensitive = true
}
'''}


def workspace(tmp_path, files):
    return open_workspace(tmp_path, ID, files)


def runner(**kw):
    lines: list[str] = []
    return CliTerraformRunner(log=lines.append, **kw), lines


# ---- the happy path ------------------------------------------------------------------------------

def test_init_plan_apply_and_replan(tmp_path):
    ws, (r, lines) = workspace(tmp_path, GOOD), runner()
    r.init(ws, {})
    plan = r.plan(ws, {})
    assert plan.has_changes and plan.summary.adds == 1 and plan.summary.deletes == 0
    assert check_plan_safety(plan.summary, "create") == []
    assert ws.plan_path.exists()

    out = r.apply(ws, {})
    assert out.ok and out.error is None
    assert out.resources_in_state == ["terraform_data.x"]
    assert out.outputs == {"greeting": "hello"}                       # the sensitive output is left out
    assert any("Apply complete" in line for line in lines)

    again = r.plan(ws, {})                                            # nothing left to do
    assert not again.has_changes and again.summary.is_empty


def test_a_destroy_plan_only_deletes(tmp_path):
    ws, (r, _) = workspace(tmp_path, GOOD), runner()
    r.init(ws, {})
    r.plan(ws, {})
    r.apply(ws, {})
    plan = r.plan(ws, {}, destroy=True)
    assert plan.summary.deletes == 1 and plan.summary.adds == 0
    assert check_plan_safety(plan.summary, "destroy") == []
    assert check_plan_safety(plan.summary, "create")                  # and a create would refuse it


def test_planning_again_discards_the_previous_plan(tmp_path):
    ws, (r, _) = workspace(tmp_path, GOOD), runner()
    r.init(ws, {})
    r.plan(ws, {})
    first = ws.plan_path.read_bytes()
    ws.meta_path.write_text("{}")
    r.plan(ws, {})
    assert not ws.meta_path.exists()                                  # a stale meta never survives a re-plan
    assert ws.plan_path.exists() and ws.plan_path.read_bytes() != b"" and first != b""


# ---- failures never destroy anything ---------------------------------------------------------------

FAILING = {"main.tf": '''
resource "terraform_data" "ok" {
  input = "fine"
}

resource "terraform_data" "bad" {
  depends_on = [terraform_data.ok]
  provisioner "local-exec" {
    command = "echo about to fail && exit 1"
  }
}
'''}


def test_a_failed_apply_keeps_partial_state_and_reports_what_exists(tmp_path):
    ws, (r, lines) = workspace(tmp_path, FAILING), runner()
    r.init(ws, {})
    r.plan(ws, {})
    out = r.apply(ws, {})
    assert not out.ok
    assert "terraform apply failed" in out.error and "Error" in out.error
    # the resource that succeeded is still there, and so is the one that failed (tainted): nothing was destroyed
    assert out.resources_in_state == ["terraform_data.bad", "terraform_data.ok"]
    assert (ws.dir / "terraform.tfstate").exists()
    assert not any("Destroying" in line or "destroyed" in line.lower() for line in lines)


def test_a_failed_plan_raises_with_the_reason(tmp_path):
    ws, (r, _) = workspace(tmp_path, {"main.tf": 'variable "need" {\n  type = string\n}\n'}), runner()
    r.init(ws, {})
    with pytest.raises(TerraformError, match="terraform plan failed.*Error"):
        r.plan(ws, {})


def test_a_missing_binary_is_reported_clearly(tmp_path):
    ws = workspace(tmp_path, GOOD)
    r = CliTerraformRunner(binary="/nonexistent/terraform")
    with pytest.raises(TerraformError, match="binary was not found"):
        r.init(ws, {})


# ---- isolation and redaction -----------------------------------------------------------------------

ENV_DUMP = {"main.tf": '''
resource "terraform_data" "probe" {
  provisioner "local-exec" {
    command = "env > env.txt; echo \\"token is $PROXMOX_VE_API_TOKEN\\""
  }
}
'''}


def test_terraform_never_sees_ecms_own_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ECM_MASTER_KEY", "master-key-that-must-not-leak")
    monkeypatch.setenv("ECM_ADMIN_PASSWORD_HASH", "hash-that-must-not-leak")
    ws, (r, _) = workspace(tmp_path, ENV_DUMP), runner()
    creds = {"PROXMOX_VE_API_TOKEN": "bret@pve!ecm=00000000-1111-2222-3333-444444444444"}
    r.init(ws, creds)
    r.plan(ws, creds)
    assert r.apply(ws, creds).ok
    seen = (ws.dir / "env.txt").read_text()
    assert "ECM_MASTER_KEY" not in seen and "master-key-that-must-not-leak" not in seen
    assert "ECM_ADMIN_PASSWORD_HASH" not in seen
    assert "PROXMOX_VE_API_TOKEN=" in seen                            # only what the caller passed in
    assert "TF_IN_AUTOMATION=1" in seen and "CHECKPOINT_DISABLE=1" in seen


def test_credentials_are_redacted_from_the_log(tmp_path):
    ws, (r, lines) = workspace(tmp_path, ENV_DUMP), runner()
    secret = "super-secret-value-12345"
    creds = {"PROXMOX_VE_API_TOKEN": f"bret@pve!ecm={secret}"}
    r.init(ws, creds)
    r.plan(ws, creds)
    r.apply(ws, creds)
    joined = "\n".join(lines)
    assert "token is" in joined                                       # the line was logged...
    assert secret not in joined                                       # ...with the secret masked


# ---- time limits -----------------------------------------------------------------------------------

SLOW = {"main.tf": '''
resource "terraform_data" "slow" {
  provisioner "local-exec" {
    command = "sleep 60"
  }
}
'''}


def test_a_run_that_exceeds_its_time_limit_is_interrupted(tmp_path):
    ws, (r, _) = workspace(tmp_path, SLOW), runner(apply_timeout=2, interrupt_grace=5)
    r.init(ws, {})
    r.plan(ws, {})
    started = time.monotonic()
    with pytest.raises(TerraformError, match="timed out after 2s and was interrupted"):
        r.apply(ws, {})
    assert time.monotonic() - started < 30                            # nowhere near the 60 s sleep
