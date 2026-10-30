import pytest
from sqlalchemy import select

from app.discovery import factory, sync
from app.models import AuditEvent, Cluster, Credential, EsNode
from tests.conftest import H
from tests.fixtures.transport import ES_KEY, FixtureTransport

KEY = ES_KEY.split(" ", 1)[1]
PVE = {"name": "lab", "api_url": "https://pve.test:8006", "token_id": "ro@pve!ecm",
       "token_secret": "fixture-pve-secret-value"}


@pytest.fixture
def fx(monkeypatch):
    t = FixtureTransport()
    monkeypatch.setattr(factory, "transport", t)
    return t


def add_proxmox(c):
    r = c.post("/api/proxmox", json=PVE, headers=H)
    assert r.status_code == 201, r.text
    assert "fixture-pve-secret-value" not in r.text          # secret never returned
    r2 = c.post(f"/api/proxmox/{r.json()['id']}/sync", headers=H)
    assert r2.status_code == 200, r2.text
    return r.json()["id"]


def register(c, host, **kw):
    return c.post("/api/clusters/register", headers=H,
                  json={"urls": [f"https://{host}:9200"], "api_key": KEY, **kw})


def test_infrastructure_discovery(logged_in, fx):
    add_proxmox(logged_in)
    inf = logged_in.get("/api/infrastructure").json()
    assert [n["name"] for n in inf["nodes"]] == ["pve1", "pve2", "pve3"]
    assert [t["vmid"] for t in inf["templates"]] == [8000]
    assert {s["name"] for s in inf["storages"]} == {"tank", "local"}
    assert any(v["vmid"] == 301 and v["pve_node"] == "pve1" for v in inf["vms"])
    assert "cipassword" not in str(inf)
    assert fx.methods == {"GET"}


def test_dashboard_and_link_states(logged_in, fx):
    add_proxmox(logged_in)
    assert register(logged_in, "fxa.test").status_code == 201
    assert register(logged_in, "fxb.test").status_code == 201
    assert register(logged_in, "fxc.test").status_code == 201
    rows = {c["name"]: c for c in logged_in.get("/api/clusters").json()}
    a = rows["fixture-a"]
    assert (a["version"], a["health"], a["nodes"], a["data_nodes"], a["ownership"]) == \
           ("9.5.6", "green", 9, 6, "discovered")
    assert a["uuid"] == "aaaaaaaaaaaaaaaaaaaaaa" and a["last_sync_at"]
    assert a["infrastructure"]["proxmox_hosts"] == ["pve1", "pve2", "pve3"]
    assert a["infrastructure"]["verified_links"] == 8            # fxa-07 is only name-matched
    assert a["storage"]["used_pct"] == 40.0 and a["jvm_heap_used_pct"]
    assert rows["fixture-b"]["health"] == "yellow" and rows["fixture-c"]["health"] == "red"
    assert rows["fixture-b"]["infrastructure"]["verified_links"] == 1   # via cloud-init static IP
    assert rows["fixture-c"]["infrastructure"]["verified_links"] == 0   # ambiguous address

    detail = logged_in.get(f"/api/clusters/{a['id']}").json()
    links = {n["name"]: n["link"] for n in detail["node_list"]}
    assert links["fxa-01"]["confidence"] == "verified"
    assert links["fxa-01"]["vm"]["vmid"] == 301
    assert links["fxa-07"]["confidence"] == "probable"
    assert links["fxa-07"]["vm"]["vmid"] == 307
    c_detail = logged_in.get(f"/api/clusters/{rows['fixture-c']['id']}").json()
    assert c_detail["node_list"][0]["link"]["evidence"]["reason"] == "ambiguous"
    assert c_detail["node_list"][0]["link"]["vm"] is None
    # three sources of truth are kept apart
    assert {"elasticsearch", "proxmox", "desired"} <= detail.keys()
    assert detail["desired"]["managed"] is False and detail["desired"]["note"]
    assert detail["elasticsearch"]["settings"]["persistent"] == {
        "cluster.routing.allocation.enable": "all"}
    assert fx.methods == {"GET"}                                    # read-only, always


def test_proxmox_sync_after_cluster_registration_links_nodes(logged_in, fx):
    assert register(logged_in, "fxa.test").status_code == 201
    row = logged_in.get("/api/clusters").json()[0]
    assert row["infrastructure"]["verified_links"] == 0
    add_proxmox(logged_in)
    assert logged_in.get("/api/clusters").json()[0]["infrastructure"]["verified_links"] == 8


def test_duplicate_registration_and_credentials_are_safe(logged_in, fx, session):
    assert register(logged_in, "fxa.test").status_code == 201
    assert register(logged_in, "fxa.test").status_code == 409
    assert session.scalar(select(AuditEvent).where(AuditEvent.action == "cluster.register"))
    stored = session.scalars(select(Credential)).all()
    assert all(KEY.encode() not in c.ciphertext for c in stored)


def test_unreachable_or_unauthorised_registration_is_rejected(logged_in, fx, session):
    r = logged_in.post("/api/clusters/register", headers=H,
                       json={"urls": ["https://fxa.test:9200"], "api_key": "wrongwrongwrong"})
    assert r.status_code == 502
    assert session.scalars(select(Cluster)).all() == []
    assert session.scalars(select(Credential)).all() == []   # nothing orphaned


def test_failed_sync_keeps_last_successful_time(logged_in, fx, session, monkeypatch):
    register(logged_in, "fxa.test")
    cid = logged_in.get("/api/clusters").json()[0]["id"]
    before = logged_in.get("/api/clusters").json()[0]["last_sync_at"]
    cluster = session.get(Cluster, cid)
    cluster.endpoint_urls = ["https://nowhere.test:9200"]     # 404 from the fixture server
    session.commit()
    assert logged_in.post(f"/api/clusters/{cid}/sync", headers=H).status_code == 502
    row = logged_in.get("/api/clusters").json()[0]
    assert row["last_sync_error"] and row["last_sync_at"] == before


def test_identity_mismatch_never_overwrites(logged_in, fx, session):
    register(logged_in, "fxa.test")
    cid = logged_in.get("/api/clusters").json()[0]["id"]
    cluster = session.get(Cluster, cid)
    cluster.endpoint_urls = ["https://fxb.test:9200"]        # a DIFFERENT cluster answers now
    session.commit()
    assert logged_in.post(f"/api/clusters/{cid}/sync", headers=H).status_code == 502
    row = logged_in.get("/api/clusters").json()[0]
    assert row["uuid"] == "aaaaaaaaaaaaaaaaaaaaaa" and row["name"] == "fixture-a"
    assert "expected" in row["last_sync_error"]
    assert session.scalar(select(EsNode).where(EsNode.name == "fxb-01")) is None


def test_sync_everything_isolates_failures(logged_in, fx, session):
    add_proxmox(logged_in)
    register(logged_in, "fxa.test")
    register(logged_in, "fxb.test")
    bad = session.scalars(select(Cluster).where(Cluster.name == "fixture-a")).one()
    bad.endpoint_urls = ["https://nowhere.test:9200"]
    session.commit()
    errors = sync.sync_everything(session)
    assert list(errors) == ["cluster:fixture-a"]
    assert session.scalars(select(Cluster).where(Cluster.name == "fixture-b")).one().last_sync_error is None


def test_discovery_endpoints_require_login(client):
    for path in ("/api/clusters", "/api/infrastructure", "/api/proxmox"):
        assert client.get(path).status_code == 401
