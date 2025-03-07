"""The GoCube integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .gocube_ble.ble import GoCubeConnection

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["binary_sensor", "sensor", "light", "button", "event", "switch"]


class GoCubeError(HomeAssistantError):
    """Base class for GoCube errors."""


class GoCubeConnectionError(GoCubeError):
    """Raised when there is an error connecting to the GoCube."""


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GoCube from a config entry."""
    try:
        connection = GoCubeConnection()
        await connection.connect(entry.data["address"])
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"connection": connection}
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        return True
    except Exception as err:
        _LOGGER.error("Failed to connect to GoCube: %s", err)
        return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        try:
            connection = hass.data[DOMAIN][entry.entry_id]["connection"]
            await connection.disconnect()
        except Exception as err:
            _LOGGER.error("Error disconnecting from GoCube: %s", err)
        finally:
            hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the GoCube integration."""
    return True
