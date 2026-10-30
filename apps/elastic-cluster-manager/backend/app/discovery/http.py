"""Shared read-only HTTP plumbing. Discovery clients can only GET."""
import ssl

import httpx


class DiscoveryError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def build_client(base_url: str, headers: dict, *, verify: bool, ca_pem: str | None,
                 transport: httpx.BaseTransport | None, timeout: float = 15.0) -> httpx.Client:
    tls: ssl.SSLContext | bool = verify
    if verify and ca_pem:
        tls = ssl.create_default_context(cadata=ca_pem)
    return httpx.Client(base_url=base_url, headers=headers, verify=tls, transport=transport,
                        timeout=timeout)


def get_json(client: httpx.Client, path: str, what: str):
    from app.crypto import redact

    try:
        r = client.get(path)
    except httpx.HTTPError as e:
        raise DiscoveryError(redact(f"{what}: {e}")) from e
    if r.status_code >= 400:
        raise DiscoveryError(redact(f"{what}: HTTP {r.status_code}"), r.status_code)
    return r.json()
