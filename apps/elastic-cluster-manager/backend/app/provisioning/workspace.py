"""A per-cluster Terraform working directory, and the link between an approved plan and its configuration.

A plan is only safe to apply if nothing changed since it was made. The workspace stores the digest of the
rendered configuration and the hash of the plan file next to the plan, and refuses to apply when either differs.
That also catches a stale plan after a failed apply, which Terraform itself rejects.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.provisioning.plan import PlanSummary
from app.provisioning.render import config_digest

PLAN_FILE = "plan.tfplan"
META_FILE = "plan.meta.json"
_CLUSTER_ID = re.compile(r"^[a-f0-9]{8,32}$")


class WorkspaceError(Exception):
    """The workspace is not in a state that allows the requested step."""


class StalePlan(WorkspaceError):
    """The stored plan no longer matches the configuration or the plan file on disk."""


@dataclass
class StoredPlan:
    operation_kind: str
    digest: str  # of the rendered configuration
    plan_sha256: str  # of the plan file
    files: list[str]
    summary: dict
    created_at: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Workspace:
    def __init__(self, directory: Path):
        self.dir = directory

    @property
    def plan_path(self) -> Path:
        return self.dir / PLAN_FILE

    @property
    def meta_path(self) -> Path:
        return self.dir / META_FILE

    def _read_config(self, files: list[str]) -> dict[str, str]:
        return {name: (self.dir / name).read_text() for name in files}

    def save_plan(self, operation_kind: str, rendered: dict[str, str], summary: PlanSummary) -> StoredPlan:
        """Record the plan that was just made, bound to the configuration that produced it."""
        if not self.plan_path.exists():
            raise WorkspaceError("there is no plan file to record")
        meta = StoredPlan(
            operation_kind=operation_kind, digest=config_digest(rendered),
            plan_sha256=_sha256(self.plan_path), files=sorted(rendered), summary=summary.to_json(),
            created_at=datetime.now(UTC).isoformat())
        self.meta_path.write_text(json.dumps(meta.__dict__, indent=2, sort_keys=True) + "\n")
        return meta

    def load_plan(self) -> StoredPlan:
        if not self.meta_path.exists():
            raise WorkspaceError("no approved plan is stored for this workspace")
        return StoredPlan(**json.loads(self.meta_path.read_text()))

    def verify_for_apply(self, expected_kind: str | None = None) -> StoredPlan:
        """Raise StalePlan unless the plan on disk is exactly the one that was stored.

        Checks the operation kind, that the plan file is unchanged, and that the configuration files on disk
        still hash to the digest taken when the plan was made.
        """
        meta = self.load_plan()
        if expected_kind is not None and meta.operation_kind != expected_kind:
            raise StalePlan(f"the stored plan is for a {meta.operation_kind} operation, not {expected_kind}")
        if not self.plan_path.exists():
            raise StalePlan("the plan file is missing; plan again")
        if _sha256(self.plan_path) != meta.plan_sha256:
            raise StalePlan("the plan file changed after it was approved; plan again")
        try:
            current = self._read_config(meta.files)
        except FileNotFoundError as exc:
            raise StalePlan(f"a configuration file is missing ({exc.filename}); plan again") from exc
        if config_digest(current) != meta.digest:
            raise StalePlan("the configuration changed after the plan was made; plan again")
        return meta

    def discard_plan(self) -> None:
        """Drop the stored plan (after an apply, or before re-planning). State and .terraform are kept."""
        for path in (self.plan_path, self.meta_path):
            path.unlink(missing_ok=True)


def open_workspace(root: Path, cluster_id: str, rendered: dict[str, str]) -> Workspace:
    """Write the rendered files into <root>/<cluster_id>/tf and return the workspace.

    Only the rendered files are touched. State, the provider cache (.terraform) and any stored plan stay, so a
    re-render never loses state. Files that were rendered before but are no longer are removed.
    """
    if not _CLUSTER_ID.match(cluster_id):
        raise WorkspaceError("cluster_id must be 8 to 32 lowercase hex characters")
    base = (root / cluster_id / "tf").resolve()
    for name in rendered:
        target = (base / name).resolve()
        if base not in target.parents:
            raise WorkspaceError(f"refusing to write outside the workspace: {name}")
    base.mkdir(parents=True, exist_ok=True)
    previous = base / ".rendered.json"
    if previous.exists():
        for name in json.loads(previous.read_text()):
            if name not in rendered:
                (base / name).unlink(missing_ok=True)
    for name, content in rendered.items():
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(content)
        tmp.replace(target)
    previous.write_text(json.dumps(sorted(rendered)))
    return Workspace(base)
