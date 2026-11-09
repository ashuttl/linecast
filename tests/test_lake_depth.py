"""The vendored lake-depth grid, and the lake beds terrain paints from it."""

from linecast.maps import lake_depth as _lake_depth
from linecast.maps import paint


class TestGrid:
    def test_the_depths_are_where_the_lakes_are(self):
        wet = [(47.8, -88.0),       # Superior, off Isle Royale
               (44.0, -86.9),       # Lake Michigan, mid-lake
               (44.8, -82.3),       # Lake Huron, mid-lake
               (42.2, -81.2),       # Lake Erie's central basin
               (43.6, -77.8)]       # Lake Ontario, mid-lake
        dry = [(43.72, -79.40),     # Toronto, inland of the shore
               (44.43, -79.37),     # Lake Simcoe: a lake, but unsounded
               (40.0, -83.0),       # Columbus
               (25.0, 10.0)]        # the Sahara
        rows = _lake_depth.grid_for_lls([wet + dry + [None]])
        depths = list(rows[0])
        assert all(d > 20.0 for d in depths[:len(wet)])
        assert depths[len(wet):] == [0.0] * (len(dry) + 1)

    def test_superior_is_the_deepest_and_erie_the_shallowest(self):
        rows = _lake_depth.grid_for_lls([[(47.8, -88.0), (42.2, -81.2)]])
        superior, erie = rows[0]
        assert superior > 200.0
        assert 10.0 < erie < 40.0

    def test_no_sounded_lake_in_view_means_no_grid(self):
        assert _lake_depth.grid_for_lls([[(25.0, 10.0), None]]) is None
        assert _lake_depth.grid_for_bbox((0.0, 20.0, 20.0, 30.0), 8, 4) is None
        # Lake Simcoe alone: inside the region's box, and unsounded
        assert _lake_depth.grid_for_bbox((-79.6, 44.3, -79.2, 44.6), 8,
                                         4) is None

    def test_a_flat_view_runs_north_to_south(self):
        # one column down 87°W, a degree a row from 47.5°N: Superior,
        # the Upper Peninsula, Lake Michigan, Illinois
        rows = _lake_depth.grid_for_bbox((-87.1, 40.0, -86.9, 48.0), 1, 8)
        depths = [row[0] for row in rows]
        assert depths[0] > 0.0 and depths[1] == 0.0
        assert depths[3] > 0.0 and depths[4] > 0.0 and depths[5] > 0.0
        assert depths[6] == 0.0 and depths[7] == 0.0

    def test_in_view_is_the_regions_box(self):
        assert _lake_depth.in_view((-90.0, 44.0, -80.0, 48.0))
        assert _lake_depth.in_view((-100.0, 30.0, -60.0, 60.0))
        assert not _lake_depth.in_view((-10.0, 44.0, 10.0, 48.0))
        assert not _lake_depth.in_view((-90.0, 20.0, -80.0, 30.0))


class TestPaint:
    """A wet sub-pixel with a depth is painted as the sea is at that
    depth; without one it keeps the flat lake tint, and a dry one never
    reads it."""

    def _buffer(self, depth, elev=180.0, water=(False, True, True)):
        grid = [[elev] * 3 for _ in range(2)]
        return paint.build_terrain_buffer(grid, (-88.0, 44.0, -87.0, 45.0),
                                          3, 2, water=[list(water)] * 2,
                                          depth=depth)

    def test_a_sounded_lake_is_the_sea_at_its_depth(self):
        shallow = self._buffer([[0.0, 0.0, 5.0]] * 2)
        deep = self._buffer([[300.0] * 3] * 2, water=(True, True, True))
        flat = self._buffer(None)
        sea = self._buffer(None, elev=-300.0, water=(False, False, False))
        assert flat[0][1] == flat[0][2]              # one tint, unsounded
        assert shallow[0][1] == flat[0][1]           # a depth of 0 is the tint
        assert deep[0][1] == sea[0][1]               # one scale of depth
        assert sum(deep[0][1]) < sum(shallow[0][2])

    def test_a_dry_sub_pixel_ignores_the_depth(self):
        with_depth = self._buffer([[300.0, 0.0, 0.0]] * 2)
        without = self._buffer(None)
        assert with_depth[0][0] == without[0][0]
