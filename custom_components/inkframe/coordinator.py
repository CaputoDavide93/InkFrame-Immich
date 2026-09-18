"""Polls the renderer and carries every write back to it."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_SCAN_SECONDS,
    CONF_TOKEN,
    CONF_URL,
    DEFAULT_SCAN_SECONDS,
    DOMAIN,
    HTTP_TIMEOUT_SECONDS,
    NEXT_TIMEOUT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class InkFrameCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """One /status poll feeds every entity.

    /status carries the current photo, the source, the live settings, the
    people summary and whether the panel has collected the frame -- one
    request, so the entities cannot disagree with each other about which
    generation they describe.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.url = entry.data[CONF_URL].rstrip("/")
        # Entries created before renderer authentication have no token. Setup
        # handles that as an actionable reconfigure requirement, not a KeyError.
        self.token = entry.data.get(CONF_TOKEN, "")
        seconds = entry.options.get(CONF_SCAN_SECONDS, DEFAULT_SCAN_SECONDS)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=seconds),
        )
        self._session = async_get_clientsession(hass)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="InkFrame",
            manufacturer="Davide Caputo",
            model="InkFrame renderer",
            configuration_url=f"{self.url}/healthz",
        )

    async def _get(self, path: str, timeout: int = HTTP_TIMEOUT_SECONDS,
                   params: dict[str, Any] | None = None) -> Any:
        try:
            async with self._session.get(
                f"{self.url}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise UpdateFailed(f"{path} -> HTTP {response.status}: {body[:200]}")
                if response.content_type.startswith("image/"):
                    return await response.read()
                return await response.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise UpdateFailed(f"{path}: {exc}") from exc
        except TimeoutError as exc:
            raise UpdateFailed(f"{path}: timeout after {timeout}s") from exc

    async def _async_update_data(self) -> dict[str, Any]:
        data = await self._get("/status")
        if not isinstance(data, dict):
            raise UpdateFailed("/status did not return an object")
        return data

    # ── writes ─────────────────────────────────────────────────────────────
    # Every write is followed by a refresh, so the entity shows what the server
    # actually stored rather than what we asked for. The two differ when the
    # server clamps or refuses a value.

    async def async_set_source(self, mode: str, person: str = "",
                               days: int | None = None,
                               people: list[str] | None = None,
                               album: str | None = None,
                               query: str | None = None) -> None:
        params: dict[str, Any] = {"mode": mode, "person": person}
        if days is not None:
            params["days"] = days
        if people is not None:
            params["people"] = ",".join(people)
        if album is not None:
            params["album"] = album
        if query is not None:
            params["query"] = query
        await self._get("/source", params=params)
        await self.async_request_refresh()

    async def async_set_settings(self, **changes: Any) -> None:
        await self._get("/settings", params={k: str(v) for k, v in changes.items()})
        await self.async_request_refresh()

    async def async_refresh_albums(self) -> None:
        """Re-read the album list from Immich now.

        `/status` serves a cache filled once a day, so an album made this
        afternoon is not in the picker until tomorrow. `/albums` reads Immich
        live and replaces that cache, which is why this is a GET of a list
        rather than a write.
        """
        await self._get("/albums")
        await self.async_request_refresh()

    async def async_next_photo(self) -> None:
        await self._get("/next", timeout=NEXT_TIMEOUT_SECONDS)
        await self.async_request_refresh()

    async def async_preview(self, generation: int | None = None) -> bytes:
        # /preview.png, never /frame.png: only the panel's own fetch may count
        # as the photo having reached the glass.
        data = await self._get("/preview.png",
                               params={"gen": generation} if generation else None)
        if not isinstance(data, (bytes, bytearray)):
            raise UpdateFailed("/preview.png did not return an image")
        return bytes(data)

    # ── convenience views over the last poll ───────────────────────────────

    @property
    def current(self) -> dict[str, Any]:
        cur = (self.data or {}).get("current")
        return cur if isinstance(cur, dict) else {}

    @property
    def settings(self) -> dict[str, Any]:
        cfg = (self.data or {}).get("settings")
        return cfg if isinstance(cfg, dict) else {}

    @property
    def people(self) -> dict[str, dict[str, Any]]:
        ppl = (self.data or {}).get("people")
        return ppl if isinstance(ppl, dict) else {}

    @property
    def source(self) -> str:
        return str((self.data or {}).get("source") or "random")
