"""Planning a new cluster: from a request to an operation, using the discovery data ECM already holds."""
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app import config, crypto
from app.desired import CatalogError, StaticCatalog, TopologyPreset
from app.discovery import factory
from app.models import (
    AuditEvent,
    Cluster,
    Credential,
    EsNode,
    Operation,
    OperationStep,
    ProxmoxConnection,
    PveNode,
    PveStorage,
    Vm,
)
from app.network_profiles import ensure_default
from app.provisioning.create import (
    CreateConflict,
    CreateInvalid,
    CreateRequest,
    NodeOverride,
    create_cluster_operation,
)

GIB = 1024**3
H = {"x-ecm-csrf": "1"}


@pytest.fixture
def pve(session):
    """Three online hosts, shared storage 'tank', a template 8000 on pve1 and the default network profile."""
    ensure_default(session)
    cred = Credential(kind="proxmox", name="pve", ciphertext=crypto.encrypt("secret-value-123"))
    session.add(cred)
    session.flush()
    conn = ProxmoxConnection(name="pve", api_url="https://pve2.lab.example.org:8006", token_id="ecm@pve!tf",
                             credential_id=cred.id, last_sync_at=datetime.now(UTC))
    session.add(conn)
    session.flush()
    for host in ("pve1", "pve2", "pve3"):
        session.add(PveNode(connection_id=conn.id, name=host, status="online",
                            usage={"maxcpu": 40, "maxmem": 187 * GIB, "mem": 10 * GIB, "cpu": 0.1}))
        session.add(PveStorage(connection_id=conn.id, node=host, name="tank", type="nfs", shared=True,
                               active=True, total=16000 * GIB, used=100 * GIB, avail=15900 * GIB))
    session.add(Vm(connection_id=conn.id, pve_node="pve1", vmid=8000, name="ubuntu-25.04", status="stopped",
                   is_template=True, disks=[{"slot": "scsi0", "storage": "tank", "size_gb": 32}]))
    session.commit()
    return conn


def request(**kw) -> CreateRequest:
    base = {"name": "lab-b", "version": "9.4.3", "preset": TopologyPreset.three_node, "template_vmid": 8000}
    return CreateRequest(**{**base, **kw})


def plan(session, **kw):
    return create_cluster_operation(session, request(**kw), "admin")


def finish(session, op, state, **kw):
    op.state = state
    for k, v in kw.items():
        setattr(op, k, v)
    session.commit()


# ---- the happy path -------------------------------------------------------------------------------------

def test_a_request_is_a_dry_run_unless_it_says_otherwise():
    assert request().dry_run is True


def test_it_plans_a_three_node_cluster_spread_over_the_hosts(session, pve):
    cluster, op, resolved = plan(session)
    assert cluster.ownership == "managed" and cluster.name == "lab-b"
    assert op.kind == "tf.create" and op.dry_run and op.cluster_id == cluster.id
    assert sorted(resolved.placement.values()) == ["pve1", "pve2", "pve3"]
    assert resolved.addresses == {"lab-b-01": "192.168.10.110", "lab-b-02": "192.168.10.111",
                                  "lab-b-03": "192.168.10.112"}
    assert resolved.vm_ids == {"lab-b-01": 500, "lab-b-02": 501, "lab-b-03": 502}
    assert op.params["template"] == {"node_name": "pve1", "vm_id": 8000}
    assert op.params["proxmox_connection_id"] == pve.id and op.params["state"]["network_profile"] == "default"
    steps = [s.name for s in session.scalars(select(OperationStep).where(OperationStep.operation_id == op.id)
                                             .order_by(OperationStep.seq))]
    assert steps == ["render", "init", "plan"]                    # a dry run has nothing to approve or apply


def test_a_real_create_has_the_approval_and_apply_steps(session, pve):
    _, op, _ = plan(session, dry_run=False)
    assert not op.dry_run
    steps = [s.name for s in session.scalars(select(OperationStep).where(OperationStep.operation_id == op.id)
                                             .order_by(OperationStep.seq))]
    assert steps == ["render", "init", "plan", "approval", "apply"]


