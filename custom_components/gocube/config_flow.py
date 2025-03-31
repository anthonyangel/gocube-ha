"""Config flow for GoCube integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
    async_scanner_count,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import AbortFlow
import voluptuous as vol

from .const import DOMAIN
from .gocube_ble.const import PRIMARY_SERVICE_UUID, TX_CHARACTERISTIC_UUID

_LOGGER = logging.getLogger(__name__)

DISCOVERY_TIMEOUT = 5


class GoCubeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GoCube."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    def _is_gocube_device(self, discovery_info: BluetoothServiceInfoBleak) -> bool:
        """Check if the device is a GoCube."""
        has_service_uuids = (
            discovery_info.advertisement.service_uuids is not None
            and len(discovery_info.advertisement.service_uuids) > 0
        )
        has_primary = (
            has_service_uuids
            and PRIMARY_SERVICE_UUID in discovery_info.advertisement.service_uuids
        )

        _LOGGER.debug(
            "Checking device %s (%s): service_uuids=%s, has_primary=%s",
            discovery_info.name,
            discovery_info.address,
            has_service_uuids,
            has_primary,
        )

        return has_primary

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug(
            "Discovered bluetooth device: %s %s",
            discovery_info.name,
            discovery_info.address,
        )
        
        if not self._is_gocube_device(discovery_info):
            return self.async_abort(reason="not_gocube_device")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name,
                data={
                    CONF_ADDRESS: self._discovery_info.address,
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovery_info.name,
                "address": self._discovery_info.address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step."""
        errors = {}

        if async_scanner_count(self.hass) == 0:
            _LOGGER.warning("No bluetooth scanners available")
            return self.async_abort(reason="bluetooth_not_available")

        _LOGGER.debug("Starting GoCube device discovery...")
        current_addresses = self._async_current_ids()
        if current_addresses:
            _LOGGER.debug("Already configured addresses: %s", current_addresses)

        self._discovered_devices.clear()
        discovered_count = 0

        # First discovery pass
        for discovery_info in async_discovered_service_info(self.hass):
            discovered_count += 1
            _LOGGER.debug(
                "Examining device: name=%s, address=%s, local_name=%s, manufacturer_data=%s, service_uuids=%s",
                discovery_info.name,
                discovery_info.address,
                discovery_info.advertisement.local_name,
                discovery_info.advertisement.manufacturer_data,
                discovery_info.advertisement.service_uuids,
            )

            if discovery_info.address in current_addresses:
                _LOGGER.debug(
                    "Skipping already configured device: %s",
                    discovery_info.address,
                )
                continue

            if discovery_info.address in self._discovered_devices:
                _LOGGER.debug(
                    "Device already discovered: %s",
                    discovery_info.address,
                )
                continue

            if self._is_gocube_device(discovery_info):
                _LOGGER.debug(
                    "Found GoCube device: %s (%s)",
                    discovery_info.name,
                    discovery_info.address,
                )
                self._discovered_devices[discovery_info.address] = discovery_info

        if not self._discovered_devices:
            _LOGGER.debug("No devices found in first pass, waiting for discovery...")
            await asyncio.sleep(DISCOVERY_TIMEOUT)
            
            # Second discovery pass after waiting
            for discovery_info in async_discovered_service_info(self.hass):
                discovered_count += 1
                if (
                    discovery_info.address not in current_addresses
                    and discovery_info.address not in self._discovered_devices
                    and self._is_gocube_device(discovery_info)
                ):
                    _LOGGER.debug(
                        "Found GoCube device in second pass: %s (%s)",
                        discovery_info.name,
                        discovery_info.address,
                    )
                    self._discovered_devices[discovery_info.address] = discovery_info

        _LOGGER.debug(
            "Discovery complete. Examined %s devices, found %s GoCube devices",
            discovered_count,
            len(self._discovered_devices),
        )

        if not self._discovered_devices:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors={"base": "no_devices_found"},
                description_placeholders={
                    "title": "No GoCube devices found",
                    "description": "Please make sure your GoCube is turned on and in range.",
                },
            )

        if user_input is not None:
            address = user_input.get(CONF_ADDRESS)
            if address:
                await self.async_set_unique_id(address, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                discovery_info = self._discovered_devices[address]
                return self.async_create_entry(
                    title=discovery_info.name,
                    data={
                        CONF_ADDRESS: address,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(
                    {
                        address: f"{discovery_info.name} ({address})"
                        for address, discovery_info in self._discovered_devices.items()
                    }
                )
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
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
