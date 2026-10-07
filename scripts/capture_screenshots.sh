#!/usr/bin/env bash
# Refresh linecast's README screenshots.
#
# Usage:
#   scripts/capture_screenshots.sh all
#   scripts/capture_screenshots.sh weather moon maps hero
#
# The individual targets are listed by --help. "all" captures every app but
# NOT the desktops (hero, languages, themes): those are composed from live
# panes, and a hand-taken whole-screen screenshot may stand in for the hero,
# so they only run when named. The app captures use live terminal mode so
# the header, footer, hidden cursor, and full-screen layout match what users
# actually see.
#
# Each frame is drawn by scripts/offscreen_terminal.py, a terminal with no
# window: the app runs in a pseudo-terminal, and the cells are drawn the way
# foot draws them, in an Omarchy window frame, with an empty config
# directory so nobody's saved settings leak into a frame. Nothing here
# touches the desktop it runs from. LINECAST_CAPTURE_TOOL=termshot
# photographs a real foot on an offscreen Hyprland output instead. Every
# frame is set in LINECAST_CAPTURE_FONT and dressed in
# LINECAST_CAPTURE_THEME, so the gallery keeps one look whatever the
# desktop is wearing.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
SHOT_DIR="$REPO_DIR/screenshots"
GALLERY_DIR="$SHOT_DIR/gallery"
CAPTURE_TOOL=${LINECAST_CAPTURE_TOOL:-$SCRIPT_DIR/offscreen_terminal.py}
OFFSCREEN="$SCRIPT_DIR/capture_offscreen.py"
export LINECAST_CAPTURE_THEME=${LINECAST_CAPTURE_THEME:-tokyo-night}
# GitHub's own Nerd Font build of Monaspace Neon (otf-monaspace-nerdfonts);
# the Nerd Fonts project's "MonaspiceNe" is the same face, but a name
# fontconfig cannot find falls back to a proportional sans and spaces every
# letter out.
CAPTURE_FONT=${LINECAST_CAPTURE_FONT:-Monaspace Neon NF:size=11}

WEATHER_PLACE=${LINECAST_CAPTURE_WEATHER_PLACE:-Dublin, Ireland}
WEATHER_YEAR_PLACE=${LINECAST_CAPTURE_WEATHER_YEAR_PLACE:-Westbrook, Maine}
YEAR_PLACE=${LINECAST_CAPTURE_YEAR_PLACE:-Reykjavík}
RADAR_PLACE=${LINECAST_CAPTURE_RADAR_PLACE:-auto}
RADAR_LANG=${LINECAST_CAPTURE_RADAR_LANG:-}
STREET_PLACE=${LINECAST_CAPTURE_STREET_PLACE:-Portland, Maine}
TERRAIN_PLACE=${LINECAST_CAPTURE_TERRAIN_PLACE:--42.5,173.5}
GLOBE_PLACE=${LINECAST_CAPTURE_GLOBE_PLACE:-auto}
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
  weather    weather.png, plus weather-reykjavik.png in Icelandic and
             weather-kyoto.png in Japanese, both metric, and weather-year.png,
             the year view for Westbrook with the pointer on a week in May
  sunshine   one June day in sunshine-night/dawn/day/golden/dusk.png, and
             sunshine-winter.png for a January noon
  year       sunshine-year.png for Reykjavík in Icelandic, plus -arctic and
             -antarctic at 78° either side
  moon       moon.png, plus moon-okinawa.png in Japanese, moon-calendar.png,
             moon-alone.png with the text put away, and moon-spin.gif (and
             .mp4), the Moon dragged round and let go
  sky        sky.png on Orion, sky-allsky.png the whole sky at once, and
             sky-hawaiian.png the same winter sky in the Hawaiian tradition;
             sky-time.gif (and .mp4), the whole sky through an August
             afternoon and night
  tides      tides.png, then tides-month.png, tides-year.png, and
             tides-makeup.png, the views v steps through, and
             tides-makeup-tokyo.png in Japanese
  radar      radar.png and radar.gif, wherever the scout finds weather
  maps       maps-street.png, maps-terrain.png over New Zealand, and the
             zoom series maps-zoom-blocks/streets/city/region/state.png
  globe      maps-globe.png, the planet in this hour's daylight, and
             maps-globe-clouds.png with this hour's clouds (differ every run),
             and both again without labels or text, maps-globe-bare.png and
             maps-globe-clouds-bare.png
  gallery    the frames docs/gallery.md shows and the README does not, into
             screenshots/gallery: the radar in its fixed themes and its
             other layers, the sky in more traditions, the weather in a
             short window, with a day's hours under the pointer, and its
             month view, as temperatures and as departures, the moon's
             month grid, a walking route
  tours      globe-spin.gif and sky-pan.gif in screenshots/gallery, each
             a recording driven by a mouse script in scripts/tours
  hero       hero.png — five apps tiled on a 1920x1200 desktop, drawn at 2x,
             in the arrangement of Andrew's desktop 2
  languages  languages.png — a second desktop, the apps in Canadian French,
             Hawaiian, Japanese, and Icelandic
  themes     themes.gif (and .mp4) — the hero desktop through a run of
             Omarchy themes, the apps taking each one up

