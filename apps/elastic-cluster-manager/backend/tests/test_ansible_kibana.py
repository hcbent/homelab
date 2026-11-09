"""What the Ansible side of adding Kibana is handed: the inventory (which Elasticsearch addresses Kibana is given, the Kibana host group, the
names on its certificate) and the runner (what it demands, where the secrets go, how a freshly made service token comes back)."""
import json
from datetime import UTC, datetime

import pytest

from app.configmgmt import (
    AnsibleError,
    AnsibleRequest,
    InventoryError,
    InventoryInput,
    KibanaHost,
    render_inventory,
)
from app.configmgmt.inventory import kibana_es_hosts
from app.crypto import redact
from app.desired import TopologyPreset, build_desired_state
from tests.test_ansible_runner import PASSWORD, fake, recorded, request, runner, work_dir_is_empty

KEYS = {"security": "s" * 40, "saved_objects": "o" * 40, "reporting": "r" * 40}
TOKEN = "AAEAAWVsYXN0aWMva2liYW5hL0001FakeServiceTokenForTests"
CA_CERT = "-----BEGIN CERTIFICATE-----\nFakeCaCertificateBody0000\n-----END CERTIFICATE-----\n"
CA_KEY = "-----BEGIN " + "PRIVATE KEY-----\nFakeCaKeyBodyForTests000000001\n-----END " + "PRIVATE KEY-----\n"
API_KEY = "FakeEncodedApiKeyForTests0000000001"


def host(**over):
    return KibanaHost(**{"name": "lab-x-kb-01", "address": "192.0.2.50", **over})


def inventory_input(**over):
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-x", "9.5.6", data_nodes=2, coordinating_nodes=1)
    names = [n.name for n in state.nodes]
    base = {"state": state, "addresses": {n: f"192.0.2.{10 + i}" for i, n in enumerate(names)}, "operation_kind": "add_kibana",
            "bootstrapped_at": datetime(2026, 11, 9, tzinfo=UTC), "ssh_user": "bret", "ssh_key_path": "/run/ecm/ssh/k",
            "known_hosts_path": "/tmp/kh", "artifacts_dir": "/tmp/art", "search_domain": "lab.example.org",
            "kibana": [host()]}
    base.update(over)
    return InventoryInput(**base)


# -- which Elasticsearch nodes Kibana is given ------------------------------------------------------------------------------------

def test_kibana_is_given_the_nodes_that_are_not_master_only_as_explicit_https_addresses():
    inp = inventory_input()
    names = [n.name for n in inp.state.nodes]
    # three dedicated masters (01-03), two data nodes (04-05), one coordinating node (06)
    assert kibana_es_hosts(inp.state, inp.addresses) == [f"https://{inp.addresses[n]}:9200" for n in names[3:]]


def test_no_more_than_three_are_listed_and_an_all_in_one_cluster_uses_its_nodes():
    big = build_desired_state(TopologyPreset.dedicated_masters, "lab-x", "9.5.6", data_nodes=5, coordinating_nodes=2)
    addresses = {n.name: f"192.0.2.{10 + i}" for i, n in enumerate(big.nodes)}
    assert len(kibana_es_hosts(big, addresses)) == 3
    small = build_desired_state(TopologyPreset.three_node, "lab-x", "9.5.6")             # every node holds every role
    assert len(kibana_es_hosts(small, {n.name: f"192.0.2.{10 + i}" for i, n in enumerate(small.nodes)})) == 3


# -- the inventory ----------------------------------------------------------------------------------------------------------------

def test_the_inventory_has_a_kibana_group_and_names_the_hosts_kibana_is_given_and_its_token():
    inv = render_inventory(inventory_input(kibana=[host(public_url="https://kibana.lab.example.org")]))
    v = inv["all"]["vars"]
    assert v["es_operation"] == "add_kibana" and v["kibana_token_name"] == "ecm-lab-x-kb-01"
    assert v["kibana_es_hosts"] == ["https://192.0.2.13:9200", "https://192.0.2.14:9200", "https://192.0.2.15:9200"]
    (k,) = inv["all"]["children"]["kibana_hosts"]["hosts"].values()
    assert (k["ansible_host"], k["kibana_ip"], k["kibana_port"]) == ("192.0.2.50", "192.0.2.50", 5601)
    assert k["kibana_public_url"] == "https://kibana.lab.example.org"
    # the certificate names: its own, its fully qualified one, and the public name; the names es_tls reads are set too
    assert k["es_dns_names"] == ["lab-x-kb-01", "lab-x-kb-01.lab.example.org", "kibana.lab.example.org"]
    assert (k["es_node_name"], k["es_node_ip"]) == ("lab-x-kb-01", "192.0.2.50")


