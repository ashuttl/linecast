"""The controls shared by the live views, with one modal and one layout."""

import math
import re

from linecast import _theme
from linecast._graphics import RESET, bg, fg, visible_len
from linecast._help_i18n import hs
from linecast._maps_i18n import ms
from linecast._textwidth import char_widths


def hint(lang='en', width=80):
    """A persistent, translated invitation; the key survives tight layouts."""
    label = f"? {hs('hint_keys', lang)}"
    return label if visible_len(label) <= width else ('?' if width > 0 else '')


def footer(line, width, lang='en'):
    """Add help in the spare right margin without truncating the readout.

    Callers with a dense footer budget for hint() before choosing their
    content. Trailing padding is expendable; text and credits are not.
    """
    # live_loop clears from the cursor after each row. At the right
    # margin a terminal can leave that cursor on the last printed cell,
    # so that cell must be air, never the hint's final letter.
    width = max(0, width - 1)
    line = re.sub(r' +(?=(?:\033\[[0-9;]*m)*$)', '', line)
    used = visible_len(line)
    label = hint(lang, width - used - 2)
    if not label:
        return line
    ink = _theme.ensure_contrast(_theme.surface_bg(0.55), _theme.theme_bg, 4.5)
    return f"{line}{RESET}{' ' * (width - used - visible_len(label))}{fg(*ink)}{label}{RESET}"


def paint_text(fb, overlays, text, x, row, color=None):
    """Readable text on the image's own cells, including wide and combining glyphs."""
    color = color or _theme.surface_bg(0.55)
    prev = None
    for ch, width in zip(text, char_widths(text)):
        if width == 0:
            if prev is not None:
                base, ink, bold = overlays[prev]
                overlays[prev] = (base + ch, ink, bold)
            continue
        if x < 0 or x + width > fb.graph_w or not 0 <= row < fb.graph_h:
            break
        cell = fb.cell_bg(x, row)
        ink = _theme.ensure_contrast(color, cell, 4.5)
        if _theme.contrast_ratio(ink, cell) < 4.5:
            ink = _theme.best_contrast(((0, 0, 0), (255, 255, 255)), cell, 4.5)
        overlays[(x, row)] = (ch, ink, False)
        prev = (x, row)
        for extra in range(1, width):
            overlays[(x + extra, row)] = ('', ink, False)
        x += width


def paint_hint(fb, overlays, lang='en', rows=None):
    """Tuck help into a free image corner, keeping existing labels intact."""
    rows = (fb.graph_h - 1, 0, fb.graph_h - 2, 1) if rows is None else rows
    for label in (hint(lang, fb.graph_w - 2), '?'):
        width = visible_len(label)
        for row in rows:
            for x in (fb.graph_w - width - 1, 1):
                cells = range(x - 1, x + width + 1)
                if x < 1 or any((c, row) in overlays for c in cells):
                    continue
                paint_text(fb, overlays, f' {label} ', x - 1, row)
                return True
    return False

# Keys are the spellings a user types, not the live loop's decoded actions.
CONTROLS = {
    'weather': [('wheel / ←→', 'forecast'), ('space / n', 'now'),
                ('hover', 'help_hover'), ('click', 'alert'), ('o', 'browser'),
                ('r', 'refresh')],
    'tides': [('wheel / ←→', 'time30'), ('space / n', 'now'), ('hover', 'help_hover')],
    'sunshine': [('wheel / ←→', 'time15'), ('space / n', 'now'), ('v / y', 'year')],
    'sunshine_year': [('hover', 'sun_times'), ('v / y', 'year')],
    'moon': [('wheel / ←→', 'time15'), ('space / n', 'now'),
             ('drag', 'turn_moon'), ('v', 'calendar')],
    'moon_calendar': [('wheel / ←→', 'months'), ('space / n', 'now'),
                      ('hover', 'moon_times'), ('click', 'day'), ('v', 'calendar')],
    'sky': [('drag / wasd', 'look'), ('wheel / ←→', 'time15'), ('+ -', 'help_zoom'),
            ('space / n', 'now'), ('hover', 'help_hover'), ('/', 'help_search'),
            ('enter', 'target'), ('c', 'figures'), ('t', 'cultures'),
            ('p', 'play_time'), ('1–8', 'compass'), ('9', 'zenith'), ('m', 'moon')],
    'radar': [('drag / wasd', 'help_pan'), ('wheel / ←→', 'frames'), ('+ -', 'help_zoom'),
              ('space / n', 'play'), ('hover', 'alert'), ('c', 'temperature'),
              ('W', 'wind'), ('t', 'theme'), ('S', 'satellite')],
}


def entries(view, lang):
    return [(mark, ms(key, lang) if key.startswith('help_') else hs(key, lang))
            for mark, key in CONTROLS[view]] + [
                ('?', ms('help_keys', lang)), ('q', ms('help_quit', lang))]


