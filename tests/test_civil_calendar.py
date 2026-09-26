"""The civil calendar: Solar Hijri dates in Persian, Gregorian elsewhere,
and the views that write dates through it."""

import io
import json
import re
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from linecast.astro.calendars.civil import (
    GREGORIAN, SOLAR_HIJRI, civil_calendar, dates_choice, resolve_dates,
    shift_month, solar_hijri_date_label, solar_hijri_day_month,
    solar_hijri_day_of_year, solar_hijri_month_title,
)
from linecast._runtime import RuntimeConfig

IRST = timezone(timedelta(hours=3, minutes=30))
ET = timezone(timedelta(hours=-4))


def _runtime(lang="fa", week_start="saturday"):
    return RuntimeConfig(live=False, icons="emoji", lang=lang, oneline=False,
                         week_start=week_start)


class TestHook:
    def test_persian_is_solar_hijri_and_the_rest_gregorian(self):
        assert civil_calendar("fa") == SOLAR_HIJRI
        for lang in ("en", "de", "ja", "zh-Hant", "pt-PT"):
            assert civil_calendar(lang) == GREGORIAN

    def test_env_and_config_override_the_language(self, monkeypatch):
        from linecast._config import write_config
        write_config({"dates": "gregorian"})
        assert resolve_dates("fa") == (GREGORIAN, "config")
        monkeypatch.setenv("LINECAST_DATES", "solar-hijri")
        assert resolve_dates("en") == (SOLAR_HIJRI, "LINECAST_DATES")
        assert resolve_dates("fa") == (SOLAR_HIJRI, "LINECAST_DATES")
        monkeypatch.setenv("LINECAST_DATES", "nonsense")
        assert resolve_dates("fa") == (GREGORIAN, "config")

    def test_choice_spellings(self):
        assert dates_choice("Solar_Hijri") == "solar-hijri"
        assert dates_choice(" gregorian ") == "gregorian"
        assert dates_choice("julian") is None
        assert dates_choice(3) is None

    def test_dates_command_sets_and_clears(self, monkeypatch):
        from linecast import _config
        from linecast.settings import dates
        with redirect_stdout(io.StringIO()):
            dates._cmd_set("gregorian")
        assert _config.saved_dates() == "gregorian"
        assert json.loads(_config.config_file().read_text())["dates"] == "gregorian"
        out = io.StringIO()
        with redirect_stdout(out):
            dates._cmd_show()
        assert "gregorian  [fixed]" in out.getvalue()
        with redirect_stdout(io.StringIO()):
            dates._cmd_auto()
        assert _config.saved_dates() is None


class TestFormatting:
    def test_first_of_mehr(self):
        # 23 September 2026 is 1 Mehr 1405: ۱ مهر ۱۴۰۵ once the output
        # pass writes Persian digits.
        d = date(2026, 9, 23)
        assert solar_hijri_date_label(d, "fa") == "1 مهر 1405"
        assert solar_hijri_day_month(d, "fa") == "1 مهر"
        assert solar_hijri_day_month(date(2026, 9, 22), "fa") == "31 شهریور"
        assert solar_hijri_date_label(d, "en") == "1 Mehr 1405"
        assert solar_hijri_month_title(1405, 7, "fa") == "مهر 1405"

    def test_persian_digits_come_from_the_output_pass(self):
        from linecast import _bidi
        _bidi.configure("fa", {})
        shown = _bidi.display(solar_hijri_date_label(date(2026, 9, 23), "fa"))
        assert "۱۴۰۵" in shown and "۱" in shown and "1" not in shown

    def test_day_of_year(self):
        assert solar_hijri_day_of_year(date(2026, 9, 23)) == (187, 365)
        assert solar_hijri_day_of_year(date(2026, 3, 21)) == (1, 365)

    def test_shift_month_crosses_the_year(self):
        assert shift_month(1405, 12, 1) == (1406, 1)
        assert shift_month(1405, 1, -1) == (1404, 12)
        assert shift_month(1405, 7, 0) == (1405, 7)

    def test_fmt_month_day_follows_the_civil_calendar(self, monkeypatch):
        from linecast.moon.i18n import _fmt_month_day, gregorian_date_label
        when = datetime(2026, 9, 23, 12, tzinfo=IRST)
        assert _fmt_month_day(when, SimpleNamespace(lang="fa")) == "1 مهر"
        assert _fmt_month_day(when, SimpleNamespace(lang="en")) == "Sep 23"
        assert gregorian_date_label(when, "fa") == "23 سپتامبر 2026"
        monkeypatch.setenv("LINECAST_DATES", "gregorian")
        assert _fmt_month_day(when, SimpleNamespace(lang="fa")) == "23 سپتامبر"
        monkeypatch.setenv("LINECAST_DATES", "solar-hijri")
        assert _fmt_month_day(when, SimpleNamespace(lang="en")) == "1 Mehr"


