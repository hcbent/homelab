import pytest
from sqlalchemy import select

from app import operations
from app.models import Cluster, Operation, OperationLog, OperationStep


def test_one_active_operation_per_cluster(session):
    c = Cluster(name="c1")
    session.add(c)
    session.commit()
    op = operations.create_operation(session, "tf.update", ["a"], cluster_id=c.id)
    with pytest.raises(operations.OperationConflict):
        operations.create_operation(session, "tf.destroy", ["a"], cluster_id=c.id)
    op.state = "failed"
    session.commit()
    operations.create_operation(session, "tf.update", ["a"], cluster_id=c.id)


def test_resume_skips_completed_phases(session):
    op = operations.create_operation(session, "demo", ["one", "two", "three"])
    calls = []

    def boom():
        raise RuntimeError("password=hunter2hunter2 failed")

    handlers = {"one": lambda: calls.append("one"), "two": boom,
                "three": lambda: calls.append("three")}
    with pytest.raises(RuntimeError):
        operations.run_phases(session, op.id, handlers)
    session.refresh(op)
    assert op.state == "failed" and "hunter2hunter2" not in op.error
    assert [s.status for s in session.scalars(
        select(OperationStep).order_by(OperationStep.seq))] == ["done", "failed", "pending"]

    # retry: "one" must not run again
    handlers["two"] = lambda: calls.append("two")
    operations.run_phases(session, op.id, handlers)
    session.refresh(op)
    assert op.state == "succeeded" and calls == ["one", "two", "three"]


def test_logs_are_redacted(session):
    op = operations.create_operation(session, "demo", ["a"])
    operations.log(session, op.id, "tok" + "en=abcdef123456")  # split: avoids scanner false positive
    assert "abcdef" not in session.scalar(select(OperationLog.line))
    assert session.get(Operation, op.id)


def test_demo_job_end_to_end(logged_in, session):
    from procrastinate import testing

    from app import jobs
    with jobs.queue.replace_connector(testing.InMemoryConnector()) as q:
        r = logged_in.post("/api/operations/demo", headers={"x-ecm-csrf": "1"})
        assert r.status_code == 202
        q.run_worker(wait=False)
    d = logged_in.get(f"/api/operations/{r.json()['id']}").json()
    assert d["state"] == "succeeded"
    assert d["progress"] == {"done": 3, "total": 3}
    assert any("phase work" in line["line"] for line in d["logs"])
