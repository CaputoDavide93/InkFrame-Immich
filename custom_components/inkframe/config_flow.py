"""Config flow for InkFrame."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_SCAN_SECONDS,
    CONF_TOKEN,
    CONF_URL,
    DEFAULT_SCAN_SECONDS,
    DEFAULT_URL,
    DOMAIN,
    MIN_SCAN_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


async def _probe(hass: HomeAssistant, url: str, token: str) -> tuple[bool, str]:
    """Is there a renderer at this URL with this credential?

    `/healthz` deliberately stays unauthenticated for Docker liveness; setup
    probes protected `/status`, which also proves the supplied token works.
    """
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"{url.rstrip('/')}/status",
            headers={"Authorization": f"Bearer {token}"},
            timeout=aiohttp.ClientTimeout(total=5),
        ) as response:
            if response.status != 200:
                return False, f"HTTP {response.status}"
            body = await response.json(content_type=None)
            if not isinstance(body, dict) or "generation" not in body:
                return False, "not an InkFrame renderer"
            return True, "ok"
    except aiohttp.ClientError as exc:
        return False, f"connect: {exc}"
    except TimeoutError:
        return False, "timeout"


class InkFrameConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            token = user_input[CONF_TOKEN].strip()
            await self.async_set_unique_id(url)
            self._abort_if_unique_id_configured()
            ok, msg = await _probe(self.hass, url, token)
            if not ok:
                _LOGGER.warning("InkFrame probe failed: %s", msg)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title="InkFrame for Immich", data={CONF_URL: url, CONF_TOKEN: token}
                )

        schema = vol.Schema({
            vol.Required(CONF_URL, default=DEFAULT_URL): str,
            vol.Required(CONF_TOKEN): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> InkFrameOptionsFlow:
        return InkFrameOptionsFlow()


class InkFrameOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(CONF_SCAN_SECONDS, DEFAULT_SCAN_SECONDS)
        schema = vol.Schema({
            vol.Required(CONF_SCAN_SECONDS, default=current):
                vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_SECONDS, max=3600)),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