def _grid(now, lang="fa", month_offset=0, mouse_pos=None, calendar=None,
          week_start="saturday"):
    from linecast.moon.calendar import render_calendar
    with patch("linecast.moon.calendar.get_terminal_size",
               return_value=(100, 32)):
        out = render_calendar(now, 35.69, 51.39, _runtime(lang, week_start),
                              month_offset=month_offset, mouse_pos=mouse_pos,
                              calendar_name=calendar)
    parts = out.split("\x00", 1)
    strip = lambda s: re.sub(r"\x1b\[[^a-zA-Z]*[a-zA-Z]", "", s)  # noqa: E731
    return strip(parts[0]).split("\n"), strip(parts[1]) if len(parts) > 1 else ""


class TestMoonGrid:
    NOW = datetime(2026, 9, 23, 14, 0, tzinfo=IRST)

    def test_a_solar_hijri_month(self):
        from linecast.moon import calendar as moon_calendar
        body, _chip = _grid(self.NOW)
        assert body[0].strip().startswith("مهر 1405 · سپتامبر – اکتبر 2026")
        assert "ربیع\u200cالثانی – جمادی\u200cالاول 1448 ق" in body[0]
        _l, _r, _cw, _ch, _w, lead, days_in, first, civil = moon_calendar._last_grid
        # 1 Mehr is a Wednesday: four cells into a Saturday-first week.
        assert (first, days_in, civil) == (date(2026, 9, 23), 30, SOLAR_HIJRI)
        assert lead == 4
        assert body[1].split()[0] == "ش"

    def test_cells_carry_the_gregorian_day(self):
        from linecast.moon import calendar as moon_calendar
        body, _chip = _grid(self.NOW)
        left, row0, cell_w, cell_h, _w, lead, _n, _first, _c = moon_calendar._last_grid

        def bottom(day):
            wk, c = divmod(lead + day - 1, 7)
            line = re.sub(r"[▀▄█]", " ", body[row0 + wk * cell_h + cell_h - 1])
            return line[left + c * cell_w:left + (c + 1) * cell_w]

        # 1 Mehr is 23 September, 9 Mehr 1 October.
        assert bottom(1).lstrip().startswith("23")
        assert bottom(9).lstrip().startswith("اکتبر 1")

    def test_clicks_and_hover_land_on_the_right_day(self):
        from linecast.moon import calendar as moon_calendar
        body, _chip = _grid(self.NOW)
        left, row0, cell_w, cell_h, *_rest = moon_calendar._last_grid
        col = left + 4 * cell_w + 2 + 1       # 1-based, inside 1 Mehr
        row = row0 + 1 + 1
        assert moon_calendar.clicked_day(col, row) == date(2026, 9, 23)
        _body, chip = _grid(self.NOW, mouse_pos=(col, row))
        assert "1 مهر" in chip and "23 سپتامبر 2026" in chip
        assert "ام\u200cالقری" in chip        # the Iranian sighting caveat

    def test_paging_from_esfand_into_farvardin(self):
        from linecast.moon import calendar as moon_calendar
        now = datetime(2027, 3, 1, 12, tzinfo=IRST)   # 10 Esfand 1405
        body, _chip = _grid(now)
        assert body[0].strip().startswith("اسفند 1405")
        assert moon_calendar._last_grid[6] == 29
        body, _chip = _grid(now, month_offset=1)
        assert body[0].strip().startswith("فروردین 1406")
        first = moon_calendar._last_grid[7]
        assert first == date(2027, 3, 21)
        # A Sunday, one cell into a Saturday-first week.
        assert moon_calendar._last_grid[5] == 1
        body, _chip = _grid(now, month_offset=-12)
        assert body[0].strip().startswith("اسفند 1404")
        assert moon_calendar._last_grid[6] == 29

    def test_other_languages_keep_the_gregorian_month(self):
        from linecast.moon import calendar as moon_calendar
        body, _chip = _grid(self.NOW, lang="en", week_start="monday")
        assert body[0].strip().startswith("Sep 2026")
        assert moon_calendar._last_grid[7] == date(2026, 9, 1)

    def test_gregorian_setting_in_persian(self, monkeypatch):
        monkeypatch.setenv("LINECAST_DATES", "gregorian")
        body, _chip = _grid(self.NOW)
        assert body[0].strip().startswith("سپتامبر 2026")


