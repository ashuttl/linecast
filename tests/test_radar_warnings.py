"""Tests for the storm-based warning layer (parse, cache, compose priority)."""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import linecast._radar_warnings as warn_mod
from linecast._radar_warnings import (
    covers, cached_at, warnings_at, WARNING_COLORS, EMERGENCY, _parse,
)
from linecast._radar_basemap import DotLayer
from linecast._radar_render import compose


def _feature(phenomena, significance="W", emergency=False, geom_type="Polygon",
             coords=None):
    if coords is None:
        ring = [[-92.5, 30.0], [-91.5, 30.0], [-91.5, 30.7], [-92.5, 30.7],
                [-92.5, 30.0]]
        coords = [ring] if geom_type == "Polygon" else [[ring]]
    return {
        "type": "Feature",
        "properties": {"phenomena": phenomena, "significance": significance,
                       "is_emergency": emergency},
        "geometry": {"type": geom_type, "coordinates": coords},
    }


class TestParse:
    def test_whitelisted_warnings_kept_with_colors(self):
        fc = {"features": [_feature("TO"), _feature("SV"), _feature("FF")]}
        parsed = _parse(fc)
        assert [color for _s, color, _r in parsed] == [
            WARNING_COLORS["FF"], WARNING_COLORS["SV"], WARNING_COLORS["TO"]]

    def test_sorted_least_severe_first(self):
        fc = {"features": [_feature("TO"), _feature("MA"), _feature("SV")]}
        sevs = [s for s, _c, _r in _parse(fc)]
        assert sevs == sorted(sevs)

    def test_non_warnings_and_unknown_phenomena_excluded(self):
        fc = {"features": [
            _feature("FA", significance="Y"),   # advisory
            _feature("FL"),                     # river flood: not whitelisted
            _feature("SV", significance="A"),   # watch
        ]}
        assert _parse(fc) == []

    def test_emergency_gets_magenta_and_sorts_last(self):
        fc = {"features": [_feature("TO"), _feature("FF", emergency=True)]}
        parsed = _parse(fc)
        assert parsed[-1][1] == EMERGENCY

    def test_multipolygon_rings_flattened(self):
        fc = {"features": [_feature("SV", geom_type="MultiPolygon")]}
        parsed = _parse(fc)
        assert len(parsed) == 1 and len(parsed[0][2]) == 1

    def test_null_geometry_skipped(self):
        ft = _feature("TO")
        ft["geometry"] = None
        assert _parse({"features": [ft]}) == []


class TestCache:
    def setup_method(self):
        self._orig_fetch = warn_mod.fetch_json
        self._orig_cache = dict(warn_mod._cache)
        warn_mod._cache.clear()
        self.calls = []
        warn_mod.fetch_json = lambda url: (
            self.calls.append(url) or {"features": [_feature("SV")]})

    def teardown_method(self):
        warn_mod.fetch_json = self._orig_fetch
        warn_mod._cache.clear()
        warn_mod._cache.update(self._orig_cache)

    def test_fetch_memoised_per_timestamp(self):
        when = dt.datetime(2026, 7, 14, 11, 0, tzinfo=dt.timezone.utc)
        first = warnings_at(when)
        second = warnings_at(when)
        assert first == second
        assert len(self.calls) == 1
        assert "ts=2026-07-14T11:00:00Z" in self.calls[0]

    def test_cached_at_is_cache_only(self):
        when = dt.datetime(2026, 7, 14, 11, 0, tzinfo=dt.timezone.utc)
        assert cached_at(when) is None
        warnings_at(when)
        assert cached_at(when) is not None
        assert len(self.calls) == 1


class TestCovers:
    def test_conus_view(self):
        assert covers((-96.0, 28.0, -88.0, 33.0))

    def test_alaska_view(self):
        assert covers((-155.0, 58.0, -145.0, 65.0))

    def test_europe_view(self):
        assert not covers((-2.0, 48.0, 6.0, 53.0))


class TestComposePriority:
    GW, HC = 4, 2

    def _echo_buffer(self):
        # every sub-pixel painted: pure radar fill everywhere
        return [[(0, 200, 0)] * self.GW for _ in range(self.HC * 2)]

    def _empty_basemap(self):
        return DotLayer((0, 0, 1, 1), self.GW, self.HC)

    def test_warning_stroke_beats_radar_fill(self):
        warn = self._empty_basemap()
        warn.dots[0][1] = 0x01
        warn.color[0][1] = (255, 65, 65)
        lines = compose(self._empty_basemap(), self._echo_buffer(), {},
                        self.GW, self.HC, warnings=warn)
        # only cell (1,0) becomes a braille stroke glyph; the rest of the
        # row stays echo fill
        row = lines[0]
        assert row.count(chr(0x2800 + 0x01)) == 1

    def test_overlay_text_beats_warning_stroke(self):
        warn = self._empty_basemap()
        warn.dots[0][1] = 0x01
        warn.color[0][1] = (255, 65, 65)
        lines = compose(self._empty_basemap(), self._echo_buffer(),
                        {(1, 0): ("X", (1, 2, 3))}, self.GW, self.HC,
                        warnings=warn)
        assert "X" in lines[0]
        assert chr(0x2800 + 0x01) not in lines[0]

    def test_no_warnings_arg_unchanged(self):
        lines = compose(self._empty_basemap(), self._echo_buffer(), {},
                        self.GW, self.HC)
        assert len(lines) == self.HC


class TestStrokeWidth:
    def test_width_two_lights_more_dots(self):
        ring = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8], [0.2, 0.2]]
        thin = DotLayer((0, 0, 1, 1), 20, 10)
        thin._draw_lines([ring], (255, 0, 0))
        thick = DotLayer((0, 0, 1, 1), 20, 10)
        thick._draw_lines([ring], (255, 0, 0), width=2)
        count = lambda l: sum(bin(c).count("1") for r in l.dots for c in r)
        assert count(thick) > count(thin)
