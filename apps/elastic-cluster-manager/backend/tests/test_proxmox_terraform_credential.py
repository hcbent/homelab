"""A separate Terraform token on a Proxmox connection: checked with a read-only request, stored apart from the
discovery token, used by Terraform, and never echoed."""
import httpx
import pytest
from sqlalchemy import select

from app import crypto
from app.discovery import factory, proxmox
from app.models import AuditEvent, Credential, Operation, ProxmoxConnection
from app.provisioning.operation import _Handlers
from tests.conftest import H
from tests.fixtures.transport import FixtureTransport

DISCOVERY = {"name": "lab", "api_url": "https://pve.test:8006", "token_id": "ro@pve!ecm",
             "token_secret": "fixture-pve-secret-value"}
TF_ID, TF_SECRET = "tf@pve!terraform", "terraform-secret-1111"

# What /access/permissions returns: effective privileges per path, as seen on the real Proxmox.
POOL_SCOPED = {"/pool/ecm": {"VM.Allocate": 1, "VM.Audit": 1, "Pool.Audit": 1},
               "/storage/tank": {"Datastore.Audit": 1, "Datastore.AllocateSpace": 1},
               "/vms/8000": {"VM.Audit": 1}}
READ_ONLY = {"/": {"Sys.Audit": 1, "VM.Audit": 1, "Datastore.Audit": 1, "Pool.Audit": 1},
             "/pool/ecm": {"VM.Audit": 1, "Pool.Audit": 1}}
NO_STORAGE = {"/pool/ecm": {"VM.Allocate": 1}}
TOO_BROAD = {"/": {"Permissions.Modify": 1, "Sys.Modify": 1}, "/pool/ecm": {"VM.Allocate": 1},
             "/storage/tank": {"Datastore.AllocateSpace": 1}}


def serving(by_secret, seen=None):
    """A Proxmox that knows which secrets are valid and what each may do. Records every request."""
    seen = seen if seen is not None else []

    def handler(request):
        seen.append((request.method, request.url.path))
        secret = request.headers["authorization"].rsplit("=", 1)[1]
        if secret not in by_secret:
            return httpx.Response(401, json={"errors": "no ticket"})
        return httpx.Response(200, json={"data": by_secret[secret]})

    transport = httpx.MockTransport(handler)
    transport.seen = seen
    return transport


@pytest.fixture
def conn_id(logged_in, monkeypatch):
    """A synced connection with only its discovery token, as every existing connection is."""
    monkeypatch.setattr(factory, "transport", FixtureTransport())
    cid = logged_in.post("/api/proxmox", json=DISCOVERY, headers=H).json()["id"]
    assert logged_in.post(f"/api/proxmox/{cid}/sync", headers=H).status_code == 200
    return cid


def put(client, cid, **body):
    return client.put(f"/api/proxmox/{cid}/credential", json={"purpose": "terraform", **body}, headers=H)


def decrypted(session, credential_id):
    session.expire_all()
    return crypto.decrypt(session.get(Credential, credential_id).ciphertext)


# ---- setting it ------------------------------------------------------------------------------------------

def test_a_terraform_token_is_stored_apart_from_the_discovery_token(logged_in, session, conn_id, monkeypatch):
    conn = session.get(ProxmoxConnection, conn_id)
    discovery_before = session.get(Credential, conn.credential_id).ciphertext
    assert logged_in.get("/api/proxmox").json()[0]["terraform_token_id"] is None

    seen: list = []
    monkeypatch.setattr(factory, "transport", serving({TF_SECRET: POOL_SCOPED}, seen))
    r = put(logged_in, conn_id, token_id=TF_ID, token_secret=TF_SECRET)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["terraform_token_id"] == TF_ID and body["token_id"] == "ro@pve!ecm" and body["warnings"] == []
    assert TF_SECRET not in r.text
    session.expire_all()
    conn = session.get(ProxmoxConnection, conn_id)
    assert session.get(Credential, conn.credential_id).ciphertext == discovery_before       # discovery untouched
    assert decrypted(session, conn.credential_id) == DISCOVERY["token_secret"]
    assert decrypted(session, conn.terraform_credential_id) == TF_SECRET
    assert len(session.scalars(select(Credential)).all()) == 2
    assert seen == [("GET", "/api2/json/access/permissions")]       # one read-only request, and no sync
    event = session.scalar(select(AuditEvent).where(AuditEvent.action == "proxmox.credential_replace"))
    assert event.details == {"token_id": TF_ID, "purpose": "terraform"}
    assert TF_SECRET not in str([e.details for e in session.scalars(select(AuditEvent))])
    assert logged_in.get("/api/proxmox").json()[0]["terraform_token_id"] == TF_ID


