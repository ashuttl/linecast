"""Tests for the maps string table.

Seventeen languages, one key list. The table is checked for shape rather
than for meaning: every language carries every key, no value is empty,
and every placeholder survives translation — the three ways a
translation table actually breaks at runtime.
"""

import sys
from pathlib import Path

import pytest

# Ensure the worktree src is preferred over any installed version.
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _maps_i18n
from linecast._completion import LANG_CODES
from linecast._framebuffer import visible_len
from linecast._maps_i18n import ms

TABLE = _maps_i18n._STRINGS
KEYS = set(TABLE["en"])


def test_every_language_the_cli_offers_has_a_table():
    assert set(LANG_CODES) <= set(TABLE)
    assert len(TABLE) == 17


@pytest.mark.parametrize("lang", sorted(TABLE))
def test_every_language_carries_every_key(lang):
    assert set(TABLE[lang]) == KEYS, sorted(set(TABLE[lang]) ^ KEYS)


@pytest.mark.parametrize("lang", sorted(TABLE))
def test_no_value_is_empty_or_padded(lang):
    for key, value in TABLE[lang].items():
        assert value, (lang, key)
        assert value == value.strip(), (lang, key)


@pytest.mark.parametrize("lang", sorted(TABLE))
def test_placeholders_survive_translation(lang):
    # A dropped {err} is a KeyError at the worst possible moment.
    for key, english in TABLE["en"].items():
        if "{err}" in english:
            assert "{err}" in TABLE[lang][key], (lang, key)
        else:
            assert "{" not in TABLE[lang][key], (lang, key)


@pytest.mark.parametrize("lang", sorted(TABLE))
def test_the_hints_fit_a_narrow_terminal(lang):
    # The footer hint shares 80 columns with a scale bar and an
    # attribution line; a hint that overflows costs the bar.
    for key in ("hint", "hint_route", "search_hint", "steps_hint"):
        assert visible_len(TABLE[lang][key]) <= 44, (lang, key)


@pytest.mark.parametrize("lang", sorted(TABLE))
def test_the_help_panel_entries_fit_their_column(lang):
    # 47 columns wide, 9 of them the key column, 3 for the frame.
    for key in TABLE[lang]:
        if key.startswith(("help_", "poi_")):
            assert visible_len(TABLE[lang][key]) <= 35, (lang, key)


def test_every_glyph_in_the_legend_has_a_name():
    from linecast import _maps_style as style
    from linecast._maps_ui import HELP_GLYPHS
    assert {g for g, _k in HELP_GLYPHS} == set(style.GLYPH_INK)
    for _glyph, key in HELP_GLYPHS:
        assert key in KEYS


def test_a_missing_key_falls_back_to_english_per_key(monkeypatch):
    monkeypatch.setitem(TABLE, "xx", {"hint": "local hint"})
    assert ms("hint", "xx") == "local hint"
    assert ms("mode_street", "xx") == TABLE["en"]["mode_street"]


def test_an_unknown_language_is_english():
    assert ms("mode_terrain", "qq") == TABLE["en"]["mode_terrain"]


def test_an_unknown_key_returns_itself_rather_than_raising():
    assert ms("no_such_key", "fr") == "no_such_key"


def test_formatting_reaches_every_language():
    for lang in TABLE:
        assert "boom" in ms("unavailable", lang, err="boom")
        assert "boom" in ms("streets_unavailable", lang, err="boom")
