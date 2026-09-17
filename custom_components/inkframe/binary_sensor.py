"""Rendered is not displayed."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InkFrameConfigEntry
from .entity import InkFrameEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: InkFrameConfigEntry, add: AddEntitiesCallback
) -> None:
    add([OnPanelSensor(entry.runtime_data)])


class OnPanelSensor(InkFrameEntity, BinarySensorEntity):
    """On when the panel has fetched the generation currently rendered.

    E-paper holds its last image with no power, so a photo the panel never
    collected looks identical to one hanging on the wall. This is the only
    entity that can tell them apart; everything else describes the server.
    """

    _attr_name = "On panel"
    _attr_icon = "mdi:monitor-dashboard"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "on_panel")

    @property
    def is_on(self) -> bool | None:
        value = (self.coordinator.data or {}).get("on_panel")
        return bool(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {"panel_generation": data.get("panel_fetched_generation"),
                "rendered_generation": data.get("generation")}