Environment overrides:
  LINECAST_CAPTURE_TOOL      offscreen_terminal.py, or termshot
  LINECAST_CAPTURE_THEME     the Omarchy theme every frame wears (tokyo-night)
  LINECAST_CAPTURE_FONT      fontconfig pattern for every single-app frame
  LINECAST_CAPTURE_WEATHER_PLACE
  LINECAST_CAPTURE_WEATHER_YEAR_PLACE
  LINECAST_CAPTURE_YEAR_PLACE
  LINECAST_CAPTURE_RADAR_PLACE   a place, or "auto" to let scout_radar.py pick
  LINECAST_CAPTURE_RADAR_LANG    language for a named radar place (auto brings its own)
  LINECAST_CAPTURE_STREET_PLACE
  LINECAST_CAPTURE_TERRAIN_PLACE
  LINECAST_CAPTURE_GLOBE_PLACE   LAT,LNG, or "auto" to centre on this hour's afternoon
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
mkdir -p "$SHOT_DIR" "$GALLERY_DIR"

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
require fc-match

# Every app is run as "linecast weather" and so on rather than by its bare
# name: the project declares only the linecast entry point, so a bare
# "uv run weather" falls through to whatever weather is on PATH, which on a
# machine with linecast installed is the released version, not this tree.

weather() {
    # The dashboard looks its best in a smallish window, where the chart
    # stays dense. The home frame is Dublin; two smaller ones show it in
    # other languages, metric and on the 24-hour clock, without making a
    # thing of it.
    printf 'Capturing weather…\n'
    "$CAPTURE_TOOL" -s 110x34 -w 10 --font "$CAPTURE_FONT" -o "$SHOT_DIR/weather.png" \
        uv --directory "$REPO_DIR" run linecast weather --location "$WEATHER_PLACE"
    "$CAPTURE_TOOL" -s 100x30 -w 10 --font "$CAPTURE_FONT" -o "$SHOT_DIR/weather-reykjavik.png" \
        uv --directory "$REPO_DIR" run linecast weather --location "Reykjavík" --lang is --metric --24h
    "$CAPTURE_TOOL" -s 100x30 -w 10 --font "$CAPTURE_FONT" -o "$SHOT_DIR/weather-kyoto.png" \
        uv --directory "$REPO_DIR" run linecast weather --location "Kyoto, Japan" --lang ja --metric --24h
    weather_year
}

weather_year() {
    # The year view, with the pointer on the middle of May so the week's
    # chip is in frame: on a 130x38 terminal, column 51, row 16.  The
    # first hover only carries the pointer onto the window, as in year();
    # here the view also answers that first move with a chip of its own,
    # and a single jump from it to May can land before the next frame, so
    # the pointer stops once on the way.  The archive answers in a few
    # seconds; the wait covers it.
    printf 'Capturing the weather year view…\n'
    "$CAPTURE_TOOL" -s 130x38 -w 12 --font "$CAPTURE_FONT" \
        --hover 100x12 --sleep 0.5 --hover 60x16 --sleep 0.7 --hover 51x16 --sleep 1.5 \
        -o "$SHOT_DIR/weather-year.png" \
        uv --directory "$REPO_DIR" run linecast weather --year --location "$WEATHER_YEAR_PLACE"
}

