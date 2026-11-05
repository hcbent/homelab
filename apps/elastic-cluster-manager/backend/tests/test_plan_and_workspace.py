import json

import pytest

from app.provisioning.plan import PlanSummary, ResourceChange, check_plan_safety, summarize_plan
from app.provisioning.render import config_digest
from app.provisioning.workspace import (
    PLAN_FILE,
    StalePlan,
    WorkspaceError,
    open_workspace,
)


def plan_json(*changes: tuple[str, list[str]]) -> dict:
    return {"resource_changes": [{"address": a, "change": {"actions": acts}} for a, acts in changes]}


# ---- reading a plan ------------------------------------------------------------------------------

def test_summary_counts_each_kind_of_change():
    s = summarize_plan(plan_json(
        ("module.node[\"b\"].vm", ["create"]), ("module.node[\"a\"].vm", ["create"]),
        ("x.upd", ["update"]), ("x.del", ["delete"]), ("x.rep1", ["delete", "create"]),
        ("x.rep2", ["create", "delete"]), ("x.same", ["no-op"]), ("x.data", ["read"])))
    assert (s.adds, s.updates, s.deletes, s.replaces) == (2, 1, 1, 2)
    assert [c.address for c in s.changes][:2] == ['module.node["a"].vm', 'module.node["b"].vm']   # sorted
    assert not s.is_empty


def test_noop_and_read_only_plans_are_empty():
    assert summarize_plan(plan_json(("x.a", ["no-op"]), ("x.b", ["read"]))).is_empty
    assert summarize_plan({}).is_empty


def test_json_form_leaves_out_unchanged_resources():
    out = summarize_plan(plan_json(("x.a", ["no-op"]), ("x.b", ["create"]))).to_json()
    assert out["adds"] == 1 and out["changes"] == [{"address": "x.b", "action": "create"}]
    json.dumps(out)                                              # serialisable for storage


# ---- what each operation may do ------------------------------------------------------------------

CREATE_ONLY = summarize_plan(plan_json(("a", ["create"]), ("b", ["create"]), ("c", ["no-op"])))


def test_create_may_only_create():
    assert check_plan_safety(CREATE_ONLY, "create") == []
    for acts, word in ((["delete"], "delete"), (["update"], "change"), (["delete", "create"], "replace")):
        problems = check_plan_safety(summarize_plan(plan_json(("vm.keep", acts))), "create")
        assert len(problems) == 1 and word in problems[0] and "vm.keep" in problems[0]


def test_update_may_create_and_change_but_never_delete_or_replace():
    ok = summarize_plan(plan_json(("a", ["create"]), ("b", ["update"])))
    assert check_plan_safety(ok, "update") == []
    assert check_plan_safety(summarize_plan(plan_json(("a", ["delete"]))), "update")
    assert check_plan_safety(summarize_plan(plan_json(("a", ["create", "delete"]))), "update")


def test_destroy_may_only_delete():
    assert check_plan_safety(summarize_plan(plan_json(("a", ["delete"]), ("b", ["delete"]))), "destroy") == []
    bad = check_plan_safety(summarize_plan(plan_json(("a", ["delete"]), ("b", ["create"]))), "destroy")
    assert len(bad) == 1 and "b" in bad[0]


def test_adoption_import_must_show_no_change_at_all():
    assert check_plan_safety(summarize_plan(plan_json(("a", ["no-op"]))), "import") == []
    assert check_plan_safety(PlanSummary(), "import") == []
    bad = check_plan_safety(summarize_plan(plan_json(("a", ["update"]))), "import")
    assert any("no changes at all" in p for p in bad)
    assert check_plan_safety(summarize_plan(plan_json(("a", ["delete", "create"]))), "import")


def test_unknown_kinds_are_refused():
    assert "unknown operation kind" in check_plan_safety(PlanSummary(), "frobnicate")[0]


def test_every_problem_names_the_resource():
    s = PlanSummary([ResourceChange("a.one", "delete"), ResourceChange("a.two", "replace")])
    problems = check_plan_safety(s, "create")
    assert len(problems) == 2 and "a.one" in problems[0] and "a.two" in problems[1]


# ---- the workspace -------------------------------------------------------------------------------

ID = "a1b2c3d4e5f60718"
FILES = {"main.tf": 'resource "terraform_data" "x" {}\n', "modules/m/main.tf": "# module\n",
         "cluster.auto.tfvars.json": '{"a": 1}\n'}


def make_ws(tmp_path, files=None):
    return open_workspace(tmp_path, ID, files or FILES)


def make_plan(ws, kind="create", files=None, body=b"plan-bytes"):
    ws.plan_path.write_bytes(body)
    return ws.save_plan(kind, files or FILES, PlanSummary([ResourceChange("a", "create")]))


