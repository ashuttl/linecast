"""Live mode: alternate screen rendering with auto-refresh and input handling.

Provides the live_loop() function that runs a render callback in a loop on the
terminal's alternate screen buffer, LiveApp — the class an app with keys and
state subclasses to run under it — and overlay(), which puts a tooltip, modal
or panel over a frame.  The loop supports:

- Auto-refresh on a configurable interval
- Immediate re-render on terminal resize
- Frames paced to the terminal: the next waits until the last was read
- Re-inking in place when the terminal's colour theme changes
- Keyboard navigation (arrows, q to quit, n to reset)
- Mouse wheel scrubbing
- Alert modal interaction (click to open, scroll to read, q/click to dismiss)

What the bytes the terminal sends mean -- keys, mouse reports, replies
to its queries -- is terminal.keys.
"""

import os
import sys
import threading
import time as _time

from linecast.terminal import bidi as _bidi
from linecast.terminal import term as _term


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------
# A frame is laid out to the terminal's own width, so a row the terminal
# measures wider than linecast does -- an emoji it draws with a cell for
# the variation selector, a Nerd Font glyph its font draws double-width --
# runs past the last column and wraps, and every row below it slides down
# one and the top row off the screen.  Painting with the terminal's
# autowrap off makes such a row clip at the margin instead: one row is
# then wrong where the whole frame used to be.
_AUTOWRAP_OFF = "\033[?7l"
_AUTOWRAP_ON = "\033[?7h"

# A frame goes out in one write, but the terminal may draw its screen
# partway through reading it: rows above the read boundary from the new
# frame, rows below from the old, and the row on the boundary cleared
# and half drawn -- a blank stripe across a moon mid-drag.  Between
# these two sequences a terminal that knows synchronized output (DEC
# private mode 2026: Alacritty, kitty, foot, WezTerm, Ghostty, iTerm2,
# Windows Terminal, tmux) holds the screen and shows the frame whole.
# One that does not ignores them, as it ignores any unknown mode.
_SYNC_BEGIN = "\033[?2026h"
_SYNC_END = "\033[?2026l"

# The cursor position query sent after each frame, whose reply says the
# terminal has read the frame (see _Pacing), and how long the next
# frame waits for it: long enough for a terminal that is genuinely
# behind, and not long on a terminal that has yet to answer at all.
_CPR_QUERY = _term.CPR_QUERY.decode("ascii")
_ACK_WAIT_S = 1.0
_ACK_FIRST_WAIT_S = 0.25

# A hover chip goes once the mouse has been still this long, as though the
# pointer had left the window: a view left open on the desk should not
# keep a chip up because the pointer came to rest over it.
_HOVER_IDLE_S = 7.0

# An idle loop sleeps until something is due rather than waking ten times
# a second to look: the theme's watch file is looked at this often, the
# periodic re-probe asks for the two default colours, and every so often
# for the whole palette, for a change that leaves both alone.
_THEME_WATCH_S = 0.5
_FULL_PROBE_S = 10.0


def frame_body(text):
    r"""A frame with every row addressed, so no row can shift the ones below.

    Reaching the next row by newline leaves the terminal to say where it
    is: a row it draws wider than linecast measured wraps, and the row
    below lands one line down, taking the whole frame with it.  Addressed
    rows land where they belong whatever the row above did, and \033[K
    clears whatever the last frame left on them.  The clear comes before
    the row, not after: with autowrap off a row that reaches the last
    column leaves the cursor on that cell, and a clear from there would
    take the cell's glyph with it.
    """
    return "".join(f"\033[{row};1H\033[K{line}"
                   for row, line in enumerate(text.split("\n"), 1))


def frame_paint(body, floating=""):
    r"""Everything the live loop writes for one frame, as one string.

    Rows are addressed (frame_body) and drawn with the terminal's
    autowrap off, so a row drawn wider than it measured cannot shift the
    frame.  \033[J clears below the last row; `floating` -- the
    cursor-addressed overlay -- draws on top.  The whole frame sits
    inside a synchronized update so the terminal shows none of it until
    it has all of it.

    The clear below comes first, from the row after the last, not after
    the body from wherever it ended: a row that reaches the last column
    leaves the cursor on that cell, and \033[J from there erases the
    cell's glyph -- the last letter of the help hint.  When the frame
    fills the screen, skip this clear: terminals clamp the row after
    the last to the last row.  Clearing there would erase the footer
    for the duration of the repaint, visible through tmux when updates
    are not presented atomically.
    """
    rows = body.count("\n") + 1
    width = _mirror_width()
    body, floating = _bidi.display(body, width), _bidi.display(floating, width)
    from linecast.terminal.composition import resolve_shadows
    from linecast.terminal.framebuffer import get_terminal_size
    floating = resolve_shadows(body, floating)
    clear_below = f"\033[{rows + 1};1H\033[J" if rows < get_terminal_size()[1] else ""
    return (f"{_SYNC_BEGIN}{_AUTOWRAP_OFF}{clear_below}{frame_body(body)}"
            f"\033[0m{floating}\033[0m{_AUTOWRAP_ON}{_SYNC_END}")


def _mirror_width():
    """The terminal's width when the view on screen is laid out from the
    right (a right-to-left language), for _bidi.display; else None."""
    if not _bidi.mirrored():
        return None
    from linecast.terminal.framebuffer import get_terminal_size
    return get_terminal_size()[0]


def print_frame(text, stream=None):
    """Print a rendered frame, clipped at the last column rather than wrapped."""
    stream = sys.stdout if stream is None else stream
    try:
        clip = stream.isatty()
    except Exception:
        clip = False
    text = _bidi.display(text, _mirror_width())
    if clip:
        explicit, implicit = bidi_modes()
        stream.write(f"{explicit}{_AUTOWRAP_OFF}{text}{_AUTOWRAP_ON}{implicit}\n")
    else:
        stream.write(f"{text}\n")
    stream.flush()


def print_view(render):
    """Print one frame of a view, for --print or a pipe: the terminal's
    glyph widths measured first, as the live loop measures them before
    its first frame, then *render* called and its frame printed."""
    from linecast.terminal.textwidth import calibrate_from_terminal
    calibrate_from_terminal()
    print_frame(render())


