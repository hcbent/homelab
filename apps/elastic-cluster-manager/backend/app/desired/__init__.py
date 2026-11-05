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
from .versions import (
    ArtifactsApiCatalog,
    CatalogError,
    StaticCatalog,
    Version,
    VersionCatalog,
    available_versions,
    check_target_version,
    check_upgrade,
)

__all__ = [
    "ArtifactsApiCatalog",
    "CatalogError",
    "DesiredState",
    "NodeSpec",
    "RolesMode",
    "StaticCatalog",
    "TopologyPreset",
    "Version",
    "VersionCatalog",
    "available_versions",
    "build_desired_state",
    "check_target_version",
    "check_upgrade",
    "default_heap_mb",
    "discovery_settings",
    "expand_preset",
    "node_settings",
    "render_node_roles",
    "warnings",
]