def fit(text, width):
    """Clip plain text by terminal cells, keeping combining marks."""
    if visible_len(text) <= width:
        return text
    out = ''
    for ch in text:
        if visible_len(out + ch) > width - 1:
            break
        out += ch
    return out + '…' if width > 0 else ''


def wrap(text, width):
    """Wrap words, or long unspaced labels, without splitting wide cells."""
    out, line = [], ''
    for word in text.split():
        trial = f'{line} {word}'.strip()
        if visible_len(trial) <= width:
            line = trial
            continue
        if line:
            out.append(line)
        line = ''
        for ch in word:
            if visible_len(line + ch) > width:
                out.append(line)
                line = ''
            line += ch
    if line:
        out.append(line)
    return out


def panel(content, cols, rows, lang='en', page=0):
    """A centered panel and its page count. Short windows retain every key."""
    if cols < 16 or rows < 5:
        note = fit('? / esc', cols)
        return f'\033[1;1H{RESET}{note}', 1
    label_width = max((visible_len(entry[1]) for entry in content if entry), default=0)
    width = min(cols - 4, max(47, label_width + 17))
    key_width = 12 if width >= 36 else 0
    laid_out = []
    for entry in content:
        if entry is None:
            laid_out.append(None)
            continue
        mark, text = entry
        if mark and key_width:
            pieces = wrap(text, width - key_width - 3)
            laid_out.extend((mark if i == 0 else ' ', line)
                            for i, line in enumerate(pieces))
        else:
            if mark:
                laid_out.append(('', mark))
            laid_out.extend(('', line) for line in wrap(text, width - 2))
    budget = rows - 4
    if len(laid_out) > budget:
        laid_out = [entry for entry in laid_out if entry is not None]
    pages = max(1, math.ceil(len(laid_out) / budget))
    page = min(max(0, page), pages - 1)
    shown = laid_out[page * budget:(page + 1) * budget]
    surface = _theme.surface_bg(0.10)
    ink = _theme.ensure_contrast(_theme.theme_fg, surface, 4.5)
    dim = _theme.ensure_contrast(_theme.surface_bg(0.55), surface, 3.0)
    key_ink = _theme.ensure_contrast(_theme.theme_ansi[3], surface, 4.5)

    def border(left, text, right):
        text = fit(' ' + text + ' ', width)
        pad = width - visible_len(text)
        return (f'{bg(*surface)}{fg(*dim)}{left}' + '─' * (pad // 2) + text
                + '─' * (pad - pad // 2) + right + RESET)

    title = ms('help_title', lang)
    if pages > 1:
        title += f'  ←→ {page + 1}/{pages}'
    lines = [border('╭', title, '╮')]
    for entry in shown:
        if entry is None:
            body = ' ' * width
        else:
            mark, text = entry
            if mark:
                mark = fit(mark, key_width)
                label = fit(text, width - key_width - 3)
                body = (f' {fg(*key_ink)}{mark}' + ' ' * (key_width - visible_len(mark))
                        + f' {fg(*ink)}{label}')
            else:
                body = f' {fg(*dim)}{fit(text, width - 2)}'
            body += ' ' * (width - visible_len(body))
        lines.append(f'{bg(*surface)}{fg(*dim)}│{body}{fg(*dim)}│{RESET}')
    lines.append(border('╰', ms('help_close', lang), '╯'))
    top = max(1, (rows - len(lines)) // 2 + 1)
    left = max(1, (cols - width - 2) // 2 + 1)
    return ''.join(f'\033[{top + i};{left}H{line}' for i, line in enumerate(lines)), pages


class HelpPanel:
    """Help owns input while open; a command dismisses it and passes through."""

    def __init__(self, view, lang='en', content=None):
        self.view = view
        self.lang = lang
        self.content = content
        self.open = False
        self.page = 0
        self.pages = 1

    def handle(self, action):
        if action == 'key:?':
            self.open = not self.open
            self.page = 0
            return True
        if not self.open:
            return False
        if action in ('quit', 'escape'):
            self.open = False
            return True
        if isinstance(action, tuple):
            if action[0] == 'mouse' and action[1] & 64:
                self.page = (self.page + (1 if action[1] & 1 else -1)) % self.pages
            return True  # never click or drag the view through the panel
        if action in ('fwd', 'back') and self.pages > 1:
            self.page = (self.page + (1 if action == 'fwd' else -1)) % self.pages
            return True
        if action is not None:
            self.open = False
        return False

    def render(self, cols, rows):
        view = self.view() if callable(self.view) else self.view
        content = (self.content(cols, rows) if self.content is not None
                   else entries(view, self.lang))
        out, self.pages = panel(content, cols, rows, self.lang, self.page)
        self.page = min(self.page, self.pages - 1)
        return out
