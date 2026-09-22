"""linecast prose: the undocumented command that reads the weather prose
over a frozen set of forecasts."""

import json
import sys
from datetime import datetime
from io import StringIO
from unittest import mock

import pytest

from linecast import prose
from linecast import __main__ as cli
from linecast._weather.sections import narrative_lines


def _record(**overrides):
    """A frozen place with a comparison and a wind-chill sentence to say."""
    record = {
        "name": "Testville", "lat": 0.0, "lng": 0.0, "metric": False,
        "now": "2026-07-15T12:00:00",
        "data": {
            "current": {"temperature_2m": 40, "apparent_temperature": 30,
                        "relative_humidity_2m": 70, "wind_speed_10m": 18,
                        "wind_gusts_10m": 36, "weather_code": 3},
            "daily": {"time": ["2026-07-14", "2026-07-15", "2026-07-16"],
                      "sunrise": ["2026-07-14T05:40", "2026-07-15T05:40", "2026-07-16T05:40"],
                      "sunset": ["2026-07-14T20:55", "2026-07-15T20:55", "2026-07-16T20:55"],
                      "temperature_2m_max": [60, 62, 63], "temperature_2m_min": [50, 51, 52],
                      "precipitation_sum": [0, 0, 0], "precipitation_probability_max": [0, 0, 0],
                      "weather_code": [3, 3, 3]},
            "hourly": {},
        },
    }
    record.update(overrides)
    return record


class TestTrace:
    def test_every_candidate_is_recorded_and_the_chosen_ones_marked(self):
        record = _record()
        trace = []
        runtime = prose.runtime_for("en", False)
        rows = narrative_lines(record["data"], datetime(2026, 7, 15, 12), 1000, runtime,
                               trace=trace)
        said = prose._ANSI.sub("", " ".join(rows))

        assert [t["text"] for t in trace if t["chosen"]] == [
            "Today will be about the same temperature as yesterday",
            "The wind is making it feel cooler",
        ]
        for entry in trace:
            assert set(entry) == {"salience", "at", "text", "chosen"}
            assert (entry["text"] in said) == entry["chosen"]

    def test_the_trace_is_optional(self):
        record = _record()
        runtime = prose.runtime_for("en", False)
        assert narrative_lines(record["data"], datetime(2026, 7, 15, 12), 1000, runtime)

    def test_trace_lines_mark_the_chosen(self):
        lines = prose.trace_lines([
            {"salience": 3, "at": 0.0, "text": "Now", "chosen": True},
            {"salience": 2, "at": float("inf"), "text": "Then", "chosen": False},
        ])
        assert lines[0].startswith("* 3")
        assert lines[1].startswith("  2")
        assert "week" in lines[1]


class TestWindUnits:
    def test_a_metres_per_second_language_gets_converted_wind(self):
        record = _record(metric=True)
        record["data"]["hourly"] = {"wind_gusts_10m": [36.0, None]}
        data = prose.wind_for(record["data"], prose.runtime_for("ja", True))

        assert data["current"]["wind_gusts_10m"] == pytest.approx(10.0)
        assert data["hourly"]["wind_gusts_10m"] == [pytest.approx(10.0), None]
        # The frozen record is untouched
        assert record["data"]["current"]["wind_gusts_10m"] == 36

    def test_a_kilometres_per_hour_language_reads_the_data_as_is(self):
        record = _record(metric=True)
        data = prose.wind_for(record["data"], prose.runtime_for("fr", True))
        assert data is record["data"]


