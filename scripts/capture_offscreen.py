#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""The README's desktops and recordings, drawn by scripts/offscreen_terminal.py.

Usage:
    scripts/capture_offscreen.py [options] TARGET...

Targets:
    hero        hero.png: five apps tiled on one desktop, in the arrangement
                of Andrew's desktop 2, the Moon in Japanese and the year of
                daylight in Icelandic
    moon        moon-alone.png, the Moon with the text put away (t)
    moon-spin   moon-spin.gif and .mp4: the Moon dragged round and let go,
                settling back to the face it really shows
    sky-time    sky-time.gif and .mp4: the whole sky overhead, played
                through an August afternoon and night at an hour a second
    themes      themes.gif and .mp4: the hero desktop through a run of
                Omarchy themes, the apps taking each one up as it lands
    languages   languages.png: a second desktop, the apps in Canadian French,
                Icelandic, Hawaiian, and Japanese
    all         every target above

Nothing here touches the desktop it runs on: each app runs in its own
pseudo-terminal, and the Omarchy frame around it (the theme's wallpaper,
Hyprland's gaps and borders, foot's padding) is drawn to measure.  The
wallpaper and colours are the theme's own, read from its colors.toml.
The hero and the themes run live, so they are whatever the day is; the
languages desktop's Moons, month, and sky, and the Moon recording, are
fixed moments frozen by scripts/capture_moment.py, so those repeat.

Read every frame back before committing it.  A finished command is not
proof that a live pane finished loading.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from offscreen_terminal import (  # noqa: E402
    REPO, Look, Pointer, Session, Theme, Typeface, desktop_image, draw_pointer, encode,
    framed, sample, window_image,
)

SHOTS = REPO / "screenshots"
PY = sys.executable
FAMILY = "Monaspace Neon NF"

WESTBROOK = "43.676,-70.371"
OKINAWA = "26.2124,127.6809"
REYKJAVIK = "64.1466,-21.9426"
HILO = "19.7297,-155.0900"


def linecast(*args):
    return [PY, "-m", "linecast", *args]


def moment(at, location, app, *args):
    """An astronomy view frozen at *at*, local time on this machine."""
    return [PY, str(REPO / "scripts/capture_moment.py"), "--at", at,
            "--location", location, app, "--", *args]


# ---------------------------------------------------------------------------
# Desktops
# ---------------------------------------------------------------------------

@dataclass
class Pane:
    """One terminal on the desktop: what runs in it, keys typed once it
    has drawn, and the language whose fonts its fallback glyphs prefer."""
    argv: list[str]
    keys: str = ""
    lang: str = ""
    active: bool = False
    hover: tuple = ()       # where the pointer rests, as fractions of the grid
    session: Session | None = field(default=None, repr=False)
    rect: tuple = ()        # the window's inside, in logical pixels


def h(ratio, left, right):
    return ("h", ratio, left, right)


def v(ratio, top, bottom):
    return ("v", ratio, top, bottom)


def tile(node, box, gap):
    """Split *box* (x, y, w, h) the way Hyprland's dwindle does: each
    split leaves *gap* between its halves.  Returns (pane, box) pairs, each
    box the window's border box."""
    if isinstance(node, Pane):
        return [(node, box)]
    kind, ratio, a, b = node
    x, y, w, ht = box
    if kind == "h":
        first = round((w - gap) * ratio)
        return (tile(a, (x, y, first, ht), gap)
                + tile(b, (x + first + gap, y, w - first - gap, ht), gap))
    first = round((ht - gap) * ratio)
    return (tile(a, (x, y, w, first), gap)
            + tile(b, (x, y + first + gap, w, ht - first - gap), gap))


