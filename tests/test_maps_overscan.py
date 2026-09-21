"""The margin a flat view is built beyond the window that shows it.

A view is built a quarter wider and a quarter taller than the frame it
was asked for, and the frame is a crop of it.  What that buys is here:
a pan inside the margin is the real map at the new centre rather than
the last one shifted clear of its own picture, and it asks the network
for nothing at all.  What it costs is here too — a window past the
margin, where the next view is asked for centred ahead of the motion.
"""

import re
import sys
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast._maps import overscan as over
from linecast import maps
from linecast._maps import views
from linecast._maps.hover import HoverIndex
from linecast._radar_basemap import DotLayer
from linecast._radar_render import bbox_for

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
COLS, ROWS = 60, 20
LAT, LON, ZOOM = 40.7, -74.0, 0.05


def _braille_between(frame, lo, hi):
    """Braille cells in columns [lo, hi) of a frame's map rows."""
    rows = [ANSI.sub("", line) for line in frame.split("\n")[1:-1]]
    return sum(1 for row in rows for ch in row[lo:hi]
               if 0x2800 <= ord(ch) <= 0x28FF)


# ---------------------------------------------------------------------------
# The frame and the crop
# ---------------------------------------------------------------------------
class TestThePlan:
    BBOX = (0.0, 0.0, 8.0, 4.0)   # one degree a column, one a row
    GW, HC = 8, 4

    def test_a_resting_plan_splits_the_margin_evenly(self):
        frame, at = over.plan(self.BBOX, self.GW, self.HC)
        pw, ph = over.padding(self.GW, self.HC)
        assert (frame.gw, frame.hc) == (self.GW + 2 * pw, self.HC + 2 * ph)
        assert at == (pw, ph)
        assert over.locate(frame, self.BBOX, self.GW, self.HC) == at

    def test_a_moving_plan_puts_the_whole_margin_in_front(self):
        pw, ph = over.padding(self.GW, self.HC)
        east, at = over.plan(self.BBOX, self.GW, self.HC, (1, 0))
        # the same view, the same cost — only somewhere else
        assert (east.gw, east.hc) == (self.GW + 2 * pw, self.HC + 2 * ph)
        assert at == (0, ph)          # the window sits at the west edge
        assert east.bbox[0] == pytest.approx(self.BBOX[0])
        assert east.bbox[2] == pytest.approx(self.BBOX[2] + 2 * pw)
        north, at = over.plan(self.BBOX, self.GW, self.HC, (0, -1))
        assert at == (pw, 2 * ph)     # and at the south edge going north
        assert north.bbox[3] == pytest.approx(self.BBOX[3] + 2 * ph)

    def test_the_window_is_always_inside_the_plan(self):
        for ahead in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, -1)):
            frame, at = over.plan(self.BBOX, self.GW, self.HC, ahead)
            assert over.locate(frame, self.BBOX, self.GW, self.HC) == at

    def test_locate_refuses_another_scale_or_ground_it_does_not_cover(self):
        frame, _at = over.plan(self.BBOX, self.GW, self.HC)
        # half a cell out is a miss, not something to round into place
        off = tuple(v + 0.5 for v in self.BBOX)
        assert over.locate(frame, off, self.GW, self.HC) is None
        # another zoom is another map
        wide = (-4.0, 0.0, 12.0, 4.0)
        assert over.locate(frame, wide, self.GW, self.HC) is None
        # and ground past the margin
        away = tuple(v + 40.0 for v in self.BBOX)
        assert over.locate(frame, away, self.GW, self.HC) is None

    def test_a_window_dragged_a_row_north_is_still_a_crop(self):
        # a flat window's width in longitude follows the cosine of its
        # own centre latitude, so one row north it is a hair narrower
        # than the view it was cut from — a few thousandths of a cell
        # across the whole width at street zoom, which is a crop
        gw, hc = 60, 20
        here = bbox_for(LAT, LON, ZOOM, gw, hc)
        frame, (dx, dy) = over.plan(here, gw, hc)
        for rows in (1, 3, -2):
            up = bbox_for(LAT + rows * ZOOM / hc, LON, ZOOM, gw, hc)
            assert over.locate(frame, up, gw, hc) == (dx, dy - rows)

    def test_a_drift_wider_than_the_slack_is_not_a_crop(self):
        # at a terrain zoom the same rows are a few hundredths of a cell
        # each, and past the slack the window is reprojected instead
        gw, hc = 60, 20
        here = bbox_for(46.8, 8.2, 4.0, gw, hc)
        frame, _at = over.plan(here, gw, hc)
        far = bbox_for(46.8 + 3 * 4.0 / hc, 8.2, 4.0, gw, hc)
        assert over.locate(frame, far, gw, hc) is None

    def test_a_crop_is_the_sub_cells_the_built_view_already_held(self):
        frame, (dx, dy) = over.plan(self.BBOX, self.GW, self.HC)
        grid = [[(x, y) for x in range(frame.gw)]
                for y in range(frame.hc * 2)]
        cut = over.crop_grid(grid, dx, dy * 2, self.GW, self.HC * 2)
        assert len(cut) == self.HC * 2 and len(cut[0]) == self.GW
        assert cut[0][0] == (dx, dy * 2)
        assert cut[-1][-1] == (dx + self.GW - 1, (dy + self.HC) * 2 - 1)


