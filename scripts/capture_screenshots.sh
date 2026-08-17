#!/usr/bin/env bash
# Refresh linecast's README screenshots with Andrew's offscreen termshot tool.
#
# Usage:
#   scripts/capture_screenshots.sh all
#   scripts/capture_screenshots.sh weather moon maps hero
#
# The individual targets are weather, sunshine, moon, tides, radar, maps, and
# hero. "all" captures every app before rebuilding the hero. The app captures
# use live terminal mode so the header, footer, hidden cursor, and full-screen
# layout match what users actually see.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
SHOT_DIR="$REPO_DIR/screenshots"
CAPTURE_TOOL=${LINECAST_CAPTURE_TOOL:-termshot}

WEATHER_PLACE=${LINECAST_CAPTURE_WEATHER_PLACE:-Portland, Maine}
RADAR_PLACE=${LINECAST_CAPTURE_RADAR_PLACE:-Manila, Philippines}
STREET_PLACE=${LINECAST_CAPTURE_STREET_PLACE:-Portland, Maine}
TERRAIN_PLACE=${LINECAST_CAPTURE_TERRAIN_PLACE:-Innsbruck}
TIDE_STATION=${LINECAST_CAPTURE_TIDE_STATION:-8418150}
ASTRO_LOCATION=${LINECAST_CAPTURE_ASTRO_LOCATION:-43.676,-70.371}

usage() {
    cat <<'EOF'
Usage: scripts/capture_screenshots.sh [TARGET...]

Targets:
  all        capture every app, then compose the hero (default)
  weather    weather.png
  sunshine   sunshine-day.png and sunshine-dusk.png
  moon       moon.png
  tides      tides.png
  radar      radar.png and radar.gif
  maps       maps-street.png and maps-terrain.png
  hero       compose hero.png from existing captures

Environment overrides:
  LINECAST_CAPTURE_TOOL
  LINECAST_CAPTURE_WEATHER_PLACE
  LINECAST_CAPTURE_RADAR_PLACE
  LINECAST_CAPTURE_STREET_PLACE
  LINECAST_CAPTURE_TERRAIN_PLACE
  LINECAST_CAPTURE_TIDE_STATION
  LINECAST_CAPTURE_ASTRO_LOCATION
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

cd "$REPO_DIR"
mkdir -p "$SHOT_DIR"

exec 9>/tmp/linecast-capture-screenshots.lock
if ! flock -n 9; then
    printf 'capture_screenshots: another capture run is already active\n' >&2
    exit 1
fi

require() {
    command -v "$1" >/dev/null 2>&1 || {
        printf 'capture_screenshots: missing required command: %s\n' "$1" >&2
        exit 1
    }
}

require "$CAPTURE_TOOL"
require magick
require uv

weather() {
    printf 'Capturing weather…\n'
    "$CAPTURE_TOOL" -s 150x44 -w 10 -o "$SHOT_DIR/weather.png" \
        uv --directory "$REPO_DIR" run weather --location "$WEATHER_PLACE"
}

sunshine() {
    printf 'Capturing sunshine at midday…\n'
    "$CAPTURE_TOOL" -s 120x36 -w 4 -o "$SHOT_DIR/sunshine-day.png" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-06-21T13:30 --location "$ASTRO_LOCATION" sunshine

    printf 'Capturing sunshine at dusk…\n'
    "$CAPTURE_TOOL" -s 120x36 -w 4 -o "$SHOT_DIR/sunshine-dusk.png" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-06-21T20:15 --location "$ASTRO_LOCATION" sunshine
}

moon() {
    printf 'Capturing Moon…\n'
    "$CAPTURE_TOOL" -s 120x40 -w 4 -o "$SHOT_DIR/moon.png" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-08-22T21:30 --location "$ASTRO_LOCATION" moon
}

tides() {
    printf 'Capturing tides…\n'
    "$CAPTURE_TOOL" -s 120x36 -w 12 -o "$SHOT_DIR/tides.png" \
        uv --directory "$REPO_DIR" run tides --station "$TIDE_STATION"
}

radar() {
    printf 'Capturing radar still…\n'
    "$CAPTURE_TOOL" -s 120x36 -w 15 -o "$SHOT_DIR/radar.png" \
        uv --directory "$REPO_DIR" run radar --location "$RADAR_PLACE" \
        --layers temp,wind

    printf 'Capturing radar animation…\n'
    "$CAPTURE_TOOL" -s 120x36 -w 15 --gif 4 --fps 6 --gif-width 800 \
        -o "$SHOT_DIR/radar.gif" \
        uv --directory "$REPO_DIR" run radar --location "$RADAR_PLACE"
}

maps() {
    printf 'Capturing street map…\n'
    "$CAPTURE_TOOL" -s 120x38 -w 15 -o "$SHOT_DIR/maps-street.png" \
        uv --directory "$REPO_DIR" run maps --location "$STREET_PLACE" \
        --zoom 0.015

    printf 'Capturing terrain map…\n'
    "$CAPTURE_TOOL" -s 120x38 -w 15 -o "$SHOT_DIR/maps-terrain.png" \
        uv --directory "$REPO_DIR" run maps --view terrain \
        --location "$TERRAIN_PLACE" --zoom 1.5
}

hero() {
    printf 'Composing hero…\n'
    local shot_tmp_dir tile_w=1400 tile_h=900 gap=14 bg='#0b0d14'
    shot_tmp_dir=$(mktemp -d /tmp/linecast-screenshots.XXXXXX)

    magick \
        \( "$SHOT_DIR/weather.png" -resize "${tile_w}x${tile_h}" \
           -background "$bg" -gravity center -extent "${tile_w}x${tile_h}" \) \
        \( "$SHOT_DIR/sunshine-day.png" -resize "${tile_w}x${tile_h}" \
           -background "$bg" -gravity center -extent "${tile_w}x${tile_h}" \) \
        +append "$shot_tmp_dir/top.png"
    magick \
        \( "$SHOT_DIR/radar.png" -resize "${tile_w}x${tile_h}" \
           -background "$bg" -gravity center -extent "${tile_w}x${tile_h}" \) \
        \( "$SHOT_DIR/maps-street.png" -resize "${tile_w}x${tile_h}" \
           -background "$bg" -gravity center -extent "${tile_w}x${tile_h}" \) \
        +append "$shot_tmp_dir/bottom.png"
    magick "$shot_tmp_dir/top.png" "$shot_tmp_dir/bottom.png" \
        -background "$bg" -gravity center -append \
        -bordercolor "$bg" -border "$gap" "$SHOT_DIR/hero.png"
    rm -rf -- "$shot_tmp_dir"
}

run_target() {
    case "$1" in
        weather|sunshine|moon|tides|radar|maps|hero) "$1" ;;
        all)
            weather
            sunshine
            moon
            tides
            radar
            maps
            hero
            ;;
        *)
            printf 'capture_screenshots: unknown target: %s\n' "$1" >&2
            exit 2
            ;;
    esac
}

if [ "$#" -eq 0 ]; then
    set -- all
fi

for target in "$@"; do
    run_target "$target"
done

printf 'Screenshots refreshed in %s\n' "$SHOT_DIR"
