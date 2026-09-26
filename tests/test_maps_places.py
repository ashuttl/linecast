"""One label system for the city names, at every zoom.

Stages one and two put both registers on one orthographic geometry, so
the shape of the map no longer changes as a reader zooms out past
`globe.local_tiles`.  What still changed there was the *names*: which
list they came from, how many of them there were, how they were
spelled and how they were drawn.  This pins the thing that was left —
that crossing the hand-off changes nothing a reader can see in them.

No network: the gazetteer is vendored, and the tile side is either
hand-encoded or stubbed out.
"""

import sys
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast.terminal import theme as _theme
from linecast.maps import view as maps
from linecast.maps import globe as _globe
from linecast.maps import labels as lb
from linecast.maps import places as _places
from linecast.maps import streets as st
from linecast.maps import style as _maps_style

from test_maps_streets import layer, tile

DARK_BG = (14, 15, 18)


@pytest.fixture(autouse=True)
def _truecolor(monkeypatch):
    monkeypatch.setattr(_maps_style, "color_mode", lambda: "truecolor")
    monkeypatch.setattr(_theme, "theme_bg", DARK_BG)


# Terminal shapes a reader can actually have, and the two the report
# was written from.  The wide one hands off long before `is_globe`
# does — its corner leaves the disk first.
SIZES = ((160, 43), (80, 22), (400, 20), (200, 60))
PLACES = ((46.8, 8.2), (40.7, -74.0), (-33.9, 151.2), (1.3, 103.8))


def hand_off(lat, gw, hc, lo=0.5, hi=130.0):
    """The two zooms `local_tiles` turns over between.

    Bisected until they are a part in a million million of each other,
    so the window either side is the same window to well under a dot
    and anything that differs between them is the hand-off itself and
    not the view.
    """
    for _ in range(200):
        if hi - lo <= lo * 1e-12:
            break
        mid = (lo + hi) / 2.0
        if _globe.local_tiles(lat, mid, gw, hc):
            lo = mid
        else:
            hi = mid
    return lo, hi


def band_of(lat, lon, zoom, gw, hc):
    bbox = _globe.scale_bbox(lat, lon, zoom, gw, hc)
    return _maps_style.band_for(_maps_style.z_eff(bbox, hc))


def glyphs(lines):
    """Every cell of a rendered frame that is a character rather than
    braille or a half-block, as (row, column, the escape run)."""
    import re
    out = []
    for row, line in enumerate(lines):
        col = 0
        for esc, ch in re.findall(r"((?:\x1b\[[0-9;]*m)*)(.)", line):
            if ch == "\n":
                continue
            if not (0x2800 <= ord(ch) <= 0x28FF or ch in "▀▄█"):
                out.append((row, col, esc, ch))
            col += 1
    return out


class TestTheHandOffIsAtBandZeroOrOne:
    """The switch to the gazetteer has to be *below* the band the
    tile-to-planet hand-off happens at, or the flip comes back: past
    `local_tiles` there are no tiles, so the band on the near side must
    already be one the gazetteer owns."""

    def test_on_every_terminal_a_reader_can_have(self):
        for gw, hc in SIZES:
            for lat, lon in PLACES:
                last, first = hand_off(lat, gw, hc)
                for zoom in (last, first):
                    band = band_of(lat, lon, zoom, gw, hc)
                    assert band < _maps_style.GAZETTEER_BAND, (
                        gw, hc, lat, zoom, band)


