from tests.conftest import PASSWORD, H


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/operations").status_code == 401
    assert client.get("/api/health").status_code == 200


def test_login_logout(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}, headers=H)
    assert r.status_code == 200
    assert "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=strict" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json()["username"] == "admin"
    assert client.post("/api/auth/logout", headers=H).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_bad_password_and_unknown_user(client):
    for user in ("admin", "nobody"):
        r = client.post("/api/auth/login", json={"username": user, "password": "wrong"}, headers=H)
        assert r.status_code == 401


def test_lockout_after_repeated_failures(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "x"}, headers=H)
    r = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}, headers=H)
    assert r.status_code == 429


def test_mutations_require_csrf_header(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert r.status_code == 403


def test_failed_login_is_audited(client, session):
    from sqlalchemy import select

    from app.models import AuditEvent
    client.post("/api/auth/login", json={"username": "admin", "password": "x"}, headers=H)
    assert session.scalar(select(AuditEvent).where(AuditEvent.action == "auth.login_failed"))
