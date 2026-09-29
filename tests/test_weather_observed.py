"""The current sky from a nearby station's METAR."""

from types import SimpleNamespace

from linecast.weather.cover import MOSTLY_CLOUDY, sky_condition
from linecast.weather.observed import (
    apply_observation,
    metar_sky,
    nearest_observation,
)
from linecast.weather.view import data_credits

NOW = 1_790_000_000


def metar(raw, cover=None, clouds=(), wx=None, lat=43.64, lon=-70.30, age=600, icao="KPWM"):
    return {"icaoId": icao, "name": "Portland Intl, ME, US", "lat": lat, "lon": lon,
            "obsTime": NOW - age, "rawOb": raw, "cover": cover, "wxString": wx,
            "clouds": [{"cover": c, "base": b} for c, b in clouds]}


def metar_weather_code(report):
    sky = metar_sky(report)
    return sky and sky[0]


def named(report):
    """The condition a report is shown as."""
    return sky_condition(*metar_sky(report))


class TestScale:
    def test_the_nws_steps(self):
        assert [sky_condition(0, c) for c in (0, 12.5, 13, 37.5, 38, 62.5, 63, 87.5, 88, 100)] \
            == [0, 0, 1, 1, 2, 2, MOSTLY_CLOUDY, MOSTLY_CLOUDY, 3, 3]

    def test_the_code_decides_without_a_cover(self):
        assert sky_condition(3, None) == 3

    def test_weather_is_not_a_sky(self):
        assert sky_condition(61, 100) == 61
        assert sky_condition(45, 100) == 45


class TestWeatherCode:
    def test_sky_cover(self):
        assert named(metar("", "CLR")) == 0
        assert named(metar("", "CAVOK")) == 0
        assert named(metar("", "FEW", [("FEW", 15000)])) == 1
        assert named(metar("", "SCT", [("FEW", 15000), ("SCT", 25000)])) == 2
        assert named(metar("", "BKN", [("BKN", 1800)])) == MOSTLY_CLOUDY
        assert named(metar("", "OVC", [("OVC", 500)])) == 3

    def test_the_code_stays_in_open_meteos_terms(self):
        assert metar_sky(metar("", "BKN", [("BKN", 1800)])) == (2, 75)

    def test_an_obscured_sky_is_fog(self):
        assert metar_weather_code(metar("", "OVX", [("OVX", 0)], wx="BR")) == 45

    def test_present_weather_over_cloud(self):
        assert metar_weather_code(metar("", "OVC", [("OVC", 3100)], wx="RA BR")) == 63
        assert metar_weather_code(metar("", "BKN", wx="-DZ")) == 51
        assert metar_weather_code(metar("", "OVC", wx="+SHRA")) == 82
        assert metar_weather_code(metar("", "OVC", wx="-SHSN")) == 85
        assert metar_weather_code(metar("", "OVC", wx="-FZRA")) == 66
        assert metar_weather_code(metar("", "OVC", wx="FZFG")) == 48
        assert metar_weather_code(metar("", "OVC", wx="-TSRA")) == 95
        assert metar_weather_code(metar("", "OVC", wx="FG")) == 45

    def test_the_heaviest_group_is_the_headline(self):
        assert metar_weather_code(metar("", "OVC", wx="-DZ TSRA")) == 95

    def test_weather_nearby_or_past_is_not_overhead(self):
        assert named(metar("", "SCT", wx="VCSH")) == 2
        assert named(metar("", "SCT", wx="RESHRA")) == 2
        assert named(metar("", "FEW", wx="BCFG")) == 1

    def test_blowing_snow_is_not_snowfall(self):
        assert named(metar("", "SCT", wx="BLSN")) == 2
        assert named(metar("", "CLR", wx="DRSN")) == 0
        assert metar_weather_code(metar("", "OVC", wx="-SN BLSN")) == 71

    def test_nothing_to_go_on(self):
        assert metar_weather_code(metar("", None)) is None


class TestNearest:
    WESTBROOK = (43.677, -70.371)

    def test_the_closest_recent_report(self):
        far = metar("", "OVC", lat=43.9, lon=-70.3, icao="KFAR")
        near = metar("", "FEW", icao="KPWM")
        found = nearest_observation(*self.WESTBROOK, [far, near], now=NOW)
        assert found["station"] == "KPWM"
        assert found["code"] == 1

    def test_too_far_or_too_old(self):
        far = metar("", "CLR", lat=44.2)
        old = metar("", "CLR", age=3 * 3600)
        assert nearest_observation(*self.WESTBROOK, [far, old], now=NOW) is None

    def test_an_observer_sees_high_cloud_a_ceilometer_does_not(self):
        staffed = metar("METAR KPWM 211051Z 35003KT 10SM FEW150 SCT250", "SCT")
        auto = metar("METAR KSFM 211056Z AUTO 33004KT 10SM CLR", "CLR")
        cavok = metar("METAR LIRU 210950Z VRB03KT CAVOK", "CAVOK")
        assert nearest_observation(*self.WESTBROOK, [staffed], now=NOW)["sees_high_cloud"]
        assert not nearest_observation(*self.WESTBROOK, [auto], now=NOW)["sees_high_cloud"]
        assert not nearest_observation(*self.WESTBROOK, [cavok], now=NOW)["sees_high_cloud"]


