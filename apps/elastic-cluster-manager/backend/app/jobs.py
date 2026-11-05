import procrastinate

from app.config import get_settings
from app.db import session_factory
from app.operations import log, run_phases


def _conninfo() -> str:
    # SQLAlchemy URL -> libpq URL
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


queue = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=_conninfo()),
                          import_paths=["app.jobs"])

DEMO_PHASES = ["validate", "work", "finish"]


def demo_handlers(db, op_id: str) -> dict:
    def step(name):
        return lambda: log(db, op_id, f"phase {name} completed")
    return {p: step(p) for p in DEMO_PHASES}


@queue.task(name="demo.noop", retry=procrastinate.RetryStrategy(max_attempts=3, wait=5))
def demo_noop(operation_id: str) -> None:
    """Placeholder job proving durable execution. Real provisioning jobs follow this shape."""
    with session_factory()() as db:
        run_phases(db, operation_id, demo_handlers(db, operation_id))


@queue.task(name="tf.run")  # no retry strategy: a Terraform run is retried only by a person, never automatically
def tf_run(operation_id: str) -> None:
    """Run or resume a Terraform operation: until it pauses for approval, finishes or fails."""
    from app.provisioning.operation import run_operation

    with session_factory()() as db:
        run_operation(db, operation_id)


_minutes = min(max(get_settings().sync_interval_minutes, 1), 59)


@queue.periodic(cron=f"*/{_minutes} * * * *")
@queue.task(name="discovery.sync_all")
def sync_all(timestamp: int) -> None:
    """Read-only refresh of Proxmox and every registered Elasticsearch cluster."""
    from app.discovery.sync import sync_everything

    with session_factory()() as db:
        sync_everything(db)
