"""Support for GoCube buttons."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .gocube_ble.ble import GoCubeConnection

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GoCube button based on a config entry."""
    connection = hass.data[DOMAIN][entry.entry_id]["connection"]
    async_add_entities([GoCubeRebootButton(connection, entry)])


class GoCubeRebootButton(ButtonEntity):
    """Defines a GoCube reboot button."""

    _attr_has_entity_name = True
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, connection: GoCubeConnection, entry: ConfigEntry) -> None:
        """Initialize the button entity."""
        self.connection = connection
        self._attr_unique_id = f"{entry.data['address']}_reboot"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["address"])},
            "name": entry.title,
            "model": "GoCube",
            "manufacturer": "GoCube",
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            await self.connection.send_command("Reboot")
            _LOGGER.debug("GoCube reboot command sent successfully")
        except Exception as err:
            _LOGGER.error("Failed to reboot GoCube: %s", err)
