"""Support for GoCube switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .gocube_ble.ble import GoCubeConnection

_LOGGER = logging.getLogger(__name__)

SWITCH_TYPES: dict[str, SwitchEntityDescription] = {
    "auto_reconnect": SwitchEntityDescription(
        key="auto_reconnect",
        name="Auto Reconnect",
        entity_category=EntityCategory.CONFIG,
        has_entity_name=True,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GoCube switch based on a config entry."""
    connection = hass.data[DOMAIN][entry.entry_id]["connection"]
    async_add_entities(
        GoCubeSwitch(connection, entry, description)
        for description in SWITCH_TYPES.values()
    )


class GoCubeSwitch(SwitchEntity):
    """Defines a GoCube switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        connection: GoCubeConnection,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        self.connection = connection
        self.entity_description = description
        self._attr_unique_id = f"{entry.data['address']}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["address"])},
            "name": entry.title,
            "model": "GoCube",
            "manufacturer": "GoCube",
        }
        self._unsubscribe = None

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self._unsubscribe = self.connection.register_callback(self._handle_state_change)

    def _handle_state_change(self) -> None:
        """Handle state changes."""
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return the state of the switch."""
        if self.entity_description.key == "auto_reconnect":
            return self.connection.should_auto_reconnect
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self.entity_description.key == "auto_reconnect":
            await self.connection.enable_auto_reconnect()
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self.entity_description.key == "auto_reconnect":
            await self.connection.disconnect()  # This also disables auto-reconnect
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed."""
        if self._unsubscribe:
            self._unsubscribe() 