def bidi_modes():
    """The escapes that put the terminal in bidi explicit mode, where it
    draws cells as linecast ordered them, and that take it back out; both
    empty when the terminal is left to order the text itself.  Inside
    tmux the mode goes to the outer terminal too, through tmux's
    passthrough (allow-passthrough on): tmux keeps cells as sent, and a
    VTE terminal around it would otherwise reorder them again."""
    if not _bidi.reorders():
        return "", ""
    explicit, implicit = _bidi.TERMINAL_EXPLICIT, _bidi.TERMINAL_IMPLICIT
    if os.environ.get("TMUX"):
        wrap = "\033Ptmux;\033{}\033\\"
        explicit += wrap.format(explicit)
        implicit += wrap.format(implicit)
    return explicit, implicit


def overlay(body, floating="", motion=None):
    """A frame with something floating over it: a tooltip, a modal, a panel.

    live_loop paints `body` from the top-left, clearing each line to the
    margin, then writes `floating` — cursor-addressed escapes — on top,
    so the overlay is never disturbed by the clear.  `motion` switches
    any-motion mouse reporting (mode 1003) with this frame: False while
    a text field is open, since a torn motion sequence reads as ESC —
    the key guarding the field — True to switch it back on, None to
    leave it as it is.  With nothing floating and no switch, the body
    comes back untouched.  A body that already has something floating,
    a frame a render returned, keeps it: *floating* goes after it, and
    the switch ahead of both.
    """
    switch = "" if motion is None else ("\033[?1003h" if motion
                                        else "\033[?1003l")
    if not floating and not switch:
        return body
    body, _, before = body.partition("\x00")
    return f"{body}\x00{switch}{before}{floating}"


def pointer_chip(lines, col, mouse_row, cols, rows, pad_bg="", flip_at=None):
    """A floating chip near the pointer, placed so the pointer cannot cover it.

    The pointer glyph hangs down and right of its hotspot — further when a
    user has sized it up — so the chip goes below the pointer row with a
    clear row between, and flips to just above the pointer when there is
    no room below; pushed inward at the screen edges as a last resort.

    `lines` are the chip's rows, styled but unpadded; they are padded to
    one visible width, with `pad_bg` re-asserted under the padding.  `col`
    is the 1-based terminal column of the chip's left edge; a chip past
    the right edge slides inward, or with `flip_at` ends just left of that
    column instead (for chips beside a hairline or the pointer itself).
    Returns cursor-addressed escapes for overlay()'s floating channel.
    """
    if not lines or cols < 1 or rows < 1:
        return ""
    from linecast.terminal.textwidth import visible_len
    shadow = cols > 1 and len(lines) < rows
    width = min(cols, max(visible_len(line) for line in lines) + int(shadow))
    height = min(rows, len(lines) + int(shadow))
    row = mouse_row + 2
    if row + height - 1 > rows:
        row = mouse_row - height
    if row < 1:
        row = max(1, rows - height + 1)
    anchor = col if flip_at is None else flip_at
    if flip_at is not None and col + width - 1 > cols:
        col = max(1, flip_at - width)
    col = max(1, min(col, cols - width + 1))
    # Compare the placed footprint with the pointer: when an edge forces
    # the chip across it, the shadow falls on the opposite side too.
    dx = -1 if col + (width - 1) / 2 < anchor else 1
    dy = -1 if row + (height - 1) / 2 < mouse_row else 1
    return chip_at(lines, row + int(shadow and dy < 0),
                   col + int(shadow and dx < 0), cols, pad_bg, rows=rows,
                   shadow_direction=(dx, dy))


def chip_at(lines, row, col, cols, pad_bg="", *, rows=None, shadow=True,
            shadow_direction=(1, 1)):
    """A padded chip with an optional shadow offset one column and half a row.

    Exposed halves are resolved against the displayed frame by frame_paint.
    Reserve the shadow's footprint; on a screen too small for it, keep the
    text and omit the shadow. ``shadow_direction`` gives the horizontal and
    vertical signs; row and col locate the text, excluding the shadow.
    """
    from linecast.terminal import theme
    from linecast.terminal.box import place
    from linecast.terminal.color import RESET, bg, fg
    from linecast.terminal.textwidth import clip_styled, visible_len
    if not lines or cols < 1 or (rows is not None and rows < 1):
        return ""
    shadow = shadow and cols > 1 and (rows is None or len(lines) < rows)
    dx, dy = shadow_direction
    left, up = int(shadow and dx < 0), int(shadow and dy < 0)
    right, down = int(shadow and dx > 0), int(shadow and dy > 0)
    row = max(1 + up, row)
    if rows is not None:
        lines = lines[:rows]
        row = max(1 + up, min(row, rows - len(lines) - down + 1))
    width = min(cols - int(shadow), max(visible_len(line) for line in lines))
    col = max(1 + left, min(col, cols - width - right + 1))
    surface, _, dim = theme.chip_inks()
    pad_bg = pad_bg or bg(*surface)
    from linecast.terminal.composition import SHADOW

    def half_block(glyph):
        return f"\033[0m{SHADOW}{fg(*dim)}{glyph}\033[0m"

    padded = []
    for i, line in enumerate(lines):
        line = clip_styled(line, width)
        body = f"{line}{pad_bg}{' ' * (width - visible_len(line))}{RESET}"
        if shadow:
            end = 0 if dy > 0 else len(lines) - 1
            glyph = ("▄" if dy > 0 else "▀") if i == end else "█"
            side = half_block(glyph)
            body = side + body if dx < 0 else body + side
        padded.append(body)
    out = place(padded, row, col - left)
    if shadow:
        cap = "".join(half_block("▀" if dy > 0 else "▄") for _ in range(width))
        out += place([cap], row + len(lines) if dy > 0 else row - 1, col + dx)
    return out


MUTED = (150, 155, 170)   # the frame and text of a menu box


def menu_box(lines, cols, rows, title="", sel=None, border="", fill="",
             more=(False, False)):
    """A centred box of rows for overlay()'s floating channel: the radar's
    theme picker and the sky's tradition picker are drawn with it, so the
    two read as one thing.

    `lines` are plain-text rows, or None for a rule across the box; each
    is padded to the widest and cut to the screen. `sel` is the index of
    the highlighted row, drawn in reverse video. `title` sits in the top
    border. `border` colours the frame and the text; `fill` is a
    background escape for the interior, or empty to leave the terminal's.
    `more` says whether there is more above and below the rows shown,
    marked ▲ and ▼ in the borders.
    """
    from linecast.terminal.box import REVERSE, REVERSE_OFF, centre, place
    from linecast.terminal.color import RESET
    from linecast.terminal.textwidth import fit, pad, visible_len
    widths = [visible_len(line) for line in lines if line is not None]
    inner = max(0, min(cols - 4, (max(widths) if widths else 0) + 1))
    top, left = centre(cols, rows, inner + 2, len(lines) + 2)
    # The title is centred by cells, and the marks put in the last cell
    # but one counting from the right: a wide glyph in the title is two
    # cells but one character.
    head = pad(fit(f" {title} ", inner), inner, "^", "─") if title else "─" * inner
    foot = "─" * inner
    above, below = more
    if above:
        head = head[:-2] + "▲" + head[-1:]
    if below:
        foot = foot[:-2] + "▼" + foot[-1:]
    out = [f"┌{head}┐"]
    for i, line in enumerate(lines):
        if line is None:
            out.append(f"├{'─' * inner}┤")
            continue
        while line and visible_len(line) > inner:
            line = line[:-1]
        body = pad(line, inner)
        if i == sel:
            body = f"{REVERSE}{body}{REVERSE_OFF}"
        out.append(f"│{body}│")
    out.append(f"└{foot}┘")
    # never on the top row
    return place([f"{border}{fill}{line}{RESET}" for line in out],
                 max(2, top), left)


