from sqlalchemy import select

from app.desired.network import allocate_addresses
from app.models import AuditEvent, Cluster, EsNode, NetworkProfileRow, Vm
from app.network_profiles import ensure_default, to_domain
from tests.conftest import H

URL = "/api/network-profiles"
GOOD = {"name": "lab", "bridge": "vmbr0", "vlan": 10, "cidr": "192.0.2.0/24", "gateway": "192.0.2.1",
        "dns": ["192.0.2.1"], "search_domain": "lab.example.org",
        "range_start": "192.0.2.50", "range_end": "192.0.2.60"}


def default(c) -> dict:
    return next(p for p in c.get(URL).json() if p["name"] == "default")


def test_endpoints_require_login_and_the_csrf_header(client, logged_in):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as anon:
        assert anon.get(URL, headers=H).status_code == 401
        assert anon.put(f"{URL}/x", json=GOOD, headers=H).status_code == 401
    # reads need no header, but every change does
    assert logged_in.get(URL, headers={}).status_code == 200
    p = default(logged_in)
    assert logged_in.put(f"{URL}/{p['id']}", json=GOOD, headers={}).status_code == 403
    assert logged_in.post(URL, json=GOOD, headers={}).status_code == 403


def test_the_default_profile_is_seeded_with_the_agreed_range(logged_in):
    p = default(logged_in)
    # the agreed static range stops one short of the DHCP range, which starts at .150
    assert (p["range_start"], p["range_end"]) == ("192.168.10.110", "192.168.10.149")
    assert (p["dhcp_start"], p["dhcp_end"]) == ("192.168.10.150", "192.168.10.254")
    assert p["cidr"] == "192.168.10.0/24" and p["gateway"] == "192.168.10.1" and p["vlan"] == 10
    assert p["pool_size"] == 40 and p["in_use_in_range"] == []


def test_seeding_is_idempotent_and_never_overwrites_an_edit(logged_in, session):
    p = default(logged_in)
    body = {k: p[k] for k in GOOD} | {"name": "default", "range_start": "192.168.10.120",
                                       "range_end": "192.168.10.130"}
    assert logged_in.put(f"{URL}/{p['id']}", json=body, headers=H).status_code == 200
    ensure_default(session)                                  # what every start does
    ensure_default(session)
    rows = session.scalars(select(NetworkProfileRow)).all()
    assert len(rows) == 1 and rows[0].range_start == "192.168.10.120"


