"""The GoCube integration."""

from __future__ import annotations

import asyncio
import logging
import time

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_register_callback,
    async_track_unavailable,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, SIGNAL_MOVEMENT, SIGNAL_STATE_UPDATE
from .gocube_ble.ble import GoCubeConnection, GoCubeData
from .gocube_ble.models import KNOWN_PATTERNS

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = [
    "binary_sensor",
    "button",
    "event",
    "image",
    "light",
    "sensor",
    "switch",
]

RECONNECT_DELAY = 3.0
MAX_RECONNECT_ATTEMPTS = 5
STATE_UPDATE_DEBOUNCE = 0.5
STORAGE_KEY = f"{DOMAIN}_patterns"
STORAGE_VERSION = 1

SERVICE_SAVE_PATTERN = "save_pattern"
SERVICE_DELETE_PATTERN = "delete_pattern"
SERVICE_LIST_PATTERNS = "list_patterns"
ATTR_NAME = "name"

SAVE_PATTERN_SCHEMA = vol.Schema({vol.Required(ATTR_NAME): str})
DELETE_PATTERN_SCHEMA = vol.Schema({vol.Required(ATTR_NAME): str})


class PatternStore:
    """Persistent storage for user-saved cube patterns."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the pattern store."""
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._patterns: dict[str, str] = {}

    async def async_load(self) -> None:
        """Load patterns from storage."""
        data = await self._store.async_load()
        if data and isinstance(data, dict):
            self._patterns = data.get("patterns", {})

    async def async_save(self, name: str, fingerprint: str) -> None:
        """Save a pattern."""
        self._patterns[name] = fingerprint
        await self._store.async_save({"patterns": self._patterns})

    async def async_delete(self, name: str) -> bool:
        """Delete a pattern. Returns True if it existed."""
        if name in self._patterns:
            del self._patterns[name]
            await self._store.async_save({"patterns": self._patterns})
            return True
        return False

    @property
    def patterns(self) -> dict[str, str]:
        """Return all user-saved patterns."""
        return self._patterns

    def match(self, fingerprint: str) -> str | None:
        """Match a fingerprint against user-saved patterns."""
        for name, fp in self._patterns.items():
            if fp == fingerprint:
                return name
        return None


