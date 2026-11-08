"""Restarting nodes of a built cluster as an operation (docs/DESIGN_RECOVERY.md, slice 5b).

There is no Terraform step. The plan is the ordered list of nodes and what is done to each, made when the operator asked
(lifecycle.plan_restart_nodes), and the digest the operator approves is a hash of that list, so what is approved is exactly what
runs. The restart itself is the rolling restart playbook following that list: it asks Elasticsearch about the cluster with ECM's API
key and asks Proxmox to restart or start each VM with the Terraform token, one node at a time, and a retry skips every node that
has been restarted since the operation began.
"""
import hashlib
import json
from collections.abc import Callable
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crypto
from app.configmgmt import AnsibleError, AnsibleRequest, AnsibleRunner
from app.desired.models import DesiredState
from app.desired.network import NetworkProfile
from app.discovery import factory, proxmox
from app.discovery.http import DiscoveryError
from app.models import Cluster, Credential, Operation
from app.operations import AwaitingApproval, log
from app.provisioning.operation import ApplyRefused, PreflightFailed, _connection
from app.provisioning.ownership import foreign_machines


class RestartFailed(Exception):
    """A node could not be restarted or started. Nodes already done stay done."""


def plan_digest(cluster_id: str | None, change: dict) -> str:
    """What the operator approves: a hash of the cluster and the plan, so a different plan has a different digest."""
    text = json.dumps({"cluster": cluster_id, "change": change}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


class RestartHandlers:
    def __init__(self, db: Session, op: Operation, make_ansible: Callable[[Callable[[str], None]], AnsibleRunner]):
        self.db, self.op = db, op
        self.ansible = make_ansible(lambda line: log(db, op.id, line, "ansible"))

    def handlers(self) -> dict[str, Callable[[], None]]:
        return {"plan": self.plan, "approval": self.approval, "restart": self.restart}

    def _fresh(self) -> Operation:
        self.db.refresh(self.op)
        return self.op

    def _change(self) -> dict:
        return self.op.params["change"]

    def plan(self) -> None:
        change = self._change()
        actions = [info["action"] for info in change["nodes"].values()]
        op = self._fresh()
        op.plan_digest = plan_digest(op.cluster_id, change)
        op.plan_summary = {"restart": actions.count("restart"), "start": actions.count("start"), "has_changes": True,
                           "configure": change.get("describe")}
        self.db.commit()
        log(self.db, op.id, f"plan {op.plan_digest}: {actions.count('restart')} to restart, {actions.count('start')} to start")

    def approval(self) -> None:
        op = self._fresh()
        if op.approved_digest is None:
            raise AwaitingApproval()
        if op.approved_digest != op.plan_digest:
            raise ApplyRefused("the approval is for a different plan; plan again")

    def _proxmox_token(self) -> tuple[str, str]:
        conn = _connection(self.db, self.op.params)
        separate = bool(conn.terraform_credential_id and conn.terraform_token_id)
        credential_id = conn.terraform_credential_id if separate else conn.credential_id
        token_id = conn.terraform_token_id if separate else conn.token_id
        return token_id, crypto.decrypt(self.db.get(Credential, credential_id).ciphertext)

    def _preflight(self, token_id: str, secret: str) -> None:
        params = self.op.params
        conn = _connection(self.db, params)
        try:
            perms = factory.proxmox_client_for(conn, token_id, secret).permissions()
        except DiscoveryError as e:
            raise PreflightFailed(f"could not check the rights of the token that restarts the machines ({e}); retry when Proxmox "
                                  "is reachable") from e
        problems = proxmox.preflight_problems(perms, pool_id=params.get("pool_id", "ecm"),
                                              datastore=params.get("datastore_id", "tank"), template_vmid=None,
                                              creating=False, restarting=True)
        if problems:
            raise PreflightFailed(f"the token that restarts the machines is missing rights: {'; '.join(problems)}. Fix its "
                                  "permissions in Proxmox, then retry")

    def restart(self) -> None:
        """Restart or start the nodes in the plan, one at a time (playbooks/rolling_restart.yml with the plan). Checked again first:
        that the machines are still ECM's and that the token may restart them."""
        op, params, change = self._fresh(), self.op.params, self._change()
        mine = {"proxmox_connection_id": params.get("proxmox_connection_id"),
                "vm_ids": {n: info["vm_id"] for n, info in change["nodes"].items()}}
        foreign = foreign_machines(self.db, mine)
        if foreign:
            raise ApplyRefused("a restart only touches machines ECM created, and these are not: " + ", ".join(foreign))
        cluster = self.db.get(Cluster, op.cluster_id)
        conn = _connection(self.db, params)
        api_key = self.db.scalar(select(Credential).where(Credential.name == f"es-api-key-{cluster.id}"))
        if api_key is None or not cluster.tls_ca_pem:
            raise RestartFailed("ECM has no API key or CA certificate for this cluster, so it cannot check the cluster's health "
                                "between restarts. Nothing was restarted")
        token_id, token_secret = self._proxmox_token()
        self._preflight(token_id, token_secret)
        started = op.started_at if op.started_at.tzinfo else op.started_at.replace(tzinfo=UTC)
        profile = NetworkProfile.model_validate(params["profile"])
        request = AnsibleRequest(
            state=DesiredState.model_validate(params["state"]), addresses=params["addresses"], kind="restart",
            bootstrapped_at=cluster.bootstrapped_at, search_domain=profile.search_domain,
            vm_ids=params["vm_ids"], placement=params["placement"],
            es_api_key=crypto.decrypt(api_key.ciphertext), es_ca_pem=cluster.tls_ca_pem,
            pve_api_url=conn.api_url, pve_token_id=token_id, pve_token_secret=token_secret,
            pve_ca_pem=conn.tls_ca_pem, pve_verify_tls=conn.tls_verify,
            restart_plan=[{"name": n, "action": change["nodes"][n]["action"]} for n in change["order"]],
            restart_present=list(change["present"]), restart_since=int(started.timestamp()))
        log(self.db, op.id, f"restarting, in this order: {', '.join(change['order'])}")
        resumes = ("Nodes already restarted stay restarted. Retry plans again and needs a new approval; it skips every node that "
                   "has been restarted since this operation began")
        try:
            outcome = self.ansible.run(request)
        except AnsibleError as e:
            raise RestartFailed(f"{e}. {resumes}") from e
        if not outcome.ok:
            raise RestartFailed(f"{outcome.error or 'the restart failed'}. {resumes}")
        log(self.db, op.id, "every node in the plan was restarted and the cluster is green")