class Desktop:
    """Panes tiled on a screen of *size* logical pixels, drawn at *scale*.
    *top* is the margin above the windows: the bar's room on a real
    desktop, the side margin when there is no bar to leave room for."""

    def __init__(self, layout, theme, size=(1920, 1200), scale=2.0,
                 font_size=12.0, top=None):
        self.theme = theme
        self.look = Look(scale=scale)
        self.size = size
        self.font_size = font_size
        look = self.look
        edge = look.gaps_out + look.border
        top = edge if top is None else top
        box = (look.gaps_out, top - look.border,
               size[0] - 2 * look.gaps_out, size[1] - top + look.border - look.gaps_out)
        self.panes = []
        for pane, (x, y, w, ht) in tile(layout, box, 2 * look.gaps_in):
            b = look.border
            pane.rect = (x + b, y + b, w - 2 * b, ht - 2 * b)
            self.panes.append(pane)
        self._faces = {}

    def face(self, lang="", scale=None):
        key = (lang if lang in ("ja", "zh", "ko") else "", scale or self.look.scale)
        if key not in self._faces:
            self._faces[key] = Typeface(FAMILY, self.font_size, key[1], lang=key[0])
        return self._faces[key]

    def px(self, value, scale=None):
        return round(value * (scale or self.look.scale))

    def start(self, settle=8.0):
        face = self.face()
        pad = self.px(self.look.foot_pad)
        for pane in self.panes:
            _, _, w, ht = pane.rect
            cols = (self.px(w) - 2 * pad) // face.cell_w
            rows = (self.px(ht) - 2 * pad) // face.cell_h
            pane.session = Session(pane.argv, cols, rows, self.theme,
                                   cell=(face.cell_w, face.cell_h)).start()
        time.sleep(settle)
        acted = False
        for pane in self.panes:
            for key in pane.keys:
                pane.session.send(key)
                time.sleep(0.2)
                acted = True
            if pane.hover:
                s = pane.session
                pane.cell = (max(1, round(pane.hover[0] * s.cols)),
                             max(1, round(pane.hover[1] * s.rows)))
                for dx in (-1, 0):          # a move, then the move that counts
                    s.mouse(35, pane.cell[0] + dx, pane.cell[1])
                    time.sleep(0.3)
                acted = True
        if acted:
            time.sleep(1.5)
        return self

    def stop(self):
        for pane in self.panes:
            if pane.session:
                pane.session.stop()

    def set_theme(self, theme):
        self.theme = theme
        for pane in self.panes:
            pane.session.set_theme(theme)

    def start_recording(self):
        for pane in self.panes:
            pane.session.start_recording()

    def frames_at(self, t=None):
        return [p.session.frame() if t is None else p.session.frame_at(t)
                for p in self.panes]

    def image(self, frames=None, scale=None):
        """The desktop, drawn at *scale* (by default the one it was laid
        out at; the cells are the same either way)."""
        frames = frames or self.frames_at()
        scale = scale or self.look.scale
        look = Look(scale=scale)
        windows = []
        for pane, frame in zip(self.panes, frames):
            x, y, w, ht = pane.rect
            b = look.border
            face = self.face(pane.lang, scale)
            im = window_image(frame, face, (self.px(w, scale), self.px(ht, scale)), look,
                              active=pane.active)
            if pane.hover:
                inset = self.px(look.foot_pad + look.border, scale)
                col, row = pane.cell
                draw_pointer(im, inset + (col - 0.5) * face.cell_w,
                             inset + (row - 0.5) * face.cell_h, face.cell_h, False)
            windows.append((im, (self.px(x - b, scale), self.px(y - b, scale))))
        theme = frames[0].theme if frames else self.theme
        return desktop_image((self.px(self.size[0], scale), self.px(self.size[1], scale)),
                             windows, theme)


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

def hero_layout(radar_place):
    """Andrew's desktop 2: the weather over its year on the left; the
    radar on the right, over the Moon and the sunshine year side by side."""
    return h(0.535,
             v(0.635, Pane(linecast("weather", "--location", "Westbrook, Maine")),
                      Pane(linecast("weather", "--year", "--location", "Westbrook, Maine"),
                           active=True)),
             v(0.575, Pane(linecast("radar", "--location", radar_place)),
                      h(0.52, Pane(linecast("moon", "--location", OKINAWA, "--lang", "ja",
                                            "--24h"), lang="ja"),
                              Pane(linecast("sunshine", "--year", "--location",
                                            "Reykjavík", "--lang", "is", "--24h")))))


def hero(args, theme):
    desk = Desktop(hero_layout(args.radar), theme).start(settle=args.settle)
    try:
        image = desk.image()
    finally:
        desk.stop()
    save(image, args.out / "hero.png", args.width)


