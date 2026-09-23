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
- Mouse wheel scrubbing (SGR and legacy X10/VT200 encoding)
- Alert modal interaction (click to open, scroll to read, q/click to dismiss)

Mouse protocol references:
  - SGR (1006): https://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h3-Extended-coordinates
  - Legacy X10:  https://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h3-Normal-tracking-mode
"""

import os
import sys
import threading
import time as _time

from linecast import _bidi, _term


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
# terminal has read the frame (see live_loop), and how long the next
# frame waits for it: long enough for a terminal that is genuinely
# behind, and not long on a terminal that has yet to answer at all.
_CPR_QUERY = _term.CPR_QUERY.decode("ascii")
_ACK_WAIT_S = 1.0
_ACK_FIRST_WAIT_S = 0.25

# A hover chip goes once the mouse has been still this long, as though the
# pointer had left the window: a view left open on the desk should not
# keep a chip up because the pointer came to rest over it.
_HOVER_IDLE_S = 7.0


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
    fills the screen the row after the last is the last, which the
    clear empties and the body then draws.
    """
    rows = body.count("\n") + 1
    width = _mirror_width()
    body, floating = _bidi.display(body, width), _bidi.display(floating, width)
    return (f"{_SYNC_BEGIN}{_AUTOWRAP_OFF}\033[{rows + 1};1H\033[J{frame_body(body)}"
            f"\033[0m{floating}\033[0m{_AUTOWRAP_ON}{_SYNC_END}")