def test_without_a_public_name_there_is_none_on_the_certificate_or_in_the_host_vars():
    (k,) = render_inventory(inventory_input())["all"]["children"]["kibana_hosts"]["hosts"].values()
    assert "kibana_public_url" not in k and k["es_dns_names"] == ["lab-x-kb-01", "lab-x-kb-01.lab.example.org"]


def test_kibana_is_not_an_elasticsearch_node_in_the_inventory():
    inv = render_inventory(inventory_input())
    children = inv["all"]["children"]
    assert "lab-x-kb-01" not in children["es_nodes"]["hosts"] and "lab-x-kb-01" not in json.dumps(children["es_bootstrap"])
    assert inv["all"]["vars"]["es_expected_nodes"] == 6                                  # the quorum arithmetic counts nodes only
    assert inv["all"]["vars"]["es_ca_host"] in children["es_nodes"]["hosts"]            # an existing node signs Kibana's certificate


def test_other_kinds_have_no_kibana_group():
    inv = render_inventory(inventory_input(operation_kind="converge", kibana=None))
    assert "kibana_hosts" not in inv["all"]["children"] and "kibana_es_hosts" not in inv["all"]["vars"]


@pytest.mark.parametrize("over,message", [
    ({"bootstrapped_at": None}, "has bootstrapped"),
    ({"kibana": None}, "needs the Kibana machine"),
    ({"kibana": []}, "needs the Kibana machine"),
    ({"kibana": [host(name="lab-x-01")]}, "a name of its own"),
    ({"kibana": [host(), host(address="192.0.2.51")]}, "a name of its own"),
    ({"kibana": [host(address="not-an-ip")]}, "not an IPv4 address"),
    ({"kibana": [host(address="192.0.2.10")]}, "has the address of a node"),
])
def test_a_bad_kibana_inventory_is_refused(over, message):
    with pytest.raises(InventoryError, match=message):
        render_inventory(inventory_input(**over))


# -- the runner -------------------------------------------------------------------------------------------------------------------

def kibana_request(**over):
    base = {"kind": "add_kibana", "kibana": [host()], "kibana_keys": dict(KEYS), "es_api_key": API_KEY, "es_ca_pem": CA_CERT,
            "ca_cert_pem": CA_CERT, "ca_key_pem": CA_KEY}
    base.update(over)
    return request(**base)


def test_the_run_uses_the_kibana_playbook_with_the_secrets_in_the_private_extra_vars_file_only(tmp_path):
    binary, record = fake(tmp_path)
    out = runner(tmp_path, binary)[0].run(kibana_request(kibana_token=TOKEN))
    assert out.ok
    seen = recorded(record)
    assert seen["argv"][-1] == "playbooks/add_kibana.yml"
    extra = seen["extra"]
    assert extra["kibana_encryption_keys"] == KEYS and extra["kibana_service_token"] == TOKEN
    assert extra["es_api_key"] == API_KEY and extra["first_boot_hosts"] == "kibana_hosts"
    assert extra["es_ca_cert_pem"] == CA_CERT and extra["es_ca_key_pem"] == CA_KEY
    assert seen["extra_mode"] == "0o600"
    on_disk = json.dumps(seen["inventory"]) + " ".join(seen["argv"])
    for secret in (TOKEN, *KEYS.values(), API_KEY, CA_KEY):
        assert secret not in on_disk                                                     # not in the inventory or on the command line
    assert work_dir_is_empty(tmp_path)


def test_a_first_run_hands_no_token_to_ansible_and_a_retry_hands_back_the_one_it_holds(tmp_path):
    binary, record = fake(tmp_path)
    runner(tmp_path, binary)[0].run(kibana_request())
    assert "kibana_service_token" not in recorded(record)["extra"]


