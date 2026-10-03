"""The theme can change under a live view.

_theme._apply swaps the palette and runs every registered rebuild, so
modules that derived colours at import — and modules that copied those
names out of them — all see the new theme.  The live loop learns of a
change from OSC replies parsed out of its own input stream.
"""

import colorsys
import os
import select
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from linecast.terminal import color as _color
from linecast.terminal import framebuffer as _framebuffer
from linecast.terminal import theme as _theme

from linecast.tides import view as tides

from linecast.sunshine import palette

from linecast.moon import view as moon
from linecast.moon import palette as moon_palette
from linecast.radar import basemap
from linecast.radar import render as _radar_render
from linecast.maps import style as _maps_style
from linecast.weather import alerts
from linecast.weather import view as _weather_view
from linecast.weather import style
from linecast.terminal.keys import read_key
from conftest import SRC


def _ansi(fg, bg):
    ansi = [(205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 205),
            (205, 0, 205), (0, 205, 205)]
    return tuple([bg] + ansi + [fg] + [(128, 128, 128)] + ansi + [fg])


LIGHT = ((20, 20, 24), (250, 250, 248), _ansi((20, 20, 24), (250, 250, 248)))
DARK = ((210, 210, 220), (18, 18, 24), _ansi((210, 210, 220), (18, 18, 24)))


@pytest.fixture
def restore_theme():
    saved = (_theme.theme_fg, _theme.theme_bg, _theme.theme_ansi,
             _theme.theme_available)
    yield
    _theme._apply(*saved[:3])
    _theme.theme_available = saved[3]


@pytest.mark.skipif(_theme.theme_legacy_mode, reason="legacy palette is fixed")
class TestApply:
    def test_bumps_generation_and_runs_hooks(self, restore_theme):
        gen = _theme.generation
        _theme._apply(*LIGHT)
        assert _theme.generation == gen + 1
        assert _theme.theme_bg == (250, 250, 248)
        assert _theme.is_light_theme()

    def test_import_time_palettes_follow(self, restore_theme):
        _theme._apply(*DARK)
        dark = (style.TEXT_RGB, palette.INFO_TEXT_RGB,
                tides.TEXT_RGB, moon_palette.MOON_SHADOW_RGB, basemap.SEA_FILL)
        _theme._apply(*LIGHT)
        light = (style.TEXT_RGB, palette.INFO_TEXT_RGB,
                 tides.TEXT_RGB, moon_palette.MOON_SHADOW_RGB, basemap.SEA_FILL)
        for d, lt in zip(dark, light):
            assert d != lt
        # text is ink on the new background, not the old one
        assert _theme.contrast_ratio(style.TEXT_RGB, (250, 250, 248)) >= 4.5
        assert _theme.contrast_ratio(tides.TEXT_RGB, (250, 250, 248)) >= 4.5
        # the ground follows the background; the inks keep the theme's hues
        assert _maps_style._light()
        assert _maps_style.ground_color() != _maps_style._GROUND_ANCHOR_DARK

    def test_themed_inks_follow_the_ansi_hues(self, restore_theme, monkeypatch):
        monkeypatch.setattr(_color, "_COLOR_MODE", "truecolor")
        _theme._apply(*DARK)
        canonical = _maps_style.PALETTE_DARK["water"]
        green = tuple((40, 160, 70) if 1 <= i <= 6 or 9 <= i <= 14 else c
                      for i, c in enumerate(DARK[2]))
        _theme._apply(DARK[0], DARK[1], green)
        assert _maps_style.PALETTE_DARK["water"] != canonical

    def test_land_cover_follows_the_ansi_hues(self, restore_theme, monkeypatch):
        from linecast.maps import paint
        monkeypatch.setattr(_color, "_COLOR_MODE", "truecolor")
        _theme._apply(*DARK)
        canonical = _maps_style.COVER_COLOR["wood"]
        green = tuple((40, 160, 70) if 1 <= i <= 6 or 9 <= i <= 14 else c
                      for i, c in enumerate(DARK[2]))
        _theme._apply(DARK[0], DARK[1], green)
        wood = _maps_style.COVER_COLOR["wood"]
        assert wood != canonical
        assert paint._COVER_RGB[_maps_style.COVER_ORDER.index("wood") + 1] == wood

    def test_track_imports_finds_the_copied_names(self):
        import types
        src = types.ModuleType("linecast._track_imports_probe")
        src.INK = (1, 2, 3)
        src.PAPER = (4, 5, 6)
        src.paint = lambda: None
        src.os = os
        sys.modules[src.__name__] = src
        ns = {"__name__": "probe", "INK": src.INK, "paint": src.paint, "os": os,
              "PAPER": (9, 9, 9), "LOCAL": (7, 7, 7)}
        try:
            n = len(_theme._reload_hooks)
            _theme.track_imports(ns, src.__name__)
            hook = _theme._reload_hooks.pop()
            assert len(_theme._reload_hooks) == n
            src.INK = (10, 20, 30)
            src.PAPER = (40, 50, 60)
            src.paint = lambda: 1
            hook()
        finally:
            del sys.modules[src.__name__]
        assert ns["INK"] == (10, 20, 30)         # copied at import: follows
        assert ns["paint"] is src.paint
        assert ns["PAPER"] == (9, 9, 9)          # the module's own: untouched
        assert ns["LOCAL"] == (7, 7, 7)
        assert ns["os"] is os

    def test_copied_names_are_re_imported(self, restore_theme):
        _theme._apply(*LIGHT)
        assert _color.BG_PRIMARY == (250, 250, 248)
        assert _radar_render.BG_PRIMARY == (250, 250, 248)
        assert _framebuffer.Framebuffer(2, 1).bg == (250, 250, 248)
        assert _weather_view.TEXT == style.TEXT
        assert _weather_view.TOOLTIP_BG_RGB == style.TOOLTIP_BG_RGB
        assert moon_palette.INFO_TEXT_RGB == palette.INFO_TEXT_RGB
        assert moon.PANEL_TEXT_RGB == moon_palette.PANEL_TEXT_RGB
        assert _radar_render.SEA_FILL == basemap.SEA_FILL


