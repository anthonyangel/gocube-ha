"""Support for GoCube visualization as an image entity."""

from __future__ import annotations

import logging

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_STATE_UPDATE
from .gocube_ble.renderer import render_cube_svg

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GoCube image entity."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GoCubeImageEntity(coordinator, entry)])


class GoCubeImageEntity(ImageEntity):
    """Isometric cube visualization entity."""

    _attr_has_entity_name = True
    _attr_name = "Cube View"
    _attr_content_type = "image/svg+xml"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the image entity."""
        super().__init__(coordinator.hass)
        self.coordinator = coordinator
        address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{address}_cube_view"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": entry.title,
            "model": "GoCube",
            "manufacturer": "GoCube",
        }
        self._address = address
        self._cached_svg: bytes | None = None

    async def async_added_to_hass(self) -> None:
        """Register dispatcher listener."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_STATE_UPDATE}_{self._address}",
                self._handle_update,
            )
        )
        # Generate initial image
        self._update_image()

    @callback
    def _handle_update(self) -> None:
        """Handle state update — re-render the cube."""
        self._update_image()
        self.async_write_ha_state()

    def _update_image(self) -> None:
        """Re-render the SVG from current face data."""
        face_colors = self.coordinator.data.face_colors or None
        svg = render_cube_svg(face_colors=face_colors)
        self._cached_svg = svg.encode("utf-8")
        from datetime import datetime
        self._attr_image_last_updated = datetime.now()

    async def async_image(self) -> bytes | None:
        """Return the current cube image."""
        return self._cached_svg

    @property
    def available(self) -> bool:
        """Return True once we've received state data."""
        return self.coordinator.has_been_seen

    @property
    def assumed_state(self) -> bool:
        """Return True when disconnected (image is cached)."""
        return not self.coordinator.is_connected
