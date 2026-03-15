"""Isometric SVG renderer for GoCube state visualization."""

from __future__ import annotations

import math

from .const import COLOR_RGB, ISOMETRIC_FACES

# Rendering constants
CELL_SIZE = 40
GAP = 2
STROKE_COLOR = "#333333"
STROKE_WIDTH = 1.5
BACKGROUND_COLOR = "#1a1a1a"
UNKNOWN_COLOR = "#808080"

# Isometric projection basis vectors
_DX = CELL_SIZE * math.sqrt(3) / 2
_DY = CELL_SIZE / 2


def _iso_point(apex: tuple[float, float], right: int, left: int, down: int) -> tuple[float, float]:
    """Compute screen coordinates from isometric grid position.

    Args:
        apex: The (x, y) screen position of the cube's front apex.
        right: Steps along the right-down axis.
        left: Steps along the left-down axis.
        down: Steps along the vertical-down axis.
    """
    x = apex[0] + right * _DX - left * _DX
    y = apex[1] + right * _DY + left * _DY + down * CELL_SIZE
    return (x, y)


def _polygon_points(corners: list[tuple[float, float]]) -> str:
    """Format corner coordinates as SVG polygon points string."""
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in corners)


def _shrink_polygon(corners: list[tuple[float, float]], gap: float) -> list[tuple[float, float]]:
    """Shrink a polygon inward by `gap` pixels to create inter-sticker gaps."""
    cx = sum(p[0] for p in corners) / len(corners)
    cy = sum(p[1] for p in corners) / len(corners)
    result = []
    for px, py in corners:
        dx = px - cx
        dy = py - cy
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > 0:
            factor = (dist - gap) / dist
            result.append((cx + dx * factor, cy + dy * factor))
        else:
            result.append((px, py))
    return result


def _sticker_color(face_colors: dict[str, list[str]], face_name: str, index: int) -> str:
    """Get the RGB hex color for a sticker."""
    if face_name not in face_colors:
        return UNKNOWN_COLOR
    stickers = face_colors[face_name]
    if index >= len(stickers):
        return UNKNOWN_COLOR
    color_name = stickers[index]
    return COLOR_RGB.get(color_name, UNKNOWN_COLOR)


def render_cube_svg(
    face_colors: dict[str, list[str]] | None = None,
    top_face: str = "White",
    right_face: str = "Blue",
    left_face: str = "Red",
) -> str:
    """Render an isometric cube as an SVG string.

    Args:
        face_colors: Dict mapping face name to list of 9 color names in row-major
                     order [TL, TC, TR, ML, C, MR, BL, BC, BR].
                     If None, renders a grey cube.
        top_face: Name of the face to render on top.
        right_face: Name of the face to render on the right.
        left_face: Name of the face to render on the left.

    Returns:
        SVG markup string.
    """
    if face_colors is None:
        face_colors = {}

    margin = 8
    width = 6 * _DX + 2 * margin
    height = 6 * _DY + 3 * CELL_SIZE + 2 * margin
    apex = (width / 2, margin)

    polygons: list[str] = []

    # --- Top face ---
    # Grid: row goes along left axis, col goes along right axis
    for row in range(3):
        for col in range(3):
            corners = [
                _iso_point(apex, col, row, 0),
                _iso_point(apex, col + 1, row, 0),
                _iso_point(apex, col + 1, row + 1, 0),
                _iso_point(apex, col, row + 1, 0),
            ]
            corners = _shrink_polygon(corners, GAP)
            # Map grid position to sticker index (row-major in face coordinates)
            # Top face: isometric row=face_row, isometric col=face_col
            sticker_idx = row * 3 + col
            color = _sticker_color(face_colors, top_face, sticker_idx)
            polygons.append(
                f'  <polygon points="{_polygon_points(corners)}" '
                f'fill="{color}" stroke="{STROKE_COLOR}" stroke-width="{STROKE_WIDTH}"/>'
            )

    # --- Left face ---
    # Grid: row goes down, col goes along the left-down axis
    # Anchored at left=3 (left edge of top face) — renders on viewer's LEFT
    for row in range(3):
        for col in range(3):
            corners = [
                _iso_point(apex, col, 3, row),
                _iso_point(apex, col + 1, 3, row),
                _iso_point(apex, col + 1, 3, row + 1),
                _iso_point(apex, col, 3, row + 1),
            ]
            corners = _shrink_polygon(corners, GAP)
            sticker_idx = row * 3 + col
            color = _sticker_color(face_colors, left_face, sticker_idx)
            polygons.append(
                f'  <polygon points="{_polygon_points(corners)}" '
                f'fill="{color}" stroke="{STROKE_COLOR}" stroke-width="{STROKE_WIDTH}"/>'
            )

    # --- Right face ---
    # Grid: row goes down, col goes along the right-down axis
    # Anchored at right=3 (right edge of top face) — renders on viewer's RIGHT
    for row in range(3):
        for col in range(3):
            corners = [
                _iso_point(apex, 3, col, row),
                _iso_point(apex, 3, col + 1, row),
                _iso_point(apex, 3, col + 1, row + 1),
                _iso_point(apex, 3, col, row + 1),
            ]
            corners = _shrink_polygon(corners, GAP)
            sticker_idx = row * 3 + col
            color = _sticker_color(face_colors, right_face, sticker_idx)
            polygons.append(
                f'  <polygon points="{_polygon_points(corners)}" '
                f'fill="{color}" stroke="{STROKE_COLOR}" stroke-width="{STROKE_WIDTH}"/>'
            )

    svg_content = "\n".join(polygons)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="{width:.0f}" height="{height:.0f}">\n'
        f'  <rect width="100%" height="100%" fill="{BACKGROUND_COLOR}" rx="8"/>\n'
        f"{svg_content}\n"
        f"</svg>"
    )
