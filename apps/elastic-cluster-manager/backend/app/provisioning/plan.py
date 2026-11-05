"""Reading a Terraform plan and deciding whether it is safe to apply.

The rules mirror ARCHITECTURE sections 4 and 7 and the Phase 7 adoption rule: an operation may only do what its
kind allows. A create never deletes or replaces anything. An update never deletes or replaces unless the user
explicitly allowed it. A destroy only deletes. An adoption import must show no change at all.
"""
from dataclasses import dataclass, field

CREATE, UPDATE, DELETE, NOOP, READ = "create", "update", "delete", "no-op", "read"

# What each operation kind is allowed to do. Anything else makes the plan unsafe to apply.
ALLOWED: dict[str, frozenset[str]] = {
    "create": frozenset({CREATE}),
    "update": frozenset({CREATE, UPDATE}),
    "destroy": frozenset({DELETE}),
    "import": frozenset(),  # adoption: the plan must be a no-op
}


@dataclass
class ResourceChange:
    address: str
    action: str  # create, update, delete, replace, no-op or read


@dataclass
class PlanSummary:
    changes: list[ResourceChange] = field(default_factory=list)

    def count(self, action: str) -> int:
        return sum(1 for c in self.changes if c.action == action)

    @property
    def adds(self) -> int:
        return self.count(CREATE)

    @property
    def updates(self) -> int:
        return self.count(UPDATE)

    @property
    def deletes(self) -> int:
        return self.count(DELETE)

    @property
    def replaces(self) -> int:
        return self.count("replace")

    @property
    def is_empty(self) -> bool:
        return not any(c.action not in (NOOP, READ) for c in self.changes)

    def to_json(self) -> dict:
        return {"adds": self.adds, "updates": self.updates, "deletes": self.deletes,
                "replaces": self.replaces,
                "changes": [{"address": c.address, "action": c.action} for c in self.changes
                            if c.action not in (NOOP, READ)]}


def _action(actions: list[str]) -> str:
    """Terraform reports a replacement as both create and delete, in either order."""
    if CREATE in actions and DELETE in actions:
        return "replace"
    return actions[0] if actions else NOOP


def summarize_plan(plan_json: dict) -> PlanSummary:
    """Summarise the output of `terraform show -json <planfile>`."""
    changes = [
        ResourceChange(rc["address"], _action(rc.get("change", {}).get("actions", [])))
        for rc in plan_json.get("resource_changes", [])
    ]
    return PlanSummary(sorted(changes, key=lambda c: c.address))


def check_plan_safety(summary: PlanSummary, operation_kind: str) -> list[str]:
    """Why this plan must not be applied for this kind of operation. Empty means it is safe."""
    if operation_kind not in ALLOWED:
        return [f"unknown operation kind {operation_kind!r}"]
    allowed = ALLOWED[operation_kind]
    problems = []
    for c in summary.changes:
        if c.action in (NOOP, READ) or c.action in allowed:
            continue
        verb = {"replace": "would replace (destroy and recreate)", "delete": "would delete",
                "update": "would change", "create": "would create"}.get(c.action, f"would {c.action}")
        problems.append(f"{operation_kind} must not touch existing resources, but the plan {verb} {c.address}")
    if operation_kind == "import" and not summary.is_empty:
        problems.append("adoption needs a plan with no changes at all")
    return problems
