import pytest
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import auth, config, db

PASSWORD = "correct horse battery"
H = {"x-ecm-csrf": "1"}


@pytest.fixture
def settings_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ECM_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("ECM_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("ECM_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ECM_ADMIN_PASSWORD_HASH", PasswordHasher().hash(PASSWORD))
    monkeypatch.setenv("ECM_SECURE_COOKIES", "false")
    config.get_settings.cache_clear()
    db.reset_engine()
    auth._failures.clear()
    from app import models  # noqa: F401
    db.Base.metadata.create_all(db.get_engine())
    yield
    db.reset_engine()
    config.get_settings.cache_clear()


@pytest.fixture
def session(settings_env):
    with db.session_factory()() as s:
        yield s


@pytest.fixture
def client(settings_env):
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def logged_in(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}, headers=H)
    assert r.status_code == 200
    return client
