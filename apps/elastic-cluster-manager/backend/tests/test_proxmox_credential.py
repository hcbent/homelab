"""Replacing a Proxmox connection's token: verified before it is saved, never echoed, audited without the secret."""
import httpx
import pytest
from sqlalchemy import select

from app import crypto
from app.discovery import factory
from app.models import AuditEvent, Credential, ProxmoxConnection
from tests.conftest import H
from tests.fixtures.transport import FixtureTransport

RIGHT = "fixture-pve-secret-value"          # the fixture Proxmox accepts ro@pve!ecm with this secret
WRONG = "an-old-or-mistyped-secret"
PVE = {"name": "lab", "api_url": "https://pve.test:8006", "token_id": "ro@pve!ecm", "token_secret": WRONG}


@pytest.fixture
def fx(monkeypatch):
    t = FixtureTransport()
    monkeypatch.setattr(factory, "transport", t)
    return t


@pytest.fixture
def broken(logged_in, fx):
    """A connection whose stored secret is wrong, exactly as on infra: its sync fails with HTTP 401."""
    r = logged_in.post("/api/proxmox", json=PVE, headers=H)
    assert r.status_code == 201
    conn_id = r.json()["id"]
    sync = logged_in.post(f"/api/proxmox/{conn_id}/sync", headers=H)
    assert sync.status_code == 502 and "HTTP 401" in sync.json()["detail"]
    return conn_id


def replace(client, conn_id, **body):
    return client.put(f"/api/proxmox/{conn_id}/credential", json=body, headers=H)


def stored_secret(session, conn_id):
    session.expire_all()
    conn = session.get(ProxmoxConnection, conn_id)
    return crypto.decrypt(session.get(Credential, conn.credential_id).ciphertext)


# ---- the case from infra ----------------------------------------------------------------------------------

