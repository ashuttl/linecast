"""Read-only, one-frame ANSI color-run experiment; no timing claim."""
import argparse
import json
import os
import re
import socket
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
args = parser.parse_args()

os.environ['LINECAST_CACHE_DIR'] = tempfile.mkdtemp(prefix='linecast-ansi-')
os.environ['LINECAST_CONFIG_DIR'] = tempfile.mkdtemp(prefix='linecast-ansi-config-')
os.environ['LINECAST_COLOR'] = 'truecolor'
os.environ['LINECAST_THEME'] = 'off'
os.environ.pop('NO_COLOR', None)
sys.path.insert(0, str(args.repo / 'src'))

def offline(*args, **kwargs):
    raise OSError('network disabled for ANSI probe')

socket.socket.connect = socket.create_connection = offline
from linecast import _color, maps, moon, sky  # noqa: E402
from linecast._framebuffer import Framebuffer  # noqa: E402
from linecast._runtime import RuntimeConfig  # noqa: E402

_color._COLOR_MODE = 'truecolor'
maps.get_terminal_size = moon.get_terminal_size = sky.get_terminal_size = lambda: (120, 40)
moon.install_banner = sky.install_banner = lambda: ''
runtime = RuntimeConfig(live=True, icons='plain', lang='en', oneline=False)
base = datetime(2026, 9, 7, 23, 0, tzinfo=ZoneInfo('America/New_York'))
CSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')

def pieces(s):
    pos = 0
    for match in CSI.finditer(s):
        if match.start() > pos:
            yield s[pos:match.start()], False
        yield match.group(), True
        pos = match.end()
    if pos < len(s):
        yield s[pos:], False

def color_slot(s):
    if not s.endswith('m'):
        return None
    p = s[2:-1].split(';')
    if p[0] in ('38', '48') and ((len(p) == 5 and p[1] == '2') or
                                  (len(p) == 3 and p[1] == '5')):
        return 'fg' if p[0] == '38' else 'bg'
    if len(p) == 1 and p[0].isdigit():
        n = int(p[0])
        if 30 <= n <= 37 or 90 <= n <= 97 or n == 39:
            return 'fg'
        if 40 <= n <= 47 or 100 <= n <= 107 or n == 49:
            return 'bg'
    return None

def compact(s):
    colors, out, removed = {}, [], 0
    for token, escape in pieces(s):
        if escape:
            slot = color_slot(token)
            if slot:
                if colors.get(slot) == token:
                    removed += 1
                    continue
                colors[slot] = token
            elif token in ('\x1b[0m', '\x1b[m'):
                colors.clear()
            elif not re.fullmatch(r'\x1b\[(1|2|3|4|7|9|22|23|24|27|29)m', token):
                colors.clear()  # unfamiliar escapes are a conservative barrier
        out.append(token)
    return ''.join(out), removed

def visible_signature(s):
    """Glyph order, effective colors/attributes, and non-SGR controls."""
    colors, attrs, output = {}, set(), []
    for token, escape in pieces(s):
        if not escape:
            output.extend((ch, tuple(sorted(colors.items())), tuple(sorted(attrs)))
                          for ch in token)
            continue
        slot = color_slot(token)
        if slot:
            colors[slot] = token
        elif token in ('\x1b[0m', '\x1b[m'):
            colors.clear()
            attrs.clear()
        elif token in ('\x1b[1m', '\x1b[2m', '\x1b[3m', '\x1b[4m', '\x1b[7m', '\x1b[9m'):
            attrs.add(int(token[2:-1]))
        elif token in ('\x1b[22m', '\x1b[23m', '\x1b[24m', '\x1b[27m', '\x1b[29m'):
            n = int(token[2:-1])
            attrs.difference_update((1, 2) if n == 22 else (n - 20,))
        else:
            output.append(('control', token, tuple(sorted(colors.items())), tuple(sorted(attrs))))
    return output

turn = moon.Turn()
turn.drag(12, 3)
frames = {
    'uniform_118x30': '\n'.join(Framebuffer(118, 30, (20, 25, 30)).render()),
    'moon_120x40': moon.render(base, 40.7128, -74.0060, runtime, fullscreen=True,
                            calendar_name='almanac', turn=turn),
    'sky_120x40': sky.render(base, 40.7128, -74.0060, runtime,
                           sky.View(180, 30, 100, 2), fullscreen=True),
    'globe_terrain_120x40': maps.render_map(43.66, -70.2, 'Benchmark', 130,
                                         marker=(43.66, -70.2), runtime=runtime,
                                         block=True, view='terrain'),
}
for name, original in frames.items():
    packed, removed = compact(original)
    assert visible_signature(packed) == visible_signature(original), name
    before, after = len(original.encode()), len(packed.encode())
    print(json.dumps(dict(view=name, before=before, after=after,
                          reduction_pct=round((1-after/before)*100, 2),
                          removed_sgr=removed, same_glyphs_colors_attributes=True)))
