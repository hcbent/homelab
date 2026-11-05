"""The Terraform state connection string: built from parts so a password with special characters works, and
never echoed back in pieces."""
import shutil
from urllib.parse import unquote, urlsplit

import pytest
from sqlalchemy.engine import URL

from app import config, crypto
from app.config import Settings, tf_state_conninfo
from app.dburl import libpq_url
from app.provisioning.runner import CliTerraformRunner, TerraformError
from app.provisioning.workspace import Workspace, open_workspace

NASTY = ["Fake#pw-9x", "a/b?c:d%e", "p w+d", "100%", "ünï©ode", "!$&'()*,;=", "x" * 3 + "@" + "y" * 3, "plain"]


def sqla(password, **kw):
    return URL.create("postgresql+psycopg", **{"username": "ecm", "host": "postgres", "port": 5432,
                                               "database": "ecm", **kw}, password=password
                      ).render_as_string(hide_password=False)


# ---- building the URL -------------------------------------------------------------------------------------

@pytest.mark.parametrize("password", NASTY)
def test_every_part_survives_a_round_trip_through_a_standard_url_parser(password):
    got = urlsplit(libpq_url(sqla(password)))
    assert got.scheme == "postgresql"
    assert (unquote(got.username), unquote(got.password)) == ("ecm", password)
    assert (got.hostname, got.port, got.path) == ("postgres", 5432, "/ecm")
    assert got.fragment == "" and got.query == ""                    # nothing leaked out of the password


@pytest.mark.parametrize("username", ["dba@corp", "ops user#1", "a/b:c"])
def test_a_username_with_special_characters_survives_too(username):
    got = urlsplit(libpq_url(sqla("pw-1234", username=username)))
    assert unquote(got.username) == username and unquote(got.password) == "pw-1234" and got.hostname == "postgres"


def test_the_password_from_the_real_deployment_shape_works():
    """The compose file used to build this URL by pasting the password into a string."""
    got = urlsplit(libpq_url("postgresql+psycopg://ecm:Fake#pw-9x@postgres:5432/ecm"))
    assert unquote(got.password) == "Fake#pw-9x" and got.hostname == "postgres" and got.path == "/ecm"


def test_query_options_ipv6_and_missing_parts_are_kept():
    assert libpq_url("postgresql+psycopg://u:p@db/ecm?sslmode=require") == "postgresql://u:p@db/ecm?sslmode=require"
    assert libpq_url("postgresql://u@[::1]:5433/x") == "postgresql://u@[::1]:5433/x"
    assert libpq_url("postgresql://db") == "postgresql://db"


def test_anything_but_postgresql_gives_nothing():
    assert libpq_url("sqlite:////tmp/x.db") == ""


# ---- choosing it ------------------------------------------------------------------------------------------

def test_an_explicit_state_url_wins_and_otherwise_it_comes_from_the_database_url():
    own = Settings(database_url="postgresql+psycopg://ecm:Fake#pw-9x@postgres:5432/ecm", tf_state_url="")
    assert unquote(urlsplit(tf_state_conninfo(own)).password) == "Fake#pw-9x"
    chosen = Settings(database_url="postgresql+psycopg://ecm:pw@postgres:5432/ecm",
                      tf_state_url="postgresql://tf:other@elsewhere/tfstate")
    assert tf_state_conninfo(chosen) == "postgresql://tf:other@elsewhere/tfstate"
    assert tf_state_conninfo(Settings(database_url="sqlite:////tmp/x.db", tf_state_url="")) == ""


