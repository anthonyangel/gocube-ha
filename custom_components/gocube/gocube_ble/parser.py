"""Parser for GoCube BLE protocol messages."""

from __future__ import annotations

import logging
import struct

from .const import (
    COLOR_HEX_LOOKUP,
    FACE_ROTATION_MAP,
    MSG_PREFIX,
    MSG_SUFFIX,
    MSG_TYPE_BATTERY,
    MSG_TYPE_CUBE_TYPE,
    MSG_TYPE_ORIENTATION,
    MSG_TYPE_ROTATION,
    MSG_TYPE_STATE,
    MSG_TYPE_STATS,
)
from .models import CubeStats, GoCubeData, Orientation

_LOGGER = logging.getLogger(__name__)


class GoCubeDataParser:
    """Parser for GoCube BLE protocol messages.

    This parser is stateful — it accumulates data across messages
    and persists last-known values across connection cycles.
    """

    def __init__(self) -> None:
        """Initialize the parser."""
        self.data = GoCubeData()

    def parse_message(self, raw: bytearray) -> list[str]:
        """Parse a raw BLE notification and return list of message types handled.

        Returns a list of message type strings that were successfully parsed,
        e.g. ["rotation", "state"] or ["battery"].
        """
        handled: list[str] = []

        if len(raw) < 3:
            _LOGGER.debug("Message too short (%d bytes): %s", len(raw), raw.hex())
            return handled

        # Validate frame prefix if present
        if raw[0] == MSG_PREFIX:
            data = raw
        else:
            _LOGGER.debug("Message missing prefix (0x%02x): %s", raw[0], raw.hex())
            data = raw

        msg_type = data[2]

        if msg_type == MSG_TYPE_ROTATION:
            rotations = self._parse_rotation_message(data)
            if rotations:
                handled.append("rotation")
        elif msg_type == MSG_TYPE_STATE:
            if self._parse_state_message(data):
                handled.append("state")
        elif msg_type == MSG_TYPE_ORIENTATION:
            if self._parse_orientation_message(data):
                handled.append("orientation")
        elif msg_type == MSG_TYPE_BATTERY:
            if self._parse_battery_message(data):
                handled.append("battery")
        elif msg_type == MSG_TYPE_STATS:
            if self._parse_stats_message(data):
                handled.append("stats")
        elif msg_type == MSG_TYPE_CUBE_TYPE:
            if self._parse_cube_type_message(data):
                handled.append("cube_type")
        else:
            _LOGGER.debug("Unknown message type: 0x%02x data=%s", msg_type, data.hex())

        return handled

    def _parse_rotation_message(self, data: bytearray) -> list[str]:
        """Parse rotation message.

        Format: [prefix, len, 0x01, face_byte, ...trailing bytes]
        The face rotation byte is at index 3. Remaining bytes are
        counters/checksums.

        Returns list of rotation descriptions.
        """
        rotations: list[str] = []
        if len(data) < 4:
            return rotations

        rotation_byte = data[3]
        desc = FACE_ROTATION_MAP.get(rotation_byte)
        if desc:
            rotations.append(desc)
            self.data.last_move = desc
            _LOGGER.debug("Rotation: %s (0x%02x)", desc, rotation_byte)
        else:
            _LOGGER.debug(
                "Unknown rotation byte: 0x%02x data=%s", rotation_byte, data.hex()
            )

        return rotations

    def _parse_state_message(self, data: bytearray) -> bool:
        """Parse state message with per-sticker color data.

        Each face block is 9 bytes: [center_color, s0, s1, s2, s3, s4, s5, s6, s7]
        The center byte identifies which face this block belongs to.
        Sticker order (looking at face straight-on):
          s0 s1 s2
          s3  C s4
          s5 s6 s7
        """
        if len(data) < 57:  # prefix + len + type + 54 color bytes
            _LOGGER.debug("State message too short: %d bytes", len(data))
            return False

        state_data = data[3:]

        for i in range(6):
            offset = i * 9
            if offset + 9 > len(state_data):
                break

            face_bytes = state_data[offset : offset + 9]

            # Use byte 0 (center color) to identify which face this is
            center_byte = face_bytes[0]
            face_name = COLOR_HEX_LOOKUP.get(center_byte)
            if face_name is None:
                _LOGGER.debug(
                    "Unknown center color 0x%02x in face block %d: %s",
                    center_byte, i, face_bytes.hex(),
                )
                continue

            center_color = face_name
            surround_colors = [
                COLOR_HEX_LOOKUP.get(b, "Unknown") for b in face_bytes[1:]
            ]

            # Surrounding stickers are in clockwise order:
            # s0=UL, s1=U, s2=UR, s3=R, s4=DR, s5=D, s6=DL, s7=L
            # Reconstruct 3x3 grid in row-major order:
            sticker_grid = [
                surround_colors[0],  # UL
                surround_colors[1],  # U
                surround_colors[2],  # UR
                surround_colors[7],  # L
                center_color,        # Center
                surround_colors[3],  # R
                surround_colors[6],  # DL
                surround_colors[5],  # D
                surround_colors[4],  # DR
            ]

            self.data.face_colors[face_name] = sticker_grid

            # Check if face is solved (all stickers same color)
            is_solved = all(c == sticker_grid[0] for c in sticker_grid)
            self.data.face_states[face_name] = is_solved

            _LOGGER.debug(
                "%s face (block %d): %s raw=%s",
                face_name,
                i,
                "Solved" if is_solved else "Not solved",
                face_bytes.hex(),
            )

        self.data.is_solved = all(self.data.face_states.values())
        if self.data.is_solved:
            _LOGGER.debug("Cube solved!")

        return True

    def _parse_battery_message(self, data: bytearray) -> bool:
        """Parse battery message with checksum validation."""
        if len(data) < 5:
            return False

        battery_level = data[3]
        checksum = sum(data[:4]) % 0x100
        if checksum != data[4]:
            _LOGGER.debug("Invalid battery checksum")
            return False

        self.data.battery_level = battery_level
        _LOGGER.debug("Battery level: %d%%", battery_level)
        return True

    def _parse_orientation_message(self, data: bytearray) -> bool:
        """Parse orientation quaternion message.

        The GoCube sends orientation as 4 signed int16 values (little-endian)
        representing the quaternion (x, y, z, w) scaled by 16384.
        """
        if len(data) < 11:  # prefix + len + type + 8 bytes (4 x int16)
            _LOGGER.debug("Orientation message too short: %d bytes", len(data))
            return False

        try:
            # Parse 4 signed int16 values from bytes 3-10
            x_raw, y_raw, z_raw, w_raw = struct.unpack_from("<hhhh", data, 3)
            scale = 16384.0
            self.data.orientation = Orientation(
                x=x_raw / scale,
                y=y_raw / scale,
                z=z_raw / scale,
                w=w_raw / scale,
            )
            _LOGGER.debug(
                "Orientation: x=%.3f y=%.3f z=%.3f w=%.3f",
                self.data.orientation.x,
                self.data.orientation.y,
                self.data.orientation.z,
                self.data.orientation.w,
            )
            return True
        except struct.error as err:
            _LOGGER.debug("Failed to parse orientation: %s", err)
            return False

    def _parse_stats_message(self, data: bytearray) -> bool:
        """Parse session statistics message."""
        if len(data) < 7:
            _LOGGER.debug("Stats message too short: %d bytes", len(data))
            return False

        try:
            solve_count = data[3]
            # Total solve time as uint16 (milliseconds)
            total_time = struct.unpack_from("<H", data, 4)[0]
            self.data.stats = CubeStats(
                solve_count=solve_count,
                total_solve_time_ms=total_time,
            )
            _LOGGER.debug(
                "Stats: %d solves, %d ms total",
                solve_count,
                total_time,
            )
            return True
        except (struct.error, IndexError) as err:
            _LOGGER.debug("Failed to parse stats: %s", err)
            return False

    def _parse_cube_type_message(self, data: bytearray) -> bool:
        """Parse cube type/model identification message."""
        if len(data) < 4:
            return False

        type_byte = data[3]
        type_map = {
            0x00: "GoCube",
            0x01: "GoCube Edge",
            0x02: "GoCube Pro",
            0x35: "GoCube",
        }
        self.data.cube_type = type_map.get(type_byte, f"Unknown (0x{type_byte:02x})")
        _LOGGER.debug("Cube type: %s", self.data.cube_type)
        return True
