"""Tests for GoCube data models."""

from gocube_ble.models import KNOWN_PATTERNS, CubeStats, GoCubeData, Orientation


class TestOrientation:
    def test_defaults(self):
        o = Orientation()
        assert o.x == 0.0
        assert o.y == 0.0
        assert o.z == 0.0
        assert o.w == 1.0

    def test_custom_values(self):
        o = Orientation(x=0.5, y=-0.5, z=0.25, w=0.75)
        assert o.x == 0.5
        assert o.w == 0.75


class TestCubeStats:
    def test_defaults(self):
        s = CubeStats()
        assert s.solve_count == 0
        assert s.total_solve_time_ms == 0


class TestGoCubeData:
    def test_defaults(self):
        d = GoCubeData()
        assert d.battery_level is None
        assert d.is_solved is False
        assert d.face_states == {}
        assert d.face_colors == {}
        assert d.orientation is None
        assert d.stats is None
        assert d.cube_type is None
        assert d.last_move is None

    def test_mutable_defaults_are_independent(self):
        """Each instance should get its own dict."""
        d1 = GoCubeData()
        d2 = GoCubeData()
        d1.face_states["White"] = True
        assert "White" not in d2.face_states

    def test_fingerprint_none_when_no_data(self):
        d = GoCubeData()
        assert d.state_fingerprint is None

    def test_fingerprint_solved_cube(self):
        d = GoCubeData()
        for face, color in [
            ("White", "White"), ("Yellow", "Yellow"), ("Blue", "Blue"),
            ("Green", "Green"), ("Red", "Red"), ("Orange", "Orange"),
        ]:
            d.face_colors[face] = [color] * 9
        assert d.state_fingerprint == "WWWWWWWWWYYYYYYYYYBBBBBBBBBGGGGGGGGGRRRRRRRRROOOOOOOOO"

    def test_fingerprint_deterministic(self):
        d = GoCubeData()
        for face, color in [
            ("White", "White"), ("Yellow", "Yellow"), ("Blue", "Blue"),
            ("Green", "Green"), ("Red", "Red"), ("Orange", "Orange"),
        ]:
            d.face_colors[face] = [color] * 9
        # Scramble one sticker
        d.face_colors["White"][0] = "Red"
        fp1 = d.state_fingerprint
        fp2 = d.state_fingerprint
        assert fp1 == fp2
        assert fp1.startswith("R")  # First sticker is now Red
        assert len(fp1) == 54

    def test_fingerprint_none_with_partial_data(self):
        d = GoCubeData()
        d.face_colors["White"] = ["White"] * 9
        assert d.state_fingerprint is None

    def test_matched_pattern_solved(self):
        d = GoCubeData()
        for face, color in [
            ("White", "White"), ("Yellow", "Yellow"), ("Blue", "Blue"),
            ("Green", "Green"), ("Red", "Red"), ("Orange", "Orange"),
        ]:
            d.face_colors[face] = [color] * 9
        assert d.matched_pattern == "Solved"

    def test_matched_pattern_checkerboard(self):
        d = GoCubeData()
        d.face_colors["White"] = ["W", "Y", "W", "Y", "W", "Y", "W", "Y", "W"]
        d.face_colors["Yellow"] = ["Y", "W", "Y", "W", "Y", "W", "Y", "W", "Y"]
        d.face_colors["Blue"] = ["B", "G", "B", "G", "B", "G", "B", "G", "B"]
        d.face_colors["Green"] = ["G", "B", "G", "B", "G", "B", "G", "B", "G"]
        d.face_colors["Red"] = ["R", "O", "R", "O", "R", "O", "R", "O", "R"]
        d.face_colors["Orange"] = ["O", "R", "O", "R", "O", "R", "O", "R", "O"]
        # Uses abbreviations, but face_colors stores full names from parser
        # Let me fix this test to use full color names
        assert d.matched_pattern is None  # single-letter names won't match

    def test_matched_pattern_checkerboard_full_names(self):
        d = GoCubeData()
        d.face_colors["White"] = ["White", "Yellow", "White", "Yellow", "White", "Yellow", "White", "Yellow", "White"]
        d.face_colors["Yellow"] = ["Yellow", "White", "Yellow", "White", "Yellow", "White", "Yellow", "White", "Yellow"]
        d.face_colors["Blue"] = ["Blue", "Green", "Blue", "Green", "Blue", "Green", "Blue", "Green", "Blue"]
        d.face_colors["Green"] = ["Green", "Blue", "Green", "Blue", "Green", "Blue", "Green", "Blue", "Green"]
        d.face_colors["Red"] = ["Red", "Orange", "Red", "Orange", "Red", "Orange", "Red", "Orange", "Red"]
        d.face_colors["Orange"] = ["Orange", "Red", "Orange", "Red", "Orange", "Red", "Orange", "Red", "Orange"]
        assert d.matched_pattern == "Checkerboard"

    def test_matched_pattern_none_when_scrambled(self):
        d = GoCubeData()
        for face, color in [
            ("White", "White"), ("Yellow", "Yellow"), ("Blue", "Blue"),
            ("Green", "Green"), ("Red", "Red"), ("Orange", "Orange"),
        ]:
            d.face_colors[face] = [color] * 9
        d.face_colors["White"][0] = "Red"
        assert d.matched_pattern is None

    def test_matched_pattern_none_without_data(self):
        d = GoCubeData()
        assert d.matched_pattern is None

    def test_known_patterns_are_54_chars(self):
        for name, fp in KNOWN_PATTERNS.items():
            assert len(fp) == 54, f"{name} pattern is {len(fp)} chars, expected 54"
