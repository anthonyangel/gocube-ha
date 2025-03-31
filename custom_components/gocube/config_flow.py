"""Config flow for GoCube integration."""

from __future__ import annotations

import logging
from typing import Any

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from homeassistant.components.bluetooth import (
    DOMAIN as BLUETOOTH_DOMAIN,
    async_ble_device_from_address,
    async_discovered_service_info,
    async_last_service_info,
    async_scanner_count,
)
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .gocube_ble.ble import GoCubeConnection
from .gocube_ble.const import PRIMARY_SERVICE_UUID, TX_CHARACTERISTIC_UUID

_LOGGER = logging.getLogger(__name__)


class GoCubeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GoCube."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: AdvertisementData | None = None
        self._discovered_devices: dict[str, BLEDevice] = {}

    def _is_gocube_device(self, discovery_info: AdvertisementData) -> bool:
        """Check if the device is a GoCube."""
        service_uuids = discovery_info.service_uuids
        return (
            PRIMARY_SERVICE_UUID in service_uuids
            and TX_CHARACTERISTIC_UUID in service_uuids
        )

    async def async_step_bluetooth(
        self, discovery_info: AdvertisementData
    ) -> dict[str, Any]:
        """Handle the bluetooth discovery step."""
        if not self._is_gocube_device(discovery_info):
            return self.async_abort(reason="not_gocube_device")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Confirm discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.address,
                data={
                    CONF_ADDRESS: self._discovery_info.address,
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "address": self._discovery_info.address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the initial step."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            # Check if the device exists and is a GoCube
            device = async_ble_device_from_address(self.hass, address, connectable=True)
            if not device:
                return self.async_abort(reason="device_not_found")

            # Get the latest service info for the device
            service_info = async_last_service_info(self.hass, address)
            if not service_info or not self._is_gocube_device(service_info):
                return self.async_abort(reason="not_gocube_device")

            return self.async_create_entry(
                title=address,
                data={
                    CONF_ADDRESS: address,
                },
            )

        # Scan for devices
        scanner = BleakScanner()
        devices = await scanner.discover()

        current_addresses = self._async_current_ids()
        for device in devices:
            if device.address in current_addresses:
                continue
            # Get the metadata for the device
            if device.metadata:
                service_uuids = device.metadata.get("uuids", [])
                if (
                    PRIMARY_SERVICE_UUID in service_uuids
                    and TX_CHARACTERISTIC_UUID in service_uuids
                ):
                    self._discovered_devices[device.address] = device

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=self._get_schema(),
            errors={},
        )

    def _get_schema(self) -> dict[str, Any]:
        """Get the schema for the user step."""
        return {
            "address": str,
        }

    async def async_step_import(self, import_info: dict[str, Any]) -> dict[str, Any]:
        """Set up this integration using yaml."""
        address = import_info[CONF_ADDRESS]
        return self.async_create_entry(
            title=address,
            data={
                CONF_ADDRESS: address,
            },
        )
