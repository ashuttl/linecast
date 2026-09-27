#!/bin/sh
# Build linecast.pyz, the single-file linecast on each GitHub release,
# from a built wheel.
#
# Usage:
#   scripts/build_pyz.sh <dist-dir> <out-dir>
#
# Needs shiv on PATH (pip install shiv). The pyz is a zip of linecast
# with shiv's bootstrap in front, run by whatever python3 is on PATH.
# linecast needs nothing but Python outside Windows, so one file serves
# every platform; tzdata and truststore, which the wheel asks for only
# on Windows, go in as well, because pip leaves them out on the Linux
# machine that builds it.
#
# The first run of each build unpacks it under ~/.cache/linecast-pyz,
# beside linecast's own cache rather than in it: on macOS, a
# ~/.cache/linecast made first would become the cache in place of
# ~/Library/Caches/linecast. scripts/pyz_preamble.py runs before
# linecast every time.

set -eu

dist=$1
out=$2

set -- "$dist"/linecast-*.whl
if [ "$#" -ne 1 ] || ! [ -f "$1" ]; then
    echo "build_pyz: expected one linecast wheel in $dist" >&2
    exit 1
fi

mkdir -p "$out"
# The tilde is for shiv to expand on the machine that runs the pyz.
# shellcheck disable=SC2088
shiv --console-script linecast \
    --python "/usr/bin/env python3" \
    --root "~/.cache/linecast-pyz" \
    --preamble "$(dirname "$0")/pyz_preamble.py" \
    --output-file "$out/linecast.pyz" \
    "$1" tzdata truststore
