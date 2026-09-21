"""The baked world texture: what it carries, and how a frame reads it.

The globe's fill, coastline, lakes and borders all come out of one
equirectangular bake now, so what these tests pin is the bake being the
same planet every time, the sampler finding the texel a sub-pixel is
actually over (both hemispheres, and across the antimeridian), the
borders surviving the resample at every pitch a frame reads them at,
the disk cache round-tripping under a name that changes with the theme,
and the old path drawing while the first bake runs — and after one
that failed, until the hold on it lifts.
"""

import sys
import threading
import zlib
from array import array
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import (  # noqa: E402
    _globe, _globe_texture, _maps_paint, _maps_views, _theme,
)

SMALL = (32, 16)    # mask texels: a planet small enough to bake in a blink


def _pixel(metres, alpha=255):
    v = int(metres + 32768)
    return bytes((v >> 8, v & 0xFF, 0, alpha))


def _canvas(world, ground):
    """A stitched world canvas, `ground(x, y)` metres at each pixel."""
    rows = [b"".join(_pixel(ground(x, y)) for x in range(world))
            for y in range(world)]
    return bytearray(b"".join(rows)), world, world, 0, 0, world


def _flat_canvas(world, metres):
    """The same, one height everywhere, without the per-pixel loop."""
    return (bytearray(_pixel(metres) * world * world),
            world, world, 0, 0, world)


def _land_east(x, y):
    # dry ground on the canvas's eastern half, deep sea on its western
    return 900.0 if x >= 8 else -3000.0


@pytest.fixture
def tiny(monkeypatch, tmp_path):
    """Bake the whole planet into 32x16 texels from a stub canvas."""
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(_globe_texture, "_mask_dims", lambda z: SMALL)
    monkeypatch.setattr(_globe, "_world_canvas",
                        lambda z, t: _canvas(16, _land_east))
    _globe_texture.clear()
    yield
    _globe_texture.clear()


def _planes(tex, level=0):
    lv = tex.levels[level]
    return lv.r.at(0), lv.g.at(0), lv.b.at(0)