def toast_box(text, cols, rows, icon=""):
    """A compact, rounded notification above the bottom-right of the view."""
    from linecast.terminal import theme as _theme
    from linecast.terminal.box import at, place
    from linecast.terminal.color import RESET, bg, fg
    from linecast.terminal.textwidth import fit, visible_len
    if cols < 1 or rows < 1:
        return ""
    surface = _theme.surface_bg(0.10)
    ink = fg(*_theme.ensure_contrast(_theme.theme_fg, surface, 4.5))
    border = fg(*_theme.ensure_contrast(_theme.surface_bg(0.55), surface, 2.2))
    fill = bg(*surface)
    label = f"{icon} {text}" if icon else text
    if cols < 8 or rows < 4:
        # A tiny terminal still gets the spinner, without an overflowing box.
        return f"{at(rows, 1)}{fill}{ink}{fit(label, cols)}{RESET}"
    label = fit(label, min(60, cols - 8))
    inner = visible_len(label) + 2
    left, top = cols - inner - 3, rows - 3
    lines = [f"{border}╭{'─' * inner}╮",
             f"{border}│{ink} {label} {border}│",
             f"{border}╰{'─' * inner}╯"]
    return place([f"{fill}{line}{RESET}" for line in lines], top, left)


# ---------------------------------------------------------------------------
# Live loop
# ---------------------------------------------------------------------------
_running = False  # a live loop is on screen with the terminal taken over


class WorkerWatch:
    """threading.excepthook for the length of a live loop.

    A worker thread that raises is otherwise reported by Python's own
    hook: a traceback on stderr, which on the alternate screen is
    overdrawn by the next frame and gone when the screen is restored.
    Installed around the loop, this records each one and logs it
    through log_failure at once; `report()` runs after the terminal is
    back -- every traceback in full with --debug, one line pointing at
    --debug without.
    """

    def __init__(self):
        self.failures = []   # (thread name, type name, first line, traceback)
        self._previous = None

    def install(self):
        import threading
        self._previous = threading.excepthook
        threading.excepthook = self._hook

    def uninstall(self):
        import threading
        if self._previous is not None:
            threading.excepthook = self._previous
            self._previous = None

    def _hook(self, args):
        try:
            import traceback
            from linecast._log import log_failure
            exc = args.exc_value
            if exc is None:
                exc = args.exc_type()
            name = args.thread.name if args.thread is not None else "?"
            text = "".join(traceback.format_exception(
                args.exc_type, exc, args.exc_traceback))
            first = str(exc).splitlines()[0] if str(exc) else ""
            self.failures.append((name, args.exc_type.__name__, first, text))
            log_failure("worker", name, exc, fallback="thread ended")
        except Exception:
            pass  # a hook that raises would only add a second traceback

    def report(self, stream=None):
        """What died, on stderr, once the screen is the user's again."""
        if not self.failures:
            return
        from linecast._log import debug_enabled
        stream = sys.stderr if stream is None else stream
        try:
            if debug_enabled():
                for name, _kind, _first, text in self.failures:
                    stream.write(f"linecast: background task {name} failed:\n{text}")
            else:
                stream.write("linecast: a background task failed; "
                             "run with --debug for details\n")
            stream.flush()
        except Exception:
            pass  # stderr may be gone with the terminal (SIGHUP)


def nudge():
    """Ask the live loop to repaint now, from any thread.

    Wakeups coalesce harmlessly when several arrive at once, and with no
    live loop running this does nothing, so background work can call it
    unconditionally.  _term decides how the wakeup travels: a self-pipe
    written from the SIGWINCH handler on POSIX, an event the poll picks
    up on Windows."""
    _term.nudge()


class Ticker:
    """A thread that wakes the live loop thirty times a second while
    something on screen is in motion: a disc settling, a flick coasting,
    a zoom easing in, a clock running.

    It asks for frames rather than making them: the loop holds each one
    until the terminal says it read the last, so a terminal that cannot
    keep up simply gets fewer, and a wakeup that arrives during the wait
    is absorbed into the frame already coming.  The motion is timed off
    the clock, so fewer frames never make it slower.

    After each wait `step()` runs, then the wakeup goes out.  The step
    moves on whatever runs off the ticker itself, and says whether
    anything is still in motion; the wakeup after the step that says
    not draws the rest, and the thread ends with it.  start() goes with
    every change that sets something moving, and does nothing while the
    thread runs; stop() parks the thread for good at its next wakeup.
    """

    INTERVAL = 1 / 30   # seconds between wakeups

    def __init__(self, step):
        self.step = step
        self.thread = None
        self._lock = threading.Lock()
        self._stopped = False

    def start(self):
        """Run the ticker, unless it is running already."""
        with self._lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.run, daemon=True)
                self.thread.start()

    def stop(self):
        """The loop is over: end the thread at its next wakeup."""
        self._stopped = True

    def run(self):
        while not self._stopped:
            _time.sleep(self.INTERVAL)
            moving = self.step()
            nudge()
            if not moving:
                return