def test_updating_the_range_persists_and_is_audited(logged_in, session):
    p = default(logged_in)
    body = {"name": "default", "bridge": "vmbr0", "vlan": 10, "cidr": "192.168.10.0/24",
            "gateway": "192.168.10.1", "dns": ["192.168.10.1"], "search_domain": "lab.thewortmans.org",
            "range_start": "192.168.10.200", "range_end": "192.168.10.219"}
    r = logged_in.put(f"{URL}/{p['id']}", json=body, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["range_start"] == "192.168.10.200" and r.json()["pool_size"] == 20
    assert default(logged_in)["range_end"] == "192.168.10.219"       # survives a re-read
    ev = session.scalars(select(AuditEvent).where(AuditEvent.action == "network_profile.update")).one()
    assert ev.actor == "admin"
    assert ev.details["range_before"] == "192.168.10.110-192.168.10.149"
    assert ev.details["range_after"] == "192.168.10.200-192.168.10.219"


def test_the_stored_profile_drives_allocation(logged_in, session):
    from app.desired import NodeSpec
    p = default(logged_in)
    body = {k: p[k] for k in GOOD} | {"name": "default"} | {
        "cidr": p["cidr"], "gateway": p["gateway"], "dns": p["dns"], "search_domain": p["search_domain"]}
    body["range_start"], body["range_end"] = "192.168.10.140", "192.168.10.142"
    logged_in.put(f"{URL}/{p['id']}", json=body, headers=H)
    row = session.scalars(select(NetworkProfileRow)).one()
    nodes = [NodeSpec(name=f"lab-b-0{i}", data_disk_gb=50) for i in (1, 2, 3)]
    got = allocate_addresses(to_domain(row), nodes)
    assert list(got.values()) == ["192.168.10.140", "192.168.10.141", "192.168.10.142"]


def test_invalid_ranges_are_rejected_with_a_readable_message(logged_in):
    p = default(logged_in)
    base = {"name": "default", "bridge": "vmbr0", "vlan": 10, "cidr": "192.168.10.0/24",
            "gateway": "192.168.10.1", "dns": ["192.168.10.1"], "search_domain": None}
    cases = [
        ({"range_start": "192.168.10.150", "range_end": "192.168.10.110"}, "not be after"),
        ({"range_start": "10.0.0.5", "range_end": "10.0.0.9"}, "inside 192.168.10.0/24"),
        ({"range_start": "192.168.10.1", "range_end": "192.168.10.20"}, "must not include the gateway"),
        ({"range_start": "192.168.10.110", "range_end": "192.168.10.300"}, "IPv4"),
    ]
    for change, msg in cases:
        r = logged_in.put(f"{URL}/{p['id']}", json={**base, **change}, headers=H)
        assert r.status_code == 422, change
        assert msg in r.text, (change, r.text)
    assert default(logged_in)["range_start"] == "192.168.10.110"     # nothing was changed


def test_an_update_that_overlaps_the_dhcp_range_is_rejected(logged_in):
    p = default(logged_in)
    body = {k: p[k] for k in ("name", "bridge", "vlan", "cidr", "gateway", "dns", "search_domain",
                              "dhcp_start", "dhcp_end")}
    r = logged_in.put(f"{URL}/{p['id']}", json={**body, "range_start": "192.168.10.110",
                                                "range_end": "192.168.10.150"}, headers=H)
    assert r.status_code == 422 and "overlaps the DHCP range" in r.text
    assert default(logged_in)["range_end"] == "192.168.10.149"       # unchanged
    # clearing the DHCP range is allowed, which removes the check
    ok = logged_in.put(f"{URL}/{p['id']}", json={**body, "dhcp_start": None, "dhcp_end": None,
                                                  "range_start": "192.168.10.110",
                                                  "range_end": "192.168.10.150"}, headers=H)
    assert ok.status_code == 200 and ok.json()["dhcp_start"] is None


def test_unknown_profile_and_extra_fields(logged_in):
    assert logged_in.put(f"{URL}/nope", json=GOOD, headers=H).status_code == 404
    p = default(logged_in)
    assert logged_in.put(f"{URL}/{p['id']}", json={**GOOD, "pool_size": 3}, headers=H).status_code == 422


def test_create_and_duplicate_names(logged_in, session):
    r = logged_in.post(URL, json=GOOD, headers=H)
    assert r.status_code == 201, r.text
    assert logged_in.post(URL, json=GOOD, headers=H).status_code == 409
    other = default(logged_in)
    assert logged_in.put(f"{URL}/{other['id']}", json=GOOD, headers=H).status_code == 409  # name taken
    ev = session.scalars(select(AuditEvent).where(AuditEvent.action == "network_profile.create")).one()
    assert ev.details["range"] == "192.0.2.50-192.0.2.60"


def test_addresses_already_in_use_inside_the_range_are_reported(logged_in, session):
    cluster = Cluster(name="lab")
    session.add(cluster)
    session.flush()
    session.add_all([
        Vm(connection_id="c", pve_node="pve1", vmid=101, name="plex", status="running",
           ips=[{"ip": "192.168.10.120", "source": "guest-agent"}]),
        Vm(connection_id="c", pve_node="pve1", vmid=8000, name="tmpl", is_template=True,
           ips=[{"ip": "192.168.10.125", "source": "cloud-init"}]),          # templates are ignored
        Vm(connection_id="c", pve_node="pve2", vmid=102, name="elsewhere", status="running",
           ips=[{"ip": "192.168.10.60", "source": "guest-agent"}]),          # outside the range
        EsNode(cluster_id=cluster.id, es_node_id="n1", name="lab-01", ip="192.168.10.111"),
        EsNode(cluster_id=cluster.id, es_node_id="n2", name="lab-02", ip="192.168.10.120"),  # same as plex
    ])
    session.commit()
    hits = default(logged_in)["in_use_in_range"]
    assert [h["ip"] for h in hits] == ["192.168.10.111", "192.168.10.120"]
    assert hits[0] == {"ip": "192.168.10.111", "source": "elasticsearch", "name": "lab-01"}
    assert hits[1]["ip"] == "192.168.10.120" and hits[1]["source"] == "proxmox"   # Proxmox is seen first