def test_the_default_template_comes_from_settings(session, pve, monkeypatch):
    monkeypatch.setenv("ECM_DEFAULT_TEMPLATE_NAME", "ubuntu-25.04")
    config.get_settings.cache_clear()
    _, op, _ = plan(session, template_vmid=None)
    assert op.params["template"]["vm_id"] == 8000
    monkeypatch.setenv("ECM_DEFAULT_TEMPLATE_VMID", "8000")
    config.get_settings.cache_clear()
    assert plan(session, name="lab-c", template_vmid=None)[1].params["template"]["vm_id"] == 8000


def test_a_stale_proxmox_sync_is_a_warning_not_a_refusal(session, pve):
    pve.last_sync_at = datetime.now(UTC) - timedelta(hours=3)
    session.commit()
    assert any("not been synced" in w for w in plan(session)[2].warnings)


# ---- what is already taken ------------------------------------------------------------------------------

def test_addresses_and_vmids_already_in_use_are_skipped(session, pve):
    other = Cluster(name="old", ownership="discovered")
    session.add(other)
    session.flush()
    session.add(Vm(connection_id=pve.id, pve_node="pve2", vmid=500, name="stopped-thing", status="stopped",
                   ips=[{"ip": "192.168.10.110", "source": "guest-agent"}]))
    session.add(EsNode(cluster_id=other.id, es_node_id="n1", name="old-1", ip="192.168.10.111"))
    session.commit()
    resolved = plan(session)[2]
    assert list(resolved.addresses.values()) == ["192.168.10.112", "192.168.10.113", "192.168.10.114"]
    assert list(resolved.vm_ids.values()) == [501, 502, 503]


def test_two_clusters_planned_back_to_back_never_share_an_address_or_vmid(session, pve):
    first = plan(session, name="lab-a", dry_run=False)[2]
    second = plan(session, name="lab-b", dry_run=False)[2]
    assert not set(first.addresses.values()) & set(second.addresses.values())
    assert not set(first.vm_ids.values()) & set(second.vm_ids.values())


def test_a_dry_run_reserves_nothing(session, pve):
    first = plan(session, name="lab-a")[2]                         # dry run, still "running" here
    second = plan(session, name="lab-b")[2]
    assert list(first.addresses.values()) == list(second.addresses.values())
    assert list(first.vm_ids.values()) == list(second.vm_ids.values())


def test_a_failed_create_keeps_its_addresses_until_it_is_cleaned_up(session, pve):
    cluster, op, first = plan(session, name="lab-a", dry_run=False)
    finish(session, op, "failed", result={"resources_in_state": ["vm.a"]})
    assert not set(plan(session, name="lab-b", dry_run=False)[2].addresses.values()) & set(first.addresses.values())

    session.add(Operation(kind="tf.destroy", cluster_id=cluster.id, parent_op_id=op.id, state="succeeded"))
    session.commit()
    freed = plan(session, name="lab-c", dry_run=False)[2]            # lab-b's reservation is still active
    assert set(freed.addresses.values()) & set(first.addresses.values())


def test_a_failed_create_that_applied_nothing_holds_nothing(session, pve):
    _, op, first = plan(session, name="lab-a", dry_run=False)
    finish(session, op, "failed")                                    # no result: nothing was applied
    assert list(plan(session, name="lab-b", dry_run=False)[2].addresses.values()) == list(first.addresses.values())


def test_a_recent_success_holds_its_addresses_until_discovery_could_have_seen_them(session, pve):
    _, op, first = plan(session, name="lab-a", dry_run=False)
    finish(session, op, "succeeded", finished_at=datetime.now(UTC))
    assert not set(plan(session, name="lab-b")[2].addresses.values()) & set(first.addresses.values())
    op.finished_at = datetime.now(UTC) - timedelta(hours=2)
    session.commit()
    assert list(plan(session, name="lab-c")[2].addresses.values()) == list(first.addresses.values())