def _mtime(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


class _ThemeSchedule:
    """When an idle live loop next looks at the terminal's colours.

    Nothing here waits.  `look()` does what is due -- a look at the
    theme's watch file, a re-probe sent -- and sets `due` to when the
    next look will be; the idle loop sleeps until then unless something
    else wakes it first.  A changed watch file probes at once, and then
    briskly for a few seconds, since the terminal may get its colours a
    beat after the marker file is written.  Otherwise the periodic probe
    asks for the two default colours, and every _FULL_PROBE_S for the
    whole palette.  The probe's answers arrive as input
    (terminal.keys), not here.
    """

    def __init__(self):
        from linecast.terminal import theme as _theme
        self.poll = _theme.poll_interval()
        self.watch = _theme.watch_path()
        self.watch_mtime = _mtime(self.watch) if self.watch else None
        started = _time.monotonic()
        self.next_probe = started + self.poll
        self.next_watch = started + _THEME_WATCH_S
        self.last_full = started   # the probe at import asked for everything
        self.burst_until = 0.0     # the brisk probing after a watch file change
        self.due = started         # the first idle wait looks at once

    def look(self):
        """Look at the watch file and send a re-probe if either is due,
        and set `due` to when one next will be."""
        from linecast.terminal import theme as _theme
        if not _theme.can_reprobe():
            self.due = float("inf")
            return
        now = _time.monotonic()
        due = []
        if self.watch:
            if now >= self.next_watch:
                self.next_watch = now + _THEME_WATCH_S
                m = _mtime(self.watch)
                if m != self.watch_mtime:
                    self.watch_mtime = m
                    self.burst_until = now + 4.0
                    self.next_probe = now
            due.append(self.next_watch)
        interval = 0.5 if now < self.burst_until else self.poll
        if interval > 0 and now >= self.next_probe:
            if _theme.probe_pending():
                # its answers arrive as input; one the terminal never
                # sends is given up on (probe_pending) by a later look
                self.next_probe = now + 0.5
            else:
                self.next_probe = now + interval
                full = now < self.burst_until or now - self.last_full >= _FULL_PROBE_S
                if _theme.request_probe(sys.stdout.fileno(), full=full) and full:
                    self.last_full = now
        if interval > 0:
            due.append(self.next_probe)
        self.due = min(due) if due else float("inf")


class _Pacing:
    """Frames paced to the terminal.

    Each frame goes out with a cursor position query after it, and the
    next frame waits for the reply: the terminal answers once it has
    read the frame, so a terminal slower than the loop is never handed
    a backlog to play out after the user stops scrolling.  Input that
    arrives during the wait is folded into the frame being held.  A
    terminal that never answers is asked once, then left alone.
    LINECAST_FRAME_SYNC=0 turns the pacing off (`on`).
    """

    def __init__(self):
        self.on = _term.frame_sync_enabled()
        self.owed = 0   # queries sent and not yet answered

    def wait_s(self):
        """How long a frame waits for the last one's reply."""
        return _ACK_WAIT_S if _term.answered else _ACK_FIRST_WAIT_S

    def ask(self):
        """The query to send after a frame, counted as owed; empty when
        the pacing is off."""
        if not self.on:
            return ""
        self.owed += 1
        return _CPR_QUERY

    def answered(self):
        """A reply came: the oldest query is answered."""
        _term.mark_answered()
        self.owed = max(0, self.owed - 1)

    def give_up(self):
        """The wait ran out.  A terminal that has never answered is not
        asked again."""
        if not _term.answered:
            self.on = False
        self.owed = 0


def _screen_escapes(mouse):
    """What a live loop writes to take the terminal -- the alternate
    screen, the cursor hidden, mouse reporting -- and what it writes to
    give it back, at its end and at ctrl-Z before it stops.

    The giving back begins with the end of a synchronized update: a
    frame cut short by a signal never sent its own _SYNC_END, and a
    terminal would hold the rest of the screen until the update timed
    out.
    """
    is_apple_terminal = os.environ.get('TERM_PROGRAM') == 'Apple_Terminal'
    bidi_on, bidi_off = bidi_modes()
    take = f"\033[?1049h\033[?25l{bidi_on}"
    give_back = _SYNC_END
    if mouse:
        # Both legacy and SGR mouse reporting, for broad compatibility.
        take += "\033[?1000h\033[?1002h\033[?1003h\033[?1006h"
        give_back += "\033[?1006l\033[?1003l\033[?1002l\033[?1000l"
        if is_apple_terminal:
            # Alternate-scroll mode, for a terminal that does not report
            # the wheel as mouse buttons.
            take += "\033[?1007h"
            give_back += "\033[?1007l"
    give_back += f"{_AUTOWRAP_ON}{bidi_off}\033[?25h\033[?1049l"
    return take, give_back


def live_loop(render_fn, interval=60, mouse=False, on_open=None, scroll_step=15,
              auto_play=False, play_interval=0.6, on_action=None, on_drag=None,
              intercept=None, play_gate=None, on_wheel=None, text_mode=None,
              on_click=None, help_panel=None, clamp_offset=None):
    """Run render_fn() in a loop on the alternate screen buffer.

    render_fn: callable(offset_minutes=0) returning (display_string, metadata)
               or just display_string.
               If mouse=True, also receives mouse_pos=(col, row) or None
               and active_alert=int_or_None.
               Scroll/arrow keys adjust offset_minutes to scrub through time.
    interval: seconds between refreshes, or a callable asked for them
              before each wait.
    mouse: if True, enable SGR mouse tracking and pass mouse_pos to render_fn.
    on_open: optional callback(alert_index) called when user presses 'o' on a modal.
    scroll_step: minutes to advance/retreat per scroll or arrow key event.
    clamp_offset: optional callable(offset_minutes) returning a bounded offset.
                  Applied to each time-scrub event, even in a coalesced burst,
                  and before rendering, so finite views cannot overscroll.
    auto_play: if True, run an animation loop instead of time-scrubbing.
               render_fn also receives play_frame (monotonic frame counter) and
               playing (bool). Space toggles play/pause — pausing homes
               play_frame to 0 (the caller's "home" frame, e.g. the present);
               scroll/arrows step one frame and pause in place; play_interval
               sets the frame rate.
    on_action: optional callback(key) for miscellaneous single-character keys
               not otherwise handled ('+', '-', 'c', 'w', …). Return a truthy
               value to trigger an immediate re-render; return falsy to leave
               the loop waiting as before. Default None preserves existing
               behavior exactly.
    on_drag: optional callback(dcol, drow, done) for left-button drags.
             Fired with the cumulative cell delta from the press position:
             during the drag with done=False (live preview) and once on
             release with done=True (commit). Return a truthy value to
             trigger an immediate re-render. Requires mouse. Default None
             preserves existing behavior exactly.
    play_gate: optional callable() consulted before each auto-play frame
               advance. Return falsy to hold the animation on the current
               frame (the loop still re-renders every play_interval, so the
               caller can animate a buffering indicator); return truthy to
               let playback proceed. Only consulted while auto_play is on
               and playing. Default None preserves existing behavior.
    intercept: optional callback(action) consulted for every decoded keyboard
               action ('fwd', 'quit', 'key:t', …; mouse events excluded)
               BEFORE the built-in handling. Return truthy to consume the
               action and trigger a re-render — this is how a caller-drawn
               menu takes over the arrow keys. Default None preserves
               existing behavior exactly.
    on_wheel: optional callback(direction, col, row) for mouse wheel
              events: +1 up / -1 down, and the pointer's 1-based terminal
              (col, row) — the same frame as mouse_pos — so the caller
              can zoom about the pointer rather than the view centre.
              When set it takes the wheel over entirely (no time-scrub,
              no frame-step, no modal scroll — the caller decides, e.g.
              zoom vs panel scroll). Return truthy to re-render; falsy
              leaves the frame alone (a clamped zoom). Return NotImplemented
              to use the loop's normal forecast/frame/modal scrolling.
              Default None preserves existing behavior exactly.
    text_mode: optional callable() -> bool consulted before each key read.
               While truthy, printable input arrives at intercept as
               'char:<c>' plus 'key:backspace'/'key:kill'/'key:enter' —
               the plumbing for a caller-drawn text field. Escape
               sequences (arrows, mouse) decode as usual. Default None
               preserves existing behavior exactly.
    on_click: optional callback(col, row) for a left click — a press
              and release on the same cell, in the same 1-based frame
              as mouse_pos. Fired on the release, before the zero-delta
              on_drag commit, so a drag is never also a click. Return
              truthy to re-render. Requires mouse and on_drag (the
              press is only tracked while a drag callback is set).
              Default None preserves existing behavior exactly.
    help_panel: optional terminal.help.HelpPanel for the view's controls.
                It owns `?` and input while open, without changing the
                view's state. Text fields still receive a literal
                question mark.
    Re-renders immediately on terminal resize or input.  A mouse_pos
    with no mouse input for _HOVER_IDLE_S seconds goes back to None.

    While idle, re-probes the terminal's colours now and then (see
    _theme.poll_interval / watch_path) and repaints when they change,
    so switching the terminal theme re-inks the view in place.
    """
    _LiveLoop(render_fn, interval=interval, mouse=mouse, scroll_step=scroll_step,
              clamp_offset=clamp_offset, auto_play=auto_play,
              play_interval=play_interval, play_gate=play_gate,
              help_panel=help_panel, on_open=on_open, on_action=on_action,
              on_drag=on_drag, on_click=on_click, on_wheel=on_wheel,
              intercept=intercept, text_mode=text_mode).run()


class _LiveLoop:
    """One run of live_loop: the state a frame is rendered from, the
    handlers that change it, and the terminal it is drawn on.

    The settings and hooks are live_loop's arguments, kept as they came.
    """

    def __init__(self, render_fn, *, interval, mouse, scroll_step, clamp_offset,
                 auto_play, play_interval, play_gate, help_panel, on_open,
                 on_action, on_drag, on_click, on_wheel, intercept, text_mode):
        self.render_fn = render_fn
        self.interval = interval
        self.mouse = mouse
        self.scroll_step = scroll_step
        self.clamp_offset = clamp_offset
        self.auto_play = auto_play
        self.play_interval = play_interval
        self.play_gate = play_gate
        self.help_panel = help_panel
        self.on_open = on_open
        self.on_action = on_action
        self.on_drag = on_drag
        self.on_click = on_click
        self.on_wheel = on_wheel
        self.intercept = intercept
        self.text_mode = text_mode

        self.offset = 0
        self.playing = auto_play
        self.play_frame = 0
        self.mouse_pos = None
        self.hover_until = 0.0    # monotonic time mouse_pos is forgotten
        self.drag_start = None    # (col, row) of left-button press while on_drag is set
        self.drag_delta = (0, 0)  # last displayed drag, to finish before opening help
        self.active_alert = None  # index of alert whose modal is open, or None
        self.modal_scroll = 0     # scroll offset within the modal
        self.alert_row_map = {}   # 0-based line index → [(first col, last col, alert index)]

        self.theme = self.term = self.pacing = None
        self.init = self.restore = ""

    def run(self):
        """Take the terminal, paint frames until the view quits, and give
        the terminal back however the loop ends."""
        global _running
        # Before the terminal is taken: the theme's import probes it, the
        # first time.
        self.theme = _ThemeSchedule()
        # Cbreak input, the wakeup nudge() pulls, and resize notice — a self-pipe
        # and SIGWINCH on POSIX, console modes and a poll on Windows.
        self.term = _term.LiveTerminal(sys.stdin.fileno())
        self.term.install()
        self.pacing = _Pacing()
        self.init, self.restore = _screen_escapes(self.mouse)

        watch = WorkerWatch()
        watch.install()
        try:
            _running = True
            self._take()
            while True:
                if self._hold() == 'quit':
                    return
                if self.term.suspend_pending:
                    self._suspend()
                self._paint()
                if self._idle() == 'quit':
                    return
        except KeyboardInterrupt:
            pass
        # SystemExit is NOT swallowed: a sys.exit(1) from a render callback (or
        # a signal handler in terminal.term) must reach the shell as a nonzero
        # status.  The finally block still restores the terminal on its way out.
        finally:
            _running = False
            self._give_back()
            watch.uninstall()
            watch.report()

    def _take(self):
        """Put the terminal in cbreak and switch to the alternate screen."""
        # Cbreak first, then the escapes: on Windows, switching stdin to
        # VT input resets the terminal's mouse tracking, so enables sent
        # beforehand are silently dropped.  Order is moot on POSIX.
        self.term.set_cbreak()
        sys.stdout.write(self.init)
        sys.stdout.flush()

    def _hold(self):
        """Hold the next frame until the terminal has read the last one
        (_Pacing); 'quit' if input during the hold quit the view.

        Keys and wheel notches that arrive meanwhile change the state the
        frame is rendered from; a wakeup or a timer tick is absorbed the
        same way, since a repaint is coming.  Ctrl-Z ends the hold."""
        term, pacing = self.term, self.pacing
        if not (pacing.on and pacing.owed):
            return None
        until = _time.monotonic() + pacing.wait_s()
        while pacing.owed:
            left = until - _time.monotonic()
            if left <= 0:
                pacing.give_up()
                break
            event = term.wait(min(0.1, left))
            if term.suspend_pending:
                break
            if event == 'input':
                if self._on_input() == 'quit':
                    return 'quit'
        return None

    def _suspend(self):
        """Ctrl-Z: hand the terminal back as the loop's end does, stop,
        and on resume take it again.  The frame drawn next is drawn
        whole, as every frame is."""
        term, pacing = self.term, self.pacing

        def hand_back():
            # Alone in its job, the loop waits for the terminal to answer,
            # so no reply or late mouse report reaches the shell.  Under a
            # wrapper the shell may be reading the terminal already, and
            # the answer would land on its prompt: drop what has come in
            careful = pacing.on and term.leads_job()
            sys.stdout.write(self.restore + (_CPR_QUERY if careful else ""))
            sys.stdout.flush()
            term.settle(pacing.wait_s() if careful else 0, replies=pacing.owed + 1)

        term.suspend(hand_back)
        pacing.owed = 0
        sys.stdout.write(self.init)
        sys.stdout.flush()

    def _paint(self):
        """Render the frame from the state as it stands, and write it."""
        # Drain wakeups from before this render: whatever they announced,
        # the frame about to be drawn reflects it.  The drain must come
        # BEFORE render_fn, never after — a background fetch can finish
        # (and nudge the pipe) while the render is still composing its
        # "loading" frame, and a drain after the paint would swallow that
        # completion, leaving the loading frame up until the next input.
        self.term.drain()
        kwargs = {}
        if self.mouse:
            kwargs.update(mouse_pos=self.mouse_pos, active_alert=self.active_alert,
                          modal_scroll=self.modal_scroll)
        if self.auto_play:
            kwargs.update(play_frame=self.play_frame, playing=self.playing)
        if self.clamp_offset is not None:
            self.offset = self.clamp_offset(self.offset)
        result = self.render_fn(offset_minutes=self.offset, **kwargs)
        # render_fn may return (output, metadata) or just output
        if isinstance(result, tuple):
            output, self.alert_row_map = result
        else:
            output = result
            self.alert_row_map = {}
        # Separate the cursor-positioned overlay from the body (the
        # \x00 delimiter overlay() writes)
        body, _, floating = output.partition('\x00')
        help_panel = self.help_panel
        if help_panel is not None and help_panel.open:
            from linecast.terminal.framebuffer import get_terminal_size
            floating = "\033[?1003l" + help_panel.render(*get_terminal_size())
        elif help_panel is not None and self.mouse:
            # A search field may intentionally disable motion; only
            # restore it when the caller's overlay has not done so.
            if "\033[?1003l" not in floating:
                floating = "\033[?1003h" + floating
        sys.stdout.write(frame_paint(body, floating) + self.pacing.ask())
        sys.stdout.flush()

    def _idle(self):
        """Wait for the next frame to be due: input that changes the
        view, a wakeup or a resize, the interval running out, or the
        hover chip's time.  The theme is looked at as its schedule says
        meanwhile.  'quit' if input quit the view."""
        term, theme = self.term, self.theme
        interval = self.interval
        wait = (self.play_interval if (self.auto_play and self.playing)
                else interval() if callable(interval) else interval)
        deadline = _time.time() + wait
        owed = False   # a coalesced input is waiting for its repaint
        while True:
            # A repaint held back for more input is due once the input
            # has run out.  It cannot wait for the last of that input
            # to ask: that is often the terminal's reply to the frame
            # before, and a reply changes nothing on screen.
            if owed and not _term.wait_readable(term.fd, 0):
                return None
            remaining = deadline - _time.time()
            if remaining <= 0:
                if self.auto_play and self.playing and (
                        self.play_gate is None or self.play_gate()):
                    self.play_frame += 1  # advance the animation
                return None
            now = _time.monotonic()
            if self.mouse_pos is not None and self.drag_start is None:
                if now >= self.hover_until:
                    self.mouse_pos = None  # the mouse has been still: drop the chip
                    return None
                remaining = min(remaining, self.hover_until - now)
            event = term.wait(max(0.0, min(remaining, theme.due - now)))
            if event == 'wake':
                return None
            if event == 'timeout':
                theme.look()
                continue
            if event == 'input':
                verdict = self._on_input()
                if verdict == 'quit':
                    return 'quit'
                if verdict == 'repaint':
                    return None
                if verdict == 'coalesce':
                    owed = True

    def _give_back(self):
        """Hand the terminal back to the shell, at the loop's end."""
        term, pacing = self.term, self.pacing
        try:
            sys.stdout.write(self.restore + (_CPR_QUERY if pacing.on else ""))
            sys.stdout.flush()
        except Exception:
            pass  # tty may already be gone (SIGHUP); nothing left to restore
        # What the terminal was still sending -- a colour probe's replies,
        # mouse reports from before it read the escape above -- is read
        # and dropped, up to its reply to the query, so none of it reaches
        # the shell.  A frame whose reply was still owed when the loop
        # ended is answered first, so the drain waits for one reply more
        # than that.  Then the terminal settings, the signal handlers and
        # the wakeup channel go back, in that order (terminal.term.LiveTerminal).
        # The drain waits on the terminal, and a second ctrl-C or SIGTERM
        # meanwhile raises through this block: close() runs regardless,
        # or the shell would inherit the tty in cbreak.
        try:
            term.settle(pacing.wait_s() if pacing.on else 0, replies=pacing.owed + 1)
        except Exception:
            pass
        finally:
            term.close()

    def _coalesce_or_repaint(self):
        """The verdict for input that changed the frame: paint now, or
        hold the paint while more input is waiting."""
        return 'coalesce' if _term.wait_readable(self.term.fd, 0) else 'repaint'

    def _scrub(self, step):
        """An arrow or a wheel notch, `step` +1 forward or -1 back: a
        frame of the animation, which pauses it, or scroll_step minutes
        of time."""
        if self.auto_play:
            self.playing = False
            self.play_frame += step
        else:
            if self.clamp_offset is not None:
                self.offset = self.clamp_offset(self.offset)
            self.offset += step * self.scroll_step
            if self.clamp_offset is not None:
                self.offset = self.clamp_offset(self.offset)

    def _on_input(self):
        """Read one key or mouse event and apply it.

        'quit' to leave the loop, 'repaint' when the frame should be drawn
        again, 'coalesce' when it should but more input is already waiting
        -- so a burst of scrolling paints once at its end -- and None when
        nothing on screen changed.  The caller owes a repaint after a
        'coalesce' whatever the later input says: the bytes waiting may
        be the terminal's reply to the last frame, which changes nothing.

        The terminal's replies are taken first, then the help panel has
        the input while it is open; the rest goes to _on_key or, for the
        mouse, _on_mouse.
        """
        from linecast.terminal.keys import read_key
        help_panel = self.help_panel
        action = read_key(self.term.fd,
                          text=bool(self.text_mode is not None and self.text_mode()))
        if isinstance(action, tuple) and action[0] == 'mouse' and _bidi.mirrored():
            # The view laid this frame out from the left and the pass
            # drew it from the right: the pointer goes back the same way
            from linecast.terminal.framebuffer import get_terminal_size
            _, cb, cx, cy, is_rel = action
            action = ('mouse', cb, get_terminal_size()[0] + 1 - cx, cy, is_rel)
        if isinstance(action, tuple) and action[0] == 'mouse':
            self.hover_until = _time.monotonic() + _HOVER_IDLE_S
        if action == 'ack':
            self.pacing.answered()
            return None
        if action == 'theme':
            return 'repaint'  # the terminal's colours changed
        help_closed = False
        if help_panel is not None:
            was_helping = help_panel.open
            if help_panel.handle(action):
                if not was_helping and help_panel.open and self.drag_start is not None:
                    self.on_drag(*self.drag_delta, True)
                self.drag_start = None
                return 'repaint'
            # A key the panel does not take closes it and goes on
            help_closed = was_helping and not help_panel.open
        if isinstance(action, tuple):
            verdict = self._on_mouse(*action[1:]) if self.mouse else None
        else:
            verdict = self._on_key(action)
        if verdict is None and help_closed:
            return 'repaint'  # even an unbound key must erase the panel
        return verdict

    def _on_key(self, action):
        """A key (or None, for bytes that are none): the view's intercept
        first, then the loop's own -- q, the modal's o, the arrows, space
        -- then the view's on_action."""
        if (self.intercept is not None and action is not None
                and self.intercept(action)):
            return 'repaint'
        if action == 'quit':
            # q closes the alert modal before it quits.  Esc does not:
            # the modal opens only with mouse tracking on, and then a bare
            # ESC is almost always a mouse report split in two.
            if self.active_alert is not None:
                self.active_alert = None
                self.modal_scroll = 0
                return 'repaint'
            return 'quit'
        elif action == 'open':
            if self.active_alert is not None and self.on_open:
                self.on_open(self.active_alert)
                return 'repaint'
        elif action in ('fwd', 'back'):
            self._scrub(1 if action == 'fwd' else -1)
            return self._coalesce_or_repaint()  # rapid scrolling
        elif action == 'reset':
            if self.auto_play:
                self.playing = not self.playing  # space = play/pause
                if not self.playing:
                    self.play_frame = 0  # pause returns to the home frame
            else:
                self.offset = 0
            return 'repaint'
        elif (self.on_action is not None and isinstance(action, str)
              and action.startswith('key:')):
            if self.on_action(action[4:]):
                return self._coalesce_or_repaint()  # held-down keys (zoom taps)
        return None

    def _on_mouse(self, cb, cx, cy, is_rel):
        """A mouse report: button code `cb`, the pointer's 1-based
        (cx, cy), and whether a button was released."""
        from linecast.terminal.keys import wheel_code
        wheel_cb = wheel_code(cb)
        if wheel_cb in (64, 65):
            return self._on_wheel(1 if wheel_cb == 64 else -1, cx, cy)
        if is_rel:
            return self._on_release(cx, cy)
        if (cb & 0b11) == 0 and not (cb & 0x20):
            # Left button press (not release, not motion)
            verdict = self._on_press(cx, cy)
            if verdict is not None:
                return verdict
        if cb & 32:
            return self._on_motion(cx, cy)
        # Fallback for terminals without motion reporting:
        # update pointer on press so tooltip can still appear.
        if (cb & 0b11) in (0, 1, 2):
            self.mouse_pos = (cx, cy)
            return 'repaint'
        return None

    def _on_wheel(self, direction, cx, cy):
        """A wheel notch, +1 up or -1 down: the view's on_wheel, unless it
        defers; else the open modal scrolls, or time (or the animation)
        does."""
        if self.on_wheel is not None:
            # A view can own the wheel, or defer to ordinary scrolling
            # when its panel is closed.
            handled = self.on_wheel(direction, cx, cy)
            if handled is not NotImplemented:
                return self._coalesce_or_repaint() if handled else None
        if self.active_alert is not None:
            # Scroll the modal: down reads on
            self.modal_scroll = max(0, self.modal_scroll - 3 * direction)
        else:
            self._scrub(direction)
        return self._coalesce_or_repaint()  # rapid scrolling

    def _on_release(self, cx, cy):
        """A button released: the end of a drag gesture, and a click if
        it ended where it began; nothing if no drag started."""
        if self.drag_start is None:
            return None
        dcol, drow = cx - self.drag_start[0], cy - self.drag_start[1]
        self.drag_start = None
        clicked = (dcol == 0 and drow == 0
                   and self.on_click is not None
                   and self.on_click(cx, cy))
        if self.on_drag(dcol, drow, True) or clicked:
            return 'repaint'
        return None

    def _on_press(self, cx, cy):
        """The left button pressed: where a drag starts, if the view takes
        drags, and a click on the alert modal, which dismisses it, or on
        an alert, which opens it.  None when the press is only the
        pointer's (see _on_mouse)."""
        if self.on_drag is not None:
            self.drag_start = (cx, cy)
            self.drag_delta = (0, 0)
        row_idx = cy - 1  # 1-based → 0-based
        if self.active_alert is not None:
            # Click while modal open — dismiss
            self.active_alert = None
            self.modal_scroll = 0
            return 'repaint'
        elif row_idx in self.alert_row_map:
            spans = self.alert_row_map[row_idx]
            col_idx = cx - 1  # 1-based → 0-based
            self.active_alert = next(
                (i for start, end, i in spans
                 if start <= col_idx <= end),
                spans[0][2])
            self.modal_scroll = 0
            return 'repaint'
        return None

    def _on_motion(self, cx, cy):
        """The pointer moved: a drag's live preview while a button is
        held, else the hover chip follows it."""
        if self.drag_start is not None:
            # mid-drag: live preview with cumulative delta
            dcol, drow = cx - self.drag_start[0], cy - self.drag_start[1]
            self.drag_delta = (dcol, drow)
            if self.on_drag(dcol, drow, False):
                return self._coalesce_or_repaint()  # rapid drag motion
            return None
        # Hover-capable terminals: render once at the final position.
        self.mouse_pos = (cx, cy)
        return self._coalesce_or_repaint()


# ---------------------------------------------------------------------------
# Live apps
# ---------------------------------------------------------------------------
class LiveApp:
    """What a live view is made of: state, the hooks that change it, and
    one render per repaint.

    live_loop's keyword hooks are methods here, with the same contracts
    (see live_loop's docstring for each); the loop's tuning is the class
    attributes below, overridden per app.  A hook a subclass leaves
    alone is not handed to the loop at all, so the loop's own defaults
    hold exactly as they do for a bare render callback: without
    on_wheel the wheel scrubs time, without on_drag the press is not
    tracked and there are no clicks.  `run()` puts the app on screen
    and calls `stop()` on the way out, however the loop ends.

    An app whose whole state is a render function can still call
    live_loop directly; this is for the ones with keys.
    """

    interval = 60        # seconds between idle repaints
    mouse = True         # SGR mouse tracking; the frame gets mouse_pos
    scroll_step = 15     # minutes per wheel notch or arrow, when scrubbing
    auto_play = False    # an animation loop rather than a time scrub
    play_interval = 0.6  # seconds per frame while playing

    HOOKS = ("on_action", "on_drag", "on_wheel", "intercept", "on_click",
             "on_open", "play_gate", "text_mode", "clamp_offset")

    def clamp_offset(self, offset_minutes):
        """Bound time scrubbing to the view's available data."""
        return offset_minutes

    def render(self, **frame):
        """The frame: a string, or (string, alert_row_map).

        `frame` is what live_loop knows about the moment — offset_minutes,
        mouse_pos, active_alert, modal_scroll, and play_frame/playing when
        auto_play is on.  Take what the view uses and swallow the rest.
        """
        raise NotImplementedError

    def on_action(self, key):
        """A single-character key ('+', 'c', …); truthy repaints."""
        return False

    def on_drag(self, dcol, drow, done):
        """A left-button drag, as the cumulative cell delta; truthy repaints."""
        return False

    def on_wheel(self, direction, col, row):
        """The wheel: +1 up / -1 down. NotImplemented defers to loop scrolling."""
        return False

    def intercept(self, action):
        """Every decoded key before the loop's own handling; truthy
        consumes it and repaints — how a panel takes the arrows."""
        return False

    def on_click(self, col, row):
        """A press and release on one cell; truthy repaints."""
        return False

    def on_open(self, index):
        """`o` with alert `index`'s modal open."""

    def play_gate(self):
        """Whether auto-play may advance a frame."""
        return True

    def text_mode(self):
        """Whether a text field is open: printable keys arrive at
        intercept as 'char:<c>' while it is."""
        return False

    def stop(self):
        """The loop is over; park any thread that was serving it."""

    _flash = None  # (paragraphs, deadline, busy) while a note is up
    _flash_timer = None

    def clear_flash(self):
        """Dismiss a note and cancel its next repaint."""
        self._flash = None
        if self._flash_timer is not None:
            self._flash_timer.cancel()
            self._flash_timer = None

    def _flash_repaint(self, seconds):
        if self._flash_timer is not None:
            return

        def repaint():
            if self._flash_timer is timer:
                # Clear before waking: the next render may start immediately.
                self._flash_timer = None
                nudge()

        timer = threading.Timer(seconds, repaint)
        timer.daemon = True
        self._flash_timer = timer
        timer.start()

    def flash(self, paragraphs, seconds=3.0, *, busy=False):
        """Float a brief note, or an animated toast until clear_flash().

        A busy toast stays above the view without moving its rows. Its
        timer only wakes the live loop; all painting belongs to the loop.
        """
        self.clear_flash()
        self._flash = (list(paragraphs), _time.monotonic() + seconds, busy)
        self._flash_repaint(0.08 if busy else seconds + 0.05)

    def busy_toast(self, text, cols, rows, after=0.0):
        """The animated toast for work under way, on overlay()'s floating
        channel.  It asks for its own next frame, so it turns for as long
        as each frame asks for it again, and a view that stops asking
        has nothing to dismiss.  *after* is how long the toast is still
        to be held back: work that is over by then never shows one.
        """
        if after > 0:
            self._flash_repaint(after)
            return ""
        from linecast.terminal.spinner import SPINNER_FRAMES
        spinner = SPINNER_FRAMES[int(_time.monotonic() / 0.08) % len(SPINNER_FRAMES)]
        self._flash_repaint(0.08)
        return toast_box(text, cols, rows, icon=spinner)

    def flash_overlay(self, cols, rows):
        """The current note on overlay()'s floating channel."""
        if self._flash is None:
            return ""
        paragraphs, deadline, busy = self._flash
        if busy:
            return self.busy_toast(' '.join(paragraphs), cols, rows)
        if _time.monotonic() >= deadline:
            self.clear_flash()
            return ""
        from linecast.terminal.color import fg
        from linecast.terminal.help import wrap
        width = max(10, min(cols - 6, 64))
        lines = []
        for text in paragraphs:
            lines += [f" {line}" for line in wrap(text, width)]
        return menu_box(lines, cols, rows, border=fg(*MUTED))

    def hooks(self):
        """The hooks this app overrides, as live_loop keyword arguments.
        An app that takes clicks and no drags is handed a drag that does
        nothing: the loop tells a click by the press and the release,
        which it tracks only for an app with on_drag."""
        hooks = {name: getattr(self, name) for name in self.HOOKS
                 if getattr(type(self), name) is not getattr(LiveApp, name)}
        if "on_click" in hooks and "on_drag" not in hooks:
            hooks["on_drag"] = lambda dcol, drow, done: False
        return hooks

    # The help panel: the view's keys (terminal/help.CONTROLS[help_view]),
    # after help_rows and before help_credits.  help_view is read each
    # time the panel is drawn, so a view that switches, as weather's year
    # view does, makes it a property.
    help_view = None

    def help_rows(self):
        """Rows placed before the view's own keys."""
        return []

    def help_credits(self):
        """The data credits listed under the keys."""
        return ()

    def help_panel(self):
        from linecast.terminal.help import HelpPanel, entries
        if not self.help_view:
            return None
        lang = self.runtime.lang
        return HelpPanel(self.help_view, lang, content=lambda cols, rows:
                         self.help_rows() + entries(self.help_view, lang,
                                                    credits=self.help_credits()))

    def run(self):
        """Run the app on the alternate screen until it quits."""
        from linecast.terminal.textwidth import calibrate_from_terminal
        calibrate_from_terminal()
        try:
            live_loop(self.render, interval=self.interval, mouse=self.mouse,
                      scroll_step=self.scroll_step, auto_play=self.auto_play,
                      play_interval=self.play_interval, help_panel=self.help_panel(),
                      **self.hooks())
        finally:
            self.clear_flash()
            self.stop()
