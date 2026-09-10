"""Give the six commands their short names, as links to the linecast binary.

Usage: linecast link [--dir DIR]
       linecast link --remove [--dir DIR]

2.0 installs only `linecast`; `weather`, `sunshine`, `moon`, `tides`,
`radar` and `maps` are common words that other programs also claim.
The binary runs as the command it is invoked by, so a link named
`moon` beside it is the moon command.  This makes those links, next
to the binary unless --dir says otherwise, and never touches a file
that is not already a link to linecast.
"""

import argparse
import filecmp
import os
import sys

from linecast import _runtime
from linecast._runtime import VersionAction

SHORT_NAMES = ("weather", "sunshine", "moon", "sky", "tides", "radar", "maps")


def _binary():
    """The linecast binary as the user runs it, or None under python -m."""
    path = os.path.abspath(_runtime.INVOKED_AS or sys.argv[0] or "")
    name = os.path.splitext(os.path.basename(path))[0].lower()
    return path if name == "linecast" and os.path.isfile(path) else None


def _is_ours(path, binary):
    """True when *path* is a link to the binary, or a copy of it."""
    if os.path.islink(path):
        try:
            return os.path.samefile(os.path.realpath(path), os.path.realpath(binary))
        except OSError:
            return False
    try:
        return filecmp.cmp(path, binary, shallow=False)
    except OSError:
        return False


def _make(target, binary):
    """Link, or copy where links are not allowed (Windows without the
    privilege); the console-script launcher works as a copy."""
    try:
        os.symlink(binary, target)
        return "linked"
    except (OSError, NotImplementedError):
        import shutil
        shutil.copy2(binary, target)
        return "copied"


def _link(directory, binary):
    made, kept, refused = [], [], []
    ext = os.path.splitext(binary)[1] if sys.platform == "win32" else ""
    for name in SHORT_NAMES:
        target = os.path.join(directory, name + ext)
        if os.path.lexists(target):
            if _is_ours(target, binary):
                kept.append(name)
            else:
                refused.append(name)
            continue
        made.append((name, _make(target, binary)))
    if made:
        print(f"in {directory}:")
    for name, how in made:
        print(f"  {name}: {how} to linecast")
    if kept:
        print(f"already linked: {', '.join(kept)}")
    for name in refused:
        print(f"{name}: something else is installed here, left alone "
              f"(alias {name}='linecast {name}' instead)")
    if made and directory not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"{directory} is not on your PATH.")
    return 1 if refused else 0


def _remove(directory, binary):
    removed, refused = [], []
    ext = os.path.splitext(binary)[1] if sys.platform == "win32" else ""
    for name in SHORT_NAMES:
        target = os.path.join(directory, name + ext)
        if not os.path.lexists(target):
            continue
        if _is_ours(target, binary):
            os.remove(target)
            removed.append(name)
        else:
            refused.append(name)
    print(f"removed: {', '.join(removed)}" if removed else "nothing to remove")
    for name in refused:
        print(f"{name}: not a link to linecast, left alone")
    return 1 if refused else 0


def link_parser():
    """The parser, shared with generated shell completions."""
    parser = argparse.ArgumentParser(
        prog="linecast link",
        description="Make (or remove) the short commands as links to linecast",
    )
    parser.add_argument("--version", action=VersionAction)
    parser.add_argument("--dir", default=None,
                        help="where to put the links (default: beside linecast)")
    parser.add_argument("--remove", action="store_true",
                        help="remove the links this command made")
    return parser


def main():
    args = link_parser().parse_args()

    binary = _binary()
    if binary is None:
        print("linecast link needs the installed linecast binary; run it as "
              "`linecast link`, not through python -m.", file=sys.stderr)
        sys.exit(1)
    directory = os.path.abspath(args.dir) if args.dir else os.path.dirname(binary)
    if not os.path.isdir(directory):
        print(f"{directory} is not a directory.", file=sys.stderr)
        sys.exit(1)
    sys.exit(_remove(directory, binary) if args.remove else _link(directory, binary))


if __name__ == "__main__":
    main()
