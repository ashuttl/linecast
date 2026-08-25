#!/bin/sh
# linecast — weather, tides, the sun, the moon, and maps for the terminal
# https://github.com/ashuttl/linecast
#
# Quick start:  curl -sL URL | sh
# With args:    curl -sL URL | sh -s -- --metric
# Other tools:  curl -sL URL | sh -s sunshine
#
# The script runs linecast with whatever the machine already has, trying
# in order:
#
#   1. an installed linecast on PATH
#   2. uvx (from uv), which runs the latest release without installing it
#   3. pipx, the same way
#   4. plain python3: a small venv of our own, kept between runs
#
# The venv lives at <cache>/venv, where <cache> is the directory linecast
# itself caches in: $LINECAST_CACHE_DIR if set, else $XDG_CACHE_HOME/linecast,
# else ~/Library/Caches/linecast on macOS, else ~/.cache/linecast.  It is
# private to you (mode 0700) and is checked before anything in it runs: a
# real directory, not a symlink, owned by you and writable, with a python
# that can import linecast and the command you asked for.  A venv that
# fails the check is rebuilt, and once a day the script asks pip for a
# newer release.  Deleting the venv with rm -rf is always safe; the next
# run makes a new one.  When there is no cache directory to use, the venv
# is a throwaway under $TMPDIR, removed on exit.  Python runs isolated
# (-I) throughout, so files in the directory you run from cannot stand in
# for venv, pip or linecast.
#
# One thing a shell script cannot make safe: a cache directory under a
# parent that is world-writable without the sticky bit, where another user
# can swap the directory between the checks here and the moment python
# runs from it.  Keep the cache under your home directory.
#
# Everything below is a function, and the last line calls main, so a
# download cut short by the network runs nothing.

set -e

note() { printf 'linecast: %s\n' "$*" >&2; }
die() { note "$@"; exit 1; }

# Run a linecast command, reclaiming the terminal for interactive input
# when stdin is a pipe (e.g. curl | sh). /dev/tty is the controlling
# terminal regardless of shell redirections — this lets live mode work.
# The node can exist without being openable (no controlling terminal),
# so test by opening it, not with -c.
run() {
    if [ -t 0 ]; then
        "$@"
    elif ( : < /dev/tty ) 2>/dev/null; then
        "$@" < /dev/tty
    else
        "$@" --print
    fi
}

