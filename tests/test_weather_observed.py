"""The current sky from a nearby station's METAR."""

from linecast._weather_cover import MOSTLY_CLOUDY, sky_condition
from linecast._weather_observed import (
    apply_observation,
    metar_sky,
    nearest_observation,
)
from linecast.weather import data_credits

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
    def test_explanations_go_before_sources(self):
        assert data_credits("US", "en", observed={"station": "KPWM"}) == (
            "Weather data by Open-Meteo · Current conditions by Aviation Weather Center (KPWM)"
            " · Alerts by US National Weather Service",
            "Weather data by Open-Meteo · Aviation Weather Center (KPWM)"
            " · US National Weather Service",
            "Weather data by Open-Meteo · Aviation Weather Center (KPWM)",
            "Weather data by Open-Meteo",
        )

    def test_no_station_no_credit(self):
        assert "Aviation" not in " ".join(data_credits("US", "en"))


class TestFallback:
    """Wherever the station cannot answer, the model's condition stands."""

    def test_no_station_in_the_box(self, monkeypatch):
        from linecast import _weather_observed as obs
        monkeypatch.setattr(obs, "fetch_bytes", lambda url, timeout: b"")
        assert obs._fetch_reports("https://example.invalid", 6) == []

    def test_a_failed_fetch(self, monkeypatch):
        from linecast import _weather_observed as obs

        def fail(lat, lng):
            raise OSError("network down")
        monkeypatch.setattr(obs, "fetch_metars", fail)
        assert obs.fetch_observation(43.677, -70.371) is None
        data = {"current": {"weather_code": 45}}
        assert obs.apply_observation(data, None)["current"]["weather_code"] == 45

    def test_a_malformed_answer(self, monkeypatch):
        from linecast import _weather_observed as obs
        monkeypatch.setattr(obs, "fetch_metars", lambda lat, lng: ["junk", {"lat": "x"}, None])
        assert obs.fetch_observation(43.677, -70.371) is None