def test_setting_it_again_replaces_the_same_credential(logged_in, session, conn_id, monkeypatch):
    monkeypatch.setattr(factory, "transport", serving({TF_SECRET: POOL_SCOPED, "rotated-secret-2222": POOL_SCOPED}))
    put(logged_in, conn_id, token_id=TF_ID, token_secret=TF_SECRET)
    first = session.get(ProxmoxConnection, conn_id).terraform_credential_id

    r = put(logged_in, conn_id, token_secret="rotated-secret-2222")          # the id is remembered
    assert r.status_code == 200 and r.json()["terraform_token_id"] == TF_ID
    session.expire_all()
    conn = session.get(ProxmoxConnection, conn_id)
    assert conn.terraform_credential_id == first and len(session.scalars(select(Credential)).all()) == 2
    assert decrypted(session, first) == "rotated-secret-2222"
    assert session.get(Credential, first).rotated_at is not None


def test_the_first_time_needs_a_token_id(logged_in, conn_id):
    r = put(logged_in, conn_id, token_secret=TF_SECRET)
    assert r.status_code == 422 and "send token_id" in r.json()["detail"]


# ---- what is required, what is only advice ---------------------------------------------------------------

def test_a_token_that_cannot_create_vms_in_the_pool_is_refused_and_nothing_is_saved(
        logged_in, session, conn_id, monkeypatch):
    monkeypatch.setattr(factory, "transport", serving({TF_SECRET: READ_ONLY}))
    r = put(logged_in, conn_id, token_id=TF_ID, token_secret=TF_SECRET)
    detail = r.json()["detail"]
    assert r.status_code == 422 and "VM.Allocate on /pool/ecm" in detail and "Nothing was changed" in detail
    session.expire_all()
    conn = session.get(ProxmoxConnection, conn_id)
    assert conn.terraform_credential_id is None and conn.terraform_token_id is None
    assert len(session.scalars(select(Credential)).all()) == 1
    rejected = session.scalars(select(AuditEvent).where(AuditEvent.action == "proxmox.credential_rejected")).all()
    assert [e.details for e in rejected] == [{"token_id": TF_ID, "purpose": "terraform"}]


def test_the_pool_and_datastore_to_check_can_be_named(logged_in, conn_id, monkeypatch):
    monkeypatch.setattr(factory, "transport", serving({TF_SECRET: POOL_SCOPED}))
    r = put(logged_in, conn_id, token_id=TF_ID, token_secret=TF_SECRET, pool_id="labpool")
    assert r.status_code == 422 and "/pool/labpool" in r.json()["detail"]
    r = put(logged_in, conn_id, token_id=TF_ID, token_secret=TF_SECRET, datastore="fast")
    assert r.status_code == 200 and any("/storage/fast" in w for w in r.json()["warnings"])


def test_missing_storage_rights_and_an_over_broad_token_are_advice_not_refusals(logged_in, conn_id, monkeypatch):
    monkeypatch.setattr(factory, "transport", serving({"no-storage-secret-1": NO_STORAGE,
                                                       "too-broad-secret-22": TOO_BROAD}))
    r = put(logged_in, conn_id, token_id=TF_ID, token_secret="no-storage-secret-1")
    assert r.status_code == 200 and len(r.json()["warnings"]) == 1
    assert "Datastore.AllocateSpace on /storage/tank" in r.json()["warnings"][0]

    r = put(logged_in, conn_id, token_id=TF_ID, token_secret="too-broad-secret-22")
    assert r.status_code == 200 and len(r.json()["warnings"]) == 1
    assert "Permissions.Modify" in r.json()["warnings"][0] and "Sys.Modify" in r.json()["warnings"][0]


