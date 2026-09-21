"""Location selection: persistence, panel input, and competing forecast workers."""

import json
import re
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from linecast import weather
from linecast._graphics import visible_len
from linecast._maps_search import Result
from linecast._runtime import WeatherRuntime
from linecast._weather_locations import LocationPicker, LocationSearch, RecentLocations
from linecast._weather_sections import render_header


def place(name='Paris', lat=48.85, lon=2.35):
    return Result(name, 'France', lat, lon, 'city')


def app():
    return weather.WeatherApp({'old': 1}, [{'old': 1}], {'old': 1}, 43, -70,
                              SimpleNamespace(lang='en'), location_name='Portland',
                              country='US', historical={'old': 1})


def finish(view):
    view._location_worker.join(2)
    assert not view._location_worker.is_alive()
    with view._state_lock:
        view._finish_location()


def test_recent_locations_survive_restart_deduplicate_and_cap_at_ten():
    recent = RecentLocations()
    for i in range(12):
        recent.remember(place(str(i), i, i))
    recent.remember(place('renamed', 5.000001, 5))
    loaded = RecentLocations()
    assert [p.name for p in loaded.places] == ['renamed', '11', '10', '9', '8',
                                             '7', '6', '4', '3', '2']
    loaded.clear()
    assert not RecentLocations().places


def test_the_old_weather_only_list_moves_to_the_shared_name():
    recent = RecentLocations()
    old = recent.path.with_name('weather-locations.json')
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(json.dumps([{'name': 'Paris', 'lat': 48.86, 'lon': 2.35}]))
    loaded = RecentLocations()
    assert [p.name for p in loaded.places] == ['Paris']
    assert loaded.path.name == 'locations.json' and loaded.path.exists()
    assert not old.exists()


def test_the_shared_list_wins_over_a_leftover_old_one():
    recent = RecentLocations()
    recent.remember(place('Portland', 43.66, -70.25))
    old = recent.path.with_name('weather-locations.json')
    old.write_text(json.dumps([{'name': 'Paris', 'lat': 48.86, 'lon': 2.35}]))
    assert [p.name for p in RecentLocations().places] == ['Portland']


def test_an_old_list_that_cannot_move_is_read_in_place():
    recent = RecentLocations()
    old = recent.path.with_name('weather-locations.json')
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(json.dumps([{'name': 'Paris', 'lat': 48.86, 'lon': 2.35}]))
    with patch('linecast._weather_locations.os.replace', side_effect=OSError('read-only')):
        assert [p.name for p in RecentLocations().places] == ['Paris']
    assert old.exists()


def test_malformed_history_and_bad_entries_are_ignored():
    recent = RecentLocations()
    recent.path.parent.mkdir(parents=True, exist_ok=True)
    recent.path.write_text('not json')
    assert RecentLocations().places == []
    recent.path.write_text(json.dumps([None, {}, {'name': [], 'lat': 0, 'lon': 0},
                                      {'name': 'bad', 'lat': 'nan', 'lon': 0},
                                      {'name': 'bad', 'lat': 91, 'lon': 0},
                                      {'name': 'ok', 'lat': 1, 'lon': 2}]))
    assert [p.name for p in RecentLocations().places] == ['ok']


def test_unwritable_history_keeps_session_choices():
    recent = RecentLocations()
    with patch('linecast._cache.write_bytes_atomic', side_effect=PermissionError):
        recent.remember(place())
    assert recent.places[0].name == 'Paris'


def test_menu_keyboard_clear_and_search():
    picker = LocationPicker('en')
    picker.start()
    assert [key for key, _label in picker.items()] == ['add']
    picker.recent.remember(place())
    picker.handle('back', 0, 0)
    picker.handle('back', 0, 0)
    picker.handle('key:enter', 0, 0)
    assert picker.open and not picker.recent.places
    picker.handle('key:enter', 0, 0)
    assert picker.search.open and not picker.open
    picker.handle('escape', 0, 0)
    assert not picker.active


