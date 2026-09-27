"""scripts/pyz_preamble.py, which runs first inside linecast.pyz.

What it promises: a Python too old for linecast gets one plain line;
old unpacked builds go, but not this one, the one before it, or one
unpacking right now; and the weekly word about a newer release comes
only to a terminal, only once a week, and never in place of linecast
when PyPI can't be reached.
"""

import importlib.util
import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

PREAMBLE = Path(__file__).parent.parent / "scripts" / "pyz_preamble.py"


@pytest.fixture(scope="module")
def preamble():
    """The preamble as a module, without its __main__ block. The sdist
    leaves scripts/ out."""
    if not PREAMBLE.exists():
        pytest.skip("scripts/pyz_preamble.py is not in this tree")
    spec = importlib.util.spec_from_file_location("pyz_preamble", PREAMBLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def pypi(preamble, monkeypatch):
    """PyPI stood in for: set .newest to what it reports, or to an
    exception to raise. .asked counts the requests."""
    class PyPI:
        newest = "2.9.0"
        asked = 0

    def urlopen(request, timeout):
        PyPI.asked += 1
        assert request.full_url == preamble.PYPI
        if isinstance(PyPI.newest, Exception):
            raise PyPI.newest
        return io.BytesIO(json.dumps({"info": {"version": PyPI.newest}}).encode())

    monkeypatch.setattr(preamble.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(preamble, "version", lambda name: "2.8.0")
    return PyPI


def _on_a_terminal(monkeypatch):
    """stderr as a terminal. Called in the test itself: pytest puts its
    own capture back on sys.stderr after the fixtures are set up."""
    stream = _Terminal()
    monkeypatch.setattr(sys, "stderr", stream)
    return stream


def test_old_python_gets_one_plain_line(preamble):
    with pytest.raises(SystemExit) as exit_:
        preamble.check_python((3, 9, 6, "final", 0))
    assert "needs Python 3.10 or newer" in str(exit_.value)
    assert "Python 3.9 " in str(exit_.value)
    preamble.check_python((3, 10, 0, "final", 0))
    preamble.check_python(sys.version_info)


def test_tidy_keeps_this_build_the_one_before_and_one_unpacking(preamble, tmp_path):
    root = tmp_path / "linecast-pyz"
    for age, name in enumerate(["linecast.pyz_current", "linecast.pyz_before",
                                "linecast_older", "linecast.pyz_oldest"]):
        (root / name / "site-packages").mkdir(parents=True)
        (root / f".{name}_lock").touch()
        then = time.time() - age * 86400
        os.utime(root / name, (then, then))
    (root / "linecast.pyz_new.tmp").mkdir()
    (root / ".checked").touch()

    preamble.tidy(root / "linecast.pyz_current")

    assert sorted(p.name for p in root.iterdir()) == [
        ".checked",
        ".linecast.pyz_before_lock",
        ".linecast.pyz_current_lock",
        "linecast.pyz_before",
        "linecast.pyz_current",
        "linecast.pyz_new.tmp",
    ]


def test_tidy_never_raises(preamble, tmp_path):
    preamble.tidy(tmp_path / "gone" / "linecast.pyz_current")


def test_newer_release_is_named_with_the_command_to_fetch_it(
        preamble, pypi, tmp_path, monkeypatch):
    terminal = _on_a_terminal(monkeypatch)
    preamble.remind(tmp_path, tmp_path / "my apps" / "linecast")
    said = terminal.getvalue()
    assert said.startswith("linecast: 2.9.0 is out, and this is 2.8.0. To update:\n")
    here = tmp_path.resolve() / "my apps" / "linecast"
    assert f"curl -fLo '{here}' {preamble.LATEST}\n" in said
    assert (tmp_path / ".checked").exists()


def test_asks_once_a_week(preamble, pypi, tmp_path, monkeypatch):
    terminal = _on_a_terminal(monkeypatch)
    preamble.remind(tmp_path, "linecast.pyz")
    preamble.remind(tmp_path, "linecast.pyz")
    assert pypi.asked == 1
    assert terminal.getvalue().count("is out") == 1

    last_week = time.time() - preamble.WEEK - 60
    os.utime(tmp_path / ".checked", (last_week, last_week))
    preamble.remind(tmp_path, "linecast.pyz")
    assert pypi.asked == 2


def test_nothing_to_say_when_current(preamble, pypi, tmp_path, monkeypatch):
    terminal = _on_a_terminal(monkeypatch)
    pypi.newest = "2.8.0"
    preamble.remind(tmp_path, "linecast.pyz")
    assert pypi.asked == 1
    assert terminal.getvalue() == ""


def test_output_nobody_reads_neither_asks_nor_starts_the_week(
        preamble, pypi, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    preamble.remind(tmp_path, "linecast.pyz")
    assert pypi.asked == 0
    assert not (tmp_path / ".checked").exists()


@pytest.mark.parametrize("trouble", [OSError("offline"), "2.9.0rc1", "garbage"])
def test_trouble_with_pypi_is_silent_and_waits_a_week(
        preamble, pypi, tmp_path, monkeypatch, trouble):
    terminal = _on_a_terminal(monkeypatch)
    pypi.newest = trouble
    preamble.remind(tmp_path, "linecast.pyz")
    assert terminal.getvalue() == ""
    preamble.remind(tmp_path, "linecast.pyz")
    assert pypi.asked == 1
