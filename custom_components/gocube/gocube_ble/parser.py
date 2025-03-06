"""Parser for GoCube data."""

from __future__ import annotations

import logging
from typing import Any, Callable, Set

from .const import (
    COLOR_HEX_LOOKUP,
    MSG_TYPE_BATTERY,
    MSG_TYPE_STATE,
    MSG_TYPE_ORIENTATION,
    MSG_TYPE_ROTATION,
)
from .models import GoCubeData

_LOGGER = logging.getLogger(__name__)


class GoCubeDataParser:
    """Parser for GoCube data."""

    def __init__(self) -> None:
        """Initialize the parser."""
        self.data = GoCubeData()
        self._state_callbacks: Set[Callable[[], None]] = set()
        self._movement_callbacks: Set[Callable[[str], None]] = set()

    def parse_state_message(self, data: bytearray) -> None:
        """Parse state message."""
        if len(data) >= 60:
            state_data = data[3:]  # Start parsing from offset 3
            face_data = [state_data[i : i + 9] for i in range(0, 54, 9)]

            # Update each face's solved state
            for i, colors in enumerate(face_data):
                face_name = list(COLOR_HEX_LOOKUP.values())[i]
                face_colors = [COLOR_HEX_LOOKUP.get(byte) for byte in colors[1:]]
                self.data.face_states[face_name] = self._is_face_solved(face_colors)
                _LOGGER.debug(
                    "%s Face: %s",
                    face_name,
                    "Solved" if self.data.face_states[face_name] else "Not Solved",
                )

            # Check if all faces are solved
            self.data.is_solved = all(self.data.face_states.values())
            if self.data.is_solved:
                _LOGGER.debug("🎉 Cube Solved! 🎉")
            else:
                _LOGGER.debug("Cube Not Solved Yet")

            self._notify_state_change()

    def parse_battery_message(self, data: bytearray) -> None:
        """Parse battery message."""
        if len(data) >= 5:
            battery_level = data[3]
            checksum = sum(data[:4]) % 0x100
            if checksum == data[4]:
                self.data.battery_level = battery_level
                _LOGGER.debug("Updated battery level: %d%%", self.data.battery_level)
            else:
                _LOGGER.debug("Invalid battery status checksum")

    def parse_orientation_message(self, data: bytearray) -> None:
        """Parse orientation message."""
        if len(data) >= 5:
            # Orientation messages are used to track the cube's physical orientation
            # We don't need to store this data, but we should acknowledge receipt
            _LOGGER.debug("Received orientation update")

    def _is_face_solved(self, face_colors: list[str]) -> bool:
        """Check if a face is solved (all colors match the center)."""
        return all(color == face_colors[0] for color in face_colors)

    def _notify_state_change(self) -> None:
        """Notify all state callbacks."""
        for callback in self._state_callbacks:
            try:
                callback()
            except Exception as err:
                _LOGGER.error("Error in state callback: %s", err)

    def update(self, data: bytes) -> None:
        """Update the data."""
        try:
            # Parse the data
            if len(data) < 5:  # Minimum length for a valid message
                _LOGGER.debug("Message too short: %s", data.hex())
                return

            # Get message type
            msg_type = data[2] if len(data) > 2 else None
            _LOGGER.debug("Message type: %02x", msg_type)

            # Handle different message types
            if msg_type == MSG_TYPE_BATTERY:  # Battery
                self.parse_battery_message(data)
            elif msg_type == MSG_TYPE_STATE:  # State
                self.parse_state_message(data)
            elif msg_type == MSG_TYPE_ORIENTATION:  # Orientation
                self.parse_orientation_message(data)
            elif msg_type == MSG_TYPE_ROTATION:  # Rotation
                # Rotation messages are handled by the connection class
                pass
            else:
                _LOGGER.debug("Unhandled message type: %02x", msg_type)
        except Exception as err:
            _LOGGER.error("Error parsing message: %s", err)
            _LOGGER.debug("Raw data: %s", data.hex())

    def add_state_callback(self, callback: Callable[[], None]) -> None:
        """Add a callback for state changes."""
        self._state_callbacks.add(callback)

    def remove_state_callback(self, callback: Callable[[], None]) -> None:
        """Remove a callback for state changes."""
        self._state_callbacks.discard(callback)

    def add_movement_callback(self, callback: Callable[[str], None]) -> None:
        """Add a callback for movement events."""
        self._movement_callbacks.add(callback)

    def remove_movement_callback(self, callback: Callable[[str], None]) -> None:
        """Remove a callback for movement events."""
        self._movement_callbacks.discard(callback)

    def _notify_movement(self, movement: str) -> None:
        """Notify all movement callbacks."""
        for callback in self._movement_callbacks:
            try:
                callback(movement)
            except Exception as err:
                _LOGGER.error("Error in movement callback: %s", err)