def test_menu_click_uses_drawn_rows_and_closes_outside():
    picker = LocationPicker('en')
    picker.recent.remember(place())
    picker.start()
    picker.overlay(80, 24, (0, 0))
    selected = picker.click(75, 2)
    assert selected.name == 'Paris' and not picker.active
    picker.start()
    picker.overlay(80, 24, (0, 0))
    assert picker.click(1, 20) is None and not picker.active


def test_search_click_and_keyboard_choose_the_highlighted_result():
    picker = LocationPicker('en')
    picker.choose('add')
    picker.search.results = [place(), place('Lyon', 45.76, 4.83)]
    picker.handle('back', 0, 0)
    assert picker.handle('key:enter', 0, 0).name == 'Lyon'
    picker.choose('add')
    picker.search.results = [place()]
    picker.overlay(80, 24, (0, 0))
    assert picker.click(75, 2).name == 'Paris'
    assert not picker.active


def test_typing_cannot_select_old_suggestions_or_commit_unseen_results():
    search = LocationSearch(refresh=lambda: None)
    search.start()
    search.query, search.results = 'Pa', [place()]
    with patch('linecast._maps_ui.threading.Timer'):
        search.handle('char:r', 0, 0, 7)
    assert not search.results and search.status == 'pending'
    search.handle('key:enter', 0, 0, 7)
    search._publish(search.gen, [place()], '', auto=True)
    assert search.open and search.take_chosen() is None
    search.handle('key:enter', 0, 0, 7)
    assert search.take_chosen().name == 'Paris'


def test_closed_search_ignores_late_results():
    search = LocationSearch(refresh=lambda: None)
    search.start()
    generation = search.gen
    search.close()
    search._publish(generation, [place()], '', auto=True)
    assert not search.results and search.take_chosen() is None


@pytest.mark.parametrize('searching', [True, False])
@pytest.mark.parametrize('cols,rows', [(8, 3), (20, 8), (40, 12), (80, 24)])
def test_panels_fit_and_scroll_to_selected_row(cols, rows, searching):
    picker = LocationPicker('ja')
    for i in range(10):
        picker.recent.remember(place('東京' * 40, i, i))
    if searching:
        picker.choose('add')
        picker.search.query = '京都' * 100
        picker.search.results = picker.recent.places[:8]
        picker.search.sel = 7
    else:
        picker.start()
        picker.sel = 11
    overlay = picker.overlay(cols, rows, (0, 0))
    for n, c, body in re.findall(r'\033\[(\d+);(\d+)H(.*?)(?=\033\[\d+;\d+H|$)', overlay):
        assert 1 <= int(n) <= rows
        assert 1 <= int(c) <= cols
        assert int(c) - 1 + visible_len(body) <= cols
    assert '\033[7m' in overlay
    if not searching:
        assert 'clear' in picker.hits.values()


@pytest.mark.parametrize('width', [20, 40, 80, 120])
def test_live_header_keeps_location_control_on_narrow_screens(width):
    runtime = WeatherRuntime(live=True, lang='en', icons='plain', oneline=False,
                             celsius=False, metric=False)
    data = {'current': {'temperature_2m': 70, 'apparent_temperature': 65,
                        'weather_code': 95, 'wind_speed_10m': 30}}
    line = render_header(data, width, 'A very long location name', runtime,
                         location_menu=True)
    plain = re.sub(r'\033\[[0-9;]*m', '', line)
    assert plain.endswith(' ▼') and visible_len(line) == width
    assert '▼' not in render_header(data, width, 'Paris', runtime)


def test_switch_commits_all_location_data_and_remembers_departure():
    view = app()
    result = dict(data={'new': 1}, alerts=[{'new': 1}], aqi={'new': 1},
                  historical={'new': 1}, name='Paris', country_code='FR')
    with patch.object(weather, 'gather', return_value=result) as gather:
        view._choose_location(place())
        finish(view)
    gather.assert_called_once()
    assert gather.call_args.args == (48.85, 2.35, '', view.runtime)
    assert gather.call_args.kwargs['geo_label'] == 'Paris'
    assert gather.call_args.kwargs['stale']() is False   # still the place on screen
    assert (view.lat, view.lng, view.country, view.location_name) == (48.85, 2.35, 'FR', 'Paris')
    assert view.data == view.aqi == view.historical == {'new': 1}
    assert view.alerts == [{'new': 1}]
    assert [p.name for p in RecentLocations().places] == ['Paris', 'Portland']