# ---- names, overrides, version-independent validation --------------------------------------------------

def test_a_node_name_that_matches_an_existing_vm_is_refused(session, pve):
    session.add(Vm(connection_id=pve.id, pve_node="pve1", vmid=300, name="lab-b-02", status="running"))
    session.commit()
    with pytest.raises(CreateInvalid, match="lab-b-02"):
        plan(session)
    assert session.scalar(select(Cluster)) is None


def test_a_cluster_name_that_already_exists_is_refused(session, pve):
    session.add(Cluster(name="lab-b", ownership="discovered"))
    session.commit()
    with pytest.raises(CreateConflict, match="already exists"):
        plan(session)


def test_overrides_change_only_what_they_name(session, pve):
    resolved = plan(session, node_overrides={
        "lab-b-01": NodeOverride(ram_mb=16384, pve_node="pve3"),
        "lab-b-02": NodeOverride(ip="192.168.10.120")})[2]
    nodes = {n.name: n for n in resolved.state.nodes}
    assert nodes["lab-b-01"].ram_mb == 16384 and nodes["lab-b-02"].ram_mb == 8192
    assert resolved.placement["lab-b-01"] == "pve3"
    assert resolved.addresses["lab-b-02"] == "192.168.10.120" and resolved.addresses["lab-b-01"] == "192.168.10.110"


def test_an_override_for_a_node_that_does_not_exist_is_refused(session, pve):
    with pytest.raises(CreateInvalid, match="lab-b-09"):
        plan(session, node_overrides={"lab-b-09": NodeOverride(cores=2)})


def test_an_override_that_breaks_a_rule_is_refused_with_the_reason(session, pve):
    with pytest.raises(CreateInvalid, match="heap_mb must not exceed half"):
        plan(session, node_overrides={"lab-b-01": NodeOverride(heap_mb=8192)})


def test_a_fixed_address_inside_the_dhcp_range_is_refused(session, pve):
    with pytest.raises(CreateInvalid, match="DHCP"):
        plan(session, node_overrides={"lab-b-01": NodeOverride(ip="192.168.10.200")})


def test_custom_needs_nodes_and_presets_refuse_them(session, pve):
    with pytest.raises(CreateInvalid, match="needs a nodes list"):
        plan(session, preset=TopologyPreset.custom)
    from app.desired import NodeSpec
    with pytest.raises(CreateInvalid, match="only for the custom preset"):
        plan(session, nodes=[NodeSpec(name="x-01", data_disk_gb=100)])


def test_the_address_pool_running_out_is_reported_plainly(session, pve):
    from app.models import NetworkProfileRow
    row = session.scalar(select(NetworkProfileRow))
    row.range_end = "192.168.10.111"
    session.commit()
    with pytest.raises(CreateInvalid, match="no free address left"):
        plan(session)


# ---- Proxmox facts --------------------------------------------------------------------------------------

def test_a_missing_template_is_refused_with_a_plain_message(session, pve):
    with pytest.raises(CreateInvalid, match="no single template with VMID 9999"):
        plan(session, template_vmid=9999)


def test_no_template_configured_is_refused(session, pve):
    with pytest.raises(CreateInvalid, match="no template"):
        plan(session, template_vmid=None)


def test_connections_must_be_unambiguous(session, pve):
    with pytest.raises(CreateInvalid, match="does not exist"):
        plan(session, proxmox_connection_id="nope")
    cred = Credential(kind="proxmox", name="pve-b", ciphertext=crypto.encrypt("secret-value-456"))
    session.add(cred)
    session.flush()
    session.add(ProxmoxConnection(name="pve-b", api_url="https://b.example.org:8006", token_id="x@pve!y",
                                  credential_id=cred.id))
    session.commit()
    with pytest.raises(CreateInvalid, match="more than one Proxmox connection"):
        plan(session)
    assert plan(session, proxmox_connection_id=pve.id)[1].params["proxmox_connection_id"] == pve.id


