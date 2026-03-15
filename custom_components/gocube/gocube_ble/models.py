"""Data models for GoCube."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Orientation:
    """Quaternion orientation data from the cube's IMU."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0


@dataclass
class CubeStats:
    """Session statistics from the cube."""

    solve_count: int = 0
    total_solve_time_ms: int = 0


# Known cube patterns: name → fingerprint
KNOWN_PATTERNS: dict[str, str] = {
    "Solved": "WWWWWWWWWYYYYYYYYYBBBBBBBBBGGGGGGGGGRRRRRRRRROOOOOOOOO",
    "Checkerboard": "WYWYWYWYWYWYWYWYWYBGBGBGBGBGBGBGBGBGRORORORORORORORORO",
}

_COLOR_ABBREV = {
    "Blue": "B",
    "Green": "G",
    "White": "W",
    "Yellow": "Y",
    "Red": "R",
    "Orange": "O",
}

# Canonical face order for fingerprint
_FACE_ORDER = ("White", "Yellow", "Blue", "Green", "Red", "Orange")


@dataclass
class GoCubeData:
    """Data class for GoCube state."""

    battery_level: int | None = None
    is_solved: bool = False
    face_states: dict[str, bool] = field(default_factory=dict)
    face_colors: dict[str, list[str]] = field(default_factory=dict)
    orientation: Orientation | None = None
    stats: CubeStats | None = None
    cube_type: str | None = None
    last_move: str | None = None

    @property
    def state_fingerprint(self) -> str | None:
        """Return a compact string representing the full cube state.

        Format: 54 single-letter color codes (6 faces × 9 stickers),
        faces in canonical order (W/Y/B/G/R/O), stickers in row-major.
        Example solved cube: "WWWWWWWWWYYYYYYYYYBBBBBBBBBGGGGGGGGGRRRRRRRRROOOOOOOOO"

        Returns None if face data is not yet available.
        """
        if len(self.face_colors) < 6:
            return None
        parts = []
        for face in _FACE_ORDER:
            stickers = self.face_colors.get(face)
            if not stickers or len(stickers) != 9:
                return None
            parts.extend(_COLOR_ABBREV.get(c, "?") for c in stickers)
        return "".join(parts)

    @property
    def matched_pattern(self) -> str | None:
        """Return the name of a known pattern if the current state matches one."""
        fp = self.state_fingerprint
        if fp is None:
            return None
        for name, pattern in KNOWN_PATTERNS.items():
            if fp == pattern:
                return name
        return None