sunshine() {
    # One June day over Westbrook, six ways: night with the sun's dot
    # under the horizon, dawn, midday, golden hour, dusk, and a January
    # noon for the difference nine hours of daylight make to the arc.
    local at name spec
    for spec in "2026-06-21T23:30|sunshine-night.png" \
                "2026-06-21T05:05|sunshine-dawn.png" \
                "2026-06-21T13:30|sunshine-day.png" \
                "2026-06-21T19:15|sunshine-golden.png" \
                "2026-06-21T20:15|sunshine-dusk.png" \
                "2026-01-15T12:00|sunshine-winter.png"; do
        IFS='|' read -r at name <<<"$spec"
        printf 'Capturing sunshine %s…\n' "$name"
        "$CAPTURE_TOOL" -s 120x36 -w 4 --font "$CAPTURE_FONT" -o "$SHOT_DIR/$name" \
            uv --directory "$REPO_DIR" run python \
            "$REPO_DIR/scripts/capture_moment.py" \
            --at "$at" --location "$ASTRO_LOCATION" sunshine
    done
}

year() {
    # The year view for Reykjavík, in Icelandic, and at two places near the
    # poles, each with the pointer on the December solstice so the hover
    # tooltip is in frame. On a 120x36 terminal that is column 117, row 19 (noon). The
    # first hover only carries the pointer onto the window: a single warp
    # from outside arrives as a pointer enter, not the motion the app
    # listens for, so the second, real move is what raises the tooltip.
    #
    # "Today" is the June solstice, as in the day captures. capture_moment
    # reads --at in this machine's zone, so each is 13:30 local time in
    # Reykjavík, Svalbard, and at Vostok as seen from US Eastern; if that
    # drifts only the sun glyph's row moves.
    local place at name extra spec
    for spec in "$YEAR_PLACE|2026-06-21T09:30|sunshine-year.png|--lang is" \
                "$ARCTIC_PLACE|2026-06-21T07:30|sunshine-year-arctic.png|" \
                "$ANTARCTIC_PLACE|2026-06-21T04:30|sunshine-year-antarctic.png|"; do
        IFS='|' read -r place at name extra <<<"$spec"
        printf 'Capturing sunshine year view for %s…\n' "$place"
        "$CAPTURE_TOOL" -s 120x36 -w 6 --font "$CAPTURE_FONT" \
            --hover 100x12 --sleep 0.5 --hover 117x19 --sleep 1 \
            -o "$SHOT_DIR/$name" \
            uv --directory "$REPO_DIR" run python \
            "$REPO_DIR/scripts/capture_moment.py" \
            --at "$at" --location "$ASTRO_LOCATION" sunshine -- \
            --year --location "$place" $extra
    done
}

moon() {
    printf 'Capturing Moon…\n'
    "$CAPTURE_TOOL" -s 120x40 -w 4 --font "$CAPTURE_FONT" -o "$SHOT_DIR/moon.png" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-08-22T21:30 --location "$ASTRO_LOCATION" moon
    # Okinawa in Japanese, the evening after the mid-autumn full moon of
    # 2026, so the headline names the night 十六夜 and the calendar's
    # September carries 十五夜 on the 25th. capture_moment's --at lands as
    # the place's local time here. The calendar frame presses v and hovers
    # the 25th (column 94, row 27 on 120x40; the first hover only carries
    # the pointer onto the window, the second raises the chip). Then the Moon
    # alone, with its text put away, and the recording of it dragged round and
    # let go, which capture_offscreen.py draws with the pointer doing it.
    "$CAPTURE_TOOL" -s 120x40 -w 6 --font "$CAPTURE_FONT" -o "$SHOT_DIR/moon-okinawa.png" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-09-26T21:30 --location "$OKINAWA_LOCATION" moon -- \
        --lang ja --24h
    "$CAPTURE_TOOL" -s 120x40 -w 6 --font "$CAPTURE_FONT" --press v --sleep 2 \
        --hover 93x26 --sleep 1 --hover 94x27 --sleep 2 \
        -o "$SHOT_DIR/moon-calendar.png" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-09-26T21:30 --location "$OKINAWA_LOCATION" moon -- \
        --lang ja --24h
    "$OFFSCREEN" --theme "$LINECAST_CAPTURE_THEME" --out "$SHOT_DIR" moon moon-spin
}

