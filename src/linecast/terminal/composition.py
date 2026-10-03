"""Resolve hover shadows against the displayed frame, including earlier overlays.

Only linecast's output vocabulary is read: SGR, cursor-addressed overlay
rows, and body newlines. This is not a terminal emulator. Color parameters
stay in their original form on exposed halves; blended halves use the
current palette and are encoded in the terminal's selected color mode.
"""

from linecast.terminal import bidi
from linecast.terminal.textwidth import glyphs

# An internal SGR attribute travels with a half-block through bidi's cell
# ordering. It is removed before output; it must never reach the terminal.
_SHADOW_ATTR = "999"
SHADOW = "\033[999m"


def _background(color, foreground=False):
    """An SGR color, expressed as a background without RGB quantization."""
    if not color:
        if foreground:
            from linecast.terminal import theme
            from linecast.terminal.color import bg
            return bg(*theme.theme_fg) or "\033[49m"
        return "\033[49m"
    if foreground:
        head, *tail = color.split(";", 1)
        # Colon-form truecolor is accepted by the bidi color state too.
        if ":" in head:
            head, rest = head.split(":", 1)
            return f"\033[{int(head) + 10}:{rest}m"
        color = str(int(head) + 10) + (";" + tail[0] if tail else "")
    return f"\033[{color}m"


def _rgb(background):
    """Resolve a background SGR against the current terminal palette."""
    from linecast.terminal import theme
    parts = background[2:-1].replace(":", ";").split(";")
    code = int(parts[0])
    if code == 49:
        return theme.theme_bg
    if code == 48:
        if parts[1] == "2":
            return tuple(map(int, parts[-3:]))
        index = int(parts[2])
    else:
        index = code - (100 - 8 if code >= 100 else 40)
    if index < 16:
        return theme.theme_ansi[index]
    if index >= 232:
        return (8 + (index - 232) * 10,) * 3
    index -= 16
    levels = (0, 95, 135, 175, 215, 255)
    return levels[index // 36], levels[index // 6 % 6], levels[index % 6]


def resolve_shadows(body, floating):
    """Blend shadows at 60% opacity and preserve their unused halves.

    Call after bidi.display, when body and overlays have screen coordinates.
    Ordinary glyphs contribute their background; block graphics contribute
    the color of the exposed half. Newly resolved cells join the surface so
    a later chip can cast its shadow over an earlier one.
    """
    if _SHADOW_ATTR not in floating:
        return floating
    from linecast.terminal.color import bg, fg
    from linecast.terminal.theme import lerp_rgb

    surface = {}
    blends = {}

    def blend(under, ink):
        key = under, ink
        if key not in blends:
            rgb = lerp_rgb(_rgb(under), _rgb(ink), 0.6)
            blends[key] = bg(*rgb) or "\033[49m", fg(*rgb)
        return blends[key]

    state = bidi._EMPTY
    row = col = 1

    def read(text, emit=False):
        nonlocal state, row, col
        out = []
        pos = 0

        def write(run):
            nonlocal row, col
            for i, line in enumerate(run.split("\n")):
                if i:
                    row, col = row + 1, 1
                    if emit:
                        out.append("\n")
                for _x, glyph, width in glyphs(line):
                    attrs, foreground, background, _link = state
                    reverse = "7" in attrs
                    back = _background(foreground if reverse else background, reverse)
                    front = _background(background if reverse else foreground, not reverse)
                    top = front if glyph in ("▀", "█") else back
                    bottom = front if glyph in ("▄", "█") else back
                    if emit and _SHADOW_ATTR in attrs and glyph in ("▀", "▄", "█"):
                        under = surface.get((row, col), ("\033[49m", "\033[49m"))
                        top, bottom = under
                        if glyph in ("▀", "█"):
                            top, top_fg = blend(top, front)
                        if glyph in ("▄", "█"):
                            bottom, bottom_fg = blend(bottom, front)
                        # A full-height side can cover two different chart colors.
                        # Use two halves there too, so both receive the same opacity.
                        if glyph == "▄":
                            out.extend((top, bottom_fg, "▄"))
                        else:
                            out.extend((bottom, top_fg, "▀"))
                        out.extend((_background(background),
                                    "\033[" + (foreground or "39") + "m"))
                    elif emit:
                        out.append(glyph)
                    for offset in range(width):
                        surface[row, col + offset] = top, bottom
                    col += width

        for match in bidi._ESCAPE.finditer(text):
            write(text[pos:match.start()])
            seq = match.group()
            pos = match.end()
            if bidi._SGR.match(seq):
                state = bidi._next_state(state, seq)
                if emit:
                    groups = list(bidi._sgr_groups(seq[2:-1]))
                    clean = [g for g in groups if g != _SHADOW_ATTR]
                    if clean:
                        out.append("\033[" + ";".join(clean) + "m")
            else:
                cup = bidi._CUP.match(seq)
                if cup:
                    row, col = int(cup[1] or 1), int(cup[2] or 1)
                if emit:
                    out.append(seq)
        write(text[pos:])
        return "".join(out)

    read(body)
    state = bidi._EMPTY  # frame_paint resets between body and floating
    return read(floating, emit=True)
