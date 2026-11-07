"""Rules for changing a cluster that exists, with no Terraform, Ansible or Proxmox involved."""
from datetime import UTC, datetime

import pytest

from app.desired import TopologyPreset, build_desired_state
from app.models import Cluster, Credential, ProxmoxConnection, PveStorage
from app.provisioning.lifecycle import ExpandDisk, plan_expand_disk
from app.provisioning.operation import OperationRefused

GIB = 1024 ** 3


def desired(preset=TopologyPreset.dedicated_masters, **kw):
    state = build_desired_state(preset, "lab-x", "9.5.6", **kw)
    hosts = ["pve1", "pve2", "pve3"]
    return {"state": state.model_dump(mode="json"), "datastore_id": "tank",
            "placement": {n.name: hosts[i % 3] for i, n in enumerate(state.nodes)}}


@pytest.fixture
def built(session):
    """A managed, bootstrapped cluster: 3 masters (no data disk), 2 data nodes (100 GB) and 1 coordinating node."""
    c = Cluster(name="lab-x", ownership="managed", bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC),
                desired=desired(data_nodes=2, coordinating_nodes=1))
    session.add(c)
    session.commit()
    return c


def disks(params):
    return {n["name"]: n["data_disk_gb"] for n in params["state"]["nodes"]}


def test_every_node_with_a_data_disk_is_grown_and_the_rest_are_left_alone(session, built):
    new = plan_expand_disk(session, built, ExpandDisk(data_disk_gb=200))
    assert disks(new) == {"lab-x-01": None, "lab-x-02": None, "lab-x-03": None, "lab-x-04": 200,
                          "lab-x-05": 200, "lab-x-06": None}
    assert new["change"]["nodes"] == {"lab-x-04": {"from_gb": 100, "to_gb": 200},
                                      "lab-x-05": {"from_gb": 100, "to_gb": 200}}
    assert "grow the data disk of lab-x-04, lab-x-05 to 200 GB" in new["change"]["describe"]
    assert disks(built.desired)["lab-x-04"] == 100                       # the record itself is not touched


def test_one_named_node_can_be_grown_on_its_own(session, built):
    new = plan_expand_disk(session, built, ExpandDisk(data_disk_gb=150, nodes=["lab-x-05"]))
    assert disks(new)["lab-x-05"] == 150 and disks(new)["lab-x-04"] == 100


@pytest.mark.parametrize("size,message", [
    (50, "cannot be shrunk to 50 GB"),
    (100, "already 100 GB"),
])
def test_a_disk_is_only_ever_grown(session, built, size, message):
    with pytest.raises(OperationRefused, match=message):
        plan_expand_disk(session, built, ExpandDisk(data_disk_gb=size))


def test_a_node_without_a_data_disk_and_an_unknown_node_are_refused(session, built):
    with pytest.raises(OperationRefused, match="lab-x-01 has no data disk"):
        plan_expand_disk(session, built, ExpandDisk(data_disk_gb=200, nodes=["lab-x-01"]))
    with pytest.raises(OperationRefused, match="no node named nope"):
        plan_expand_disk(session, built, ExpandDisk(data_disk_gb=200, nodes=["nope"]))


def test_one_bad_node_refuses_the_whole_change(session, built):
    built.desired["state"]["nodes"][4]["data_disk_gb"] = 300             # lab-x-05 is already bigger
    with pytest.raises(OperationRefused, match="lab-x-05's data disk is 300 GB and cannot be shrunk"):
        plan_expand_disk(session, built, ExpandDisk(data_disk_gb=200))


def test_a_cluster_that_is_not_built_or_has_no_recorded_state_cannot_be_changed(session, built):
    built.desired = None
    with pytest.raises(OperationRefused, match="no record of this cluster's current state"):
        plan_expand_disk(session, built, ExpandDisk(data_disk_gb=200))
    other = Cluster(name="half", ownership="managed", desired=desired())
    session.add(other)
    session.commit()
    with pytest.raises(OperationRefused, match="not finished being built"):
        plan_expand_disk(session, other, ExpandDisk(data_disk_gb=200))


def test_the_request_itself_is_bounded():
    for bad in (9, 70000):
        with pytest.raises(ValueError):
            ExpandDisk(data_disk_gb=bad)
    with pytest.raises(ValueError):
        ExpandDisk(data_disk_gb=200, nodes=[])


def storage(session, host, avail_gib, shared=False, name="tank"):
    conn = session.query(ProxmoxConnection).first()
    if conn is None:
        credential = Credential(kind="proxmox_token", name="proxmox:lab", ciphertext=b"not a real secret")
        session.add(credential)
        session.flush()
        conn = ProxmoxConnection(name="lab", api_url="https://pve.test:8006", token_id="x@pve!y",
                                 credential_id=credential.id)
        session.add(conn)
        session.flush()
    session.add(PveStorage(connection_id=conn.id, node=host, name=name, shared=shared, avail=avail_gib * GIB))
    session.commit()


def test_a_host_without_room_on_the_datastore_refuses_the_growth(session, built):
    storage(session, "pve1", 500)
    storage(session, "pve2", 50)                                          # lab-x-05 is on pve2 and needs 100 GiB
    storage(session, "pve3", 500)
    with pytest.raises(OperationRefused, match="pve2 has 50 GiB free on tank and this needs 100 GiB there"):
        plan_expand_disk(session, built, ExpandDisk(data_disk_gb=200))


def test_growth_on_a_host_with_room_is_allowed_and_unseen_storage_is_not_counted_against_it(session, built):
    plan_expand_disk(session, built, ExpandDisk(data_disk_gb=200))        # nothing synced: no objection
    storage(session, "pve1", 500)
    storage(session, "pve2", 500)
    plan_expand_disk(session, built, ExpandDisk(data_disk_gb=200))


def test_shared_storage_is_counted_once_across_hosts(session, built):
    storage(session, "pve1", 150, shared=True)
    storage(session, "pve2", 150, shared=True)
    with pytest.raises(OperationRefused, match="shared datastore tank has 150 GiB free and this needs 200 GiB"):
        plan_expand_disk(session, built, ExpandDisk(data_disk_gb=200))
