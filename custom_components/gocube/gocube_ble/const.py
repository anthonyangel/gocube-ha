"""Constants for GoCube Bluetooth communication."""

from __future__ import annotations

# Bluetooth UUIDs (Nordic UART Service)
PRIMARY_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX_CHARACTERISTIC_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
TX_CHARACTERISTIC_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# Message framing
MSG_PREFIX = 0x2A
MSG_SUFFIX = bytearray([0x0D, 0x0A])  # CR, LF

# Message types
MSG_TYPE_ROTATION = 0x01
MSG_TYPE_STATE = 0x02
MSG_TYPE_ORIENTATION = 0x03
MSG_TYPE_BATTERY = 0x05
MSG_TYPE_STATS = 0x07
MSG_TYPE_CUBE_TYPE = 0x08

# Configuration commands
CONFIGURATION_COMMANDS = {
    "Reboot": bytearray([0x34]),
    "SetSolvedState": bytearray([0x35]),
    "DisableOrientation": bytearray([0x37]),
    "EnableOrientation": bytearray([0x38]),
    "GetBattery": bytearray([0x32]),
    "GetState": bytearray([0x33]),
    "GetStats": bytearray([0x39]),
    "GetCubeType": bytearray([0x56]),
    # LED Commands
    "LedFlash": bytearray([0x41]),
    "LedToggleAnimation": bytearray([0x42]),
    "LedFlashSlow": bytearray([0x43]),
    "LedToggle": bytearray([0x44]),
    # LED Brightness Presets (0x45=brightest → 0x4B=off)
    "LedBrightness6": bytearray([0x45]),
    "LedBrightness5": bytearray([0x46]),
    "LedBrightness4": bytearray([0x47]),
    "LedBrightness3": bytearray([0x48]),
    "LedBrightness2": bytearray([0x49]),
    "LedBrightness1": bytearray([0x4A]),
    "LedBrightnessOff": bytearray([0x4B]),
}

# Face rotation mapping
FACE_ROTATION_MAP = {
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

# Color index to name mapping
COLOR_HEX_LOOKUP = {
    0x00: "Blue",
    0x01: "Green",
    0x02: "White",
    0x03: "Yellow",
    0x04: "Red",
    0x05: "Orange",
}

# Color name to RGB hex for rendering
COLOR_RGB = {
    "Blue": "#0051BA",
    "Green": "#009E60",
    "White": "#FFFFFF",
    "Yellow": "#FFD500",
    "Red": "#C41E3A",
    "Orange": "#FF5800",
}

# Standard face ordering for isometric rendering (top, right, left)
ISOMETRIC_FACES = ("White", "Blue", "Red")
