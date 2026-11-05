"""Topology presets: expand a name into a list of NodeSpec.

Presets only choose roles, counts and default sizing. Everything stays overridable, and the result still passes
through the normal DesiredState validation.
"""
from .models import DesiredState, NodeSpec, RolesMode, TopologyPreset


def _name(cluster: str, index: int) -> str:
    return f"{cluster}-{index:02d}"


def expand_preset(
    preset: TopologyPreset,
    cluster_name: str,
    *,
    data_nodes: int = 3,
    coordinating_nodes: int = 0,
) -> list[NodeSpec]:
    """Build the node list for a preset.

    single_node        one node with default roles
    three_node         three nodes, all default roles (each is master-eligible and holds data)
    dedicated_masters  three master-only nodes plus `data_nodes` data and ingest nodes
    """
    if preset == TopologyPreset.single_node:
        nodes = [NodeSpec(name=_name(cluster_name, 1), data_disk_gb=100)]
    elif preset == TopologyPreset.three_node:
        nodes = [NodeSpec(name=_name(cluster_name, i), data_disk_gb=100) for i in (1, 2, 3)]
    elif preset == TopologyPreset.dedicated_masters:
        if data_nodes < 1:
            raise ValueError("dedicated_masters needs at least one data node")
        nodes = [
            NodeSpec(name=_name(cluster_name, i), roles_mode=RolesMode.custom, roles=["master"],
                     cores=2, ram_mb=4096)
            for i in (1, 2, 3)
        ]
        nodes += [
            NodeSpec(name=_name(cluster_name, 3 + i), roles_mode=RolesMode.custom,
                     roles=["data", "ingest"], data_disk_gb=100)
            for i in range(1, data_nodes + 1)
        ]
    else:
        raise ValueError("the 'custom' preset has no template; supply the nodes directly")

    start = len(nodes) + 1
    nodes += [
        NodeSpec(name=_name(cluster_name, start + i), roles_mode=RolesMode.coordinating,
                 cores=2, ram_mb=4096)
        for i in range(coordinating_nodes)
    ]
    return nodes


def build_desired_state(
    preset: TopologyPreset,
    cluster_name: str,
    version: str,
    *,
    data_nodes: int = 3,
    coordinating_nodes: int = 0,
    network_profile: str | None = None,
) -> DesiredState:
    return DesiredState(
        name=cluster_name,
        version=version,
        topology_preset=preset,
        nodes=expand_preset(preset, cluster_name, data_nodes=data_nodes,
                            coordinating_nodes=coordinating_nodes),
        network_profile=network_profile,
    )
