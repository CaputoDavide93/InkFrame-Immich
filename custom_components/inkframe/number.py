"""Render settings and the recency window."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InkFrameConfigEntry
from .const import MAX_RECENT_DAYS, MIN_RECENT_DAYS, NUMBER_SETTINGS
from .entity import InkFrameEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: InkFrameConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[NumberEntity] = [
        SettingNumber(coordinator, key, name, lo, hi, step, category, icon, unit)
        for key, name, lo, hi, step, category, icon, unit in NUMBER_SETTINGS
    ]
    entities.append(RecentDaysNumber(coordinator))
    add(entities)


class SettingNumber(InkFrameEntity, NumberEntity):
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, key, name, lo, hi, step, category, icon, unit) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = step
        self._attr_icon = icon
        if unit:
            self._attr_native_unit_of_measurement = unit
        if category == "config":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.settings.get(self._key)
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_settings(**{self._key: value})


class RecentDaysNumber(InkFrameEntity, NumberEntity):
    """The N in "Recent". Changing it only matters while Recent is selected,
    but it is kept so the value is there when Recent is chosen."""

    _attr_name = "Recent window"
    _attr_icon = "mdi:calendar-range"
    _attr_native_min_value = MIN_RECENT_DAYS
    _attr_native_max_value = MAX_RECENT_DAYS
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "d"
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "recent_days")

    @property
    def native_value(self) -> float | None:
        days = (self.coordinator.data or {}).get("source_days")
        return float(days) if isinstance(days, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        # Only the days change; the active mode is left alone.
        mode, _, rest = self.coordinator.source.partition(":")
        person = rest if mode == "person" else ""
        await self.coordinator.async_set_source(mode or "random", person=person,
                                                days=int(value))
