"""Tests for GoCube isometric SVG renderer."""

import pytest

from gocube_ble.renderer import (
    BACKGROUND_COLOR,
    CELL_SIZE,
    STROKE_COLOR,
    UNKNOWN_COLOR,
    _iso_point,
    _polygon_points,
    _shrink_polygon,
    _sticker_color,
    render_cube_svg,
)
from gocube_ble.const import COLOR_RGB


# --- Isometric projection ---


class TestIsoPoint:
    def test_apex_identity(self):
        """Zero offsets should return the apex."""
        apex = (100.0, 50.0)
        assert _iso_point(apex, 0, 0, 0) == apex

    def test_right_moves_right_and_down(self):
        apex = (100.0, 50.0)
        x, y = _iso_point(apex, 1, 0, 0)
        assert x > apex[0]
        assert y > apex[1]

    def test_left_moves_left_and_down(self):
        apex = (100.0, 50.0)
        x, y = _iso_point(apex, 0, 1, 0)
        assert x < apex[0]
        assert y > apex[1]

    def test_down_moves_only_down(self):
        apex = (100.0, 50.0)
        x, y = _iso_point(apex, 0, 0, 1)
        assert x == apex[0]
        assert y == apex[1] + CELL_SIZE

    def test_symmetry(self):
        """Right 1 + Left 1 should give same y but different x."""
        apex = (100.0, 50.0)
        xr, yr = _iso_point(apex, 1, 0, 0)
        xl, yl = _iso_point(apex, 0, 1, 0)
        assert abs(yr - yl) < 0.001
        assert xr > apex[0]
        assert xl < apex[0]


# --- Polygon helpers ---


class TestPolygonPoints:
    def test_format(self):
        corners = [(10.0, 20.0), (30.0, 40.0)]
        result = _polygon_points(corners)
        assert result == "10.0,20.0 30.0,40.0"


class TestShrinkPolygon:
    def test_shrink_reduces_area(self):
        """Shrunk polygon should be closer to center."""
        corners = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        shrunk = _shrink_polygon(corners, 1.0)
        # Center is (5, 5). All shrunk points should be closer to center.
        for (ox, oy), (sx, sy) in zip(corners, shrunk):
            orig_dist = ((ox - 5) ** 2 + (oy - 5) ** 2) ** 0.5
            shrunk_dist = ((sx - 5) ** 2 + (sy - 5) ** 2) ** 0.5
            assert shrunk_dist < orig_dist

    def test_zero_gap(self):
        corners = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        shrunk = _shrink_polygon(corners, 0.0)
        for (ox, oy), (sx, sy) in zip(corners, shrunk):
            assert abs(ox - sx) < 0.001
            assert abs(oy - sy) < 0.001


# --- Sticker color lookup ---


class TestStickerColor:
    def test_known_color(self):
        face_colors = {"White": ["White"] * 9}
        assert _sticker_color(face_colors, "White", 0) == COLOR_RGB["White"]

    def test_unknown_face(self):
        assert _sticker_color({}, "White", 0) == UNKNOWN_COLOR

    def test_index_out_of_range(self):
        face_colors = {"White": ["White"] * 3}
        assert _sticker_color(face_colors, "White", 5) == UNKNOWN_COLOR


# --- SVG rendering ---


class TestRenderCubeSvg:
    def test_returns_svg_string(self):
        svg = render_cube_svg()
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg

    def test_contains_background(self):
        svg = render_cube_svg()
        assert BACKGROUND_COLOR in svg

    def test_contains_27_polygons(self):
        """3 faces × 9 stickers = 27 polygons."""
        svg = render_cube_svg()
        assert svg.count("<polygon") == 27

    def test_grey_cube_when_no_colors(self):
        svg = render_cube_svg()
        assert UNKNOWN_COLOR in svg

    def test_colored_cube(self):
        face_colors = {
            "White": ["White"] * 9,
            "Blue": ["Blue"] * 9,
            "Red": ["Red"] * 9,
        }
        svg = render_cube_svg(face_colors)
        assert COLOR_RGB["White"] in svg
        assert COLOR_RGB["Blue"] in svg
        assert COLOR_RGB["Red"] in svg

    def test_custom_faces(self):
        face_colors = {
            "Yellow": ["Yellow"] * 9,
            "Green": ["Green"] * 9,
            "Orange": ["Orange"] * 9,
        }
        svg = render_cube_svg(
            face_colors, top_face="Yellow", right_face="Orange", left_face="Green"
        )
        assert COLOR_RGB["Yellow"] in svg
        assert COLOR_RGB["Green"] in svg
        assert COLOR_RGB["Orange"] in svg

    def test_viewbox_dimensions(self):
        svg = render_cube_svg()
        assert 'viewBox="0 0' in svg
