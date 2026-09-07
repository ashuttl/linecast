"""Alert banners: how the badges lay out, and what a click on one opens."""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._graphics import visible_len
from linecast._runtime import WeatherRuntime
from linecast._weather_alerts import render_alerts, render_alerts_mapped

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 3, 5, 14, 30)

# What the JMA sends for the Izu Islands: several watches, one shared body.
_SHARED = "伊豆諸島南部では、強風や高波に注意してください。"
_WATCHES = ["High Wind Watch", "Dense Fog Watch", "Thunderstorm Watch",
            "High Wave Watch"]


def _runtime(**overrides):
    defaults = dict(live=False, icons="emoji", lang="en", oneline=False,
                    celsius=False, metric=False, shading=False)
    defaults.update(overrides)
    return WeatherRuntime(**defaults)


def _clicked(spans, column):
    """The alert a click at `column` opens, as the live loop resolves it."""
    return next((index for start, end, index in spans if start <= column <= end),
                spans[0][2])


def _alerts(events=_WATCHES, description=_SHARED):
    return [{"event": event, "severity": "Moderate", "description": description,
             "effective": "", "expires": ""} for event in events]


class TestBadgeLayout:
    def test_badges_break_between_themselves_rather_than_mid_word(self):
        lines, _spans = render_alerts_mapped(_alerts(), width=74)

        assert len(lines) == 3  # two rows of badges, then the shared body
        assert all(visible_len(line) <= 74 for line in lines)

    def test_they_share_one_line_when_the_terminal_is_wide_enough(self):
        lines, spans = render_alerts_mapped(_alerts(), width=120)

        assert len(lines) == 2
        assert [index for _s, _e, index in spans[0]] == [0, 1, 2, 3]

    def test_a_badge_wider_than_the_terminal_is_trimmed(self):
        alerts = _alerts(["Excessive Heat Warning for the Entire Region"])
        lines = render_alerts(alerts, width=30)

        assert all(visible_len(line) <= 30 for line in lines)

    def test_a_single_alert_still_reads_as_one_line(self):
        alerts = [{"event": "Flood Warning", "severity": "Severe",
                   "description": "Rain is expected.", "effective": "",
                   "expires": ""}]
        lines, spans = render_alerts_mapped(alerts, width=80)

        assert len(lines) == 1
        assert spans == [[(0, 79, 0)]]

    def test_no_width_is_wide_enough_to_overrun(self):
        for width in range(20, 200, 3):
            lines = render_alerts(_alerts(), width=width)
            assert all(visible_len(line) <= width for line in lines)


class TestClickTargets:
    def test_a_click_finds_the_badge_under_it(self):
        _lines, spans = render_alerts_mapped(_alerts(), width=120)

        # Every column of every badge opens that badge's own alert -- the
        # fourth one opens the fourth alert, not the first on the line.
        for start, end, index in spans[0]:
            for column in (start, (start + end) // 2, end):
                assert _clicked(spans[0], column) == index

    def test_badges_on_a_second_line_keep_their_own_alerts(self):
        _lines, spans = render_alerts_mapped(_alerts(), width=74)

        assert [index for row in spans[:2] for _s, _e, index in row] == [0, 1, 2, 3]

    def test_the_shared_body_opens_the_first_of_its_group(self):
        _lines, spans = render_alerts_mapped(_alerts(), width=120)

        assert [index for _s, _e, index in spans[-1]] == [0]


class TestDashboardFits:
    """A frame taller or wider than the window scrolls the header away."""

    def _render(self, cols, rows, alerts, lang="en"):
        from linecast.weather import render_from_data

        data = json.loads((FIXTURES / "open_meteo_forecast.json").read_text())
        with patch("linecast.weather.get_terminal_size", return_value=(cols, rows)), \
             patch("linecast.weather._local_now_for_data", return_value=NOW), \
             patch("linecast._weather_hourly._local_now_for_data", return_value=NOW):
            output, row_map = render_from_data(
                data, alerts=alerts, runtime=_runtime(lang=lang),
                location_name="Hachijojima, Tokyo",
            )
        return output.split("\x00", 1)[0].split("\n"), row_map

    def test_the_frame_fits_the_window(self):
        for cols in (20, 40, 74, 80, 120, 200):
            for rows in (10, 14, 20, 24, 40):
                lines, _map = self._render(cols, rows, _alerts())
                assert len(lines) <= rows, (cols, rows)
                assert all(visible_len(line) <= cols for line in lines), (cols, rows)

    def test_a_short_window_keeps_the_conditions_line(self):
        lines, _map = self._render(80, 12, _alerts())

        assert "Overcast" in lines[0]

    def test_every_clickable_row_is_a_row_that_is_drawn(self):
        lines, row_map = self._render(74, 24, _alerts())

        assert row_map
        for row in row_map:
            assert 0 <= row < len(lines)