def test_no_known_hosts_means_sync_first(session, pve):
    for node in session.scalars(select(PveNode)):
        session.delete(node)
    session.commit()
    with pytest.raises(CreateInvalid, match="run a sync"):
        plan(session)


def test_nodes_that_do_not_fit_are_refused_with_the_reason(session, pve):
    for node in session.scalars(select(PveNode)):
        node.usage = {**node.usage, "mem": 186 * GIB}
    session.commit()
    with pytest.raises(CreateInvalid, match="cannot be placed"):
        plan(session)


def test_a_template_on_local_storage_cannot_be_cloned_to_another_host(session, pve):
    template = session.scalar(select(Vm).where(Vm.vmid == 8000))
    template.disks = [{"slot": "scsi0", "storage": "local-lvm", "size_gb": 32}]
    session.add(PveStorage(connection_id=pve.id, node="pve1", name="local-lvm", type="lvmthin", shared=False,
                           active=True, total=GIB, used=0, avail=GIB))
    session.commit()
    with pytest.raises(CreateInvalid, match="local-lvm") as err:
        plan(session)
    assert "pve1" in str(err.value) and "pve_node" in str(err.value)

    pinned = {f"lab-b-0{i}": NodeOverride(pve_node="pve1") for i in (1, 2, 3)}
    resolved = plan(session, node_overrides=pinned)[2]               # all on the template's host: fine
    assert set(resolved.placement.values()) == {"pve1"}
    assert any("master quorum" in w for w in resolved.warnings)      # but the quorum warning still shows


# ---- planning the same cluster again --------------------------------------------------------------------

def test_a_dry_run_can_be_followed_by_the_real_create_under_the_same_name(session, pve):
    cluster, dry, first = plan(session)
    finish(session, dry, "succeeded")
    again, real, second = plan(session, dry_run=False)
    assert again.id == cluster.id and real.id != dry.id and not real.dry_run
    assert second.addresses == first.addresses                       # nothing was reserved by the dry run
    assert len(session.scalars(select(Cluster)).all()) == 1


def test_a_plan_in_progress_blocks_planning_the_same_name(session, pve):
    plan(session)                                                     # still running
    with pytest.raises(CreateConflict, match="in progress"):
        plan(session, dry_run=False)


@pytest.mark.parametrize("state, result", [("succeeded", None), ("failed", {"resources_in_state": ["a"]})])
def test_a_name_whose_create_ran_cannot_be_planned_again(session, pve, state, result):
    _, op, _ = plan(session, dry_run=False)
    finish(session, op, state, result=result)
    with pytest.raises(CreateConflict, match="already ran"):
        plan(session)


@pytest.mark.parametrize("state, result", [("cancelled", None), ("failed", None)])
def test_a_name_whose_create_applied_nothing_can_be_planned_again(session, pve, state, result):
    cluster, op, _ = plan(session, dry_run=False)
    finish(session, op, state, result=result)
    assert plan(session, dry_run=False)[0].id == cluster.id


def test_a_request_that_cannot_render_leaves_no_cluster_behind(session, pve):
    with pytest.raises(Exception, match="cannot be rendered"):
        plan(session, pool_id="bad pool name!")
    assert session.scalar(select(Cluster)) is None and session.scalar(select(Operation)) is None


# ---- the HTTP layer -------------------------------------------------------------------------------------

@pytest.fixture
def api(logged_in, pve):
    from app.api.provisioning import get_catalog
    from app.main import app
    app.dependency_overrides[get_catalog] = lambda: StaticCatalog(["9.4.3", "9.3.1"])
    yield logged_in
    app.dependency_overrides.pop(get_catalog, None)


BODY = {"name": "lab-b", "version": "9.4.3", "preset": "three_node", "template_vmid": 8000}


