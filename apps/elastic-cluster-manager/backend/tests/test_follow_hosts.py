"""The recorded host of each node follows where Proxmox says its machine is (the operator's decision, 2026-11-08), through a real sync
against the fixture Proxmox, and on its own for the cases a sync would not set up."""
# ruff: noqa: F811  (the cluster fixture is imported from the operation tests and used by name)
from sqlalchemy import select

from app.discovery import sync
from app.models import AuditEvent, Cluster, Vm
from app.provisioning.reality import follow_hosts
from tests.test_tf_operations import cluster, fixture_proxmox  # noqa: F401  (a fixture and a helper)


def test_a_sync_records_where_proxmox_has_the_machine_and_leaves_an_audit_event(logged_in, session, cluster, monkeypatch):
    pve = fixture_proxmox(logged_in, session, monkeypatch)
    cluster.desired = {"proxmox_connection_id": pve.id, "vm_ids": {"fxa-01": 301}, "placement": {"fxa-01": "pve-where-it-was-made"},
                       "state": {"keep": "me"}}
    session.commit()
    sync.sync_proxmox(session, pve)
    session.refresh(cluster)
    actual = session.scalar(select(Vm).where(Vm.vmid == 301)).pve_node
    assert actual and actual != "pve-where-it-was-made"
    assert cluster.desired["placement"] == {"fxa-01": actual} and cluster.desired["state"] == {"keep": "me"}   # nothing else touched
    event = session.scalar(select(AuditEvent).where(AuditEvent.action == "cluster.host_followed"))
    assert event.target_id == cluster.id and event.details == {"node": "fxa-01", "was": "pve-where-it-was-made", "now": actual}

    sync.sync_proxmox(session, pve)                                              # nothing has moved since: no second event
    assert len(session.scalars(select(AuditEvent).where(AuditEvent.action == "cluster.host_followed")).all()) == 1


def test_only_a_machine_with_the_same_vmid_and_name_is_followed(logged_in, session, cluster, monkeypatch):
    pve = fixture_proxmox(logged_in, session, monkeypatch)
    cluster.desired = {"proxmox_connection_id": pve.id, "vm_ids": {"someone-else": 301, "lab-no-row": 999999},
                       "placement": {"someone-else": "pve-x", "lab-no-row": "pve-y"}}
    session.commit()
    sync.sync_proxmox(session, pve)                                              # 301 is named fxa-01, and 999999 does not exist
    session.refresh(cluster)
    assert cluster.desired["placement"] == {"someone-else": "pve-x", "lab-no-row": "pve-y"}


def test_other_connections_unmanaged_and_unbuilt_clusters_are_left_alone(logged_in, session, cluster, monkeypatch):
    pve = fixture_proxmox(logged_in, session, monkeypatch)
    sync.sync_proxmox(session, pve)
    actual = session.scalar(select(Vm).where(Vm.vmid == 301)).pve_node
    desired = {"proxmox_connection_id": "another-connection", "vm_ids": {"fxa-01": 301}, "placement": {"fxa-01": "old"}}
    cluster.desired = desired
    other = Cluster(name="lab-unmanaged", ownership="discovered",
                    desired={**desired, "proxmox_connection_id": pve.id})
    unbuilt = Cluster(name="lab-unbuilt", ownership="managed", desired=None)
    session.add_all([other, unbuilt])
    session.commit()
    assert follow_hosts(session, pve.id) == []
    session.refresh(cluster)
    session.refresh(other)
    assert cluster.desired["placement"] == {"fxa-01": "old"} and other.desired["placement"] == {"fxa-01": "old"}
    assert actual != "old"                                                        # it would have changed if they had been followed


# -- Sync now on a cluster ECM built also reads Proxmox --------------------------------------------------------------------------------

H = {"x-ecm-csrf": "1"}


def spy_syncs(monkeypatch, fail_proxmox=False):
    """Replace the two syncs with recorders, so the order and who was called are visible."""
    from app.discovery import sync as sync_module
    from app.discovery.http import DiscoveryError
    calls: list[str] = []
    real_proxmox = sync_module.sync_proxmox

    def proxmox(db, conn, client=None):
        calls.append("proxmox")
        if fail_proxmox:
            raise DiscoveryError("connection refused")
        return real_proxmox(db, conn, client)
    monkeypatch.setattr(sync_module, "sync_proxmox", proxmox)
    monkeypatch.setattr(sync_module, "sync_cluster", lambda db, c, client=None: calls.append("cluster"))
    return calls


