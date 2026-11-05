"""Desired-state models, validation, role rules and topology presets (pure; no I/O)."""
from .models import (
    DesiredState,
    NodeSpec,
    RolesMode,
    TopologyPreset,
    default_heap_mb,
    warnings,
)
from .presets import build_desired_state, expand_preset
from .roles import discovery_settings, node_settings, render_node_roles

__all__ = [
    "DesiredState", "NodeSpec", "RolesMode", "TopologyPreset", "build_desired_state",
    "default_heap_mb", "discovery_settings", "expand_preset", "node_settings",
    "render_node_roles", "warnings",
]
