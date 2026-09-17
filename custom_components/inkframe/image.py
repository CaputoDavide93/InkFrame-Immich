"""The frame itself, as Home Assistant will show it."""
from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InkFrameConfigEntry
from .entity import InkFrameEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: InkFrameConfigEntry, add: AddEntitiesCallback
) -> None:
    add([PreviewImage(hass, entry.runtime_data)])


class PreviewImage(InkFrameEntity, ImageEntity):
    """The 1-bit frame the panel will collect, straight from the renderer.

    Fetches /preview.png and never /frame.png: only the panel's own fetch may
    count as the photo having reached the glass, and the server tracks that by
    path. `image_last_updated` follows the render timestamp, so the frontend
    re-fetches exactly when a new generation exists and not on every poll.
    """

    _attr_name = "Preview"
    _attr_content_type = "image/png"

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        InkFrameEntity.__init__(self, coordinator, "preview")
        ImageEntity.__init__(self, hass)

    @property
    def image_last_updated(self) -> datetime | None:
        rendered = self.coordinator.current.get("rendered_at")
        if isinstance(rendered, (int, float)) and rendered > 0:
            return datetime.fromtimestamp(rendered, tz=timezone.utc)
        return None

    async def async_image(self) -> bytes | None:
        try:
            return await self.coordinator.async_preview()
        except Exception:  # noqa: BLE001 - a missing preview is not a dead integration
            return None
