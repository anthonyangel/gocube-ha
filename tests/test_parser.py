"""Tests for GoCube BLE protocol parser."""

import struct

import pytest

from gocube_ble.const import (
    MSG_TYPE_BATTERY,
    MSG_TYPE_CUBE_TYPE,
    MSG_TYPE_ORIENTATION,
    MSG_TYPE_ROTATION,
    MSG_TYPE_STATE,
    MSG_TYPE_STATS,
)
from gocube_ble.parser import GoCubeDataParser


@pytest.fixture
def parser():
    """Return a fresh parser instance."""
    return GoCubeDataParser()


def _make_msg(msg_type: int, payload: bytes = b"") -> bytearray:
    """Build a minimal GoCube message: [prefix, length, type, ...payload]."""
    prefix = 0x2A
    length = len(payload) + 1  # type byte + payload
    return bytearray([prefix, length, msg_type]) + bytearray(payload)


# --- Message framing ---


class TestMessageFraming:
    def test_too_short_message(self, parser):
        result = parser.parse_message(bytearray([0x2A, 0x01]))
        assert result == []

    def test_empty_message(self, parser):
        result = parser.parse_message(bytearray())
        assert result == []

    def test_unknown_message_type(self, parser):
        result = parser.parse_message(_make_msg(0xFF))
        assert result == []

    def test_message_without_prefix(self, parser):
        """Messages without 0x2A prefix are still processed (type at index 2)."""
        msg = bytearray([0x00, 0x04, MSG_TYPE_BATTERY, 75, 0x00])
        # Fix checksum
        msg[4] = sum(msg[:4]) % 0x100
        result = parser.parse_message(msg)
        assert "battery" in result


# --- Rotation messages ---


class TestRotation:
    def test_known_rotations(self, parser):
        """Each known rotation byte should be parsed correctly."""
        expected = {
            0x00: "Blue Clockwise",
            0x01: "Blue Counterclockwise",
            0x02: "Green Clockwise",
            0x03: "Green Counterclockwise",
            0x04: "White Clockwise",
            0x05: "White Counterclockwise",
            0x06: "Yellow Clockwise",
            0x07: "Yellow Counterclockwise",
            0x08: "Red Clockwise",
            0x09: "Red Counterclockwise",
            0x0A: "Orange Clockwise",
            0x0B: "Orange Counterclockwise",
        }
        for byte_val, desc in expected.items():
            p = GoCubeDataParser()
            result = p.parse_message(_make_msg(MSG_TYPE_ROTATION, bytes([byte_val])))
            assert "rotation" in result
            assert p.data.last_move == desc

    def test_unknown_rotation_byte(self, parser):
        result = parser.parse_message(_make_msg(MSG_TYPE_ROTATION, bytes([0xFF])))
        assert result == []
        assert parser.data.last_move is None

    def test_rotation_message_too_short(self, parser):
        """Rotation message needs at least 4 bytes (prefix, len, type, face_byte)."""
        result = parser.parse_message(bytearray([0x2A, 0x01, MSG_TYPE_ROTATION]))
        assert result == []


# --- State messages ---


def _make_solved_state() -> bytearray:
    """Build a solved cube state message (54 color bytes, all faces uniform)."""
    # 6 faces, 9 bytes each. Byte 0 = center color ID, bytes 1-8 = same color.
    state_bytes = bytearray()
    for color_id in range(6):
        state_bytes.extend([color_id] * 9)
    return _make_msg(MSG_TYPE_STATE, bytes(state_bytes))


def _make_scrambled_state() -> bytearray:
    """Build a state with the White face having a Red sticker at UL."""
    state_bytes = bytearray()
    for color_id in range(6):
        face = [color_id] * 9
        if color_id == 2:  # White face
            face[1] = 4  # Surround sticker 0 (UL) = Red
        state_bytes.extend(face)
    return _make_msg(MSG_TYPE_STATE, bytes(state_bytes))


