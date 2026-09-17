"""Render a new photo now."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InkFrameConfigEntry
from .entity import InkFrameEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: InkFrameConfigEntry, add: AddEntitiesCallback
) -> None:
    add([NextPhotoButton(entry.runtime_data)])


class NextPhotoButton(InkFrameEntity, ButtonEntity):
    """Renders on the server immediately. The glass changes at the panel's
    next wake, which may be days away -- watch `On panel`."""

    _attr_name = "Next photo"
    _attr_icon = "mdi:image-refresh"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "next_photo")

    async def async_press(self) -> None:
        await self.coordinator.async_next_photo()