class TestBake:
    def test_is_the_same_planet_every_time(self, tiny):
        one, _holes = _globe_texture.bake(1, "terrain")
        two, _holes = _globe_texture.bake(1, "terrain")
        assert one.mask.at(0) == two.mask.at(0)
        assert _planes(one) == _planes(two)
        assert one.levels[0].elev.at(0) == two.levels[0].elev.at(0)

    def test_carries_the_canvas_as_water_and_land(self, tiny):
        tex, _holes = _globe_texture.bake(1, "terrain")
        mask = tex.mask.at(0)
        mw, mh = SMALL
        row = mask[(mh // 2) * mw:(mh // 2 + 1) * mw]
        # the canvas is dry from its column 8 on, which is longitude 0;
        # the two texels either side of a shore blend across it
        assert all(b & _globe_texture.WATER for b in row[1:mw // 2])
        assert not any(b & _globe_texture.WATER
                       for b in row[mw // 2 + 1:mw - 1])
        assert all(b & _globe_texture.SAMPLED for b in row)

    def test_levels_halve_and_keep_the_metres(self, tiny):
        tex, _holes = _globe_texture.bake(1, "terrain")
        assert [(lv.w, lv.h) for lv in tex.levels] == [(16, 8), (8, 4)]
        deep = tex.levels[0].elev.at(0)
        assert min(deep) <= -3000 and max(deep) >= 900

    def test_street_bakes_no_colour(self, tiny):
        tex, _holes = _globe_texture.bake(1, "street")
        assert all(lv.r is None for lv in tex.levels)
        assert len(tex.levels[0].elev.at(0)) == 16 * 8

    def test_a_hole_in_the_canvas_is_never_cached(self, monkeypatch):
        monkeypatch.setattr(_globe_texture, "_mask_dims", lambda z: SMALL)
        canvas = _canvas(16, _land_east)
        canvas[0][:4] = _pixel(0.0, alpha=0)
        monkeypatch.setattr(_globe, "_world_canvas", lambda z, t: canvas)
        _tex, holes = _globe_texture.bake(1, "terrain")
        assert holes


class TestLevelChoice:
    def test_takes_the_coarsest_that_still_fits_a_sub_pixel(self, tiny):
        tex, _holes = _globe_texture.bake(1, "terrain")
        # levels span 180/8 = 22.5 and 180/4 = 45 degrees a texel
        assert _globe_texture.level_for(tex, 100.0, 1) == 1   # 50 a sub-pixel
        assert _globe_texture.level_for(tex, 60.0, 1) == 0    # 30 a sub-pixel
        assert _globe_texture.level_for(tex, 20.0, 1) == 0    # finer than both


def _texture(fw, fh, painted, borders=()):
    """A one-level texture with `painted` = {texel index: (r, g, b)}.

    `borders` are texel indices of the level's own border plane.
    """
    mask = _globe_texture._BytePlane(
        [bytes([_globe_texture.SAMPLED] * (fw * 2)) for _ in range(fh * 2)])
    planes = []
    for channel in range(3):
        rows = []
        for y in range(fh):
            row = bytearray(fw)
            for x in range(fw):
                hit = painted.get(y * fw + x)
                if hit is not None:
                    row[x] = hit[channel]
            rows.append(bytes(row))
        planes.append(_globe_texture._BytePlane(rows))
    elev = _globe_texture._ShortPlane([array("h", [100] * fw)
                                       for _ in range(fh)])
    edge = []
    for y in range(fh):
        row = bytearray(fw)
        for x in range(fw):
            if y * fw + x in borders:
                row[x] = 1
        edge.append(bytes(row))
    return _globe_texture.Texture(
        1, "terrain", mask, fw * 2, fh * 2,
        (_globe_texture.Level(fw, fh, *planes, elev,
                              _globe_texture._BytePlane(edge)),))


class TestSampling:
    # a centre on a texel boundary, so the roll is exact and the test
    # is about the lookup rather than about half a texel of rounding
    FW, FH = 128, 64
    GW, HC, ZOOM = 60, 16, 130.0

    def _round_trip(self, lon0, row, col):
        lat0 = 20.0
        lls, _zs, _rhos = _globe.geometry(lat0, lon0, self.ZOOM,
                                          self.GW, self.HC * 2)
        lat, lon = lls[row][col]
        want = (min(self.FH - 1, int((90.0 - lat) / 180.0 * self.FH))
                * self.FW + int((lon + 180.0) / 360.0 * self.FW) % self.FW)
        ink = (11, 22, 33)
        tex = _texture(self.FW, self.FH, {want: ink})
        shot = _globe_texture.sample(tex, lat0, lon0, self.ZOOM,
                                     self.GW, self.HC, (0, 0, 0))
        assert shot.fill[row][col] == ink

    def test_northern_sample(self):
        self._round_trip(0.0, 10, 30)

    def test_southern_sample(self):
        self._round_trip(0.0, 24, 30)

    def test_across_the_antimeridian(self):
        # 177.1875 is a whole number of texels, and a hair west of 180
        self._round_trip(177.1875, 16, 30)
        self._round_trip(-177.1875, 16, 40)

    def test_an_off_texel_centre_lands_within_a_texel(self):
        # Every test above centres the view on a texel boundary, where
        # the roll is exact.  Half a texel off is the most it can
        # round away, and the sample must still land in the texel the
        # geometry names or one of its neighbours — not two out.
        lat0 = 20.0
        lon0 = 180.0 / self.FW        # half of a texel's 2.8125 degrees
        row, col = 18, 34
        lls, _zs, _rhos = _globe.geometry(lat0, lon0, self.ZOOM,
                                          self.GW, self.HC * 2)
        lat, lon = lls[row][col]
        ty = min(self.FH - 1, int((90.0 - lat) / 180.0 * self.FH))
        tx = int((lon + 180.0) / 360.0 * self.FW) % self.FW
        ink = (11, 22, 33)

        def shot_at(offsets):
            tex = _texture(self.FW, self.FH,
                           {ty * self.FW + (tx + d) % self.FW: ink
                            for d in offsets})
            return _globe_texture.sample(tex, lat0, lon0, self.ZOOM,
                                         self.GW, self.HC, (0, 0, 0))

        assert shot_at((-1, 0, 1)).fill[row][col] == ink
        assert shot_at((-2, 2)).fill[row][col] != ink

    def test_space_stays_off_the_planet(self):
        tex = _texture(self.FW, self.FH, {})
        shot = _globe_texture.sample(tex, 20.0, 0.0, self.ZOOM,
                                     self.GW, self.HC, (0, 0, 0))
        assert shot.elev[0][0] is None
        assert not shot.land[0][0] and not shot.water[0][0]
        assert shot.elev[self.HC][self.GW // 2] == 100


def _dots(layer):
    """A braille layer expanded back to a (row, column) set of dots."""
    out = set()
    for cy, row in enumerate(layer.dots):
        for cx, mask in enumerate(row):
            for dx in range(2):
                for dy in range(4):
                    if mask & _globe_texture._BITS[dx][dy]:
                        out.add((cy * 4 + dy, cx * 2 + dx))
    return out


class TestBorders:
    """A slanted border, read back at every pitch a frame can ask for.

    The three border planes are a factor of two apart and a frame
    takes the coarsest still no coarser than its own dots, so a dot
    spans between one and two texels of whichever plane it reads and
    the stroke is cut two texels wide for that.  The one place it runs
    out is the wide end: `_globe._source_zoom` floors at 1 and level 1
    is the coarsest plane there is, so a terminal under about twelve
    rows at its widest zoom puts nearly three of level 1's texels
    under a dot.  Both are pinned below.
    """
    # a straight lat/lon run at about thirty degrees, across a third
    # of the planet: the resample that dashes a thin stroke
    LINE = [(lon, -30.0 + (lon + 60.0) * 0.5) for lon in range(-60, 61, 2)]

    # (map height in cells, zoom, the plane it reads, the texels a dot
    # spans there).  The mask is source zoom 1's own, 1024 texels
    # across, so its pitch is 0.352 degrees, level 0's 0.703 and level
    # 1's 1.406.
    CASES = [
        (43, 130.0, 1, 1.07),   # a 160x45 terminal at its widest zoom
        (43, 90.0, 0, 1.49),
        (30, 120.0, 1, 1.42),
        (24, 70.0, 1, 1.04),
        (22, 130.0, 2, 1.05),   # an 80x24 terminal at its widest zoom
        (20, 90.0, 1, 1.60),
        (14, 120.0, 2, 1.52),
        (12, 110.0, 2, 1.63),
        (10, 100.0, 2, 1.78),
    ]

    @pytest.fixture
    def slanted(self, monkeypatch):
        data = {"borders": [self.LINE], "lakes": ()}
        monkeypatch.setattr(_globe_texture, "_load_data", lambda: data)
        monkeypatch.setattr(_globe, "_load_data", lambda: data)
        monkeypatch.setattr(_globe_texture, "_mask_dims",
                            lambda z: (1024, 512))
        monkeypatch.setattr(_globe, "_world_canvas",
                            lambda z, t: _flat_canvas(512, 500.0))
        return _globe_texture.bake(1, "street")[0]

    def test_a_slanted_border_resamples_without_gaps(self, slanted):
        for hc, zoom, plane, ratio in self.CASES:
            where = f"hc={hc} zoom={zoom}"
            assert _globe_texture.border_level_for(
                slanted, zoom, hc) == plane, where
            pitch = 180.0 / _globe_texture._border_planes(slanted)[plane][1]
            assert abs(zoom / (hc * 4.0) / pitch - ratio) < 0.05, where
            by_column = {}
            for dy, dx in _dots(_globe_texture.sample(
                    slanted, 20.0, 0.0, zoom, hc * 3, hc, (0, 0, 0)).borders):
                by_column.setdefault(dx, []).append(dy)
            columns = sorted(by_column)
            # no column the border crosses is left empty, and the dots
            # in one column touch the dots in the next: a stroke that
            # came back dashed fails one or the other
            assert len(columns) > 20, where
            assert columns == list(range(columns[0], columns[-1] + 1)), where
            for a, b in zip(columns, columns[1:]):
                assert (min(by_column[b]) - max(by_column[a]) <= 1
                        and min(by_column[a]) - max(by_column[b]) <= 1), where

    def test_past_the_floor_the_border_thins_rather_than_going(self, slanted):
        # The one pitch the stroke does not survive whole: a ten-row
        # terminal at its widest, where a dot spans 2.9 of level 1's
        # texels and there is no coarser plane to read.  The planet is
        # forty dots across there; what it costs is a dot here and
        # there on a disk that has few to begin with.
        hc, gw, zoom = 8, 24, 130.0
        pitch = 180.0 / _globe_texture._border_planes(slanted)[2][1]
        assert abs(zoom / (hc * 4.0) / pitch - 2.89) < 0.05
        textured = _dots(_globe_texture.sample(slanted, 20.0, 0.0, zoom,
                                               gw, hc, (0, 0, 0)).borders)
        built = _dots(_globe.border_layer(20.0, 0.0, zoom, gw, hc, (0, 0, 0)))
        assert 0.5 < len(textured) / len(built) < 1.2


class TestDiskCache:
    def test_round_trips(self, tiny):
        tex, _holes = _globe_texture.bake(1, "terrain")
        _globe_texture._store(1, "terrain", tex)
        back = _globe_texture._load(1, "terrain")
        assert back is not None
        assert back.mask.at(0) == tex.mask.at(0)
        assert back.mask_w == tex.mask_w and back.mask_h == tex.mask_h
        assert _planes(back) == _planes(tex)
        assert back.levels[0].elev.at(0) == tex.levels[0].elev.at(0)

    def test_a_new_theme_misses_it(self, tiny, monkeypatch):
        tex, _holes = _globe_texture.bake(1, "terrain")
        _globe_texture._store(1, "terrain", tex)
        assert _globe_texture._load(1, "terrain") is not None
        # a theme change re-inks every ramp the bake was shaded with
        monkeypatch.setattr(_maps_paint, "HYPSO_FAMILIES",
                            [[(0, (1, 2, 3))]] * 4)
        assert _globe_texture._load(1, "terrain") is None

    def test_a_short_file_is_rebaked_not_sampled(self, tiny):
        # a plane that came up short would not fail on load but on the
        # first frame that samples it, and on every frame after
        tex, _holes = _globe_texture.bake(1, "terrain")
        path = _globe_texture._path(1, "terrain")
        blob = zlib.decompress(_globe_texture._dump(tex))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(zlib.compress(blob[:-100]))
        assert _globe_texture._load(1, "terrain") is None

    def test_generation_misses_the_memo(self):
        before = _globe_texture._key(1, "terrain")
        gen = _theme.generation
        try:
            _theme.generation = gen + 1
            assert _globe_texture._key(1, "terrain") != before
        finally:
            _theme.generation = gen

    def test_the_street_name_ignores_the_inks(self, tiny, monkeypatch):
        before = _globe_texture._path(1, "street")
        monkeypatch.setattr(_maps_paint, "HYPSO_FAMILIES",
                            [[(0, (1, 2, 3))]] * 4)
        assert _globe_texture._path(1, "street") == before


class _Dead:
    """A thread that never starts, for a test that expects none."""
    def start(self):
        pytest.fail("a worker was started")


class TestFirstFrame:
    def test_one_bake_per_key_and_the_old_path_meanwhile(self, tiny,
                                                         monkeypatch):
        held = threading.Event()
        calls = []

        def slow_bake(z, register, timeout=15):
            calls.append((z, register))
            held.wait(5)
            return _texture(8, 4, {}), False

        monkeypatch.setattr(_globe_texture, "bake", slow_bake)
        try:
            for _ in range(5):
                assert _globe_texture.for_view(130.0, 120, "terrain",
                                               False) is None
            assert not _globe_texture.ready(130.0, 120, "terrain")
            held.set()
            for _ in range(50):
                if _globe_texture.ready(130.0, 120, "terrain"):
                    break
                threading.Event().wait(0.02)
            assert _globe_texture.ready(130.0, 120, "terrain")
            assert calls == [(1, "terrain")]
        finally:
            held.set()

    def test_a_texture_on_disk_is_read_on_the_view_thread(self, tiny,
                                                           monkeypatch):
        # nothing to bake, so nothing goes to a thread: the first live
        # miss comes back with the texture, and the old path never runs
        tex = _texture(8, 4, {})
        monkeypatch.setattr(_globe_texture, "_load",
                            lambda z, register: tex)
        monkeypatch.setattr(_globe_texture, "bake",
                            lambda *a, **k: pytest.fail("baked"))
        started = []
        monkeypatch.setattr(threading, "Thread",
                            lambda *a, **k: started.append(k) or _Dead())
        assert _globe_texture.for_view(130.0, 120, "terrain", False) is tex
        assert not started
        assert _globe_texture.ready(130.0, 120, "terrain")

    def test_a_theme_change_under_the_bake_throws_it_away(self, tiny,
                                                          monkeypatch):
        # bands shaded before the change carry the old inks; the result
        # must reach neither the memo nor the disk
        stored = []
        monkeypatch.setattr(_globe_texture, "_store",
                            lambda z, r, t: stored.append(z))
        gen = _theme.generation

        def bake_under_a_new_theme(z, register, timeout=15):
            _theme.generation += 1
            return _texture(8, 4, {}), False

        monkeypatch.setattr(_globe_texture, "bake", bake_under_a_new_theme)
        try:
            assert _globe_texture.for_view(130.0, 120, "terrain",
                                           True) is None
            assert not stored
            assert not _globe_texture.ready(130.0, 120, "terrain")
            assert not _globe_texture._pending
        finally:
            _theme.generation = gen

    def test_a_failed_bake_is_held_off_rather_than_retried(self, tiny,
                                                            monkeypatch):
        # Without the hold every repaint of a view whose bake raises
        # would start another worker to raise the same way, and a live
        # view repaints many times a second.
        calls = []

        def angry_bake(z, register, timeout=15):
            calls.append(z)
            raise OSError("no tiles")

        monkeypatch.setattr(_globe_texture, "bake", angry_bake)
        for _ in range(5):
            assert _globe_texture.for_view(130.0, 120, "terrain",
                                           True) is None
        assert calls == [1]
        assert not _globe_texture._pending
        key = _globe_texture._key(1, "terrain")
        _globe_texture._held[key] -= _globe_texture._BAKE_HOLD_S + 1
        assert _globe_texture.for_view(130.0, 120, "terrain", True) is None
        assert calls == [1, 1]


class TestThroughTheView:
    """What `_maps_views._get_globe` hands back, baked and unbaked."""
    ARGS = (20.0, 10.0, 130.0, 30, 12)

    def test_the_view_falls_back_to_elevation(self, tiny, monkeypatch):
        # a bake that raises leaves the frame to the old path, and the
        # frame has to come out whole
        def angry_bake(z, register, timeout=15):
            raise OSError("no tiles")

        monkeypatch.setattr(_globe_texture, "bake", angry_bake)
        view = _maps_views._get_globe(*self.ARGS, True)
        assert view.fill is None and view.wet is None
        assert view.elev is not None and view.coast is not None
        assert view.borders is not None

    def test_a_ready_texture_changes_the_view_key(self, tiny, monkeypatch):
        # the view drawn the long way while the planet baked must not
        # be the one still on screen after the bake lands
        baked = []
        monkeypatch.setattr(_globe_texture, "for_view",
                            lambda *a, **k: baked[0] if baked else None)
        cold = _maps_views._get_globe(*self.ARGS, True)
        assert cold.fill is None

        tex, _holes = _globe_texture.bake(1, "terrain")
        _globe_texture._finish(_globe_texture._key(1, "terrain"), tex)
        baked.append(tex)
        assert _globe_texture.ready(130.0, 48, "terrain")

        warm = _maps_views._get_globe(*self.ARGS, True)
        assert warm.fill is not None and warm.wet is not None
        assert warm.elev is not None and warm.coast is not None
