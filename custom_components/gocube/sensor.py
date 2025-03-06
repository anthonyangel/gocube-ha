"""Support for GoCube sensors."""

from __future__ import annotations

from typing import Any
from datetime import datetime
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
    EntityCategory,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import logging

from .const import DOMAIN
from .gocube_ble.ble import GoCubeConnection

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES: dict[str, SensorEntityDescription] = {
    "battery": SensorEntityDescription(
        key="battery",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
    "connection_state": SensorEntityDescription(
        key="connection_state",
        name="Connection State",
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
    "solved_faces": SensorEntityDescription(
        key="solved_faces",
        name="Solved Faces",
        native_unit_of_measurement="faces",
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
    # "rssi": SensorEntityDescription(
    #     key="rssi",
    #     name="Signal Strength",
    #     device_class="signal_strength",
    #     native_unit_of_measurement="dBm",
    #     translation_key="rssi",
    # ),
    # "last_update": SensorEntityDescription(
    #     key="last_update",
    #     name="Last Update",
    #     device_class="timestamp",
    #     translation_key="last_update",
    # ),
    # "last_move": SensorEntityDescription(
    #     key="last_move",
    #     name="Last Move",
    #     translation_key="last_move",
    # ),
    # "cube_type": SensorEntityDescription(
    #     key="cube_type",
    #     name="Cube Type",
    #     translation_key="cube_type",
    # ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GoCube sensors."""
    connection = hass.data[DOMAIN][entry.entry_id]["connection"]
    async_add_entities(
        [
            GoCubeSensor(connection, entry, description)
            for description in SENSOR_TYPES.values()
        ]
    )


class GoCubeSensor(SensorEntity):
    """Base class for GoCube sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = True

    def __init__(
        self,
        connection: GoCubeConnection,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.connection = connection
        self.entity_description = description
        self._attr_unique_id = f"{entry.data['address']}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["address"])},
            "name": entry.title,
            "model": "GoCube",
            "manufacturer": "GoCube",
        }
        self._unsubscribe = self.connection.register_callback(self._handle_state_change)

    def _handle_state_change(self) -> None:
        """Handle state changes."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.connection._is_connected
            and self.connection._client is not None
            and self.connection._client.is_connected
        )

    @property
    def native_value(self) -> str | int | float | None:
        """Return the native value."""
        if not self.available:
            return None

        value = None
        if self.entity_description.key == "battery":
            value = self.connection.data.battery_level
        elif self.entity_description.key == "connection_state":
            # Only show connected if we have received data
            value = (
                "connected"
                if self.connection.data.battery_level is not None
                else "connecting"
            )
        elif self.entity_description.key == "solved_faces":
            # Count the number of solved faces
            if self.connection.data.face_states:
                value = sum(
                    1
                    for face_solved in self.connection.data.face_states.values()
                    if face_solved
                )
            else:
                value = 0
        # elif self.entity_description.key == "rssi":
        #     value = self.connection.data.rssi
        # elif self.entity_description.key == "last_update":
        #     if self.connection.data.last_update:
        #         value = datetime.fromtimestamp(self.connection.data.last_update).isoformat()
        # elif self.entity_description.key == "last_move":
        #     value = self.connection.data.last_move
        # elif self.entity_description.key == "cube_type":
        #     value = self.connection.data.cube_type

        _LOGGER.debug(
            "Sensor %s value: %s (data: %s)",
            self.entity_description.key,
            value,
            self.connection.data,
        )
        return value

    async def async_update(self) -> None:
        """Update the sensor."""
        if not self.available:
            return

        try:
            if self.entity_description.key == "battery":
                await self.connection.send_command("GetBattery")
        except Exception as err:
            _LOGGER.error("Failed to update sensor: %s", err)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed."""
        self._unsubscribe()
