"""Tests for the radar hover chip: the warnings under the pointer
(hit-test + rendering) and the condition layers' reading there."""

from linecast.radar.basemap import _point_in_rings
from linecast.radar.ui import _build_hover_chip, _fmt_expire, conditions_at

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
        out = _build_hover_chip(_warns(), None, self.HIT, _BBOX, _GW, _HC,
                                cols=80, rows=24, use_24h=False)
        assert "Tornado Warning" in out
        assert "\033[" in out  # cursor-addressed overlay

    def test_empty_off_polygon(self):
        # top-left corner cell is outside the ring
        out = _build_hover_chip(_warns(), None, (1, 2), _BBOX, _GW, _HC,
                                cols=80, rows=24, use_24h=False)
        assert out == ""

    def test_empty_outside_map(self):
        out = _build_hover_chip(_warns(), None, (999, 999), _BBOX, _GW, _HC,
                                cols=80, rows=24, use_24h=False)
        assert out == ""

    def test_emergency_marker(self):
        out = _build_hover_chip(_warns(emergency=True), None, self.HIT, _BBOX,
                                _GW, _HC, cols=80, rows=24, use_24h=False)
        assert "‼" in out

    def test_pds_marker(self):
        out = _build_hover_chip(_warns(pds=True), None, self.HIT, _BBOX,
                                _GW, _HC, cols=80, rows=24, use_24h=False)
        assert "(PDS)" in out


class _Field:
    """A condition field that reads the same everywhere."""

    def __init__(self, temp_c=14.0, wind_kmh=36.0, bearing=45.0):
        self.temp_c, self.wind_kmh, self.bearing = temp_c, wind_kmh, bearing

    def sample_temp(self, t, lon, lat):
        return self.temp_c

    def sample_wind(self, t, lon, lat):
        return self.wind_kmh, self.bearing


def _runtime(*argv, environ=None):
    from linecast._parsers import radar_parser
    from linecast._runtime import RuntimeConfig
    return RuntimeConfig.from_sources(radar_parser().parse_args(["--print", *argv]),
                                      environ={} if environ is None else environ,
                                      country=None)


class TestConditions:
    def test_reads_each_layer_that_is_on(self):
        rt = _runtime("--lang", "en", "--metric")
        both = conditions_at(_Field(), 0, {"temp", "wind"}, -70.5, 43.5, rt)
        assert both == ["14°C", "↗ 36km/h"]
        assert conditions_at(_Field(), 0, {"temp"}, -70.5, 43.5, rt) == ["14°C"]
        assert len(conditions_at(_Field(), 0, {"wind"}, -70.5, 43.5, rt)) == 1

    def test_wind_in_the_chosen_unit(self):
        (wind,) = conditions_at(_Field(), 0, {"wind"}, -70.5, 43.5,
                                _runtime("--lang", "en", "--wind-units", "m/s"))
        assert wind.endswith("10m/s")
        (wind,) = conditions_at(_Field(), 0, {"wind"}, -70.5, 43.5,
                                _runtime("--lang", "en", "--imperial"))
        assert wind.endswith("22mph")

    def test_calm_air_has_no_arrow(self):
        (wind,) = conditions_at(_Field(wind_kmh=2.0), 0, {"wind"}, -70.5, 43.5,
                                _runtime("--lang", "en", "--metric"))
        assert wind == "2km/h"

    def test_chip_reads_the_layers_anywhere_on_the_map(self):
        rt = _runtime("--lang", "en", "--metric")

        def conditions(lon, lat):
            return conditions_at(_Field(), 0, {"temp", "wind"}, lon, lat, rt)

        # off the warning: the reading alone
        out = _build_hover_chip(None, conditions, (1, 2), _BBOX, _GW, _HC,
                                cols=80, rows=24, use_24h=False)
        assert "14°C" in out and "36km/h" in out
        # on it: the warning, then the reading
        out = _build_hover_chip(_warns(), conditions, TestTooltip.HIT, _BBOX,
                                _GW, _HC, cols=80, rows=24, use_24h=False)
        assert out.index("Tornado Warning") < out.index("14°C")
        # off the map: nothing
        assert _build_hover_chip(None, conditions, (999, 999), _BBOX, _GW, _HC,
                                 cols=80, rows=24, use_24h=False) == ""
