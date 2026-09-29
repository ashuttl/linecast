"""What the bytes a terminal sends mean: keys, mouse reports, and its
replies to the live loop's queries.

read_key() reads one of them from stdin in cbreak mode and says what it
is, as the action string, mouse tuple or reply live_loop acts on.  KEYS
is every key a view answers to outside a text field.

Mouse protocol references:
  - SGR (1006): https://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h3-Extended-coordinates
  - Legacy X10:  https://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h3-Normal-tracking-mode
"""

from linecast.terminal import bidi as _bidi
from linecast.terminal import term as _term


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


def wheel_code(cb):
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


# The keys a view answers to outside a text field, byte to action; any
# other byte is dropped.  A key a view handles and its help lists must be
# here too, or it never reaches on_action.  A letter reads the same in
# either case, except W, A, S and D: lower-case wasd pans, and the
# shifted letters keep the view actions panning displaced.  A digit is
# itself.
KEYS = {
    b'q': 'quit', b'Q': 'quit',
    b'o': 'open', b'O': 'open',
    b'n': 'reset', b'N': 'reset', b' ': 'reset',
    b'+': 'key:+', b'=': 'key:+',
    b'-': 'key:-', b'_': 'key:-',
    b't': 'key:t', b'T': 'key:t',
    b'c': 'key:c', b'C': 'key:c',
    b'w': 'key:w', b'a': 'key:a', b's': 'key:s', b'd': 'key:d',
    b'W': 'key:W', b'A': 'key:A', b'S': 'key:S', b'D': 'key:D',
    b'v': 'key:v', b'V': 'key:v',
    b'p': 'key:p', b'P': 'key:p',
    b'l': 'key:l', b'L': 'key:l',
    b'm': 'key:m', b'M': 'key:m',
    b'y': 'key:y', b'Y': 'key:y',
    b'r': 'key:r', b'R': 'key:r',
    b'/': 'key:/', b'?': 'key:?',
    b'\r': 'key:enter', b'\n': 'key:enter',
    **{digit.encode(): 'key:' + digit for digit in '0123456789'},
}


def _read_byte_timeout(fd, timeout):
    """The next byte of input if it arrives within `timeout` seconds, else None."""
    if _term.wait_readable(fd, timeout):
        return _term.read_byte(fd)
    return None


def _read_utf8(fd, lead):
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
        c = _read_byte_timeout(fd, 0.05)
        if c is None:
            return None
        buf.extend(c)
    try:
        return buf.decode('utf-8')
    except UnicodeDecodeError:
        return None


def _read_escape(fd):
    """What an ESC just read begins: an arrow, a mouse report, the
    terminal's answer to a query, or the Esc key alone.

    Reads the whole of an OSC, CSI or SS3 sequence, so none of its bytes
    is later taken for a key.  Returns an action, a mouse tuple, 'ack',
    'theme', 'escape', or None for a sequence that means nothing here.
    """
    # Use 150ms timeout — 50ms is too short when the system is busy
    # rendering; mouse release sequences (\033[<0;x;ym) can arrive late
    # and the \033 gets read as a bare ESC.
    b2 = _read_byte_timeout(fd, 0.15)
    if b2 is None:
        return 'escape'
    if b2 == b'\033':
        # Esc, and the next sequence already arriving: a mouse report
        # while the pointer moves, an arrow.  The first is a bare Esc;
        # the second goes back to start the next read, or the rest of
        # its sequence would be taken for keys ([<35;12;5M: 3, 5, m)
        _term.unread(b2)
        return 'escape'

    if b2 == b']':
        # An OSC reply to the live loop's theme probe, e.g.
        # \033]11;rgb:1e/1e/2e\007 (or ST-terminated).  Consume it
        # whole and hand the body to the theme; it is never a key.
        body = bytearray()
        while True:
            c = _read_byte_timeout(fd, 0.15)
            if c is None:
                return None
            if c == b'\x07':
                break
            if c == b'\033':
                _read_byte_timeout(fd, 0.05)  # the backslash of ST
                break
            body.extend(c)
            if len(body) > 256:
                return None
        from linecast.terminal import theme as _theme
        return 'theme' if _theme.ingest_osc(bytes(body)) else None

    if b2 == b'[':
        seq = bytearray()
        while True:
            c = _read_byte_timeout(fd, 0.15)
            if c is None:
                break
            if c == b'\033':
                # a sequence cut short by the next one: drop this one,
                # keep the next whole
                _term.unread(c)
                return None
            seq.extend(c)
            # Legacy mouse: \033[M Cb Cx Cy
            if c == b'M' and len(seq) == 1:
                tail = bytearray()
                for _ in range(3):
                    c_tail = _read_byte_timeout(fd, 0.15)
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
        b3 = _read_byte_timeout(fd, 0.15)
        if b3 is not None:
            return _arrow(b3)
    return 'escape'


def read_key(fd, text=False):
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
    key it sits on (see terminal.keylayouts): Persian ض and Russian й are q.
    """
    b = _term.read_byte(fd)
    if b is None:
        return None

    if b == b'\033':
        return _read_escape(fd)

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
        ch = _read_utf8(fd, b)
        return 'char:' + ch if ch is not None else None

    if b[0] >= 0x80:
        # A letter from a non-Latin layout (ض, й, ㅂ): read it as the
        # Latin key it sits on, so q still quits under Persian or Russian.
        from linecast.terminal.keylayouts import latin_key
        ch = _read_utf8(fd, b)
        latin = latin_key(ch) if ch is not None else None
        if latin is None:
            return None
        b = latin.encode()

    return KEYS.get(b)
