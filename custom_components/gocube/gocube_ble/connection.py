"""Thin BLE connection wrapper for GoCube.

This module handles only the Bleak connection lifecycle: connect, disconnect,
send commands, and receive notifications. All reconnect policy, debouncing,
and HA-specific logic belongs in the integration layer.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .const import (
    CONFIGURATION_COMMANDS,
    FACE_ROTATION_MAP,
    RX_CHARACTERISTIC_UUID,
    TX_CHARACTERISTIC_UUID,
)
from .models import GoCubeData
from .parser import GoCubeDataParser

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 20.0


class GoCubeConnection:
    """Thin BLE connection wrapper for GoCube.

    Manages a single BleakClient connection. Callbacks are invoked from
    Bleak's notification thread — callers are responsible for thread safety.
    """

    def __init__(
        self,
        on_state_changed: Callable[[], None] | None = None,
        on_movement: Callable[[str], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the connection.

        Args:
            on_state_changed: Called when cube data changes (battery, state, etc).
                              Called from Bleak's notification thread.
            on_movement: Called with rotation description on each face rotation.
                         Called from Bleak's notification thread.
            on_disconnected: Called when the BLE connection drops.
                             Called from Bleak's callback thread.
        """
        self._client: BleakClient | None = None
        self._write_char: str | None = None
        self._parser = GoCubeDataParser()
        self._is_connected = False
        self._on_state_changed = on_state_changed
        self._on_movement = on_movement
        self._on_disconnected = on_disconnected

    @property
    def is_connected(self) -> bool:
        """Return whether the BLE connection is active."""
        return self._is_connected

    @property
    def data(self) -> GoCubeData:
        """Return the current parsed data."""
        return self._parser.data

    async def connect(self, device: BLEDevice) -> None:
        """Connect to the GoCube.

        Args:
            device: A fresh BLEDevice from HA's Bluetooth manager.

        Raises:
            BleakError: If connection fails.
        """
        # Clean up any existing connection
        await self._disconnect_client()

        self._client = BleakClient(
            device,
            timeout=CONNECT_TIMEOUT,
            disconnected_callback=self._handle_disconnect,
        )

        _LOGGER.info("Connecting to GoCube %s...", device.address)
        await self._client.connect()

        # Find characteristics
        notify_char = None
        write_char = None
        for service in self._client.services:
            for char in service.characteristics:
                if char.uuid == TX_CHARACTERISTIC_UUID:
                    notify_char = char.uuid
                elif char.uuid == RX_CHARACTERISTIC_UUID:
                    write_char = char.uuid

        if not notify_char or not write_char:
            await self._disconnect_client()
            raise BleakError("Required UART characteristics not found")

        await self._client.start_notify(notify_char, self._notification_handler)
        self._write_char = write_char
        self._is_connected = True
        _LOGGER.info("Connected to GoCube %s", device.address)

    async def disconnect(self) -> None:
        """Disconnect from the GoCube."""
        await self._disconnect_client()

    async def send_command(self, command_name: str) -> None:
        """Send a named command to the GoCube.

        Silently returns if not connected.

        Raises:
            ValueError: If command_name is not a known command.
        """
        if not self._is_connected or not self._client or not self._write_char:
            _LOGGER.debug("Cannot send '%s': not connected", command_name)
            return

        command_data = CONFIGURATION_COMMANDS.get(command_name)
        if command_data is None:
            raise ValueError(f"Unknown command: {command_name}")

        try:
            await self._client.write_gatt_char(self._write_char, command_data)
            _LOGGER.debug("Sent command: %s", command_name)
        except BleakError as err:
            _LOGGER.debug("Failed to send %s: %s", command_name, err)

    async def send_raw(self, data: bytearray) -> None:
        """Send raw bytes to the GoCube.

        Silently returns if not connected.
        """
        if not self._is_connected or not self._client or not self._write_char:
            _LOGGER.debug("Cannot send raw data: not connected")
            return

        try:
            await self._client.write_gatt_char(self._write_char, data)
            _LOGGER.debug("Sent raw: %s", data.hex())
        except BleakError as err:
            _LOGGER.debug("Failed to send raw data: %s", err)

    async def _disconnect_client(self) -> None:
        """Disconnect and clean up the BleakClient."""
        self._is_connected = False
        if self._client is not None:
            try:
                if self._client.is_connected:
                    try:
                        await self._client.stop_notify(TX_CHARACTERISTIC_UUID)
                    except Exception:
                        pass
                    await self._client.disconnect()
            except Exception as err:
                _LOGGER.debug("Error during disconnect: %s", err)
            finally:
                self._client = None
                self._write_char = None

    def _handle_disconnect(self, client: BleakClient) -> None:
        """Handle BLE disconnection callback from Bleak."""
        _LOGGER.info("GoCube disconnected")
        self._is_connected = False
        if self._on_disconnected:
            self._on_disconnected()

    def _notification_handler(self, sender: Any, data: bytearray) -> None:
        """Handle BLE notifications from the GoCube.

        Called from Bleak's notification thread.
        """
        try:
            handled = self._parser.parse_message(data)

            if "rotation" in handled:
                if self._on_movement and self._parser.data.last_move:
                    self._on_movement(self._parser.data.last_move)

            if any(t in handled for t in ("state", "battery", "orientation", "stats", "cube_type")):
                if self._on_state_changed:
                    self._on_state_changed()
        except Exception as err:
            _LOGGER.error("Error handling notification: %s", err)
