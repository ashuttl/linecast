"""The composers write their rows the way compact_colors would leave them.

compose_terrain and compose_map leave out the colour escapes that
repeat the colour in effect, which compact_colors used to do in a pass
over the finished frame; compact_frame finishes the job on the header
and the footer.  These tests hold the two paths to the same bytes on
synthetic frames that use everything the composers draw: runs of one
colour, half-blocks, unpainted cells, glyphs plain and bold, a
contrast-picked ink, an empty glyph, borders, a coast, strokes, the
motorway ribbon, hover highlights and the dusk-dimmed ink.
"""

from types import SimpleNamespace

import pytest

from linecast.maps import paint
from linecast.radar.basemap import BORDER
from linecast.terminal import color as _color
from linecast.terminal.color import bg, escape_tables, fg

A, B, C, D = (24, 36, 48), (200, 120, 60), (90, 90, 90), (10, 200, 30)
INK, ROUTE = (200, 210, 220), (120, 210, 255)
W, H = 12, 3


@pytest.fixture(params=["truecolor", "256", "16", "none"])
def mode(request, monkeypatch):
    m = request.param
    monkeypatch.setattr(_color, "_COLOR_MODE", m)
    monkeypatch.setattr(paint, "BOLD", "\x1b[1m" if m != "none" else "")
    monkeypatch.setattr(paint, "RESET", "\x1b[0m" if m != "none" else "")
    return m


def _fills():
    """Six sub-pixel rows: runs of one colour, cells whose halves differ,
    and None where street mode leaves the ground unpainted."""
    return [
        [A, A, A, B, B, B, C, C, A, A, None, D],
        [A, A, B, B, B, C, C, C, A, None, None, D],
        [B, B, B, B, A, A, A, A, A, A, A, A],
        [B, B, B, B, A, A, A, A, A, A, A, A],
        [C, D, C, D, C, D, A, A, A, A, A, A],
        [C, C, C, C, C, C, A, A, A, B, B, B],
    ]


def _layer(dots, color, ribbon=()):
    return SimpleNamespace(dots=dots, color=color, ribbon=set(ribbon))


def _street():
    layer = _layer(
        dots=[[0, 0, 1, 3, 0, 0, 7, 0, 0, 0, 0, 1],
              [0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0],
              [0, 0, 0, 0, 0, 0, 4, 4, 0, 0, 0, 0]],
        color=[[None, None, C, C, None, None, D, None, None, None, None, B],
               [None] * 8 + [None, None, None, None],
               [None] * 6 + [D, D, None, None, None, None]],
        ribbon=[(1, 0), (2, 1), (3, 1)])
    route = _layer(dots=[[0] * 5 + [8, 0, 0, 0, 0, 0, 0],
                         [0] * 5 + [8, 0, 0, 0, 0, 0, 0],
                         [0] * W],
                   color=[[None] * 5 + [ROUTE] + [None] * 6,
                          [None] * 5 + [None] + [None] * 6,
                          [None] * W])
    overlays = {(4, 0): ("京", INK, True), (5, 0): ("", INK, False),
                (7, 0): ("é", None), (8, 1): ("x", (1, 2, 3)),
                (9, 2): ("y", None, True), (10, 0): ("z", INK)}
    dusk = [[(1.0, 1.0, 1.0)] * 4 + [(0.5, 0.5, 0.6)] * 4 + [None] * 4
            for _ in range(H)]
    return dict(fills=_fills(), layer=layer, overlays=overlays, graph_w=W,
                height_cells=H, strokes=[route], hot={(3, 0), (6, 2), (8, 1)},
                hot_glyphs={(7, 0), (8, 1)}, ink_dusk=dusk)


