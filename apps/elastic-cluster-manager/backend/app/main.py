import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import auth
from app.api import auth as auth_api
from app.api import operations as ops_api
from app.config import get_settings
from app.crypto import install_log_redaction, register_secret
from app.db import session_factory
from app.jobs import queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    install_log_redaction()
    s = get_settings()
    register_secret(s.master_key.get_secret_value())
    register_secret(s.admin_password_hash.get_secret_value())
    with session_factory()() as db:
        auth.sync_admin(db)
    if s.database_url.startswith("postgresql"):
        # The API only enqueues jobs; the pool must be open for defer_async to work.
        async with queue.open_async():
            yield
    else:  # tests use SQLite and an in-memory queue
        yield


app = FastAPI(title="Elasticsearch Cluster Manager", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth_api.router)
app.include_router(ops_api.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