def test_files_are_written_under_the_cluster_directory(tmp_path):
    ws = make_ws(tmp_path)
    assert ws.dir == (tmp_path / ID / "tf").resolve()
    assert (ws.dir / "modules/m/main.tf").read_text() == "# module\n"
    assert not list(ws.dir.rglob("*.tmp"))                       # atomic writes leave nothing behind


def test_re_rendering_removes_old_files_but_keeps_state_and_provider_cache(tmp_path):
    ws = make_ws(tmp_path)
    (ws.dir / "terraform.tfstate").write_text("STATE")
    (ws.dir / ".terraform").mkdir()
    (ws.dir / ".terraform" / "providers").write_text("CACHE")
    ws2 = make_ws(tmp_path, {"main.tf": "new\n"})
    assert (ws2.dir / "main.tf").read_text() == "new\n"
    assert not (ws2.dir / "modules/m/main.tf").exists() and not (ws2.dir / "cluster.auto.tfvars.json").exists()
    assert (ws2.dir / "terraform.tfstate").read_text() == "STATE"
    assert (ws2.dir / ".terraform" / "providers").read_text() == "CACHE"


@pytest.mark.parametrize("bad", ["../escape", "ABC", "a1b2", "a1b2c3d4/../x", "g" * 16])
def test_cluster_ids_are_validated(tmp_path, bad):
    with pytest.raises(WorkspaceError, match="cluster_id"):
        open_workspace(tmp_path, bad, FILES)


def test_files_cannot_escape_the_workspace(tmp_path):
    with pytest.raises(WorkspaceError, match="outside the workspace"):
        open_workspace(tmp_path, ID, {"../../evil.tf": "x"})
    assert not (tmp_path / "evil.tf").exists()


# ---- binding a plan to its configuration -----------------------------------------------------------

def test_a_plan_applies_when_nothing_changed(tmp_path):
    ws = make_ws(tmp_path)
    meta = make_plan(ws)
    assert meta.digest == config_digest(FILES) and meta.operation_kind == "create"
    assert ws.verify_for_apply("create").summary["adds"] == 1


def test_a_changed_config_makes_the_plan_stale(tmp_path):
    ws = make_ws(tmp_path)
    make_plan(ws)
    (ws.dir / "cluster.auto.tfvars.json").write_text('{"a": 2}\n')           # someone edits the variables
    with pytest.raises(StalePlan, match="configuration changed"):
        ws.verify_for_apply()


def test_re_rendering_different_values_makes_the_old_plan_stale(tmp_path):
    ws = make_ws(tmp_path)
    make_plan(ws)
    open_workspace(tmp_path, ID, {**FILES, "cluster.auto.tfvars.json": '{"a": 3}\n'})
    with pytest.raises(StalePlan, match="configuration changed"):
        ws.verify_for_apply()


def test_a_tampered_plan_file_is_refused(tmp_path):
    ws = make_ws(tmp_path)
    make_plan(ws)
    ws.plan_path.write_bytes(b"something else entirely")
    with pytest.raises(StalePlan, match="plan file changed"):
        ws.verify_for_apply()


def test_missing_plan_or_config_file_is_refused(tmp_path):
    ws = make_ws(tmp_path)
    with pytest.raises(WorkspaceError, match="no approved plan"):
        ws.verify_for_apply()
    make_plan(ws)
    (ws.dir / "main.tf").unlink()
    with pytest.raises(StalePlan, match="configuration file is missing"):
        ws.verify_for_apply()
    make_plan(make_ws(tmp_path))
    ws.plan_path.unlink()
    with pytest.raises(StalePlan, match="plan file is missing"):
        ws.verify_for_apply()


def test_the_operation_kind_must_match(tmp_path):
    ws = make_ws(tmp_path)
    make_plan(ws, kind="destroy")
    with pytest.raises(StalePlan, match="destroy operation, not create"):
        ws.verify_for_apply("create")
    assert ws.verify_for_apply("destroy").operation_kind == "destroy"


def test_saving_needs_a_plan_file_and_discarding_keeps_state(tmp_path):
    ws = make_ws(tmp_path)
    with pytest.raises(WorkspaceError, match="no plan file"):
        ws.save_plan("create", FILES, PlanSummary())
    make_plan(ws)
    (ws.dir / "terraform.tfstate").write_text("STATE")
    ws.discard_plan()
    assert not ws.plan_path.exists() and not ws.meta_path.exists()
    assert (ws.dir / "terraform.tfstate").read_text() == "STATE"
    ws.discard_plan()                                                  # idempotent
    assert PLAN_FILE == "plan.tfplan"
