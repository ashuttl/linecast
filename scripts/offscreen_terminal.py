#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""A terminal with no window, for the README's frames and recordings.

termshot photographs a real terminal on a borrowed Hyprland output.  This
runs the command in a pseudo-terminal instead and keeps the screen itself:
it answers the questions linecast asks a terminal (its colours, where the
cursor is, its name), keeps the cells in a small emulator that knows what
linecast writes and little else, and draws them the way foot does, with
braille and the block elements drawn rather than taken from the font.  It
needs no display, so it runs the same way anywhere, and it can type,
click, drag, and change the theme on a schedule while it records.

Pillow draws the glyphs.  It is the one thing here outside the standard
library, and the header above names it, so uv runs the script directly:

    scripts/offscreen_terminal.py -s 110x34 -o weather.png linecast weather

The pieces, top to bottom: Theme (an Omarchy theme's colours and
wallpaper), Screen (the emulator), Session (a command in a pty, driven on
a timeline), Typeface and render_cells (cells to pixels), and window_image
and desktop_image (the Omarchy frame around them).
"""

from __future__ import annotations

import codecs
import fcntl
import functools
import math
import os
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# The emulator measures text with linecast's own rules, so the grid it
# keeps and the layout linecast computed always agree.
from linecast.terminal.textwidth import char_width  # noqa: E402

# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

RGB = tuple[int, int, int]

THEME_DIRS = (Path.home() / ".config/omarchy/themes",
              Path.home() / ".local/share/omarchy/themes",
              Path("/usr/share/omarchy/themes"))


def _hex(value: str) -> RGB:
    value = value.strip().lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


@dataclass(frozen=True)
class Theme:
    """The colours a terminal answers with, and the desktop around it.

    ansi follows Omarchy's foot template: regular0 is the background,
    regular7 the foreground, bright0 the muted grey."""
    name: str
    fg: RGB
    bg: RGB
    ansi: tuple[RGB, ...]
    accent: RGB
    inactive_border: RGB = (0x59, 0x59, 0x59)
    wallpaper: Path | None = None

    @classmethod
    def omarchy(cls, name: str) -> Theme:
        for base in THEME_DIRS:
            path = base / name / "colors.toml"
            if path.exists():
                break
        else:
            raise SystemExit(f"no Omarchy theme called {name!r}")
        c = tomllib.loads(path.read_text())

        def pick(*keys):
            for key in keys:
                if key in c:
                    return _hex(c[key])
            raise KeyError(keys[0])

        ansi = (pick("background"), pick("red"), pick("green"), pick("yellow"),
                pick("blue"), pick("purple", "magenta"), pick("cyan"),
                pick("foreground"),
                pick("muted", "bright_black"), pick("bright_red"),
                pick("bright_green"), pick("bright_yellow"), pick("bright_blue"),
                pick("bright_magenta", "bright_purple"), pick("bright_cyan"),
                pick("bright_foreground", "bright_white"))
        backgrounds = sorted(p for p in (path.parent / "backgrounds").glob("*")
                             if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
        return cls(name=name, fg=pick("foreground"), bg=pick("background"),
                   ansi=ansi, accent=pick("accent", "blue"),
                   wallpaper=backgrounds[0] if backgrounds else None)

    @classmethod
    def current(cls) -> Theme:
        marker = Path.home() / ".local/state/omarchy/current/theme.name"
        try:
            return cls.omarchy(marker.read_text().strip())
        except (OSError, SystemExit):
            return cls.omarchy("tokyo-night")

    def color(self, index: int) -> RGB:
        if index < 16:
            return self.ansi[index]
        if index < 232:
            index -= 16
            steps = (0, 95, 135, 175, 215, 255)
            return steps[index // 36], steps[index // 6 % 6], steps[index % 6]
        level = 8 + (index - 232) * 10
        return level, level, level


def _osc_rgb(color: RGB) -> str:
    return "rgb:" + "/".join(f"{c:02x}{c:02x}" for c in color)


# ---------------------------------------------------------------------------
# The emulator
# ---------------------------------------------------------------------------

# A cell is (text, pen, width): width 1 or 2 for a cell that starts a
# glyph, 0 for the right half of a wide one.  A pen is (fg, bg, attrs),
# fg and bg each None for the default, an int palette index, or an RGB
# tuple.  Cells and pens are tuples, so a snapshot is a copy of the rows.
BOLD, DIM, ITALIC, UNDERLINE, STRIKE, REVERSE, INVISIBLE = (1 << i for i in range(7))
_SGR_ON = {1: BOLD, 2: DIM, 3: ITALIC, 4: UNDERLINE, 7: REVERSE, 8: INVISIBLE, 9: STRIKE}
_SGR_OFF = {22: BOLD | DIM, 23: ITALIC, 24: UNDERLINE, 27: REVERSE, 28: INVISIBLE,
            29: STRIKE}
PLAIN = (None, None, 0)
_VS16 = "️"


@dataclass
class Frame:
    """The screen at one moment."""
    t: float
    rows: list[list[tuple]]
    theme: Theme


class Screen:
    """Just enough of xterm for what linecast writes.

    *reply* is called with the bytes a terminal would send back: colour
    reports, cursor reports, its name.  *on_frame* is called after each
    synchronized update (mode 2026) ends, which is when linecast has
    finished a frame."""

    def __init__(self, cols, rows, theme, reply=lambda b: None, on_frame=None):
        self.cols, self.rows = cols, rows
        self.theme = theme
        self.reply = reply
        self.on_frame = on_frame
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._state = "ground"
        self._seq = []
        self.main = self._blank_grid()
        self.alt = self._blank_grid()
        self.grid = self.main
        self.x = self.y = 0
        self.pen = PLAIN
        self.wrap_pending = False
        self.autowrap = True
        self.top, self.bottom = 0, rows - 1
        self.saved = (0, 0, PLAIN)
        self.cursor_visible = True
        self.modes: set[int] = set()

    def _blank_grid(self):
        blank = (" ", PLAIN, 1)
        return [[blank] * self.cols for _ in range(self.rows)]

    def _blank(self):
        # Erasing paints with the current background, as xterm does.
        return (" ", (None, self.pen[1], 0) if self.pen[1] is not None else PLAIN, 1)

    def snapshot(self) -> list[list[tuple]]:
        return [row[:] for row in self.grid]

    # --- input ------------------------------------------------------------

    _CONTROL = re.compile(r"[\x00-\x1f\x7f\x9b]")

    def feed(self, data: bytes):
        text = self._decoder.decode(data)
        i, n = 0, len(text)
        while i < n:
            if self._state == "ground":
                m = self._CONTROL.search(text, i)
                end = m.start() if m else n
                if end > i:
                    self._print(text[i:end])
                    i = end
                    continue
                ch = text[i]
                i += 1
                self._control(ch)
            else:
                ch = text[i]
                i += 1
                self._escape_char(ch)

    def _control(self, ch):
        if ch == "\x1b":
            self._state, self._seq = "esc", []
        elif ch == "\r":
            self.x, self.wrap_pending = 0, False
        elif ch in "\n\x0b\x0c":
            self._linefeed()
        elif ch == "\b":
            self.x, self.wrap_pending = max(0, self.x - 1), False
        elif ch == "\t":
            self.x = min(self.cols - 1, (self.x // 8 + 1) * 8)
        elif ch == "\x9b":
            self._state, self._seq = "csi", []

    def _escape_char(self, ch):
        state = self._state
        if state == "esc":
            if ch == "[":
                self._state, self._seq = "csi", []
            elif ch == "]":
                self._state, self._seq = "osc", []
            elif ch in "P_^X":
                self._state, self._seq = "string", []
            elif ch in "()*+-./#%":
                self._state = "charset"
            else:
                self._state = "ground"
                self._esc(ch)
        elif state == "charset":
            self._state = "ground"
        elif state == "csi":
            if "\x40" <= ch <= "\x7e":
                self._state = "ground"
                self._csi("".join(self._seq), ch)
            elif ch == "\x1b":           # a broken sequence; start again
                self._state, self._seq = "esc", []
            else:
                self._seq.append(ch)
        elif state in ("osc", "string"):
            if ch == "\x07":
                self._end_string("\x07")
            elif ch == "\x1b":
                self._state = state + "_esc"
            else:
                self._seq.append(ch)
        elif state in ("osc_esc", "string_esc"):
            if ch == "\\":
                self._state = state[:-4]
                self._end_string("\x1b\\")
            else:
                self._state = "esc"
                self._escape_char(ch)

    def _end_string(self, terminator):
        kind, body = self._state, "".join(self._seq)
        self._state = "ground"
        if kind == "osc":
            self._osc(body, terminator)

    # --- printing ---------------------------------------------------------

    def _print(self, run):
        cols = self.cols
        for ch in run:
            w = 1 if " " <= ch < "\x7f" else char_width(ch)
            if w == 0:
                self._combine(ch)
                continue
            if self.wrap_pending:
                self.wrap_pending = False
                if self.autowrap:
                    self.x = 0
                    self._linefeed()
            if w == 2 and self.x == cols - 1:
                if not self.autowrap:
                    continue
                self._put(self.y, self.x, self._blank())
                self.x = 0
                self._linefeed()
            self._put(self.y, self.x, (ch, self.pen, w))
            if w == 2:
                self._put(self.y, self.x + 1, ("", self.pen, 0))
            self.x += w
            if self.x >= cols:
                self.x = cols - 1
                self.wrap_pending = True

    def _put(self, y, x, cell):
        row = self.grid[y]
        old = row[x]
        if old[2] == 0 and x > 0 and row[x - 1][2] == 2:
            row[x - 1] = (" ", row[x - 1][1], 1)
        elif old[2] == 2 and x + 1 < self.cols and cell[2] != 2:
            row[x + 1] = (" ", row[x + 1][1], 1)
        row[x] = cell

    def _combine(self, ch):
        x = self.x if self.wrap_pending else self.x - 1
        if x < 0:
            return
        row = self.grid[self.y]
        if row[x][2] == 0 and x > 0:
            x -= 1
        text, pen, w = row[x]
        row[x] = (text + ch, pen, w)
        # An emoji selector widens a one-cell base, as char_width has it.
        if ch == _VS16 and w == 1 and char_width(text[:1], _VS16) == 2:
            if x + 1 < self.cols:
                row[x] = (text + ch, pen, 2)
                row[x + 1] = ("", pen, 0)
                if not self.wrap_pending:
                    self.x = x + 2
                    if self.x >= self.cols:
                        self.x, self.wrap_pending = self.cols - 1, True

    def _linefeed(self):
        self.wrap_pending = False
        if self.y == self.bottom:
            self._scroll_up(1)
        elif self.y < self.rows - 1:
            self.y += 1

    def _scroll_up(self, n):
        region = self.grid[self.top:self.bottom + 1]
        n = min(n, len(region))
        blank = self._blank()
        del region[:n]
        region.extend([blank] * self.cols for _ in range(n))
        self.grid[self.top:self.bottom + 1] = region

    def _scroll_down(self, n):
        region = self.grid[self.top:self.bottom + 1]
        n = min(n, len(region))
        blank = self._blank()
        del region[len(region) - n:]
        region[0:0] = [[blank] * self.cols for _ in range(n)]
        self.grid[self.top:self.bottom + 1] = region

    # --- escapes ----------------------------------------------------------

    def _esc(self, ch):
        if ch == "7":
            self.saved = (self.x, self.y, self.pen)
        elif ch == "8":
            self.x, self.y, self.pen = self.saved
            self.wrap_pending = False
        elif ch == "D":
            self._linefeed()
        elif ch == "E":
            self.x = 0
            self._linefeed()
        elif ch == "M":
            if self.y == self.top:
                self._scroll_down(1)
            elif self.y > 0:
                self.y -= 1
        elif ch == "c":
            self.__init__(self.cols, self.rows, self.theme, self.reply, self.on_frame)

    def _csi(self, body, final):
        private = body[:1] if body[:1] in "?<>=" else ""
        params_text = body[len(private):].rstrip(" !\"#$%&'*+,-./")
        raw = params_text.replace(":", ";").split(";") if params_text else []
        params = [int(p) if p.isdigit() else 0 for p in raw]

        def arg(i=0, default=1):
            return params[i] if len(params) > i and params[i] else default

        if final == "m" and not private:
            self._sgr(params or [0])
        elif final in "Hf":
            self.y = min(self.rows - 1, arg(0) - 1)
            self.x = min(self.cols - 1, arg(1) - 1)
            self.wrap_pending = False
        elif final == "A":
            self.y = max(self.top if self.y >= self.top else 0, self.y - arg())
            self.wrap_pending = False
        elif final in "Be":
            self.y = min(self.bottom if self.y <= self.bottom else self.rows - 1,
                         self.y + arg())
            self.wrap_pending = False
        elif final in "Ca":
            self.x = min(self.cols - 1, self.x + arg())
            self.wrap_pending = False
        elif final == "D":
            self.x = max(0, self.x - arg())
            self.wrap_pending = False
        elif final == "E":
            self.y, self.x = min(self.rows - 1, self.y + arg()), 0
        elif final == "F":
            self.y, self.x = max(0, self.y - arg()), 0
        elif final in "G`":
            self.x = min(self.cols - 1, arg() - 1)
            self.wrap_pending = False
        elif final == "d":
            self.y = min(self.rows - 1, arg() - 1)
            self.wrap_pending = False
        elif final == "J" and not private:
            self._erase_display(arg(0, 0))
        elif final == "K" and not private:
            self._erase_line(arg(0, 0))
        elif final == "X":
            row = self.grid[self.y]
            for x in range(self.x, min(self.cols, self.x + arg())):
                row[x] = self._blank()
        elif final == "P":
            row = self.grid[self.y]
            n = min(arg(), self.cols - self.x)
            del row[self.x:self.x + n]
            row.extend([self._blank()] * n)
        elif final == "@":
            row = self.grid[self.y]
            n = min(arg(), self.cols - self.x)
            row[self.x:self.x] = [self._blank()] * n
            del row[self.cols:]
        elif final == "L":
            if self.top <= self.y <= self.bottom:
                saved_top, self.top = self.top, self.y
                self._scroll_down(arg())
                self.top = saved_top
        elif final == "M" and not private:
            if self.top <= self.y <= self.bottom:
                saved_top, self.top = self.top, self.y
                self._scroll_up(arg())
                self.top = saved_top
        elif final == "S" and not private:
            self._scroll_up(arg())
        elif final == "T" and not private:
            self._scroll_down(arg())
        elif final == "r" and not private:
            top, bottom = arg(0) - 1, arg(1, self.rows) - 1
            if top < bottom:
                self.top, self.bottom = top, min(bottom, self.rows - 1)
                self.x = self.y = 0
        elif final == "s" and not private:
            self.saved = (self.x, self.y, self.pen)
        elif final == "u" and not private:
            self.x, self.y, self.pen = self.saved
        elif final in "hl":
            on = final == "h"
            for p in params:
                self._mode(private, p, on)
        elif final == "n" and not private and arg(0, 0) == 6:
            self.reply(f"\x1b[{self.y + 1};{self.x + 1}R".encode())
        elif final == "n" and not private and arg(0, 0) == 5:
            self.reply(b"\x1b[0n")
        elif final == "q" and private == ">":
            self.reply(b"\x1bP>|foot(1.28.0)\x1b\\")
        elif final == "c" and not private:
            self.reply(b"\x1b[?62;4;22;28c")

    def _mode(self, private, p, on):
        if private == "?":
            if on:
                self.modes.add(p)
            else:
                self.modes.discard(p)
            if p == 25:
                self.cursor_visible = on
            elif p == 7:
                self.autowrap = on
            elif p in (47, 1047, 1049):
                if on and self.grid is self.main:
                    if p == 1049:
                        self.saved = (self.x, self.y, self.pen)
                    self.alt = self._blank_grid()
                    self.grid = self.alt
                elif not on and self.grid is self.alt:
                    self.grid = self.main
                    if p == 1049:
                        self.x, self.y, self.pen = self.saved
            elif p == 2026 and not on and self.on_frame:
                self.on_frame()

    def _erase_display(self, how):
        if how == 0:
            self._erase_line(0)
            for y in range(self.y + 1, self.rows):
                self.grid[y] = [self._blank()] * self.cols
        elif how == 1:
            self._erase_line(1)
            for y in range(0, self.y):
                self.grid[y] = [self._blank()] * self.cols
        elif how in (2, 3):
            for y in range(self.rows):
                self.grid[y] = [self._blank()] * self.cols

    def _erase_line(self, how):
        row = self.grid[self.y]
        span = {0: range(self.x, self.cols), 1: range(0, self.x + 1),
                2: range(self.cols)}.get(how, ())
        blank = self._blank()
        for x in span:
            row[x] = blank

    def _sgr(self, params):
        fg, bg, attrs = self.pen
        i = 0
        while i < len(params):
            p = params[i]
            i += 1
            if p == 0:
                fg, bg, attrs = PLAIN
            elif p in _SGR_ON:
                attrs |= _SGR_ON[p]
            elif p in _SGR_OFF:
                attrs &= ~_SGR_OFF[p]
            elif 30 <= p <= 37:
                fg = p - 30
            elif 40 <= p <= 47:
                bg = p - 40
            elif 90 <= p <= 97:
                fg = p - 90 + 8
            elif 100 <= p <= 107:
                bg = p - 100 + 8
            elif p == 39:
                fg = None
            elif p == 49:
                bg = None
            elif p in (38, 48, 58):
                color = None
                if i < len(params) and params[i] == 5 and i + 1 < len(params):
                    color, i = params[i + 1], i + 2
                elif i < len(params) and params[i] == 2:     # 38;2;r;g;b
                    rgb = params[i + 1:i + 4]
                    if len(rgb) == 3:
                        color = tuple(min(255, c) for c in rgb)
                    i += 4
                if p == 38:
                    fg = color
                elif p == 48:
                    bg = color
        self.pen = (fg, bg, attrs)

    def _osc(self, body, terminator):
        ps, _, rest = body.partition(";")
        t = self.theme
        if ps in ("10", "11") and rest == "?":
            color = t.fg if ps == "10" else t.bg
            self.reply(f"\x1b]{ps};{_osc_rgb(color)}{terminator}".encode())
        elif ps == "4":
            parts = rest.split(";")
            for index, spec in zip(parts[0::2], parts[1::2]):
                if spec == "?" and index.isdigit() and int(index) < 256:
                    color = t.color(int(index))
                    self.reply(f"\x1b]4;{index};{_osc_rgb(color)}{terminator}".encode())


# ---------------------------------------------------------------------------
# A command in a pty
# ---------------------------------------------------------------------------

# The home a capture's config gives linecast.  Units and the clock
# default to the reader's own country, which with no saved place linecast
# guesses from the IP address; a fixed one keeps the frames the same on
# any machine.  Every command names its own --location.
CAPTURE_HOME = {"lat": 43.677, "lng": -70.3712, "label": "Westbrook, Maine",
                "country": "US"}


@functools.lru_cache(maxsize=1)
def _capture_config_dir() -> str:
    import atexit
    import json
    import shutil
    path = tempfile.mkdtemp(prefix="linecast-offscreen-config-")
    Path(path, "config.json").write_text(json.dumps({"location": CAPTURE_HOME}))
    atexit.register(shutil.rmtree, path, True)
    return path


@dataclass
class Session:
    """Runs *argv* in a pty of *cols* x *rows* cells and keeps its screen.

    *cell* is the cell size in pixels the pty reports, which linecast
    reads to keep its circles round.  Frames are recorded at every
    synchronized update once *record* is set."""
    argv: list[str]
    cols: int
    rows: int
    theme: Theme
    cell: tuple[int, int] = (18, 37)
    env: dict = field(default_factory=dict)
    record: bool = False

    def __post_init__(self):
        self.frames: list[Frame] = []
        self.finished = None     # the rows at the last synchronized update's end
        self.lock = threading.Lock()
        self.screen = Screen(self.cols, self.rows, self.theme,
                             reply=self._reply, on_frame=self._frame_done)
        self.watch = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / \
            f"linecast-offscreen-{os.getpid()}-{id(self)}.theme"
        self.watch.write_text(self.theme.name)

    def _env(self):
        """The environment of a fresh account on this machine: what foot
        sets, English, the Nerd Font icons the capture face has, and a
        config directory of its own, so the person running the capture
        never leaks their saved place, units, or clock into a frame.  The
        flags in each command decide the rest.  linecast runs from this tree
        (it needs nothing but the standard library), and it watches the
        theme marker's mtime to notice a theme change."""
        env = dict(os.environ)
        for key in ("TERM_PROGRAM", "KONSOLE_VERSION", "TMUX", "STY", "NO_COLOR",
                    "LC_ALL", "LC_MESSAGES", "LANGUAGE", "LINECAST_LANG",
                    "LINECAST_ICONS", "LINECAST_THEME", "LINECAST_CELL_ASPECT"):
            env.pop(key, None)
        env.update(TERM="xterm-256color", COLORTERM="truecolor", LANG="en_US.UTF-8",
                   LINECAST_CONFIG_DIR=_capture_config_dir(), LINECAST_ICONS="nerd",
                   LINECAST_THEME_WATCH=str(self.watch),
                   PYTHONPATH=os.pathsep.join(
                       filter(None, (str(REPO / "src"), env.get("PYTHONPATH")))))
        env.update(self.env)
        return env

    def start(self):
        master, slave = os.openpty()
        cw, ch = self.cell
        fcntl.ioctl(slave, termios.TIOCSWINSZ,
                    struct.pack("HHHH", self.rows, self.cols,
                                self.cols * cw, self.rows * ch))

        def controlling_tty():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        self.proc = subprocess.Popen(self.argv, stdin=slave, stdout=slave,
                                     stderr=slave, env=self._env(), cwd=REPO,
                                     preexec_fn=controlling_tty, close_fds=True)
        os.close(slave)
        self.fd = master
        self._alive = True
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        return self

    def _reply(self, data: bytes):
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def _frame_done(self):
        self.finished = self.screen.snapshot()
        if self.record:
            self.frames.append(Frame(time.monotonic(), self.finished, self.screen.theme))

    def _rows(self):
        """What a terminal would be showing: the last finished frame when
        the app draws in synchronized updates, as linecast's live views
        do, since the screen between two of them is half drawn; else the
        screen as it stands."""
        return self.finished if self.finished is not None else self.screen.snapshot()

    def _read(self):
        while self._alive:
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.05)
            except (OSError, ValueError):
                break
            if not ready:
                if self.proc.poll() is not None:
                    break
                continue
            try:
                data = os.read(self.fd, 1 << 16)
            except OSError:
                break
            if not data:
                break
            with self.lock:
                self.screen.feed(data)

    def frame(self) -> Frame:
        """The screen as a terminal would show it now."""
        with self.lock:
            return Frame(time.monotonic(), self._rows(), self.screen.theme)

    def start_recording(self):
        """Keep every frame from now on, starting with the one on screen."""
        with self.lock:
            self.frames = [Frame(time.monotonic(), self._rows(), self.screen.theme)]
            self.record = True

    def stop_recording(self):
        self.record = False

    def frame_at(self, t: float) -> Frame:
        """The last frame recorded at or before *t* (time.monotonic)."""
        frames = self.frames
        lo, hi = 0, len(frames)
        while lo < hi:
            mid = (lo + hi) // 2
            if frames[mid].t <= t:
                lo = mid + 1
            else:
                hi = mid
        return frames[max(0, lo - 1)]

    # --- driving it -------------------------------------------------------

    def send(self, data: bytes | str):
        if isinstance(data, str):
            data = data.encode()
        os.write(self.fd, data)

    def mouse(self, button, col, row, release=False):
        """An SGR mouse report; col and row are 1-based cells."""
        self.send(f"\x1b[<{button};{col};{row}{'m' if release else 'M'}")

    def set_theme(self, theme: Theme):
        """What omarchy-theme-set does to a running terminal: new colours
        at once, and the theme marker touched so linecast asks again."""
        with self.lock:
            self.screen.theme = theme
            self.theme = theme
            if self.record:
                self.frames.append(Frame(time.monotonic(), self._rows(), theme))
        self.watch.write_text(theme.name)
        now = time.time()
        os.utime(self.watch, (now, now))

    def stop(self):
        self._alive = False
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
        self._reader.join(timeout=1)
        os.close(self.fd)
        self.watch.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Drawing cells