def test_the_operation_hands_terraform_the_derived_url(session, tmp_path, monkeypatch):
    from app.models import Credential, Operation, ProxmoxConnection
    from app.provisioning.operation import _Handlers

    monkeypatch.setenv("ECM_TF_STATE_URL", "")
    monkeypatch.setenv("ECM_DATABASE_URL", "postgresql+psycopg://ecm:Fake#pw-9x@postgres:5432/ecm")
    config.get_settings.cache_clear()
    cred = Credential(kind="proxmox", name="pve", ciphertext=crypto.encrypt("token-secret-123"))
    session.add(cred)
    session.flush()
    conn = ProxmoxConnection(name="pve", api_url="https://pve.example.org:8006", token_id="ecm@pve!tf",
                             credential_id=cred.id)
    session.add(conn)
    session.flush()
    op = Operation(kind="tf.create", params={"proxmox_connection_id": conn.id})
    session.add(op)
    session.commit()

    env = _Handlers(session, op, lambda _log: None, tmp_path)._env()
    assert set(env) == {"PROXMOX_VE_API_TOKEN", "PG_CONN_STR"}
    got = urlsplit(env["PG_CONN_STR"])
    assert unquote(got.password) == "Fake#pw-9x" and got.hostname == "postgres" and got.path == "/ecm"
    assert "#" not in env["PG_CONN_STR"]                              # what broke Terraform on infra


# ---- not echoing it back ----------------------------------------------------------------------------------

def test_the_password_inside_a_url_is_masked_on_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_known", set())
    ws = Workspace(tmp_path)
    CliTerraformRunner()._env(ws, {"PG_CONN_STR": "postgresql://ecm:Sup3r%23Secret@db/x"})
    assert "Sup3r#Secret" not in crypto.redact("connecting with Sup3r#Secret failed")      # decoded form
    assert "Sup3r%23Secret" not in crypto.redact("url had Sup3r%23Secret in it")             # as written


# ---- against the real Terraform CLI -----------------------------------------------------------------------

needs_terraform = pytest.mark.skipif(not shutil.which("terraform"), reason="terraform is not installed")
BACKEND = {"main.tf": 'terraform {\n  backend "pg" {\n    schema_name = "tf_probe"\n  }\n}\n'}
ID = "0123456789abcdef"


def init_error(tmp_path, url, monkeypatch):
    monkeypatch.setattr(crypto, "_known", set())
    ws = open_workspace(tmp_path, ID, BACKEND)
    with pytest.raises(TerraformError) as err:                      # nothing listens on port 1
        CliTerraformRunner(log=lambda _: None).init(ws, {"PG_CONN_STR": url})
    return str(err.value)


@needs_terraform
@pytest.mark.parametrize("password", ["Fake#pw-9x", "a/b?c:d%e", "p w+d"])
def test_terraform_accepts_the_derived_url_and_only_fails_to_connect(tmp_path, monkeypatch, password):
    url = libpq_url(sqla(password, host="127.0.0.1", port=1))
    message = init_error(tmp_path, url, monkeypatch)
    assert "connection refused" in message and "invalid" not in message and "parse" not in message


@needs_terraform
def test_a_url_that_still_breaks_terraform_does_not_leak_the_start_of_the_password(tmp_path, monkeypatch):
    """The failure that happened on infra: a raw # cuts the URL short and Terraform echoes the piece it kept."""
    message = init_error(tmp_path, "postgresql://ecm:Zq8wLm3Xtv#tail@127.0.0.1:1/ecm", monkeypatch)
    assert "invalid port" in message                                 # it does still fail...
    assert "Zq8wLm3Xtv" not in message and "[REDACTED]" in message   # ...but the password is not shown


def test_the_pieces_of_a_password_a_url_parser_could_echo_are_masked(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "_known", set())
    CliTerraformRunner()._env(Workspace(tmp_path), {"PG_CONN_STR": "postgresql://ecm:Zq8wLm3Xtv#tail/x?y@db:5432/ecm"})
    for shown in ("Zq8wLm3Xtv", "Zq8wLm3Xtv#tail/x?y"):
        assert shown not in crypto.redact(f'parse "postgresql://ecm:{shown}": invalid port')


@pytest.mark.parametrize("value", ["", "not a url", "https://example.org/path", "postgresql://db/ecm",
                                   "postgresql://user@db/ecm"])
def test_values_without_a_password_register_nothing(tmp_path, monkeypatch, value):
    monkeypatch.setattr(crypto, "_known", set())
    CliTerraformRunner()._env(Workspace(tmp_path), {"PG_CONN_STR": value})
    assert crypto._known <= {value}                                  # only the whole value, if long enough
