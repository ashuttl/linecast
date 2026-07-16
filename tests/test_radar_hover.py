"""Tests for the radar warning hover tooltip (hit-test + rendering)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast.radar import (
    _point_in_rings, _fmt_expire, _build_warning_tooltip,
)

# a square warning polygon inside the view
_RING = [[-70.7, 43.3], [-70.3, 43.3], [-70.3, 43.7], [-70.7, 43.7],
         [-70.7, 43.3]]
_BBOX = (-71.0, 43.0, -70.0, 44.0)
_GW, _HC = 10, 5


def _warns(name="Tornado Warning", expire="2026-07-16T20:00:00Z", **info):
    base = {"name": name, "expire": expire, "emergency": False, "pds": False}
    base.update(info)
    return [(4, (255, 65, 65), [_RING], base)]


class TestPointInRings:
    def test_inside(self):
        assert _point_in_rings(-70.5, 43.5, [_RING])

    def test_outside(self):
        assert not _point_in_rings(-70.9, 43.5, [_RING])


class TestFmtExpire:
    def test_parses_iso_z(self):
        assert _fmt_expire("2026-07-16T20:00:00Z", use_24h=True)

    def test_none_and_garbage(self):
        assert _fmt_expire(None, False) is None
        assert _fmt_expire("not-a-date", False) is None


class TestTooltip:
    # cursor over the polygon interior: mcol=5,mrow=4 → lon≈-70.55, lat=43.5
    HIT = (5, 4)

    def test_names_the_warning_under_cursor(self):
        out = _build_warning_tooltip(_warns(), self.HIT, _BBOX, _GW, _HC,
                                     cols=80, rows=24, use_24h=False)
        assert "Tornado Warning" in out
        assert "\033[" in out  # cursor-addressed overlay

    def test_empty_off_polygon(self):
        # top-left corner cell is outside the ring
        out = _build_warning_tooltip(_warns(), (1, 2), _BBOX, _GW, _HC,
                                     cols=80, rows=24, use_24h=False)
        assert out == ""

    def test_empty_outside_map(self):
        out = _build_warning_tooltip(_warns(), (999, 999), _BBOX, _GW, _HC,
                                     cols=80, rows=24, use_24h=False)
        assert out == ""

    def test_emergency_marker(self):
        out = _build_warning_tooltip(_warns(emergency=True), self.HIT, _BBOX,
                                     _GW, _HC, cols=80, rows=24, use_24h=False)
        assert "‼" in out

    def test_pds_marker(self):
        out = _build_warning_tooltip(_warns(pds=True), self.HIT, _BBOX,
                                     _GW, _HC, cols=80, rows=24, use_24h=False)
        assert "(PDS)" in out