def test_post_plans_a_dry_run_and_enqueues_the_job(api, session):
    from procrastinate import testing

    from app import jobs
    with jobs.queue.replace_connector(testing.InMemoryConnector()) as q:
        r = api.post("/api/clusters", json=BODY, headers=H)
        assert r.status_code == 202, r.text
        assert [j["task_name"] for j in q.connector.jobs.values()] == ["tf.run"]
    body = r.json()
    assert body["dry_run"] is True and len(body["nodes"]) == 3
    assert {n["host"] for n in body["nodes"]} == {"pve1", "pve2", "pve3"}
    assert body["nodes"][0] == {"name": "lab-b-01", **{k: body["nodes"][0][k] for k in ("host", "address", "vm_id")}}
    op = session.get(Operation, body["operation_id"])
    assert op.dry_run and op.created_by == "admin" and op.cluster_id == body["cluster_id"]
    assert api.get("/api/clusters").status_code == 200               # a planned cluster does not break the list


def test_post_with_dry_run_false_makes_an_approvable_operation(api, session):
    from procrastinate import testing

    from app import jobs
    with jobs.queue.replace_connector(testing.InMemoryConnector()):
        r = api.post("/api/clusters", json={**BODY, "dry_run": False}, headers=H)
    assert r.status_code == 202 and r.json()["dry_run"] is False


def test_post_refuses_an_unpublished_version(api):
    r = api.post("/api/clusters", json={**BODY, "version": "9.9.9"}, headers=H)
    assert r.status_code == 422 and "not a published" in r.json()["detail"]
    assert r.json()["detail"].endswith("Newest published: 9.4.3, 9.3.1")      # it says what would work


def test_post_says_so_when_the_version_list_is_unreachable(api):
    from app.api.provisioning import get_catalog
    from app.main import app

    class Down:
        def releases(self):
            raise CatalogError("could not fetch the Elasticsearch version list: timeout")

    app.dependency_overrides[get_catalog] = lambda: Down()
    r = api.post("/api/clusters", json=BODY, headers=H)
    assert r.status_code == 503 and "cannot be verified" in r.json()["detail"]


def test_post_maps_refusals_to_422_and_conflicts_to_409(api, session):
    assert api.post("/api/clusters", json={**BODY, "template_vmid": 9999}, headers=H).status_code == 422
    session.add(Cluster(name="lab-b", ownership="discovered"))
    session.commit()
    assert api.post("/api/clusters", json=BODY, headers=H).status_code == 409


def test_post_rejects_unknown_fields_and_bad_values(api):
    assert api.post("/api/clusters", json={**BODY, "ownership": "adopted"}, headers=H).status_code == 422
    assert api.post("/api/clusters", json={**BODY, "preset": "nonsense"}, headers=H).status_code == 422
    assert api.post("/api/clusters", json={**BODY, "data_nodes": 0}, headers=H).status_code == 422


def test_post_needs_a_session_and_the_csrf_header(client, pve):
    assert client.post("/api/clusters", json=BODY, headers=H).status_code == 401


def test_a_failed_enqueue_marks_the_operation_failed_and_frees_the_name(api, session, monkeypatch):
    from app import jobs

    async def boom(**_):
        raise RuntimeError("queue down")

    monkeypatch.setattr(jobs.tf_run, "defer_async", boom)
    r = api.post("/api/clusters", json=BODY, headers=H)
    assert r.status_code == 503
    op = session.scalar(select(Operation))
    assert op.state == "failed" and "queue down" in op.error
    assert "operation.enqueue_failed" in [e.action for e in session.scalars(select(AuditEvent))]
    monkeypatch.undo()
    from procrastinate import testing
    with jobs.queue.replace_connector(testing.InMemoryConnector()):
        assert api.post("/api/clusters", json=BODY, headers=H).status_code == 202    # the same name works again


# ---- from the request all the way through the job -------------------------------------------------------

