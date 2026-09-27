"""Runs first inside linecast.pyz, the single-file build on each GitHub
release, and nowhere else.

scripts/build_pyz.sh hands this file to shiv as its preamble. The first
time a build runs, shiv unpacks it into a directory of its own under
~/.cache/linecast-pyz; then, on every run, it sets site_packages (that
directory's site-packages) and archive (the path the pyz was run as),
runs this, and runs linecast.

It does what a package manager would otherwise do for the one file:
refuses a Python older than linecast supports, clears away builds
unpacked by older copies, and once a week says when a newer release is
out, with the command that fetches it.

Keep it to syntax an old Python can parse, so that the version check
gets to run.
"""

import json
import os
import shlex
import shutil
import sys
import threading
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

LATEST = "https://github.com/ashuttl/linecast/releases/latest/download/linecast.pyz"
PYPI = "https://pypi.org/pypi/linecast/json"
WEEK = 7 * 24 * 3600
BUDGET = 2  # seconds the weekly check may add to a run, name lookup included


def check_python(version_info=sys.version_info):
    """Exit with a plain line on a Python linecast can't run on, where
    pip would have refused to install it, and point to the installs
    that bring a newer one (the Mac's own python3 is still 3.9)."""
    if tuple(version_info[:2]) < (3, 10):
        sys.exit(f"linecast needs Python 3.10 or newer, and this is Python "
                 f"{version_info[0]}.{version_info[1]} ({sys.executable}).\n"
                 f"Homebrew and uv can install linecast with a newer Python: "
                 f"https://github.com/ashuttl/linecast#install")


def tidy(build):
    """Remove the builds unpacked beside this one, except the newest of
    them, which may still be running in another terminal.

    shiv names each directory for the file and the build, and never
    removes one. The directory above is linecast's alone. A name ending
    .tmp is a build unpacking right now; a dotted name is a shiv lock
    or the stamp remind() keeps.
    """
    root = build.parent
    try:
        others = [p for p in root.iterdir()
                  if p != build and p.is_dir()
                  and not p.name.startswith(".") and not p.name.endswith(".tmp")]
        others.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for old in others[1:]:
            shutil.rmtree(old, ignore_errors=True)
            (root / f".{old.name}_lock").unlink(missing_ok=True)
    except OSError:
        pass


def _release(text):
    return tuple(int(part) for part in text.split("."))


def _ask_pypi(mine, answer):
    """Append PyPI's newest version to answer. Any failure leaves it
    empty: offline, or PyPI answered oddly, and there is nothing to say."""
    try:
        request = urllib.request.Request(
            PYPI, headers={"User-Agent": f"linecast/{mine} (pyz)"})
        with urllib.request.urlopen(request, timeout=BUDGET) as response:
            answer.append(json.load(response)["info"]["version"])
    except Exception:
        pass


def remind(root, archive):
    """Once a week, when someone is there to read it, ask PyPI for the
    newest release and say so if it is newer than this one.

    A run whose output nobody sees, such as a status bar's, neither
    asks nor starts the week. The stamp is touched before asking, so a
    request that fails waits a week like any other.

    The request's timeout doesn't cover looking up the name, which a
    broken network can stall for ten seconds, so it runs on a thread of
    its own and linecast goes on without it after BUDGET.

    The command overwrites the file that was run, which keeps its
    permissions, with sudo when the file isn't the user's to write, as
    in /usr/local/bin. -f matters: for the minute between the PyPI
    upload and the file reaching the release, the download is a 404,
    and without -f curl would write the error page over a working
    linecast.
    """
    if not sys.stderr.isatty():
        return
    stamp = root / ".checked"
    try:
        if time.time() - stamp.stat().st_mtime < WEEK:
            return
    except OSError:
        pass
    try:
        stamp.touch()
        mine = version("linecast")
    except Exception:
        return
    answer = []
    ask = threading.Thread(target=_ask_pypi, args=(mine, answer), daemon=True)
    ask.start()
    ask.join(BUDGET)
    try:
        newest = answer[0]
        if _release(newest) > _release(mine):
            here = Path(archive).resolve()
            sudo = "" if os.access(here, os.W_OK) else "sudo "
            print(f"linecast: {newest} is out, and this is {mine}. To update:\n"
                  f"  {sudo}curl -fLo {shlex.quote(str(here))} {LATEST}", file=sys.stderr)
    except Exception:
        pass  # no answer in time, or not a version we can compare


if __name__ == "__main__":
    check_python()
    build = Path(site_packages).parent  # noqa: F821 -- shiv sets it
    tidy(build)
    remind(build.parent, archive)  # noqa: F821 -- shiv sets it