def test_a_correct_secret_replaces_the_wrong_one_and_discovery_works_again(logged_in, session, broken):
    assert logged_in.get("/api/proxmox").json()[0]["last_sync_error"] == "list nodes: HTTP 401"
    r = replace(logged_in, broken, token_secret=RIGHT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last_sync_error"] is None and body["last_sync_at"]            # it synced straight away
    assert RIGHT not in r.text and WRONG not in r.text                         # a secret is never returned
    assert stored_secret(session, broken) == RIGHT
    inf = logged_in.get("/api/infrastructure").json()                          # and the data is there
    assert [n["name"] for n in inf["nodes"]] == ["pve1", "pve2", "pve3"] and [t["vmid"] for t in inf["templates"]] == [8000]
    assert session.scalar(select(Credential)).rotated_at is not None


def test_whitespace_from_pasting_is_trimmed(logged_in, session, broken):
    assert replace(logged_in, broken, token_secret=f"  {RIGHT}\n").status_code == 200
    assert stored_secret(session, broken) == RIGHT


def test_a_secret_pasted_with_whitespace_when_adding_the_connection_is_trimmed_too(logged_in, fx, session):
    r = logged_in.post("/api/proxmox", json={**PVE, "token_secret": RIGHT + "\n", "token_id": " ro@pve!ecm "},
                       headers=H)
    assert r.status_code == 201
    assert logged_in.post(f"/api/proxmox/{r.json()['id']}/sync", headers=H).status_code == 200


# ---- a bad replacement changes nothing --------------------------------------------------------------------

def test_a_rejected_secret_changes_nothing(logged_in, session, fx):
    conn_id = logged_in.post("/api/proxmox", json={**PVE, "token_secret": RIGHT}, headers=H).json()["id"]
    assert logged_in.post(f"/api/proxmox/{conn_id}/sync", headers=H).status_code == 200
    before = session.scalar(select(Credential)).ciphertext

    r = replace(logged_in, conn_id, token_secret="a-typo-that-proxmox-refuses")
    assert r.status_code == 422 and "nothing was changed" in r.json()["detail"] and "HTTP 401" in r.json()["detail"]
    session.expire_all()
    assert session.scalar(select(Credential)).ciphertext == before             # the working secret survives
    assert stored_secret(session, conn_id) == RIGHT
    assert logged_in.get("/api/proxmox").json()[0]["last_sync_error"] is None   # and is still syncing


def test_an_unreachable_proxmox_is_a_502_and_changes_nothing(logged_in, session, fx, monkeypatch):
    conn_id = logged_in.post("/api/proxmox", json={**PVE, "token_secret": RIGHT}, headers=H).json()["id"]

    def down(request):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(factory, "transport", httpx.MockTransport(down))
    r = replace(logged_in, conn_id, token_secret="whatever-the-new-secret-is")
    assert r.status_code == 502 and "nothing was changed" in r.json()["detail"]
    assert stored_secret(session, conn_id) == RIGHT


def test_a_rejected_attempt_is_audited_without_the_secret(logged_in, session, broken):
    attempt = "rejected-secret-12345678"
    assert replace(logged_in, broken, token_secret=attempt).status_code == 422
    events = session.scalars(select(AuditEvent).where(AuditEvent.action == "proxmox.credential_rejected")).all()
    assert len(events) == 1 and events[0].actor == "admin" and events[0].details == {"token_id": "ro@pve!ecm"}
    assert attempt not in str([e.details for e in session.scalars(select(AuditEvent))])


# ---- changing the token id, audit, access -----------------------------------------------------------------

def test_the_token_id_can_change_with_its_secret_and_is_tested_as_a_pair(logged_in, session, fx, monkeypatch):
    conn_id = logged_in.post("/api/proxmox", json={**PVE, "token_secret": RIGHT}, headers=H).json()["id"]
    seen = []

    def only_the_new_token(request):
        seen.append(request.headers["authorization"])
        ok = request.headers["authorization"] == "PVEAPIToken=svc@pve!ecm2=brand-new-secret-9"
        return httpx.Response(200 if ok else 401, json={"data": []})

    monkeypatch.setattr(factory, "transport", httpx.MockTransport(only_the_new_token))
    assert replace(logged_in, conn_id, token_secret="brand-new-secret-9").status_code == 422   # old id, new secret
    r = replace(logged_in, conn_id, token_secret="brand-new-secret-9", token_id="svc@pve!ecm2")
    assert r.status_code == 200 and r.json()["token_id"] == "svc@pve!ecm2"
    assert stored_secret(session, conn_id) == "brand-new-secret-9"
    assert seen[0].startswith("PVEAPIToken=ro@pve!ecm=")                        # the first try used the old id


def test_the_replacement_is_audited_with_the_token_id_only(logged_in, session, broken):
    replace(logged_in, broken, token_secret=RIGHT)
    event = session.scalar(select(AuditEvent).where(AuditEvent.action == "proxmox.credential_replace"))
    assert event.details == {"token_id": "ro@pve!ecm"} and event.target_id == broken
    assert RIGHT not in str([e.details for e in session.scalars(select(AuditEvent))])


def test_testing_the_token_is_read_only(logged_in, broken, fx):
    replace(logged_in, broken, token_secret=RIGHT)
    assert fx.methods == {"GET"}                                               # the fixture would fail on a write


def test_it_needs_a_session_the_csrf_header_a_real_connection_and_a_long_enough_secret(client, logged_in, broken):
    assert logged_in.put("/api/proxmox/nope/credential", json={"token_secret": RIGHT}, headers=H).status_code == 404
    assert replace(logged_in, broken, token_secret="short").status_code == 422
    assert replace(logged_in, broken, token_secret=RIGHT, token_id="ab").status_code == 422
    assert logged_in.put(f"/api/proxmox/{broken}/credential", json={"token_secret": RIGHT}).status_code in (400, 403)
    logged_in.cookies.clear()
    assert replace(logged_in, broken, token_secret=RIGHT).status_code == 401
