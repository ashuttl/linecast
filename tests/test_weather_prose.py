"""weather --prose prints the dashboard's paragraph and exits."""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

from linecast import _location
from linecast._parsers import weather_parser
from linecast._runtime import WeatherRuntime
from linecast.terminal import bidi
from linecast.weather import live
from linecast.weather.narrative import narrative_lines


NOW = datetime(2026, 3, 5, 14, 30)


@pytest.fixture
def forecast(monkeypatch):
    path = Path(__file__).parent / "fixtures" / "open_meteo_forecast.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    runtimes = []
    monkeypatch.setattr(_location, "resolve_location",
                        lambda *a, **k: (43.65, -79.38, "CA", "Toronto"))
    # Exercise the runtime being rebuilt after resolving the location, too.
    monkeypatch.setattr(_location, "country_for_defaults", lambda *a: "CA")

    def gather(lat, lng, country, runtime, label):
        assert (lat, lng, country, label) == (43.65, -79.38, "CA", "Toronto")
        assert runtime.prose and not runtime.live
        runtimes.append(runtime)
        return {"data": data, "name": label, "country_code": country}

    monkeypatch.setattr(live, "gather", gather)
    monkeypatch.setattr(live, "local_now", lambda data: NOW)
    return data, runtimes


@pytest.mark.parametrize("tty", [False, True])
@pytest.mark.parametrize("lang,units,clock", [
    ("en", "imperial", "12h"),
    ("fr", "metric", "24h"),
    ("ja", "metric", "12h"),
    ("fa", "metric", "24h"),
])
def test_prints_only_the_dashboard_paragraph(monkeypatch, capsys, forecast,
                                            tty, lang, units, clock):
    data, runtimes = forecast
    monkeypatch.setattr(sys.stdout, "isatty", lambda: tty)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty)
    monkeypatch.setattr(sys, "argv", ["weather", "--prose", "--live", "--location", "Toronto",
                                     "--lang", lang, f"--{units}", f"--{clock}"])
    # A narrow, short terminal must still receive the complete paragraph.
    monkeypatch.setenv("COLUMNS", "20")
    monkeypatch.setenv("LINES", "5")
    live.main()
    runtime, = runtimes
    assert runtime.lang == lang
    assert runtime.metric == runtime.celsius == (units == "metric")
    assert runtime.use_24h == (clock == "24h")
    paragraph, = narrative_lines(data, NOW, 10_000, runtime)
    paragraph = re.sub(r"\x1b\[[0-9;]*m", "", paragraph)
    expected = bidi.for_stream(paragraph, sys.stdout)
    output = capsys.readouterr()
    assert output.out == expected + "\n"
    assert output.out.count("\n") == 1
    assert "\x1b" not in output.out
    assert output.err == ""


def test_nothing_to_say_prints_an_empty_line(monkeypatch, capsys, forecast):
    data, _ = forecast
    data.clear()
    monkeypatch.setattr(sys, "argv", ["weather", "--prose", "--print"])
    live.main()
    output = capsys.readouterr()
    assert output.out == "\n"
    assert output.err == ""


def test_fetch_failure_uses_stderr(monkeypatch, capsys, forecast):
    monkeypatch.setattr(sys, "argv", ["weather", "--prose"])
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(live, "gather", lambda *a: {"data": None})
    with pytest.raises(SystemExit) as error:
        live.main()
    assert error.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Could not fetch weather data.\n"


@pytest.mark.parametrize("flags", [["--json"], ["--oneline"], ["--year"],
                                    ["--width", "80"], ["--height", "50%"]])
@pytest.mark.parametrize("prose_first", [False, True])
def test_conflicting_flags_fail_before_fetch(monkeypatch, capsys, flags, prose_first):
    def unexpected(*a, **k):
        pytest.fail("invalid output flags must fail before resolving the location")

    monkeypatch.setattr(live, "place_for", unexpected)
    args = ["--prose", *flags] if prose_first else [*flags, "--prose"]
    monkeypatch.setattr(sys, "argv", ["weather", *args])
    with pytest.raises(SystemExit) as error:
        live.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "--prose" in output.err and flags[0] in output.err


def test_prose_is_opt_in():
    runtime = WeatherRuntime.from_sources(weather_parser().parse_args([]), environ={})
    assert not runtime.prose
