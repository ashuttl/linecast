"""The final painted cells of chips over charts and other overlays."""

import pytest

from linecast.terminal import bidi, color, composition, live
from linecast.terminal.composition import SHADOW, resolve_shadows
from test_maps_color_runs import painted


@pytest.fixture(autouse=True)
def inks(monkeypatch):
    monkeypatch.setattr(color, "_COLOR_MODE", "truecolor")
    monkeypatch.setattr(color, "RESET", "\033[0m")


def shadow(glyph, row=1, col=1):
    return f"\033[{row};{col}H\033[0m{SHADOW}\033[38;2;90;90;90m{glyph}\033[0m"


def cell(body, floating, row=0, col=0):
    out = live.frame_paint(body, floating)
    assert "999" not in out
    return painted(out)[row][col]


@pytest.mark.parametrize("sgr,expected", [
    ("48;2;12;34;56", (2, 12, 34, 56)),
    ("48;5;137", (5, 137)), ("44", 44), ("104", 104),
    ("48;5;137;49", None), ("48;5;137;0", None), ("", None),
])
def test_background_colors_and_resets(sgr, expected):
    assert cell(f"\033[{sgr}m⣷", shadow("▀"))[2] == expected


@pytest.mark.parametrize("glyph,shadow_glyph,expected", [
    ("▀", "▄", (5, 25)), ("▀", "▀", (5, 66)),
    ("▄", "▀", (5, 25)), ("▄", "▄", (5, 66)),
    ("█", "▀", (5, 25)), ("█", "▄", (5, 25)),
    ("⣷", "▀", (5, 66)), ("a", "▄", (5, 66)),
])
def test_samples_the_exposed_half(glyph, shadow_glyph, expected):
    assert cell("\033[38;5;25;48;5;66m" + glyph, shadow(shadow_glyph))[2] == expected


def test_reverse_video_is_an_effective_background():
    out = resolve_shadows("\033[31;44;7ma", shadow("▀"))
    assert "\033[41m" in out


def test_wide_glyphs_marks_and_links_keep_sample_coordinates():
    body = ("\033[48;5;18m界é\033]8;;https://example.org\033\\"
            "\033[48;5;22mZ\033]8;;\033\\")
    assert "\033[48;5;18m" in resolve_shadows(body, shadow("▀", col=2))
    assert "\033[48;5;22m" in resolve_shadows(body, shadow("▀", col=4))


def test_background_carries_across_body_rows_but_not_into_overlay():
    body = "\033[48;5;18mabc\nabc"
    assert cell(body, shadow("▀", row=2), row=1)[2] == (5, 18)
    floating = "\033[2;1Hx" + shadow("▀", row=2)
    assert cell(body, floating, row=1)[2] is None


def test_shadow_does_not_measure_uncovered_chart_rows(monkeypatch):
    measured = []
    glyphs = composition.glyphs

    def measure(text):
        measured.append(text)
        return glyphs(text)

    monkeypatch.setattr(composition, "glyphs", measure)
    rows = ["\033[48;5;18muncovered\033[0m"] * 80
    rows[39] = "\033[48;5;22mcovered\033[0m"
    output = resolve_shadows("\n".join(rows), shadow("▀", row=40))
    assert "\033[48;5;22m" in output
    assert "covered" in measured
    assert "uncovered" not in measured


@pytest.mark.parametrize("reset", ["\033[0m", "\033[m", "\033[0;48;5;20m", ""])
def test_skipped_rows_preserve_the_state_after_their_last_reset(reset):
    body = ("\033[31;48;5;18mfirst\n"
            f"{reset}\033[48;5;22msecond\n"
            "\033[38;5;25m▀")
    assert cell(body, shadow("▀", row=3), row=2)[2] == (5, 22)
    assert cell(body, shadow("▄", row=3), row=2)[2] == (5, 25)


def test_skipped_rows_carry_reverse_video_until_it_is_reset():
    body = "\033[31;44;7mfirst\nsecond\nx"
    assert "\033[41m" in resolve_shadows(body, shadow("▀", row=3))
    body = "\033[31;44;7mfirst\n\033[27msecond\nx"
    assert "\033[44m" in resolve_shadows(body, shadow("▀", row=3))


def test_blank_space_beyond_body_uses_default_background():
    assert cell("\033[48;5;18mx", shadow("▀", col=5), col=4)[2] is None
    assert cell("x", shadow("▀", row=5), row=4)[2] is None


def test_stacked_overlays_use_the_last_painted_half():
    body = "\033[48;5;18mxxx"
    floating = "\033[1;1H\033[48;5;22mabc" + shadow("▄") + shadow("▀")
    assert cell(body, floating)[2] == (2, 54, 92, 54)
    floating = "\033[1;1H\033[48;5;22mabc" + shadow("▀") + shadow("▀")
    assert cell(body, floating)[2] == (5, 22)


