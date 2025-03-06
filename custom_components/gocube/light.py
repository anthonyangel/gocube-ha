"""Support for GoCube lights."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityDescription,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .gocube_ble.ble import GoCubeConnection

_LOGGER = logging.getLogger(__name__)

# Effect names
EFFECT_FLASH = "Flash"
EFFECT_FLASH_SLOW = "Flash Slow"
EFFECT_ANIMATION = "Animation"

LIGHT_TYPES: dict[str, LightEntityDescription] = {
    "status": LightEntityDescription(
        key="status",
        name="Status Light",
        has_entity_name=True,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the GoCube lights."""
    connection = hass.data[DOMAIN][entry.entry_id]["connection"]
    async_add_entities(
        GoCubeLight(connection, entry, description)
        for description in LIGHT_TYPES.values()
    )


class GoCubeLight(LightEntity):
    """Representation of a GoCube light."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = [EFFECT_FLASH, EFFECT_FLASH_SLOW, EFFECT_ANIMATION]

    def __init__(
        self,
        connection: GoCubeConnection,
        entry: ConfigEntry,
        description: LightEntityDescription,
    ) -> None:
        """Initialize the light."""
        self.connection = connection
        self.entity_description = description
        self._attr_unique_id = f"{entry.data['address']}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["address"])},
            "name": entry.title,
            "model": "GoCube",
            "manufacturer": "GoCube",
        }
        self._attr_is_on = False
        self._attr_available = False
        self._unsubscribe = None
        self._effect = None

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self._unsubscribe = self.connection.register_callback(self._handle_state_change)
        # Initial state update
        self.async_write_ha_state()

    def _handle_state_change(self) -> None:
        """Handle state changes."""
        _LOGGER.debug(
            "Light %s state changed: available=%s, is_on=%s",
            self.entity_description.key,
            self.available,
            self.is_on,
        )
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return if the light is on."""
        return self._attr_is_on

    @property
    def available(self) -> bool:
        """Return if the light is available."""
        return (
            self.connection._is_connected
            and self.connection._client is not None
            and self.connection._client.is_connected
        )

    @property
    def effect(self) -> str | None:
        """Return the current effect."""
        return self._effect

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        try:
            if ATTR_EFFECT in kwargs:
                effect = kwargs[ATTR_EFFECT]
                if effect == EFFECT_FLASH:
                    await self.connection.led_flash()
                    self._effect = EFFECT_FLASH
                    # Flash effect is temporary, set state to off
                    self._attr_is_on = False
                elif effect == EFFECT_FLASH_SLOW:
                    await self.connection.led_flash_slow()
                    self._effect = EFFECT_FLASH_SLOW
                    # Flash slow effect is temporary, set state to off
                    self._attr_is_on = False
                elif effect == EFFECT_ANIMATION:
                    await self.connection.led_toggle_animation()
                    self._effect = EFFECT_ANIMATION
                else:
                    self._effect = None
                    self._attr_is_on = True
            else:
                await self.connection.led_toggle()
                self._effect = None
                self._attr_is_on = True
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Failed to turn on light: %s", err)
            self._attr_is_on = False
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        try:
            await self.connection.led_toggle()
            self._attr_is_on = False
            self._effect = None
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Failed to turn off light: %s", err)
            self._attr_is_on = True
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed."""
        if self._unsubscribe:
            self._unsubscribe()