class TestCroppedLabels:
    def test_a_name_reaching_past_the_edge_is_dropped_whole(self):
        ink = (1, 2, 3)
        overlays = {(c, 1): (ch, ink) for c, ch in enumerate("Main", 3)}
        # window is columns 0..4: the run runs 3..6 and reaches past it
        assert over.crop_overlays(overlays, 0, 0, 5, 4) == {}
        # widen the window by two and the whole name comes across
        kept = over.crop_overlays(overlays, 0, 0, 7, 4)
        assert "".join(kept[(c, 1)][0] for c in range(3, 7)) == "Main"

    def test_a_name_under_the_crosshair_is_kept_for_the_mark_to_cover(self):
        # the built view reserved its own centre, not this window's, so
        # a run can sit under the crosshair; it comes across whole and
        # the mark is drawn over the one letter, as on any moving view
        ink = (1, 2, 3)
        overlays = {(c, 1): (ch, ink) for c, ch in enumerate("Main", 0)}
        kept = over.crop_overlays(overlays, 0, 0, 8, 4)
        assert "".join(kept[(c, 1)][0] for c in range(4)) == "Main"

    def test_a_wide_glyph_keeps_its_continuation(self):
        ink = (1, 2, 3)
        overlays = {(2, 0): ("東", ink), (3, 0): ("", None)}
        kept = over.crop_overlays(overlays, 1, 0, 3, 2)
        assert kept == {(1, 0): ("東", ink), (2, 0): ("", None)}
        # and is dropped with it when the pair straddles the edge
        assert over.crop_overlays(overlays, 1, 0, 2, 2) == {}


class TestCroppedHover:
    """The index belongs to the built view; the window reads it offset."""

    W, H = 8, 6

    def _index(self, marks=None, texts=None):
        owner = [[None] * self.W for _ in range(self.H)]
        owner[3][5] = 0
        owner[3][6] = 0
        area = [[0] * self.W for _ in range(self.H)]
        return HoverIndex(owner, [("primary", "Main Street")], {},
                          marks or {}, area, texts=texts or {})

    def test_a_hit_maps_to_the_feature_under_the_window_cell(self):
        cropped = over.CroppedHover(self._index(), 3, 2, 4, 3, set())
        hit = cropped.at(2, 1)            # (5, 3) in the built view
        assert hit.name == "Main Street"
        assert set(hit.cells) == {(2, 1), (3, 1)}
        assert cropped.at(0, 0) is None   # bare ground says nothing
        assert cropped.at(4, 0) is None   # and nothing outside answers

    def test_a_feature_reaching_past_the_window_lights_only_what_shows(self):
        cropped = over.CroppedHover(self._index(), 3, 2, 3, 3, set())
        assert set(cropped.at(2, 1).cells) == {(2, 1)}

    def test_a_dropped_label_neither_answers_nor_lights(self):
        marks = {(5, 3): ("hov_city", "Springfield", 0)}
        kept = over.CroppedHover(self._index(marks), 3, 2, 4, 3, {(2, 1)})
        assert kept.at(2, 1).name == "Springfield"
        # the same index with the run dropped from the crop: the mark is
        # not written there, so what answers is the road underneath
        gone = over.CroppedHover(self._index(marks), 3, 2, 4, 3, set())
        assert gone.at(2, 1).name == "Main Street"


