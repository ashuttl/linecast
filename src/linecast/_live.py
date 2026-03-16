"""Live mode: alternate screen rendering with auto-refresh and input handling.

Provides the live_loop() function that runs a render callback in a loop on the
terminal's alternate screen buffer, with support for:

- Auto-refresh on a configurable interval
- Immediate re-render on terminal resize (SIGWINCH)
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
    return ('mouse', cb, cx, cy, seq[-1:] == b'm')


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
    is_rel = (cb & 0b11) == 0b11 and not (cb & 0x40)
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


def _read_key(fd):
    """Read a keypress from stdin in cbreak mode. Returns action string or None.

    Fully consumes CSI/SS3 escape sequences so leftover bytes don't leak.
    Uses a longer timeout (150ms) to avoid splitting mouse escape sequences
    when the system is busy (e.g. after a re-render).
    """
    import select as _sel

    def _read_byte():
        try:
            data = os.read(fd, 1)
        except OSError:
            return None
        return data or None

    def _read_byte_timeout(timeout=0.15):
        if _sel.select([fd], [], [], timeout)[0]:
            return _read_byte()
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

    if b in (b'q', b'Q'):
        return 'quit'
    if b in (b'o', b'O'):
        return 'open'
    if b in (b'n', b'N', b' '):
        return 'reset'
    return None


# ---------------------------------------------------------------------------
# Live loop
# ---------------------------------------------------------------------------
def live_loop(render_fn, interval=60, mouse=False, on_open=None, scroll_step=15):
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
    Re-renders immediately on terminal resize (SIGWINCH) or input.
    """
    import select, signal, termios, tty

    # Self-pipe for async-signal-safe SIGWINCH wakeup.
    # threading.Event.set() is NOT safe in signal handlers (its internal
    # lock can deadlock when SIGWINCH re-enters itself during rapid resize).
    # os.write() to a pipe is async-signal-safe per POSIX.
    wake_r, wake_w = os.pipe()
    os.set_blocking(wake_r, False)
    os.set_blocking(wake_w, False)

    def _on_winch(*_):
        try:
            os.write(wake_w, b'\x00')
        except OSError:
            pass

    signal.signal(signal.SIGWINCH, _on_winch)

    is_apple_terminal = os.environ.get('TERM_PROGRAM') == 'Apple_Terminal'

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    offset = 0
    mouse_pos = None
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
    sys.stdout.write(init)
    sys.stdout.flush()
    try:
        tty.setcbreak(fd)

        while True:
            if mouse:
                result = render_fn(offset_minutes=offset, mouse_pos=mouse_pos, active_alert=active_alert, modal_scroll=modal_scroll)
            else:
                result = render_fn(offset_minutes=offset)
            # render_fn may return (output, metadata) or just output
            if isinstance(result, tuple):
                output, alert_row_map = result
            else:
                output = result
                alert_row_map = {}
            # Separate cursor-positioned overlay from main output (\x00 delimiter)
            parts = output.split('\x00', 1)
            main_out = parts[0]
            overlay = parts[1] if len(parts) > 1 else ""
            # \033[H homes cursor; \033[K clears line remainders;
            # \033[J clears below; overlay draws on top after clear
            padded = main_out.replace('\n', '\033[K\n')
            sys.stdout.write(f"\033[H{padded}\033[K\033[J\033[0m{overlay}\033[0m")
            sys.stdout.flush()
            # Drain any pending SIGWINCH notifications.
            try:
                os.read(wake_r, 512)
            except OSError:
                pass

            # Wait for input, resize, or timeout
            deadline = _time.time() + interval
            while True:
                remaining = deadline - _time.time()
                if remaining <= 0:
                    break
                try:
                    ready, _, _ = select.select([fd, wake_r], [], [], min(0.1, remaining))
                except (InterruptedError, OSError):
                    continue
                if wake_r in ready:
                    try:
                        os.read(wake_r, 512)
                    except OSError:
                        pass
                    break
                if fd in ready:
                    action = _read_key(fd)
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
                        offset += scroll_step
                        if select.select([fd], [], [], 0)[0]:
                            continue  # coalesce rapid scrolling
                        break
                    elif action == 'back':
                        offset -= scroll_step
                        if select.select([fd], [], [], 0)[0]:
                            continue  # coalesce rapid scrolling
                        break
                    elif action == 'reset':
                        offset = 0
                        break
                    elif mouse and isinstance(action, tuple) and action[0] == 'mouse':
                        _, cb, cx, cy, is_rel = action
                        wheel_cb = _normalize_wheel_cb(cb)
                        if wheel_cb in (64, 65):
                            if active_alert is not None:
                                # Scroll the modal
                                modal_scroll += 3 if wheel_cb == 65 else -3
                                modal_scroll = max(0, modal_scroll)
                            else:
                                offset += scroll_step if wheel_cb == 64 else -scroll_step
                            if select.select([fd], [], [], 0)[0]:
                                continue  # coalesce rapid scrolling
                            break
                        if is_rel:
                            # Button release — ignore
                            continue
                        if (cb & 0b11) == 0 and not (cb & 0x20):
                            # Left button press (not release, not motion)
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
                            # Hover-capable terminals.
                            mouse_pos = (cx, cy)
                            break
                        # Fallback for terminals without motion reporting:
                        # update pointer on press so tooltip can still appear.
                        if (cb & 0b11) in (0, 1, 2):
                            mouse_pos = (cx, cy)
                            break
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        os.close(wake_r)
        os.close(wake_w)
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        cleanup = ""
        if mouse:
            cleanup += "\033[?1006l\033[?1003l\033[?1002l\033[?1000l"
            if is_apple_terminal:
                cleanup += "\033[?1007l"
        cleanup += "\033[?25h\033[?1049l"
        sys.stdout.write(cleanup)
        sys.stdout.flush()
