"""Build discovery clients from stored configuration. Tests override `transport`."""
import httpx
from sqlalchemy.orm import Session

from app import crypto
from app.discovery.es import ESClient
from app.discovery.proxmox import ProxmoxClient
from app.models import Cluster, Credential, ProxmoxConnection

# Test hook: a transport that serves recorded fixtures instead of real network calls.
transport: httpx.BaseTransport | None = None


def proxmox_client_for(conn: ProxmoxConnection, token_id: str, secret: str) -> ProxmoxClient:
    """A client for this connection's endpoint and TLS settings with an explicit token (to test a new one)."""
    return ProxmoxClient(conn.api_url, token_id, secret, verify=conn.tls_verify, ca_pem=conn.tls_ca_pem,
                         transport=transport)


def proxmox_client(db: Session, conn: ProxmoxConnection) -> ProxmoxClient:
    secret = crypto.decrypt(db.get(Credential, conn.credential_id).ciphertext)
    return proxmox_client_for(conn, conn.token_id, secret)


def es_client(db: Session, cluster: Cluster, url: str) -> ESClient:
    key = crypto.decrypt(db.get(Credential, cluster.credential_id).ciphertext)
    return ESClient(url, key, verify=cluster.tls_verify, ca_pem=cluster.tls_ca_pem,
                    transport=transport)
