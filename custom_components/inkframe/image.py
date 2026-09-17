"""Two pictures: what is on the glass, and what is waiting to replace it.

They are usually the same. They differ from the moment a new photo is rendered
until the panel next wakes and collects it, which on a weekly cycle can be days
-- and that gap is the whole reason for having two. E-paper holds its last
image with no power, so nothing about the wall tells you a newer photo exists.
"""
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
    coordinator = entry.runtime_data
    add([OnPanelImage(hass, coordinator), UpNextImage(hass, coordinator)])


class _FrameImage(InkFrameEntity, ImageEntity):
    """Shared plumbing.

    Both fetch `/preview.png`, never `/frame.*`: the renderer counts a fetch of
    `/frame.*` as the panel having collected the photo, so an image entity on
    that path would make `On panel` read true every time somebody opened the
    dashboard.
    """

    _attr_content_type = "image/png"

    def __init__(self, hass: HomeAssistant, coordinator, key: str) -> None:
        InkFrameEntity.__init__(self, coordinator, key)
        ImageEntity.__init__(self, hass)

    def _generation(self) -> int | None:
        raise NotImplementedError

    def _meta(self) -> dict:
        raise NotImplementedError

    @property
    def image_last_updated(self) -> datetime | None:
        # Drives when the frontend re-fetches. Tying it to the render timestamp
        # means a new photo refreshes the card and a poll that changed nothing
        # does not.
        rendered = self._meta().get("rendered_at")
        if isinstance(rendered, (int, float)) and rendered > 0:
            return datetime.fromtimestamp(rendered, tz=timezone.utc)
        return None

    @property
    def extra_state_attributes(self) -> dict:
        meta = self._meta()
        return {
            "photo": meta.get("name"),
            "taken": meta.get("taken"),
            "busyness": meta.get("busyness"),
            "source": meta.get("source"),
            "portrait": meta.get("portrait"),
            "generation": self._generation(),
        }

    async def async_image(self) -> bytes | None:
        generation = self._generation()
        if not generation:
            return None
        try:
            return await self.coordinator.async_preview(generation)
        except Exception:  # noqa: BLE001 - a missing frame is not a dead integration
            return None


class OnPanelImage(_FrameImage):
    """The photo the panel fetched, which is the one actually on the wall."""

    _attr_name = "On the panel"

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        super().__init__(hass, coordinator, "photo_on_panel")

    def _generation(self) -> int | None:
        return (self.coordinator.data or {}).get("panel_fetched_generation") or None

    def _meta(self) -> dict:
        meta = (self.coordinator.data or {}).get("on_panel_photo")
        return meta if isinstance(meta, dict) else {}


class UpNextImage(_FrameImage):
    """The most recently rendered photo: what the panel will collect next.

    While it matches `On the panel` the two cards show the same picture, which
    is the honest answer -- nothing is waiting.
    """

    _attr_name = "Up next"

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        super().__init__(hass, coordinator, "photo_up_next")

    def _generation(self) -> int | None:
        return (self.coordinator.data or {}).get("generation") or None

    def _meta(self) -> dict:
        return self.coordinator.current

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            **super().extra_state_attributes,
            "waiting_for_the_panel": not bool(data.get("on_panel")),
        }
