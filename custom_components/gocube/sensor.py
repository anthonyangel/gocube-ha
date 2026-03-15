"""Support for GoCube sensors."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_STATE_UPDATE

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES: dict[str, SensorEntityDescription] = {
    "battery": SensorEntityDescription(
        key="battery",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
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
        state_class=SensorStateClass.MEASUREMENT,
        has_entity_name=True,
    ),
    "cube_type": SensorEntityDescription(
        key="cube_type",
        name="Cube Type",
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
    "state_fingerprint": SensorEntityDescription(
        key="state_fingerprint",
        name="State Fingerprint",
        entity_category=EntityCategory.DIAGNOSTIC,
        has_entity_name=True,
    ),
    "pattern": SensorEntityDescription(
        key="pattern",
        name="Pattern",
        has_entity_name=True,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GoCube sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        GoCubeSensor(coordinator, entry, description)
        for description in SENSOR_TYPES.values()
    )


class GoCubeSensor(SensorEntity):
    """GoCube sensor entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator, entry: ConfigEntry, description: SensorEntityDescription) -> None:
        """Initialize the sensor."""
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
        # Connection state sensor is always available
        if self.entity_description.key == "connection_state":
            return True
        return self.coordinator.has_been_seen

    @property
    def assumed_state(self) -> bool:
        """Return True when disconnected (values are cached)."""
        return not self.coordinator.is_connected

    @property
    def native_value(self) -> str | int | float | None:
        """Return the sensor value."""
        data = self.coordinator.data
        key = self.entity_description.key

        if key == "battery":
            return data.battery_level
        if key == "connection_state":
            if self.coordinator.is_connected:
                return "connected"
            if self.coordinator.has_been_seen:
                return "disconnected"
            return "not_seen"
        if key == "solved_faces":
            if data.face_states:
                return sum(1 for v in data.face_states.values() if v)
            return 0
        if key == "cube_type":
            return data.cube_type
        if key == "state_fingerprint":
            return data.state_fingerprint
        if key == "pattern":
            # Check built-in patterns first
            match = data.matched_pattern
            if match:
                return match
            # Check user-saved patterns
            fp = data.state_fingerprint
            if fp:
                store = self.hass.data.get(DOMAIN, {}).get("pattern_store")
                if store:
                    return store.match(fp)
            return None
        return None