class TestMoonPanel:
    def _lines(self, now):
        from linecast.moon.view import solar_hijri_lines
        return solar_hijri_lines(now, _runtime())

    def test_the_next_observance(self):
        fest, short, turn = self._lines(datetime(2026, 9, 23, 21, tzinfo=IRST))
        assert fest == "جشن مهرگان 10 مهر (9 روز دیگر)"
        assert short == "جشن مهرگان 10 مهر"
        assert turn is None

    def test_on_the_day_the_name_stands_alone(self):
        fest, _short, _turn = self._lines(datetime(2026, 12, 21, 20, tzinfo=IRST))
        assert fest == "شب یلدا"

    def test_nowruz_counts_down_in_days_then_to_the_second(self):
        fest, _short, turn = self._lines(datetime(2027, 3, 1, 12, tzinfo=IRST))
        assert fest == "چهارشنبه\u200cسوری 25 اسفند (15 روز دیگر)"
        assert re.fullmatch(r"تحویل سال 1406 · 29 اسفند \d\d:\d\d:\d\d \(19 روز دیگر\)",
                            turn)
        fest, _short, turn = self._lines(datetime(2027, 3, 20, 20, tzinfo=IRST))
        assert fest is None      # Nowruz's own line gives way to the countdown
        assert re.fullmatch(r"تحویل سال 1406 · 23:5\d:\d\d \(3:5\d:\d\d دیگر\)", turn)

    def test_outside_the_window_there_is_no_countdown(self):
        _fest, _short, turn = self._lines(datetime(2027, 2, 10, 12, tzinfo=IRST))
        assert turn is None

    def test_the_panel_shows_them_in_persian_only(self):
        from linecast.moon.view import render
        with patch("linecast.moon.view.get_terminal_size", return_value=(120, 34)):
            fa = render(datetime(2026, 9, 23, 21, tzinfo=IRST), 35.69, 51.39,
                        _runtime())
            en = render(datetime(2026, 9, 23, 21, tzinfo=IRST), 35.69, 51.39,
                        _runtime("en"))
        assert "جشن مهرگان" in fa and "روز 187 از 365" in fa
        assert "Mehregan" not in en and "Sep 23" not in en


class TestSunshineYear:
    def _ticks(self, lang, width):
        from linecast.sunshine.year import _month_ticks
        return _month_ticks(2026, 365, width, SimpleNamespace(lang=lang))

    def test_ticks_at_solar_hijri_month_starts(self):
        ticks = self._ticks("fa", 130)
        labels = [label for _x, label in ticks]
        assert labels[:3] == ["دی", "بهمن", "اسفند"]
        assert labels[-1] == "دی"
        # 1 Farvardin 1405 is 21 March 2026, day 79 of the year.
        x = dict((label, x) for x, label in ticks[1:])["فروردین"]
        assert x == int(79 / 365 * 130)

    def test_numbers_when_the_names_do_not_fit(self):
        labels = [label for _x, label in self._ticks("fa", 100)]
        assert labels[0] == "10" and labels[1:4] == ["11", "12", "1"]

    def test_gregorian_ticks_unchanged(self):
        ticks = self._ticks("en", 100)
        assert [label for _x, label in ticks][:2] == ["Jan", "Feb"]
        assert ticks[1][0] == int(31 / 365 * 100)

    def test_yalda_named_in_the_info_line(self):
        from linecast.sunshine.view import _named_night
        assert _named_night(date(2026, 12, 21), SimpleNamespace(lang="fa")) == "شب یلدا"
        assert _named_night(date(2026, 12, 22), SimpleNamespace(lang="fa")) is None
        assert _named_night(date(2026, 12, 21), SimpleNamespace(lang="en")) is None


@pytest.mark.parametrize("lang", ["en", "de", "ja"])
def test_other_languages_do_not_change(lang):
    from linecast.moon.i18n import _fmt_month_day, gregorian_month_day
    when = datetime(2026, 9, 23, 12, tzinfo=ET)
    assert _fmt_month_day(when, SimpleNamespace(lang=lang)) == gregorian_month_day(when, lang)
