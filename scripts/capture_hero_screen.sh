#!/usr/bin/env bash
# The hero as a whole-screen screenshot: five linecast panes on a headless
# 1920x1200 Hyprland output drawn at 2x, with the Omarchy bar along the top,
# the wallpaper and theme the desktop is wearing, and foot's own font.
#
#   scripts/capture_hero_screen.sh                 # -> screenshots/hero.png
#   scripts/capture_hero_screen.sh out.png
#
# This is the real desktop, not scripts/offscreen_terminal.py's drawing of
# one, so it needs Hyprland, foot, grim, wtype, ImageMagick, and the Omarchy
# shell. Nothing is drawn on the real display: the output is created far to
# the right, the windows open on its workspace without taking focus, and it
# is removed afterwards. Keyboard focus is borrowed for about two seconds
# at the end, to pause the radar on its "now" frame and to give the year
# view the accent border, and handed back.
#
# The arrangement is Andrew's second desktop: the Westbrook weather over its
# year on the left; the radar over Portland on the right, above the tide at
# Portland and the year of daylight in Reykjavík in Icelandic. Each pane is a
# floating window placed where dwindle would tile it, so the ratios below
# can be tuned without fighting the layout.
#
# Environment overrides:
#   LINECAST_CAPTURE_RADAR_PLACE   the radar's place (Portland, Maine)
#   LINECAST_CAPTURE_TIDE_STATION  the tide station (8418150, Portland)
#   LINECAST_CAPTURE_HIDE_PLUGINS  bar plugins switched off for the shot,
#                                  space separated (ashuttl.stars)
#   LINECAST_CAPTURE_SETTLE        seconds for the panes to load (50)
set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
OUT=${1:-$REPO_DIR/screenshots/hero.png}
RADAR_PLACE=${LINECAST_CAPTURE_RADAR_PLACE:-Portland, Maine}
[ "$RADAR_PLACE" = auto ] && RADAR_PLACE="Portland, Maine"
TIDE_STATION=${LINECAST_CAPTURE_TIDE_STATION:-8418150}
HIDE_PLUGINS=${LINECAST_CAPTURE_HIDE_PLUGINS-ashuttl.stars}
SETTLE=${LINECAST_CAPTURE_SETTLE:-50}

LOGW=1920; LOGH=1200; SCALE=2
MONX=20000; MONY=0
MON=linecasthero$$
GAPS_OUT=10; GAP=10; BORDER=2      # Omarchy's defaults; the bar takes the top gap

for tool in hyprctl foot grim wtype magick omarchy-shell; do
    command -v "$tool" >/dev/null || { echo "capture_hero_screen: $tool is not installed" >&2; exit 1; }
done

TMP=$(mktemp -d /tmp/linecast-hero.XXXXXX)
# The same hermetic home scripts/offscreen_terminal.py gives every frame.
mkdir -p "$TMP/config"
printf '%s' '{"location": {"lat": 43.677, "lng": -70.3712, "label": "Westbrook, Maine", "country": "US"}}' \
    > "$TMP/config/config.json"

PIDS=()
HIDDEN=()
CREATED=0
FOCUS_TAKEN=0
PREV_CURSOR=$(hyprctl cursorpos 2>/dev/null || true)
PREV_ADDR=$(hyprctl activewindow -j 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("address",""))' 2>/dev/null || true)

