"""Support for GoCube buttons."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .gocube_ble.models import KNOWN_PATTERNS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GoCube buttons."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    async_add_entities([
        GoCubeRebootButton(coordinator, entry),
        GoCubeListPatternsButton(coordinator, entry, address),
    ])


class GoCubeRebootButton(ButtonEntity):
    """GoCube reboot button."""

    _attr_has_entity_name = True
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the button entity."""
        self.coordinator = coordinator
        address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{address}_reboot"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": entry.title,
            "model": "GoCube",
            "manufacturer": "GoCube",
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            await self.coordinator.connection.send_command("Reboot")
        except Exception as err:
            _LOGGER.error("Failed to reboot GoCube: %s", err)


class GoCubeListPatternsButton(ButtonEntity):
    """Button to list all known and saved patterns."""

    _attr_has_entity_name = True
    _attr_name = "List Patterns"
    _attr_icon = "mdi:format-list-bulleted"

    def __init__(self, coordinator, entry: ConfigEntry, address: str) -> None:
        """Initialize the button entity."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{address}_list_patterns"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": entry.title,
            "model": "GoCube",
            "manufacturer": "GoCube",
        }

    async def async_press(self) -> None:
        """List all patterns as a persistent notification."""
        store = self.hass.data.get(DOMAIN, {}).get("pattern_store")

        lines = ["**Built-in patterns:**\n"]
        for name, fp in KNOWN_PATTERNS.items():
            lines.append(f"- **{name}**: `{fp}`")

        if store and store.patterns:
            lines.append("\n**Saved patterns:**\n")
            for name, fp in store.patterns.items():
                lines.append(f"- **{name}**: `{fp}`")
        else:
            lines.append("\n*No saved patterns.*")

        # Add current state
        fp = self.coordinator.data.state_fingerprint
        if fp:
            matched = self.coordinator.data.matched_pattern
            if store and not matched:
                matched = store.match(fp)
            label = f" ({matched})" if matched else ""
            lines.append(f"\n**Current state{label}:** `{fp}`")

        message = "\n".join(lines)

        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "GoCube Patterns",
                "message": message,
                "notification_id": "gocube_patterns",
            },
        )
