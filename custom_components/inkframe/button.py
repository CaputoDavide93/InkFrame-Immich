"""Render a new photo now, and re-read the album list."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InkFrameConfigEntry
from .entity import InkFrameEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: InkFrameConfigEntry, add: AddEntitiesCallback
) -> None:
    add([NextPhotoButton(entry.runtime_data),
         RefreshAlbumsButton(entry.runtime_data)])


class NextPhotoButton(InkFrameEntity, ButtonEntity):
    """Renders on the server immediately. The glass changes at the panel's
    next wake, which may be days away -- watch `On panel`."""

    _attr_name = "Next photo"
    _attr_icon = "mdi:image-refresh"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "next_photo")

    async def async_press(self) -> None:
        await self.coordinator.async_next_photo()


class RefreshAlbumsButton(InkFrameEntity, ButtonEntity):
    """Ask Immich for its albums now, instead of waiting for the daily count.

    An album made in Immich is usable immediately by name, but the picker here
    is filled from a cache that refreshes once a day. Without this button the
    honest answer to "I made an album, where is it?" was "tomorrow".
    """

    _attr_name = "Refresh albums"
    _attr_icon = "mdi:image-album"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "refresh_albums")

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_albums()
