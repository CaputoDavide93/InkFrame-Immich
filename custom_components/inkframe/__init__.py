"""The InkFrame integration: manage the ePaper photo frame's renderer."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import InkFrameCoordinator
from .const import CONF_TOKEN

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]

type InkFrameConfigEntry = ConfigEntry[InkFrameCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: InkFrameConfigEntry) -> bool:
    # v1 entries predate authenticated renderer access. Do not crash setup;
    # Home Assistant exposes the integration's Reconfigure action to collect it.
    if not entry.data.get(CONF_TOKEN):
        return False
    coordinator = InkFrameCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: InkFrameConfigEntry) -> bool:
    """Keep pre-token entries loadable enough to offer Reconfigure."""
    if entry.version < 2:
        hass.config_entries.async_update_entry(entry, version=2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InkFrameConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: InkFrameConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