def test_failed_switch_keeps_entire_current_location_and_history():
    view = app()
    with patch.object(weather, 'gather', return_value={'data': None}), \
         patch.object(view, 'flash') as flash:
        view._choose_location(place())
        finish(view)
    assert (view.lat, view.lng, view.country) == (43, -70, 'US')
    assert view.data == view.aqi == view.historical == {'old': 1}
    assert view.alerts == [{'old': 1}]
    assert not RecentLocations().places
    assert 'Paris' in flash.call_args.args[0][0]
    assert view._loading is None


def test_slow_first_choice_cannot_overwrite_second_choice():
    view = app()
    release, entered = threading.Event(), threading.Event()

    def gather(lat, *args, **kwargs):
        if lat == 1:
            entered.set()
            assert release.wait(2)
        return dict(data={'lat': lat}, name=str(lat), country_code='FR')

    with patch.object(weather, 'gather', side_effect=gather):
        view._choose_location(place('first', 1, 1))
        first = view._location_worker
        assert entered.wait(1)
        view._choose_location(place('second', 2, 2))
        finish(view)
        release.set()
        first.join(2)
        view._finish_location()
    assert view.lat == 2 and view.data == {'lat': 2}
    assert 'first' not in [p.name for p in RecentLocations().places]


def test_refresh_from_departure_cannot_overwrite_new_location():
    view = app()
    release, entered = threading.Event(), threading.Event()

    def forecast(*args):
        entered.set()
        assert release.wait(2)
        return {'wrong': 1}

    with patch.object(weather, 'fetch_forecast', side_effect=forecast), \
         patch.object(weather, 'fetch_alerts', return_value=[{'wrong': 1}]), \
         patch.object(weather, 'fetch_aqi', return_value={'wrong': 1}), \
         patch.object(weather, '_reverse_geocode', return_value=('', 'FR', {})), \
         patch.object(weather, 'gather', return_value=dict(data={'new': 1}, country_code='FR')):
        view._start_refresh()
        old = view._worker
        assert entered.wait(1)
        view._choose_location(place())
        finish(view)
        release.set()
        old.join(2)
    assert view.data == {'new': 1} and view.alerts == [] and view.aqi is None


def test_location_click_search_keys_and_panel_block_forecast_interactions():
    view = app()
    with patch.object(weather, 'render_from_data',
                      return_value=('out', {2: [(0, 50, 0)]})) as render:
        view.render()
        assert view.on_click(80, 1)
        assert view.locations.open
        assert view.intercept('key:/') and view.text_mode()
        output, alerts = view.render(mouse_pos=(10, 10), active_alert=0)
        assert not alerts and render.call_args.kwargs['mouse_pos'] is None
        assert render.call_args.kwargs['active_alert'] is None
        assert 'OpenStreetMap' in output
        view.intercept('escape')
        assert not view.text_mode()
        view.on_action('/')
        assert view.text_mode()
        view.stop()
        assert not view.locations.active


def test_wheel_moves_panel_selection_and_otherwise_defers():
    view = app()
    assert view.on_wheel(1, 80, 1) is NotImplemented
    view.locations.recent.remember(place())
    view.on_action('l')
    assert view.on_wheel(-1, 80, 2) is True
    assert view.locations.sel == 1
    view.on_action('/')
    view.locations.search.results = [place(), place('Lyon', 45.76, 4.83)]
    view.on_wheel(-1, 80, 2)
    assert view.locations.search.sel == 1
    view.stop()


def test_loading_is_a_toast_without_changing_forecast_layout():
    view = app()
    release = threading.Event()

    def gather(*args, **kwargs):
        assert release.wait(2)
        return {'data': {'new': 1}, 'name': 'Paris'}

    with patch.object(weather, 'gather', side_effect=gather), \
         patch.object(weather, 'render_from_data', return_value=('forecast', {})) as render:
        view._choose_location(place())
        try:
            output, _ = view.render()
            body, _, floating = output.partition('\x00')
            assert body == 'forecast'
            assert render.call_args.kwargs['notice'] is None
            assert 'Loading Paris' in floating
            assert '╭' in floating
        finally:
            release.set()
            finish(view)
        assert view._flash is None and view._flash_timer is None
        assert 'Loading Paris' not in view.render()[0]


