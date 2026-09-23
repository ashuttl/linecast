"""python -m linecast / linecast CLI entry point."""

import errno
import os
import sys
from linecast._commands import help_text
from linecast._completion import available_shells, completion_help, render_completion


def sky_now():
    """The Moon tonight, in one line, for the foot of the help page.

    The help page is where linecast introduces itself, and this is the
    one thing it can say about the sky without a place or a network:
    the phase is arithmetic on the clock. Nothing here is worth failing
    the help page over, so any trouble returns an empty string.
    """
    try:
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from linecast._runtime import resolve_icons
        from linecast._ephemeris import moon_illuminated_fraction
        from linecast.sunshine.view import moon_phase
        now = datetime.now(timezone.utc)
        icons, _source = resolve_icons()
        _idx, name, icon = moon_phase(now, SimpleNamespace(icons=icons))
        return f"{icon} {name}, {moon_illuminated_fraction(now) * 100:.0f}% lit"
    except Exception:
        return ""


COMMANDS = {
    "weather": "linecast.weather.view",
    "sunshine": "linecast.sunshine.view",
    "moon": "linecast.moon.view",
    "sky": "linecast.sky.view",
    "tides": "linecast.tides",
    "radar": "linecast.radar.view",
    "maps": "linecast.maps.view",
    "location": "linecast.location",
    "language": "linecast.language",
    "units": "linecast.units",
    "clock": "linecast.clock",
    "week": "linecast.week",
    "icons": "linecast.icons",
    # calendar_cmd, not calendar: running any file in this package as a
    # script (python src/linecast/moon.py) puts the package directory
    # first on sys.path, where a calendar.py would shadow the standard
    # library module the rest of the code imports.
    "calendar": "linecast.calendar_cmd",
    "culture": "linecast.culture_cmd",
    "hours": "linecast.hours",
    "link": "linecast.link",
    "doctor": "linecast.doctor",
}

# Commands for working on linecast itself: they dispatch, but the help
# page and the completions do not mention them.
HIDDEN = {
    "prose": "linecast.prose",
}

# The commands that answer to their own name as argv[0], for users and
# distro packages that link or copy the binary under a short name. Only
# these dispatch: the utility commands (location, units, doctor) have no
# standalone spelling to honour.
STANDALONE = ("weather", "sunshine", "moon", "sky", "tides", "radar", "maps")


def _run(cmd, args):
    # Shift argv so the subcommand sees itself as argv[0], keeping the
    # original where `linecast link` can find the binary.
    from linecast import _runtime
    _runtime.INVOKED_AS = sys.argv[0]
    sys.argv = [f"linecast {cmd}"] + list(args)
    import importlib
    mod = importlib.import_module(COMMANDS.get(cmd) or HIDDEN[cmd])
    mod.main()


def main():
    # A reader that closes early -- `linecast weather --print | head` --
    # ends a run with EPIPE on stdout.  That is the reader's choice, not
    # a failure: swallow it, and give the interpreter something other
    # than the broken pipe to flush at exit, or it reports the same
    # error once more on the way out.  Output shorter than the buffer
    # reaches the pipe only at that flush, so flush here, where the
    # error can still be caught.
    try:
        try:
            _main()
        finally:
            sys.stdout.flush()
    except OSError as exc:
        if not _reader_gone(exc):
            raise
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        sys.exit(0)


def _reader_gone(exc):
    """Whether an error writing stdout says the reader has closed it.

    POSIX reports it as EPIPE.  Windows has no reader to signal: its C
    runtime turns the pipe's ERROR_NO_DATA into EINVAL, so on Windows
    an EINVAL from stdout is taken the same way.
    """
    if isinstance(exc, BrokenPipeError):
        return True
    return sys.platform == "win32" and exc.errno == errno.EINVAL


def _main():
    # A binary named for a command is that command: a symlink or copy
    # of the linecast binary called `weather` runs the weather command,
    # arguments untouched.  Distro packages ship the short commands as
    # symlinks to this binary, so a name some other package owns can be
    # left out without losing the command.  lower() and splitext cover
    # Windows, where the copy is weather.exe.
    prog = os.path.splitext(os.path.basename(sys.argv[0] or ""))[0].lower()
    if prog in STANDALONE:
        _run(prog, sys.argv[1:])
        return

    args = sys.argv[1:]

    # The version comes from importlib.metadata, which costs more than
    # the rest of this dispatch put together, so only the branches that
    # print it look it up.
    if not args or args[0] in ("-h", "--help"):
        from linecast import __version__
        print(help_text(__version__))
        sky = sky_now()
        if sky:
            print()
            print(sky)
        sys.exit(0)

    if args[0] in ("-v", "--version"):
        from linecast import __version__
        print(f"linecast {__version__}")
        sys.exit(0)

    if args[0] == "completion":
        completion_args = args[1:]
        if not completion_args or completion_args[0] in ("-h", "--help"):
            print(completion_help())
            sys.exit(0)
        try:
            print(render_completion(completion_args[0]), end="")
        except ValueError:
            print(f"linecast completion: unknown shell '{completion_args[0]}'", file=sys.stderr)
            print(f"Expected one of: {', '.join(available_shells())}", file=sys.stderr)
            sys.exit(2)
        sys.exit(0)

    cmd = args[0]
    if cmd not in COMMANDS and cmd not in HIDDEN:
        print(f"linecast: unknown command '{cmd}'", file=sys.stderr)
        print("Run 'linecast --help' for usage.", file=sys.stderr)
        sys.exit(1)

    _run(cmd, args[1:])


if __name__ == "__main__":
    main()
