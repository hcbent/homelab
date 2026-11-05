"""A token that authenticates but may not audit the nodes: refused loudly, and it never wipes the stored picture.

The shape is the real one seen on infra: Proxmox lists each node with a status but leaves out its CPU and memory.
"""
import httpx
import pytest
from sqlalchemy import select

from app import crypto
from app.desired import HostView, TopologyPreset, build_desired_state, recommend_placement
from app.discovery import factory, proxmox
from app.discovery.http import InsufficientRights
from app.models import AuditEvent, Credential
from tests.conftest import H
from tests.fixtures.transport import FixtureTransport

GOOD = {"name": "lab", "api_url": "https://pve.test:8006", "token_id": "ro@pve!ecm",
        "token_secret": "fixture-pve-secret-value"}
HOSTS = ("pve1", "pve2", "pve3")


def blind(request):
    """What a pool-scoped token gets: nodes with a status and nothing else it may read."""
    assert request.method == "GET"
    if request.url.path.endswith("/api2/json/nodes"):
        return httpx.Response(200, json={"data": [{"node": n, "status": "online"} for n in HOSTS]})
    return httpx.Response(403, json={"errors": "permission check failed"})


@pytest.fixture
def synced(logged_in, monkeypatch):
    monkeypatch.setattr(factory, "transport", FixtureTransport())
    conn_id = logged_in.post("/api/proxmox", json=GOOD, headers=H).json()["id"]
    assert logged_in.post(f"/api/proxmox/{conn_id}/sync", headers=H).status_code == 200
    return conn_id


def picture(client):
    inf = client.get("/api/infrastructure").json()
    return {k: inf[k] for k in ("nodes", "storages", "templates", "vms")}


# ---- the check itself -------------------------------------------------------------------------------------

def full(name):
    return {"node": name, "status": "online", "maxcpu": 8, "maxmem": 16 * 1024**3}


def test_every_online_node_without_figures_is_refused_with_the_privilege_to_grant():
    with pytest.raises(InsufficientRights, match="Sys.Audit.*PVEAuditor"):
        proxmox.check_node_usage([{"node": "pve1", "status": "online"}, {"node": "pve2", "status": "online"}])


@pytest.mark.parametrize("partial", [{"maxcpu": 8}, {"maxmem": 16 * 1024**3}])
def test_figures_are_only_usable_with_both_cpu_and_memory(partial):
    with pytest.raises(InsufficientRights):
        proxmox.check_node_usage([{"node": "pve1", "status": "online", **partial}])


@pytest.mark.parametrize("nodes", [
    [full("pve1"), {"node": "pve2", "status": "online"}],          # one may just have booted: tolerated
    [{"node": "pve1", "status": "offline"}, {"node": "pve2", "status": "offline"}],   # nothing to judge
    [],
    [{"node": "pve1", "status": "offline"}, full("pve2")],
])
def test_partial_missing_figures_or_nothing_online_is_not_refused(nodes):
    proxmox.check_node_usage(nodes)


# ---- a sync with such a token -----------------------------------------------------------------------------

def test_the_sync_fails_clearly_and_keeps_the_last_good_data(logged_in, synced, monkeypatch):
    before = picture(logged_in)
    assert [n["name"] for n in before["nodes"]] == list(HOSTS) and before["templates"] and before["vms"]
    stamp = logged_in.get("/api/proxmox").json()[0]["last_sync_at"]

    monkeypatch.setattr(factory, "transport", httpx.MockTransport(blind))
    r = logged_in.post(f"/api/proxmox/{synced}/sync", headers=H)
    assert r.status_code == 502 and "Sys.Audit" in r.json()["detail"] and "PVEAuditor" in r.json()["detail"]

    assert picture(logged_in) == before                            # nothing was deleted or blanked
    conn = logged_in.get("/api/proxmox").json()[0]
    assert "Sys.Audit" in conn["last_sync_error"] and conn["last_sync_at"] == stamp


def test_a_connection_added_with_such_a_token_never_stores_an_empty_picture(logged_in, monkeypatch):
    monkeypatch.setattr(factory, "transport", httpx.MockTransport(blind))
    conn_id = logged_in.post("/api/proxmox", json=GOOD, headers=H).json()["id"]
    assert logged_in.post(f"/api/proxmox/{conn_id}/sync", headers=H).status_code == 502
    assert picture(logged_in) == {"nodes": [], "storages": [], "templates": [], "vms": []}


def test_one_node_without_figures_still_syncs_and_is_stored_as_unknown(logged_in, monkeypatch):
    def partial(request):
        if request.url.path.endswith("/api2/json/nodes"):
            return httpx.Response(200, json={"data": [full("pve1"), {"node": "pve2", "status": "online"}]})
        return httpx.Response(200, json={"data": []})
    monkeypatch.setattr(factory, "transport", httpx.MockTransport(partial))
    conn_id = logged_in.post("/api/proxmox", json=GOOD, headers=H).json()["id"]
    assert logged_in.post(f"/api/proxmox/{conn_id}/sync", headers=H).status_code == 200
    nodes = {n["name"]: n["usage"] for n in picture(logged_in)["nodes"]}
    assert nodes["pve1"]["maxcpu"] == 8 and nodes["pve2"]["maxcpu"] is None


# ---- replacing a token with one that cannot audit ---------------------------------------------------------

def test_replacing_a_token_with_one_that_cannot_audit_is_refused_and_changes_nothing(
        logged_in, session, synced, monkeypatch):
    before_secret = session.scalar(select(Credential)).ciphertext
    before = picture(logged_in)
    monkeypatch.setattr(factory, "transport", httpx.MockTransport(blind))

    r = logged_in.put(f"/api/proxmox/{synced}/credential", json={"token_secret": "a-pool-scoped-secret-1"}, headers=H)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "accepted that token" in detail and "Sys.Audit" in detail and "Nothing was changed" in detail
    session.expire_all()
    assert session.scalar(select(Credential)).ciphertext == before_secret
    assert crypto.decrypt(before_secret) == GOOD["token_secret"]
    assert picture(logged_in) == before
    rejected = session.scalars(select(AuditEvent).where(AuditEvent.action == "proxmox.credential_rejected")).all()
    assert len(rejected) == 1 and "a-pool-scoped-secret-1" not in str(rejected[0].details)


# ---- placement says which problem it is -------------------------------------------------------------------

def test_placement_tells_an_offline_host_from_one_with_unknown_capacity():
    hosts = [HostView(name="pve1", online=False, cores=0, mem_total=0, mem_used=0),
             HostView(name="pve2", online=True, usage_known=False, cores=0, mem_total=0, mem_used=0)]
    result = recommend_placement(build_desired_state(TopologyPreset.single_node, "lab-b", "9.4.3"), hosts)
    message = result.issues[0].message
    assert "pve1: host is offline" in message
    assert "pve2: Proxmox reports no CPU or memory" in message and "Sys.Audit" in message
    assert "offline or reports" not in message                     # the old, conflated wording is gone