class TestLightThemeInk:
    """What a light theme must not turn dark.

    An ink contrast-checked against the page comes out dark on a light
    theme, which is right for text on the page and wrong for a sun, or
    for a number knocked out of a bar the page never touches.
    """

    def test_the_sun_keeps_its_colours_on_every_theme(self, restore_theme):
        _theme._apply(*DARK)
        drawn = (palette.SUN_DOT_RGB, palette.SUN_GLOW_RGB)
        _theme._apply(*LIGHT)
        assert (palette.SUN_DOT_RGB, palette.SUN_GLOW_RGB) == drawn
        for ink in drawn:
            assert _theme.luminance(ink) > 0.5

    def test_a_bar_label_takes_its_ink_from_the_bar(self, restore_theme):
        _theme._apply(*LIGHT)
        cold = style.TEMP_COLORS[0][1]   # the coldest fill: on a light page, a navy
        ink = style._knockout_ink(cold)
        assert _theme.luminance(ink) > 0.5        # white, not the page's ink
        assert _theme.contrast_ratio(ink, cold) >= 4.5
        pale = style._knockout_ink((250, 204, 21))
        assert _theme.luminance(pale) < 0.5

    def test_alert_modal_background_follows_the_theme(self, restore_theme, monkeypatch):
        monkeypatch.setattr(_color, "_COLOR_MODE", "truecolor")
        _theme._apply(*DARK)
        old_bg = alerts.bg(*alerts.MODAL_BG_RGB)
        _theme._apply(*LIGHT)
        new_bg = alerts.bg(*alerts.MODAL_BG_RGB)
        modal, _max_scroll = alerts.build_alert_modal(
            {"event": "Fog", "description": "Visibility is low."}, 80, 24)
        assert new_bg in modal
        assert old_bg not in modal
        assert _theme.contrast_ratio(
            alerts.TEXT_RGB, alerts.MODAL_BG_RGB) >= 4.5


