"""Color compaction preserves glyphs, effective rendition, and controls.

compact_colors drops the colour escapes a frame spends on the colour
already in effect.  What it must never change is what the terminal
draws, so these tests read the frame two ways: as a rendition signature
(every character with the colours in force when it lands) and, for real
frames, as a painted grid of cells after the live loop has addressed
every row and cleared it.
"""

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _color, _maps_paint
from linecast._live import frame_body, frame_paint


CSI = re.compile(r'\x1b\[([0-?]*)([ -/]*)([@-~])')


def _sgr(values, fg, bg, bold):
    """Apply one SGR parameter list, returning the new (fg, bg, bold)."""
    i = 0
    while i < len(values):
        value = values[i]
        i += 1
        if value == 0:
            fg = bg = None
            bold = False
        elif value in (1, 22):
            bold = value == 1
        elif value in (38, 48):
            size = 4 if values[i] == 2 else 2
            color = tuple(values[i:i + size])
            i += size
            if value == 38:
                fg = color
            else:
                bg = color
        elif 30 <= value <= 37 or 90 <= value <= 97 or value == 39:
            fg = None if value == 39 else value
        elif 40 <= value <= 47 or 100 <= value <= 107 or value == 49:
            bg = None if value == 49 else value
        else:
            raise AssertionError(f'unsupported test rendition {value}')
    return fg, bg, bold


def rendition_signature(output):
    """Read SGR independently, including combined resets and color setters.

    Matching text with its rendition and every intervening cursor/control
    operation also preserves wide glyphs, combining marks, and painted spaces.
    """
    fg = bg = None
    bold = False
    signature = []
    end = 0
    for match in CSI.finditer(output):
        signature.extend((char, fg, bg, bold) for char in output[end:match.start()])
        end = match.end()
        if match[3] != 'm':
            signature.append((match[0], fg, bg, bold))
            continue
        fg, bg, bold = _sgr([int(value or 0) for value in match[1].split(';')],
                            fg, bg, bold)
    signature.extend((char, fg, bg, bold) for char in output[end:])
    signature.append(('final rendition', fg, bg, bold))
    return signature


def painted(text, cols=80, rows=24):
    """The cells a terminal is left holding after it draws `text`.

    Enough of one to read a linecast frame: addressed rows, erase in
    line and below (both painting with the current background, as a
    terminal with background-colour-erase does), SGR, and autowrap off,
    so a row that reaches the last column stops there.  Private modes —
    the synchronized update, autowrap itself — are read and ignored.
    """
    blank = (' ', None, None, False)
    grid = [[blank] * cols for _ in range(rows)]
    row = col = 0
    fg = bg = None
    bold = False

    def write(chars):
        nonlocal col
        for char in chars:
            assert char != '\n', 'a painted frame addresses its rows'
            if row < rows and col < cols:
                grid[row][col] = (char, fg, bg, bold)
            col = min(col + 1, cols - 1)

    def erase(cells):
        for r, c in cells:
            if r < rows and c < cols:
                grid[r][c] = (' ', None, bg, False)

    end = 0
    for match in CSI.finditer(text):
        write(text[end:match.start()])
        end = match.end()
        params, private, final = match[1], match[1][:1] == '?', match[3]
        if private:
            continue
        values = [int(value or 0) for value in params.split(';')]
        if final == 'm':
            fg, bg, bold = _sgr(values, fg, bg, bold)
        elif final in 'Hf':
            row = max(0, (values[0] or 1) - 1)
            col = max(0, (values[1] if len(values) > 1 else 1) - 1)
        elif final == 'K':
            span = {0: range(col, cols), 1: range(0, col + 1),
                    2: range(0, cols)}[values[0]]
            erase((row, c) for c in span)
        elif final == 'J':
            assert values[0] == 0, 'only erase-below is used'
            erase([(row, c) for c in range(col, cols)]
                  + [(r, c) for r in range(row + 1, rows)
                     for c in range(cols)])
    write(text[end:])
    return grid


# ---------------------------------------------------------------------------
# The function itself
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('color', ['38;2;12;34;56', '48;2;78;90;12',
                                   '38;5;137', '48;5;22'])
def test_repeated_colors_shorten_without_rewriting_text_or_sharing_frame_state(color):
    code = f'\x1b[{color}m'
    original = f'{code}京{code}é{code} ⣷▄\x1b[0m'
    packed = _maps_paint.compact_colors(original)
    assert len(packed) < len(original)
    assert rendition_signature(packed) == rendition_signature(original)
    assert _maps_paint.compact_colors(original) == packed


@pytest.mark.parametrize('barrier', ['\x1b[0m', '\x1b[m', '\x1b[39m', '\x1b[49m',
                                     '\x1b[1m', '\x1b[22m', '\x1b[0;31;44m',
                                     '\x1b[3;4H', '\x1b[K', '\x00'])
def test_resets_attributes_and_cursor_controls_preserve_effective_colors(barrier):
    colors = '\x1b[38;2;12;34;56m\x1b[48;2;78;90;12m'
    original = f'{colors}a{colors}b{barrier}{colors}c{colors}d\x1b[0m'
    packed = _maps_paint.compact_colors(original)
    assert barrier + colors in packed
    assert rendition_signature(packed) == rendition_signature(original)


@pytest.mark.parametrize('control', ['\x1b7', '\x1b8', '\x1b]0;title\x07',
                                     '\x1bPpayload\x1b\\', '\x1b', '\x1b['])