# ---------------------------------------------------------------------------

def _fc(pattern: str) -> str:
    return subprocess.run(["fc-match", pattern, "--format=%{file}"],
                          capture_output=True, text=True, check=True).stdout


class Typeface:
    """A monospace face at a pixel density, with fontconfig's fallbacks
    for what it lacks.  Cell size follows foot: the advance rounded, and
    the face's line height."""

    def __init__(self, family="Monaspace Neon NF", size=11.0, scale=2.0, lang=""):
        from PIL import ImageFont
        self.ImageFont = ImageFont
        self.family, self.lang = family, lang
        self.px = size * scale * 96 / 72
        self.faces = {}
        for style, key in (("Regular", 0), ("Bold", BOLD), ("Italic", ITALIC),
                           ("Bold Italic", BOLD | ITALIC)):
            self.faces[key] = ImageFont.truetype(_fc(f"{family}:style={style}"), self.px)
        regular = self.faces[0]
        self.ascent, self.descent = regular.getmetrics()
        self.cell_w = round(regular.getlength("0"))
        self.cell_h = max(round(regular.font.height), self.ascent + self.descent)
        self.baseline = self.ascent + (self.cell_h - self.ascent - self.descent) // 2
        self.primary = _fc(f"{family}:style=Regular")
        self._fallback: dict[str, object] = {}
        self._glyphs: dict = {}

    @functools.cached_property
    def coverage(self) -> frozenset:
        """The codepoints the primary face has, as fontconfig lists them."""
        out = subprocess.run(["fc-query", "--format=%{charset}", self.primary],
                             capture_output=True, text=True, check=True).stdout
        covered = set()
        for span in out.split():
            lo, _, hi = span.partition("-")
            covered.update(range(int(lo, 16), int(hi or lo, 16) + 1))
        return frozenset(covered)

    def face_for(self, ch: str, style: int):
        """The face to draw *ch* in: the primary one when it has the
        glyph, else whatever fontconfig suggests for it, as foot does
        (Monaspace has no ʻokina, for one)."""
        cp = ord(ch)
        if cp < 0x7F or cp in self.coverage:
            return self.faces[style & (BOLD | ITALIC)], False
        key = (cp, style & BOLD)
        if key not in self._fallback:
            lang = f":lang={self.lang}" if self.lang else ""
            weight = ":weight=bold" if style & BOLD else ""
            path = _fc(f"{self.family}{lang}{weight}:charset={cp:x}")
            if path == self.primary or path.endswith(Path(self.primary).name):
                self._fallback[key] = (self.faces[style & (BOLD | ITALIC)], False)
            elif "Emoji" in path:
                self._fallback[key] = (self.ImageFont.truetype(path, 109), True)
            else:
                self._fallback[key] = (self.ImageFont.truetype(path, self.px), False)
        return self._fallback[key]

    def glyph(self, text: str, style: int, width: int):
        """An alpha mask for *text* (or an RGBA image for colour emoji),
        with its offset from the cell's top left."""
        key = (text, style & (BOLD | ITALIC), width)
        hit = self._glyphs.get(key)
        if hit is not None:
            return hit
        from PIL import Image, ImageDraw
        face, emoji = self.face_for(text[0], style)
        cw, ch = self.cell_w, self.cell_h
        if emoji:
            size = int(face.size * 1.4)
            im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((size // 2, size // 2), text, font=face,
                                    anchor="mm", embedded_color=True)
            box = im.getbbox() or (0, 0, 1, 1)
            im = im.crop(box)
            target = ch * 0.8
            factor = min(target / im.height, (width * cw) / im.width)
            im = im.resize((max(1, round(im.width * factor)),
                            max(1, round(im.height * factor))), Image.LANCZOS)
            hit = (im, ((width * cw - im.width) // 2, (ch - im.height) // 2), True)
        else:
            pad = cw
            im = Image.new("L", (width * cw + 2 * pad, ch + 2 * pad), 0)
            x = pad
            advance = face.getlength(text)
            if width == 2 or advance > width * cw + 1:
                x = pad + (width * cw - advance) / 2    # centre wide glyphs
            if Path(getattr(face, "path", "")).name != Path(self.primary).name \
                    and not emoji and width == 1:
                x = pad + max(0, (cw - advance) / 2)
            ImageDraw.Draw(im).text((x, pad + self.baseline), text, font=face,
                                    fill=255, anchor="ls")
            hit = (im, (-pad, -pad), False)
        self._glyphs[key] = hit
        return hit


def _resolve(color, theme: Theme, default: RGB) -> RGB:
    if color is None:
        return default
    if isinstance(color, int):
        return theme.color(color)
    return color


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _block_rects(cp, w, h):
    """Rectangles (x0, y0, x1, y1, alpha) for the block elements, U+2580-259F."""
    half_w, half_h = w // 2, h // 2
    if cp == 0x2580:
        return [(0, 0, w, half_h, 1)]
    if 0x2581 <= cp <= 0x2588:                          # lower eighths, full
        top = h - round(h * (cp - 0x2580) / 8)
        return [(0, top, w, h, 1)]
    if 0x2589 <= cp <= 0x258F:                          # left eighths
        return [(0, 0, round(w * (0x2590 - cp) / 8), h, 1)]
    if cp == 0x2590:
        return [(half_w, 0, w, h, 1)]
    if cp in (0x2591, 0x2592, 0x2593):
        return [(0, 0, w, h, (cp - 0x2590) / 4)]
    if cp == 0x2594:
        return [(0, 0, w, round(h / 8), 1)]
    if cp == 0x2595:
        return [(w - round(w / 8), 0, w, h, 1)]
    quads = {0x2596: "3", 0x2597: "4", 0x2598: "1", 0x2599: "134",
             0x259A: "14", 0x259B: "123", 0x259C: "124", 0x259D: "2",
             0x259E: "23", 0x259F: "234"}
    boxes = {"1": (0, 0, half_w, half_h), "2": (half_w, 0, w, half_h),
             "3": (0, half_h, half_w, h), "4": (half_w, half_h, w, h)}
    return [(*boxes[q], 1) for q in quads.get(cp, "")]


def _braille_dots(cp, w, h):
    """The raised dots of a braille cell as squares, spaced as foot spaces them."""
    bits = cp - 0x2800
    size = max(1, min(w // 4, h // 8))
    xs = (round(w / 4 - size / 2), round(3 * w / 4 - size / 2))
    ys = [round(h * (2 * i + 1) / 8 - size / 2) for i in range(4)]
    order = ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3))
    return [(xs[c], ys[r], xs[c] + size, ys[r] + size)
            for bit, (c, r) in enumerate(order) if bits & (1 << bit)]


def _light_line_rects(cp, w, h, t):
    """The plain box-drawing lines linecast uses, as rectangles; None for
    any other, which the font then draws."""
    cx0 = (w - t) // 2
    cy0 = (h - t) // 2
    left, right = (0, cy0, cx0 + t, cy0 + t), (cx0, cy0, w, cy0 + t)
    up, down = (cx0, 0, cx0 + t, cy0 + t), (cx0, cy0, cx0 + t, h)
    parts = {0x2500: (left, right), 0x2502: (up, down), 0x250C: (right, down),
             0x2510: (left, down), 0x2514: (right, up), 0x2518: (left, up),
             0x251C: (up, down, right), 0x2524: (up, down, left),
             0x252C: (left, right, down), 0x2534: (left, right, up),
             0x253C: (left, right, up, down), 0x2574: (left,), 0x2575: (up,),
             0x2576: (right,), 0x2577: (down,)}
    return parts.get(cp)


def render_cells(frame: Frame, face: Typeface, dim_blend=0.45):
    """The cells as an RGB image, one cell_w x cell_h rectangle each."""
    from PIL import Image, ImageDraw
    theme = frame.theme
    rows = frame.rows
    cw, ch = face.cell_w, face.cell_h
    cols = len(rows[0]) if rows else 0
    im = Image.new("RGB", (cols * cw, len(rows) * ch), theme.bg)
    draw = ImageDraw.Draw(im)
    line_t = max(1, round(face.px / 14))
    texts = []
    for y, row in enumerate(rows):
        top = y * ch
        run_start, run_color = 0, None
        for x, (text, pen, width) in enumerate(row):
            fg_raw, bg_raw, attrs = pen
            fg = _resolve(fg_raw, theme, theme.fg)
            bg = _resolve(bg_raw, theme, theme.bg)
            if attrs & REVERSE:
                fg, bg = bg, fg
            if attrs & DIM:
                fg = _mix(fg, bg, dim_blend)
            if bg != run_color:
                if run_color is not None and run_color != theme.bg:
                    draw.rectangle((run_start * cw, top, x * cw - 1, top + ch - 1),
                                   fill=run_color)
                run_start, run_color = x, bg
            if width == 0 or text == " " or attrs & INVISIBLE:
                continue
            cp = ord(text[0])
            left = x * cw
            if 0x2800 <= cp <= 0x28FF and len(text) == 1:
                texts.append(("dots", left, top, fg, _braille_dots(cp, cw, ch)))
            elif 0x2580 <= cp <= 0x259F and len(text) == 1:
                texts.append(("blocks", left, top, (fg, bg), _block_rects(cp, cw, ch)))
            elif (rects := _light_line_rects(cp, cw, ch, line_t)) is not None:
                texts.append(("dots", left, top, fg, rects))
            else:
                texts.append(("text", left, top, fg, (text, attrs, width)))
            if attrs & (UNDERLINE | STRIKE):
                texts.append(("lines", left, top, fg, (attrs, width)))
        if run_color is not None and run_color != theme.bg:
            draw.rectangle((run_start * cw, top, cols * cw - 1, top + ch - 1),
                           fill=run_color)
    # Shapes before text, so an overhanging glyph lands on top.
    for kind, left, top, color, data in texts:
        if kind == "dots":
            for x0, y0, x1, y1 in data:
                draw.rectangle((left + x0, top + y0, left + x1 - 1, top + y1 - 1),
                               fill=color)
        elif kind == "blocks":
            fg, bg = color
            for x0, y0, x1, y1, alpha in data:
                fill = fg if alpha == 1 else _mix(bg, fg, alpha)
                if x1 > x0 and y1 > y0:
                    draw.rectangle((left + x0, top + y0, left + x1 - 1, top + y1 - 1),
                                   fill=fill)
    for kind, left, top, color, data in texts:
        if kind == "text":
            text, attrs, width = data
            mask, (dx, dy), is_color = face.glyph(text, attrs, width)
            if is_color:
                im.paste(mask, (left + dx, top + dy), mask)
            else:
                im.paste(color, (left + dx, top + dy,
                                 left + dx + mask.width, top + dy + mask.height), mask)
        elif kind == "lines":
            attrs, width = data
            if attrs & UNDERLINE:
                y0 = top + face.baseline + line_t * 2
                draw.rectangle((left, y0, left + width * cw - 1, y0 + line_t - 1),
                               fill=color)
            if attrs & STRIKE:
                y0 = top + face.baseline - face.ascent // 3
                draw.rectangle((left, y0, left + width * cw - 1, y0 + line_t - 1),
                               fill=color)
    return im


# ---------------------------------------------------------------------------
# The Omarchy frame
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Look:
    """Hyprland's and foot's measurements on Omarchy, in logical pixels."""
    scale: float = 2.0
    border: int = 2
    foot_pad: int = 14
    gaps_in: int = 5
    gaps_out: int = 10


def window_image(frame: Frame, face: Typeface, size_px=None, look=None,
                 active=False):
    """One foot window: its padding, its cells, and its border.  *size_px*
    is the window's inside size; by default just the cells and padding.
    foot leaves any extra room at the right and the bottom."""
    from PIL import Image
    look = look or Look()
    cells = render_cells(frame, face)
    pad = round(look.foot_pad * look.scale)
    border = round(look.border * look.scale)
    inner_w, inner_h = size_px or (cells.width + 2 * pad, cells.height + 2 * pad)
    im = Image.new("RGB", (inner_w + 2 * border, inner_h + 2 * border),
                   frame.theme.accent if active else frame.theme.inactive_border)
    body = Image.new("RGB", (inner_w, inner_h), frame.theme.bg)
    body.paste(cells.crop((0, 0, min(cells.width, inner_w - pad),
                           min(cells.height, inner_h - pad))), (pad, pad))
    im.paste(body, (border, border))
    return im


@functools.lru_cache(maxsize=8)
def _wallpaper(path: Path | None, size: tuple[int, int], fallback: RGB):
    from PIL import Image, ImageOps
    if path is None or not path.exists():
        return Image.new("RGB", size, fallback)
    with Image.open(path) as src:
        return ImageOps.fit(src.convert("RGB"), size, Image.LANCZOS)


def desktop_image(size_px, windows, theme: Theme):
    """Windows over the theme's wallpaper.  *windows* is a list of
    (image, (x, y)) with x, y the top left of each window's border."""
    im = _wallpaper(theme.wallpaper, tuple(size_px), theme.bg).copy()
    for image, pos in windows:
        im.paste(image, pos)
    return im


def framed(image, theme: Theme, margin_px: int):
    """A lone window with a margin of wallpaper round it, as termshot frames one."""
    size = (image.width + 2 * margin_px, image.height + 2 * margin_px)
    return desktop_image(size, [(image, (margin_px, margin_px))], theme)


# ---------------------------------------------------------------------------
# Recordings
# ---------------------------------------------------------------------------

def encode(stills, out: Path, fps: float, width: int | None = None,
           per_frame_palette=False):
    """*stills* is [(image, seconds)]; writes a looping GIF, or an MP4 when
    *out* ends in .mp4, through ffmpeg."""
    with tempfile.TemporaryDirectory(prefix="linecast-offscreen-") as tmp:
        tmp = Path(tmp)
        lines = ["ffconcat version 1.0"]
        for i, (image, seconds) in enumerate(stills):
            name = f"{i:05d}.png"
            image.save(tmp / name, compress_level=1)
            lines += [f"file '{name}'", f"duration {seconds:.4f}"]
        lines.append(f"file '{len(stills) - 1:05d}.png'")
        (tmp / "list.ffconcat").write_text("\n".join(lines) + "\n")
        scale = f"scale={width}:-2:flags=lanczos," if width else ""
        if out.suffix == ".mp4":
            vf = f"{scale}fps={fps},format=yuv420p"
            codec = ["-c:v", "libx264", "-crf", "16", "-preset", "slow",
                     "-movflags", "+faststart"]
        else:
            # No dithering: the frames are flat colour, and dither noise
            # is what makes a GIF of them big.
            if per_frame_palette:
                palette = ("split[a][b];[a]palettegen=stats_mode=single[p];"
                           "[b][p]paletteuse=new=1:dither=none")
            else:
                palette = ("split[a][b];[a]palettegen=stats_mode=diff[p];"
                           "[b][p]paletteuse=dither=none:diff_mode=rectangle")
            vf = scale + palette
            codec = ["-loop", "0"]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
                        "-safe", "0", "-i", str(tmp / "list.ffconcat"),
                        "-vf", vf, "-fps_mode", "vfr", *codec, str(out)], check=True)


def sample(render, key_at, t0, t1, fps):
    """Resample a recording to *fps*: [(image, seconds)], a new image only
    where *key_at(t)* changes, so still stretches cost one frame."""
    stills, last_key = [], object()
    step = 1.0 / fps
    n = max(1, round((t1 - t0) / step))
    for i in range(n):
        t = t0 + i * step
        key = key_at(t)
        if key == last_key:
            image, seconds = stills[-1]
            stills[-1] = (image, seconds + step)
        else:
            stills.append((render(t), step))
            last_key = key
    return stills


# ---------------------------------------------------------------------------
# A pointer, for recordings where the mouse does the work
# ---------------------------------------------------------------------------

class Pointer:
    """Moves the mouse over a session in fractional cells, sending the app
    the cell it is over, and remembers where it was when, so the pointer
    can be drawn into the frames."""

    def __init__(self, session):
        self.session = session
        self.track = []           # (t, col, row, pressed)
        self.col = self.row = None
        self.pressed = False

    def _at(self, col, row, pressed, report=True):
        cell = (round(col), round(row))
        if report and cell != (self.col, self.row):
            button = 32 if pressed else 35
            self.session.mouse(button, *cell)
        self.col, self.row = cell
        self.track.append((time.monotonic(), col, row, pressed))

    def glide(self, to, seconds, pressed=None, fps=60):
        pressed = self.pressed if pressed is None else pressed
        start = self.track[-1][1:3] if self.track else to
        n = max(1, int(seconds * fps))
        for k in range(1, n + 1):
            e = 0.5 - 0.5 * math.cos(math.pi * k / n)
            time.sleep(seconds / n)
            self._at(start[0] + (to[0] - start[0]) * e,
                     start[1] + (to[1] - start[1]) * e, pressed)

    def place(self, col, row):
        self.track.append((time.monotonic(), col, row, False))
        self.col, self.row = round(col), round(row)

    def press(self):
        self.pressed = True
        self.session.mouse(0, self.col, self.row)
        self.track.append((time.monotonic(), *self.track[-1][1:3], True))

    def release(self):
        self.pressed = False
        self.session.mouse(0, self.col, self.row, release=True)
        self.track.append((time.monotonic(), *self.track[-1][1:3], False))

    def at(self, t):
        """(col, row, pressed) at time *t*, or None before it appears."""
        last = None
        for entry in self.track:
            if entry[0] > t:
                break
            last = entry
        return last[1:] if last else None


def draw_pointer(image, x, y, size, pressed):
    """A plain arrow pointer with its tip at (x, y)."""
    from PIL import ImageDraw
    s = size / 16
    shape = [(0, 0), (0, 15), (4, 11), (7, 17.5), (9.6, 16.4), (6.8, 10.2), (11.5, 10.2)]
    points = [(x + px * s, y + py * s) for px, py in shape]
    draw = ImageDraw.Draw(image)
    draw.polygon(points, fill=(236, 236, 236) if not pressed else (200, 200, 200),
                 outline=(20, 20, 20), width=max(1, round(s * 1.1)))


# ---------------------------------------------------------------------------
# The command line: termshot's, for the options the gallery script uses
# ---------------------------------------------------------------------------

USAGE = """\
usage: offscreen_terminal.py [options] [--] COMMAND...

Run COMMAND in a terminal with no window and write what it draws to a PNG,
or record it to a GIF.  The options are termshot's, so
LINECAST_CAPTURE_TOOL=scripts/offscreen_terminal.py runs
scripts/capture_screenshots.sh without a desktop.

  -o, --out FILE       output path (default ~/Pictures/offscreen-<stamp>.png)
  -s, --size COLSxROWS terminal size in cells (default 120x34)
  -w, --wait SECS      settle time before the actions and the shot (default 4)
      --scale N        pixel density (default 2)
      --pad PX         wallpaper round the window, border included; 0 for the
                       window alone, without its border (default 10)
      --font SPEC      'Family:size=N' (default 'Monaspace Neon NF:size=11')
      --theme NAME     an Omarchy theme (default $LINECAST_CAPTURE_THEME, else
                       the desktop's own)
      --key TEXT       type TEXT (repeatable; actions run in order)
      --press KEY      a named key: Return, Escape, space, slash, Up, ... or a
                       single character
      --sleep SECS     pause between actions
      --hover COLxROW  move the pointer over a cell (1-based); the pointer is
                       drawn in the shot where it stopped
      --click COLxROW  press and release the left button on a cell
      --drag A B       drag with the left button from cell A to cell B
      --scroll COLxROW up|down
      --script FILE    the same actions, one per line (sleep, key, press,
                       hover, click, drag, scroll; # comments)
      --unfocused      the grey border of a window without focus
      --focus          accepted for termshot's sake; windows wear the accent
                       border unless --unfocused
      --width PX       scale the PNG to PX wide
      --gif SECS       record SECS of animation to a GIF; the actions run
                       while it records
      --fps N          GIF frame rate (default 8)
      --gif-width PX   GIF width (default 900)
"""

NAMED_KEYS = {
    "Return": "\r", "Enter": "\r", "KP_Enter": "\r", "Escape": "\x1b", "Tab": "\t",
    "BackSpace": "\x7f", "space": " ", "slash": "/", "question": "?", "plus": "+",
    "minus": "-", "equal": "=", "comma": ",", "period": ".", "less": "<",
    "greater": ">", "bracketleft": "[", "bracketright": "]",
    "Up": "\x1b[A", "Down": "\x1b[B", "Right": "\x1b[C", "Left": "\x1b[D",
    "Home": "\x1b[H", "End": "\x1b[F", "Page_Up": "\x1b[5~", "Prior": "\x1b[5~",
    "Page_Down": "\x1b[6~", "Next": "\x1b[6~", "Delete": "\x1b[3~",
}


def _cell(text):
    col, _, row = text.lower().partition("x")
    return float(col), float(row)


def _script_actions(path):
    actions = []
    for line in Path(path).read_text().splitlines():
        words = line.split("#", 1)[0].split()
        if not words:
            continue
        verb, rest = words[0], words[1:]
        if verb == "key":
            actions.append(("key", line.split(None, 1)[1].split("#", 1)[0].strip()))
        elif verb in ("press", "sleep", "hover", "click", "drag", "scroll"):
            actions.append((verb, *rest))
        else:
            raise SystemExit(f"{path}: unknown action {verb!r}")
    return actions


def run_actions(session, pointer, actions):
    for action in actions:
        verb, args = action[0], action[1:]
        if verb == "key":
            for ch in args[0]:
                session.send(ch)
                time.sleep(0.045)
            time.sleep(0.5)
        elif verb == "press":
            session.send(NAMED_KEYS.get(args[0], args[0]))
            time.sleep(0.5)
        elif verb == "sleep":
            time.sleep(float(args[0]))
        elif verb == "hover":
            pointer.glide(_cell(args[0]), 0.12)
        elif verb == "click":
            pointer.glide(_cell(args[0]), 0.25)
            pointer.press()
            time.sleep(0.08)
            pointer.release()
        elif verb == "drag":
            pointer.glide(_cell(args[0]), 0.35)
            pointer.press()
            pointer.glide(_cell(args[1]), 0.9)
            time.sleep(0.15)
            pointer.release()
        elif verb == "scroll":
            col, row = _cell(args[0])
            pointer.glide((col, row), 0.2)
            for _ in range(int(args[2]) if len(args) > 2 else 1):
                session.mouse(64 if args[1] == "up" else 65, round(col), round(row))
                time.sleep(0.12)


_OPTIONS = {"-o": "out", "--out": "out", "-s": "size", "--size": "size",
            "-w": "wait", "--wait": "wait", "--scale": "scale", "--pad": "pad",
            "--font": "font", "--theme": "theme", "--width": "width",
            "--gif": "gif", "--fps": "fps", "--gif-width": "gif_width"}
_ACTIONS = {"--key": 1, "--press": 1, "--sleep": 1, "--hover": 1, "--click": 1,
            "--drag": 2, "--scroll": 2}


def _parse(argv):
    """Options, actions in the order given, and the command after them."""
    opts = dict(out=None, size="120x34", wait=4.0, scale=2.0, pad=10, width=None,
                font="Monaspace Neon NF:size=11", theme=None, gif=None, fps=8.0,
                gif_width=900, focused=True)
    actions = []
    i = 0
    while i < len(argv):
        a = argv[i]
        n = 1 if a in _OPTIONS or a == "--script" else _ACTIONS.get(a, 0)
        if i + n >= len(argv) and n:
            raise SystemExit(f"offscreen_terminal: {a} needs a value")
        values = argv[i + 1:i + 1 + n]
        if a in _OPTIONS:
            opts[_OPTIONS[a]] = values[0]
        elif a in _ACTIONS:
            actions.append((a[2:], *values))
        elif a == "--script":
            actions += _script_actions(values[0])
        elif a == "--unfocused":
            opts["focused"] = False
        elif a in ("-h", "--help"):
            print(USAGE, end="")
            raise SystemExit(0)
        elif a == "--":
            i += 1
            break
        elif a.startswith("-") and a != "--focus":
            raise SystemExit(f"offscreen_terminal: unknown option {a} (try --help)")
        elif not a.startswith("-"):
            break
        i += 1 + n
    command = argv[i:]
    if not command:
        raise SystemExit("offscreen_terminal: nothing to run (try --help)")
    return opts, actions, command


def main(argv=None):
    opts, actions, command = _parse(sys.argv[1:] if argv is None else argv)
    cols, _, rows = opts["size"].lower().partition("x")
    cols, rows = int(cols), int(rows)
    family, _, rest = opts["font"].partition(":")
    size = 11.0
    for part in rest.split(":"):
        if part.startswith("size="):
            size = float(part[5:])
    theme_name = opts["theme"] or os.environ.get("LINECAST_CAPTURE_THEME")
    theme = Theme.omarchy(theme_name) if theme_name else Theme.current()
    scale, pad = float(opts["scale"]), int(opts["pad"])
    gif = float(opts["gif"]) if opts["gif"] else None
    out = Path(opts["out"] or Path.home() / "Pictures" / time.strftime(
        f"offscreen-%Y%m%d-%H%M%S.{'gif' if gif else 'png'}")).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    face = Typeface(family, size, scale)
    session = Session(command, cols, rows, theme, cell=(face.cell_w, face.cell_h)).start()
    pointer = Pointer(session)
    try:
        time.sleep(float(opts["wait"]))
        if gif:
            session.start_recording()
            t0 = time.monotonic()
            run_actions(session, pointer, actions)
            time.sleep(max(0.0, t0 + gif - time.monotonic()))
            t1 = time.monotonic()
            session.stop_recording()
        else:
            run_actions(session, pointer, actions)
            if actions:
                time.sleep(1.5)
            final = session.frame()
    finally:
        session.stop()

    def picture(frame, face, scale, t=None):
        look = Look(scale=scale)
        image = window_image(frame, face, look=look, active=opts["focused"])
        where = pointer.at(time.monotonic() if t is None else t)
        border = round(look.border * scale)
        if where:
            col, row, pressed = where
            inset = round(look.foot_pad * scale) + border
            draw_pointer(image, inset + (col - 0.5) * face.cell_w,
                         inset + (row - 0.5) * face.cell_h, face.cell_h, pressed)
        if pad <= 0:
            return image.crop((border, border, image.width - border, image.height - border))
        return framed(image, frame.theme, max(0, round((pad - look.border) * scale)))

    if gif:
        # Drawn at 1x, where the cells land on whole pixels, then scaled
        # down only if that is still wider than asked.
        small = Typeface(family, size, 1)
        fps = float(opts["fps"])

        def key_at(t):
            where = pointer.at(t)
            return id(session.frame_at(t)), where and tuple(round(v, 1) for v in where)

        stills = sample(lambda t: picture(session.frame_at(t), small, 1, t),
                        key_at, t0, t1, fps)
        width = int(opts["gif_width"])
        encode(stills, out, fps, width if stills[0][0].width > width else None)
    else:
        image = picture(final, face, scale)
        if opts["width"] and image.width > int(opts["width"]):
            from PIL import Image
            w = int(opts["width"])
            image = image.resize((w, round(image.height * w / image.width)), Image.LANCZOS)
        image.save(out, optimize=True)
    from PIL import Image
    with Image.open(out) as im:
        print(f"offscreen_terminal: {out} ({im.width}x{im.height})")


if __name__ == "__main__":
    main()
