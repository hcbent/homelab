"""Rules for changing a cluster that exists, with no Terraform, Ansible or Proxmox involved."""
from datetime import UTC, datetime

import pytest

from app.desired import TopologyPreset, build_desired_state
from app.models import Cluster, Credential, ProxmoxConnection, PveNode, PveStorage
from app.provisioning.lifecycle import ExpandDisk, ResizeNodes, plan_expand_disk, plan_resize
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


# ---- resizing CPU and RAM ---------------------------------------------------------------------------------------

def sizes(params):
    return {n["name"]: (n["cores"], n["ram_mb"]) for n in params["state"]["nodes"]}


def test_every_node_is_resized_and_the_description_says_how_they_are_restarted(session, built):
    new = plan_resize(session, built, ResizeNodes(cores=8, ram_mb=16384))
    assert set(sizes(new).values()) == {(8, 16384)}
    assert set(new["change"]["nodes"]) == {f"lab-x-0{i}" for i in range(1, 7)}
    assert new["change"]["kind"] == "resize"
    assert "8 cores and 16384 MiB of RAM" in new["change"]["describe"]
    assert "then ECM restarts the nodes one at a time" in new["change"]["describe"]
    assert "the elected master last" in new["change"]["describe"]
    assert sizes(built.desired)["lab-x-01"] == (2, 4096)                   # the record is not touched


def test_only_the_asked_for_field_changes_and_only_the_chosen_nodes(session, built):
    new = plan_resize(session, built, ResizeNodes(cores=6, nodes=["lab-x-04"]))
    assert sizes(new)["lab-x-04"] == (6, 8192) and sizes(new)["lab-x-05"] == (4, 8192)
    assert new["change"]["nodes"] == {"lab-x-04": {"cores": {"from": 4, "to": 6}}}


def test_a_node_already_at_the_size_and_an_unknown_node_are_refused(session, built):
    with pytest.raises(OperationRefused, match="lab-x-04 already has 4 cores and 8192 MiB"):
        plan_resize(session, built, ResizeNodes(cores=4, nodes=["lab-x-04"]))
    with pytest.raises(OperationRefused, match="no node named nope"):
        plan_resize(session, built, ResizeNodes(cores=8, nodes=["nope"]))


def test_smaller_sizes_are_allowed(session, built):
    new = plan_resize(session, built, ResizeNodes(ram_mb=4096, nodes=["lab-x-04"]))
    assert sizes(new)["lab-x-04"] == (4, 4096)


def test_a_pinned_heap_that_would_be_more_than_half_the_new_ram_is_refused_with_the_reason(session, built):
    built.desired["state"]["nodes"][3]["heap_mb"] = 4096                   # lab-x-04 pinned at 4 GiB
    with pytest.raises(OperationRefused, match="lab-x-04's heap is pinned at 4096 MiB.*half of 4096 MiB"):
        plan_resize(session, built, ResizeNodes(ram_mb=4096, nodes=["lab-x-04"]))
    plan_resize(session, built, ResizeNodes(ram_mb=12288, nodes=["lab-x-04"]))    # half of 12 GiB covers 4 GiB


def test_a_single_node_cluster_is_not_resized(session):
    single = Cluster(name="solo", ownership="managed", bootstrapped_at=datetime(2026, 11, 6, tzinfo=UTC),
                     desired=desired(TopologyPreset.single_node))
    session.add(single)
    session.commit()
    with pytest.raises(OperationRefused, match="single-node cluster.*down while its machine restarts"):
        plan_resize(session, single, ResizeNodes(cores=8))


def test_the_request_needs_something_to_change_and_is_bounded():
    with pytest.raises(ValueError, match="cores, an amount of RAM, or both"):
        ResizeNodes()
    for bad in ({"cores": 0}, {"cores": 65}, {"ram_mb": 1024}, {"ram_mb": 600000}, {"cores": 4, "nodes": []}):
        with pytest.raises(ValueError):
            ResizeNodes(**bad)


def host(session, name, free_mb, total_mb=65536):
    conn = session.query(ProxmoxConnection).first()
    if conn is None:
        credential = Credential(kind="proxmox_token", name="proxmox:lab", ciphertext=b"not a real secret")
        session.add(credential)
        session.flush()
        conn = ProxmoxConnection(name="lab", api_url="https://pve.test:8006", token_id="x@pve!y",
                                 credential_id=credential.id)
        session.add(conn)
        session.flush()
    session.add(PveNode(connection_id=conn.id, name=name,
                        usage={"maxmem": total_mb * 1024 ** 2, "mem": (total_mb - free_mb) * 1024 ** 2}))
    session.commit()


def test_a_host_without_the_memory_for_an_increase_refuses_it(session, built):
    host(session, "pve1", 60000)
    host(session, "pve2", 3000)                                           # lab-x-05 is on pve2 and needs 8192 MiB more
    host(session, "pve3", 60000)
    with pytest.raises(OperationRefused, match="pve2 has 3000 MiB of memory free and this needs 8192 MiB more there"):
        plan_resize(session, built, ResizeNodes(ram_mb=16384, nodes=["lab-x-04", "lab-x-05"]))


def test_a_decrease_needs_no_room_and_unseen_hosts_are_not_counted_against_the_change(session, built):
    plan_resize(session, built, ResizeNodes(ram_mb=16384, nodes=["lab-x-04"]))     # nothing synced: no objection
    host(session, "pve1", 10)                                              # a full host...
    plan_resize(session, built, ResizeNodes(ram_mb=4096, nodes=["lab-x-04"]))      # ...does not matter for a decrease
