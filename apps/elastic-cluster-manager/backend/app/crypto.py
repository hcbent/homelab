"""Credential encryption and log redaction."""
import logging
import re
import threading

from cryptography.fernet import Fernet, MultiFernet

from app.config import get_settings

REDACTED = "[REDACTED]"


def _fernet() -> MultiFernet:
    raw = get_settings().master_key.get_secret_value()
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("ECM_MASTER_KEY is not set")
    return MultiFernet([Fernet(k) for k in keys])


def encrypt(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    return _fernet().decrypt(ciphertext).decode()


def generate_key() -> str:
    return Fernet.generate_key().decode()


# --- redaction -------------------------------------------------------------

_lock = threading.Lock()
_known: set[str] = set()

# Key=value / header-style secrets and Proxmox token secrets.
_PATTERNS = [
    re.compile(r"(?i)((?:password|passwd|secret|token|api[_-]?key|authorization)\"?\s*[:=]\s*\"?)"
               r"(?:Bearer\s+|ApiKey\s+)?[^\s\",;]+"),
    re.compile(r"(?i)(PVEAPIToken=[^=\s]+=)[0-9a-f-]{8,}"),
    re.compile(r"(?i)(-----BEGIN [A-Z ]*PRIVATE KEY-----)[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----)"),
]


def register_secret(value: str) -> None:
    """Make an exact secret value redacted everywhere, wherever it appears."""
    if value and len(value) >= 6:
        with _lock:
            _known.add(value)


def redact(text: str) -> str:
    with _lock:
        known = sorted(_known, key=len, reverse=True)
    for value in known:
        text = text.replace(value, REDACTED)
    text = _PATTERNS[0].sub(lambda m: m.group(1) + REDACTED, text)
    text = _PATTERNS[1].sub(lambda m: m.group(1) + REDACTED, text)
    text = _PATTERNS[2].sub(lambda m: m.group(1) + REDACTED + m.group(2), text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def install_log_redaction() -> None:
    f = RedactingFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(f)