sky() {
    # Three fixed nights over Westbrook. Orion on a January evening, framed
    # by --at; the whole August sky at once, the way the almanacs print it;
    # and the same January sky drawn in the Hawaiian tradition, with the
    # navigators' star compass along the horizon. sky resolves its own
    # location, so it gets --location on its side of the -- as well.
    local at name spec
    for spec in "2026-01-15T21:00|sky.png|--at Orion" \
                "2026-01-15T21:00|sky-hawaiian.png|--facing S --culture hawaiian"; do
        IFS='|' read -r at name extra <<<"$spec"
        printf 'Capturing sky %s…\n' "$name"
        # shellcheck disable=SC2086
        "$CAPTURE_TOOL" -s 120x40 -w 6 --font "$CAPTURE_FONT" -o "$SHOT_DIR/$name" \
            uv --directory "$REPO_DIR" run python \
            "$REPO_DIR/scripts/capture_moment.py" \
            --at "$at" --location "$ASTRO_LOCATION" sky -- \
            --location "$ASTRO_LOCATION" $extra
    done
    # The whole sky is zoomed out to by hand, with -, since only the
    # zoom lies the view back until the horizon is a circle centred
    # overhead; facing south first puts north at the top. Then the same
    # view played through an August afternoon and night.
    printf 'Capturing sky sky-allsky.png…\n'
    "$CAPTURE_TOOL" -s 120x40 -w 6 --font "$CAPTURE_FONT" --key ---- --sleep 2.5 \
        -o "$SHOT_DIR/sky-allsky.png" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-08-15T22:30 --location "$ASTRO_LOCATION" sky -- \
        --location "$ASTRO_LOCATION" --facing S
    "$OFFSCREEN" --theme "$LINECAST_CAPTURE_THEME" --out "$SHOT_DIR" sky-time
}

tides() {
    # The day's curve, then the three longer views v steps through: the
    # month, the year, and what moves the tide there. The year is a dozen
    # requests on a cold cache, so its wait is long, and the makeup is
    # fitted to the same year. The year has the pointer on the middle of
    # June, where 2026's highest water ran over the flood stage (column
    # 53, row 14 on 110x40; the first hover only carries the pointer onto
    # the window). Then Tokyo's makeup in Japanese, for README.ja.md:
    # there the Sun's part is half the Moon's and the once-a-day tide is
    # nearly as large as the twice-a-day.
    printf 'Capturing tides…\n'
    "$CAPTURE_TOOL" -s 120x36 -w 12 --font "$CAPTURE_FONT" -o "$SHOT_DIR/tides.png" \
        uv --directory "$REPO_DIR" run linecast tides --station "$TIDE_STATION"
    "$CAPTURE_TOOL" -s 110x40 -w 12 --font "$CAPTURE_FONT" --press v --sleep 8 \
        -o "$SHOT_DIR/tides-month.png" \
        uv --directory "$REPO_DIR" run linecast tides --station "$TIDE_STATION"
    "$CAPTURE_TOOL" -s 110x40 -w 12 --font "$CAPTURE_FONT" \
        --press v --sleep 2 --press v --sleep 25 \
        --hover 90x10 --sleep 0.7 --hover 53x14 --sleep 1.5 \
        -o "$SHOT_DIR/tides-year.png" \
        uv --directory "$REPO_DIR" run linecast tides --station "$TIDE_STATION"
    "$CAPTURE_TOOL" -s 120x36 -w 12 --font "$CAPTURE_FONT" \
        --press v --sleep 2 --press v --sleep 2 --press v --sleep 25 \
        -o "$SHOT_DIR/tides-makeup.png" \
        uv --directory "$REPO_DIR" run linecast tides --station "$TIDE_STATION"
    "$CAPTURE_TOOL" -s 120x36 -w 12 --font "$CAPTURE_FONT" \
        --press v --sleep 2 --press v --sleep 2 --press v --sleep 25 \
        -o "$SHOT_DIR/tides-makeup-tokyo.png" \
        uv --directory "$REPO_DIR" run linecast tides --station jma:TK --lang ja --metric --24h
}

