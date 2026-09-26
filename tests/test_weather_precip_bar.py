"""The hourly precipitation bar: height is the forecast amount, color is the
probability faded toward the background."""
import re
from unittest.mock import patch

from linecast.terminal import color as _color
from linecast.terminal import theme as _theme
from linecast._runtime import WeatherRuntime
from linecast.weather.hourly import _build_precip_blocks, _precip_bar_full
from linecast.weather.style import PRECIP_RAIN_RGB

_FG = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+)m")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _bar(amounts, probs, n_rows=2, mode="truecolor"):
    with patch.object(_color, "_COLOR_MODE", mode):
        return _build_precip_blocks(amounts, probs, [61] * len(amounts), len(amounts),
                                    n_rows=n_rows, full=5.0)


def _height(lines, col):
    """Eighths of bar in one column, summed over the rows."""
    blocks = "▁▂▃▄▅▆▇█"
    total = 0
    for line in lines:
        ch = _ANSI.sub("", line)[col]
        if ch in blocks:
            total += blocks.index(ch) + 1
    return total


def _first_color(lines):
    for line in lines:
        m = _FG.search(line)
        if m:
            return tuple(int(v) for v in m.groups())
    return None


def _distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def test_height_follows_amount_not_probability():
    drizzle_likely = _bar([0.1] * 4, [90] * 4)
    downpour_maybe = _bar([4.0] * 4, [30] * 4)
    assert _height(drizzle_likely, 1) >= 1
    assert _height(downpour_maybe, 1) > _height(drizzle_likely, 1)


def test_amount_at_or_above_full_tops_out():
    assert _height(_bar([5.0] * 4, [100] * 4), 1) == 16
    assert _height(_bar([20.0] * 4, [100] * 4), 1) == 16


def test_no_amount_draws_nothing_however_likely():
    lines = _bar([0.0] * 4, [90] * 4)
    assert all(_ANSI.sub("", line).strip() == "" for line in lines)


def test_probability_fades_the_color():
    certain = _first_color(_bar([1.0] * 4, [100] * 4))
    unlikely = _first_color(_bar([1.0] * 4, [20] * 4))
    assert certain == tuple(PRECIP_RAIN_RGB)
    assert _distance(unlikely, _theme.theme_bg) < _distance(certain, _theme.theme_bg)
    assert unlikely != certain


def test_sixteen_color_terminals_draw_a_solid_bar():
    certain = _bar([1.0] * 4, [100] * 4, mode="16")
    unlikely = _bar([1.0] * 4, [20] * 4, mode="16")
    assert certain == unlikely


def test_full_amount_follows_the_data_unit():
    imperial = WeatherRuntime(live=False, icons=True, lang="en", oneline=False, metric=False)
    metric = WeatherRuntime(live=False, icons=True, lang="en", oneline=False, metric=True)
    assert _precip_bar_full({"hourly_units": {"precipitation": "inch"}}, metric) == 0.2
    assert _precip_bar_full({"hourly_units": {"precipitation": "mm"}}, imperial) == 5.0
    assert _precip_bar_full({}, imperial) == 0.2
    assert _precip_bar_full({}, metric) == 5.0
