"""Build discovery clients from stored configuration. Tests override `transport`."""
import httpx
from sqlalchemy.orm import Session

from app import crypto
from app.discovery.es import ESClient
from app.discovery.proxmox import ProxmoxClient
from app.models import Cluster, Credential, ProxmoxConnection

# Test hook: a transport that serves recorded fixtures instead of real network calls.
transport: httpx.BaseTransport | None = None


def proxmox_client(db: Session, conn: ProxmoxConnection) -> ProxmoxClient:
    secret = crypto.decrypt(db.get(Credential, conn.credential_id).ciphertext)
    return ProxmoxClient(conn.api_url, conn.token_id, secret, verify=conn.tls_verify,
                         ca_pem=conn.tls_ca_pem, transport=transport)


def es_client(db: Session, cluster: Cluster, url: str) -> ESClient:
    key = crypto.decrypt(db.get(Credential, cluster.credential_id).ciphertext)
    return ESClient(url, key, verify=cluster.tls_verify, ca_pem=cluster.tls_ca_pem,
                    transport=transport)
