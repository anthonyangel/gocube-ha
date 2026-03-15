"""Support for GoCube switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_STATE_UPDATE

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
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        GoCubeSwitch(coordinator, entry, description)
        for description in SWITCH_TYPES.values()
    )


class GoCubeSwitch(SwitchEntity):
    """GoCube switch entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, description: SwitchEntityDescription) -> None:
        """Initialize the switch."""
        self.coordinator = coordinator
        self.entity_description = description
        address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": entry.title,
            "model": "GoCube",
            "manufacturer": "GoCube",
        }
        self._address = address

    async def async_added_to_hass(self) -> None:
        """Register dispatcher listener."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_STATE_UPDATE}_{self._address}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle state update."""
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return the state of the switch."""
        return self.coordinator.should_auto_reconnect

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable auto-reconnect."""
        self.coordinator.should_auto_reconnect = True
        # If disconnected, try to reconnect now
        if not self.coordinator.is_connected:
            try:
                await self.coordinator.async_connect()
            except Exception:
                pass
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable auto-reconnect (does NOT disconnect)."""
        self.coordinator.should_auto_reconnect = False
        self.async_write_ha_state()
