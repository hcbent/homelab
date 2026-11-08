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
