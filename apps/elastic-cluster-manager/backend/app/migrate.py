"""Run on deploy: Alembic migrations, then the Procrastinate schema (once)."""
import subprocess
import sys

from sqlalchemy import text

from app.db import get_engine


def main() -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    with get_engine().begin() as conn:
        exists = conn.execute(text("select to_regclass('procrastinate_jobs')")).scalar()
    if exists is None:
        subprocess.run(["procrastinate", "--app=app.jobs.queue", "schema", "--apply"], check=True)


if __name__ == "__main__":
    main()
