"""Support for GoCube lights."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityDescription,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_STATE_UPDATE

_LOGGER = logging.getLogger(__name__)

EFFECT_FLASH = "Flash"
EFFECT_FLASH_SLOW = "Flash Slow"
EFFECT_ANIMATION = "Animation"

# 7 brightness levels: 0x45 (brightest) → 0x4B (off)
# Map to command names in CONFIGURATION_COMMANDS
_BRIGHTNESS_LEVELS = [
    "LedBrightnessOff",  # level 0
    "LedBrightness1",    # level 1
    "LedBrightness2",    # level 2
    "LedBrightness3",    # level 3
    "LedBrightness4",    # level 4
    "LedBrightness5",    # level 5
    "LedBrightness6",    # level 6 (max)
]

LIGHT_TYPES: dict[str, LightEntityDescription] = {
    "status": LightEntityDescription(
        key="status",
        name="Status Light",
        has_entity_name=True,
    ),
}


def _brightness_to_level(brightness: int) -> int:
    """Map HA brightness (1-255) to cube level (1-6)."""
    # 6 visible levels, evenly spaced across 1-255
    return min(6, max(1, round(brightness * 6 / 255)))


def _level_to_brightness(level: int) -> int:
    """Map cube level (0-6) to HA brightness (0-255)."""
    return round(level * 255 / 6)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the GoCube lights."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        GoCubeLight(coordinator, entry, description)
        for description in LIGHT_TYPES.values()
    )


class GoCubeLight(LightEntity):
    """GoCube light entity with brightness support."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = [EFFECT_FLASH, EFFECT_FLASH_SLOW, EFFECT_ANIMATION]

    def __init__(self, coordinator, entry: ConfigEntry, description: LightEntityDescription) -> None:
        """Initialize the light."""
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
        self._attr_is_on = False
        self._attr_brightness = 255
        self._level = 6  # Current cube brightness level (0-6)
        self._effect = None
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
        """Return True when connected (light requires active connection)."""
        return self.coordinator.is_connected

    @property
    def is_on(self) -> bool:
        """Return if the light is on."""
        return self._attr_is_on

    @property
    def brightness(self) -> int | None:
        """Return the brightness."""
        return self._attr_brightness if self._attr_is_on else None

    @property
    def effect(self) -> str | None:
        """Return the current effect."""
        return self._effect

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on, optionally with brightness or effect."""
        try:
            if ATTR_EFFECT in kwargs:
                effect = kwargs[ATTR_EFFECT]
                if effect == EFFECT_FLASH:
                    await self.coordinator.connection.send_command("LedFlash")
                    self._effect = EFFECT_FLASH
                    self._attr_is_on = False
                elif effect == EFFECT_FLASH_SLOW:
                    await self.coordinator.connection.send_command("LedFlashSlow")
                    self._effect = EFFECT_FLASH_SLOW
                    self._attr_is_on = False
                elif effect == EFFECT_ANIMATION:
                    await self.coordinator.connection.send_command("LedToggleAnimation")
                    self._effect = EFFECT_ANIMATION
                else:
                    self._effect = None
                    self._attr_is_on = True
            elif ATTR_BRIGHTNESS in kwargs:
                level = _brightness_to_level(kwargs[ATTR_BRIGHTNESS])
                if not self._attr_is_on:
                    await self.coordinator.connection.send_command("LedToggle")
                await self.coordinator.connection.send_command(_BRIGHTNESS_LEVELS[level])
                self._level = level
                self._attr_brightness = _level_to_brightness(level)
                self._attr_is_on = True
                self._effect = None
            else:
                # Turn on at last known brightness
                await self.coordinator.connection.send_command("LedToggle")
                level = self._level if self._level > 0 else 6
                await self.coordinator.connection.send_command(_BRIGHTNESS_LEVELS[level])
                self._level = level
                self._attr_brightness = _level_to_brightness(level)
                self._attr_is_on = True
                self._effect = None
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Failed to turn on light: %s", err)
            self._attr_is_on = False
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        try:
            await self.coordinator.connection.send_command("LedToggle")
            self._attr_is_on = False
            self._effect = None
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Failed to turn off light: %s", err)
            self._attr_is_on = True
            self.async_write_ha_state()