# ---------------------------------------------------------------------------
# Through render_map
# ---------------------------------------------------------------------------
class _Loader:
    """A street loader that lands one overscan and counts every ask."""

    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def view(self, gw, hc, ink=(255, 0, 0)):
        fills = [[ink] * gw for _ in range(hc * 2)]
        layer = maps._ShiftedLayer([[0xFF] * gw for _ in range(hc)],
                                   [[ink] * gw for _ in range(hc)])
        return fills, layer, {}

    def __call__(self, bbox, gw, hc, block, lang="en", reserved=(),
                 window=None):
        self.calls.append((tuple(bbox), gw, hc, block))
        return (None, None, None)


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(maps, "get_terminal_size", lambda: (COLS, ROWS))
    views._street_landed[0] = None
    views._terrain_landed[0] = None
    maps._last_street[0] = maps._last_terrain[0] = None
    yield
    views._street_landed[0] = None
    views._terrain_landed[0] = None
    maps._last_street[0] = maps._last_terrain[0] = None


def _land(gw, hc, bbox, ahead=(0, 0)):
    """Put one built overscan for `bbox` in hand, and return its frame."""
    frame, _at = over.plan(bbox, gw, hc, ahead)
    ink = (255, 0, 0)
    fills = [[ink] * frame.gw for _ in range(frame.hc * 2)]
    layer = maps._ShiftedLayer([[0xFF] * frame.gw for _ in range(frame.hc)],
                               [[ink] * frame.gw for _ in range(frame.hc)])
    maps._last_street[0] = (frame.bbox, frame.gw, frame.hc, fills, layer, {})
    return frame


def _shifted(bbox, cells, gw):
    """`bbox` moved `cells` columns east."""
    colw = (bbox[2] - bbox[0]) / gw
    return (bbox[0] + cells * colw, bbox[1], bbox[2] + cells * colw, bbox[3])


