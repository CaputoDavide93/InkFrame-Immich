"""Shared base so every entity hangs off the one device."""
from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import InkFrameCoordinator


class InkFrameEntity(CoordinatorEntity[InkFrameCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: InkFrameCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = coordinator.device_info
