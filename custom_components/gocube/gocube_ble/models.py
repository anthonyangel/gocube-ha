"""Data models for GoCube."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class GoCubeData:
    """Data class for GoCube state."""

    battery_level: int | None = None
    is_solved: bool = False
    face_states: Dict[str, bool] = None
    last_update: float | None = None
    last_move: str | None = None
    cube_type: str | None = None

    def __post_init__(self) -> None:
        """Initialize face states dictionary."""
        if self.face_states is None:
            self.face_states = {}
