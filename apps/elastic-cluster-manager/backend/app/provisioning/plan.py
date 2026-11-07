"""Reading a Terraform plan and deciding whether it is safe to apply.

The rules mirror ARCHITECTURE sections 4 and 7 and the Phase 7 adoption rule: an operation may only do what its
kind allows. A create never deletes or replaces anything. An update never deletes or replaces unless the user
explicitly allowed it. A destroy only deletes. An adoption import must show no change at all.
"""
import re
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


_NODE_INSTANCE = re.compile(r'^module\.node\["([^"]+)"\](?:\.|$)')


def node_of(address: str) -> str | None:
    """The node a resource belongs to: the instance name in `module.node["name"]`, matched exactly so `name-1` is
    never mistaken for `name-10`. None for anything that is not inside a node's module."""
    m = _NODE_INSTANCE.match(address)
    return m.group(1) if m else None


def check_removal_plan(summary: PlanSummary, removing: frozenset[str]) -> list[str]:
    """Why a plan to remove these nodes must not be applied. Empty means it deletes exactly the machines asked for.

    It may delete resources of the named nodes and change (never create or replace) anything else, and it must delete
    every named node: a plan that leaves one out would, once approved, drop the node from the cluster's record while its
    machine still ran."""
    problems: list[str] = []
    deleted: set[str] = set()
    for c in summary.changes:
        if c.action in (NOOP, READ):
            continue
        node = node_of(c.address)
        if c.action == DELETE and node in removing:
            deleted.add(node)
        elif c.action == UPDATE:
            continue
        else:
            verb = {"replace": "would replace (destroy and recreate)", "delete": "would delete",
                    "create": "would create"}.get(c.action, f"would {c.action}")
            problems.append(f"removing nodes must only delete the machines asked for, but the plan {verb} {c.address}")
    for name in sorted(removing - deleted):
        problems.append(f"the plan does not delete {name}, so approving it would not remove that machine")
    return problems


def check_rebuild_plan(summary: PlanSummary, rebuilding: frozenset[str]) -> list[str]:
    """Why a plan to rebuild these nodes must not be applied. Empty means it creates exactly the machines asked for.

    It may create the named nodes' resources and change (never delete or replace) anything else, and it must create every
    named node. A plan that leaves one out means its machine still exists in Terraform's state, and the steps that follow
    (they start the node and restart it on a configuration change) must never run against a live node."""
    problems: list[str] = []
    created: set[str] = set()
    for c in summary.changes:
        if c.action in (NOOP, READ):
            continue
        node = node_of(c.address)
        if c.action == CREATE and node in rebuilding:
            created.add(node)
        elif c.action == UPDATE:
            continue
        else:
            verb = {"replace": "would replace (destroy and recreate)", "delete": "would delete",
                    "create": "would create"}.get(c.action, f"would {c.action}")
            problems.append(f"rebuilding nodes must only create the machines asked for, but the plan {verb} {c.address}")
    for name in sorted(rebuilding - created):
        problems.append(f"the plan does not create a machine for {name}, so Terraform believes it exists; a node whose "
                        "machine exists is restarted, not rebuilt")
    return problems


def check_forget_plan(summary: PlanSummary, forgetting: frozenset[str]) -> list[str]:
    """Why a plan to forget these lost nodes must not be applied. Empty means it touches no machine at all.

    A node is forgotten only because its machine is already gone, which Terraform's refresh shows by dropping it from the
    state, so the plan has nothing to delete. A delete (of anything) means a machine still exists, and the way to take a
    live machine out is to remove it, which moves its data first."""
    problems: list[str] = []
    for c in summary.changes:
        if c.action in (NOOP, READ, UPDATE):
            continue
        node = node_of(c.address)
        verb = {"replace": "would replace (destroy and recreate)", "delete": "would delete",
                "create": "would create"}.get(c.action, f"would {c.action}")
        if c.action == DELETE and node in forgetting:
            problems.append(f"the plan {verb} {c.address}: the machine of {node} still exists, so use Remove nodes, "
                            "which moves its data off first")
        else:
            problems.append(f"forgetting nodes must not touch any machine, but the plan {verb} {c.address}")
    return problems


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