class TestTheNamesDoNotMoveAtTheHandOff:
    """The same set, in the same cells, either side of the line."""

    @staticmethod
    def _terrain(lat, lon, zoom, gw, hc, lang="en"):
        cam = _globe.Camera(lat, lon, zoom, gw, hc)
        return _places.terrain_overlays(cam, band_of(lat, lon, zoom, gw, hc),
                                        lang)

    @staticmethod
    def _street(lat, lon, zoom, gw, hc, lang="en"):
        cam = _globe.Camera(lat, lon, zoom, gw, hc)
        return _places.street_overlays(
            cam, band_of(lat, lon, zoom, gw, hc), _maps_style.palette(),
            lang)

    @pytest.mark.parametrize("register", ("terrain", "street"))
    def test_either_side_of_local_tiles(self, register):
        place = getattr(self, "_" + register)
        for gw, hc in SIZES:
            for lat, lon in PLACES:
                last, first = hand_off(lat, gw, hc)
                assert _globe.local_tiles(lat, last, gw, hc)
                assert not _globe.local_tiles(lat, first, gw, hc)
                near = place(lat, lon, last, gw, hc)
                far = place(lat, lon, first, gw, hc)
                assert near and near == far, (register, gw, hc, lat)

    def test_at_forty_five_degrees_on_the_equator(self):
        # `globe.ZOOM_DEG` itself, where the hand-off sits at the
        # equator and one press of - carries a reader across it.  The
        # view is two parts in a thousand wider on the far side, so a
        # city can cross the rim; what may not change is anything
        # about how the names that stay are written.
        for register in ("terrain", "street"):
            place = getattr(self, "_" + register)
            assert _globe.local_tiles(0.0, 44.9, 160, 43)
            assert not _globe.local_tiles(0.0, 45.1, 160, 43)
            near = place(0.0, 10.0, 44.9, 160, 43)
            far = place(0.0, 10.0, 45.1, 160, 43)
            kept = self._names(near) & self._names(far)
            assert len(kept) >= len(self._names(near)) - 1
            assert self._styles(near) == self._styles(far)

    @staticmethod
    def _names(overlays):
        from linecast.maps.overscan import label_runs
        return {"".join(e[0] for _off, e in run[2]).lstrip(
            _maps_style.GLYPH_GENERIC).strip()
            for run in label_runs(overlays)}

    @staticmethod
    def _styles(overlays):
        """Every (ink, bold) a name is written in, and the anchor glyph."""
        return ({entry[1:] for entry in overlays.values()},
                {entry[0] for entry in overlays.values()
                 if entry[0] in (_maps_style.GLYPH_GENERIC,
                                 _maps_style.GLYPH_CAPITAL)})

    @pytest.mark.parametrize("lang", ("en", "fr", "ja", "zh-Hant"))
    def test_the_language_is_the_same_on_both_sides(self, lang):
        for gw, hc in SIZES[:2]:
            for lat, lon in PLACES:
                last, first = hand_off(lat, gw, hc)
                for register in ("terrain", "street"):
                    place = getattr(self, "_" + register)
                    assert (place(lat, lon, last, gw, hc, lang)
                            == place(lat, lon, first, gw, hc, lang))

    def test_the_gazetteer_spells_the_name_the_runtime_asked_for(self):
        # Moscow is on the Alps view either side of the hand-off, and
        # the gazetteer's seventeen languages are what a reader on the
        # tiles gets as well as one past them
        last, first = hand_off(46.8, 160, 43)
        for zoom in (last, first):
            for lang, want in (("en", "Moscow"), ("fr", "Moscou"),
                               ("ja", "モスクワ")):
                ov = self._terrain(46.8, 8.2, zoom, 160, 43, lang)
                assert want in self._names(ov), (zoom, lang)


