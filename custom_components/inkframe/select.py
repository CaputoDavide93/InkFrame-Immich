"""Where photos come from: the mode, and for Album, which album."""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InkFrameConfigEntry
from .const import (
    NO_ALBUMS,
    SOURCE_ALBUM,
    SOURCE_SEARCH,
    SOURCE_PEOPLE,
    SOURCE_RANDOM,
    SOURCE_RECENT,
)
from .entity import InkFrameEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: InkFrameConfigEntry, add: AddEntitiesCallback
) -> None:
    add([SourceSelect(entry.runtime_data), AlbumSelect(entry.runtime_data)])


def _parse(source: str) -> tuple[str, str]:
    """'person:Alice' -> ('person', 'Alice'); 'random' -> ('random', '')."""
    mode, _, rest = source.partition(":")
    return mode, rest


class SourceSelect(InkFrameEntity, SelectEntity):
    """Random / Recent / People / Album, or one named person directly.

    People (plural) draws from everyone whose `Include` switch is on --
    photos of ANY of them, not only photos with all of them together. A single
    person's name is still offered as a shortcut.
    """

    _attr_name = "Source"
    _attr_icon = "mdi:image-multiple"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "source")

    @property
    def options(self) -> list[str]:
        # Only people with enough landscape photographs. Offering the others
        # gives a source that runs dry against the recently-shown list and
        # silently repeats -- the server decides the threshold, not us.
        data = self.coordinator.data or {}
        people = sorted(
            name for name, info in self.coordinator.people.items()
            if isinstance(info, dict) and info.get("eligible")
        )
        # Album and Search have mandatory companion values. Their dedicated
        # picker/text entities switch the source after they collect one.
        options = [SOURCE_RANDOM, SOURCE_RECENT, SOURCE_PEOPLE, *people]
        if data.get("source_album"):
            options.append(SOURCE_ALBUM)
        if data.get("source_query"):
            options.append(SOURCE_SEARCH)
        current = self.current_option
        # A person who dropped below the threshold since being chosen must
        # still appear, or HA shows the select as invalid.
        if current and current not in options:
            options.append(current)
        return options

    @property
    def current_option(self) -> str | None:
        mode, rest = _parse(self.coordinator.source)
        return {
            "person": rest or None,
            "people": SOURCE_PEOPLE,
            "album": SOURCE_ALBUM,
            "search": SOURCE_SEARCH,
            "recent": SOURCE_RECENT,
        }.get(mode, SOURCE_RANDOM)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        counts = {
            name: info.get("landscape")
            for name, info in sorted(self.coordinator.people.items())
            if isinstance(info, dict)
        }
        return {
            "landscape_photos_per_person": counts,
            "included_people": data.get("source_people") or [],
            "album": data.get("source_album") or None,
            "search": data.get("source_query") or None,
            "server_source": self.coordinator.source,
        }

    async def async_select_option(self, option: str) -> None:
        data = self.coordinator.data or {}
        days = data.get("source_days")
        if option == SOURCE_RANDOM:
            await self.coordinator.async_set_source("random")
        elif option == SOURCE_RECENT:
            await self.coordinator.async_set_source("recent", days=days)
        elif option == SOURCE_PEOPLE:
            await self.coordinator.async_set_source("people")
        elif option == SOURCE_ALBUM:
            await self.coordinator.async_set_source("album", album=data.get("source_album"))
        elif option == SOURCE_SEARCH:
            await self.coordinator.async_set_source("search", query=data.get("source_query"))
        else:
            await self.coordinator.async_set_source("person", person=option)


class AlbumSelect(InkFrameEntity, SelectEntity):
    """Which album, when Source is Album. Choosing one also switches the
    source to Album -- picking an album and not seeing it used would be the
    surprising outcome."""

    _attr_name = "Album"
    _attr_icon = "mdi:image-album"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "album")

    @property
    def options(self) -> list[str]:
        albums = (self.coordinator.data or {}).get("albums")
        names = sorted(albums) if isinstance(albums, list) and albums else []
        current = (self.coordinator.data or {}).get("source_album")
        if current and current not in names:
            names.append(str(current))
        return names or [NO_ALBUMS]

    @property
    def current_option(self) -> str | None:
        current = (self.coordinator.data or {}).get("source_album")
        if current:
            return str(current)
        return NO_ALBUMS if self.options == [NO_ALBUMS] else None

    async def async_select_option(self, option: str) -> None:
        if option == NO_ALBUMS:
            return
        await self.coordinator.async_set_source("album", album=option)
