"""What to search Immich for, when Source is Search."""
from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InkFrameConfigEntry
from .const import SOURCE_SEARCH
from .entity import InkFrameEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: InkFrameConfigEntry, add: AddEntitiesCallback
) -> None:
    add([SearchText(entry.runtime_data)])


class SearchText(InkFrameEntity, TextEntity):
    """A description, not a filename: Immich matches it against what the photo
    looks like. "cat" is the reason this exists -- face recognition clusters
    people, so a pet has no person to select and could not reach the frame any
    other way. "beach", "snow" and "birthday cake" work the same way.

    Typing here also switches Source to Search. Setting a search term and not
    having it used would be the surprising outcome.
    """

    _attr_name = "Search for"
    _attr_icon = "mdi:image-search"
    _attr_mode = TextMode.TEXT
    _attr_native_max = 100

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "search_query")

    @property
    def native_value(self) -> str | None:
        return str((self.coordinator.data or {}).get("source_query") or "")

    async def async_set_value(self, value: str) -> None:
        value = value.strip()
        if not value:
            # Clearing the box must not switch the source to one that cannot
            # work; leave whatever is selected alone.
            await self.coordinator.async_set_source(
                self.coordinator.source.partition(":")[0] or "random", query=""
            )
            return
        await self.coordinator.async_set_source("search", query=value)

    @property
    def extra_state_attributes(self) -> dict:
        return {"in_use": self.coordinator.source.startswith("search")}
