#!/usr/bin/env bash
# Refresh linecast's README screenshots with Andrew's offscreen termshot tool.
#
# Usage:
#   scripts/capture_screenshots.sh all
#   scripts/capture_screenshots.sh weather moon maps hero
#
# The individual targets are weather, sunshine, moon, tides, radar, maps, and
# hero. "all" captures every app and the hero; the hero is its own live
# capture — four apps tiled on one offscreen desktop — so it depends on no
# other target. The app captures use live terminal mode so the header, footer,
# hidden cursor, and full-screen layout match what users actually see.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
SHOT_DIR="$REPO_DIR/screenshots"
CAPTURE_TOOL=${LINECAST_CAPTURE_TOOL:-termshot}

WEATHER_PLACE=${LINECAST_CAPTURE_WEATHER_PLACE:-Dublin, Ireland}
RADAR_PLACE=${LINECAST_CAPTURE_RADAR_PLACE:-Glasgow, Scotland}
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
  hero       hero.png — the four apps tiled live on one offscreen desktop

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
    require ffmpeg
    printf 'Capturing radar still…\n'
    # A harmless Return makes termshot park the pointer outside the offscreen
    # window. With no window padding, the temporary focus border is excluded
    # from the capture as well.
    "$CAPTURE_TOOL" -s 120x36 -w 15 --pad 0 \
        --press Return -o "$SHOT_DIR/radar.png" \
        uv --directory "$REPO_DIR" run radar --location "$RADAR_PLACE"

    printf 'Capturing radar animation…\n'
    # Slow playback in the capture-only wrapper, oversample the terminal so
    # none of LibreWXR's 18 weather frames is skipped, collapse repeated screen
    # states, then encode one complete loop at the app's observed cadence.
    local radar_tmp_dir frame previous diff selected picked=0
    radar_tmp_dir=$(mktemp -d /tmp/linecast-radar-gif.XXXXXX)
    "$CAPTURE_TOOL" -s 120x36 -w 15 --pad 0 \
        --press Return \
        --gif 2 --fps 30 --gif-width 800 -o "$radar_tmp_dir/raw.gif" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_radar.py" --location "$RADAR_PLACE"

    magick "$radar_tmp_dir/raw.gif" -coalesce \
        "$radar_tmp_dir/raw-%03d.png"
    previous=""
    for frame in "$radar_tmp_dir"/raw-*.png; do
        if [ -n "$previous" ]; then
            diff=$(magick compare -metric AE "$previous" "$frame" null: \
                2>&1 || true)
            [ "${diff%% *}" = "0" ] && continue
        fi
        printf -v selected '%s/selected-%03d.png' "$radar_tmp_dir" "$picked"
        cp -- "$frame" "$selected"
        previous=$frame
        picked=$((picked + 1))
        [ "$picked" -eq 18 ] && break
    done
    if [ "$picked" -ne 18 ]; then
        printf 'capture_screenshots: radar recorded only %s/18 frames\n' \
            "$picked" >&2
        rm -rf -- "$radar_tmp_dir"
        return 1
    fi
    ffmpeg -y -loglevel error -framerate 2 \
        -i "$radar_tmp_dir/selected-%03d.png" \
        -vf "format=rgb24,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3" \
        -loop 0 "$SHOT_DIR/radar.gif"
    rm -rf -- "$radar_tmp_dir"
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
    printf 'Capturing hero…\n'
    # One real screenshot: four linecast apps tiled by Hyprland on the
    # offscreen monitor, composed by the compositor's own gaps and borders.
    # Pane order maps to dwindle's slots: big top-left, full-height right
    # column, then the two bottom-left quarters.
    "$CAPTURE_TOOL" --res 3840x2400 --font 'iA Writer Mono S:size=9' \
        -w 90 -o "$SHOT_DIR/hero.png" \
        --pane "uv --directory $REPO_DIR run weather --location '$WEATHER_PLACE'" \
        --pane "uv --directory $REPO_DIR run radar --location '$RADAR_PLACE'" \
        --pane "uv --directory $REPO_DIR run maps --location '$STREET_PLACE' --zoom 0.015" \
        --pane "uv --directory $REPO_DIR run python $REPO_DIR/scripts/capture_moment.py --at 2026-06-21T13:30 --location '$ASTRO_LOCATION' sunshine"
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
