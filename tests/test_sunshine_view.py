"""The sunshine day view's vertical scale."""

from linecast.sunshine.view import _solstice_range


def test_the_scale_is_the_same_year_round_in_either_hemisphere():
    # Melbourne's summer is December's: its range mirrors a northern
    # place at the same latitude, rather than topping out at a winter noon
    south = _solstice_range(-37.81, 144.96, 10)
    north = _solstice_range(37.81, 144.96, 10)
    assert abs(south[0] - north[0]) < 1.0 and abs(south[1] - north[1]) < 1.0
    assert south[0] > 70


def test_the_sky_name_is_added_only_where_it_fits():
    # The sky's name after the day length is measured in cells: in
    # Chinese, Japanese and Korean it was counted in characters, and at
    # 36 to 43 columns the line ran a few cells past its width.
    from linecast._runtime import RuntimeConfig
    from linecast.sunshine.solar import solar_times
    from linecast.sunshine.view import _info_line
    from linecast.terminal.textwidth import visible_len
    lat, lng, doy = 43.68, -70.32, 80
    sunrise, sunset = solar_times(lat, lng, doy, -4)[:2]
    for lang in ("ja", "zh", "ko"):
        runtime = RuntimeConfig(live=False, icons="plain", lang=lang, oneline=False)
        for width in range(34, 48):
            bare = _info_line(lat, lng, doy, sunrise, sunset, width, runtime, tz_offset_h=-4)
            for hour in (0.0, 5.5, 6.0, 12.0, 18.0, 19.0, 21.0):
                line = _info_line(lat, lng, doy, sunrise, sunset, width, runtime,
                                  now_hour=hour, tz_offset_h=-4)
                if visible_len(line) > visible_len(bare):   # the name went in
                    assert visible_len(line) <= width, (lang, width, hour, line)


def test_the_info_line_gives_way_in_a_narrow_window():
    # at 30 columns it ran to 33, the sunset cut to "5:4" live
    from linecast._runtime import RuntimeConfig
    from linecast.sunshine.solar import solar_times
    from linecast.sunshine.view import _info_line
    from linecast.terminal.textwidth import visible_len
    lat, lng, doy = 43.68, -70.32, 297
    sunrise, sunset = solar_times(lat, lng, doy, -4)[:2]
    runtime = RuntimeConfig(live=False, icons="plain", lang="en", oneline=False)
    from linecast._timefmt import fmt_time
    rise, sets = fmt_time(sunrise, runtime.use_24h), fmt_time(sunset, runtime.use_24h)
    shed = []
    for width in range(1, 41):
        line = _info_line(lat, lng, doy, sunrise, sunset, width, runtime, tz_offset_h=-4)
        assert visible_len(line) <= width, (width, line)
        shed.append(("(" in line, "h " in line, sets in line, rise in line))
    # the change goes first, then the length, the sunset, the sunrise
    assert sorted(set(shed), reverse=True) == [
        (True, True, True, True), (False, True, True, True),
        (False, False, True, True), (False, False, False, True), (False, False, False, False)]


def test_a_narrow_window_is_drawn_to_its_width(monkeypatch):
    # the field was never drawn narrower than 30 columns
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from linecast import _runtime
    from linecast._runtime import RuntimeConfig
    from linecast.sunshine import view, year
    from linecast.terminal.textwidth import visible_len
    runtime = RuntimeConfig(live=False, icons="plain", lang="en", oneline=False)
    now = datetime(2026, 10, 24, 7, 30, tzinfo=ZoneInfo("America/New_York"))
    for cols in (8, 20, 29):
        monkeypatch.setattr(view, "get_terminal_size", lambda cols=cols: (cols, 12))
        monkeypatch.setattr(year, "get_terminal_size", lambda cols=cols: (cols, 12))
        _runtime.set_current(runtime)
        for frame in (view.render(43.68, -70.32, 297, 7.5, runtime=runtime, now=now),
                      year.render_year(43.68, -70.32, now, runtime=runtime)):
            assert max(visible_len(line) for line in frame.split("\n")) <= cols
