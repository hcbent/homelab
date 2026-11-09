"""The two worker-side halves of adding Kibana, run for real with ansible-playbook against a local HTTPS server that plays Elasticsearch and
Kibana: asking the cluster for a service token (once, and never a second time on a retry) and checking Kibana reports itself available.

The roles that run on the Kibana machine (package, certificate, keystore, service) cannot be exercised without a VM; this does not claim to.
"""
import datetime
import ipaddress
import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "infra" / "ansible"
API_KEY = "FakeEncodedApiKeyForTests0000000001"
TOKEN_NAME = "ecm-lab-b-kb-01"
TOKEN_PATH = f"/_security/service/elastic/kibana/credential/token/{TOKEN_NAME}"

pytestmark = pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible is not installed")


def _key():
    return ec.generate_private_key(ec.SECP256R1())


def _name(common: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


def make_pki(directory: Path) -> tuple[Path, Path, Path]:
    """A throwaway CA and a server certificate for 127.0.0.1 signed by it. Returns (ca.crt, server.crt, server.key)."""
    now = datetime.datetime.now(datetime.UTC)
    ca_key = _key()
    ca = (x509.CertificateBuilder().subject_name(_name("test-ca")).issuer_name(_name("test-ca")).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
          .not_valid_after(now + datetime.timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                       key_encipherment=False, data_encipherment=False, key_agreement=False,
                                       encipher_only=False, decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    key = _key()
    cert = (x509.CertificateBuilder().subject_name(_name("fake-elastic")).issuer_name(ca.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    paths = (directory / "ca.crt", directory / "server.crt", directory / "server.key")
    paths[0].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    paths[1].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    paths[2].write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return paths


class Fake:
    """What the fake Elasticsearch and Kibana hold and have been asked. Tests change the attributes between runs."""

    def __init__(self):
        self.tokens: dict[str, str] = {}        # token name -> value the cluster issued
        self.issued = 0
        self.calls: list[tuple[str, str, str | None]] = []      # (method, path, Authorization header)
        self.token_status = 200                 # what a request for a token gets, unless the token already exists
        self.delete_status = 200
        self.kibana_status = 200
        self.kibana_level = "available"
        self.kibana_summary = "All services and plugins are available"

    def count(self, method: str, path: str | None = None) -> int:
        return sum(1 for m, p, _ in self.calls if m == method and (path is None or p == path))


@pytest.fixture
def server(tmp_path):
    ca, crt, key = make_pki(tmp_path)
    fake = Fake()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _note(self) -> None:
            fake.calls.append((self.command, self.path, self.headers.get("authorization")))

        def do_POST(self):
            self._note()
            if self.path != TOKEN_PATH:
                return self._send(404, {"error": "no such path"})
            if self.path.rsplit("/", 1)[-1] in fake.tokens:
                return self._send(409, {"error": {"type": "version_conflict_engine_exception"}})
            if fake.token_status != 200:
                return self._send(fake.token_status, {"error": {"reason": "security_exception"}})
            fake.issued += 1
            value = f"AAEAAWVsYXN0aWMva2liYW5hL{fake.issued:04d}FakeTokenValueForTests"
            fake.tokens[TOKEN_NAME] = value
            return self._send(200, {"created": True, "token": {"name": TOKEN_NAME, "value": value}})

        def do_DELETE(self):
            self._note()
            if fake.delete_status != 200:
                return self._send(fake.delete_status, {"error": "refused"})
            found = fake.tokens.pop(self.path.rsplit("/", 1)[-1], None) is not None
            return self._send(200, {"found": found})

        def do_GET(self):
            self._note()
            if self.path != "/api/status":
                return self._send(404, {})
            if fake.kibana_status != 200:
                return self._send(fake.kibana_status, {"error": "refused"})
            return self._send(200, {"status": {"overall": {"level": fake.kibana_level, "summary": fake.kibana_summary}}})

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(crt), str(key))
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    fake.port, fake.ca, fake.dir = httpd.server_address[1], ca, tmp_path
    yield fake
    httpd.shutdown()
    httpd.server_close()


def run_playbook(server: Fake, playbook: str, **extra) -> subprocess.CompletedProcess:
    """Run one of the real playbooks from the Ansible directory, on localhost, against the fake. Returns the process (never raises)."""
    port = server.port
    inventory = {"all": {
        "vars": {"kibana_es_hosts": [f"https://127.0.0.1:{port}"], "kibana_token_name": TOKEN_NAME,
                 "es_artifacts_dir": str(server.dir / "artifacts")},
        "children": {"kibana_hosts": {"hosts": {"lab-b-kb-01": {
            "kibana_name": "lab-b-kb-01", "kibana_ip": "127.0.0.1", "kibana_port": port}}}}}}
    (server.dir / "inventory.json").write_text(json.dumps(inventory))
    variables = {"es_api_key": API_KEY, "es_ca_file": str(server.ca), **extra}
    (server.dir / "extra.json").write_text(json.dumps(variables))
    return subprocess.run(
        ["ansible-playbook", "-i", str(server.dir / "inventory.json"), "-e", f"@{server.dir / 'extra.json'}", f"playbooks/{playbook}"],
        cwd=ANSIBLE_DIR, capture_output=True, text=True, timeout=180, check=False,
        env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin", "HOME": str(server.dir),
             "ANSIBLE_LOCAL_TEMP": str(server.dir / "tmp"), "ANSIBLE_NOCOLOR": "1"})


def handed_back(server: Fake) -> Path:
    return server.dir / "artifacts" / "kibana-token"


# -- asking the cluster for a service token ---------------------------------------------------------------------------------

def test_the_cluster_is_asked_for_one_token_with_ecms_api_key_and_it_is_handed_back_privately(server):
    result = run_playbook(server, "kibana_credential.yml")
    assert result.returncode == 0, result.stdout + result.stderr
    assert [(m, p) for m, p, _ in server.calls] == [("POST", TOKEN_PATH)]
    assert server.calls[0][2] == f"ApiKey {API_KEY}"
    token = handed_back(server)
    assert token.read_text() == server.tokens[TOKEN_NAME]
    assert oct(token.stat().st_mode & 0o777) == "0o600"
    assert oct(token.parent.stat().st_mode & 0o777) == "0o700"


def test_neither_the_token_nor_the_api_key_reaches_the_output(server):
    result = run_playbook(server, "kibana_credential.yml")
    assert result.returncode == 0
    assert server.tokens[TOKEN_NAME] not in result.stdout + result.stderr
    assert API_KEY not in result.stdout + result.stderr


def test_a_retry_that_is_given_the_token_asks_the_cluster_for_nothing(server):
    server.tokens[TOKEN_NAME] = "the-token-ecm-already-holds"
    result = run_playbook(server, "kibana_credential.yml", kibana_service_token="the-token-ecm-already-holds")
    assert result.returncode == 0, result.stdout + result.stderr
    assert server.calls == []                                   # no second token, no delete
    assert not handed_back(server).exists()                     # nothing new for ECM to store


def test_a_token_the_cluster_has_but_ecm_never_received_is_replaced_not_reused(server):
    server.tokens[TOKEN_NAME] = "made-by-a-run-that-died-before-handing-it-back"
    result = run_playbook(server, "kibana_credential.yml")
    assert result.returncode == 0, result.stdout + result.stderr
    assert [m for m, _, _ in server.calls] == ["POST", "DELETE", "POST"]
    assert handed_back(server).read_text() == server.tokens[TOKEN_NAME]
    assert server.tokens[TOKEN_NAME] != "made-by-a-run-that-died-before-handing-it-back"


@pytest.mark.parametrize("status", [401, 403, 500])
def test_a_refusal_stops_the_run_with_the_status_and_hands_back_nothing(server, status):
    server.token_status = status
    result = run_playbook(server, "kibana_credential.yml")
    assert result.returncode != 0
    assert f"HTTP {status}" in result.stdout + result.stderr
    assert not handed_back(server).exists()


def test_a_token_that_cannot_be_deleted_is_not_papered_over(server):
    server.tokens[TOKEN_NAME] = "old"
    server.delete_status = 403
    result = run_playbook(server, "kibana_credential.yml")
    assert result.returncode != 0 and "HTTP 403" in result.stdout + result.stderr
    assert server.count("POST") == 1                            # it did not ask again after failing to delete


# -- checking Kibana is available ----------------------------------------------------------------------------------------------

def test_kibana_that_reports_itself_available_passes_and_is_asked_with_ecms_api_key(server):
    result = run_playbook(server, "kibana_health.yml")
    assert result.returncode == 0, result.stdout + result.stderr
    assert [(m, p) for m, p, _ in server.calls] == [("GET", "/api/status")]
    assert server.calls[0][2] == f"ApiKey {API_KEY}"
    assert API_KEY not in result.stdout + result.stderr


def test_kibana_that_stays_degraded_fails_the_run_and_says_what_it_reported(server):
    server.kibana_level, server.kibana_summary = "degraded", "1 service is degraded: elasticsearch"
    result = run_playbook(server, "kibana_health.yml", kh_wait=3, kh_poll=1)
    assert result.returncode != 0
    out = result.stdout + result.stderr
    assert "lab-b-kb-01 is degraded: 1 service is degraded: elasticsearch" in out
    assert "Retry runs the configuration and the check again" in out
    assert server.count("GET") > 1                              # it waited and looked again before giving up


def test_kibana_that_turns_available_while_waiting_passes(server):
    server.kibana_level = "unavailable"

    def recover():
        import time
        time.sleep(2.5)
        server.kibana_level = "available"
    threading.Thread(target=recover, daemon=True).start()
    result = run_playbook(server, "kibana_health.yml", kh_wait=30, kh_poll=1)
    assert result.returncode == 0, result.stdout + result.stderr
    assert server.count("GET") >= 2


@pytest.mark.parametrize("status", [401, 403])
def test_kibana_refusing_the_api_key_is_reported_as_that(server, status):
    server.kibana_status = status
    result = run_playbook(server, "kibana_health.yml", kh_wait=2, kh_poll=1)
    assert result.returncode != 0
    assert f"lab-b-kb-01 refused the API key (HTTP {status})" in result.stdout + result.stderr


def test_a_kibana_that_does_not_answer_is_reported_as_not_answering(server):
    server.port = 1                                             # nothing listens here
    result = run_playbook(server, "kibana_health.yml", kh_wait=2, kh_poll=1)
    assert result.returncode != 0 and "lab-b-kb-01 did not answer" in result.stdout + result.stderr


def test_the_run_wont_start_without_the_api_key_or_the_ca(server):
    result = run_playbook(server, "kibana_health.yml", es_api_key="")
    assert result.returncode != 0 and "needs the ECM API key" in result.stdout + result.stderr
