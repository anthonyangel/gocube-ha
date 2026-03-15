"""Support for GoCube binary sensors."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_STATE_UPDATE

_LOGGER = logging.getLogger(__name__)

BINARY_SENSOR_TYPES: dict[str, BinarySensorEntityDescription] = {
    "cube_solved": BinarySensorEntityDescription(
        key="cube_solved",
        name="Solved",
        device_class=BinarySensorDeviceClass.PROBLEM,
        has_entity_name=True,
    ),
    "blue_face": BinarySensorEntityDescription(
        key="blue_face",
        name="Face: Blue",
        device_class=BinarySensorDeviceClass.PROBLEM,
        has_entity_name=True,
    ),
    "green_face": BinarySensorEntityDescription(
        key="green_face",
        name="Face: Green",
        device_class=BinarySensorDeviceClass.PROBLEM,
        has_entity_name=True,
    ),
    "white_face": BinarySensorEntityDescription(
        key="white_face",
        name="Face: White",
        device_class=BinarySensorDeviceClass.PROBLEM,
        has_entity_name=True,
    ),
    "yellow_face": BinarySensorEntityDescription(
        key="yellow_face",
        name="Face: Yellow",
        device_class=BinarySensorDeviceClass.PROBLEM,
        has_entity_name=True,
    ),
    "red_face": BinarySensorEntityDescription(
        key="red_face",
        name="Face: Red",
        device_class=BinarySensorDeviceClass.PROBLEM,
        has_entity_name=True,
    ),
    "orange_face": BinarySensorEntityDescription(
        key="orange_face",
        name="Face: Orange",
        device_class=BinarySensorDeviceClass.PROBLEM,
        has_entity_name=True,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GoCube binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        GoCubeBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSOR_TYPES.values()
    )


class GoCubeBinarySensor(BinarySensorEntity):
    """GoCube binary sensor entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator, entry: ConfigEntry, description: BinarySensorEntityDescription) -> None:
        """Initialize the binary sensor."""
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
    def available(self) -> bool:
        """Return True once we've received any data from the cube."""
        return self.coordinator.has_been_seen

    @property
    def assumed_state(self) -> bool:
        """Return True when disconnected (values are cached)."""
        return not self.coordinator.is_connected

    @property
    def is_on(self) -> bool:
        """Return True when face is NOT solved (problem sensor)."""
        data = self.coordinator.data
        if self.entity_description.key == "cube_solved":
            return not data.is_solved

        color = self.entity_description.key.split("_")[0].capitalize()
        return not data.face_states.get(color, False)
