#!/bin/sh
set -e

# linecast — terminal weather, solar arc, and tide visualizations
# https://github.com/ashuttl/linecast
#
# Quick start:  curl -sL URL | sh
# With args:    curl -sL URL | sh -s -- --metric
# Other tools:  curl -sL URL | sh -s sunshine

cmd="${1:-weather}"
shift 2>/dev/null || true

case "$cmd" in
    weather|sunshine|tides|linecast) ;;
    -*) set -- "$cmd" "$@"; cmd=weather ;;  # bare flags like --metric
    *) echo "Unknown command: $cmd (try weather, sunshine, or tides)"; exit 1 ;;
esac

# Already installed?
if command -v linecast >/dev/null 2>&1; then
    if [ "$cmd" = linecast ]; then linecast "$@"; else linecast "$cmd" "$@"; fi
    exit
fi

# uvx (from uv) — ephemeral run, no install needed
if command -v uvx >/dev/null 2>&1; then
    uvx --quiet linecast "$cmd" "$@"
    exit
fi

# pipx — ephemeral run, no install needed
if command -v pipx >/dev/null 2>&1; then
    pipx run linecast "$cmd" "$@"
    exit
fi

# Fallback: bootstrap a temp venv (works on bare macOS with just python3)
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 required — install from python.org or: brew install python"
    exit 1
fi

ENV=/tmp/linecast
if [ ! -x "$ENV/bin/weather" ]; then
    printf 'Installing linecast...\n'
    python3 -m venv "$ENV"
    "$ENV/bin/pip" install -q linecast
fi

"$ENV/bin/$cmd" "$@"

# After live mode exits (or after --print output), show next steps
printf '\n'
printf '  Also try: %s/bin/sunshine, %s/bin/tides\n' "$ENV" "$ENV"
printf '\n'
printf '  Install permanently:\n'
printf '    pip install linecast\n'
printf '    brew tap ashuttl/linecast && brew install linecast\n'
