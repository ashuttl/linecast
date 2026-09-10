"""Color compaction preserves glyphs, effective rendition, and controls."""

import re
from types import SimpleNamespace

import pytest

from linecast import _color, _maps_paint


CSI = re.compile(r'\x1b\[([0-?]*)([ -/]*)([@-~])')


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
        values = [int(value or 0) for value in match[1].split(';')]
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
    signature.extend((char, fg, bg, bold) for char in output[end:])
    signature.append(('final rendition', fg, bg, bold))
    return signature


@pytest.mark.parametrize('color', ['38;2;12;34;56', '48;2;78;90;12',
                                  '38;5;137', '48;5;22'])
def test_repeated_colors_shorten_without_rewriting_text_or_sharing_frame_state(color):
    code = f'\x1b[{color}m'
    original = f'{code}京{code}e\u0301{code} ⣷▄\x1b[0m'
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


@pytest.mark.parametrize('mode', ['truecolor', '256', '16', 'none'])
@pytest.mark.parametrize('street', [False, True])
def test_actual_map_composers_keep_their_rendition_in_every_color_mode(monkeypatch, mode, street):
    monkeypatch.setattr(_color, '_COLOR_MODE', mode)
    monkeypatch.setattr(_maps_paint, 'BOLD', '\x1b[1m' if mode != 'none' else '')
    monkeypatch.setattr(_maps_paint, 'RESET', '\x1b[0m' if mode != 'none' else '')
    fills = [[(24, 36, 48)] * 10 for _ in range(4)]
    layer = SimpleNamespace(dots=[[0, 0, 1, 1, 0, 0, 0, 0, 0, 0]] * 2,
                            color=[[(96, 128, 160)] * 10] * 2, ribbon=set())
    labels = {(4, 0): ('京', (200, 210, 220), True),
              (5, 0): ('', (200, 210, 220), False),
              (7, 0): ('e\u0301', (200, 210, 220), False)}
    if street:
        lines = _maps_paint.compose_map(fills, layer, labels, 10, 2,
                                        hot={(2, 0)}, hot_glyphs={(7, 0)})
    else:
        lines = _maps_paint.compose_terrain(None, fills, labels, 10, 2, strokes=[layer])
    original = '\n'.join(lines) + '\x00\x1b[2;3H\x1b[1mhover\x1b[0m'
    packed = _maps_paint.compact_colors(original)
    assert rendition_signature(packed) == rendition_signature(original)
    assert packed.split('\x00')[1] == original.split('\x00')[1]
    if mode in ('truecolor', '256'):
        assert len(packed) < len(original)
    else:
        assert packed == original
