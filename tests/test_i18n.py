"""The shared string-table lookup behind _s, _ts, _ms, rs and ms."""

from types import SimpleNamespace

from linecast._i18n import lang_of, lookup
from linecast._maps_i18n import ms
from linecast._moon_i18n import _ms
from linecast._radar_i18n import rs
from linecast._tides_i18n import _ts
from linecast._weather_i18n import _s

TABLE = {
    "en": {"hello": "Hello", "count": "{n} items", "braces": "{literal}"},
    "fr": {"hello": "Bonjour"},
}


class TestLookup:
    def test_language_then_english_then_key(self):
        assert lookup(TABLE, "hello", "fr") == "Bonjour"
        assert lookup(TABLE, "count", "fr", n=2) == "2 items"
        assert lookup(TABLE, "missing", "fr") == "missing"
        assert lookup(TABLE, "hello", "xx") == "Hello"

    def test_formats_only_when_given_kwargs(self):
        assert lookup(TABLE, "braces", "en") == "{literal}"


class TestLangOf:
    def test_runtime_language_or_english(self):
        assert lang_of(SimpleNamespace(lang="de")) == "de"
        assert lang_of(SimpleNamespace()) == "en"
        assert lang_of(None) == "en"


class TestWrappers:
    def test_each_command_helper_reads_its_own_table(self):
        fr = SimpleNamespace(lang="fr")
        assert _s("feels", fr) != _s("feels", None)
        assert _ts("space_to_now", fr) != _ts("space_to_now", None)
        assert _ms("up_now", fr) != _ms("up_now", None)
        assert rs("loading", "fr") != rs("loading", "en")
        assert ms("hint", "fr") != ms("hint", "en")
        assert _s("no_such_key", fr) == "no_such_key"