def test_sync_now_reads_proxmox_first_so_the_recorded_host_and_the_machine_states_are_fresh(logged_in, session, cluster, monkeypatch):
    pve = fixture_proxmox(logged_in, session, monkeypatch)
    cluster.desired = {"proxmox_connection_id": pve.id, "vm_ids": {"fxa-01": 301}, "placement": {"fxa-01": "stale-host"}}
    session.commit()
    calls = spy_syncs(monkeypatch)
    r = logged_in.post(f"/api/clusters/{cluster.id}/sync", headers=H)
    assert r.status_code == 200 and r.json()["proxmox_error"] is None
    assert calls == ["proxmox", "cluster"]                                         # Proxmox first, so the links are made from fresh data
    session.refresh(cluster)
    assert cluster.desired["placement"]["fxa-01"] != "stale-host"
    shown = logged_in.get(f"/api/clusters/{cluster.id}").json()["lifecycle"]
    assert shown["proxmox_synced_at"] is not None                                  # the page can say how old the Proxmox reading is


def test_a_proxmox_failure_is_reported_and_does_not_fail_the_sync(logged_in, session, cluster, monkeypatch):
    pve = fixture_proxmox(logged_in, session, monkeypatch)
    cluster.desired = {"proxmox_connection_id": pve.id, "vm_ids": {}, "placement": {}}
    session.commit()
    calls = spy_syncs(monkeypatch, fail_proxmox=True)
    r = logged_in.post(f"/api/clusters/{cluster.id}/sync", headers=H)
    assert r.status_code == 200 and calls == ["proxmox", "cluster"]
    assert "Proxmox could not be read (connection refused)" in r.json()["proxmox_error"]


def test_a_cluster_ecm_did_not_build_is_synced_from_elasticsearch_only(logged_in, session, monkeypatch):
    pve = fixture_proxmox(logged_in, session, monkeypatch)
    other = Cluster(name="lab-found", ownership="discovered", desired={"proxmox_connection_id": pve.id})
    session.add(other)
    session.commit()
    calls = spy_syncs(monkeypatch)
    assert logged_in.post(f"/api/clusters/{other.id}/sync", headers=H).json()["proxmox_error"] is None
    assert calls == ["cluster"]


# -- the sync forgets a pending restart once the node has restarted ---------------------------------------------------------------------

def test_a_sync_drops_a_pending_restart_for_a_node_that_has_restarted_since_and_keeps_the_rest(session, cluster):
    from datetime import UTC, datetime, timedelta

    from app.discovery import es as es_module
    written = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    cluster.pending_restart = {"n-restarted": written, "n-old": written, "n-down": written, "n-no-uptime": written}
    session.commit()

    def node(name, uptime_ms):
        return es_module.NodeInfo(es_node_id=name, name=name, ip="192.0.2.1", host=name, version="9.4.9", roles=[], attributes={},
                                  uptime_ms=uptime_ms)
    snap = es_module.ClusterSnapshot(cluster_uuid="u", cluster_name="c", version="9.4.9", status="green", detail={}, nodes=[
        node("n-restarted", 5 * 60 * 1000),                  # up for five minutes: it restarted after the change was written
        node("n-old", 3 * 24 * 3600 * 1000),                 # up for three days: it has not
        node("n-no-uptime", None)])                          # cannot tell; n-down is not in the cluster at all
    sync.apply_snapshot(session, cluster, snap)
    session.refresh(cluster)
    assert sorted(cluster.pending_restart) == ["n-down", "n-no-uptime", "n-old"]
    snap.nodes = [node("n-old", 5 * 60 * 1000), node("n-down", 5 * 60 * 1000), node("n-no-uptime", 5 * 60 * 1000)]
    sync.apply_snapshot(session, cluster, snap)
    session.refresh(cluster)
    assert cluster.pending_restart is None                   # nothing is waiting: stored as nothing, not as an empty map
