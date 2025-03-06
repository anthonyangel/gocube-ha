"""Support for GoCube binary sensors."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .gocube_ble.ble import GoCubeConnection

_LOGGER = logging.getLogger(__name__)

BINARY_SENSOR_TYPES: dict[str, BinarySensorEntityDescription] = {
    "cube_solved": BinarySensorEntityDescription(
        key="cube_solved",
        name="Solved",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
    "blue_face": BinarySensorEntityDescription(
        key="blue_face",
        name="Blue Face",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
    "green_face": BinarySensorEntityDescription(
        key="green_face",
        name="Green Face",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
    "white_face": BinarySensorEntityDescription(
        key="white_face",
        name="White Face",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
    "yellow_face": BinarySensorEntityDescription(
        key="yellow_face",
        name="Yellow Face",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
    "red_face": BinarySensorEntityDescription(
        key="red_face",
        name="Red Face",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
    "orange_face": BinarySensorEntityDescription(
        key="orange_face",
        name="Orange Face",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GoCube binary sensors."""
    connection = hass.data[DOMAIN][entry.entry_id]["connection"]
    async_add_entities(
        GoCubeBinarySensor(connection, entry, description)
        for description in BINARY_SENSOR_TYPES.values()
    )


class GoCubeBinarySensor(BinarySensorEntity):
    """Representation of a GoCube binary sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        connection: GoCubeConnection,
        entry: ConfigEntry,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
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
        """Return if the face is solved."""
        data = self.connection.data
        if self.entity_description.key == "cube_solved":
            return not data.is_solved  # Problem when not solved

        # Extract color from the key (e.g., "blue_face" -> "Blue")
        color = self.entity_description.key.split("_")[0].capitalize()
        # Return True (problem) when face is not solved
        return not data.face_states.get(color, False)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.connection._is_connected
            and self.connection._client is not None
            and self.connection._client.is_connected
        )

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self._unsubscribe:
            self._unsubscribe()