class GoCubeCoordinator:
    """Manages the GoCube BLE connection lifecycle for Home Assistant.

    Implements the Yale BLE lock pattern: advertisement-triggered on-demand
    connection for a battery-powered active-GATT device.
    """

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.address = address
        self.connection = GoCubeConnection(
            on_state_changed=self._on_state_changed,
            on_movement=self._on_movement,
            on_disconnected=self._on_disconnected,
        )
        self._has_been_seen = False
        self._should_auto_reconnect = True
        self._reconnect_task: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self._last_state_request = 0.0
        self._pending_state_update = False

    @property
    def data(self) -> GoCubeData:
        """Return the current cube data."""
        return self.connection.data

    @property
    def is_connected(self) -> bool:
        """Return whether the cube is currently connected."""
        return self.connection.is_connected

    @property
    def has_been_seen(self) -> bool:
        """Return whether we've ever received data from this cube."""
        return self._has_been_seen

    @property
    def should_auto_reconnect(self) -> bool:
        """Return whether auto-reconnect is enabled."""
        return self._should_auto_reconnect

    @should_auto_reconnect.setter
    def should_auto_reconnect(self, value: bool) -> None:
        """Set whether auto-reconnect is enabled."""
        self._should_auto_reconnect = value

    async def async_connect(self) -> None:
        """Try to connect to the cube using a fresh BLEDevice from HA."""
        device = async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            _LOGGER.debug("GoCube %s not available for connection", self.address)
            return
        await self.connection.connect(device)
        # Request initial data
        await self.connection.send_command("GetBattery")
        await self.connection.send_command("GetState")
        await self.connection.send_command("GetCubeType")
        await self.connection.send_command("DisableOrientation")

    async def async_disconnect(self) -> None:
        """Disconnect and cancel all background tasks."""
        self._cancel_reconnect()
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()
        await self.connection.disconnect()

    async def async_request_state_update(self) -> None:
        """Request a state update with debouncing."""
        now = time.monotonic()
        if now - self._last_state_request < STATE_UPDATE_DEBOUNCE:
            if not self._pending_state_update:
                self._pending_state_update = True
                self._create_task(self._async_debounced_state_update())
            return
        self._last_state_request = now
        await self.connection.send_command("GetState")

    def handle_advertisement(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Handle BLE advertisement — cube has woken up.

        Called by HA's Bluetooth manager when the cube advertises.
        """
        if not self.connection.is_connected:
            _LOGGER.debug("GoCube advertisement seen, scheduling connection")
            self._schedule_connect()

    def handle_unavailable(self, service_info: BluetoothServiceInfoBleak) -> None:
        """Handle cube becoming unavailable — no advertisements for a while."""
        _LOGGER.debug("GoCube %s marked unavailable by HA Bluetooth", self.address)
        self._dispatch_state_update()

    # --- Private helpers ---

    def _on_state_changed(self) -> None:
        """Handle state change from BLE notification thread."""
        self._has_been_seen = True
        self.hass.loop.call_soon_threadsafe(self._dispatch_state_update)

    def _on_movement(self, movement: str) -> None:
        """Handle rotation from BLE notification thread."""
        self._has_been_seen = True
        self.hass.loop.call_soon_threadsafe(self._dispatch_movement, movement)
        # Request updated face state after rotation
        self.hass.loop.call_soon_threadsafe(
            self._create_task_from_loop, self.async_request_state_update()
        )

    def _on_disconnected(self) -> None:
        """Handle BLE disconnection from Bleak's callback thread."""
        self.hass.loop.call_soon_threadsafe(self._handle_disconnect_on_loop)

    def _handle_disconnect_on_loop(self) -> None:
        """Process disconnection on the event loop."""
        self._dispatch_state_update()
        if self._should_auto_reconnect:
            self._schedule_reconnect()

    def _dispatch_state_update(self) -> None:
        """Send state update signal to all entities."""
        async_dispatcher_send(
            self.hass, f"{SIGNAL_STATE_UPDATE}_{self.address}"
        )

    def _dispatch_movement(self, movement: str) -> None:
        """Send movement signal to event entities."""
        async_dispatcher_send(
            self.hass, f"{SIGNAL_MOVEMENT}_{self.address}", movement
        )

    def _schedule_connect(self) -> None:
        """Schedule a connection attempt on the event loop."""
        self._cancel_reconnect()
        self._reconnect_task = self._create_task(self._async_try_connect())

    def _schedule_reconnect(self) -> None:
        """Schedule reconnection with exponential backoff."""
        self._cancel_reconnect()
        self._reconnect_task = self._create_task(self._async_reconnect_loop())

    def _cancel_reconnect(self) -> None:
        """Cancel any pending reconnect task."""
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None

    async def _async_try_connect(self) -> None:
        """Try to connect once."""
        try:
            await self.async_connect()
        except Exception as err:
            _LOGGER.debug("Connection attempt failed: %s", err)

    async def _async_reconnect_loop(self) -> None:
        """Reconnect with exponential backoff."""
        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            if not self._should_auto_reconnect:
                return
            delay = RECONNECT_DELAY * (attempt + 1)
            _LOGGER.debug(
                "Reconnect attempt %d/%d in %.0fs",
                attempt + 1,
                MAX_RECONNECT_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)
            if not self._should_auto_reconnect:
                return
            try:
                await self.async_connect()
                return
            except Exception as err:
                _LOGGER.debug("Reconnect attempt %d failed: %s", attempt + 1, err)

        _LOGGER.warning(
            "Failed to reconnect to GoCube after %d attempts",
            MAX_RECONNECT_ATTEMPTS,
        )

    async def _async_debounced_state_update(self) -> None:
        """Send a debounced GetState command."""
        await asyncio.sleep(STATE_UPDATE_DEBOUNCE)
        if self._pending_state_update:
            self._pending_state_update = False
            self._last_state_request = time.monotonic()
            await self.connection.send_command("GetState")

    def _create_task(self, coro) -> asyncio.Task:
        """Create a tracked background task."""
        task = self.hass.async_create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _create_task_from_loop(self, coro) -> None:
        """Create a tracked background task (must be called from event loop)."""
        self._create_task(coro)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GoCube from a config entry."""
    address = entry.data[CONF_ADDRESS]
    coordinator = GoCubeCoordinator(hass, address)

    # Try to connect now — may fail if cube is asleep, and that's OK
    try:
        await coordinator.async_connect()
    except Exception as err:
        _LOGGER.info("GoCube not available at startup (will connect on wake): %s", err)

    # Register for BLE advertisement callbacks (cube waking up)
    entry.async_on_unload(
        async_register_callback(
            hass,
            coordinator.handle_advertisement,
            BluetoothCallbackMatcher(address=address),
            BluetoothChange.ADVERTISEMENT,
        )
    )

    # Register for unavailability tracking (cube going to sleep)
    entry.async_on_unload(
        async_track_unavailable(
            hass,
            coordinator.handle_unavailable,
            address,
            connectable=True,
        )
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: GoCubeCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_disconnect()
    return unload_ok


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the GoCube integration."""
    pattern_store = PatternStore(hass)
    await pattern_store.async_load()
    hass.data.setdefault(DOMAIN, {})["pattern_store"] = pattern_store

    def _get_coordinator() -> GoCubeCoordinator | None:
        """Get the first active coordinator."""
        for key, val in hass.data.get(DOMAIN, {}).items():
            if isinstance(val, GoCubeCoordinator):
                return val
        return None

    async def handle_save_pattern(call: ServiceCall) -> None:
        """Handle save_pattern service call."""
        name = call.data[ATTR_NAME]
        coordinator = _get_coordinator()
        if coordinator is None:
            _LOGGER.error("No GoCube connected")
            return
        fingerprint = coordinator.data.state_fingerprint
        if fingerprint is None:
            _LOGGER.error("No cube state available to save")
            return
        await pattern_store.async_save(name, fingerprint)
        _LOGGER.info("Saved pattern '%s': %s", name, fingerprint)
        # Trigger update so pattern sensor refreshes
        coordinator._dispatch_state_update()

    async def handle_delete_pattern(call: ServiceCall) -> None:
        """Handle delete_pattern service call."""
        name = call.data[ATTR_NAME]
        if await pattern_store.async_delete(name):
            _LOGGER.info("Deleted pattern '%s'", name)
            coordinator = _get_coordinator()
            if coordinator:
                coordinator._dispatch_state_update()
        else:
            _LOGGER.warning("Pattern '%s' not found", name)

    async def handle_list_patterns(call: ServiceCall) -> None:
        """Handle list_patterns service call."""
        lines = ["**Built-in patterns:**\n"]
        for name, fp in KNOWN_PATTERNS.items():
            lines.append(f"- **{name}**: `{fp}`")
            _LOGGER.info("Built-in: %s: %s", name, fp)

        if pattern_store.patterns:
            lines.append("\n**Saved patterns:**\n")
            for name, fp in pattern_store.patterns.items():
                lines.append(f"- **{name}**: `{fp}`")
                _LOGGER.info("Saved: %s: %s", name, fp)
        else:
            lines.append("\n*No saved patterns.*")

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "GoCube Patterns",
                "message": "\n".join(lines),
                "notification_id": "gocube_patterns",
            },
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SAVE_PATTERN, handle_save_pattern, schema=SAVE_PATTERN_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_PATTERN, handle_delete_pattern, schema=DELETE_PATTERN_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_LIST_PATTERNS, handle_list_patterns
    )

    return True
