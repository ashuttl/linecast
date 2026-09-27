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
import shlex
import shutil
import sys
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

LATEST = "https://github.com/ashuttl/linecast/releases/latest/download/linecast.pyz"
PYPI = "https://pypi.org/pypi/linecast/json"
WEEK = 7 * 24 * 3600


def check_python(version_info=sys.version_info):
    """Exit with a plain line on a Python linecast can't run on, where
    pip would have refused to install it."""
    if tuple(version_info[:2]) < (3, 10):
        sys.exit(f"linecast needs Python 3.10 or newer, and this is Python "
                 f"{version_info[0]}.{version_info[1]} ({sys.executable}).")


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


def remind(root, archive):
    """Once a week, when someone is there to read it, ask PyPI for the
    newest release and say so if it is newer than this one.

    A run whose output nobody sees, such as a status bar's, neither
    asks nor starts the week. The stamp is touched before asking, so a
    request that fails waits a week like any other.

    The command overwrites the file that was run, which keeps its
    permissions. -f matters: for the minute between the PyPI upload and
    the file reaching the release, the download is a 404, and without
    -f curl would write the error page over a working linecast.
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
        request = urllib.request.Request(
            PYPI, headers={"User-Agent": f"linecast/{mine} (pyz)"})
        with urllib.request.urlopen(request, timeout=2) as response:
            newest = json.load(response)["info"]["version"]
        if _release(newest) > _release(mine):
            here = shlex.quote(str(Path(archive).resolve()))
            print(f"linecast: {newest} is out, and this is {mine}. To update:\n"
                  f"  curl -fLo {here} {LATEST}", file=sys.stderr)
    except Exception:
        pass  # offline, or PyPI answered oddly: say nothing


if __name__ == "__main__":
    check_python()
    build = Path(site_packages).parent  # noqa: F821 -- shiv sets it
    tidy(build)
    remind(build.parent, archive)  # noqa: F821 -- shiv sets it