def languages(args, theme):
    """A second desktop, the apps in other tongues and traditions:
    Montréal's weather in Canadian French; October in Reykjavík by the
    Icelandic calendar, the pointer on the first day of winter; the
    Moon over Hilo by the Hawaiian calendar and over Okinawa in
    Japanese; and the January sky in the Hawaiian tradition, with the
    navigators' star compass along the horizon."""
    layout = h(0.5,
               v(0.56, Pane(linecast("weather", "--location", "Montréal, Québec",
                                     "--lang", "fr-CA", "--metric", "--24h")),
                       Pane(moment("2026-10-24T21:00", REYKJAVIK, "moon", "--lang", "is",
                                   "--24h", "--calendar", "icelandic", "--month"),
                            hover=(0.93, 0.72))),
               v(0.5, h(0.5, Pane(moment("2026-09-25T21:00", HILO, "moon",
                                         "--calendar", "hawaiian", "--location", HILO)),
                             Pane(moment("2026-09-26T21:30", OKINAWA, "moon",
                                         "--lang", "ja", "--24h"), lang="ja")),
                      Pane(moment("2026-01-15T21:00", WESTBROOK, "sky",
                                  "--location", WESTBROOK, "--facing", "S",
                                  "--culture", "hawaiian"), active=True)))
    desk = Desktop(layout, theme).start(settle=args.settle)
    try:
        image = desk.image()
    finally:
        desk.stop()
    save(image, args.out / "languages.png", args.width)


def moon_alone(args, theme):
    face = Typeface(FAMILY, 11, 2)
    s = Session(moment("2026-08-22T21:30", WESTBROOK, "moon"), 96, 30, theme,
                cell=(face.cell_w, face.cell_h)).start()
    try:
        time.sleep(3)
        s.send("t")
        time.sleep(1.5)
        frame = s.frame()
    finally:
        s.stop()
    save(framed(window_image(frame, face), theme, 40), args.out / "moon-alone.png", None)


def moon_spin(args, theme):
    """Drag the Moon round by its limb and let go: it rolls back to the
    face it shows tonight, with a small overshoot."""
    face = Typeface(FAMILY, 11, 2)
    cols, rows = 96, 30
    s = Session(moment("2026-08-22T21:30", WESTBROOK, "moon"), cols, rows, theme,
                cell=(face.cell_w, face.cell_h)).start()
    pointer = Pointer(s)
    try:
        time.sleep(3)
        s.send("t")
        time.sleep(1.5)
        cx, cy = cols / 2, rows / 2
        pointer.place(cx + 30, cy + 9)
        s.start_recording()
        t0 = time.monotonic()
        pointer.glide((cx - 8, cy + 1), 0.9)
        time.sleep(0.2)
        pointer.press()
        pointer.glide((cx + 12, cy - 1), 0.9)
        time.sleep(0.25)
        pointer.release()
        time.sleep(1.2)
        pointer.glide((cx + 2, cy + 6), 0.5)
        pointer.press()
        pointer.glide((cx - 6, cy - 7), 0.7)
        time.sleep(0.2)
        pointer.release()
        time.sleep(1.1)
        pointer.glide((cx + 30, cy + 9), 0.8)
        time.sleep(0.6)
        t1 = time.monotonic()
        s.stop_recording()
    finally:
        s.stop()

    def key_at(t):
        where = pointer.at(t)
        return id(s.frame_at(t)), (round(where[0], 1), round(where[1], 1), where[2]) \
            if where else None

    # The recording is cells, so it can be drawn twice: at 2x for the
    # video, and at 1x for the GIF, where the Moon's blocks then land on
    # whole pixels instead of being blurred by a downscale.
    for scale, out in ((2, "moon-spin.mp4"), (1, "moon-spin.gif")):
        face = Typeface(FAMILY, 11, scale)
        look = Look(scale=scale)
        pad = round(look.foot_pad * scale) + round(look.border * scale)

        def render(t, face=face, look=look, pad=pad):
            image = window_image(s.frame_at(t), face, look=look)
            where = pointer.at(t)
            if where:
                col, row, pressed = where
                draw_pointer(image, pad + (col - 0.5) * face.cell_w,
                             pad + (row - 0.5) * face.cell_h, face.cell_h, pressed)
            return image

        stills = sample(render, key_at, t0, t1, fps=30 if scale == 2 else 20)
        encode(stills, args.out / out, 30 if scale == 2 else 20)
    report(args.out / "moon-spin.gif")


def sky_time(args, theme):
    """The whole sky, zoomed out with - until the horizon closes into a
    circle overhead, then played forward (p) at an hour a second through
    an August afternoon and night over Westbrook: the Sun and a waxing
    Moon crossing, the sunset and its colours, the stars and then the
    Milky Way coming out as the Moon goes down, the whole dome turning."""
    cols, rows = 110, 36
    face = Typeface(FAMILY, 11, 2)
    # Facing south as it lies back, so north is at the top of the circle.
    s = Session(moment("2026-08-18T15:00", WESTBROOK, "sky", "--location", WESTBROOK,
                       "--facing", "S"),
                cols, rows, theme, cell=(face.cell_w, face.cell_h)).start()
    try:
        time.sleep(4)
        for _ in range(4):
            s.send("-")
            time.sleep(0.15)
        time.sleep(2.5)
        s.start_recording()
        t0 = time.monotonic()
        time.sleep(1.0)              # a moment of the afternoon first
        s.send("p")
        time.sleep(args.hours)
        t1 = time.monotonic()
        s.stop_recording()
    finally:
        s.stop()

    def key_at(t):
        return id(s.frame_at(t))

    for scale, out, fps in ((1, "sky-time.gif", 15), (2, "sky-time.mp4", 30)):
        face = Typeface(FAMILY, 11, scale)
        look = Look(scale=scale)
        stills = sample(lambda t, face=face, look=look: window_image(s.frame_at(t), face,
                                                                     look=look),
                        key_at, t0, t1, fps)
        encode(stills, args.out / out, fps)
    report(args.out / "sky-time.gif")


