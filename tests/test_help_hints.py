"""Live help stays legible, inside the margin, and out of print output."""

from datetime import datetime, timedelta, timezone
import re

import pytest

from linecast import _help, _theme
from linecast._framebuffer import Framebuffer
from linecast._i18n import LANGUAGE_CODES
from linecast._runtime import RuntimeConfig
from linecast._textwidth import visible_len

NOW = datetime(2026, 9, 6, 21, 15, tzinfo=timezone(timedelta(hours=-4)))


def plain(text):
    return re.sub(r'\033\[[0-9;]*[a-zA-Z]', '', text.split('\x00')[0])


def test_help_invitation_is_not_the_panels_self_reference():
    assert _help.hint('en') == '? keys'
    assert _help.hint('fr') == '? touches'
    assert _help.hint('ja') == '? キー'
    assert _help.hint('en', 1) == '?'


@pytest.mark.parametrize('lang', LANGUAGE_CODES)
@pytest.mark.parametrize('width', [8, 20, 40, 80, 140])
def test_footer_keeps_a_clear_terminal_margin(lang, width):
    text = '風' if lang == 'ja' else 'x'
    output = _help.footer(text + ' ' * (width - visible_len(text)), width, lang)
    shown = plain(output)
    assert shown.startswith(text)
    assert '?' in shown
    assert visible_len(shown) <= width - 1
    assert shown.endswith(_help.hint(lang, width - visible_len(text) - 3))


def test_full_footer_never_erases_a_credit_to_add_help():
    assert plain(_help.footer('source credit', 13)) == 'source credit'


@pytest.mark.parametrize('background', [(12, 16, 25), (128, 140, 150), (230, 235, 245)])
@pytest.mark.parametrize('text', ['? keys', '? キー', '? ปุ่มลัด', 'e\u0301'])
def test_image_text_preserves_pixels_and_has_readable_ink(background, text):
    fb = Framebuffer(30, 4, background)
    original = [row[:] for row in fb.fb]
    overlays = {}
    _help.paint_text(fb, overlays, text, 1, 2)
    assert fb.fb == original
    assert ''.join(v[0] for v in overlays.values()) == text
    assert len(overlays) == visible_len(text)
    assert all(_theme.contrast_ratio(v[1], background) >= 4.5 for v in overlays.values())


def test_corner_hint_does_not_overwrite_an_existing_label():
    fb = Framebuffer(30, 4)
    overlays = {(26, 3): ('X', (255, 255, 255), False)}
    assert _help.paint_hint(fb, overlays)
    assert overlays[(26, 3)][0] == 'X'
    assert '? keys' in plain('\n'.join(fb.render(overlays)))


@pytest.mark.parametrize('view', ['sky', 'sunshine', 'sunshine_year', 'moon', 'moon_calendar'])
@pytest.mark.parametrize('lang', ['en', 'ja', 'th'])
@pytest.mark.parametrize('size', [(40, 18), (80, 24), (140, 40)])
def test_live_image_views_offer_help_without_adding_rows(monkeypatch, view, lang, size):
    from linecast import sky, sunshine, moon, _sunshine_year, _moon_calendar
    cols, rows = size
    runtime = RuntimeConfig(live=True, icons='plain', lang=lang, oneline=False)
    for module in (sky, sunshine, moon, _sunshine_year, _moon_calendar):
        monkeypatch.setattr(module, 'get_terminal_size', lambda: size)
    if view == 'sky':
        output = sky.render(NOW, 43.68, -70.32, runtime, sky.View(180, 90, 145, 2),
                            fullscreen=True, location_label='Westbrook', today=NOW.date())
    elif view == 'sunshine':
        output = sunshine.render(43.68, -70.32, 249, 21.25, fullscreen=True, runtime=runtime)
    elif view == 'sunshine_year':
        output = _sunshine_year.render_year(43.68, -70.32, NOW, runtime, fullscreen=True)
    elif view == 'moon':
        output = moon.render(NOW, 43.68, -70.32, runtime, fullscreen=True)
    else:
        output = _moon_calendar.render_calendar(NOW, 43.68, -70.32, runtime, fullscreen=True)
    body = plain(output)
    assert '?' in body
    assert len(body.splitlines()) == rows
    assert all(visible_len(line) <= cols for line in body.splitlines())