def test_chip_samples_after_screen_edge_placement():
    body = "\n".join("\033[48;5;18m" + "x" * 8 for _ in range(5))
    floating = live.chip_at(["abc", "def"], 5, 8, 8, rows=5)
    grid = painted(live.frame_paint(body, floating), cols=8, rows=5)
    assert grid[2][7][0::2] == ("▄", (5, 18))
    assert [c[0] for c in grid[4][5:]] == ["▀"] * 3
    assert all(c[2] == (5, 18) for c in grid[4][5:])


def test_mirrored_chip_samples_displayed_coordinates(monkeypatch):
    bidi.configure("fa", {"LINECAST_BIDI": "linecast"})
    bidi.set_mirror(True)
    monkeypatch.setattr(live, "_mirror_width", lambda: 8)
    try:
        body = "\033[48;5;18m⣷⣷⣷⣷\033[48;5;22m⣷⣷⣷⣷\033[0m\n" * 3
        floating = live.chip_at(["ab"], 1, 2, 8, rows=3)
        grid = painted(live.frame_paint(body, floating), cols=8, rows=4)
        assert grid[0][4][0::2] == ("▄", (5, 18))
        assert [c[0] for c in grid[1][4:6]] == ["▀", "▀"]
        assert all(c[2] == (5, 18) for c in grid[1][4:6])
    finally:
        bidi.configure("en", {})
        bidi.set_mirror(False)


def test_no_color_still_resolves_internal_markers(monkeypatch):
    monkeypatch.setattr(color, "_COLOR_MODE", "none")
    floating = live.chip_at(["ab"], 1, 1, 8, rows=3)
    out = live.frame_paint("chart", floating)
    assert "999" not in out
    assert "▄" in out and "▀" in out


@pytest.mark.parametrize("glyph,expected_fg,expected_bg", [
    ("▀", (2, 62, 70, 78), (2, 100, 120, 140)),
    ("▄", (2, 94, 102, 110), (2, 20, 40, 60)),
    ("█", (2, 62, 70, 78), (2, 94, 102, 110)),
])
def test_shadow_is_40_percent_transparent_in_each_covered_half(
        glyph, expected_fg, expected_bg):
    body = "\033[38;2;20;40;60;48;2;100;120;140m▀"
    result = cell(body, shadow(glyph))
    assert result[1:3] == (expected_fg, expected_bg)


@pytest.mark.parametrize("mode", ["256", "16"])
def test_blending_respects_output_color_mode(mode, monkeypatch):
    monkeypatch.setattr(color, "_COLOR_MODE", mode)
    out = resolve_shadows("\033[48;2;20;40;60mx", shadow("▀"))
    assert color.fg(62, 70, 78) + "▀" in out


def test_palette_colors_are_resolved_from_current_theme(monkeypatch):
    from linecast.terminal import theme
    monkeypatch.setattr(theme, "theme_ansi", ((20, 40, 60),) * 16)
    assert cell("\033[44mx", shadow("▀"))[1] == (2, 62, 70, 78)
    monkeypatch.setattr(theme, "theme_ansi", ((100, 120, 140),) * 16)
    assert cell("\033[44mx", shadow("▀"))[1] == (2, 94, 102, 110)


@pytest.mark.parametrize("pointer,side,cap,side_glyph,cap_glyph", [
    ((2, 1), (3, 5), (4, 3), "▄", "▀"),
    ((8, 1), (3, 6), (4, 6), "▄", "▀"),
    ((2, 8), (7, 5), (6, 3), "▀", "▄"),
    ((8, 8), (7, 6), (6, 6), "▀", "▄"),
])
def test_pointer_is_the_light_source_in_all_four_quadrants(
        pointer, side, cap, side_glyph, cap_glyph):
    floating = live.pointer_chip(["abc"], *pointer, 9, 8)
    grid = painted(live.frame_paint("", floating), cols=9, rows=8)
    assert grid[side[0] - 1][side[1] - 1][0] == side_glyph
    assert grid[cap[0] - 1][cap[1] - 1][0] == cap_glyph


@pytest.mark.parametrize("dx,dy", [(1, 1), (-1, 1), (1, -1), (-1, -1)])
def test_shadow_footprint_stays_inside_small_screens(dx, dy):
    floating = live.chip_at(["abc", "def"], 99, 99, 4, rows=3,
                            shadow_direction=(dx, dy))
    import re
    for row, col in re.findall(r"\033\[(\d+);(\d+)H", floating):
        assert 1 <= int(row) <= 3 and 1 <= int(col) <= 4
    grid = painted(live.frame_paint("", floating), cols=4, rows=3)
    assert sum(c[0] in "abcdef" for row in grid for c in row) == 6