THEME_RUN = ("tokyo-night", "catppuccin-latte", "gruvbox", "rose-pine", "everforest",
             "kanagawa", "flexoki-light", "osaka-jade", "ristretto", "nord")


def themes(args, theme):
    """The hero desktop, the theme changing under it every couple of
    seconds, the way omarchy-theme-set changes a running desktop."""
    run = [Theme.omarchy(name) for name in (args.themes or THEME_RUN)]
    desk = Desktop(hero_layout(args.radar), run[0])
    for pane in desk.panes:
        if "radar" in pane.argv:
            pane.keys = " "          # hold the radar on one frame
    desk.start(settle=args.settle)
    settled = []                     # each theme's desktop, just before the next
    try:
        desk.start_recording()
        t0 = time.monotonic()
        for theme in run[1:]:
            time.sleep(args.hold)
            settled.append(desk.frames_at())
            desk.set_theme(theme)
        time.sleep(args.hold)
        settled.append(desk.frames_at())
        t1 = time.monotonic()
    finally:
        desk.stop()

    # The GIF cuts from one settled theme to the next, which is what the
    # change looks like at a GIF's pace; each pane's half second of
    # catching up would otherwise cost a full frame apiece.  At 1x it is
    # the laptop's own screen, pixel for pixel.  The video keeps it all.
    encode([(desk.image(frames, 1), args.hold) for frames in settled],
           args.out / "themes.gif", 10, per_frame_palette=True)

    def key_at(t):
        return tuple(id(f) for f in desk.frames_at(t))

    stills = sample(lambda t: desk.image(desk.frames_at(t), 2), key_at, t0, t1, fps=30)
    encode(stills, args.out / "themes.mp4", 30)
    report(args.out / "themes.gif")


# ---------------------------------------------------------------------------

def save(image, path, width):
    if width and image.width > width:
        from PIL import Image
        image = image.resize((width, round(image.height * width / image.width)),
                             Image.LANCZOS)
    image.save(path, optimize=True)
    report(path)


def report(path):
    print(f"  {path.relative_to(REPO) if path.is_relative_to(REPO) else path}"
          f"  {path.stat().st_size / 1e6:.1f} MB")


TARGETS = {"hero": hero, "moon": moon_alone, "moon-spin": moon_spin,
           "sky-time": sky_time, "themes": themes, "languages": languages}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("targets", nargs="+", choices=[*TARGETS, "all"])
    parser.add_argument("--theme", default=None,
                        help="Omarchy theme for the still frames (default: the current one)")
    parser.add_argument("--themes", nargs="+", help="the run of themes for the themes target")
    parser.add_argument("--hours", type=float, default=10.0,
                        help="hours of the sky-time recording, played at an hour a second")
    parser.add_argument("--hold", type=float, default=2.0,
                        help="seconds on each theme in the themes target")
    parser.add_argument("--radar", default="Portland, Maine",
                        help="where the hero's radar looks")
    parser.add_argument("--settle", type=float, default=15.0,
                        help="seconds for live panes to load before a desktop is shot")
    parser.add_argument("--width", type=int, default=None,
                        help="scale desktops down to this many pixels wide")
    parser.add_argument("--out", type=Path, default=SHOTS)
    args = parser.parse_args()
    recordings = {"moon-spin", "sky-time", "themes", "all"}
    if shutil.which("ffmpeg") is None and recordings & set(args.targets):
        raise SystemExit("capture_offscreen: the recordings need ffmpeg")
    args.out.mkdir(parents=True, exist_ok=True)
    theme = Theme.omarchy(args.theme) if args.theme else Theme.current()
    targets = list(TARGETS) if "all" in args.targets else args.targets
    for name in targets:
        print(f"Capturing {name}…")
        TARGETS[name](args, theme)


if __name__ == "__main__":
    main()
