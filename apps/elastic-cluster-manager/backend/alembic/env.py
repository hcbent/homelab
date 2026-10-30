from alembic import context
from app import models  # noqa: F401  (registers tables)
from app.db import Base, get_engine

target_metadata = Base.metadata


def run() -> None:
    with get_engine().connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run()