# A radar frame is only worth taking where something is happening, and
# that moves: "auto" asks scout_radar.py which candidate city has the most
# weather on it right now, inside real radar coverage, and the frame then
# speaks that city's language. Resolved once; the radar and gallery targets
# share the answer.
RADAR_LANG_ARGS=()
resolve_radar_place() {
    [ -n "$RADAR_LANG" ] && RADAR_LANG_ARGS=(--lang "$RADAR_LANG")
    if [ "$RADAR_PLACE" = auto ]; then
        printf 'Scouting for weather…\n'
        local pick
        pick=$(uv --directory "$REPO_DIR" run python \
            "$REPO_DIR/scripts/scout_radar.py" --best)
        RADAR_PLACE=${pick%%$'\t'*}
        RADAR_LANG_ARGS=(--lang "${pick##*$'\t'}")
        printf 'Radar over %s, in %s\n' "$RADAR_PLACE" "${RADAR_LANG_ARGS[1]}"
    fi
    # A frame in another language reads the clock the way its readers do.
    case "${RADAR_LANG_ARGS[1]:-en}" in
        en*) ;;
        *) RADAR_LANG_ARGS+=(--24h) ;;
    esac
}

radar() {
    require ffmpeg
    resolve_radar_place
    local radar_lang=("${RADAR_LANG_ARGS[@]}")
    printf 'Capturing radar still…\n'
    # No window padding: the radar frame is shot without the border.
    "$CAPTURE_TOOL" -s 120x36 -w 15 --pad 0 --font "$CAPTURE_FONT" \
        -o "$SHOT_DIR/radar.png" \
        uv --directory "$REPO_DIR" run linecast radar --location "$RADAR_PLACE" "${radar_lang[@]}"

    printf 'Capturing radar animation…\n'
    # Slow playback in the capture-only wrapper to a frame every half second,
    # record for longer than the 18 LibreWXR frames take so none is skipped,
    # collapse repeated screen states, then encode one complete loop at the
    # app's observed cadence.
    local radar_tmp_dir frame previous diff selected picked=0
    radar_tmp_dir=$(mktemp -d /tmp/linecast-radar-gif.XXXXXX)
    "$CAPTURE_TOOL" -s 120x36 -w 15 --pad 0 --font "$CAPTURE_FONT" \
        --gif 12 --fps 8 --gif-width 800 -o "$radar_tmp_dir/raw.gif" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_radar.py" --location "$RADAR_PLACE" "${radar_lang[@]}"

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
    "$CAPTURE_TOOL" -s 120x38 -w 15 --font "$CAPTURE_FONT" -o "$SHOT_DIR/maps-street.png" \
        uv --directory "$REPO_DIR" run linecast maps --location "$STREET_PLACE" \
        --zoom 0.015

    # Both islands with the seafloor around them: the Hikurangi Trough off
    # the east coast and the Chatham Rise running out from Canterbury.
    printf 'Capturing terrain map…\n'
    "$CAPTURE_TOOL" -s 120x38 -w 15 --font "$CAPTURE_FONT" -o "$SHOT_DIR/maps-terrain.png" \
        uv --directory "$REPO_DIR" run linecast maps --view terrain \
        --location "$TERRAIN_PLACE" --zoom 12

    # The same place at five zooms, a decade apart or so, to show what the
    # map chooses to say at each: shop names at block level, neighbourhood
    # names and street names next, the cove and the bridge at city scale,
    # towns and islands at the region, only highways and towns at the state.
    local zoom name spec
    for spec in "0.004|blocks" "0.015|streets" "0.05|city" "0.2|region" "1|state"; do
        IFS='|' read -r zoom name <<<"$spec"
        printf 'Capturing street map at zoom %s…\n' "$zoom"
        "$CAPTURE_TOOL" -s 120x38 -w 15 --font "$CAPTURE_FONT" \
            -o "$SHOT_DIR/maps-zoom-$name.png" \
            uv --directory "$REPO_DIR" run linecast maps --location "$STREET_PLACE" \
            --zoom "$zoom"
    done
}