class TestState:
    def test_solved_cube(self, parser):
        result = parser.parse_message(_make_solved_state())
        assert "state" in result
        assert parser.data.is_solved is True
        assert all(parser.data.face_states.values())
        assert len(parser.data.face_colors) == 6

    def test_face_names(self, parser):
        parser.parse_message(_make_solved_state())
        expected_faces = {"Blue", "Green", "White", "Yellow", "Red", "Orange"}
        assert set(parser.data.face_colors.keys()) == expected_faces

    def test_solved_face_colors(self, parser):
        """Each solved face should have 9 identical color entries."""
        parser.parse_message(_make_solved_state())
        for face_name, stickers in parser.data.face_colors.items():
            assert len(stickers) == 9
            assert all(c == face_name for c in stickers), f"{face_name} not uniform: {stickers}"

    def test_scrambled_face(self, parser):
        parser.parse_message(_make_scrambled_state())
        assert parser.data.is_solved is False
        # White face should not be solved
        assert parser.data.face_states["White"] is False
        # White face UL sticker should be Red
        white_stickers = parser.data.face_colors["White"]
        assert white_stickers[0] == "Red"  # UL position

    def test_sticker_grid_ordering(self, parser):
        """Verify the clockwise-to-row-major mapping.

        Surrounding bytes are clockwise: [UL, U, UR, R, DR, D, DL, L]
        Row-major grid should be:
            [UL, U, UR, L, C, R, DL, D, DR]
        """
        # Build White face with distinct stickers
        # Center=White(0x02), surround: [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x00, 0x01]
        # = [Blue, Green, White, Yellow, Red, Orange, Blue, Green]
        face_bytes = bytes([0x02, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x00, 0x01])
        # Put this as face block 0, fill rest with solved faces
        state_bytes = bytearray(face_bytes)
        for color_id in [0, 1, 3, 4, 5]:  # Skip 2 (White, already done)
            state_bytes.extend([color_id] * 9)
        msg = _make_msg(MSG_TYPE_STATE, bytes(state_bytes))
        parser.parse_message(msg)

        white = parser.data.face_colors["White"]
        # Surround clockwise: s0=Blue, s1=Green, s2=White, s3=Yellow, s4=Red, s5=Orange, s6=Blue, s7=Green
        # Grid mapping: [s0, s1, s2, s7, C, s3, s6, s5, s4]
        assert white[0] == "Blue"    # UL = s0
        assert white[1] == "Green"   # U  = s1
        assert white[2] == "White"   # UR = s2
        assert white[3] == "Green"   # L  = s7
        assert white[4] == "White"   # C  = center
        assert white[5] == "Yellow"  # R  = s3
        assert white[6] == "Blue"    # DL = s6
        assert white[7] == "Orange"  # D  = s5
        assert white[8] == "Red"     # DR = s4

    def test_state_message_too_short(self, parser):
        result = parser.parse_message(_make_msg(MSG_TYPE_STATE, b"\x00" * 10))
        assert result == []

    def test_unknown_center_color_skipped(self, parser):
        """Face blocks with unknown center color (>5) should be skipped."""
        state_bytes = bytearray([0xFF] * 9)  # Unknown center
        for color_id in range(5):
            state_bytes.extend([color_id] * 9)
        msg = _make_msg(MSG_TYPE_STATE, bytes(state_bytes))
        parser.parse_message(msg)
        assert 0xFF not in [ord(c[0]) if len(c) == 1 else -1 for c in parser.data.face_colors]

    def test_state_persists_across_messages(self, parser):
        """Parser should accumulate state across multiple messages."""
        parser.parse_message(_make_solved_state())
        assert parser.data.is_solved is True
        parser.parse_message(_make_scrambled_state())
        assert parser.data.is_solved is False


# --- Battery messages ---