# The directory linecast caches in, with the same precedence as the
# package itself.  A relative XDG_CACHE_HOME is invalid and ignored, per
# the XDG spec.  On macOS the older ~/.cache/linecast stays in use when it
# exists and the native location does not.  Fails when there is no home.
cache_dir() {
    if [ -n "${LINECAST_CACHE_DIR:-}" ]; then
        printf '%s\n' "$LINECAST_CACHE_DIR"
        return
    fi
    case "${XDG_CACHE_HOME:-}" in
        /*) printf '%s/linecast\n' "$XDG_CACHE_HOME"; return ;;
    esac
    [ -n "${HOME:-}" ] || return 1
    legacy=$HOME/.cache/linecast
    if [ "$(uname -s 2>/dev/null)" = Darwin ]; then
        native=$HOME/Library/Caches/linecast
        if [ ! -d "$native" ] && [ -d "$legacy" ]; then
            printf '%s\n' "$legacy"
        else
            printf '%s\n' "$native"
        fi
    else
        printf '%s\n' "$legacy"
    fi
}

# A directory we may run code from: a real directory, not a symlink, owned
# by us.  (-O is not in POSIX, but bash 3.2, dash and busybox ash all have
# it.)  present() also sees a dangling symlink, which -e alone misses.
# shellcheck disable=SC3067
ours() { [ -d "$1" ] && [ ! -L "$1" ] && [ -O "$1" ]; }
present() { [ -e "$1" ] || [ -L "$1" ]; }

# The venv's python exists, can import linecast, and the command we are
# about to run is there.  -x alone stays true for a venv whose python was
# uninstalled from under it, and the import fails on a half-made venv
# (Debian without python3-venv) or a broken upgrade.  A pip install cut
# off between copying the package and writing its scripts leaves a venv
# that imports but has no bin/<cmd>.  Only called once the directory is
# known to be ours.
usable() {
    [ -x "$python" ] && [ -x "$venv/bin/$cmd" ] \
        && "$python" -I -c 'import linecast' 2>/dev/null
}

# The refresh stamp is under a day old.  A missing stamp raises, which
# counts as old.  Asked of python because BSD find -mtime rounds up.
fresh() {
    "$python" -I -c 'import os, sys, time
sys.exit(time.time() - os.stat(sys.argv[1]).st_mtime >= 86400)' "$stamp" 2>/dev/null
}

vpip() { "$python" -I -m pip -q --disable-pip-version-check "$@"; }

# Make the venv from scratch and install linecast into it.  Every failure
# exits, so callers need not check.
build() {
    note "installing linecast..."
    if ! ( umask 077 && python3 -I -m venv --clear "$venv" ); then
        rm -rf "$venv"
        die "python3 -m venv failed. On Debian/Ubuntu: sudo apt install python3-venv, then run this again."
    fi
    if ! "$python" -I -m pip --version >/dev/null 2>&1; then
        "$python" -I -m ensurepip --upgrade --default-pip >/dev/null 2>&1 \
            || die "the venv has no pip and ensurepip is unavailable"
    fi
    vpip install linecast || die "could not install linecast"
    touch "$stamp"
}

main() {
    cmd="${1:-weather}"
    if [ "$#" -gt 0 ]; then shift; fi   # a bare shift is fatal in dash

    case "$cmd" in
        weather|sunshine|moon|tides|radar|maps|linecast) ;;
        -*) set -- "$cmd" "$@"; cmd=weather ;;  # bare flags like --metric
        *) die "unknown command: $cmd (try weather, sunshine, moon, tides, radar, or maps)" ;;
    esac

    # Already installed?
    if command -v linecast >/dev/null 2>&1; then
        if [ "$cmd" = linecast ]; then run linecast "$@"; else run linecast "$cmd" "$@"; fi
        return
    fi

    # uvx (from uv) — ephemeral run, no install needed
    if command -v uvx >/dev/null 2>&1; then
        run uvx --quiet linecast "$cmd" "$@"
        return
    fi

    # pipx — ephemeral run, no install needed
    if command -v pipx >/dev/null 2>&1; then
        run pipx run linecast "$cmd" "$@"
        return
    fi

    # Fallback: a venv of our own (works on bare macOS with just python3).
    # Without the developer tools, macOS has a python3 that command -v
    # finds but that cannot run.
    command -v python3 >/dev/null 2>&1 \
        || die "Python 3 required — install from python.org or: brew install python"
    python3 -I -c '' \
        || die "python3 is not usable (on macOS run: xcode-select --install)"

    venv=
    if dir=$(cache_dir) && ( umask 077 && mkdir -p "$dir" ) 2>/dev/null; then
        if ! ours "$dir" || ! [ -w "$dir" ]; then
            note "refusing $dir: not a writable directory owned by you"
        elif present "$dir/venv" && ! ours "$dir/venv"; then
            note "refusing $dir/venv: not a directory owned by you"
        else
            venv=$dir/venv
        fi
    fi
    if [ -z "$venv" ]; then
        # Nowhere to keep it: a private one-off directory, gone when we exit.
        venv=$(mktemp -d "${TMPDIR:-/tmp}/linecast.XXXXXX")
        trap 'rm -rf "$venv"' EXIT
        trap 'exit 1' HUP TERM
        note "using a throwaway venv in $venv"
    fi
    python=$venv/bin/python
    stamp=$venv/.refreshed

    if ! usable; then
        build
    elif ! fresh; then
        # Pick up a newer release.  When the index is unreachable pip keeps
        # what is installed and exits 0; any other failure is worth a line
        # but not an exit.  An upgrade that broke the venv is rebuilt now.
        vpip install --upgrade --retries 1 --timeout 10 linecast >/dev/null 2>&1 \
            || note "could not check for a newer release; running the installed one"
        touch "$stamp"
        usable || build
    fi

    export LINECAST_TEMP=1
    run "$venv/bin/$cmd" "$@"
}

main "$@"
