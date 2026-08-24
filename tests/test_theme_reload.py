"""The theme can change under a live view.

_theme._apply swaps the palette and runs every registered rebuild, so
modules that derived colours at import — and modules that copied those
names out of them — all see the new theme.  The live loop learns of a
change from OSC replies parsed out of its own input stream.
"""

import os
import select
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import (  # noqa: E402
    _color, _framebuffer, _maps_style, _radar_basemap, _radar_render,
    _theme, _weather_render, _weather_style, moon, sunshine, tides,
)
from linecast._live import _read_key  # noqa: E402


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
        dark = (_weather_style.TEXT_RGB, sunshine.INFO_TEXT_RGB,
                tides.TEXT_RGB, moon.MOON_SHADOW_RGB, _radar_basemap.SEA_FILL)
        _theme._apply(*LIGHT)
        light = (_weather_style.TEXT_RGB, sunshine.INFO_TEXT_RGB,
                 tides.TEXT_RGB, moon.MOON_SHADOW_RGB, _radar_basemap.SEA_FILL)
        for d, l in zip(dark, light):
            assert d != l
        # text is ink on the new background, not the old one
        assert _theme.contrast_ratio(_weather_style.TEXT_RGB, (250, 250, 248)) >= 4.5
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
        assert _weather_render.TEXT == _weather_style.TEXT
        assert _weather_render.TOOLTIP_BG_RGB == _weather_style.TOOLTIP_BG_RGB
        assert moon.INFO_TEXT_RGB == sunshine.INFO_TEXT_RGB
        assert _radar_render.SEA_FILL == _radar_basemap.SEA_FILL


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
    def test_query_goes_out_and_replies_complete_it(self, pipe, restore_theme, monkeypatch):
        _theme._apply(*DARK)
        monkeypatch.setattr(_theme, "theme_available", True)
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

    def test_same_answer_is_not_a_change(self, pipe, restore_theme, monkeypatch):
        _theme._apply(*DARK)
        monkeypatch.setattr(_theme, "theme_available", True)
        _theme.request_probe(pipe[1])
        gen = _theme.generation
        for body in _replies(*DARK):
            assert _theme.ingest_osc(body.encode()) is False
        assert _theme.generation == gen

    def test_replies_without_a_probe_are_ignored(self, restore_theme):
        _theme._probe = None
        assert _theme.ingest_osc(b"11;rgb:ffff/ffff/ffff") is False

    def test_read_key_swallows_osc_and_reports_a_change(self, pipe, restore_theme, monkeypatch):
        _theme._apply(*DARK)
        monkeypatch.setattr(_theme, "theme_available", True)
        r, w = pipe
        qr, qw = os.pipe()
        try:
            _theme.request_probe(qw)
        finally:
            os.close(qr); os.close(qw)
        replies = _replies(*LIGHT)
        for body in replies[:-1]:
            os.write(w, b"\x1b]" + body.encode() + b"\x07")
            assert _read_key(r) is None
        # ST-terminated, the other legal ending
        os.write(w, b"\x1b]" + replies[-1].encode() + b"\x1b\\")
        assert _read_key(r) == "theme"
        # and the key after it is still a key
        os.write(w, b"q")
        assert _read_key(r) == "quit"


CHILD = textwrap.dedent("""
    import sys
    from linecast import _theme
    from linecast._live import live_loop
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
               PYTHONPATH=_src)
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