class TestApply:
    def observation(self, code, sees_high_cloud=True, cover=None):
        if cover is None:
            cover = {0: 0, 1: 25, 2: 50, 3: 100}.get(code)
        return {"code": code, "cover": cover, "station": "KPWM", "name": "Portland Intl, ME, US",
                "distance_km": 6.6, "time": NOW, "sees_high_cloud": sees_high_cloud}

    def test_the_station_replaces_the_models_code(self):
        data = {"current": {"weather_code": 45, "cloud_cover_high": 0}}
        apply_observation(data, self.observation(2, cover=75))
        assert data["current"]["weather_code"] == 2
        assert data["current"]["cloud_cover"] == 75
        assert data["current"]["model_weather_code"] == 45
        assert data["current"]["observed"]["station"] == "KPWM"

    def test_high_cloud_a_station_cannot_see_still_counts(self):
        data = {"current": {"weather_code": 3, "cloud_cover_high": 100}}
        apply_observation(data, self.observation(0, sees_high_cloud=False))
        assert data["current"]["weather_code"] == 3

    def test_an_observer_saying_clear_is_believed(self):
        data = {"current": {"weather_code": 3, "cloud_cover_high": 100}}
        apply_observation(data, self.observation(0))
        assert data["current"]["weather_code"] == 0

    def test_rain_is_not_raised_to_cloud(self):
        data = {"current": {"weather_code": 1, "cloud_cover_high": 100}}
        apply_observation(data, self.observation(61, sees_high_cloud=False))
        assert data["current"]["weather_code"] == 61

    def test_no_observation_leaves_the_model(self):
        data = {"current": {"weather_code": 45}}
        apply_observation(data, None)
        assert data["current"] == {"weather_code": 45}


class TestCredits:
    PWM = {"station": "KPWM", "name": "Portland Intl Jetport, ME, US",
           "distance_km": 6.4, "time": 1790423460}  # 7:51 am in Maine

    def test_station_by_name_then_by_code(self):
        assert data_credits("US", "en", self.PWM, tz_name="America/New_York") == (
            "Observed at 7:51a from Portland Intl Jetport, 4 mi away"
            " · Open-Meteo & US National Weather Service",
            "Observed at 7:51a from KPWM, 4 mi away · Open-Meteo & US National Weather Service",
            "Open-Meteo & US National Weather Service",
            "Open-Meteo",
        )

    def test_distance_and_clock_follow_the_runtime(self):
        runtime = SimpleNamespace(lang="en", metric=True, use_24h=True)
        credit = data_credits("US", "en", self.PWM, runtime, "America/New_York")[0]
        assert "at 07:51 from Portland Intl Jetport, 6 km away" in credit

    def test_translated_around_the_english_name(self):
        credit = data_credits("US", "fr", self.PWM, tz_name="America/New_York")[0]
        assert credit.startswith("Observé à 07:51 à Portland Intl Jetport")

    def test_no_station_no_credit(self):
        assert data_credits("US", "en") == ("Open-Meteo & US National Weather Service",
                                            "Open-Meteo")


class TestFallback:
    """Wherever the station cannot answer, the model's condition stands."""

    def test_no_station_in_the_box(self, monkeypatch):
        from linecast.weather import observed as obs
        monkeypatch.setattr(obs, "fetch_bytes", lambda url, timeout: b"")
        assert obs._fetch_reports("https://example.invalid", 6) == []

    def test_a_failed_fetch(self, monkeypatch):
        from linecast.weather import observed as obs

        def fail(lat, lng):
            raise OSError("network down")
        monkeypatch.setattr(obs, "fetch_metars", fail)
        assert obs.fetch_observation(43.677, -70.371) is None
        data = {"current": {"weather_code": 45}}
        assert obs.apply_observation(data, None)["current"]["weather_code"] == 45

    def test_a_malformed_answer(self, monkeypatch):
        from linecast.weather import observed as obs
        monkeypatch.setattr(obs, "fetch_metars", lambda lat, lng: ["junk", {"lat": "x"}, None])
        assert obs.fetch_observation(43.677, -70.371) is None


