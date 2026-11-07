"""The first-boot wait in the create playbook, run for real with ansible-playbook against a stand-in for the ssh
client. Found on infra: one node of a seven-node create refused SSH ("Connection refused") while cloud-init was
still running, after it had already answered the "SSH answers" wait, and Ansible dropped it from the run.

The stand-in refuses the first few calls that carry the `cloud-init` command (its text is in the module payload that
Ansible pipes to the remote shell) and otherwise runs the remote command locally. If a future Ansible stops
putting that text in the payload, nothing is refused and the sanity checks below fail with a clear message, instead
of the tests passing for the wrong reason.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "infra" / "ansible"

pytestmark = pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible is not installed")

FAKE_SSH = """#!/bin/bash
payload=""
if [ ! -t 0 ]; then payload=$(cat); fi
case "$payload" in
  *cloud-init*)
    r=$(cat "$STATE/refused" 2>/dev/null || echo 0)
    if [ "$r" -lt "${REFUSALS:-0}" ]; then
      echo $((r+1)) > "$STATE/refused"
      echo "ssh: connect to host 127.0.0.1 port 22: Connection refused" >&2
      exit 255
    fi;;
esac
cmd="${@: -1}"
printf '%s' "$payload" | exec /bin/sh -c "$cmd"
"""
FAKE_CLOUD_INIT = """#!/bin/sh
echo "$*" >> "$STATE/cloud-init-ran"
echo "status: done"
"""


def run_wait(tmp_path, refusals, *extra, ssh_retries=None):
    """Run wait_for_first_boot.yml against one fake machine. Returns the process, how many calls were refused and
    how many times the real cloud-init command ran."""
    bin_dir, state = tmp_path / "bin", tmp_path / "state"
    bin_dir.mkdir()
    state.mkdir()
    for path, text in ((bin_dir / "cloud-init", FAKE_CLOUD_INIT), (tmp_path / "fakessh.sh", FAKE_SSH)):
        path.write_text(text)
        path.chmod(0o755)
    inventory = tmp_path / "inventory.ini"
    inventory.write_text(
        "[es_nodes]\nnode1 ansible_host=127.0.0.1 ansible_connection=ssh ansible_user=nobody "
        f"ansible_python_interpreter={sys.executable} ansible_ssh_executable={tmp_path / 'fakessh.sh'}\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
    env.update(PATH=f"{bin_dir}{os.pathsep}{env['PATH']}", STATE=str(state), REFUSALS=str(refusals),
               ANSIBLE_NOCOLOR="1")
    if ssh_retries is not None:
        env["ANSIBLE_SSH_RETRIES"] = str(ssh_retries)
    result = subprocess.run(
        ["ansible-playbook", "-i", str(inventory), "playbooks/wait_for_first_boot.yml",
         "-e", "first_boot_poll_delay=0", *extra],   # the real wait pauses 5 seconds before each check; not here
        cwd=ANSIBLE_DIR, env=env, capture_output=True, text=True, timeout=120, check=False)
    refused = int((state / "refused").read_text()) if (state / "refused").exists() else 0
    ran = len((state / "cloud-init-ran").read_text().split("\n")) - 1 if (state / "cloud-init-ran").exists() else 0
    return result, refused, ran


def recap(result):
    return {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", result.stdout.split("PLAY RECAP")[1])}


def test_a_machine_that_answers_is_asked_once_and_nothing_is_repeated(tmp_path):
    result, refused, ran = run_wait(tmp_path, refusals=0)
    assert result.returncode == 0, result.stdout
    assert (refused, ran) == (0, 1)
    assert recap(result)["failed"] == 0 and "UNREACHABLE" not in result.stdout


def test_a_connection_that_drops_is_waited_for_and_cloud_init_asked_again(tmp_path):
    """Ansible's own ssh retries are off here, so this is the playbook's loop on its own."""
    result, refused, ran = run_wait(tmp_path, refusals=2, ssh_retries=0)
    assert refused == 2, "the stand-in refused nothing, so this test proved nothing: " + result.stdout[-600:]
    assert result.returncode == 0, result.stdout
    assert ran == 1                                          # it finished on the third ask
    assert recap(result)["unreachable"] == 0 and recap(result)["failed"] == 0
    assert result.stdout.count("UNREACHABLE") == 2           # shown, and ignored: the host stayed in the run


def test_a_short_drop_is_absorbed_by_ansibles_own_ssh_retries(tmp_path):
    result, refused, ran = run_wait(tmp_path, refusals=1)    # the setting in ansible.cfg applies
    assert refused == 1 and result.returncode == 0, result.stdout
    assert ran == 1 and "UNREACHABLE" not in result.stdout   # the first ask got through, nothing was repeated


def test_a_machine_that_never_comes_back_fails_with_a_plain_message_not_as_unreachable(tmp_path):
    result, refused, ran = run_wait(tmp_path, 100, "-e", "first_boot_attempts=2",
                                    "-e", "first_boot_ssh_wait=3", ssh_retries=0)
    assert refused == 2 and ran == 0                         # exactly the asks that were allowed
    assert result.returncode != 0
    assert "did not finish its first boot" in result.stdout
    assert recap(result)["failed"] == 1 and recap(result)["unreachable"] == 0


def test_the_create_playbook_uses_the_wait_and_ansible_retries_ssh():
    create = (ANSIBLE_DIR / "playbooks" / "create.yml").read_text()
    assert "import_playbook: wait_for_first_boot.yml" in create
    assert "cloud-init status" not in create                 # the wait lives in one place
    assert re.search(r"^retries\s*=\s*[1-9]", (ANSIBLE_DIR / "ansible.cfg").read_text(), re.MULTILINE)


def test_the_wait_playbook_passes_a_syntax_check(tmp_path):
    inventory = tmp_path / "inventory.ini"
    inventory.write_text("[es_nodes]\nnode1 ansible_host=192.0.2.10\n")
    result = subprocess.run(["ansible-playbook", "--syntax-check", "-i", str(inventory),
                             "playbooks/wait_for_first_boot.yml"], cwd=ANSIBLE_DIR, capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stderr