class TestShow:
    def test_prints_a_heading_and_a_paragraph_per_language(self):
        out = StringIO()
        said = prose.show([_record()], ["en", "ja"], 200, out=out)
        text = out.getvalue()

        assert "Testville   Wed 12:00   Overcast 40°F, feels 30°F" in text
        assert "    en  Today will be about the same temperature as yesterday." in text
        assert "    ja  " in text
        assert set(said["testville"]) == {"en", "ja"}
        assert said["testville"]["en"].endswith("feel cooler.")

    def test_continuation_lines_sit_under_the_first(self):
        out = StringIO()
        prose.show([_record()], ["en"], 50, out=out)
        lines = out.getvalue().splitlines()
        first = next(line for line in lines if line.startswith("    en  "))
        after = lines[lines.index(first) + 1]
        assert after.startswith(" " * len("    en  "))
        assert not after.startswith(" " * (len("    en  ") + 1))

    def test_data_adds_the_days_table(self):
        out = StringIO()
        prose.show([_record()], ["en"], 200, data=True, out=out)
        assert " yest " in out.getvalue()
        assert "today " in out.getvalue()

    def test_trace_adds_the_candidates(self):
        out = StringIO()
        prose.show([_record()], ["en"], 200, trace=True, out=out)
        assert "[en]" in out.getvalue()
        assert "* 3   +0.0h  The wind is making it feel cooler" in out.getvalue()


class TestDiff:
    def test_only_changed_paragraphs_are_listed(self):
        before = {"a": {"en": "Same.", "ja": "同じ。"}, "b": {"en": "Old."}}
        after = {"a": {"en": "Same.", "ja": "同じ。"}, "b": {"en": "New."}, "c": {"en": "Unseen."}}
        assert prose.diff_lines(before, after) == ["b [en]", "  - Old.", "  + New."]

    def test_silence_is_written_out(self):
        assert prose.diff_lines({"a": {"en": ""}}, {"a": {"en": "Said."}}) == [
            "a [en]", "  - (nothing to say)", "  + Said."]


class TestLanguages:
    def test_all_is_every_language(self):
        assert prose.languages("all") == list(prose.LANGUAGE_CODES)

    def test_a_list_keeps_its_order(self):
        assert prose.languages("ja,en") == ["ja", "en"]

    def test_an_unknown_code_is_refused(self):
        with pytest.raises(SystemExit):
            prose.languages("xx")

    def test_the_default_is_english_and_the_configured_language(self):
        with mock.patch.object(prose, "resolve_lang", return_value=("ja", "config")):
            assert prose.languages(None) == ["en", "ja"]
        with mock.patch.object(prose, "resolve_lang", return_value=("en", "default")):
            assert prose.languages(None) == ["en"]


class TestTheCommand:
    def test_save_then_diff_round_trip(self, tmp_path, monkeypatch, capsys):
        root = tmp_path / "prose" / "2026-07-15"
        root.mkdir(parents=True)
        record = _record()
        (root / "testville.json").write_text(json.dumps(record))
        (root / "index.json").write_text(json.dumps(["testville"]))
        monkeypatch.setattr(prose, "sets_root", lambda: tmp_path / "prose")

        saved = tmp_path / "before.json"
        prose.main(["--lang", "en", "--save", str(saved), "--width", "200"])
        assert json.loads(saved.read_text())["paragraphs"]["testville"]["en"]

        prose.main(["--diff", str(saved), "--lang", "en"])
        assert capsys.readouterr().out.strip().endswith("no change")

    def test_no_sets_says_how_to_get_one(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prose, "sets_root", lambda: tmp_path / "none")
        with pytest.raises(SystemExit, match="linecast prose fetch"):
            prose.main([])

    def test_dispatches_but_is_not_on_the_help_page(self):
        ran = {}

        def fake_import(name):
            ran["module"] = name
            return mock.Mock(main=lambda: None)

        old = sys.argv
        try:
            sys.argv = ["linecast", "prose", "--lang", "en"]
            with mock.patch("importlib.import_module", side_effect=fake_import):
                cli.main()
        finally:
            sys.argv = old
        assert ran["module"] == "linecast.prose"
        from linecast._commands import help_text
        from linecast._completion import TOP_LEVEL_COMMANDS
        assert "prose" not in help_text("0")
        assert "prose" not in TOP_LEVEL_COMMANDS