def _mirror_width():
    """The terminal's width when the view on screen is laid out from the
    right (a right-to-left language), for _bidi.display; else None."""
    if not _bidi.mirrored():
        return None
    from linecast._framebuffer import get_terminal_size
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
    comes back untouched.
    """
    switch = "" if motion is None else ("\033[?1003h" if motion
                                        else "\033[?1003l")
    if not floating and not switch:
        return body
    return f"{body}\x00{switch}{floating}"


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
    if not lines:
        return ""
    from linecast._graphics import RESET, visible_len
    width = max(visible_len(line) for line in lines)
    padded = [f"{line}{pad_bg}{' ' * (width - visible_len(line))}{RESET}"
              for line in lines]
    height = len(padded)
    row = mouse_row + 2
    if row + height - 1 > rows:
        row = mouse_row - height
    if row < 1:
        row = max(1, rows - height + 1)
    if col + width - 1 > cols:
        col = max(1, (cols - width + 1) if flip_at is None else flip_at - width)
    return "".join(f"\033[{row + i};{col}H{line}"
                   for i, line in enumerate(padded))


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
    from linecast._graphics import RESET, visible_len
    widths = [visible_len(line) for line in lines if line is not None]
    inner = max(0, min(cols - 4, (max(widths) if widths else 0) + 1))
    top = max(1, (rows - (len(lines) + 2)) // 2)
    left = max(0, (cols - inner - 2) // 2)
    head = f" {title} ".center(inner, "─") if title else "─" * inner
    foot = "─" * inner
    above, below = more
    if above:
        head = head[:inner - 2] + "▲" + head[inner - 1:]
    if below:
        foot = foot[:inner - 2] + "▼" + foot[inner - 1:]
    out = [f"┌{head}┐"]
    for i, line in enumerate(lines):
        if line is None:
            out.append(f"├{'─' * inner}┤")
            continue
        while line and visible_len(line) > inner:
            line = line[:-1]
        body = line + " " * (inner - visible_len(line))
        if i == sel:
            body = f"\033[7m{body}\033[27m"  # reverse-video highlight
        out.append(f"│{body}│")
    out.append(f"└{foot}┘")
    return "".join(
        f"\033[{top + 1 + i};{left + 1}H{border}{fill}{line}{RESET}"
        for i, line in enumerate(out))


def toast_box(text, cols, rows, icon=""):
    """A compact, rounded notification above the bottom-right of the view."""
    from linecast import _theme
    from linecast._graphics import RESET, bg, fg, visible_len
    from linecast._help import fit
    if cols < 1 or rows < 1:
        return ""
    surface = _theme.surface_bg(0.10)
    ink = fg(*_theme.ensure_contrast(_theme.theme_fg, surface, 4.5))
    border = fg(*_theme.ensure_contrast(_theme.surface_bg(0.55), surface, 2.2))
    fill = bg(*surface)
    label = f"{icon} {text}" if icon else text
    if cols < 8 or rows < 4:
        # A tiny terminal still gets the spinner, without an overflowing box.
        return f"\033[{rows};1H{fill}{ink}{fit(label, cols)}{RESET}"
    label = fit(label, min(60, cols - 8))
    inner = visible_len(label) + 2
    left, top = cols - inner - 3, rows - 3
    lines = [f"{border}╭{'─' * inner}╮",
             f"{border}│{ink} {label} {border}│",
             f"{border}╰{'─' * inner}╯"]
    return ''.join(f"\033[{top + i};{left}H{fill}{line}{RESET}"
                   for i, line in enumerate(lines))


# ---------------------------------------------------------------------------
# Mouse decoding
# ---------------------------------------------------------------------------
def _decode_sgr_mouse(seq):
    """Decode an SGR mouse sequence payload like b'<64;10;20M'.

    SGR encoding (mode 1006) sends: CSI < Cb ; Cx ; Cy M/m
    where M = press, m = release.
    """
    if not seq.startswith(b'<') or seq[-1:] not in (b'M', b'm'):
        return None
    try:
        parts = seq[1:-1].decode("ascii").split(";")
        cb, cx, cy = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError, UnicodeDecodeError):
        return None
    # A motion report is never a release, whatever terminator was used:
    # xterm ends motion with 'M', Windows Terminal ends button-less motion
    # with 'm'.  The motion bit (0x20) settles it on both.
    is_rel = seq[-1:] == b'm' and not (cb & 0x20)
    return ('mouse', cb, cx, cy, is_rel)


def _decode_legacy_mouse(payload):
    """Decode legacy X10/VT200 mouse payload bytes (Cb, Cx, Cy).

    Legacy encoding sends: CSI M Cb Cx Cy
    where each byte is the value + 32 (to avoid control characters).
    """
    if len(payload) != 3:
        return None
    cb = payload[0] - 32
    cx = payload[1] - 32
    cy = payload[2] - 32
    if cb < 0 or cx < 1 or cy < 1:
        return None
    is_rel = (cb & 0b11) == 0b11 and not (cb & 0x40) and not (cb & 0x20)
    return ('mouse', cb, cx, cy, is_rel)


def _normalize_wheel_cb(cb):
    """Return canonical wheel code 64 (up) / 65 (down), or None.

    Wheel events set bit 6 (0x40). The low two bits encode direction:
    0 = scroll up, 1 = scroll down. Modifier keys (shift/ctrl/meta) set
    bits 2–4 but don't change the direction, so we mask them off.
    """
    if not (cb & 0x40):
        return None
    base = cb & 0b11
    if base in (0, 1):
        return 64 + base
    return None


def _arrow(final):
    """An arrow key's action: up and right go forward, down and left
    back -- left and right the other way round in a view laid out from
    the right, where time runs leftward."""
    if _bidi.mirrored():
        return {b'A': 'fwd', b'B': 'back', b'C': 'back', b'D': 'fwd'}.get(final)
    return {b'A': 'fwd', b'B': 'back', b'C': 'fwd', b'D': 'back'}.get(final)


def _read_key(fd, text=False):
    """Read a keypress from stdin in cbreak mode. Returns action string or None.

    Fully consumes CSI/SS3 escape sequences so leftover bytes don't leak.
    Uses a longer timeout (150ms) to avoid splitting mouse escape sequences
    when the system is busy (e.g. after a re-render).

    With text=True (a caller-drawn input field is open), printable input
    comes back as 'char:<c>' — including multi-byte UTF-8, assembled from
    continuation bytes — plus 'key:backspace' / 'key:kill' (ctrl-U) /
    'key:enter' for editing. Escape sequences (arrows, mouse) decode
    exactly as before, so list navigation keeps working while typing.

    Without it, a letter typed under a non-Latin layout acts as the Latin
    key it sits on (see _keylayouts): Persian ض and Russian й are q.
    """
    def _read_byte():
        return _term.read_byte(fd)

    def _read_byte_timeout(timeout=0.15):
        if _term.wait_readable(fd, timeout):
            return _term.read_byte(fd)
        return None

    def _read_utf8(lead):
        """The character a UTF-8 lead byte starts, or None if it is broken."""
        o = lead[0]
        if 0xC0 <= o < 0xE0:
            extra = 1
        elif 0xE0 <= o < 0xF0:
            extra = 2
        elif 0xF0 <= o < 0xF8:
            extra = 3
        else:
            return None  # stray continuation byte or invalid lead
        buf = bytearray(lead)
        for _ in range(extra):
            c = _read_byte_timeout(0.05)
            if c is None:
                return None
            buf.extend(c)
        try:
            return buf.decode('utf-8')
        except UnicodeDecodeError:
            return None

    b = _read_byte()
    if b is None:
        return None

    if b == b'\033':
        # Use 150ms timeout — 50ms is too short when the system is busy
        # rendering; mouse release sequences (\033[<0;x;ym) can arrive late
        # and the \033 gets read as a bare ESC.
        b2 = _read_byte_timeout(0.15)
        if b2 is None:
            return 'escape'

        if b2 == b']':
            # An OSC reply to the live loop's theme probe, e.g.
            # \033]11;rgb:1e/1e/2e\007 (or ST-terminated).  Consume it
            # whole and hand the body to the theme; it is never a key.
            body = bytearray()
            while True:
                c = _read_byte_timeout(0.15)
                if c is None:
                    return None
                if c == b'\x07':
                    break
                if c == b'\033':
                    _read_byte_timeout(0.05)  # the backslash of ST
                    break
                body.extend(c)
                if len(body) > 256:
                    return None
            from linecast import _theme
            return 'theme' if _theme.ingest_osc(bytes(body)) else None

        if b2 == b'[':
            seq = bytearray()
            while True:
                c = _read_byte_timeout(0.15)
                if c is None:
                    break
                seq.extend(c)
                # Legacy mouse: \033[M Cb Cx Cy
                if c == b'M' and len(seq) == 1:
                    tail = bytearray()
                    for _ in range(3):
                        c_tail = _read_byte_timeout(0.15)
                        if c_tail is None:
                            return None
                        tail.extend(c_tail)
                    return _decode_legacy_mouse(bytes(tail))
                c0 = c[0]
                if (65 <= c0 <= 90) or (97 <= c0 <= 122) or c0 == 126:
                    break

            action = _decode_sgr_mouse(bytes(seq))
            if action is not None:
                return action

            final = bytes(seq[-1:]) if seq else b''
            if final == b'R' and seq[:1].isdigit():
                # A cursor position report: the terminal has reached the
                # query the loop sent after its last frame (or a probe's).
                return 'ack'
            return _arrow(final)

        if b2 == b'O':
            # SS3 sequence (some terminals use for arrows)
            b3 = _read_byte_timeout(0.15)
            if b3 is not None:
                return _arrow(b3)
        return 'escape'

    # On Windows cbreak turns off the console's own Ctrl-C handling, so
    # the keystroke arrives as ETX instead of a KeyboardInterrupt. It is
    # read ahead of the text field, where `q` is a letter and Ctrl-C is
    # the only quit there is.
    if b == b'\x03':
        return 'quit'

    if text:
        # Free-text capture: editing keys first, then any printable
        # character (assembling UTF-8 continuations), control bytes dropped.
        if b in (b'\x7f', b'\x08'):
            return 'key:backspace'
        if b in (b'\r', b'\n'):
            return 'key:enter'
        if b == b'\x15':  # ctrl-U
            return 'key:kill'
        o = b[0]
        if o < 0x20:
            return None
        if o < 0x80:
            return 'char:' + chr(o)
        ch = _read_utf8(b)
        return 'char:' + ch if ch is not None else None

    if b[0] >= 0x80:
        # A letter from a non-Latin layout (ض, й, ㅂ): read it as the
        # Latin key it sits on, so q still quits under Persian or Russian.
        from linecast._keylayouts import latin_key
        ch = _read_utf8(b)
        latin = latin_key(ch) if ch is not None else None
        if latin is None:
            return None
        b = latin.encode()

    if b in (b'q', b'Q'):
        return 'quit'
    if b in (b'o', b'O'):
        return 'open'
    if b in (b'n', b'N', b' '):
        return 'reset'
    if b in (b'+', b'='):
        return 'key:+'
    if b.isdigit():
        return 'key:' + b.decode()
    if b in (b'-', b'_'):
        return 'key:-'
    if b in (b't', b'T'):
        return 'key:t'
    if b in (b'c', b'C'):
        return 'key:c'
    # Lowercase WASD pans; shifted keys retain the displaced view actions.
    if b in (b'w', b'a', b's', b'd', b'W', b'S', b'D'):
        return 'key:' + b.decode()
    if b in (b'v', b'V'):
        return 'key:v'
    if b in (b'p', b'P'):
        return 'key:p'
    if b in (b'l', b'L'):
        return 'key:l'
    if b in (b'm', b'M'):
        return 'key:m'
    if b in (b'y', b'Y'):
        return 'key:y'
    if b in (b'r', b'R'):
        return 'key:r'
    if b == b'/':
        return 'key:/'
    if b == b'?':
        return 'key:?'
    if b in (b'\r', b'\n'):
        return 'key:enter'
    return None


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
            from linecast._runtime import log_failure
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
        from linecast._runtime import debug_enabled
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
    help_panel: optional _help.HelpPanel for the view's controls. It owns
                `?` and input while open, without changing the view's state.
                Text fields still receive a literal question mark.
    Re-renders immediately on terminal resize or input.  A mouse_pos
    with no mouse input for _HOVER_IDLE_S seconds goes back to None.

    While idle, re-probes the terminal's colours now and then (see
    _theme.poll_interval / watch_path) and repaints when they change,
    so switching the terminal theme re-inks the view in place.
    """
    global _running
    from linecast import _theme

    # Cbreak input, the wakeup nudge() pulls, and resize notice — a self-pipe
    # and SIGWINCH on POSIX, console modes and a poll on Windows.
    term = _term.LiveTerminal(sys.stdin.fileno())
    term.install()

    is_apple_terminal = os.environ.get('TERM_PROGRAM') == 'Apple_Terminal'

    fd = term.fd

    def _mtime(path):
        try:
            return os.stat(path).st_mtime_ns
        except OSError:
            return None

    theme_poll = _theme.poll_interval()
    theme_watch = _theme.watch_path()
    theme_watch_mtime = _mtime(theme_watch) if theme_watch else None
    next_probe = _time.monotonic() + theme_poll
    burst_until = 0.0   # after the watch file changes, probe briskly for a
                        # few seconds: the terminal may get its colours a
                        # beat after the marker file is written

    def _maybe_probe():
        nonlocal theme_watch_mtime, next_probe, burst_until
        if not _theme.can_reprobe() or _theme.probe_pending():
            return
        now = _time.monotonic()
        if theme_watch:
            m = _mtime(theme_watch)
            if m != theme_watch_mtime:
                theme_watch_mtime = m
                burst_until = now + 4.0
                next_probe = now
        interval = 0.5 if now < burst_until else theme_poll
        if interval <= 0 and now >= burst_until:
            return
        if now >= next_probe:
            next_probe = now + interval
            _theme.request_probe(sys.stdout.fileno())

    offset = 0
    playing = auto_play
    play_frame = 0
    mouse_pos = None
    hover_until = 0.0    # monotonic time mouse_pos is forgotten
    drag_start = None    # (col, row) of left-button press while on_drag is set
    drag_delta = (0, 0)  # last displayed drag, to finish before opening help
    active_alert = None  # index of alert whose modal is open, or None
    modal_scroll = 0     # scroll offset within the modal
    alert_row_map = {}   # 0-based line index → [(first col, last col, alert index)]

    # Each frame goes out with a cursor position query after it, and the
    # next frame waits for the reply: the terminal answers once it has
    # read the frame, so a terminal slower than the loop is never handed
    # a backlog to play out after the user stops scrolling.  Input that
    # arrives during the wait is folded into the frame being held.  A
    # terminal that never answers is asked once, then left alone.
    sync = _term.frame_sync_enabled()
    acks_owed = 0

    def _ack_wait():
        return _ACK_WAIT_S if _term.answered else _ACK_FIRST_WAIT_S

    def _coalesce_or_repaint():
        """The verdict for input that changed the frame: paint now, or
        hold the paint while more input is waiting."""
        return 'coalesce' if _term.wait_readable(fd, 0) else 'repaint'

    def handle_input():
        """Read one key or mouse event and apply it.

        'quit' to leave the loop, 'repaint' when the frame should be drawn
        again, 'coalesce' when it should but more input is already waiting
        -- so a burst of scrolling paints once at its end -- and None when
        nothing on screen changed.  The caller owes a repaint after a
        'coalesce' whatever the later input says: the bytes waiting may
        be the terminal's reply to the last frame, which changes nothing.
        """
        nonlocal offset, playing, play_frame, mouse_pos, drag_start, drag_delta
        nonlocal active_alert, modal_scroll, acks_owed, hover_until
        action = _read_key(fd, text=bool(text_mode is not None and text_mode()))
        if isinstance(action, tuple) and action[0] == 'mouse' and _bidi.mirrored():
            # The view laid this frame out from the left and the pass
            # drew it from the right: the pointer goes back the same way
            from linecast._framebuffer import get_terminal_size
            _, cb, cx, cy, is_rel = action
            action = ('mouse', cb, get_terminal_size()[0] + 1 - cx, cy, is_rel)
        if isinstance(action, tuple) and action[0] == 'mouse':
            hover_until = _time.monotonic() + _HOVER_IDLE_S
        if action == 'ack':
            _term.mark_answered()
            acks_owed = max(0, acks_owed - 1)
            return None
        if action == 'theme':
            return 'repaint'  # the terminal's colours changed
        help_closed = False
        if help_panel is not None:
            was_helping = help_panel.open
            if help_panel.handle(action):
                if not was_helping and help_panel.open and drag_start is not None:
                    on_drag(*drag_delta, True)
                drag_start = None
                return 'repaint'
            help_closed = was_helping and not help_panel.open
        if (intercept is not None and action is not None
                and not isinstance(action, tuple)
                and intercept(action)):
            return 'repaint'
        if action == 'quit':
            if active_alert is not None:
                active_alert = None
                modal_scroll = 0
                return 'repaint'
            return 'quit'
        elif action == 'escape':
            # With mouse tracking, bare ESC is almost always a split mouse
            # sequence (release bytes arriving late).  Only honour ESC to
            # dismiss when mouse is off.
            if not mouse and active_alert is not None:
                active_alert = None
                return 'repaint'
        elif action == 'open':
            if active_alert is not None and on_open:
                on_open(active_alert)
                return 'repaint'
        elif action in ('fwd', 'back'):
            step = 1 if action == 'fwd' else -1
            if auto_play:
                playing = False
                play_frame += step
            else:
                if clamp_offset is not None:
                    offset = clamp_offset(offset)
                offset += step * scroll_step
                if clamp_offset is not None:
                    offset = clamp_offset(offset)
            return _coalesce_or_repaint()  # rapid scrolling
        elif action == 'reset':
            if auto_play:
                playing = not playing  # space = play/pause
                if not playing:
                    play_frame = 0  # pause returns to the home frame
            else:
                offset = 0
            return 'repaint'
        elif (on_action is not None and isinstance(action, str)
              and action.startswith('key:')):
            if on_action(action[4:]):
                return _coalesce_or_repaint()  # held-down keys (zoom taps)
        elif mouse and isinstance(action, tuple) and action[0] == 'mouse':
            _, cb, cx, cy, is_rel = action
            wheel_cb = _normalize_wheel_cb(cb)
            if wheel_cb in (64, 65):
                if on_wheel is not None:
                    # A view can own the wheel, or defer to ordinary scrolling
                    # when its panel is closed.
                    handled = on_wheel(1 if wheel_cb == 64 else -1, cx, cy)
                    if handled is not NotImplemented:
                        return _coalesce_or_repaint() if handled else None
                if active_alert is not None:
                    # Scroll the modal
                    modal_scroll += 3 if wheel_cb == 65 else -3
                    modal_scroll = max(0, modal_scroll)
                elif auto_play:
                    playing = False
                    play_frame += 1 if wheel_cb == 64 else -1
                else:
                    if clamp_offset is not None:
                        offset = clamp_offset(offset)
                    offset += scroll_step if wheel_cb == 64 else -scroll_step
                    if clamp_offset is not None:
                        offset = clamp_offset(offset)
                return _coalesce_or_repaint()  # rapid scrolling
            if is_rel:
                # Button release — completes a drag gesture if one
                # started; otherwise ignore.
                if drag_start is not None:
                    dcol, drow = cx - drag_start[0], cy - drag_start[1]
                    drag_start = None
                    clicked = (dcol == 0 and drow == 0
                               and on_click is not None
                               and on_click(cx, cy))
                    if on_drag(dcol, drow, True) or clicked:
                        return 'repaint'
                return None
            if (cb & 0b11) == 0 and not (cb & 0x20):
                # Left button press (not release, not motion)
                if on_drag is not None:
                    drag_start = (cx, cy)
                    drag_delta = (0, 0)
                row_idx = cy - 1  # 1-based → 0-based
                if active_alert is not None:
                    # Click while modal open — dismiss
                    active_alert = None
                    modal_scroll = 0
                    return 'repaint'
                elif row_idx in alert_row_map:
                    spans = alert_row_map[row_idx]
                    col_idx = cx - 1  # 1-based → 0-based
                    active_alert = next(
                        (i for start, end, i in spans
                         if start <= col_idx <= end),
                        spans[0][2])
                    modal_scroll = 0
                    return 'repaint'
            if cb & 32:
                if drag_start is not None:
                    # mid-drag: live preview with cumulative delta
                    dcol, drow = cx - drag_start[0], cy - drag_start[1]
                    drag_delta = (dcol, drow)
                    if on_drag(dcol, drow, False):
                        return _coalesce_or_repaint()  # rapid drag motion
                    return None
                # Hover-capable terminals: render once at the final position.
                mouse_pos = (cx, cy)
                return _coalesce_or_repaint()
            # Fallback for terminals without motion reporting:
            # update pointer on press so tooltip can still appear.
            if (cb & 0b11) in (0, 1, 2):
                mouse_pos = (cx, cy)
                return 'repaint'
        if help_closed:
            return 'repaint'  # even an unbound key must erase the panel
        return None

    bidi_on, bidi_off = bidi_modes()
    init = f"\033[?1049h\033[?25l{bidi_on}"
    if mouse:
        # Enable both legacy and SGR mouse reporting for broad compatibility.
        init += "\033[?1000h\033[?1002h\033[?1003h\033[?1006h"
        # Alternate-scroll mode helps terminals that don't report wheel as mouse.
        if is_apple_terminal:
            init += "\033[?1007h"
    watch = WorkerWatch()
    watch.install()
    try:
        _running = True
        # Cbreak first, then the escapes: on Windows, switching stdin to
        # VT input resets the terminal's mouse tracking, so enables sent
        # beforehand are silently dropped.  Order is moot on POSIX.
        term.set_cbreak()
        sys.stdout.write(init)
        sys.stdout.flush()

        while True:
            # Hold this frame until the terminal has read the last one.
            # Keys and wheel notches that arrive meanwhile change the
            # state the frame is rendered from; a wakeup or a timer tick
            # is absorbed the same way, since a repaint is coming.
            if sync and acks_owed:
                until = _time.monotonic() + _ack_wait()
                while acks_owed:
                    left = until - _time.monotonic()
                    if left <= 0:
                        if not _term.answered:
                            sync = False  # this terminal does not answer
                        acks_owed = 0
                        break
                    if term.wait(min(0.1, left)) == 'input':
                        if handle_input() == 'quit':
                            return

            # Drain wakeups from before this render: whatever they announced,
            # the frame about to be drawn reflects it.  The drain must come
            # BEFORE render_fn, never after — a background fetch can finish
            # (and nudge the pipe) while the render is still composing its
            # "loading" frame, and a drain after the paint would swallow that
            # completion, leaving the loading frame up until the next input.
            term.drain()
            kwargs = {}
            if mouse:
                kwargs.update(mouse_pos=mouse_pos, active_alert=active_alert,
                              modal_scroll=modal_scroll)
            if auto_play:
                kwargs.update(play_frame=play_frame, playing=playing)
            if clamp_offset is not None:
                offset = clamp_offset(offset)
            result = render_fn(offset_minutes=offset, **kwargs)
            # render_fn may return (output, metadata) or just output
            if isinstance(result, tuple):
                output, alert_row_map = result
            else:
                output = result
                alert_row_map = {}
            # Separate the cursor-positioned overlay from the body (the
            # \x00 delimiter overlay() writes)
            parts = output.split('\x00', 1)
            main_out = parts[0]
            overlay = parts[1] if len(parts) > 1 else ""
            if help_panel is not None and help_panel.open:
                from linecast._framebuffer import get_terminal_size
                overlay = "\033[?1003l" + help_panel.render(*get_terminal_size())
            elif help_panel is not None and mouse:
                # A search field may intentionally disable motion; only
                # restore it when the caller's overlay has not done so.
                if "\033[?1003l" not in overlay:
                    overlay = "\033[?1003h" + overlay
            paint = frame_paint(main_out, overlay)
            if sync:
                paint += _CPR_QUERY
                acks_owed += 1
            sys.stdout.write(paint)
            sys.stdout.flush()

            # Wait for input, resize, or timeout
            wait = (play_interval if (auto_play and playing)
                    else interval() if callable(interval) else interval)
            deadline = _time.time() + wait
            owed = False   # a coalesced input is waiting for its repaint
            while True:
                # A repaint held back for more input is due once the input
                # has run out.  It cannot wait for the last of that input
                # to ask: that is often the terminal's reply to the frame
                # before, and a reply changes nothing on screen.
                if owed and not _term.wait_readable(fd, 0):
                    break
                remaining = deadline - _time.time()
                if remaining <= 0:
                    if auto_play and playing and (play_gate is None
                                                  or play_gate()):
                        play_frame += 1  # advance the animation
                    break
                if (mouse_pos is not None and drag_start is None
                        and _time.monotonic() >= hover_until):
                    mouse_pos = None  # the mouse has been still: drop the chip
                    break
                event = term.wait(min(0.1, remaining))
                if event == 'wake':
                    break
                if event == 'timeout':
                    _maybe_probe()
                    continue
                if event == 'input':
                    verdict = handle_input()
                    if verdict == 'quit':
                        return
                    if verdict == 'repaint':
                        break
                    if verdict == 'coalesce':
                        owed = True
    except KeyboardInterrupt:
        pass
    # SystemExit is NOT swallowed: a sys.exit(1) from a render callback (or
    # the signal handler above) must reach the shell as a nonzero status.
    # The finally block still restores the terminal on its way out.
    finally:
        _running = False
        try:
            cleanup = ""
            if mouse:
                cleanup += "\033[?1006l\033[?1003l\033[?1002l\033[?1000l"
                if is_apple_terminal:
                    cleanup += "\033[?1007l"
            cleanup += f"{_AUTOWRAP_ON}{bidi_off}\033[?25h\033[?1049l"
            if sync:
                cleanup += _CPR_QUERY
            sys.stdout.write(cleanup)
            sys.stdout.flush()
        except Exception:
            pass  # tty may already be gone (SIGHUP); nothing left to restore
        # What the terminal was still sending -- a colour probe's replies,
        # mouse reports from before it read the escape above -- is read
        # and dropped, up to its reply to the query, so none of it reaches
        # the shell.  A frame whose reply was still owed when the loop
        # ended is answered first, so the drain waits for one reply more
        # than that.  Then the terminal settings, the signal handlers and
        # the wakeup channel go back, in that order (_term.LiveTerminal).
        # The drain waits on the terminal, and a second ctrl-C or SIGTERM
        # meanwhile raises through this block: close() runs regardless,
        # or the shell would inherit the tty in cbreak.
        try:
            term.settle(_ack_wait() if sync else 0, replies=acks_owed + 1)
        except Exception:
            pass
        finally:
            term.close()
        watch.uninstall()
        watch.report()



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

    def flash_overlay(self, cols, rows):
        """The current note on overlay()'s floating channel."""
        if self._flash is None:
            return ""
        paragraphs, deadline, busy = self._flash
        if busy:
            from linecast._spinner import SPINNER_FRAMES
            spinner = SPINNER_FRAMES[int(_time.monotonic() / 0.08) % len(SPINNER_FRAMES)]
            self._flash_repaint(0.08)
            return toast_box(' '.join(paragraphs), cols, rows, icon=spinner)
        if _time.monotonic() >= deadline:
            self.clear_flash()
            return ""
        from linecast._graphics import fg
        from linecast._help import wrap
        width = max(10, min(cols - 6, 64))
        lines = []
        for text in paragraphs:
            lines += [f" {line}" for line in wrap(text, width)]
        return menu_box(lines, cols, rows, border=fg(*MUTED))

    def hooks(self):
        """The hooks this app overrides, as live_loop keyword arguments."""
        return {name: getattr(self, name) for name in self.HOOKS
                if getattr(type(self), name) is not getattr(LiveApp, name)}

    help_view = None

    def help_panel(self):
        from linecast._help import HelpPanel
        return HelpPanel(self.help_view, self.runtime.lang) if self.help_view else None

    def run(self):
        """Run the app on the alternate screen until it quits."""
        from linecast._textwidth import calibrate_from_terminal
        calibrate_from_terminal()
        try:
            live_loop(self.render, interval=self.interval, mouse=self.mouse,
                      scroll_step=self.scroll_step, auto_play=self.auto_play,
                      play_interval=self.play_interval, help_panel=self.help_panel(),
                      **self.hooks())
        finally:
            self.clear_flash()
            self.stop()
