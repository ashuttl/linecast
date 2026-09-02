"""The moon's calendar view: the month grid, its labels, and the hover chip.

These assert structure — every day lands once, the right days are
called out, nothing overflows — rather than exact pixels, in the manner
of test_moon_layout.
"""

import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._textwidth import visible_len  # noqa: E402

# Fixed-offset zones keep the ephemeris hermetic. September 2026 holds
# all four principal phases on distinct days.
ET = timezone(timedelta(hours=-4))
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 1, 14, 30, tzinfo=ET)


def _strip_ansi(text):
    text = re.sub(r"\x1b\][^\x1b]*\x1b\\", "", text)
    text = re.sub(r"\x1b\[[^a-zA-Z]*[a-zA-Z]", "", text)
    return re.sub(r"\x1b[()][0-9A-Za-z]", "", text)


def _render(cols, rows, lang="en", calendar=None, mouse_pos=None,
            month_offset=0, now=NOW, lat=43.7, lng=-70.3, israel=False):
    from linecast._moon_calendar import render_calendar
    from linecast._runtime import RuntimeConfig

    runtime = RuntimeConfig(live=False, icons="emoji", lang=lang,
                            oneline=False)
    with patch("linecast._moon_calendar.get_terminal_size",
               return_value=(cols, rows)):
        out = render_calendar(now, lat, lng, runtime, fullscreen=True,
                              mouse_pos=mouse_pos, month_offset=month_offset,
                              calendar_name=calendar, israel=israel)
    parts = out.split("\x00", 1)
    body = _strip_ansi(parts[0]).split("\n")
    chip = _strip_ansi(parts[1]) if len(parts) > 1 else ""
    return body, chip


def _blocks_to_space(line):
    return re.sub(r"[▀▄█]", " ", line)