@pytest.mark.parametrize('hour', [1, 13, 21])
def test_sky_status_uses_the_finished_image_background(monkeypatch, hour):
    from linecast import sky
    monkeypatch.setattr(sky, 'get_terminal_size', lambda: (100, 30))
    # Other tests reload linecast modules; patch the class this renderer
    # actually owns rather than a previous import's Framebuffer.
    original = sky.Framebuffer.render
    captures = []

    def capture(self, overlays=None):
        captures.append((self, dict(overlays or {})))
        return original(self, overlays)

    monkeypatch.setattr(sky.Framebuffer, 'render', capture)
    moment = NOW.replace(hour=hour)
    runtime = RuntimeConfig(live=True, icons='plain', lang='en', oneline=False)
    output = sky.render(moment, 43.68, -70.32, runtime,
                        sky.View(180, 35, 110, 2), fullscreen=True,
                        location_label='Westbrook', today=NOW.date())
    fb, overlays = captures[-1]
    row = fb.graph_h - 1
    footer = plain(output).splitlines()[-1]
    assert 'Westbrook' in footer and '? keys' in footer
    assert fb.graph_h == 30
    # The help text is readable over the actual final image, and gaps
    # between the status groups remain image cells rather than a bar.
    start = fb.graph_w - len('? keys')
    for x in range(start, fb.graph_w):
        assert _theme.contrast_ratio(overlays[(x, row)][1], fb.cell_bg(x, row)) >= 4.5
    assert any((x, row) not in overlays for x in range(20, start))


def test_static_sky_does_not_advertise_inactive_controls(monkeypatch):
    from linecast import sky
    monkeypatch.setattr(sky, 'get_terminal_size', lambda: (80, 24))
    runtime = RuntimeConfig(live=False, icons='plain', lang='en', oneline=False)
    output = sky.render(NOW, 43.68, -70.32, runtime,
                        sky.View(180, 30, 110, 2), location_label='Westbrook')
    assert '? keys' not in plain(output)


@pytest.mark.parametrize('view', ['maps', 'radar'])
@pytest.mark.parametrize('lang', ['en', 'ja', 'th'])
@pytest.mark.parametrize('cols', [40, 80, 140])
def test_map_and_radar_footer_hints_end_before_the_erase_column(monkeypatch, view, lang, cols):
    from types import SimpleNamespace
    from linecast import maps, radar
    runtime = RuntimeConfig(live=True, icons='plain', lang=lang, oneline=False)
    module = maps if view == 'maps' else radar
    monkeypatch.setattr(module, 'get_terminal_size', lambda: (cols, 24))
    if view == 'maps':
        monkeypatch.setattr(maps, '_render_terrain',
                            lambda *a, **kw: ([''] * 22, '', '', False, None))
        output = maps.render_map(43.68, -70.32, 'Westbrook', 1, runtime=runtime)
    else:
        source = SimpleNamespace(attribution='LibreWXR', current_frames=lambda: [
            SimpleNamespace(time=NOW, future=False)])
        monkeypatch.setattr(radar._radar_frames, '_source', source)
        monkeypatch.setattr(radar, '_get_basemap', lambda *a: SimpleNamespace(
            city_overlays=lambda **kw: {}))
        monkeypatch.setattr(radar, '_load_frame', lambda *a: ([], 0))
        monkeypatch.setattr(radar._radar_warnings, 'covers', lambda *a: False)
        monkeypatch.setattr(radar, 'compose', lambda *a, **kw: [''] * 22)
        monkeypatch.setattr(radar, 'has_radar', lambda *a: True)
        output = radar.render_radar(43.68, -70.32, 'Westbrook', 1, runtime=runtime)
    foot = plain(output).splitlines()[-1]
    assert foot.endswith(_help.hint(lang) + ' ')
    assert visible_len(foot) == cols
    # Emulate the right-margin clear: only the padding cell is erased.
    assert foot[:-1].endswith(_help.hint(lang))


def test_radar_help_describes_warning_hover():
    entries = dict(_help.entries('radar', 'en'))
    assert entries['hover'] == 'read an alert'
