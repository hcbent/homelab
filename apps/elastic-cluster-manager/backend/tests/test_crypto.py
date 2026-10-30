import pytest
from cryptography.fernet import Fernet

from app import config, crypto


def test_roundtrip_and_ciphertext_differs(settings_env):
    ct = crypto.encrypt("s3cret-value")
    assert b"s3cret-value" not in ct
    assert crypto.decrypt(ct) == "s3cret-value"


def test_key_rotation(settings_env, monkeypatch):
    ct = crypto.encrypt("v")
    old = config.get_settings().master_key.get_secret_value()
    new = Fernet.generate_key().decode()
    monkeypatch.setenv("ECM_MASTER_KEY", f"{new},{old}")
    config.get_settings.cache_clear()
    assert crypto.decrypt(ct) == "v"


def test_missing_key_fails_loudly(settings_env, monkeypatch):
    monkeypatch.setenv("ECM_MASTER_KEY", "")
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        crypto.encrypt("x")


def test_redaction_patterns_and_known_values():
    crypto.register_secret("hunter2hunter2")
    out = crypto.redact("pw=hunter2hunter2 password: abc123 Authorization: Bearer tok.en "
                        "PVEAPIToken=root@pam!ecm=12345678-aaaa-bbbb")
    assert "hunter2hunter2" not in out and "abc123" not in out and "tok.en" not in out
    assert "12345678-aaaa" not in out
    key = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----"
    assert "AAAA" not in crypto.redact(key)
