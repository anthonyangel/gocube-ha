"""Support for GoCube events."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.event import (
    EventDeviceClass,
    EventEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .gocube_ble.ble import GoCubeConnection

_LOGGER = logging.getLogger(__name__)

# Define all possible rotation events
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
    connection = hass.data[DOMAIN][entry.entry_id]["connection"]
    async_add_entities([GoCubeRotationEvent(connection, entry)])


class GoCubeRotationEvent(EventEntity):
    """Defines a GoCube rotation event."""

    _attr_has_entity_name = True
    _attr_name = "Rotation"
    _attr_device_class = EventDeviceClass.MOTION
    _attr_event_types = ROTATION_EVENTS

    def __init__(self, connection: GoCubeConnection, entry: ConfigEntry) -> None:
        """Initialize the event entity."""
        self.connection = connection
        self._attr_unique_id = f"{entry.data['address']}_rotation"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["address"])},
            "name": entry.title,
            "model": "GoCube",
            "manufacturer": "GoCube",
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.connection.add_movement_callback(self._handle_movement)

    def _handle_movement(self, movement: str) -> None:
        """Handle movement events from the cube."""
        # Convert "Blue Clockwise" to "blue_clockwise"
        event_type = movement.lower().replace(" ", "_")
        self._trigger_event(event_type)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        self.connection.remove_movement_callback(self._handle_movement)
