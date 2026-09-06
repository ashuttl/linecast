"""Shared help must not leak keystrokes or mouse gestures into a live view."""

import io
import re
from types import SimpleNamespace

import pytest

from linecast import _framebuffer, _help, _help_i18n, _live
from linecast._graphics import visible_len
from linecast._i18n import LANGUAGE_CODES


def lines(panel):
    return [re.sub(r'\033\[[^m]*m', '', row)
            for row in re.split(r'\033\[\d+;\d+H', panel)[1:]]


@pytest.mark.parametrize('view', _help.CONTROLS)
@pytest.mark.parametrize('lang', LANGUAGE_CODES)
def test_every_view_has_translated_controls(view, lang):
    assert set(_help_i18n._STRINGS[lang]) == set(_help_i18n._STRINGS['en'])
    help_panel = _help.HelpPanel(view, lang)
    output = ''.join(lines(help_panel.render(160, 50)))
    for key, text in _help.entries(view, lang):
        assert key in output and text in output


@pytest.mark.parametrize('cols,rows', [(8, 3), (20, 8), (40, 12), (80, 24), (160, 50)])
@pytest.mark.parametrize('lang', LANGUAGE_CODES)
def test_panel_fits_terminal_cells(cols, rows, lang):
    help_panel = _help.HelpPanel('sky', lang)
    for _ in range(30):
        output = help_panel.render(cols, rows)
        rendered = lines(output)
        assert all(visible_len(line) <= cols for line in rendered)
        positions = re.findall(r'\033\[(\d+);(\d+)H', output)
        assert len(positions) <= rows
        for (row, col), line in zip(positions, rendered):
            assert 1 <= int(row) <= rows
            assert 1 <= int(col) <= cols
            assert int(col) - 1 + visible_len(line) <= cols
        help_panel.page += 1
        if help_panel.page >= help_panel.pages:
            break


def test_all_controls_remain_reachable_in_short_windows():
    help_panel = _help.HelpPanel('sky')
    output = help_panel.render(100, 8)
    assert help_panel.pages > 1
    for page in range(1, help_panel.pages):
        help_panel.page = page
        output += help_panel.render(100, 8)
    text = ''.join(lines(output))
    for key, label in _help.entries('sky', 'en'):
        assert key in text and label in text


def test_help_follows_the_active_view_and_clamps_after_resize():
    state = ['moon']
    help_panel = _help.HelpPanel(lambda: state[0])
    assert 'turn the Moon' in help_panel.render(100, 30)
    state[0] = 'moon_calendar'
    output = help_panel.render(100, 30)
    assert 'move by one month' in output and 'turn the Moon' not in output
    help_panel.render(40, 8)
    help_panel.page = help_panel.pages - 1
    help_panel.render(100, 30)
    assert help_panel.page == 0 and help_panel.pages == 1


def run_loop(monkeypatch, actions, **hooks):
    """Drive the actual live loop with decoded input and a fake terminal."""
    terminal = SimpleNamespace(fd=0, install=lambda: None, set_cbreak=lambda: None,
                               drain=lambda: None, close=lambda: None,
                               wait=lambda timeout: 'input')
    monkeypatch.setattr(_live._term, 'LiveTerminal', lambda fd: terminal)
    monkeypatch.setattr(_live._term, 'wait_readable', lambda fd, timeout: False)
    monkeypatch.setattr(_live.sys, 'stdin', SimpleNamespace(fileno=lambda: 0))
    output = io.StringIO()
    monkeypatch.setattr(_live.sys, 'stdout', output)
    monkeypatch.setattr(_framebuffer, 'get_terminal_size', lambda: (80, 24))
    inputs = iter(actions)
    modes = []

    def read(fd, text=False):
        modes.append(text)
        return next(inputs)

    monkeypatch.setattr(_live, '_read_key', read)
    frames = []
    help_panel = _help.HelpPanel('sky')

    def render(**kw):
        frames.append(dict(kw, helping=help_panel.open))
        return _live.overlay('body', 'TOOLTIP'), {3: 0}

    _live.live_loop(render, mouse=True, help_panel=help_panel, **hooks)
    return frames, output.getvalue(), modes


