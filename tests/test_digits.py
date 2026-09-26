"""`linecast digits`: Persian digits by default in Persian, 0-9 by
choice, and the output pass following the saved setting."""

import io
import json
import re
from contextlib import redirect_stdout

import pytest

from linecast import _config
from linecast.terminal import bidi as _bidi
from linecast.settings import digits
from linecast.terminal.bidi import digits_choice, resolve_digits

_SGR = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text):
    return _SGR.sub("", text)


@pytest.fixture(autouse=True)
def _english_after():
    yield
    _bidi.configure("en", {})


class TestResolve:
    def test_auto_is_native_where_the_language_has_its_own(self):
        assert resolve_digits("fa", {}) == ("native", "auto")
        assert resolve_digits("en", {}) == ("latin", "auto")
        assert resolve_digits("ar", {}) == ("latin", "auto")

    def test_env_beats_config_beats_the_language(self):
        _config.write_config({"digits": "latin"})
        assert resolve_digits("fa", {}) == ("latin", "config")
        env = {"LINECAST_DIGITS": "native"}
        assert resolve_digits("fa", env) == ("native", "LINECAST_DIGITS")
        assert resolve_digits("fa", {"LINECAST_DIGITS": "roman"}) == (
            "latin", "config")

    def test_choice_spellings(self):
        assert digits_choice(" Latin ") == "latin"
        assert digits_choice("native") == "native"
        assert digits_choice("persian") is None
        assert digits_choice(3) is None

    def test_junk_in_the_config_is_no_setting(self):
        _config.write_config({"digits": "roman"})
        assert _config.saved_digits() is None
        assert resolve_digits("fa", {}) == ("native", "auto")

    def test_a_corrupt_config_never_raises(self):
        path = _config.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{not json")
        assert resolve_digits("fa", {}) == ("native", "auto")
        _bidi.configure("fa", {})


class TestOutputPass:
    def test_persian_digits_by_default(self):
        _bidi.configure("fa", {})
        assert _plain(_bidi.display("12")) == "۱۲"

    def test_saved_latin_keeps_ascii_digits(self):
        _config.write_config({"digits": "latin"})
        _bidi.configure("fa", {})
        assert _plain(_bidi.display("12")) == "12"

    def test_env_native_overrides_saved_latin(self):
        _config.write_config({"digits": "latin"})
        _bidi.configure("fa", {"LINECAST_DIGITS": "native"})
        assert _plain(_bidi.display("12")) == "۱۲"

    def test_auto_in_english_leaves_persian_digits_be(self):
        _bidi.configure("en", {})
        assert _plain(_bidi.display("abc ۱۲")) == "abc ۱۲"

    def test_native_in_english_changes_nothing(self):
        _config.write_config({"digits": "native"})
        _bidi.configure("en", {})
        assert _plain(_bidi.display("12")) == "12"


class TestCommand:
    def test_sets_shows_and_clears(self, monkeypatch):
        monkeypatch.setenv("LINECAST_LANG", "fa")
        with redirect_stdout(io.StringIO()):
            digits._cmd_set("latin")
        assert _config.saved_digits() == "latin"
        assert json.loads(_config.config_file().read_text())["digits"] == "latin"

        out = io.StringIO()
        with redirect_stdout(out):
            digits._cmd_show()
        assert "latin  [fixed]" in out.getvalue()

        monkeypatch.setenv("LINECAST_DIGITS", "native")
        out = io.StringIO()
        with redirect_stdout(out):
            digits._cmd_show()
        assert "native  [LINECAST_DIGITS]" in out.getvalue()
        assert "The saved setting (latin) is overridden" in out.getvalue()

        monkeypatch.delenv("LINECAST_DIGITS")
        with redirect_stdout(io.StringIO()):
            digits._cmd_auto()
        assert _config.saved_digits() is None
        assert "digits" not in _config.read_config()

        out = io.StringIO()
        with redirect_stdout(out):
            digits._cmd_show()
        assert out.getvalue().startswith("native  [auto:")

    def test_dispatched_from_the_top_level(self, monkeypatch):
        import sys

        from linecast import __main__ as cli
        monkeypatch.setattr(sys, "argv", ["linecast", "digits", "latin"])
        out = io.StringIO()
        with redirect_stdout(out):
            cli.main()
        assert _config.saved_digits() == "latin"
        assert "0-9" in out.getvalue()