class TestBattery:
    def test_valid_battery(self, parser):
        battery = 75
        payload = bytes([battery])
        msg = _make_msg(MSG_TYPE_BATTERY, payload)
        # Append checksum (sum of first 4 bytes mod 256)
        checksum = sum(msg[:4]) % 0x100
        msg.append(checksum)
        result = parser.parse_message(msg)
        assert "battery" in result
        assert parser.data.battery_level == 75

    def test_battery_full(self, parser):
        battery = 100
        msg = _make_msg(MSG_TYPE_BATTERY, bytes([battery]))
        msg.append(sum(msg[:4]) % 0x100)
        result = parser.parse_message(msg)
        assert "battery" in result
        assert parser.data.battery_level == 100

    def test_battery_zero(self, parser):
        battery = 0
        msg = _make_msg(MSG_TYPE_BATTERY, bytes([battery]))
        msg.append(sum(msg[:4]) % 0x100)
        result = parser.parse_message(msg)
        assert "battery" in result
        assert parser.data.battery_level == 0

    def test_battery_bad_checksum(self, parser):
        msg = _make_msg(MSG_TYPE_BATTERY, bytes([75]))
        msg.append(0xFF)  # Wrong checksum
        result = parser.parse_message(msg)
        assert result == []

    def test_battery_too_short(self, parser):
        result = parser.parse_message(_make_msg(MSG_TYPE_BATTERY))
        assert result == []


# --- Orientation messages ---


class TestOrientation:
    def test_valid_orientation(self, parser):
        # Quaternion (0.5, -0.5, 0.25, 0.75) scaled by 16384
        x, y, z, w = 8192, -8192, 4096, 12288
        payload = struct.pack("<hhhh", x, y, z, w)
        result = parser.parse_message(_make_msg(MSG_TYPE_ORIENTATION, payload))
        assert "orientation" in result
        assert parser.data.orientation is not None
        assert abs(parser.data.orientation.x - 0.5) < 0.001
        assert abs(parser.data.orientation.y - (-0.5)) < 0.001
        assert abs(parser.data.orientation.z - 0.25) < 0.001
        assert abs(parser.data.orientation.w - 0.75) < 0.001

    def test_identity_quaternion(self, parser):
        """Identity quaternion (0, 0, 0, 1)."""
        payload = struct.pack("<hhhh", 0, 0, 0, 16384)
        result = parser.parse_message(_make_msg(MSG_TYPE_ORIENTATION, payload))
        assert "orientation" in result
        assert abs(parser.data.orientation.w - 1.0) < 0.001

    def test_orientation_too_short(self, parser):
        result = parser.parse_message(_make_msg(MSG_TYPE_ORIENTATION, b"\x00" * 4))
        assert result == []


# --- Stats messages ---


class TestStats:
    def test_valid_stats(self, parser):
        solve_count = 5
        total_time = 12345  # ms
        payload = bytes([solve_count]) + struct.pack("<H", total_time) + b"\x00"
        result = parser.parse_message(_make_msg(MSG_TYPE_STATS, payload))
        assert "stats" in result
        assert parser.data.stats is not None
        assert parser.data.stats.solve_count == 5
        assert parser.data.stats.total_solve_time_ms == 12345

    def test_stats_too_short(self, parser):
        result = parser.parse_message(_make_msg(MSG_TYPE_STATS, b"\x00"))
        assert result == []


# --- Cube type messages ---


class TestCubeType:
    def test_known_types(self, parser):
        expected = {
            0x00: "GoCube",
            0x01: "GoCube Edge",
            0x02: "GoCube Pro",
            0x35: "GoCube",
        }
        for byte_val, name in expected.items():
            p = GoCubeDataParser()
            result = p.parse_message(_make_msg(MSG_TYPE_CUBE_TYPE, bytes([byte_val])))
            assert "cube_type" in result
            assert p.data.cube_type == name

    def test_unknown_type(self, parser):
        result = parser.parse_message(_make_msg(MSG_TYPE_CUBE_TYPE, bytes([0xFF])))
        assert "cube_type" in result
        assert "Unknown" in parser.data.cube_type

    def test_cube_type_too_short(self, parser):
        result = parser.parse_message(bytearray([0x2A, 0x01, MSG_TYPE_CUBE_TYPE]))
        assert result == []