class TestGauge:
    """What the station's rain gauge caught in the last day."""

    # The Portland Jetport's reports for the night of September 26, 2026:
    # a trace in the afternoon, half an inch between eight and two, and
    # light rain again at seven in the morning, when this was fetched
    FETCHED = 1_790_508_420   # 11:27Z

    @staticmethod
    def day():
        import json
        from pathlib import Path
        path = Path(__file__).parent / "fixtures" / "awc_metar_kpwm_day.json"
        return json.loads(path.read_text())

    def gauge(self, reports=None, now=FETCHED):
        from linecast.weather.observed import station_precipitation
        return station_precipitation(self.day() if reports is None else reports, now)

    def test_the_jetports_night(self):
        # 0.52″ in the hourly reports, and 0.02″ since the last of them;
        # the hourly traces add nothing
        assert self.gauge() == {"station": "KPWM", "precip": 0.54,
                                "rain_hours": 7, "snow_hours": 0, "mix_hours": 0}

    def test_the_hour_so_far_is_only_the_last_special_report(self):
        # At eleven, before the specials at 11:11 and 11:20, the day ends
        # with the 10:51 report
        assert self.gauge(now=self.FETCHED - 27 * 60)["precip"] == 0.52

    def test_a_correction_is_not_counted_twice(self):
        day = self.day()
        worst = max(day, key=lambda m: m.get("precip") or 0)
        corrected = dict(worst, obsTime=worst["obsTime"] + 60,
                         rawOb=worst["rawOb"].replace("METAR KPWM", "METAR KPWM COR"))
        assert self.gauge(day + [corrected])["precip"] == 0.54

    def test_missing_hours(self):
        day = self.day()
        routine = [m for m in day if m["metarType"] == "METAR"]
        gone = {id(m) for m in routine[5:10]}
        assert self.gauge([m for m in day if id(m) not in gone]) is None

    def test_a_gauge_that_is_out(self):
        day = self.day()
        day[3] = dict(day[3], rawOb=day[3]["rawOb"].replace(" $", " PNO $"))
        assert self.gauge(day) is None

    def test_a_day_without_an_amount(self):
        dry = [{k: v for k, v in m.items() if k not in ("precip", "pcp3hr", "pcp6hr")}
               for m in self.day()]
        # Rain named and not measured: a station without a gauge
        assert self.gauge(dry) is None
        # Nothing named all day by a station that tells rain from nothing
        clear = [dict(m, wxString="", rawOb=m["rawOb"].split(" RMK ")[0] + " RMK AO2")
                 for m in dry]
        assert self.gauge(clear) == {"station": "KPWM", "precip": 0.0,
                                     "rain_hours": 0, "snow_hours": 0, "mix_hours": 0}
        # Nor by one that cannot
        blind = [dict(m, rawOb=m["rawOb"].replace(" AO2", " AO1")) for m in clear]
        assert self.gauge(blind) is None

    def test_what_each_hour_fell_as(self):
        from linecast.weather.observed import _hour_kind

        def kind(wx, remarks="AO2"):
            return _hour_kind({"wxString": wx, "rawOb": f"METAR KPWM 271051Z RMK {remarks}"})

        assert kind("-RA BR") == "rain"
        assert kind("", "AO2 RAE38 P0002") == "rain"
        assert kind("") == "rain"
        assert kind("-SN") == "snow"
        assert kind("-SHSN", "AO2 SNB05") == "snow"
        assert kind("-FZRA") == "mix"
        assert kind("-RA", "AO2 SNE12RAB12") == "mix"
        assert kind("BR", "AO2 FZDZB30") == "mix"

    def test_only_an_automated_station_is_asked(self, monkeypatch):
        from linecast.weather import observed as obs

        def fetch(station):
            raise AssertionError("asked for a station that reports no gauge")
        monkeypatch.setattr(obs, "fetch_station_history", fetch)
        station = {"station": "EGBB", "automated": False}
        assert obs.fetch_station_precipitation(station) is None
        assert obs.fetch_station_precipitation(None) is None

    def test_the_station_is_automated(self):
        near = nearest_observation(43.677, -70.371, [
            metar("METAR KPWM 271051Z 04012G21KT 2SM -RA BR OVC008 12/12 A2993 RMK AO2 P0002",
                  wx="-RA BR")], now=NOW)
        assert near["automated"]
        near = nearest_observation(43.677, -70.371, [
            metar("METAR KPWM 271051Z 04012KT 9999 -RA OVC008 12/12 Q1013", wx="-RA")],
            now=NOW)
        assert not near["automated"]

    def test_a_failed_fetch_leaves_the_model(self, monkeypatch):
        from linecast.weather import observed as obs

        def fail(station):
            raise OSError("network down")
        monkeypatch.setattr(obs, "fetch_station_history", fail)
        assert obs.fetch_station_precipitation({"station": "KPWM", "automated": True}) is None

    def test_a_strange_station_is_not_asked_for(self):
        from linecast.weather.observed import fetch_station_history
        assert fetch_station_history("../KPWM") == []

    def test_the_forecast_carries_it(self):
        gauge = self.gauge()
        data = {"current": {"weather_code": 53}}
        apply_observation(data, TestApply().observation(61), gauge)
        assert data["observed_precipitation"] == gauge
