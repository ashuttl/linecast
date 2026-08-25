"""Live mode: alternate screen rendering with auto-refresh and input handling.

Provides the live_loop() function that runs a render callback in a loop on the
terminal's alternate screen buffer, LiveApp — the class an app with keys and
state subclasses to run under it — and overlay(), which puts a tooltip, modal
or panel over a frame.  The loop supports:

- Auto-refresh on a configurable interval
- Immediate re-render on terminal resize
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
import time as _time

from linecast import _term


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------
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
    """
    def _read_byte():
        return _term.read_byte(fd)

    def _read_byte_timeout(timeout=0.15):
        if _term.wait_readable(fd, timeout):
            return _term.read_byte(fd)
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
            return {
                b'A': 'fwd',
                b'B': 'back',
                b'C': 'fwd',
                b'D': 'back',
            }.get(final)

        if b2 == b'O':
            # SS3 sequence (some terminals use for arrows)
            b3 = _read_byte_timeout(0.15)
            if b3 is not None:
                return {
                    b'A': 'fwd',
                    b'B': 'back',
                    b'C': 'fwd',
                    b'D': 'back',
                }.get(b3)
        return 'escape'

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
        if 0xC0 <= o < 0xE0:
            extra = 1
        elif 0xE0 <= o < 0xF0:
            extra = 2
        elif 0xF0 <= o < 0xF8:
            extra = 3
        else:
            return None  # stray continuation byte or invalid lead
        buf = bytearray(b)
        for _ in range(extra):
            c = _read_byte_timeout(0.05)
            if c is None:
                return None
            buf.extend(c)
        try:
            return 'char:' + buf.decode('utf-8')
        except UnicodeDecodeError:
            return None

    if b in (b'q', b'Q'):
        return 'quit'
    if b in (b'o', b'O'):
        return 'open'
    if b in (b'n', b'N', b' '):
        return 'reset'
    if b in (b'+', b'='):
        return 'key:+'
    if b in (b'-', b'_'):
        return 'key:-'
    if b in (b't', b'T'):
        return 'key:t'
    if b in (b'c', b'C'):
        return 'key:c'
    if b in (b'w', b'W'):
        return 'key:w'
    if b in (b's', b'S'):
        return 'key:s'
    if b in (b'v', b'V'):
        return 'key:v'
    if b in (b'p', b'P'):
        return 'key:p'
    if b in (b'd', b'D'):
        return 'key:d'
    if b in (b'l', b'L'):
        return 'key:l'
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
              on_click=None):
    """Run render_fn() in a loop on the alternate screen buffer.

    render_fn: callable(offset_minutes=0) returning (display_string, metadata)
               or just display_string.
               If mouse=True, also receives mouse_pos=(col, row) or None
               and active_alert=int_or_None.
               Scroll/arrow keys adjust offset_minutes to scrub through time.
    interval: seconds between refreshes.
    mouse: if True, enable SGR mouse tracking and pass mouse_pos to render_fn.
    on_open: optional callback(alert_index) called when user presses 'o' on a modal.
    scroll_step: minutes to advance/retreat per scroll or arrow key event.
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
              leaves the frame alone (a clamped zoom).
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
    Re-renders immediately on terminal resize or input.

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
    drag_start = None    # (col, row) of left-button press while on_drag is set
    active_alert = None  # index of alert whose modal is open, or None
    modal_scroll = 0     # scroll offset within the modal
    alert_row_map = {}   # 0-based line index → alert index

    init = "\033[?1049h\033[?25l"
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
            # \033[H homes cursor; \033[K clears line remainders;
            # \033[J clears below; overlay draws on top after clear
            padded = main_out.replace('\n', '\033[K\n')
            sys.stdout.write(f"\033[H{padded}\033[K\033[J\033[0m{overlay}\033[0m")
            sys.stdout.flush()

            # Wait for input, resize, or timeout
            wait = play_interval if (auto_play and playing) else interval
            deadline = _time.time() + wait
            while True:
                remaining = deadline - _time.time()
                if remaining <= 0:
                    if auto_play and playing and (play_gate is None
                                                  or play_gate()):
                        play_frame += 1  # advance the animation
                    break
                event = term.wait(min(0.1, remaining))
                if event == 'wake':
                    break
                if event == 'timeout':
                    _maybe_probe()
                    continue
                if event == 'input':
                    action = _read_key(
                        fd, text=bool(text_mode is not None and text_mode()))
                    if action == 'theme':
                        break  # the terminal's colours changed: repaint
                    if (intercept is not None and action is not None
                            and not isinstance(action, tuple)
                            and intercept(action)):
                        break
                    if action == 'quit':
                        if active_alert is not None:
                            active_alert = None
                            modal_scroll = 0
                            break
                        return
                    elif action == 'escape':
                        # With mouse tracking, bare ESC is almost always a
                        # split mouse sequence (release bytes arriving late).
                        # Only honour ESC to dismiss when mouse is off.
                        if not mouse and active_alert is not None:
                            active_alert = None
                            break
                    elif action == 'open':
                        if active_alert is not None and on_open:
                            on_open(active_alert)
                            break
                    elif action == 'fwd':
                        if auto_play:
                            playing = False
                            play_frame += 1
                        else:
                            offset += scroll_step
                        if _term.wait_readable(fd, 0):
                            continue  # coalesce rapid scrolling
                        break
                    elif action == 'back':
                        if auto_play:
                            playing = False
                            play_frame -= 1
                        else:
                            offset -= scroll_step
                        if _term.wait_readable(fd, 0):
                            continue  # coalesce rapid scrolling
                        break
                    elif action == 'reset':
                        if auto_play:
                            playing = not playing  # space = play/pause
                            if not playing:
                                play_frame = 0  # pause returns to the home frame
                        else:
                            offset = 0
                        break
                    elif (on_action is not None and isinstance(action, str)
                          and action.startswith('key:')):
                        if on_action(action[4:]):
                            if _term.wait_readable(fd, 0):
                                continue  # coalesce held-down keys (zoom taps)
                            break
                    elif mouse and isinstance(action, tuple) and action[0] == 'mouse':
                        _, cb, cx, cy, is_rel = action
                        wheel_cb = _normalize_wheel_cb(cb)
                        if wheel_cb in (64, 65):
                            if on_wheel is not None:
                                # Caller owns the wheel outright (zoom,
                                # panel scroll, …) — no scrub fallback.
                                if on_wheel(1 if wheel_cb == 64 else -1,
                                            cx, cy):
                                    if _term.wait_readable(fd, 0):
                                        continue  # coalesce rapid wheel
                                    break
                                continue
                            if active_alert is not None:
                                # Scroll the modal
                                modal_scroll += 3 if wheel_cb == 65 else -3
                                modal_scroll = max(0, modal_scroll)
                            elif auto_play:
                                playing = False
                                play_frame += 1 if wheel_cb == 64 else -1
                            else:
                                offset += scroll_step if wheel_cb == 64 else -scroll_step
                            if _term.wait_readable(fd, 0):
                                continue  # coalesce rapid scrolling
                            break
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
                                    break
                            continue
                        if (cb & 0b11) == 0 and not (cb & 0x20):
                            # Left button press (not release, not motion)
                            if on_drag is not None:
                                drag_start = (cx, cy)
                            row_idx = cy - 1  # 1-based → 0-based
                            if active_alert is not None:
                                # Click while modal open — dismiss
                                active_alert = None
                                modal_scroll = 0
                                break
                            elif row_idx in alert_row_map:
                                active_alert = alert_row_map[row_idx]
                                modal_scroll = 0
                                break
                        if cb & 32:
                            if drag_start is not None:
                                # mid-drag: live preview with cumulative delta
                                dcol, drow = cx - drag_start[0], cy - drag_start[1]
                                if on_drag(dcol, drow, False):
                                    if _term.wait_readable(fd, 0):
                                        continue  # coalesce rapid drag motion
                                    break
                                continue
                            # Hover-capable terminals.
                            mouse_pos = (cx, cy)
                            if _term.wait_readable(fd, 0):
                                continue  # coalesce rapid motion: render once at the final position
                            break
                        # Fallback for terminals without motion reporting:
                        # update pointer on press so tooltip can still appear.
                        if (cb & 0b11) in (0, 1, 2):
                            mouse_pos = (cx, cy)
                            break
    except KeyboardInterrupt:
        pass
    # SystemExit is NOT swallowed: a sys.exit(1) from a render callback (or
    # the signal handler above) must reach the shell as a nonzero status.
    # The finally block still restores the terminal on its way out.
    finally:
        _running = False
        # Puts back the terminal settings, the signal handlers and the
        # wakeup channel, in that order — see _term.LiveTerminal.close.
        term.close()
        try:
            cleanup = ""
            if mouse:
                cleanup += "\033[?1006l\033[?1003l\033[?1002l\033[?1000l"
                if is_apple_terminal:
                    cleanup += "\033[?1007l"
            cleanup += "\033[?25h\033[?1049l"
            sys.stdout.write(cleanup)
            sys.stdout.flush()
        except Exception:
            pass  # tty may already be gone (SIGHUP); nothing left to restore
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
             "on_open", "play_gate", "text_mode")

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
        """The wheel, owned outright: +1 up / -1 down at (col, row)."""
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

    def hooks(self):
        """The hooks this app overrides, as live_loop keyword arguments."""
        return {name: getattr(self, name) for name in self.HOOKS
                if getattr(type(self), name) is not getattr(LiveApp, name)}

    def run(self):
        """Run the app on the alternate screen until it quits."""
        try:
            live_loop(self.render, interval=self.interval, mouse=self.mouse,
                      scroll_step=self.scroll_step, auto_play=self.auto_play,
                      play_interval=self.play_interval, **self.hooks())
        finally:
            self.stop()
