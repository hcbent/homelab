"""Configuration management: the inventory and, later, the Ansible runner.

Named configmgmt, not config, because app/config.py already holds the settings module.
"""
from .inventory import (
    InventoryError,
    InventoryInput,
    ephemeral_inventory,
    inventory_json,
    render_inventory,
)

__all__ = ["InventoryError", "InventoryInput", "ephemeral_inventory", "inventory_json",
           "render_inventory"]
