"""Operations on a Kibana that exists, with no Terraform step (docs/DESIGN_KIBANA.md, slice 6b): setting the sign-in and restarting Kibana.

Like a rolling restart, the plan is a description of what will be done, made when the operator asked (lifecycle.plan_kibana_login,
lifecycle.plan_restart_kibana), and the digest the operator approves is a hash of it, so what is approved is exactly what runs.

The sign-in is a new, generated password for the `elastic` user. ECM keeps it encrypted as {username, current, pending, reset_at}. The order is
what keeps it from being lost: the new password is stored as *pending* before the cluster is asked to change anything, the playbook then sets it
and signs in with it to prove it works, and only then does ECM make it *current*. A reset that fails anywhere leaves the old password as
current, and a retry sets the same pending password again, which is safe to repeat.
"""
import copy
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, crypto
from app.configmgmt import AnsibleError, AnsibleRequest, AnsibleRunner, KibanaHost
from app.desired.kibana import kibana_of
from app.desired.models import DesiredState
from app.desired.network import NetworkProfile
from app.models import Cluster, Credential, Operation
from app.operations import AwaitingApproval, log
from app.provisioning.operation import ApplyRefused, kibana_credential_names
from app.provisioning.restart import plan_digest


def login_for_reveal(db: Session, cluster: Cluster) -> dict | None:
    """{username, password} of the sign-in ECM set, or None when it has set none that works. Only a password that was set and proved is shown:
    a pending one, from a reset that did not finish, never is."""
    row = db.scalar(select(Credential).where(Credential.name == kibana_credential_names(cluster.id)[2]))
    state = json.loads(crypto.decrypt(row.ciphertext)) if row is not None else {}
    if not state.get("current"):
        return None
    crypto.register_secret(state["current"])
    return {"username": state.get("username", "elastic"), "password": state["current"], "reset_at": state.get("reset_at")}


class KibanaOpFailed(Exception):
    """Kibana's sign-in or restart did not complete. The message says what is and is not changed, and what a retry does."""


