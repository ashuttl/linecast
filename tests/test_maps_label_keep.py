"""Names carried from one street view to the next (labels.label_overlays's
`keep`): a view built one pan over writes the names it had where they
were, on the ground they stood on, and places afresh only what is new.

Driven by hand-encoded tiles over the whole world, as test_maps_labels
is: at gw=40 the z0 tile's x of 2048 is column 20, and a pan is a bbox
moved by whole columns of nine degrees.
"""

from linecast.maps import labels as lb
from linecast.maps import streets as st

from test_maps_labels import GW, HC, WORLD, _truecolor, lines, overlays  # noqa: F401
from test_maps_labels import text_at
from test_maps_streets import polyline, tile
from linecast.maps import style as _maps_style


def _road(y=1024):
    """One primary road right across the tile, on one row."""
    return (lines("transportation",
                  (polyline((0, y), (4095, y)), {"class": "primary"})),
            lines("transportation_name",
                  (polyline((0, y), (4095, y)),
                   {"class": "primary", "name": "Forest Avenue"})))


def _overlays(bbox, keep=(), placed=None, band=7):
    road, names = _road()
    view = st.decode_view({(0, 0, 0): tile(road, names)})
    return lb.label_overlays(view, bbox, GW, HC, band, _maps_style.palette(),
                             "en", (), None, keep=keep, placed=placed)


def _shifted(cols):
    """WORLD moved east by whole columns."""
    colw = (WORLD[2] - WORLD[0]) / GW
    return (WORLD[0] + cols * colw, WORLD[1], WORLD[2] + cols * colw, WORLD[3])


def _start(ov, text):
    """(col, row) of the first letter of `text` on the page, or None."""
    cells = sorted((c, r) for (c, r), (ch, *_rest) in ov.items())
    for c, r in cells:
        if "".join(ov.get((c + i, r), (" ",))[0] for i in range(len(text))) == text:
            return c, r
    return None


class TestNamesAreCarried:
    def test_a_view_records_where_it_wrote_its_names(self):
        placed = []
        ov = _overlays(WORLD, placed=placed)
        at = _start(ov, "Forest Avenue")
        assert at is not None
        assert [(how, kind, name, text) for how, kind, name, text, *_g in placed] == [
            ("beside", "road", "Forest Avenue", "Forest Avenue")]
        _how, _kind, _name, _text, lat, lon, anchor = placed[0]
        assert anchor is None
        # the ground under the first letter, by the bbox's box
        colw, rowh = (WORLD[2] - WORLD[0]) / GW, (WORLD[3] - WORLD[1]) / HC
        assert lon == WORLD[0] + (at[0] + 0.5) * colw
        assert lat == WORLD[3] - (at[1] + 0.5) * rowh

    def test_the_next_view_writes_them_where_they_were(self):
        placed = []
        first = _overlays(WORLD, placed=placed)
        c0, r0 = _start(first, "Forest Avenue")
        # a pan of three columns east carries the ground three columns
        # west; the name goes with it, whatever anchor the road's
        # newly clipped path would otherwise have offered
        kept = _overlays(_shifted(3), keep=placed)
        assert _start(kept, "Forest Avenue") == (c0 - 3, r0)
        assert text_at(kept, r0).count("Forest Avenue") == 1

    def test_a_name_whose_ground_has_left_the_page_is_placed_afresh(self):
        placed = []
        _overlays(WORLD, placed=placed)
        # a pan of thirty columns: the ground the name stood on is off
        # the page, and the road, still on it, is named anew
        fresh = _overlays(_shifted(30), keep=placed)
        assert _start(fresh, "Forest Avenue") is not None
        assert text_at(fresh, _start(fresh, "Forest Avenue")[1]).count(
            "Forest Avenue") == 1

    def test_what_is_kept_is_recorded_again_for_the_view_after(self):
        placed = []
        _overlays(WORLD, placed=placed)
        again = []
        _overlays(_shifted(3), keep=placed, placed=again)
        assert [p[:4] for p in again] == [p[:4] for p in placed]
        # three columns further east on the ground
        colw = (WORLD[2] - WORLD[0]) / GW
        assert again[0][5] == placed[0][5]       # same ground, same lon
        assert again[0][4] == placed[0][4]