move_cursor() { hyprctl eval "hl.dispatch(hl.dsp.cursor.move({ x = $1, y = $2 }))" >/dev/null 2>&1 || true; }
focus_window() { hyprctl eval "hl.dispatch(hl.dsp.focus({ window = \"address:$1\" }))" >/dev/null 2>&1 || true; }
address_of() {  # $1 = app id
    hyprctl clients -j | APPID="$1" python3 -c '
import json, os, sys
print(next((c["address"] for c in json.load(sys.stdin) if c["class"] == os.environ["APPID"]), ""))'
}
cleanup() {
    [ ${#PIDS[@]} -gt 0 ] && kill "${PIDS[@]}" 2>/dev/null
    # The output goes first: while it exists, the real outputs' coordinates
    # are shifted and the cursor would be sent to the wrong place.
    if [ "$CREATED" = 1 ]; then hyprctl output remove "$MON" >/dev/null 2>&1; sleep 0.5; fi
    [ "$FOCUS_TAKEN" = 1 ] && [ -n "$PREV_ADDR" ] && focus_window "$PREV_ADDR"
    [ -n "$PREV_CURSOR" ] && move_cursor "${PREV_CURSOR%,*}" "${PREV_CURSOR##*, }"
    for id in "${HIDDEN[@]}"; do omarchy-shell -q shell setPluginEnabled "$id" true; done
    rm -rf "$TMP"
}
trap cleanup EXIT

for id in $HIDE_PLUGINS; do
    if [ "$(omarchy-shell shell setPluginEnabled "$id" false 2>/dev/null)" = ok ]; then
        HIDDEN+=("$id")
    else
        echo "capture_hero_screen: bar plugin $id not found; left alone" >&2
    fi
done

hyprctl output create headless "$MON" >/dev/null || { echo "capture_hero_screen: could not create a headless output" >&2; exit 1; }
CREATED=1
hyprctl eval "hl.monitor({ output = \"$MON\", mode = \"$((LOGW * SCALE))x$((LOGH * SCALE))@60\", position = \"${MONX}x${MONY}\", scale = $SCALE })" >/dev/null
sleep 1.5
read -r WS TOP < <(hyprctl monitors -j | MON="$MON" python3 -c '
import json, os, sys
m = next((m for m in json.load(sys.stdin) if m["name"] == os.environ["MON"]), None)
print(m["activeWorkspace"]["name"], m["reserved"][1]) if m else print("", 0)')
[ -n "$WS" ] || { echo "capture_hero_screen: the headless output never came up" >&2; exit 1; }

# Window content rectangles, split the way dwindle splits, border excluded.
mapfile -t RECTS < <(python3 - "$LOGW" "$LOGH" "$TOP" "$GAPS_OUT" "$GAP" "$BORDER" <<'PY'
import sys
W, H, top, gaps_out, gap, b = map(int, sys.argv[1:])
def tile(node, box):
    if isinstance(node, str):
        return [(node, box)]
    kind, ratio, a, c = node
    x, y, w, h = box
    if kind == "h":
        first = round((w - gap) * ratio)
        return tile(a, (x, y, first, h)) + tile(c, (x + first + gap, y, w - first - gap, h))
    first = round((h - gap) * ratio)
    return tile(a, (x, y, w, first)) + tile(c, (x, y + first + gap, w, h - first - gap))
layout = ("h", 0.535,
          ("v", 0.58, "weather", "year"),
          ("v", 0.575, "radar", ("h", 0.55, "tides", "sunshine")))
for name, (x, y, w, h) in tile(layout, (gaps_out, top, W - 2 * gaps_out, H - top - gaps_out)):
    print(name, x + b, y + b, w - 2 * b, h - 2 * b)
PY
)

pane_command() {
    case "$1" in
        weather)  printf "linecast weather --location 'Westbrook, Maine'" ;;
        year)     printf "linecast weather --year --location 'Westbrook, Maine'" ;;
        radar)    printf "linecast radar --location '%s'" "$RADAR_PLACE" ;;
        tides)    printf "linecast tides --station '%s'" "$TIDE_STATION" ;;
        sunshine) printf "linecast sunshine --year --location Reykjavík --lang is --24h" ;;
    esac
}

for line in "${RECTS[@]}"; do
    read -r name x y w h <<<"$line"
    wrap=$TMP/run-$name.sh
    cat > "$wrap" <<EOW
#!/usr/bin/env bash
export LINECAST_CONFIG_DIR='$TMP/config' LINECAST_ICONS=nerd LANG=en_US.UTF-8
unset LINECAST_LANG LINECAST_THEME NO_COLOR
cd '$REPO_DIR' && uv --directory '$REPO_DIR' run $(pane_command "$name")
read -r -t 900 _ || sleep 900
EOW
    chmod +x "$wrap"
    appid=linecast-hero-$name
    # Rule coordinates are relative to the output the window opens on.
    hyprctl eval "hl.dispatch(hl.dsp.exec_cmd(\"[workspace $WS silent;float;noanim;move $x $y;size $w $h] foot --app-id=$appid $wrap\"))" >/dev/null
    for _ in $(seq 1 40); do
        pid=$(hyprctl clients -j | APPID="$appid" python3 -c '
import json, os, sys
print(next((c["pid"] for c in json.load(sys.stdin) if c["class"] == os.environ["APPID"]), ""))')
        [ -n "$pid" ] && break
        sleep 0.25
    done
    [ -n "$pid" ] || { echo "capture_hero_screen: the $name pane never opened" >&2; exit 1; }
    PIDS+=("$pid")
    sleep 0.3
done

# Creating the output warped the pointer onto it; a headless output draws
# the cursor into its framebuffer, so park it on the last pixel.
move_cursor "$((MONX + LOGW - 1))" "$((MONY + LOGH - 1))"
sleep "$SETTLE"

radar=$(address_of linecast-hero-radar)
year=$(address_of linecast-hero-year)
FOCUS_TAKEN=1
if [ -n "$radar" ]; then
    focus_window "$radar"; sleep 0.6
    wtype -k space            # pause: the loop homes on the present
    sleep 1.2
fi
if [ -n "$year" ]; then
    focus_window "$year"; sleep 0.5
fi
move_cursor "$((MONX + LOGW - 1))" "$((MONY + LOGH - 1))"
sleep 0.4

grim -g "${MONX},${MONY} ${LOGW}x${LOGH}" "$TMP/shot.png" || exit 1
magick "$TMP/shot.png" -define png:compression-level=9 -define png:compression-filter=5 "$OUT"
echo "capture_hero_screen: $OUT ($(magick identify -format '%wx%h' "$OUT"))"