def _terrain():
    basemap = _layer(dots=[[0, 0, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0]] * H,
                     color=[[None, None, BORDER, D] + [None] * 8] * H)
    borders = _layer(dots=[[0] * W, [0, 0, 0, 0, 9, 9, 0, 0, 0, 0, 0, 0],
                           [0] * W], color=[[None] * W] * H)
    coast = [[0, 0, 0, 0, 0, 0, 0, 0, 0, 16, 16, 0], [0] * W,
             [0, 0, 0, 0, 0, 0, 32, 0, 0, 0, 0, 0]]
    rivers = _layer(dots=[[0] * W, [0] * 6 + [64, 64] + [0] * 4, [0] * W],
                     color=[[None] * W, [None] * 6 + [C, None] + [None] * 4,
                            [None] * W])
    route = _layer(dots=[[0] * 5 + [8] + [0] * 6, [0] * 6 + [8] + [0] * 5,
                         [0] * W],
                   color=[[None] * 5 + [ROUTE] + [None] * 6,
                          [None] * 6 + [ROUTE] + [None] * 5, [None] * W])
    overlays = {(4, 0): ("京", INK, True), (5, 0): ("", INK, False),
                (7, 0): ("é", None), (8, 1): ("x", (1, 2, 3)),
                (9, 2): ("y", None, True), (10, 0): ("z", INK)}
    return dict(basemap=basemap, terrain=_fills(), overlays=overlays,
                graph_w=W, height_cells=H, coast=coast,
                strokes=[rivers, route], borders=borders)


COMPOSERS = {"terrain": (paint.compose_terrain, _terrain),
             "street": (paint.compose_map, _street)}


@pytest.mark.parametrize("which", list(COMPOSERS))
def test_a_composed_frame_is_what_compact_colors_makes_of_the_spelled_out_one(
        mode, which):
    compose, inputs = COMPOSERS[which]
    raw = "\n".join(compose(**inputs(), compact=False))
    compact = "\n".join(compose(**inputs()))
    assert compact == paint.compact_colors(raw)
    assert paint.compact_colors(compact) == compact, "already compact"
    if mode in ("truecolor", "256"):
        assert len(compact) < len(raw)
    else:
        # a 16-colour SGR is kept and forgotten on; `none` has none at all
        assert compact == raw


@pytest.mark.parametrize("which", list(COMPOSERS))
def test_compact_frame_matches_the_pass_over_the_whole_frame(mode, which):
    compose, inputs = COMPOSERS[which]
    raw = compose(**inputs(), compact=False)
    lines = compose(**inputs())
    reset = paint.RESET
    dim = fg(*C)
    header = f"{fg(*B)}Portland{reset}{dim} · terrain{dim} · 12 m{reset}   "
    foot = f"{dim}├────┤{reset} {dim}500 m{reset}  {dim}© OSM{reset} {dim}?{reset}"
    whole = paint.compact_colors("\n".join([header, *raw, foot]))
    assert paint.compact_frame(header, lines, foot) == whole


def test_a_colour_the_header_leaves_in_effect_reaches_the_first_row(mode):
    # The first cell's background is the header's own, so the pass over
    # the whole frame drops it; compact_frame must know what the header
    # left in effect.  Without a RESET the header's colour runs on into
    # the footer too, as it does when there are no map rows at all.
    compose, inputs = COMPOSERS["terrain"]
    raw = compose(**inputs(), compact=False)
    lines = compose(**inputs())
    header = f"{bg(*A)}{fg(*B)}title"
    foot = f"{bg(*A)}{fg(*B)}credits{paint.RESET}"
    for rows, compact in (([*raw], lines), ([], [])):
        whole = paint.compact_colors("\n".join([header, *rows, foot]))
        assert paint.compact_frame(header, compact, foot) == whole


def test_the_escape_tables_are_fg_and_bg_by_tuple(monkeypatch):
    monkeypatch.setattr(_color, "_COLOR_MODE", "truecolor")
    fgs, bgs = escape_tables()
    assert fgs[(1, 2, 3)] == fg(1, 2, 3) == "\x1b[38;2;1;2;3m"
    assert bgs[(1.4, 300, -5)] == bg(1.4, 300, -5) == "\x1b[48;2;1;255;0m"
    assert (1, 2, 3) in fgs
    monkeypatch.setattr(_color, "_COLOR_MODE", "none")
    fgs, bgs = escape_tables()
    assert (1, 2, 3) not in fgs, "a mode change empties the tables"
    assert fgs[(1, 2, 3)] == fg(1, 2, 3) == ""
