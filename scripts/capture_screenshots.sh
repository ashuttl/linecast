#!/usr/bin/env bash
# Refresh linecast's README screenshots with Andrew's offscreen termshot tool.
#
# Usage:
#   scripts/capture_screenshots.sh all
#   scripts/capture_screenshots.sh weather moon maps hero
#
# The individual targets are weather, sunshine, year, moon, tides, radar,
# maps, and hero. "all" captures every app but NOT the hero: the shipped hero is a
# hand-composed whole-screen screenshot, and the hero target — a live
# auto-capture of four apps tiled on one offscreen desktop — would overwrite
# it, so it only runs when named explicitly. The app captures use live
# terminal mode so the header, footer, hidden cursor, and full-screen layout
# match what users actually see.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
SHOT_DIR="$REPO_DIR/screenshots"
CAPTURE_TOOL=${LINECAST_CAPTURE_TOOL:-termshot}

WEATHER_PLACE=${LINECAST_CAPTURE_WEATHER_PLACE:-Dublin, Ireland}
RADAR_PLACE=${LINECAST_CAPTURE_RADAR_PLACE:-Glasgow, Scotland}
STREET_PLACE=${LINECAST_CAPTURE_STREET_PLACE:-Portland, Maine}
TERRAIN_PLACE=${LINECAST_CAPTURE_TERRAIN_PLACE:-Innsbruck}
GLOBE_PLACE=${LINECAST_CAPTURE_GLOBE_PLACE:-20,-30}
TIDE_STATION=${LINECAST_CAPTURE_TIDE_STATION:-8418150}
ASTRO_LOCATION=${LINECAST_CAPTURE_ASTRO_LOCATION:-43.676,-70.371}
ARCTIC_PLACE=${LINECAST_CAPTURE_ARCTIC_PLACE:-Longyearbyen}
ANTARCTIC_PLACE=${LINECAST_CAPTURE_ANTARCTIC_PLACE:-Vostok Station}
OKINAWA_LOCATION=${LINECAST_CAPTURE_OKINAWA_LOCATION:-26.2124,127.6809}

usage() {
    cat <<'EOF'
Usage: scripts/capture_screenshots.sh [TARGET...]

Targets:
  all        capture every app (default; leaves the hand-made hero alone)
  weather    weather.png
  sunshine   sunshine-day.png and sunshine-dusk.png
  year       sunshine-year.png, plus -arctic and -antarctic at 78° either side
  moon       moon.png, plus moon-okinawa.png in Japanese and moon-calendar.png
  tides      tides.png
  radar      radar.png and radar.gif
  maps       maps-street.png and maps-terrain.png
  globe      maps-globe.png — the planet with the live sky (differs every run)
  hero       hero.png — the four apps tiled live on one offscreen desktop

Environment overrides:
  LINECAST_CAPTURE_TOOL
  LINECAST_CAPTURE_WEATHER_PLACE
  LINECAST_CAPTURE_RADAR_PLACE
  LINECAST_CAPTURE_STREET_PLACE
  LINECAST_CAPTURE_TERRAIN_PLACE
  LINECAST_CAPTURE_GLOBE_PLACE
  LINECAST_CAPTURE_TIDE_STATION
  LINECAST_CAPTURE_ASTRO_LOCATION
  LINECAST_CAPTURE_ARCTIC_PLACE
  LINECAST_CAPTURE_ANTARCTIC_PLACE
  LINECAST_CAPTURE_OKINAWA_LOCATION
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

year() {
    # The year view at the home location and at two places near the poles,
    # each with the pointer on the December solstice so the hover tooltip is
    # in frame. On a 120x36 terminal that is column 115, row 18 (noon). The
    # first hover only carries the pointer onto the window: a single warp
    # from outside arrives as a pointer enter, not the motion the app
    # listens for, so the second, real move is what raises the tooltip.
    #
    # "Today" is the June solstice, as in the day captures. capture_moment
    # reads --at in this machine's zone, so the later two are 13:30 local
    # time in Svalbard and at Vostok as seen from US Eastern; if that drifts
    # only the sun glyph's row moves.
    local place at name spec
    for spec in "$ASTRO_LOCATION|2026-06-21T13:30|sunshine-year.png" \
                "$ARCTIC_PLACE|2026-06-21T07:30|sunshine-year-arctic.png" \
                "$ANTARCTIC_PLACE|2026-06-21T04:30|sunshine-year-antarctic.png"; do
        IFS='|' read -r place at name <<<"$spec"
        printf 'Capturing sunshine year view for %s…\n' "$place"
        "$CAPTURE_TOOL" -s 120x36 -w 6 \
            --hover 100x12 --sleep 0.5 --hover 115x18 --sleep 1 \
            -o "$SHOT_DIR/$name" \
            uv --directory "$REPO_DIR" run python \
            "$REPO_DIR/scripts/capture_moment.py" \
            --at "$at" --location "$ASTRO_LOCATION" sunshine -- \
            --year --location "$place"
    done
}

moon() {
    printf 'Capturing Moon…\n'
    "$CAPTURE_TOOL" -s 120x40 -w 4 -o "$SHOT_DIR/moon.png" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-08-22T21:30 --location "$ASTRO_LOCATION" moon
    # Okinawa in Japanese, the evening after the mid-autumn full moon of
    # 2026, so the headline names the night 十六夜 and the calendar's
    # September carries 十五夜 on the 25th. capture_moment's --at lands as
    # the place's local time here. The calendar frame presses v and hovers
    # the 25th (column 84, row 27 on 120x40; the first hover only carries
    # the pointer onto the window, the second raises the chip). --focus
    # gives the disc frame the same accent border the key presses give
    # the calendar.
    "$CAPTURE_TOOL" -s 120x40 -w 6 --focus -o "$SHOT_DIR/moon-okinawa.png" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-09-26T21:30 --location "$OKINAWA_LOCATION" moon -- \
        --lang ja --24h
    "$CAPTURE_TOOL" -s 120x40 -w 6 --press v --sleep 2 \
        --hover 84x27 --sleep 1 --hover 85x27 --sleep 2 \
        -o "$SHOT_DIR/moon-calendar.png" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-09-26T21:30 --location "$OKINAWA_LOCATION" moon -- \
        --lang ja --24h
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

globe() {
    printf 'Capturing globe…\n'
    # The frame is this hour's terminator and city lights — honestly
    # different every run — but *not* this hour's clouds: daylight alone
    # reads instantly, where the cloud layer makes a first-glance reader
    # work out what they are looking at.  So the capture opens the plain
    # terrain planet and presses s once the canvas is warm.  The default
    # centre sits on the mid-Atlantic where the terminator usually
    # crosses the disk.
    "$CAPTURE_TOOL" -s 120x38 -w 25 --press s --sleep 2 \
        -o "$SHOT_DIR/maps-globe.png" \
        uv --directory "$REPO_DIR" run maps --view terrain --zoom 130 \
        --location "$GLOBE_PLACE"
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
        weather|sunshine|year|moon|tides|radar|maps|globe|hero) "$1" ;;
        all)
            weather
            sunshine
            year
            moon
            tides
            radar
            maps
            globe
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