def _copied_names():
    """Every name a linecast module took by value from another with a
    module-level `from linecast... import`, as (module, local name,
    source module, source name); functions, classes and modules left out,
    since a theme change never replaces those."""
    import ast
    import importlib
    import pkgutil
    import types

    import linecast
    copies = []
    for info in pkgutil.walk_packages(linecast.__path__, "linecast."):
        if ".locales." in info.name or info.name.endswith("__main__"):
            continue
        module = importlib.import_module(info.name)
        with open(module.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            if not (isinstance(node, ast.ImportFrom) and node.level == 0
                    and (node.module or "").startswith("linecast")):
                continue
            source = importlib.import_module(node.module)
            for alias in node.names:
                value = getattr(source, alias.name, None)
                if value is None or callable(value) or isinstance(value, types.ModuleType):
                    continue
                copies.append((module, alias.asname or alias.name, source, alias.name))
    return copies


@pytest.mark.skipif(_theme.theme_legacy_mode, reason="legacy palette is fixed")
def test_no_module_keeps_a_copy_of_the_old_theme():
    # A name taken with `from x import INK` is a copy: when the theme
    # changes, x rebuilds INK and the copy keeps the old colour unless
    # the module asked to follow it (_theme.track_imports at its tail).
    # In truecolor, so that an escape string is more than "" to compare;
    # the theme and the mode are put back by hand, in that order, since
    # the palettes rebuilt in truecolor must be rebuilt again without it.
    copies = _copied_names()
    saved = (_theme.theme_fg, _theme.theme_bg, _theme.theme_ansi, _theme.theme_available)
    mode, _color._COLOR_MODE = _color._COLOR_MODE, "truecolor"
    try:
        for theme in (LIGHT, DARK):
            _theme._apply(*theme)
            stale = [f"{module.__name__}.{local} (from {source.__name__})"
                     for module, local, source, name in copies
                     if getattr(module, local) != getattr(source, name)]
            assert not stale, "not re-imported after a theme change: " + ", ".join(stale)
    finally:
        _color._COLOR_MODE = mode
        _theme._apply(*saved[:3])
        _theme.theme_available = saved[3]


@pytest.mark.skipif(_theme.theme_legacy_mode, reason="legacy palette is fixed")
class TestExtremeColors:
    """Below freezing the temperature colors deepen from the theme's
    blue and then pale toward ice, staying blue; past red they turn
    crimson and deepen toward a maroon."""

    ADWAITA_DARK = ((255, 255, 255), (28, 28, 31), (
        (36, 31, 49), (192, 28, 40), (46, 194, 126), (245, 194, 17),
        (30, 120, 228), (152, 65, 187), (10, 185, 220), (192, 191, 188),
        (94, 92, 100), (237, 51, 59), (87, 227, 137), (248, 228, 92),
        (81, 161, 255), (192, 97, 203), (79, 210, 253), (246, 245, 244)))

    # Gruvbox Dark's two blues are teals.
    GRUVBOX_DARK = ((235, 219, 178), (40, 40, 40), (
        (40, 40, 40), (204, 36, 29), (152, 151, 26), (215, 153, 33),
        (69, 133, 136), (177, 98, 134), (104, 157, 106), (168, 153, 132),
        (146, 131, 116), (251, 73, 52), (184, 187, 38), (250, 189, 47),
        (131, 165, 152), (211, 134, 155), (142, 192, 124), (235, 219, 178)))

    @staticmethod
    def _hue(rgb):
        return colorsys.rgb_to_hls(*(c / 255 for c in rgb))[0] * 360

    def test_colder_deepens_and_then_pales_to_ice(self, restore_theme):
        _theme._apply(*self.ADWAITA_DARK)
        rt = SimpleNamespace(celsius=False)
        freezing, deep, cold, ice = (style._temp_color(t, rt) for t in (32, 15, -10, -40))
        assert _theme.luminance(deep) < _theme.luminance(freezing)
        assert _theme.luminance(deep) < _theme.luminance(cold) < _theme.luminance(ice)
        for color in (deep, cold, ice):
            assert 190 <= self._hue(color) <= 240

    def test_the_scale_runs_to_forty_below(self, restore_theme):
        _theme._apply(*self.ADWAITA_DARK)
        rt = SimpleNamespace(celsius=False)
        assert style._temp_color(-40, rt) != style._temp_color(-20, rt)
        assert style._temp_color(-60, rt) == style._temp_color(-40, rt)

    def test_a_teal_blue_turns_toward_sky_blue_for_the_ice(self, restore_theme):
        _theme._apply(*self.GRUVBOX_DARK)
        rt = SimpleNamespace(celsius=False)
        assert self._hue(_theme.theme_ansi[4]) < 185
        assert 190 <= self._hue(style._temp_color(-40, rt)) <= 235

    def test_hotter_turns_crimson_and_deepens(self, restore_theme):
        _theme._apply(*self.ADWAITA_DARK)
        rt = SimpleNamespace(celsius=False)
        red, crimson, maroon = (style._temp_color(t, rt) for t in (95, 105, 115))
        assert 332 <= self._hue(crimson) <= 348
        assert _theme.luminance(maroon) < _theme.luminance(crimson) < _theme.luminance(red)
        assert _theme.contrast_ratio(maroon, _theme.theme_bg) >= 2.1
        assert style._temp_color(130, rt) == maroon

    def test_on_a_light_theme_the_ice_darkens_instead(self, restore_theme):
        _theme._apply(*LIGHT)
        rt = SimpleNamespace(celsius=False)
        deep, ice = style._temp_color(15, rt), style._temp_color(-40, rt)
        assert _theme.luminance(ice) < _theme.luminance(deep)
        crimson, maroon = style._temp_color(105, rt), style._temp_color(115, rt)
        assert _theme.luminance(maroon) < _theme.luminance(crimson)


class TestHueHelpers:
    def test_clamp_hue_turns_only_a_hue_outside_the_window(self):
        teal = (69, 133, 136)
        turned = _theme.clamp_hue(teal, 215, 20)
        assert round(_theme.hue_distance(turned, 215)) == 20
        h1, l1, s1 = colorsys.rgb_to_hls(*(c / 255 for c in teal))
        h2, l2, s2 = colorsys.rgb_to_hls(*(c / 255 for c in turned))
        assert abs(l1 - l2) < 0.01 and abs(s1 - s2) < 0.02
        sky = (30, 120, 228)
        assert _theme.clamp_hue(sky, 215, 20) == sky

    def test_hue_distance_goes_the_short_way_round(self):
        red = (220, 60, 50)
        assert _theme.hue_distance(red, 340) < 30
        assert _theme.hue_distance(red, 340) == pytest.approx(
            _theme.hue_distance(red, 340 - 360))


@pytest.fixture
def pipe():
    r, w = os.pipe()
    yield r, w
    for fd in (r, w):
        try:
            os.close(fd)
        except OSError:
            pass


def _replies(fg, bg, ansi):
    def hexpair(c):
        return "rgb:" + "/".join(f"{v:02x}{v:02x}" for v in c)
    out = [f"10;{hexpair(fg)}", f"11;{hexpair(bg)}"]
    out += [f"4;{i};{hexpair(c)}" for i, c in enumerate(ansi)]
    return out


@pytest.mark.skipif(_theme.theme_legacy_mode, reason="legacy palette is fixed")
class TestProbe:
    def test_query_goes_out_and_replies_complete_it(self, pipe, restore_theme):
        _theme._apply(*DARK)
        r, w = pipe
        assert _theme.request_probe(w)
        assert os.read(r, 4096).startswith(b"\x1b]10;?\x07\x1b]11;?\x07\x1b]4;0;?\x07")
        assert _theme.probe_pending()
        gen = _theme.generation
        replies = _replies(*LIGHT)
        for body in replies[:-1]:
            assert _theme.ingest_osc(body.encode()) is False
        assert _theme.ingest_osc(replies[-1].encode()) is True
        assert _theme.generation == gen + 1
        assert _theme.theme_bg == (250, 250, 248)
        assert not _theme.probe_pending()

    def test_same_answer_is_not_a_change(self, pipe, restore_theme):
        _theme._apply(*DARK)
        _theme.request_probe(pipe[1])
        gen = _theme.generation
        for body in _replies(*DARK):
            assert _theme.ingest_osc(body.encode()) is False
        assert _theme.generation == gen

    def test_replies_without_a_probe_are_ignored(self, restore_theme):
        _theme._probe = None
        assert _theme.ingest_osc(b"11;rgb:ffff/ffff/ffff") is False

    def test_read_key_swallows_osc_and_reports_a_change(self, pipe, restore_theme):
        _theme._apply(*DARK)
        r, w = pipe
        qr, qw = os.pipe()
        try:
            _theme.request_probe(qw)
        finally:
            os.close(qr)
            os.close(qw)
        replies = _replies(*LIGHT)
        for body in replies[:-1]:
            os.write(w, b"\x1b]" + body.encode() + b"\x07")
            assert read_key(r) is None
        # ST-terminated, the other legal ending
        os.write(w, b"\x1b]" + replies[-1].encode() + b"\x1b\\")
        assert read_key(r) == "theme"
        # and the key after it is still a key
        os.write(w, b"q")
        assert read_key(r) == "quit"


CHILD = textwrap.dedent("""
    import sys
    from linecast.terminal import theme as _theme
    from linecast.terminal.live import live_loop
    def render(offset_minutes=0, **kw):
        sys.stderr.write("BG %r\\n" % (_theme.theme_bg,))
        sys.stderr.flush()
        return "."
    live_loop(render, interval=5)
""")


def _reply_bytes(fg, bg, ansi):
    return b"".join(b"\x1b]" + r.encode() + b"\x07" for r in _replies(fg, bg, ansi))


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs a pty")
def test_live_loop_re_inks_when_the_terminal_changes(tmp_path):
    """The real live loop on a pty: we play the terminal, answer its
    palette queries, then answer differently and expect a repaint in
    the new colours."""
    import time
    master, slave = os.openpty()
    env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor",
               LINECAST_THEME="auto", LINECAST_THEME_TIMEOUT_MS="1000",
               LINECAST_THEME_POLL="0.2", LINECAST_THEME_WATCH="",
               PYTHONPATH=SRC)
    env.pop("NO_COLOR", None)
    proc = subprocess.Popen([sys.executable, "-c", CHILD], stdin=slave,
                            stdout=slave, stderr=subprocess.PIPE, env=env,
                            close_fds=True)
    os.close(slave)
    os.set_blocking(proc.stderr.fileno(), False)
    palette = DARK
    seen, errbuf, outbuf = [], b"", b""
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master, proc.stderr], [], [], 0.1)
            if master in ready:
                try:
                    outbuf += os.read(master, 65536)
                except OSError:
                    break
                while b"\x1b]4;15;?\x07" in outbuf:  # the tail of one query
                    outbuf = outbuf.split(b"\x1b]4;15;?\x07", 1)[1]
                    os.write(master, _reply_bytes(*palette))
            if proc.stderr in ready:
                chunk = proc.stderr.read()
                if chunk:
                    errbuf += chunk
                    while b"\n" in errbuf:
                        line, errbuf = errbuf.split(b"\n", 1)
                        if line.startswith(b"BG "):
                            seen.append(line.decode())
            if seen and palette is DARK and seen[-1] == "BG (18, 18, 24)":
                palette = LIGHT   # the user switches themes
            if "BG (250, 250, 248)" in seen:
                break
        os.write(master, b"q")
        # Keep draining the pty until the child is gone: its teardown
        # restores the tty with TCSADRAIN, which on macOS waits for the
        # master to read every pending byte before it returns.
        deadline = time.monotonic() + 5
        while proc.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.05)[0]:
                try:
                    os.read(master, 65536)
                except OSError:
                    # EIO: the child closed its side of the pty, which
                    # happens a beat before it can be reaped
                    break
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
        os.close(master)
    assert "BG (18, 18, 24)" in seen, (seen, errbuf)
    assert "BG (250, 250, 248)" in seen, (seen, errbuf)


@pytest.mark.parametrize("background,foreground", [
    ((28, 28, 38), (180, 185, 210)),
    ((250, 250, 248), (35, 35, 40)),
])
def test_chip_text_contrast(background, foreground, monkeypatch):
    monkeypatch.setattr(_theme, "theme_bg", background)
    monkeypatch.setattr(_theme, "theme_fg", foreground)
    surface, text, secondary = _theme.chip_inks()
    assert _theme.contrast_ratio(text, surface) >= 4.5
    assert _theme.contrast_ratio(secondary, surface) >= 4.5
