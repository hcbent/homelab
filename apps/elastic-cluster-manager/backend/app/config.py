from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from ECM_* environment variables (see deploy/.env.example)."""

    model_config = SettingsConfigDict(env_prefix="ECM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ecm:ecm@localhost:5432/ecm"
    # Comma-separated Fernet keys. First encrypts; all decrypt (supports rotation).
    master_key: SecretStr = SecretStr("")
    admin_username: str = "admin"
    # Argon2id hash. Generate with: python -m app.hashpw
    admin_password_hash: SecretStr = SecretStr("")
    secure_cookies: bool = True
    session_ttl_hours: int = 12
    login_max_failures: int = 5
    login_lockout_seconds: int = 300
    # Background discovery refresh, in minutes (1-59)
    sync_interval_minutes: int = 5

    # Terraform. The worker image provides the binary and a vendored provider (plugin dir); nothing is downloaded.
    terraform_binary: str = "terraform"
    terraform_plugin_dir: str | None = None
    tf_workspace_root: str = "/data/clusters"
    # libpq URL of the database that holds Terraform state (one schema per cluster). Handed to Terraform as
    # PG_CONN_STR and nowhere else. Empty means Terraform operations cannot run.
    tf_state_url: SecretStr = SecretStr("")

    # Proxmox VMIDs handed out to new nodes (DECISIONS: disposable VMs use 5xx)
    vmid_range_start: int = 500
    vmid_range_end: int = 599

    # Defaults offered by the wizard in later phases. Never assumed to exist.
    default_template_vmid: int | None = None
    default_template_name: str | None = None
    default_storage: str = "tank"


@lru_cache
def get_settings() -> Settings:
    return Settings()