def test_the_ca_the_worker_checks_kibana_against_is_a_private_file_removed_with_the_run(tmp_path):
    binary, record = fake(tmp_path)
    runner(tmp_path, binary)[0].run(kibana_request())
    assert recorded(record)["extra"]["es_ca_file"].endswith("es-ca.crt")
    assert work_dir_is_empty(tmp_path)


def test_a_token_the_run_made_is_returned_even_when_the_run_then_failed(tmp_path):
    fail = ["TASK [kibana_health : Stop if Kibana is not available]", 'fatal: [localhost]: FAILED! => {"msg": "Kibana did not become available"}',
            "PLAY RECAP *****", "localhost                  : ok=9    changed=1    unreachable=0    failed=1    skipped=2    rescued=0"]
    binary, _ = fake(tmp_path, artifacts={"kibana-token": TOKEN + "\n"}, output=fail, exit=2)
    out = runner(tmp_path, binary)[0].run(kibana_request())
    assert not out.ok and "Kibana did not become available" in out.error
    assert out.kibana_token == TOKEN                                                     # it cannot be read from the cluster again


def test_a_run_that_made_no_token_returns_none(tmp_path):
    binary, _ = fake(tmp_path)
    assert runner(tmp_path, binary)[0].run(kibana_request(kibana_token=TOKEN)).kibana_token is None


def test_the_token_and_the_keys_are_redacted_from_the_log_when_a_task_echoes_them(tmp_path):
    binary, _ = fake(tmp_path, echo_extra=True)
    r, lines = runner(tmp_path, binary)
    r.run(kibana_request(kibana_token=TOKEN))
    text = "\n".join(lines)
    for secret in (TOKEN, *KEYS.values(), API_KEY):
        assert secret not in text and secret not in redact(secret)


def test_a_token_that_was_made_is_redacted_as_soon_as_it_is_read(tmp_path):
    binary, _ = fake(tmp_path, artifacts={"kibana-token": TOKEN})
    runner(tmp_path, binary)[0].run(kibana_request())
    assert TOKEN not in redact(f"the token is {TOKEN}")


def test_the_secrets_do_not_appear_in_the_repr_of_a_request_or_an_outcome(tmp_path):
    binary, _ = fake(tmp_path, artifacts={"kibana-token": TOKEN})
    req = kibana_request(kibana_token=TOKEN)
    out = runner(tmp_path, binary)[0].run(req)
    for secret in (TOKEN, *KEYS.values()):
        assert secret not in repr(req) and secret not in repr(out)


@pytest.mark.parametrize("over,message", [
    ({"kibana": None}, "the Kibana machine"),
    ({"es_api_key": None}, "the ECM API key"),
    ({"es_ca_pem": None, "ca_cert_pem": None, "ca_key_pem": None}, "the cluster's CA certificate, the cluster's CA key"),
    ({"es_ca_pem": None, "ca_cert_pem": None}, "together, or neither"),         # a key with no certificate: refused for every kind
    ({"ca_key_pem": None}, "together, or neither"),
    ({"kibana_keys": None}, "encryption keys"),
    ({"kibana_keys": {"security": "x" * 40}}, "security, saved_objects and reporting"),
    ({"check": True}, "cannot be checked"),
])
def test_a_bad_kibana_request_is_refused_before_ansible_starts(tmp_path, over, message):
    binary, record = fake(tmp_path)
    with pytest.raises(AnsibleError, match=message):
        runner(tmp_path, binary)[0].run(kibana_request(**over))
    assert not record.exists()
    assert work_dir_is_empty(tmp_path)


def test_an_ordinary_run_reads_no_token_back_and_needs_no_kibana_input(tmp_path):
    binary, record = fake(tmp_path)
    out = runner(tmp_path, binary)[0].run(request("converge"))
    assert out.ok and out.kibana_token is None and "kibana_encryption_keys" not in (recorded(record)["extra"] or {})


def test_the_request_type_still_has_no_required_kibana_fields():
    assert AnsibleRequest.__dataclass_fields__["kibana"].default is None and PASSWORD
