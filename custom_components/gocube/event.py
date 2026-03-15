"""Support for GoCube events."""

from __future__ import annotations

import logging

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_MOVEMENT

_LOGGER = logging.getLogger(__name__)

ROTATION_EVENTS = [
    "blue_clockwise",
    "blue_counterclockwise",
    "green_clockwise",
    "green_counterclockwise",
    "white_clockwise",
    "white_counterclockwise",
    "yellow_clockwise",
    "yellow_counterclockwise",
    "red_clockwise",
    "red_counterclockwise",
    "orange_clockwise",
    "orange_counterclockwise",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GoCube event based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GoCubeRotationEvent(coordinator, entry)])


class GoCubeRotationEvent(EventEntity):
    """GoCube rotation event entity."""

    _attr_has_entity_name = True
    _attr_name = "Rotation"
    _attr_device_class = EventDeviceClass.MOTION
    _attr_event_types = ROTATION_EVENTS

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the event entity."""
        self.coordinator = coordinator
        address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{address}_rotation"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": entry.title,
            "model": "GoCube",
            "manufacturer": "GoCube",
        }
        self._address = address

    async def async_added_to_hass(self) -> None:
        """Register movement dispatcher listener."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_MOVEMENT}_{self._address}",
                self._handle_movement,
            )
        )

    @callback
    def _handle_movement(self, movement: str) -> None:
        """Handle movement events from the cube."""
        event_type = movement.lower().replace(" ", "_")
        self._trigger_event(event_type)
        self.async_write_ha_state()
