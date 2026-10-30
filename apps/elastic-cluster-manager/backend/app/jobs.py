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