class TestAWindowInsideTheMargin:
    def test_it_is_a_crop_and_asks_for_nothing(self, quiet, monkeypatch):
        gw, hc = maps.map_cells((COLS, ROWS))
        here = bbox_for(LAT, LON, ZOOM, gw, hc)
        loader = _Loader(_land(gw, hc, here))
        monkeypatch.setattr(maps, "_get_street", loader)
        frame = maps.render_map(LAT, LON, "New York", ZOOM, block=False,
                                view="street")
        assert loader.calls == []
        # painted to both edges, and not "loading"
        assert _braille_between(frame, 0, gw // 4) > 0
        assert _braille_between(frame, gw - gw // 4, gw) > 0
        assert "loading" not in frame.split("\n", 1)[0].lower()

    def test_a_pan_inside_the_margin_has_no_bare_leading_edge(
            self, quiet, monkeypatch):
        gw, hc = maps.map_cells((COLS, ROWS))
        here = bbox_for(LAT, LON, ZOOM, gw, hc)
        pw, _ph = over.padding(gw, hc)
        _land(gw, hc, here)
        loader = _Loader(None)
        monkeypatch.setattr(maps, "_get_street", loader)
        # the drag carries the view east by the margin and no further
        colw = (here[2] - here[0]) / gw
        lon = LON + pw * colw
        frame = maps.render_map(LAT, lon, "New York", ZOOM, block=False,
                                view="street", motion=(1, 0))
        assert loader.calls == []
        assert _braille_between(frame, gw - gw // 4, gw) > 0

    def test_an_overscan_that_lands_between_frames_is_taken_as_one(
            self, quiet, monkeypatch):
        gw, hc = maps.map_cells((COLS, ROWS))
        here = bbox_for(LAT, LON, ZOOM, gw, hc)
        loader = _Loader(None)
        monkeypatch.setattr(maps, "_get_street", loader)
        # the frame before it lands has nothing to cut from and asks
        maps.render_map(LAT, LON, "New York", ZOOM, block=False,
                        view="street")
        assert len(loader.calls) == 1
        # the loader lands it under its own key, as _get_street does
        frame, _at = over.plan(here, gw, hc)
        views._street_landed[0] = (frame.bbox, frame.gw, frame.hc,
                                         *loader.view(frame.gw, frame.hc))
        after = maps.render_map(LAT, LON, "New York", ZOOM, block=False,
                                view="street")
        assert len(loader.calls) == 1          # nothing more was asked
        assert _braille_between(after, 0, gw) > 0
        assert views.take_street() is None   # taken once

    def test_a_pan_past_the_margin_asks_for_one_centred_ahead(
            self, quiet, monkeypatch):
        gw, hc = maps.map_cells((COLS, ROWS))
        here = bbox_for(LAT, LON, ZOOM, gw, hc)
        pw, ph = over.padding(gw, hc)
        _land(gw, hc, here)
        loader = _Loader(None)
        monkeypatch.setattr(maps, "_get_street", loader)
        colw = (here[2] - here[0]) / gw
        lon = LON + 3 * pw * colw        # well past the margin
        maps.render_map(LAT, lon, "New York", ZOOM, block=False,
                        view="street", motion=(1, 0))
        assert len(loader.calls) == 1
        asked, agw, ahc, block = loader.calls[0]
        assert not block
        assert (agw, ahc) == (gw + 2 * pw, hc + 2 * ph)
        # centred ahead: the whole margin is east of the window, so the
        # built view's centre sits pw columns east of the window's
        window = bbox_for(LAT, lon, ZOOM, gw, hc)
        offset = ((asked[0] + asked[2]) - (window[0] + window[2])) / 2
        assert offset > 0
        assert offset == pytest.approx(pw * colw)

    def test_the_other_way_is_the_other_sign(self, quiet, monkeypatch):
        gw, hc = maps.map_cells((COLS, ROWS))
        here = bbox_for(LAT, LON, ZOOM, gw, hc)
        pw, _ph = over.padding(gw, hc)
        loader = _Loader(None)
        monkeypatch.setattr(maps, "_get_street", loader)
        maps.render_map(LAT, LON, "New York", ZOOM, block=False,
                        view="street", motion=(-1, 0))
        asked = loader.calls[0][0]
        colw = (here[2] - here[0]) / gw
        offset = ((asked[0] + asked[2]) - (here[0] + here[2])) / 2
        assert offset == pytest.approx(-pw * colw)

    def test_a_window_past_the_margin_still_has_a_bare_leading_edge(
            self, quiet, monkeypatch):
        # the margin is what a free pan is worth, and no more: past it
        # the frame is the last view reprojected, as it always was, and
        # the ground the window has moved onto is not drawn yet
        gw, hc = maps.map_cells((COLS, ROWS))
        here = bbox_for(LAT, LON, ZOOM, gw, hc)
        pw, _ph = over.padding(gw, hc)
        _land(gw, hc, here)
        monkeypatch.setattr(maps, "_get_street", _Loader(None))
        colw = (here[2] - here[0]) / gw
        frame = maps.render_map(LAT, LON + 4 * pw * colw, "New York", ZOOM,
                                block=False, view="street", motion=(1, 0))
        assert _braille_between(frame, gw - gw // 4, gw) == 0
        assert _braille_between(frame, 0, gw // 4) > 0


def _geo_view(bbox, gw, hc, *_a, **_k):
    """A view whose every sub-cell's colour is the ground it covers.

    Two windows over the same ground must therefore paint the same
    picture, whether one of them was cut out of something wider.
    """
    minlon, minlat, maxlon, maxlat = bbox
    colw, rowh = (maxlon - minlon) / gw, (maxlat - minlat) / (hc * 2)
    fills = [[(int(round((minlon + (x + .5) * colw) * 1e6)) % 251,
               int(round((maxlat - (y + .5) * rowh) * 1e6)) % 251, 40)
              for x in range(gw)] for y in range(hc * 2)]
    layer = maps._ShiftedLayer([[0] * gw for _ in range(hc)],
                               [[None] * gw for _ in range(hc)])
    return fills, layer, {}


class TestACropIsTheFrameAWindowBuildWouldDraw:
    def test_the_same_ground_paints_the_same_bytes(self, quiet, monkeypatch):
        gw, hc = maps.map_cells((COLS, ROWS))
        here = bbox_for(LAT, LON, ZOOM, gw, hc)
        pw, _ph = over.padding(gw, hc)
        colw = (here[2] - here[0]) / gw
        lon = LON + (pw - 1) * colw      # a pan to the far side of the margin
        monkeypatch.setattr(maps, "_get_street", _geo_view)

        # built for this window and nothing beyond it
        alone = maps.render_map(LAT, lon, "New York", ZOOM, block=True,
                                view="street")
        # and cut out of one built a margin wider
        frame, _at = over.plan(here, gw, hc, (1, 0))
        maps._last_street[0] = (frame.bbox, frame.gw, frame.hc,
                                *_geo_view(frame.bbox, frame.gw, frame.hc))
        cropped = maps.render_map(LAT, lon, "New York", ZOOM, block=False,
                                  view="street", motion=(1, 0))
        # a live frame ends with the escapes that arm the mouse; what is
        # being compared is the picture, line for line and byte for byte
        assert cropped.split("\n")[:-1] == alone.split("\n")[:-1]


class TestHoverThroughTheCrop:
    def test_the_pointer_names_what_is_drawn_under_it(self, quiet,
                                                      monkeypatch):
        gw, hc = maps.map_cells((COLS, ROWS))
        here = bbox_for(LAT, LON, ZOOM, gw, hc)
        frame, (dx, dy) = over.plan(here, gw, hc)
        ink = (255, 0, 0)
        owner = [[None] * frame.gw for _ in range(frame.hc)]
        owner[dy + 3][dx + 6] = 0
        layer = DotLayer(frame.bbox, frame.gw, frame.hc)
        layer.dots = [[0xFF] * frame.gw for _ in range(frame.hc)]
        layer.color = [[ink] * frame.gw for _ in range(frame.hc)]
        layer.owner = owner
        layer.hover = HoverIndex(
            owner, [("primary", "Brighton Avenue")], {}, {},
            [[0] * frame.gw for _ in range(frame.hc)])
        maps._last_street[0] = (
            frame.bbox, frame.gw, frame.hc,
            [[ink] * frame.gw for _ in range(frame.hc * 2)], layer, {})
        monkeypatch.setattr(maps, "_get_street", _Loader(None))
        # the index is the built view's; the window reads it offset, so
        # the pointer over window cell (6, 3) asks about (dx+6, dy+3)
        out = maps.render_map(LAT, LON, "New York", ZOOM, block=False,
                              view="street", mouse_pos=(7, 5))
        assert "Brighton Avenue" in out.split("\n", 1)[0]
        away = maps.render_map(LAT, LON, "New York", ZOOM, block=False,
                               view="street", mouse_pos=(8, 5))
        assert "Brighton Avenue" not in away.split("\n", 1)[0]


class TestBlockingFramesAreUntouched:
    def test_print_asks_for_the_windows_own_bbox(self, quiet, monkeypatch):
        gw, hc = maps.map_cells((COLS, ROWS))
        loader = _Loader(None)
        monkeypatch.setattr(maps, "_get_street", loader)
        maps.render_map(LAT, LON, "New York", ZOOM, block=True, view="street")
        asked, agw, ahc, block = loader.calls[0]
        assert block and (agw, ahc) == (gw, hc)
        assert asked == bbox_for(LAT, LON, ZOOM, gw, hc)

    def test_a_landed_overscan_does_not_answer_a_printed_frame(
            self, quiet, monkeypatch):
        gw, hc = maps.map_cells((COLS, ROWS))
        _land(gw, hc, bbox_for(LAT, LON, ZOOM, gw, hc))
        loader = _Loader(None)
        monkeypatch.setattr(maps, "_get_street", loader)
        maps.render_map(LAT, LON, "New York", ZOOM, block=True, view="street")
        assert loader.calls and loader.calls[0][1:3] == (gw, hc)


class TestTheDestinationFetch:
    def test_a_coast_asks_for_the_overscan_around_where_it_stops(
            self, quiet, monkeypatch):
        gw, hc = maps.map_cells((COLS, ROWS))
        monkeypatch.setattr(maps, "fetch_destination", lambda work: work())
        loader = _Loader(None)
        monkeypatch.setattr(maps, "_get_street", loader)
        maps.prefetch_view(LAT, LON, ZOOM, "street", gw, hc, "en")
        asked, agw, ahc, block = loader.calls[0]
        pw, ph = over.padding(gw, hc)
        assert block and (agw, ahc) == (gw + 2 * pw, hc + 2 * ph)
        # around the resting centre, not ahead of it
        window = bbox_for(LAT, LON, ZOOM, gw, hc)
        assert ((asked[0] + asked[2]) / 2
                == pytest.approx((window[0] + window[2]) / 2))
        assert ((asked[1] + asked[3]) / 2
                == pytest.approx((window[1] + window[3]) / 2))

    def test_the_terrain_register_asks_the_same_way(self, quiet, monkeypatch):
        gw, hc = maps.map_cells((COLS, ROWS))
        monkeypatch.setattr(maps, "fetch_destination", lambda work: work())
        calls = []
        monkeypatch.setattr(
            maps, "_get_elevation",
            lambda bbox, g, h, block, window=None: calls.append((g, h)))
        maps.prefetch_view(LAT, LON, 2.0, "terrain", gw, hc, "en")
        pw, ph = over.padding(gw, hc)
        assert calls == [(gw + 2 * pw, hc + 2 * ph)]
