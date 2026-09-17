"""The camera filter, and one Include switch per eligible person."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InkFrameConfigEntry
from .entity import InkFrameEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: InkFrameConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [RequireCameraSwitch(coordinator),
                                   PortraitsSwitch(coordinator)]
    # One switch per person who has enough photos. Home Assistant has no
    # multi-select entity; a row of switches is the native way to say "these
    # people". Someone who becomes eligible later appears after a reload.
    for name, info in sorted(coordinator.people.items()):
        if isinstance(info, dict) and info.get("eligible"):
            entities.append(IncludePersonSwitch(coordinator, name))
    add(entities)


class RequireCameraSwitch(InkFrameEntity, SwitchEntity):
    """On: only assets with a camera make in EXIF -- no screenshots, memes or
    downloads. Off: any landscape image. Default on, for good reason: the
    cleanest-dithering image in the first sample was a meme."""

    _attr_name = "Photographs only"
    _attr_icon = "mdi:camera"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "require_camera")

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.settings.get("require_camera")
        return bool(value) if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_settings(require_camera=1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_settings(require_camera=0)


class PortraitsSwitch(InkFrameEntity, SwitchEntity):
    """On: portraits are cropped to fit the landscape panel, with the window
    placed on the faces Immich found. Off: they are skipped entirely.

    The server setting is `landscape_only`, which is the inverse, because it
    describes what the filter does. This entity is named for what a person
    wants: whether portraits appear on the wall.
    """

    _attr_name = "Portraits"
    _attr_icon = "mdi:crop-portrait"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "portraits")

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.settings.get("landscape_only")
        return (not value) if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_settings(landscape_only=0)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_settings(landscape_only=1)


class IncludePersonSwitch(InkFrameEntity, SwitchEntity):
    """Is this person part of the People source? Only matters while Source is
    People; kept regardless so the choice is there when People is selected."""

    _attr_icon = "mdi:account-check"

    def __init__(self, coordinator, person: str) -> None:
        super().__init__(coordinator, f"include_{person.lower().replace(' ', '_')}")
        self._person = person
        self._attr_name = f"Include {person}"

    @property
    def is_on(self) -> bool:
        included = (self.coordinator.data or {}).get("source_people") or []
        return self._person in included

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.coordinator.people.get(self._person) or {}
        return {"landscape_photos": info.get("landscape")}

    async def _set(self, include: bool) -> None:
        current = list((self.coordinator.data or {}).get("source_people") or [])
        if include and self._person not in current:
            current.append(self._person)
        if not include and self._person in current:
            current.remove(self._person)
        # Only the list changes; the active mode is left alone.
        mode, _, _ = self.coordinator.source.partition(":")
        person = self.coordinator.source.partition(":")[2] if mode == "person" else ""
        await self.coordinator.async_set_source(mode or "random", person=person,
                                                people=current)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