def test_help_dismissal_and_mouse_do_not_change_the_view(monkeypatch):
    gestures = []
    frames, output, _ = run_loop(monkeypatch, [
        'key:?', ('mouse', 0, 4, 4, False), ('mouse', 0, 4, 4, True),
        ('mouse', 64, 4, 4, False), 'quit', 'quit',
    ], on_drag=lambda *args: gestures.append(args),
       on_wheel=lambda *args: gestures.append(args),
       on_click=lambda *args: gestures.append(args))
    assert not gestures
    assert all(f['offset_minutes'] == 0 and f['active_alert'] is None for f in frames)
    assert [f['helping'] for f in frames] == [False, True, True, True, True, False]
    assert '\033[?1003l' in output
    assert '\033[?1003hTOOLTIP' in output  # motion and the caller's overlay return
    assert '\033[?1049l' in output  # terminal restored on exit


@pytest.mark.parametrize('close', ['escape', 'key:?', 'quit'])
def test_all_dismiss_keys_leave_the_app_running(monkeypatch, close):
    frames, _, _ = run_loop(monkeypatch, ['key:?', close, 'quit'])
    assert [f['helping'] for f in frames] == [False, True, False]


def test_shortcut_closes_help_and_runs_once(monkeypatch):
    seen = []
    frames, _, _ = run_loop(monkeypatch, ['key:?', 'key:v', 'quit'],
                            on_action=lambda key: seen.append(key) or True)
    assert seen == ['v']
    assert not frames[-1]['helping']


def test_unbound_key_still_erases_help(monkeypatch):
    frames, _, _ = run_loop(monkeypatch, ['key:?', 'key:d', 'quit'],
                            on_action=lambda key: False)
    assert [f['helping'] for f in frames] == [False, True, False]


def test_question_mark_in_search_stays_text(monkeypatch):
    text = []

    def intercept(action):
        if action.startswith('char:'):
            text.append(action[5:])
            return True
        return False

    frames, _, modes = run_loop(monkeypatch, ['char:?', 'quit'],
                                text_mode=lambda: True, intercept=intercept)
    assert text == ['?'] and all(modes)
    assert all(not f['helping'] for f in frames)


def test_help_returns_to_an_open_alert(monkeypatch):
    frames, _, _ = run_loop(monkeypatch, [
        ('mouse', 0, 4, 4, False), 'key:?', 'quit', 'quit', 'quit',
    ])
    assert [f['active_alert'] for f in frames] == [None, 0, 0, 0, None]


def test_opening_help_finishes_an_existing_drag_once(monkeypatch):
    gestures = []
    run_loop(monkeypatch, [
        ('mouse', 0, 5, 5, False), ('mouse', 32, 9, 8, False),
        'key:?', ('mouse', 0, 9, 8, True), 'escape', 'quit',
    ], on_drag=lambda *args: gestures.append(args) or True)
    assert gestures == [(4, 3, False), (4, 3, True)]


def test_short_help_pages_use_arrows_and_wheel_without_closing():
    help_panel = _help.HelpPanel('sky')
    help_panel.handle('key:?')
    help_panel.render(80, 8)
    assert help_panel.handle('fwd') and help_panel.page == 1
    assert help_panel.handle('back') and help_panel.page == 0
    assert help_panel.handle(('mouse', 65, 1, 1, False)) and help_panel.page == 1
    assert help_panel.open


def test_wrapping_preserves_unspaced_and_combining_text():
    for text in ('星空の文化を選ぶ', 'ก้าวไปยังเวลาที่ดวงจันทร์ขึ้น', 'e\u0301' * 8):
        wrapped = _help.wrap(text, 4)
        assert ''.join(wrapped) == text
        assert all(visible_len(row) <= 4 for row in wrapped)