def test_a_planned_dry_run_runs_to_a_reviewable_plan_that_cannot_be_approved(session, pve, tmp_path, monkeypatch):
    """The params the resolver stores must render, init and plan through the real job code."""
    from app import operations
    from app.provisioning.operation import run_operation
    from app.provisioning.plan import summarize_plan
    from app.provisioning.runner import PlanOutcome

    monkeypatch.setenv("ECM_TF_STATE_URL", "postgresql://tf:statepw1234@db/tfstate")
    config.get_settings.cache_clear()
    rights = {"/pool/ecm": {"VM.Allocate": 1}, "/storage/tank": {"Datastore.AllocateSpace": 1}, "/vms/8000": {"VM.Clone": 1}}
    monkeypatch.setattr(factory, "transport", httpx.MockTransport(lambda r: httpx.Response(200, json={"data": rights})))
    _, op, resolved = plan(session)

    class FakeTerraform:
        def __init__(self, log):
            pass

        def init(self, ws, env):
            assert (ws.dir / "cluster.auto.tfvars.json").exists()

        def plan(self, ws, env, *, destroy=False):
            vars_ = (ws.dir / "cluster.auto.tfvars.json").read_text()
            assert all(a in vars_ for a in resolved.addresses.values())          # the planned addresses are in it
            ws.plan_path.write_bytes(b"plan")
            summary = summarize_plan({"resource_changes": [
                {"address": f"vm.{n}", "change": {"actions": ["create"]}} for n in resolved.addresses]})
            return PlanOutcome(True, summary)

        def apply(self, ws, env):
            raise AssertionError("a dry run must never apply")

    run_operation(session, op.id, FakeTerraform, tmp_path)
    session.refresh(op)
    assert op.state == "succeeded" and op.plan_summary["adds"] == 3 and op.plan_digest
    with pytest.raises(operations.ApprovalRefused, match="dry run"):
        operations.approve_operation(session, op.id, op.plan_digest, "admin")


# ---- when ECM cannot see the machines that already exist ------------------------------------------------

def test_it_warns_when_it_can_see_no_vms_at_all(session, pve):
    warning = next(w for w in plan(session)[2].warnings if "can see no VMs" in w)
    assert "PVEAuditor" in warning and "addresses, names and VMIDs" in warning


def test_that_warning_goes_away_once_a_vm_is_visible(session, pve):
    session.add(Vm(connection_id=pve.id, pve_node="pve1", vmid=301, name="other-vm", status="running"))
    session.commit()
    assert not any("can see no VMs" in w for w in plan(session)[2].warnings)


def test_the_plan_says_why_a_host_was_not_used(session, pve):
    for node in session.scalars(select(PveNode).where(PveNode.name == "pve1")):
        node.usage = {**node.usage, "mem": 186 * GIB}
    session.commit()
    notes = plan(session)[2].warnings
    assert any(w.startswith("pve1 was not used: not enough free RAM") for w in notes)
    assert any("master quorum" in w for w in notes)                  # the consequence, and now its cause


# ---- one token for two jobs ----------------------------------------------------------------------------

def test_the_plan_nudges_towards_a_separate_terraform_token_until_there_is_one(session, pve):
    assert any("one token for both discovery and Terraform" in w for w in plan(session)[2].warnings)

    cred = Credential(kind="proxmox_token", name="tf", ciphertext=crypto.encrypt("terraform-secret-1111"))
    session.add(cred)
    session.flush()
    pve.terraform_credential_id, pve.terraform_token_id = cred.id, "tf@pve!terraform"
    session.commit()
    assert not any("one token for both" in w for w in plan(session, name="lab-c")[2].warnings)


# ---- after a teardown ----------------------------------------------------------------------------------

def test_a_torn_down_create_frees_its_addresses_and_its_name_at_once(session, pve):
    cluster, op, first = plan(session, name="lab-a", dry_run=False)
    finish(session, op, "succeeded", finished_at=datetime.now(UTC), result={"resources_in_state": ["vm.a"]})
    held = plan(session, name="lab-b", dry_run=False)[2]
    assert not set(held.addresses.values()) & set(first.addresses.values())       # held while it exists
    with pytest.raises(CreateConflict, match="already ran"):
        plan(session, name="lab-a", dry_run=False)                                  # and the name is taken

    session.add(Operation(kind="tf.destroy", cluster_id=cluster.id, parent_op_id=op.id, state="succeeded"))
    session.commit()
    freed = plan(session, name="lab-c", dry_run=False)[2]
    assert set(freed.addresses.values()) & set(first.addresses.values())            # free again, though recent
    again, _, _ = plan(session, name="lab-a", dry_run=False)
    assert again.id == cluster.id                                                    # the same cluster, planned anew


