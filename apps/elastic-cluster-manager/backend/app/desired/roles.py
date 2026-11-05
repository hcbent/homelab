"""What the generated Elasticsearch configuration says about roles and bootstrapping.

These functions return the exact settings a renderer must emit. They exist as separate pure functions so the
two rules that are easiest to get wrong are unit-tested directly:

  * node.roles: omitted for default roles, [] for coordinating-only, an explicit list only for custom.
  * cluster.initial_master_nodes: rendered only when creating a cluster that has never bootstrapped.
"""
from datetime import datetime

from .models import DesiredState, NodeSpec, RolesMode

OMIT = None  # sentinel: do not render the setting at all


def render_node_roles(node: NodeSpec) -> list[str] | None:
    """The value of node.roles, or None when the setting must be left out."""
    if node.roles_mode == RolesMode.default:
        return OMIT
    if node.roles_mode == RolesMode.coordinating:
        return []
    return sorted(node.roles)


def node_settings(node: NodeSpec, state: DesiredState) -> dict:
    """Per-node elasticsearch.yml settings that ECM generates."""
    settings: dict = {"cluster.name": state.name, "node.name": node.name}
    roles = render_node_roles(node)
    if roles is not OMIT:
        settings["node.roles"] = roles
    settings.update(node.extra_settings)
    return settings


def discovery_settings(
    state: DesiredState, *, operation_kind: str, bootstrapped_at: datetime | None
) -> dict:
    """Cluster-formation settings for one run.

    A single-node cluster always uses discovery.type single-node. A multi-node cluster gets
    cluster.initial_master_nodes only on the create operation and only while bootstrapped_at is unset.
    After the first successful bootstrap the setting must never be rendered again, because a stale value can
    split a cluster or block a node from joining.
    """
    if state.is_single_node:
        return {"discovery.type": "single-node"}
    settings: dict = {"discovery.seed_hosts": [n.name for n in state.master_eligible_nodes]}
    if operation_kind == "create" and bootstrapped_at is None:
        # Only electable nodes can win the first election, so voting_only nodes are left out.
        settings["cluster.initial_master_nodes"] = [n.name for n in state.nodes if n.is_electable]
    return settings
