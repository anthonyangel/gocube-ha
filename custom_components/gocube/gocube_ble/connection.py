"""Connection management for GoCube."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional, Set

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .const import (
    CONFIGURATION_COMMANDS,
    FACE_ROTATION_MAP,
    MSG_TYPE_BATTERY,
    MSG_TYPE_ROTATION,
    MSG_TYPE_STATE,
    RX_CHARACTERISTIC_UUID,
    TX_CHARACTERISTIC_UUID,
    PRIMARY_SERVICE_UUID,
)
from .parser import GoCubeDataParser

_LOGGER = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds
CONNECT_TIMEOUT = 20.0  # seconds
DISCONNECT_TIMEOUT = 10.0  # seconds
SCAN_TIMEOUT = 5.0  # seconds
CLEANUP_DELAY = 1.0  # seconds


class GoCubeConnection:
    """Manager for GoCube Bluetooth connection."""

    def __init__(self) -> None:
        """Initialize the connection manager."""
        self._client: Optional[BleakClient] = None
        self._characteristic: Optional[str] = None
        self._data_parser = GoCubeDataParser()
        self._is_connected = False
        self._device: Optional[BLEDevice] = None
        self._response_event: Optional[asyncio.Event] = None
        self._state_callbacks: Set[Callable[[], None]] = set()
        self._movement_callbacks: Set[Callable[[str], None]] = set()
        self._connection_lock = asyncio.Lock()
        self._last_state_update = 0
        self._state_update_interval = 0.5  # seconds
        self._pending_state_update = False
        self._should_auto_reconnect = True  # New property to control auto-reconnection

    @property
    def should_auto_reconnect(self) -> bool:
        """Return whether the connection should auto-reconnect."""
        return self._should_auto_reconnect

    @should_auto_reconnect.setter
    def should_auto_reconnect(self, value: bool) -> None:
        """Set whether the connection should auto-reconnect."""
        self._should_auto_reconnect = value

    @property
    def data(self) -> GoCubeData:
        """Get the current data from the parser."""
        return self._data_parser.data

    async def __aenter__(self) -> "GoCubeConnection":
        """Set up the async context manager."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Clean up the async context manager."""
        await self.disconnect()

    async def _find_device(self, address: str) -> Optional[BLEDevice]:
        """Find the GoCube device by scanning.

        Args:
            address: The MAC address of the device

        Returns:
            Optional[BLEDevice]: The found device or None if not found
        """
        _LOGGER.info("Scanning for GoCube device %s", address)
        scanner = BleakScanner()
        try:
            devices = await scanner.discover(timeout=SCAN_TIMEOUT)
            for device in devices:
                if device.address == address:
                    _LOGGER.info(
                        "Found GoCube device: %s", device.name or device.address
                    )
                    return device
            _LOGGER.warning("GoCube device %s not found during scan", address)
            return None
        except Exception as err:
            _LOGGER.error("Error scanning for device: %s", err)
            return None

    async def _cleanup_connection(self) -> None:
        """Clean up any existing connection."""
        if self._client is not None:
            try:
                # Stop notifications before disconnecting
                try:
                    await self._client.stop_notify(TX_CHARACTERISTIC_UUID)
                except Exception:
                    pass
                await self._client.disconnect()
                _LOGGER.info("Cleaned up existing connection")
            except Exception as err:
                _LOGGER.error("Error during connection cleanup: %s", err)
            finally:
                self._client = None
                self._characteristic = None
                self._is_connected = False
                self._device = None
                # Reset parser data
                self._data_parser = GoCubeDataParser()
                # Notify callbacks of disconnection
                for callback in self._state_callbacks:
                    callback()
                await asyncio.sleep(CLEANUP_DELAY)  # Wait for cleanup to complete

    async def connect(self, device: BLEDevice) -> None:
        """Connect to the GoCube with retry logic."""
        async with self._connection_lock:
            retry_count = 0
            while retry_count < MAX_RETRIES:
                try:
                    # Clean up any existing connection first
                    await self._cleanup_connection()

                    self._device = device
                    self._client = BleakClient(device, timeout=CONNECT_TIMEOUT)

                    _LOGGER.info(
                        "Attempting to connect to GoCube (attempt %d/%d)...",
                        retry_count + 1,
                        MAX_RETRIES,
                    )

                    await self._client.connect()
                    _LOGGER.debug("Connected to GoCube")

                    # Find the characteristics
                    notify_char = None
                    write_char = None

                    for service in self._client.services:
                        for char in service.characteristics:
                            if (
                                char.uuid == TX_CHARACTERISTIC_UUID
                            ):  # Notification characteristic
                                notify_char = char.uuid
                            elif (
                                char.uuid == RX_CHARACTERISTIC_UUID
                            ):  # Write characteristic
                                write_char = char.uuid

                    if not notify_char or not write_char:
                        raise BleakError("Required characteristics not found")

                    # Set up notification handler
                    await self._client.start_notify(
                        notify_char,
                        self._notification_handler,
                    )

                    self._characteristic = (
                        write_char  # Store write characteristic for sending commands
                    )
                    self._is_connected = True

                    # Disable orientation updates
                    await self.send_command("DisableOrientation")
                    _LOGGER.debug("Disabled orientation updates")

                    # Notify callbacks of successful connection
                    for callback in self._state_callbacks:
                        callback()

                    return  # Successfully connected

                except Exception as err:
                    _LOGGER.error(
                        "Failed to connect to GoCube (attempt %d/%d): %s",
                        retry_count + 1,
                        MAX_RETRIES,
                        err,
                    )
                    await self._cleanup_connection()
                    retry_count += 1
                    if retry_count < MAX_RETRIES:
                        await asyncio.sleep(RETRY_DELAY)
                    else:
                        raise

    def _handle_disconnect(self, client: BleakClient) -> None:
        """Handle disconnection event."""
        self._is_connected = False
        self._notify_state_change()
        
        if self._should_auto_reconnect and self._device:
            _LOGGER.debug("Device disconnected, scheduling reconnection")
            asyncio.create_task(self._auto_reconnect())
        else:
            _LOGGER.debug("Device disconnected, auto-reconnect disabled")

    async def _auto_reconnect(self) -> None:
        """Attempt to reconnect to the device."""
        if not self._should_auto_reconnect or not self._device:
            return

        for attempt in range(MAX_RETRIES):
            try:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                if not self._should_auto_reconnect:
                    _LOGGER.debug("Auto-reconnect cancelled")
                    return
                _LOGGER.debug("Attempting to reconnect (attempt %d/%d)", attempt + 1, MAX_RETRIES)
                await self.connect(self._device)
                return
            except Exception as err:
                _LOGGER.debug("Reconnection attempt failed: %s", err)

        _LOGGER.warning("Failed to reconnect after %d attempts", MAX_RETRIES)

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        self._should_auto_reconnect = False  # Disable auto-reconnect before disconnecting
        if self._client:
            await self._client.disconnect()
        await self._cleanup_connection()

    async def enable_notifications(self) -> None:
        """Enable notifications from the GoCube."""
        try:
            await self._client.start_notify(
                TX_CHARACTERISTIC_UUID,
                self._notification_handler,
            )
            _LOGGER.info("Notifications enabled")
        except BleakError as err:
            _LOGGER.error("Failed to enable notifications: %s", err)
            raise

    def register_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for state changes."""

        def unsubscribe() -> None:
            """Unsubscribe from state changes."""
            if callback in self._state_callbacks:
                self._state_callbacks.remove(callback)

        self._state_callbacks.add(callback)
        return unsubscribe

    def _notify_state_change(self) -> None:
        """Notify all state callbacks."""
        _LOGGER.debug("Notifying %d state callbacks", len(self._state_callbacks))
        for callback in self._state_callbacks:
            try:
                callback()
            except Exception as err:
                _LOGGER.error("Error in state callback: %s", err)

    def add_movement_callback(self, callback: Callable[[str], None]) -> None:
        """Add a callback for movement events."""
        self._movement_callbacks.add(callback)

    def remove_movement_callback(self, callback: Callable[[str], None]) -> None:
        """Remove a callback for movement events."""
        self._movement_callbacks.discard(callback)

    async def send_command(self, command_name: str) -> None:
        """Send a command to the GoCube."""
        if not self._is_connected or self._characteristic is None:
            _LOGGER.debug("Cannot send command '%s': device is disconnected", command_name)
            return  # Silently return instead of raising an error

        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Cannot send command '%s': connection lost", command_name)
            return  # Silently return instead of raising an error

        command_data = CONFIGURATION_COMMANDS.get(command_name)
        if command_data is None:
            raise ValueError(f"Unknown command: {command_name}")

        try:
            # Debounce GetState commands
            if command_name == "GetState":
                current_time = time.time()
                if current_time - self._last_state_update < self._state_update_interval:
                    if not self._pending_state_update:
                        self._pending_state_update = True
                        asyncio.create_task(self._send_debounced_state_update())
                    return
                self._last_state_update = current_time

            await self._client.write_gatt_char(self._characteristic, command_data)
            _LOGGER.debug("Sent command: %s", command_name)
        except Exception as err:
            _LOGGER.debug("Failed to send command %s: %s", command_name, err)  # Changed to debug level
            # Don't raise the error, just log it

    async def _send_debounced_state_update(self) -> None:
        """Send a debounced GetState command."""
        await asyncio.sleep(self._state_update_interval)
        if self._pending_state_update:
            try:
                await self.send_command("GetState")
            finally:
                self._pending_state_update = False

    def _notification_handler(self, sender: int, data: bytearray) -> None:
        """Handle notifications from the GoCube."""
        try:
            if len(data) < 3:
                return

            message_type = data[2]
            if message_type == MSG_TYPE_ROTATION:  # Rotation
                face_rotation = data[3]
                face_rotation_desc = FACE_ROTATION_MAP.get(face_rotation, "Unknown")
                _LOGGER.debug("Rotation: %s", face_rotation_desc)
                for callback in self._movement_callbacks:
                    callback(face_rotation_desc)
                # Get state after rotation
                asyncio.create_task(self.send_command("GetState"))
            elif message_type == MSG_TYPE_STATE:  # State
                self._data_parser.parse_state_message(data)
                _LOGGER.debug("State updated, notifying callbacks")
                self._notify_state_change()
            elif message_type == MSG_TYPE_BATTERY:  # Battery
                self._data_parser.parse_battery_message(data)
                _LOGGER.debug("Battery updated, notifying callbacks")
                self._notify_state_change()
            else:
                _LOGGER.debug("Unknown message type: %02x", message_type)
        except Exception as err:
            _LOGGER.error("Error handling notification: %s", err)

    async def get_battery_level(self) -> Optional[int]:
        """Get the battery level from the GoCube."""
        try:
            # Send GetBattery command
            await self.send_command("GetBattery")

            # Wait for response
            start_time = time.time()
            while time.time() - start_time < 1.0:
                if self._data_parser.data.battery_level is not None:
                    return self._data_parser.data.battery_level
                await asyncio.sleep(0.1)

            return None
        except Exception as err:
            _LOGGER.error("Failed to get battery level: %s", err)
            return None

    # LED Control Methods
    async def led_flash(self) -> None:
        """Flash the backlight three times."""
        await self.send_command("LedFlash")

    async def led_toggle_animation(self) -> None:
        """Enable or disable animated backlight."""
        await self.send_command("LedToggleAnimation")

    async def led_flash_slow(self) -> None:
        """Slowly flash the backlight three times."""
        await self.send_command("LedFlashSlow")

    async def led_toggle(self) -> None:
        """Toggle backlight."""
        await self.send_command("LedToggle")

    async def enable_auto_reconnect(self) -> None:
        """Enable auto-reconnect feature."""
        was_disabled = not self._should_auto_reconnect
        self._should_auto_reconnect = True
        
        # If auto-reconnect was disabled and we're not connected, try to reconnect immediately
        if was_disabled and not self._is_connected and self._device:
            _LOGGER.debug("Auto-reconnect enabled, attempting immediate reconnection")
            await self._auto_reconnect()
        else:
            _LOGGER.debug("Auto-reconnect enabled, device is already connected or no device info available")
