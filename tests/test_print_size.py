"""Print viewports use cells or the observed terminal's dimensions."""

from datetime import datetime, timezone
import os

import pytest

from linecast import _parsers, _runtime
from linecast.terminal import framebuffer


VIEWS = ("weather", "sunshine", "moon", "sky", "tides", "radar", "maps")


def runtime_for(view, flags):
    parser = getattr(_parsers, f"{view}_parser")()
    args = parser.parse_args(flags)
    cls = {"weather": _runtime.WeatherRuntime,
           "tides": _runtime.TidesRuntime}.get(view, _runtime.RuntimeConfig)
    return cls.from_sources(args, environ={}, country="US")


@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize("flags,expected", [
    (["--width", "80", "--height", "20"], (80, 20)),
    (["--width", "50%", "--height", "25%"], (60, 10)),
    (["--width", "80", "--height", "50%"], (80, 20)),
    (["--width", "12.5%"], (15, 40)),
    (["--height", "0.1%"], (120, 1)),
])
def test_view_dimensions(monkeypatch, view, flags, expected):
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setenv("LINES", "40")
    runtime = runtime_for(view, ["--live", *flags])
    assert not runtime.live
    _runtime.set_current(runtime)
    assert framebuffer.get_terminal_size() == expected
    # A second location/config resolution must not scale an already scaled size.
    _runtime.set_current(runtime_for(view, flags))
    assert framebuffer.get_terminal_size() == expected
    assert os.environ["COLUMNS"] == "120"
    assert os.environ["LINES"] == "40"


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "0%", "-20%", "101%",
                                    "nan%", "inf%", "80x24", "abc", ""])
@pytest.mark.parametrize("flag", ["--width", "--height"])
def test_invalid_dimension(value, flag):
    with pytest.raises(SystemExit) as error:
        _parsers.moon_parser().parse_args([flag, value])
    assert error.value.code == 2


@pytest.mark.parametrize("mode", ["--json", "--oneline"])
@pytest.mark.parametrize("flags", [["--width", "80"], ["--height", "50%"]])
def test_data_output_rejects_dimensions(mode, flags):
    for args in ([mode, *flags], [*flags, mode]):
        with pytest.raises(SystemExit) as error:
            _parsers.moon_parser().parse_args(args)
        assert error.value.code == 2


def test_percentage_fallback_and_rounding(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("no terminal")

    monkeypatch.setattr(os, "get_terminal_size", unavailable)
    _runtime.set_current(runtime_for("moon", ["--width", "33%", "--height", "50%"]))
    assert framebuffer.get_terminal_size() == (26, 12)


def test_new_runtime_restores_terminal_dimensions(monkeypatch):
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setenv("LINES", "40")
    _runtime.set_current(runtime_for("moon", ["--width", "80"]))
    assert framebuffer.get_terminal_size() == (80, 40)
    _runtime.set_current(runtime_for("moon", ["--print"]))
    assert framebuffer.get_terminal_size() == (120, 40)


@pytest.mark.parametrize("month", [False, True])
def test_moon_render_matches_an_equivalent_terminal(monkeypatch, month):
    from linecast.moon.calendar import render_calendar
    from linecast.moon.view import render

    draw = render_calendar if month else render
    moment = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
    monkeypatch.setenv("COLUMNS", "160")
    monkeypatch.setenv("LINES", "48")
    runtime = runtime_for("moon", ["--width", "50%", "--height", "50%"])
    _runtime.set_current(runtime)
    sized = draw(moment, 43.68, -70.37, runtime)
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("LINES", "24")
    runtime = runtime_for("moon", ["--print"])
    _runtime.set_current(runtime)
    assert draw(moment, 43.68, -70.37, runtime) == sized


@pytest.mark.parametrize("view", VIEWS)
def test_help_describes_print_dimensions(view):
    help_text = getattr(_parsers, f"{view}_parser")().format_help()
    assert "--width COLS|PERCENT%" in help_text
    assert "--height ROWS|PERCENT%" in help_text
    assert "50%" in help_text