globe() {
    # The globe is only worth looking at with the terminator across the
    # disk. "auto" centres the view 45° east of where the sun is overhead
    # right now, so the left of the disk is afternoon, the sunset line
    # crosses the right half, and the city lights are coming on beyond it,
    # whatever the hour here.
    if [ "$GLOBE_PLACE" = auto ]; then
        GLOBE_PLACE=$(python3 -c '
import datetime
now = datetime.datetime.now(datetime.timezone.utc)
subsolar = -15 * (now.hour + now.minute / 60 - 12)
lon = (subsolar + 45 + 180) % 360 - 180
print(f"20,{lon:.0f}")')
        printf 'Globe centred on %s\n' "$GLOBE_PLACE"
    fi
    printf 'Capturing globe…\n'
    # The plain terrain planet with S pressed for this hour's daylight
    # and city lights, and then with c pressed as well for this hour's
    # clouds: the daylight-only frame reads at a glance, where the cloud
    # layer makes a first-glance reader work out what they are looking
    # at; the cloudy one is the planet as it is. Both are honestly
    # different every run. --view now brings the daylight and the clouds
    # by itself, but it also puts the text and the labels away and sets
    # the planet turning a degree a second, so by the time the clouds are
    # in, the sunset line has left the frame; these open on terrain and
    # press the keys instead. The clouds take a while to arrive at this
    # size, hence the longer settle.
    "$CAPTURE_TOOL" -s 120x38 -w 25 --font "$CAPTURE_FONT" --key S --sleep 4 \
        -o "$SHOT_DIR/maps-globe.png" \
        uv --directory "$REPO_DIR" run linecast maps --view terrain --zoom 130 \
        --location "$GLOBE_PLACE"
    "$CAPTURE_TOOL" -s 120x38 -w 25 --font "$CAPTURE_FONT" --key Sc --sleep 25 \
        -o "$SHOT_DIR/maps-globe-clouds.png" \
        uv --directory "$REPO_DIR" run linecast maps --view terrain --zoom 130 \
        --location "$GLOBE_PLACE"
    # The planet alone: the same two with the labels put away by l and
    # the text by t. The second is what --view now opens on, held still.
    printf 'Capturing the globe alone…\n'
    "$CAPTURE_TOOL" -s 120x38 -w 25 --font "$CAPTURE_FONT" --key Slt --sleep 4 \
        -o "$SHOT_DIR/maps-globe-bare.png" \
        uv --directory "$REPO_DIR" run linecast maps --view terrain --zoom 130 \
        --location "$GLOBE_PLACE"
    "$CAPTURE_TOOL" -s 120x38 -w 25 --font "$CAPTURE_FONT" --key Sclt --sleep 25 \
        -o "$SHOT_DIR/maps-globe-clouds-bare.png" \
        uv --directory "$REPO_DIR" run linecast maps --view terrain --zoom 130 \
        --location "$GLOBE_PLACE"
}

gallery() {
    # The states the README leaves out. Smaller windows than the README
    # frames: these sit three abreast on the gallery page.
    resolve_radar_place
    local theme
    for theme in dusk ember ink marangai; do
        printf 'Capturing radar in %s…\n' "$theme"
        "$CAPTURE_TOOL" -s 100x30 -w 15 --pad 0 --font "$CAPTURE_FONT" \
            -o "$GALLERY_DIR/radar-$theme.png" \
            uv --directory "$REPO_DIR" run linecast radar --location "$RADAR_PLACE" \
            --theme "$theme" "${RADAR_LANG_ARGS[@]}"
    done
    printf 'Capturing radar satellite layer…\n'
    "$CAPTURE_TOOL" -s 100x30 -w 20 --pad 0 --font "$CAPTURE_FONT" \
        -o "$GALLERY_DIR/radar-satellite.png" \
        uv --directory "$REPO_DIR" run linecast radar --location "$RADAR_PLACE" \
        --layer satellite "${RADAR_LANG_ARGS[@]}"
    printf 'Capturing radar with temperature and wind…\n'
    "$CAPTURE_TOOL" -s 100x30 -w 20 --pad 0 --font "$CAPTURE_FONT" \
        -o "$GALLERY_DIR/radar-layers.png" \
        uv --directory "$REPO_DIR" run linecast radar --location "$RADAR_PLACE" \
        --layers temp,wind "${RADAR_LANG_ARGS[@]}"

    # The same January sky as the README's, in three more traditions.
    local culture
    for culture in chinese norse rey; do
        printf 'Capturing sky in the %s tradition…\n' "$culture"
        "$CAPTURE_TOOL" -s 120x40 -w 6 --font "$CAPTURE_FONT" \
            -o "$GALLERY_DIR/sky-$culture.png" \
            uv --directory "$REPO_DIR" run python \
            "$REPO_DIR/scripts/capture_moment.py" \
            --at 2026-01-15T21:00 --location "$ASTRO_LOCATION" sky -- \
            --location "$ASTRO_LOCATION" --facing S --culture "$culture"
    done

    printf 'Capturing weather in a short window…\n'
    "$CAPTURE_TOOL" -s 90x22 -w 10 --font "$CAPTURE_FONT" \
        -o "$GALLERY_DIR/weather-short.png" \
        uv --directory "$REPO_DIR" run linecast weather --location "$WEATHER_PLACE"

    # The dashboard at the README's size, with the pointer on a day's bar
    # for the chip that draws that day's hours: the fourth day, column 58,
    # row 26 on 110x34.
    printf 'Capturing weather with the pointer on a day…\n'
    "$CAPTURE_TOOL" -s 110x34 -w 10 --font "$CAPTURE_FONT" \
        --hover 100x12 --sleep 0.5 --hover 56x26 --sleep 0.7 --hover 58x26 --sleep 1.5 \
        -o "$GALLERY_DIR/weather-day.png" \
        uv --directory "$REPO_DIR" run linecast weather --location "$WEATHER_PLACE"

    # Last month's hourly temperatures for the year view's place, as
    # --month opens, then the same month as c shows it, each hour against
    # its ten-year average, with the pointer on the afternoon of the 10th
    # so the chip that gives the hour, its average, and the difference is
    # in the frame: on 110x40, column 66, row 16. A 31-day month starts a
    # row higher, and the pointer is then on the 11th. As in weather_year,
    # the pointer stops once on the way.
    printf 'Capturing the weather month view…\n'
    "$CAPTURE_TOOL" -s 110x40 -w 15 --font "$CAPTURE_FONT" \
        -o "$GALLERY_DIR/weather-month.png" \
        uv --directory "$REPO_DIR" run linecast weather --month --location "$WEATHER_YEAR_PLACE"
    "$CAPTURE_TOOL" -s 110x40 -w 15 --font "$CAPTURE_FONT" \
        --hover 100x12 --sleep 0.5 --hover 70x16 --sleep 0.7 --hover 66x16 --sleep 1.5 \
        -o "$GALLERY_DIR/weather-month-departure.png" \
        uv --directory "$REPO_DIR" run linecast weather --month-departure --location "$WEATHER_YEAR_PLACE"

    printf 'Capturing the moon month grid…\n'
    "$CAPTURE_TOOL" -s 120x40 -w 4 --font "$CAPTURE_FONT" \
        -o "$GALLERY_DIR/moon-grid.png" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-09-13T21:30 --location "$ASTRO_LOCATION" moon -- --month

    printf 'Capturing the Alps in terrain…\n'
    "$CAPTURE_TOOL" -s 120x38 -w 15 --font "$CAPTURE_FONT" \
        -o "$GALLERY_DIR/maps-innsbruck.png" \
        uv --directory "$REPO_DIR" run linecast maps --view terrain \
        --location Innsbruck --zoom 1.5
    printf 'Capturing Cook Strait in terrain…\n'
    "$CAPTURE_TOOL" -s 120x38 -w 15 --font "$CAPTURE_FONT" \
        -o "$GALLERY_DIR/maps-cook-strait.png" \
        uv --directory "$REPO_DIR" run linecast maps --view terrain \
        --location -41.3,174.6 --zoom 7

    # A continent under this hour's clouds, at a zoom between the street
    # map and the globe, centred where it is mid-afternoon right now. S and
    # c bring the daylight and the clouds, as in globe(), since --view now
    # would put the labels away and turn the view off the continent.
    local afternoon
    afternoon=$(python3 -c '
import datetime
now = datetime.datetime.now(datetime.timezone.utc)
subsolar = -15 * (now.hour + now.minute / 60 - 12)
lon = (subsolar - 20 + 180) % 360 - 180
print(f"30,{lon:.0f}")')
    printf 'Capturing clouds over a continent at %s…\n' "$afternoon"
    "$CAPTURE_TOOL" -s 120x38 -w 15 --font "$CAPTURE_FONT" --key Sc --sleep 25 \
        -o "$GALLERY_DIR/maps-clouds-continent.png" \
        uv --directory "$REPO_DIR" run linecast maps --view terrain \
        --location "$afternoon" --zoom 45

    printf 'Capturing a walking route…\n'
    "$CAPTURE_TOOL" -s 120x38 -w 25 --font "$CAPTURE_FONT" \
        -o "$GALLERY_DIR/maps-route.png" \
        uv --directory "$REPO_DIR" run linecast maps --from "Portland, Maine" \
        --to "South Portland, Maine" --profile foot
}

# The desktops are composed by capture_offscreen.py, which runs every pane
# at once on one clock. The hero's radar looks over Portland, beside the
# Westbrook weather, unless LINECAST_CAPTURE_RADAR_PLACE names a place.
desktop() {
    local radar=${LINECAST_CAPTURE_RADAR_PLACE:-auto}
    [ "$radar" = auto ] && radar="Portland, Maine"
    "$OFFSCREEN" --theme "$LINECAST_CAPTURE_THEME" --radar "$radar" --out "$SHOT_DIR" "$@"
}

hero() { desktop hero; }
languages() { desktop languages; }
themes() { require ffmpeg; desktop themes; }

tours() {
    # Recordings driven by the mouse, each scripted in scripts/tours.
    printf 'Recording the globe spin…\n'
    "$CAPTURE_TOOL" -s 100x30 -w 20 --font "$CAPTURE_FONT" \
        --gif 7 --fps 10 --gif-width 700 \
        --script "$REPO_DIR/scripts/tours/globe-spin.termshot" \
        -o "$GALLERY_DIR/globe-spin.gif" \
        uv --directory "$REPO_DIR" run linecast maps --view terrain --zoom 130 \
        --location 20,-30
    printf 'Recording the sky pan…\n'
    "$CAPTURE_TOOL" -s 100x30 -w 6 --font "$CAPTURE_FONT" \
        --gif 7 --fps 10 --gif-width 700 \
        --script "$REPO_DIR/scripts/tours/sky-pan.termshot" \
        -o "$GALLERY_DIR/sky-pan.gif" \
        uv --directory "$REPO_DIR" run python \
        "$REPO_DIR/scripts/capture_moment.py" \
        --at 2026-01-15T21:00 --location "$ASTRO_LOCATION" sky -- \
        --location "$ASTRO_LOCATION" --facing S
}

run_target() {
    case "$1" in
        weather|sunshine|year|moon|sky|tides|radar|maps|globe|gallery|tours|hero|languages|themes)
            "$1" ;;
        all)
            weather
            sunshine
            year
            moon
            sky
            tides
            radar
            maps
            globe
            gallery
            tours
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