def test_unfamiliar_controls_leave_the_whole_frame_untouched(control):
    colors = '\x1b[38;2;12;34;56m'
    original = f'{colors}a{colors}b{control}{colors}c{colors}d'
    assert _maps_paint.compact_colors(original) == original


def test_a_newline_is_not_a_barrier():
    # The live loop reaches the next row with a cursor address and an
    # erase, and neither resets the rendition, so a colour that spans
    # the row break is still the colour in effect.
    colors = '\x1b[38;2;12;34;56m\x1b[48;2;78;90;12m'
    original = f'{colors}a\n{colors}b'
    packed = _maps_paint.compact_colors(original)
    assert packed == f'{colors}a\nb'
    assert rendition_signature(packed) == rendition_signature(original)


def test_the_row_prefix_and_the_frame_carry_no_reset_of_their_own():
    # What makes the row break safe: frame_body writes no SGR at all —
    # every escape it adds is a cursor address or an erase — and
    # frame_paint resets only after the last row.
    body = frame_body('a\nb')
    assert all(match[3] != 'm' for match in CSI.finditer(body))
    whole = frame_paint('a\nb')
    assert whole.index('\x1b[0m') > whole.index(body)


def test_the_overlay_channel_is_copied_through_untouched():
    colors = '\x1b[38;2;12;34;56m'
    floating = f'\x1b[2;3H{colors}hover{colors}!\x1b[0m'
    original = f'{colors}a{colors}b\x00{floating}'
    packed = _maps_paint.compact_colors(original)
    assert len(packed) < len(original)
    assert packed.split('\x00')[1] == floating
    assert rendition_signature(packed) == rendition_signature(original)


@pytest.mark.parametrize('mode', ['truecolor', '256', '16', 'none'])
@pytest.mark.parametrize('street', [False, True])
def test_actual_map_composers_keep_their_rendition_in_every_color_mode(
        monkeypatch, mode, street):
    monkeypatch.setattr(_color, '_COLOR_MODE', mode)
    monkeypatch.setattr(_maps_paint, 'BOLD', '\x1b[1m' if mode != 'none' else '')
    monkeypatch.setattr(_maps_paint, 'RESET', '\x1b[0m' if mode != 'none' else '')
    fills = [[(24, 36, 48)] * 10 for _ in range(4)]
    layer = SimpleNamespace(dots=[[0, 0, 1, 1, 0, 0, 0, 0, 0, 0]] * 2,
                            color=[[(96, 128, 160)] * 10] * 2, ribbon=set())
    labels = {(4, 0): ('京', (200, 210, 220), True),
              (5, 0): ('', (200, 210, 220), False),
              (7, 0): ('é', (200, 210, 220), False)}
    if street:
        lines = _maps_paint.compose_map(fills, layer, labels, 10, 2,
                                        hot={(2, 0)}, hot_glyphs={(7, 0)})
    else:
        lines = _maps_paint.compose_terrain(None, fills, labels, 10, 2,
                                            strokes=[layer])
    original = '\n'.join(lines) + '\x00\x1b[2;3H\x1b[1mhover\x1b[0m'
    packed = _maps_paint.compact_colors(original)
    assert rendition_signature(packed) == rendition_signature(original)
    assert packed.split('\x00')[1] == original.split('\x00')[1]
    if mode in ('truecolor', '256'):
        assert len(packed) < len(original)
    else:
        assert packed == original


# ---------------------------------------------------------------------------
# Real frames, painted
# ---------------------------------------------------------------------------
def _snapshot_frames(monkeypatch, compact):
    """The pinned street, terrain and globe frames, rendered here.

    The snapshot module already builds a view out of hand-made tiles and
    a synthetic hemisphere; borrowing its cases is how these tests get a
    map that a real composer painted without a network.  `compact` False
    renders the frame as it was before this pass existed.
    """
    import test_render_snapshots as snapshots
    from linecast import maps

    if not compact:
        monkeypatch.setattr(maps, 'compact_colors', lambda out: out)
    frames = {}
    monkeypatch.setattr(snapshots, '_compare_or_create',
                        lambda name, out: frames.__setitem__(
                            name, out.replace('\\e', '\x1b')))
    case = snapshots.TestMapsSnapshot()
    case.test_maps_street_80x24()
    case.test_maps_terrain_80x24()
    case.test_maps_globe_80x24()
    return frames


@pytest.fixture(scope='module')
def frames():
    """(uncompacted, compacted) frames, each rendered under its own patches."""
    rendered = []
    for compact in (False, True):
        with pytest.MonkeyPatch.context() as patcher:
            rendered.append(_snapshot_frames(patcher, compact))
    return tuple(rendered)


@pytest.mark.parametrize('name', ['maps_street_80x24.txt',
                                  'maps_terrain_80x24.txt',
                                  'maps_globe_80x24.txt'])
def test_a_real_frame_paints_the_same_cells_after_compaction(frames, name):
    raw, compacted = (side[name] for side in frames)
    assert compacted == _maps_paint.compact_colors(raw), 'render_map compacts'
    assert len(compacted) < len(raw)
    assert rendition_signature(compacted) == rendition_signature(raw)
    # and through the live loop, which addresses and clears every row
    assert painted(frame_paint(compacted), rows=26) == \
        painted(frame_paint(raw), rows=26)


def test_a_compacted_frame_is_already_compact(frames):
    _raw, compacted = frames
    for frame in compacted.values():
        assert _maps_paint.compact_colors(frame) == frame