class TestGrid:
    def test_every_day_lands_exactly_once(self):
        body, _chip = _render(100, 32)
        tokens = re.findall(r"\d+", _blocks_to_space("\n".join(body)))
        days = sorted(int(t) for t in tokens if 1 <= int(t) <= 30)
        assert days == list(range(1, 31))

    def test_title_and_weekdays(self):
        body, _chip = _render(100, 32)
        assert "Sep 2026" in body[0]
        assert "Sun" in body[1] and "Sat" in body[1]
        # English weeks open on Sunday: Sep 1 2026 is a Tuesday, so day 1
        # sits under the third column, two empty cells in.
        first_day_row = next(line for line in body
                             if re.search(r"\b1\b", _blocks_to_space(line)))
        assert _blocks_to_space(first_day_row).index("1") >= 2 * (100 // 7)

    def test_monday_first_for_german(self):
        body, _chip = _render(100, 32, lang="de")
        assert body[1].strip().startswith("Mo")

    def test_nothing_overflows(self):
        for cols, rows in ((100, 32), (80, 24), (44, 16), (30, 12)):
            body, _chip = _render(cols, rows)
            assert len(body) <= rows
            assert all(visible_len(line) <= cols for line in body)

    def test_tiny_grid_falls_back_to_glyphs(self):
        body, _chip = _render(30, 12)
        assert any("🌒" in line or "🌘" in line for line in body)

    def test_paged_month_names_itself_and_the_way_back(self):
        body, _chip = _render(100, 32, month_offset=1)
        assert "Oct 2026" in body[0]
        assert "space" in body[0]


class TestPhaseDays:
    def test_september_2026_principal_phases(self):
        from linecast._moon_calendar import principal_phase_days
        found = {d.day: idx
                 for d, (idx, _at) in principal_phase_days(2026, 9, ET).items()}
        # Last quarter the 4th, new the 10th, first quarter the 18th,
        # full the 26th — Eastern Time.
        assert found == {4: 6, 10: 0, 18: 2, 26: 4}

    def test_meridian_moves_the_day(self):
        from linecast._moon_calendar import principal_phase_days
        found = {d.day: idx
                 for d, (idx, _at) in principal_phase_days(2026, 9, JST).items()}
        assert found[11] == 0 and found[27] == 4


class TestCalendars:
    def test_japanese_month_start_and_tsukimi(self):
        now = datetime(2026, 9, 1, 14, 30, tzinfo=JST)
        body, _chip = _render(100, 32, lang="ja", now=now, lat=35.7, lng=139.7)
        text = "\n".join(body)
        assert "8月" in text        # 旧暦8月 opens on the 11th
        assert "十五夜" in text     # the 25th
        assert "2026年9月" in body[0]

    def test_chinese_day_names_and_festival(self):
        now = datetime(2026, 9, 1, 14, 30, tzinfo=timezone(timedelta(hours=8)))
        body, _chip = _render(100, 32, lang="zh", calendar="chinese", now=now)
        text = "\n".join(body)
        assert "初二" in text
        assert "中秋节" in text

    def test_hawaiian_names_the_nights(self):
        body, _chip = _render(120, 34, calendar="hawaiian")
        text = "\n".join(body)
        assert "Hilo" in text and "Muku" in text

    def test_samoan_and_chamorro_name_the_nights(self):
        body, _chip = _render(120, 34, calendar="samoan")
        text = "\n".join(body)
        assert "Masina Fou" in text and "Masina Maunā" in text
        body, _chip = _render(120, 34, calendar="refaluwasch")
        text = "\n".join(body)
        assert "Sinahen Håcha" in text and "Sinahi" in text

    def test_islamic_month_starts_and_observances(self):
        # Ramadan 1447 opens on 18 February 2026; the grid marks the
        # month start, and March carries Laylat al-Qadr and Eid al-Fitr.
        now = datetime(2026, 2, 10, 14, 30, tzinfo=ET)
        body, _chip = _render(120, 34, calendar="islamic", now=now)
        text = "\n".join(body)
        assert "18 Ramadan" in text
        body, _chip = _render(120, 34, calendar="islamic", now=now,
                              month_offset=1)
        text = "\n".join(body)
        # A 16-cell column clips the longer name after the day number.
        assert "16 Laylat al" in text and "20 Eid al-Fitr" in text

    def test_hebrew_holidays_and_month_starts(self):
        # Tishrei 5787 opens on 12 September 2026: the grid names the
        # two days of Rosh Hashanah, Yom Kippur, and the days of
        # Sukkot, and October carries Simchat Torah and 1 Cheshvan.
        now = datetime(2026, 9, 2, 14, 30, tzinfo=ET)
        body, _chip = _render(120, 34, calendar="hebrew", now=now)
        text = "\n".join(body)
        assert "12 Rosh Hashan" in text and "13 Rosh Hashan" in text
        assert "21 Yom Kippur" in text
        assert "26 Sukkot" in text and "30 Sukkot" in text
        body, _chip = _render(120, 34, calendar="hebrew", now=now,
                              month_offset=1)
        text = "\n".join(body)
        assert "4 Simchat Tora" in text and "12 Cheshvan" in text

    def test_hebrew_holidays_in_israel(self):
        # Seen from Jerusalem, Simchat Torah shares Shemini Atzeret's
        # day and 4 October is an ordinary day.
        now = datetime(2026, 9, 2, 14, 30, tzinfo=ET)
        body, _chip = _render(120, 34, calendar="hebrew", now=now,
                              month_offset=1, israel=True)
        text = "\n".join(body)
        assert "3 Shemini Atz" in text
        assert "4 Simchat Tora" not in text

    def test_hebrew_months_in_the_title(self):
        # September runs from Elul into Tishrei, across the new year;
        # October stays in 5787; February 2025 sat inside Shevat.
        now = datetime(2026, 9, 2, 14, 30, tzinfo=ET)
        body, _chip = _render(120, 34, calendar="hebrew", now=now)
        assert "Sep 2026 · Elul 5786 – Tishrei 5787" in body[0]
        body, _chip = _render(120, 34, calendar="hebrew", now=now,
                              month_offset=1)
        assert "Oct 2026 · Tishrei – Cheshvan 5787" in body[0]
        now = datetime(2025, 2, 10, 14, 30, tzinfo=ET)
        body, _chip = _render(120, 34, calendar="hebrew", now=now)
        assert "Feb 2025 · Shevat 5785" in body[0]

    def test_hijri_months_in_the_title(self):
        now = datetime(2026, 9, 2, 14, 30, tzinfo=ET)
        body, _chip = _render(120, 34, calendar="islamic", now=now)
        assert ("Sep 2026 · Rabiʻ al-Awwal – Rabiʻ al-Thani 1448 AH"
                in body[0])
        body, _chip = _render(120, 34, calendar="islamic", now=now,
                              lang="id")
        assert "Rabiulawal – Rabiulakhir 1448 H" in body[0]

    def test_title_span_yields_to_a_narrow_grid(self):
        # Paged away on a narrow terminal, the way back keeps its place
        # and the calendar's months are the part that goes.
        now = datetime(2026, 9, 2, 14, 30, tzinfo=ET)
        body, _chip = _render(48, 24, calendar="islamic", now=now,
                              month_offset=1)
        assert "Oct 2026" in body[0] and "Rabi" not in body[0]
        assert "now" in body[0]

    def test_plain_english_carries_no_labels(self):
        body, _chip = _render(100, 32)
        assert "月" not in "\n".join(body)


class TestHoverChip:
    def _chip_over(self, day, **kw):
        # Day cells are cell_w=100//7=14 wide from left=1, cell_h=6 from
        # row 2 (32-row fullscreen, 5 weeks); Sep 2026 leads with 2 blanks.
        slot = 2 + day - 1
        wk, c = divmod(slot, 7)
        col = 1 + c * 14 + 3
        row = 3 + wk * 6 + 2
        return _render(100, 32, mouse_pos=(col, row), **kw)

    def test_ordinary_day_reads_phase_and_events(self):
        _body, chip = self._chip_over(16)
        assert "Sep 16" in chip
        assert "illuminated" in chip
        assert "↑" in chip and "↓" in chip

    def test_principal_day_reads_the_moment(self):
        _body, chip = self._chip_over(26)
        assert "Full" in chip
        assert re.search(r"\d{1,2}:\d{2}", chip)

    def test_full_moon_keeps_its_almanac_name(self):
        _body, chip = self._chip_over(26)
        assert "Harvest" in chip

    def test_calendar_line_rides_along(self):
        _body, chip = self._chip_over(25, calendar="chinese")
        assert "Mid-Autumn" in chip

    def test_japanese_night_named_once(self):
        # 十五夜 is both the night's name and the festival's on 8/15.
        _body, chip = self._chip_over(25, lang="ja", calendar="japanese")
        assert "十五夜 · 旧暦8月15日" in chip
        assert chip.count("十五夜") == 1
        _body, chip = self._chip_over(26, lang="ja", calendar="japanese")
        assert "十六夜 · 旧暦8月16日" in chip

    def test_hijri_date_in_the_chip(self):
        # March 2026 opens on a Sunday, so day 20 is week 2, column 5.
        pos = (1 + 5 * 14 + 3, 3 + 2 * 6 + 2)
        _body, chip = _render(100, 32, mouse_pos=pos, calendar="islamic",
                              now=datetime(2026, 3, 1, 14, 30, tzinfo=ET))
        assert "Eid al-Fitr · 1 Shawwal 1447 AH" in chip

    def test_hebrew_date_in_the_chip(self):
        # September 2026 opens on a Tuesday, so the 12th is week 1,
        # column 6, and October's 11th (a Sunday) is week 2, column 0.
        now = datetime(2026, 9, 1, 14, 30, tzinfo=ET)
        pos = (1 + 6 * 14 + 3, 3 + 1 * 6 + 2)
        _body, chip = _render(100, 32, mouse_pos=pos, calendar="hebrew",
                              now=now)
        assert "Rosh Hashanah · 1 Tishrei 5787" in chip
        pos = (1 + 0 * 14 + 3, 3 + 2 * 6 + 2)
        _body, chip = _render(100, 32, mouse_pos=pos, calendar="hebrew",
                              now=now, month_offset=1)
        assert "Rosh Chodesh Cheshvan · 30 Tishrei 5787" in chip

    def test_off_grid_raises_nothing(self):
        _body, chip = _render(100, 32, mouse_pos=(1, 1))
        assert chip == ""


class TestClickedDay:
    def test_maps_a_cell_to_its_day(self):
        from datetime import date
        from linecast._moon_calendar import clicked_day
        _render(100, 32)
        # Same geometry as TestHoverChip: day 16 sits in week 2, col 3.
        assert clicked_day(1 + 3 * 14 + 3, 3 + 2 * 6 + 2) == date(2026, 9, 16)

    def test_matches_the_hover_chip(self):
        from linecast._moon_calendar import clicked_day
        pos = (1 + 3 * 14 + 3, 3 + 2 * 6 + 2)
        _body, chip = _render(100, 32, mouse_pos=pos)
        d = clicked_day(*pos)
        assert f"Sep {d.day}" in chip

    def test_off_grid_is_none(self):
        from linecast._moon_calendar import clicked_day
        _render(100, 32)
        assert clicked_day(1, 1) is None
        assert clicked_day(1000, 1000) is None

    def test_leading_blank_cell_is_none(self):
        from linecast._moon_calendar import clicked_day
        _render(100, 32)
        # Sep 2026 leads with two empty cells (Sun, Mon of week one).
        assert clicked_day(1 + 3, 3 + 2) is None


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
class TestFlags:
    def _run(self, *flags):
        import os
        root = Path(__file__).parent.parent
        return subprocess.run(
            [sys.executable, "-m", "linecast", "moon", *flags],
            capture_output=True, text=True, cwd=root,
            env={**os.environ, "PYTHONPATH": str(root / "src")},
        )

    def test_grid_has_no_json_output(self):
        done = self._run("--grid", "--json")
        assert done.returncode == 2
        assert "--grid has no --json output" in done.stderr

    def test_grid_has_no_oneline_output(self):
        done = self._run("--grid", "--oneline")
        assert done.returncode == 2
        assert "--grid has no --oneline output" in done.stderr

    def test_grid_parses_with_a_calendar(self):
        from linecast._runtime import moon_parser
        args = moon_parser().parse_args(["--grid", "--calendar", "hebrew"])
        assert args.grid and args.calendar == "hebrew"
        assert not moon_parser().parse_args([]).grid