class TestTheBudget:
    """One rule: a name is given a patch of screen, the patch shrinks
    as the view closes in, and the clamp rises with it."""

    def test_the_rule_at_three_sizes_and_three_zooms(self):
        # A 160x45 terminal over the Alps, and the two smaller ones;
        # the old flat rule gave 17, 17, 17 and 6, 6, 6 at every zoom.
        want = {
            # (gw, hc): [2 deg, 10 deg, 30 deg]
            (160, 43): [25, 21, 17],
            (80, 22): [8, 6, 6],
            (40, 12): [8, 6, 6],
        }
        for (gw, hc), counts in want.items():
            got = [_places.budget(gw, hc, band_of(46.8, 8.2, z, gw, hc))
                   for z in (2.0, 10.0, 30.0)]
            assert got == counts, (gw, hc, got)

    def test_band_zero_is_the_planets_own_rule_to_the_number(self):
        for gw, hc in SIZES + ((40, 12), (20, 8), (1000, 300)):
            assert (_places.budget(gw, hc, 0)
                    == max(6, min(24, gw * hc // 400)))

    def test_a_closer_view_is_never_given_fewer_names(self):
        for gw, hc in SIZES:
            counts = [_places.budget(gw, hc, b) for b in range(8)]
            assert counts == sorted(counts)

    def test_the_budget_is_what_a_view_actually_carries(self):
        # over the Alps at 2 degrees the crowding rule alone would
        # place 23 names, so the budget is not what binds there; at 30
        # it is
        cam = _globe.Camera(46.8, 8.2, 2.0, 160, 43)
        assert len(_places.layout(cam, band_of(46.8, 8.2, 2.0, 160, 43))) == 23
        cam = _globe.Camera(46.8, 8.2, 30.0, 160, 43)
        band = band_of(46.8, 8.2, 30.0, 160, 43)
        assert len(_places.layout(cam, band)) == _places.budget(160, 43, band)


class TestTheTwoRegistersReadTheSameList:
    def test_the_street_planet_and_the_tiled_view_make_one_call(self):
        # An empty place layer below the switch: every name the tiled
        # street view writes is the gazetteer's, and it is the very
        # dict the planet writes on the other side.
        gw, hc = 160, 43
        lat, lon = 46.8, 8.2
        zoom = hand_off(lat, gw, hc)[0]
        bbox = _globe.scale_bbox(lat, lon, zoom, gw, hc)
        cam = _globe.Camera.for_bbox(bbox, gw, hc)
        band = band_of(lat, lon, zoom, gw, hc)
        view = st.decode_view({(0, 0, 0): tile(layer("place", []))})
        tiled = lb.label_overlays(view, bbox, gw, hc, band,
                                  _maps_style.palette(), "en", camera=cam)
        planet = _places.street_overlays(cam, band, _maps_style.palette(),
                                         "en")
        assert planet
        assert all(tiled[cell] == entry for cell, entry in planet.items())

    def test_the_gazetteer_ignores_what_the_page_reserved(self):
        # A name the planet writes cannot be taken away by a crosshair
        # the planet has never heard of, or the two sides differ.
        gw, hc = 160, 43
        bbox = _globe.scale_bbox(46.8, 8.2, 30.0, gw, hc)
        cam = _globe.Camera.for_bbox(bbox, gw, hc)
        band = band_of(46.8, 8.2, 30.0, gw, hc)
        view = st.decode_view({(0, 0, 0): tile(layer("place", []))})
        free = lb.label_overlays(view, bbox, gw, hc, band,
                                 _maps_style.palette(), "en", camera=cam)
        blocked = lb.label_overlays(
            view, bbox, gw, hc, band, _maps_style.palette(), "en",
            reserved=[(c, r) for c in range(gw) for r in range(hc)],
            camera=cam)
        assert blocked == free

    def test_the_two_registers_agree_on_which_cities(self):
        gw, hc = 160, 43
        cam = _globe.Camera(46.8, 8.2, 30.0, gw, hc)
        band = band_of(46.8, 8.2, 30.0, gw, hc)
        dots = {cell for cell, e in
                _places.terrain_overlays(cam, band).items()
                if e[0] == _maps_style.GLYPH_GENERIC}
        street = {cell for cell, e in _places.street_overlays(
            cam, band, _maps_style.palette(), "en").items()
            if e[0] == _maps_style.GLYPH_GENERIC}
        assert dots and dots == street


class TestTheWindowOfAnOverscanIsThePlanetsOwnSet:
    """Live, the street register's last tiled frame is an overscan and
    the planet on the far side of `local_tiles` is the window alone —
    so the window cropped out of the overscan has to carry the set the
    window would carry built alone, or the flip is back in the loop,
    where a reader zooms, and gone only from `--print`, where it was
    measured."""

    @staticmethod
    def _built(lat, lon, zoom, gw, hc, window):
        from linecast.maps import overscan as o
        from linecast.radar.render import bbox_for
        bbox = bbox_for(lat, lon, zoom, gw, hc)
        frame, at = o.plan(bbox, gw, hc)
        band = band_of(lat, lon, zoom, gw, hc)
        fcam = _globe.Camera.for_bbox(frame.bbox, frame.gw, frame.hc)
        wide = _places.street_overlays(fcam, band, _maps_style.palette(),
                                       "en", window=window)
        alone = _places.street_overlays(_globe.Camera.for_bbox(bbox, gw, hc),
                                        band, _maps_style.palette(), "en")
        return wide, alone, at

    def test_the_crop_is_the_window_built_alone(self):
        from linecast.maps import overscan as o
        for gw, hc in SIZES[:2]:
            for lat, lon in PLACES:
                zoom = hand_off(lat, gw, hc)[0]
                wide, alone, (dx, dy) = self._built(lat, lon, zoom, gw, hc,
                                                    (gw, hc))
                assert alone
                assert o.crop_overlays(wide, dx, dy, gw, hc) == alone, (
                    gw, hc, lat)
                # and the margin around the window is still named
                assert any(not (dx <= c < dx + gw and dy <= r < dy + hc)
                           for c, r in wide), (gw, hc, lat)

    def test_without_the_window_the_overscan_places_for_itself(self):
        # which is the crop that differed: the margin's cities took the
        # overscan's budget and crowded the window's
        from linecast.maps import overscan as o
        gw, hc = 80, 22
        lat, lon = 40.7, -74.0
        zoom = hand_off(lat, gw, hc)[0]
        wide, alone, (dx, dy) = self._built(lat, lon, zoom, gw, hc, None)
        assert o.crop_overlays(wide, dx, dy, gw, hc) != alone
        # a window the overscan's own size asks for nothing more
        cam = _globe.Camera(lat, lon, zoom, gw, hc)
        band = band_of(lat, lon, zoom, gw, hc)
        assert (_places.layout(cam, band, window=(gw, hc))
                == _places.layout(cam, band))


class TestTheLabelToggle:
    """`l` hides every name in both registers at every zoom.  The
    crosshair and the marks are not names."""

    # a window on a city, so there is a name to hide at every zoom
    LAT, LON = 47.37, 8.54

    @staticmethod
    def _terrain(zoom, monkeypatch, show):
        gw, hc = 60, 20
        elev = [[500.0] * gw for _ in range(hc * 2)]
        view = maps.TerrainView(elev, [[0] * gw for _ in range(hc)],
                                None, None, None)
        monkeypatch.setattr(maps, "_get_elevation", lambda *a, **k: view)
        monkeypatch.setattr(maps, "_get_globe", lambda *a, **k: None)
        bbox = _globe.scale_bbox(TestTheLabelToggle.LAT,
                                 TestTheLabelToggle.LON, zoom, gw, hc)
        return maps._render_terrain(bbox, gw, hc, True, (0, 0), None, None,
                                    None, None, "en", None,
                                    show_labels=show)[0]

    @staticmethod
    def _street(zoom, monkeypatch, show):
        gw, hc = 60, 20
        lat, lon = TestTheLabelToggle.LAT, TestTheLabelToggle.LON
        bbox = _globe.scale_bbox(lat, lon, zoom, gw, hc)
        cam = _globe.Camera.for_bbox(bbox, gw, hc)
        band = band_of(lat, lon, zoom, gw, hc)
        fills = [[(20, 20, 20)] * gw for _ in range(hc * 2)]
        ov = _places.street_overlays(cam, band, _maps_style.palette(), "en")
        layer = maps._ShiftedLayer([[0] * gw for _ in range(hc)],
                                   [[None] * gw for _ in range(hc)])
        monkeypatch.setattr(maps, "_get_street",
                            lambda *a, **k: (fills, layer, ov))
        return maps._render_street(bbox, gw, hc, True, (0, 0), None, None,
                                   None, None, "en", None,
                                   show_labels=show)[0]

    @pytest.mark.parametrize("register", ("terrain", "street"))
    @pytest.mark.parametrize("zoom", (0.05, 2.0, 30.0, 40.0, 120.0))
    def test_nothing_but_the_marks_is_left(self, register, zoom,
                                           monkeypatch):
        draw = getattr(self, "_" + register)
        on = glyphs(draw(zoom, monkeypatch, True))
        off = glyphs(draw(zoom, monkeypatch, False))
        assert {g[3] for g in off} <= {"+", "○", "●", " "}
        # and there was something to hide
        assert {g[3] for g in on} - {"+", "○", "●", " "}
