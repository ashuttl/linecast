"""The daily sweep of cached files no view will read again."""

import os
import time

from linecast import _cache

DAY = 86400
NOW = time.mktime((2026, 9, 29, 12, 0, 0, 0, 0, -1))


def _file(root, name, days_old):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    then = NOW - days_old * DAY
    os.utime(path, (then, then))
    return path


def test_old_short_lived_files_go_and_fresh_ones_stay(tmp_path, monkeypatch):
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
    old = _file(tmp_path, "weather/forecast_ab12cd34_Fi.json", 20)
    fresh = _file(tmp_path, "weather/forecast_ab12cd34_Cm.json", 2)
    alert = _file(tmp_path, "weather/alerts_ab12cd34.json", 8)
    tide = _file(tmp_path, "tides/pred_8418150_202605.json", 120)
    assert _cache.sweep(now=NOW) == 3
    assert not old.exists() and not alert.exists() and not tide.exists()
    assert fresh.exists()


def test_what_does_not_change_stays_a_year(tmp_path, monkeypatch):
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
    kept = [_file(tmp_path, name, 200) for name in (
        "timezone_ab12cd34.json", "weather/place_ab12cd34_en.json",
        "tides/station_ab12cd34.json", "tides/station_meta_8418150.json",
        "tides/chs_station_ab12cd34.json", "maps/search/0123456789ab.json")]
    gone = _file(tmp_path, "weather/place_ffff0000.json", 400)
    _cache.sweep(now=NOW)
    assert all(path.exists() for path in kept)
    assert not gone.exists()


def test_the_climate_goes_by_the_years_it_covers_not_its_age(tmp_path, monkeypatch):
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
    this = _file(tmp_path, "weather/hist_ab12cd34_2016-2025_Fi.json", 900)
    last = _file(tmp_path, "weather/hist_ab12cd34_2015-2024_Fi.json", 900)
    older = _file(tmp_path, "weather/hist_ab12cd34_2014-2023_Fi.json", 1)
    year = _file(tmp_path, "weather/year_ab12cd34_2025_Fi.json", 300)
    old_year = _file(tmp_path, "weather/year_ab12cd34_2024_Fi.json", 1)
    _cache.sweep(now=NOW)
    assert this.exists() and last.exists() and year.exists()
    assert not older.exists() and not old_year.exists()


def test_only_known_files_are_touched(tmp_path, monkeypatch):
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
    untouched = [_file(tmp_path, name, 5000) for name in (
        "prose/set/index.json", "location.json", "tides/all_stations.json",
        "weather/jma_areas.json", "maps/vt/3/1_2_3.pbf", "radar/lwxr/weather-maps.json")]
    _cache.sweep(now=NOW)
    assert all(path.exists() for path in untouched)


def test_it_runs_at_most_once_a_day(tmp_path, monkeypatch):
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
    assert _cache.sweep(now=NOW) == 0
    _file(tmp_path, "weather/forecast_ab12cd34_Fi.json", 30)
    assert _cache.sweep(now=NOW + DAY / 2) is None
    assert _cache.sweep(now=NOW + DAY + 1) == 1


def test_a_write_cut_short_is_cleared_after_a_day(tmp_path, monkeypatch):
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
    old = _file(tmp_path, "weather/forecast_x.json.123.456.tmp", 2)
    new = _file(tmp_path, "weather/forecast_y.json.123.456.tmp", 0.5)
    _cache.sweep(now=NOW)
    assert not old.exists() and new.exists()


def test_a_tide_kept_for_the_year_outlasts_the_year_it_serves(tmp_path, monkeypatch):
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
    # Open-Meteo's finished year and the tide fitted to it are read all
    # the following year without being written again, as JMA's tables
    # and Kartverket's turns are through their own
    kept = [_file(tmp_path, name, 380) for name in (
        "tides/om_year_ab12cd34_2025.json", "tides/om_fit_ab12cd34_2025.json")]
    kept += [_file(tmp_path, name, 300) for name in (
        "tides/jma_pred_TK_2026.json", "tides/kv_hilo_ab12cd34_2026.json")]
    gone = [_file(tmp_path, name, 401) for name in (
        "tides/om_year_ab12cd34_2024.json", "tides/om_fit_ab12cd34_2024.json",
        "tides/jma_pred_TK_2025.json", "tides/kv_hilo_ab12cd34_2025.json")]
    assert _cache.sweep(now=NOW) == len(gone)
    assert all(path.exists() for path in kept)
    assert not any(path.exists() for path in gone)


def test_what_a_gauge_measured_goes_three_months_after_it_was_last_read(tmp_path, monkeypatch):
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
    names = ("tides/chs_obs_5cebf1e23d0f4a073c4bbfac_{}.json", "tides/jma_obs_TK_{}.json",
             "tides/jma_obsz_TK_{}.json", "tides/jma_dep_TK_{}.json",
             "tides/jma_depz_TK_{}.json", "tides/kv_obs_BGO_{}01.json",
             "tides/kv_pred_ab12cd34_{}.json")
    kept = [_file(tmp_path, name.format("202608"), 80) for name in names]
    gone = [_file(tmp_path, name.format("202601"), 100) for name in names]
    assert _cache.sweep(now=NOW) == len(gone)
    assert all(path.exists() for path in kept)
    assert not any(path.exists() for path in gone)


def test_noaas_measurements_and_flood_levels_go_after_three_months(tmp_path, monkeypatch):
    """The preliminary levels are named by the day they start from, which
    moves on as NOAA verifies, so a station leaves a new file each month."""
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
    names = ("tides/obs_hl_8418150_{}.json", "tides/obs_wl_8418150_{}0831.json",
             "tides/flood_841815{}.json", "tides/datums_841815{}.json")
    kept = [_file(tmp_path, name.format("2026"), 80) for name in names]
    gone = [_file(tmp_path, name.format("2025"), 100) for name in names]
    assert _cache.sweep(now=NOW) == len(gone)
    assert all(path.exists() for path in kept)
    assert not any(path.exists() for path in gone)


def test_a_gauges_holdings_go_after_a_month(tmp_path, monkeypatch):
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
    kept = _file(tmp_path, "tides/chs_holdings_5cebf1e23d0f4a073c4bbfac.json", 20)
    gone = _file(tmp_path, "tides/chs_holdings_5cebf1de3d0f4a073c4bbd1e.json", 40)
    assert _cache.sweep(now=NOW) == 1
    assert kept.exists() and not gone.exists()
