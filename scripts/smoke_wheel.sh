#!/bin/sh
# Smoke-test an installed linecast wheel.
#
# Usage:
#   scripts/smoke_wheel.sh [<version>]
#
# Runs against whichever `linecast` is first on PATH, so put the venv
# that holds the wheel there first. Every command must exit 0, print
# something on stdout, and print nothing on stderr; the --version
# outputs must carry the version given (or, with no argument, the
# version the installed package reports). The last check imports
# linecast from that same install and reads each of the four data
# files, which is what catches a wheel that installed but shipped
# without them.
#
# Every command runs with stdin closed and with HOME and the XDG dirs
# pointed at a scratch directory that is removed afterwards, so nothing
# here reads or writes the real home, and the working directory moves
# there too so a source checkout can never stand in for the wheel.

set -u

commands="weather sunshine moon tides radar maps"
data="basemap.json.gz climate.png globe_canvas_1.bin globe_canvas_2.bin"
status=0

fail() {
    echo "smoke_wheel: $*" >&2
    status=1
}

linecast=$(command -v linecast) \
    || { echo "smoke_wheel: linecast is not on PATH" >&2; exit 1; }
bindir=$(dirname "$linecast")
# The probe must import from the install that owns the linecast
# command, so prefer the interpreter beside it.
if [ -x "$bindir/python3" ]; then
    python="$bindir/python3"
else
    python=python3
fi

version=${1:-$("$python" -c \
    "import importlib.metadata as m; print(m.version('linecast'))")} \
    || { echo "smoke_wheel: could not read the installed version" >&2; exit 1; }

scratch=$(mktemp -d) || exit 1
trap 'rm -rf "$scratch"' EXIT INT TERM
export HOME="$scratch/home"
export XDG_CONFIG_HOME="$scratch/config"
export XDG_CACHE_HOME="$scratch/cache"
export XDG_STATE_HOME="$scratch/state"
export XDG_DATA_HOME="$scratch/data"
mkdir -p "$HOME"
cd "$scratch" || exit 1

# run <label> <command...>: exit 0, non-empty stdout, empty stderr.
run() {
    label=$1
    shift
    "$@" </dev/null >"$scratch/out" 2>"$scratch/err" \
        || fail "$label: exit status $?"
    if [ -s "$scratch/err" ]; then
        fail "$label: wrote to stderr: $(head -c 300 "$scratch/err")"
    fi
    if ! [ -s "$scratch/out" ]; then
        fail "$label: printed nothing"
    fi
}

# expect <label> <text>: the last run's stdout carries the text.
expect() {
    if ! grep -qF -- "$2" "$scratch/out"; then
        fail "$1: expected '$2' in: $(head -c 300 "$scratch/out")"
    fi
}

run "linecast --help" linecast --help
run "linecast --version" linecast --version
expect "linecast --version" "$version"

for cmd in $commands; do
    run "$cmd --help" "$cmd" --help
    run "linecast $cmd --help" linecast "$cmd" --help
    run "$cmd --version" "$cmd" --version
    expect "$cmd --version" "$version"
done

for shell in bash zsh fish nushell; do
    run "linecast completion $shell" linecast completion "$shell"
done

run "linecast location" linecast location
run "linecast units" linecast units

# The probe script goes through a file because run() closes stdin.
cat >"$scratch/probe.py" <<'PY'
import importlib.resources as resources
import sys

import linecast

version, names = sys.argv[1], sys.argv[2:]
print("linecast", linecast.__version__, "from", linecast.__file__)
if linecast.__version__ != version:
    sys.exit(f"installed version is {linecast.__version__}, expected {version}")
data = resources.files("linecast") / "data"
for name in names:
    size = len((data / name).read_bytes())
    if size <= 0:
        sys.exit(f"{name} is empty")
    print(f"{name}: {size} bytes")
PY
# shellcheck disable=SC2086  # $data is a word list on purpose
run "data probe" "$python" "$scratch/probe.py" "$version" $data

if [ "$status" -eq 0 ]; then
    echo "smoke_wheel: ok: linecast $version from $bindir"
fi
exit "$status"