def test_a_rejected_secret_or_an_unreachable_proxmox_changes_nothing(logged_in, session, conn_id, monkeypatch):
    monkeypatch.setattr(factory, "transport", serving({}))
    r = put(logged_in, conn_id, token_id=TF_ID, token_secret="wrongwrongwrong")
    assert r.status_code == 422 and "rejected that token" in r.json()["detail"]

    def down(request):
        raise httpx.ConnectError("no route to host")
    monkeypatch.setattr(factory, "transport", httpx.MockTransport(down))
    r = put(logged_in, conn_id, token_id=TF_ID, token_secret=TF_SECRET)
    assert r.status_code == 502 and "nothing was changed" in r.json()["detail"]
    assert session.get(ProxmoxConnection, conn_id).terraform_credential_id is None


def test_the_discovery_purpose_is_unchanged_and_the_default(logged_in, session, conn_id):
    r = logged_in.put(f"/api/proxmox/{conn_id}/credential", json={"token_secret": DISCOVERY["token_secret"]}, headers=H)
    assert r.status_code == 200 and r.json()["terraform_token_id"] is None
    assert logged_in.put(f"/api/proxmox/{conn_id}/credential", json={"token_secret": TF_SECRET, "purpose": "other"},
                         headers=H).status_code == 422


# ---- reading effective privileges ------------------------------------------------------------------------

def test_a_listed_path_is_authoritative_and_only_an_unlisted_one_inherits():
    perms = {"/": {"VM.Allocate": 1}, "/pool/ecm": {"VM.Audit": 1}, "/storage": {"Datastore.AllocateSpace": 1}}
    assert not proxmox.has_privilege(perms, "/pool/ecm", "VM.Allocate")        # an explicit entry replaces the parent's
    assert proxmox.has_privilege(perms, "/pool/ecm", "VM.Audit")
    assert proxmox.has_privilege(perms, "/pool/other", "VM.Allocate")          # unlisted: inherits from /, its nearest
    assert not proxmox.has_privilege({"/pool": {"VM.Audit": 1}, "/": {"VM.Allocate": 1}}, "/pool/other", "VM.Allocate")
    assert proxmox.has_privilege(perms, "/storage/tank", "Datastore.AllocateSpace")   # inherited from /storage
    assert proxmox.has_privilege({}, "/pool/ecm", "VM.Allocate") is False
    assert proxmox.has_privilege({"/pool/ecm": None}, "/pool/ecm", "VM.Allocate") is False


# ---- Terraform uses it -----------------------------------------------------------------------------------

def make_connection(session, *, separate):
    discovery = Credential(kind="proxmox_token", name="d", ciphertext=crypto.encrypt("discovery-secret-9999"))
    session.add(discovery)
    session.flush()
    conn = ProxmoxConnection(name="pve", api_url="https://pve.test:8006", token_id="ro@pve!ecm",
                             credential_id=discovery.id)
    if separate:
        tf = Credential(kind="proxmox_token", name="t", ciphertext=crypto.encrypt(TF_SECRET))
        session.add(tf)
        session.flush()
        conn.terraform_credential_id, conn.terraform_token_id = tf.id, TF_ID
    session.add(conn)
    op = Operation(kind="tf.create", params={"proxmox_connection_id": None})
    session.add(op)
    session.flush()
    op.params = {"proxmox_connection_id": conn.id}
    session.commit()
    return op


def tf_env(session, tmp_path, op, monkeypatch):
    monkeypatch.setenv("ECM_TF_STATE_URL", "postgresql://tf:statepw1234@db/tfstate")
    from app import config
    config.get_settings.cache_clear()
    return _Handlers(session, op, lambda _log: None, tmp_path)._env()


def test_terraform_runs_with_its_own_token_when_the_connection_has_one(session, tmp_path, monkeypatch):
    env = tf_env(session, tmp_path, make_connection(session, separate=True), monkeypatch)
    assert env["PROXMOX_VE_API_TOKEN"] == f"{TF_ID}={TF_SECRET}"
    assert "discovery-secret-9999" not in str(env)                           # the discovery token never reaches it


def test_without_a_separate_token_terraform_falls_back_to_the_discovery_token(session, tmp_path, monkeypatch):
    env = tf_env(session, tmp_path, make_connection(session, separate=False), monkeypatch)
    assert env["PROXMOX_VE_API_TOKEN"] == "ro@pve!ecm=discovery-secret-9999"