def test_a_teardown_that_failed_part_way_keeps_the_name_and_the_addresses(session, pve):
    cluster, op, first = plan(session, name="lab-a", dry_run=False)
    finish(session, op, "succeeded", finished_at=datetime.now(UTC), result={"resources_in_state": ["vm.a"]})
    session.add(Operation(kind="tf.destroy", cluster_id=cluster.id, parent_op_id=op.id, state="failed",
                          result={"resources_in_state": ["vm.a"]}))
    session.commit()
    with pytest.raises(CreateConflict, match="already ran"):
        plan(session, name="lab-a", dry_run=False)
    assert not set(plan(session, name="lab-b", dry_run=False)[2].addresses.values()) & set(first.addresses.values())


def test_a_failed_teardown_followed_by_a_successful_one_leaves_nothing_to_block_the_name(session, pve):
    """A destroy never blocks by itself: the create it belongs to decides whether anything remains."""
    cluster, op, _ = plan(session, name="lab-a", dry_run=False)
    finish(session, op, "succeeded", finished_at=datetime.now(UTC), result={"resources_in_state": ["vm.a"]})
    session.add(Operation(kind="tf.destroy", cluster_id=cluster.id, parent_op_id=op.id, state="failed",
                          result={"resources_in_state": ["vm.a"]}))
    session.add(Operation(kind="tf.destroy", cluster_id=cluster.id, parent_op_id=op.id, state="succeeded"))
    session.commit()
    assert plan(session, name="lab-a", dry_run=False)[0].id == cluster.id


# ---- the CPU type --------------------------------------------------------------------------------------

def test_a_create_asks_for_the_host_cpu_type_unless_told_otherwise(session, pve):
    assert request().cpu_type == "host"
    assert plan(session)[1].params["cpu_type"] == "host"
    assert plan(session, name="lab-c", cpu_type="x86-64-v2-AES")[1].params["cpu_type"] == "x86-64-v2-AES"


def test_a_cpu_type_that_is_not_one_is_refused_before_anything_is_planned(session, pve):
    for bad in ("host; rm", "two words", ""):
        with pytest.raises(ValueError):
            request(cpu_type=bad)


def test_a_stored_create_from_before_the_setting_existed_still_renders_with_host(session, pve):
    from app.provisioning.operation import render_input
    _, op, _ = plan(session)
    params = {k: v for k, v in op.params.items() if k != "cpu_type"}
    assert render_input(params, "0123456789abcdef0123456789abcdef", "https://pve.test:8006", False).cpu_type == "host"


def test_post_clusters_takes_a_cpu_type_and_refuses_a_bad_one(logged_in, session, pve, monkeypatch):
    from procrastinate import testing

    from app import jobs
    from app.api.provisioning import get_catalog
    from app.main import app
    app.dependency_overrides[get_catalog] = lambda: StaticCatalog(["9.4.3"])
    try:
        body = {"name": "lab-b", "version": "9.4.3", "preset": "three_node", "template_vmid": 8000}
        assert logged_in.post("/api/clusters", json={**body, "cpu_type": "bad type"}, headers=H).status_code == 422
        with jobs.queue.replace_connector(testing.InMemoryConnector()):
            r = logged_in.post("/api/clusters", json={**body, "cpu_type": "x86-64-v3"}, headers=H)
        assert r.status_code == 202
        assert session.get(Operation, r.json()["operation_id"]).params["cpu_type"] == "x86-64-v3"
    finally:
        app.dependency_overrides.pop(get_catalog, None)