class KibanaHandlers:
    def __init__(self, db: Session, op: Operation, make_ansible: Callable[[Callable[[str], None]], AnsibleRunner]):
        self.db, self.op = db, op
        self.ansible = make_ansible(lambda line: log(db, op.id, line, "ansible"))

    def handlers(self) -> dict[str, Callable[[], None]]:
        return {"plan": self.plan, "approval": self.approval, "kibana": self.run}

    def _fresh(self) -> Operation:
        self.db.refresh(self.op)
        return self.op

    def _change(self) -> dict:
        return self.op.params["change"]

    def plan(self) -> None:
        change = self._change()
        op = self._fresh()
        op.plan_digest = plan_digest(op.cluster_id, change)
        op.plan_summary = {"has_changes": True, "configure": change.get("describe")}
        self.db.commit()
        log(self.db, op.id, f"plan {op.plan_digest}: {change['kind']}")

    def approval(self) -> None:
        op = self._fresh()
        if op.approved_digest is None:
            raise AwaitingApproval()
        if op.approved_digest != op.plan_digest:
            raise ApplyRefused("the approval is for a different plan; plan again")

    # -- what the two operations share --

    def _credential(self, name: str) -> Credential | None:
        return self.db.scalar(select(Credential).where(Credential.name == name))

    def _store(self, kind: str, name: str, value: str) -> None:
        row = self._credential(name)
        if row is None:
            self.db.add(Credential(kind=kind, name=name, ciphertext=crypto.encrypt(value)))
        else:
            row.ciphertext, row.rotated_at = crypto.encrypt(value), datetime.now(UTC)
        self.db.commit()

    def _request(self, kind: str, **extra) -> AnsibleRequest:
        """The request every one of these makes: the machine, ECM's API key and the cluster's CA. The Elasticsearch nodes are the cluster's own."""
        cluster = self.db.get(Cluster, self.op.cluster_id)
        params = self.op.params
        api_key = self._credential(f"es-api-key-{cluster.id}")
        if api_key is None or not cluster.tls_ca_pem:
            raise KibanaOpFailed("ECM has no API key or CA certificate for this cluster, so it cannot ask the cluster anything. "
                                 "Nothing was changed")
        change = self._change()
        hosts = [KibanaHost(name=k.name, address=k.address, public_url=k.public_url)
                 for k in kibana_of(params) if k.name in change["kibana"]]
        if not hosts:
            raise KibanaOpFailed("this cluster no longer has the Kibana this was planned for. Nothing was changed")
        profile = NetworkProfile.model_validate(params["profile"])
        return AnsibleRequest(
            state=DesiredState.model_validate(params["state"]), addresses=params["addresses"], kind=kind,
            bootstrapped_at=cluster.bootstrapped_at, search_domain=profile.search_domain, kibana=hosts,
            es_api_key=crypto.decrypt(api_key.ciphertext), es_ca_pem=cluster.tls_ca_pem, **extra)

    def run(self) -> None:
        # What is about to run must be what was approved: the digest is recomputed from the parameters themselves, not just compared with the
        # one stored at plan time, so a plan changed after it was approved does not run.
        op = self._fresh()
        if op.approved_digest is None or op.approved_digest != plan_digest(op.cluster_id, self._change()):
            raise ApplyRefused("what is about to run is not the plan that was approved; plan again")
        kind = self._change()["kind"]
        if kind == "reset_login":
            self._reset_login()
        elif kind == "restart_kibana":
            self._restart()
        else:
            raise KibanaOpFailed(f"unknown Kibana operation {kind!r}")

    # -- the sign-in --

    def _reset_login(self) -> None:
        cluster = self.db.get(Cluster, self.op.cluster_id)
        name = kibana_credential_names(cluster.id)[2]
        held = self._credential(name)
        state = json.loads(crypto.decrypt(held.ciphertext)) if held is not None else {}
        # A pending password from an earlier attempt that did not finish is reused: the cluster may already have it.
        pending = state.get("pending") or secrets.token_urlsafe(24)
        crypto.register_secret(pending)
        if state.get("current"):
            crypto.register_secret(state["current"])
        self._store("es_kibana_login", name, json.dumps({"username": "elastic", "current": state.get("current"), "pending": pending,
                                                          "reset_at": state.get("reset_at")}))
        log(self.db, self.op.id, "the new password is stored (encrypted) as pending; now setting it on the cluster")
        left = ("The password that was current is unchanged in ECM's record, and the new one is kept as pending. Retry sets the same "
                "password again and checks it, which is safe to repeat")
        try:
            outcome = self.ansible.run(self._request("kibana_login", kibana_login_pass=pending))
        except (AnsibleError, KibanaOpFailed) as e:
            raise KibanaOpFailed(f"{e}. {left}") from e
        if not outcome.ok:
            raise KibanaOpFailed(f"{outcome.error or 'setting the password failed'}. {left}")
        now = datetime.now(UTC).isoformat()
        self._store("es_kibana_login", name, json.dumps({"username": "elastic", "current": pending, "pending": None, "reset_at": now}))
        audit.record(self.db, self.op.created_by or "worker", "kibana.login.set", "cluster", cluster.id, operation=self.op.id)
        log(self.db, self.op.id, "the elastic user's new password works and is stored; show it from the Kibana panel when it is needed")

    # -- restarting --

    def _restart(self) -> None:
        cluster = self.db.get(Cluster, self.op.cluster_id)
        change = self._change()
        log(self.db, self.op.id, "rewriting Kibana's configuration and restarting it")
        kept = "Kibana's configuration may already be rewritten; retry rewrites it and restarts again, which is safe to repeat"
        try:
            outcome = self.ansible.run(self._request("restart_kibana"))
        except (AnsibleError, KibanaOpFailed) as e:
            raise KibanaOpFailed(f"{e}. {kept}") from e
        if not outcome.ok:
            raise KibanaOpFailed(f"{outcome.error or 'restarting Kibana failed'}. {kept}")
        # Kibana now uses the nodes the cluster has, so that is what is on record (it decides whether the panel says it is out of date).
        desired = copy.deepcopy(cluster.desired)
        for k in desired.get("kibana") or []:
            info = change["kibana"].get(k["name"])
            if info is not None:
                k["es_hosts"] = list(info["es_hosts_after"])
        cluster.desired = desired
        self.db.commit()
        log(self.db, self.op.id, "Kibana restarted with the cluster's current nodes and reports itself available")