def test_stop_dismisses_loading_toast_and_cancels_animation():
    view = app()
    view.flash(['Loading Paris…'], busy=True)
    timer = view._flash_timer
    view.stop()
    assert timer.finished.is_set()
    assert view._flash is None and view._flash_timer is None


def test_divider_separates_places_from_actions_and_is_not_selectable():
    picker = LocationPicker('en', 'Ulaanbaatar')
    picker.recent.places = [place(), place('Tokyo', 35, 139)]
    picker.start()
    output = picker.overlay(80, 24, (0, 0))
    assert '─' * 10 in output
    assert '+ Add location' in output
    assert '★ Save Ulaanbaatar as default' in output
    assert '× Clear recent locations' in output
    assert picker.dividers == {4}
    assert picker.click(70, 4) is None and picker.open
    picker.handle('back', 0, 0)
    picker.handle('back', 0, 0)
    assert picker.items()[picker.sel][0] == 'add'
    picker.overlay(80, 24, (0, 0))
    assert picker.hits[5] == 'add' and 4 not in picker.hits
    picker.choose('clear')
    output = picker.overlay(80, 24, (0, 0))
    assert not picker.dividers and 'Clear recent' not in output
    assert [key for key, _ in picker.items()] == ['add', 'save']


def test_long_save_label_preserves_action_and_default_wording():
    picker = LocationPicker('en', 'Somewhere with a very long place name ' * 3)
    picker.start()
    output = picker.overlay(80, 24, (0, 0))
    assert '★ Save ' in output and '… as default' in output


def test_save_default_uses_displayed_place_and_preserves_other_settings():
    from linecast import _config, _location
    _config.write_config({'units': 'metric', 'language': 'fr', 'custom': {'a': 1}})
    view = app()
    # A remembered place is different from the displayed location being saved.
    view.locations.recent.remember(place())
    view.on_action('l')
    view.locations.sel = next(i for i, (key, _) in enumerate(view.locations.items())
                              if key == 'save')
    with patch.object(weather, 'gather') as gather:
        assert view.intercept('key:enter')
    assert not gather.called and not view.locations.active
    assert _config.saved_location() == dict(lat=43, lng=-70, label='Portland', country='US')
    assert _location.get_location() == (43, -70, 'US')
    assert _config.read_config()['custom'] == {'a': 1}
    assert _config.saved_units() == 'metric' and _config.saved_language() == 'fr'
    assert 'Saved Portland' in view.flash_overlay(80, 24)
    view.locations.recent.clear()
    assert _config.saved_location()['label'] == 'Portland'
    view.stop()


def test_save_default_click_and_write_failure_leave_old_default_intact():
    from linecast import _config
    old = dict(lat=1, lng=2, label='Old default', country='FR')
    _config.write_config({'location': old})
    view = app()
    view.on_action('l')
    view.locations.overlay(80, 24, (43, -70))
    row = next(row for row, key in view.locations.hits.items() if key == 'save')
    with patch.object(_config, 'write_config', side_effect=PermissionError), \
         patch.object(view, 'flash') as flash:
        assert view.on_click(70, row)
    assert _config.saved_location() == old
    assert flash.call_args.args[0] == ['Could not save the default location. Please try again.']
    assert view.location_name == 'Portland'


def test_save_action_tracks_successful_location_changes():
    from linecast import _config
    view = app()
    with patch.object(weather, 'gather', return_value=dict(
            data={'new': 1}, name='Ulaanbaatar', country_code='MN')):
        view._choose_location(place('Ulaanbaatar', 47.92, 106.92))
        finish(view)
    assert ('save', '★ Save Ulaanbaatar as default') in view.locations.items()
    view._choose_location('save')
    assert _config.saved_location() == dict(
        lat=47.92, lng=106.92, label='Ulaanbaatar', country='MN')
    view.stop()
