"""What is rendered, how busy it is, and when the panel last collected it."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InkFrameConfigEntry
from .entity import InkFrameEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: InkFrameConfigEntry, add: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    add([
        PhotoSensor(c),
        BusynessSensor(c),
        LastPanelFetchSensor(c),
        RejectedSensor(c),
        LastErrorSensor(c),
    ])


def _ts(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


class PhotoSensor(InkFrameEntity, SensorEntity):
    _attr_name = "Photo"
    _attr_icon = "mdi:image"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "photo")

    @property
    def native_value(self) -> str | None:
        name = self.coordinator.current.get("name")
        return str(name)[:255] if name else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cur = self.coordinator.current
        return {
            "taken": cur.get("taken"),
            "source": cur.get("source"),
            "busyness": cur.get("busyness"),
            "asset_id": cur.get("asset_id"),
            "generation": (self.coordinator.data or {}).get("generation"),
            "rendered_at": _ts(cur.get("rendered_at")),
        }


class BusynessSensor(InkFrameEntity, SensorEntity):
    """Mean absolute Laplacian of the chosen photo. Lower dithers cleaner."""

    _attr_name = "Busyness"
    _attr_icon = "mdi:blur"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "busyness")

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.current.get("busyness")
        return float(value) if isinstance(value, (int, float)) else None


class LastPanelFetchSensor(InkFrameEntity, SensorEntity):
    """When the panel itself last collected a frame -- its last wake."""

    _attr_name = "Last panel fetch"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "last_panel_fetch")

    @property
    def native_value(self) -> datetime | None:
        return _ts((self.coordinator.data or {}).get("panel_fetched_at"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {"panel_generation": data.get("panel_fetched_generation"),
                "rendered_generation": data.get("generation")}


class RejectedSensor(InkFrameEntity, SensorEntity):
    """Of the candidates scored for the current photo, how many were too busy.
    A high number means the source is mostly foliage and the threshold is
    doing real work; zero for weeks means it could be tightened."""

    _attr_name = "Candidates rejected"
    _attr_icon = "mdi:filter-remove"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "candidates_rejected")

    @property
    def native_value(self) -> int | None:
        value = self.coordinator.current.get("candidates_too_busy")
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"candidates_scored": self.coordinator.current.get("candidates_scored")}


class LastErrorSensor(InkFrameEntity, SensorEntity):
    _attr_name = "Last error"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "last_error")

    @property
    def native_value(self) -> str:
        err = (self.coordinator.data or {}).get("last_error")
        return str(err)[:255] if err else "none"
