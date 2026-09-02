"""The live radar: what runs when you type `radar`.

main() settles the arguments, resolves the location and picks the
source, then runs render_radar under live_loop as a RadarApp — the
state that gives the view its hands: zoom, drag, the layer keys and
the theme picker.  --print renders once and exits.  Everything drawn
is in radar; the frames and their prefetcher are in _radar_frames.
"""

import os
import sys

from linecast import _radar_frames
from linecast import _radar_sources
from linecast._framebuffer import get_terminal_size
from linecast._geo import wrap_lon
from linecast._live import LiveApp
from linecast._location import country_for_defaults, resolve_location
from linecast._radar_frames import N_FRAMES, _nudge, _sat_timeline
from linecast._radar_i18n import rs
from linecast._radar_render import bbox_for
from linecast._radar_source import FRAME_STEP
from linecast._radar_sources import (
    DEFAULT_THEME, THEMES, _in_conus, get_source, theme_id,
)
from linecast._radar_ui import ThemePicker
from linecast._runtime import RuntimeConfig, radar_parser, set_current
from linecast._spinner import Spinner
from linecast.radar import LAYERS, parse_layers, render_radar


class RadarApp(LiveApp):
    """The live radar's state and keys, run under live_loop.

    The centre pans while the marker stays at the true location; the
    layer keys toggle the condition layers and cycle radar and
    satellite; + and - zoom; t opens the theme picker, which takes
    every key while open.  A theme change swaps the source for one
    with the same index, so nothing is fetched again.
    """

    interval = FRAME_STEP   # pick up a new composite every 5 min
    mouse = True
    auto_play = True
    play_interval = 0.2     # animation frame rate (~5 fps)

    def __init__(self, runtime, lat, lon, location_name, zoom, layers,
                 layer, theme):
        self.runtime = runtime
        self.home = (lat, lon)         # the marker stays at the true location
        self.location_name = location_name
        self.zoom = zoom
        self.lat, self.lon = lat, lon  # the view centre; pans
        self.region = _in_conus(lat, lon)
        self.layers = set(layers)
        self.layer = layer
        self.theme = theme             # active theme id (the picker updates it)
        self.pan_preview = (0, 0)      # live cell offset while a drag is in progress
        self.picker = ThemePicker()

    def on_action(self, key):
        if key in ('c', 'w'):
            self.layers.symmetric_difference_update(
                {'temp' if key == 'c' else 'wind'})
            return True
        if key == 's':
            # cycle layers; a no-op on sources without a cloud mosaic
            if not _sat_timeline():
                return False
            i = LAYERS.index(self.layer)
            self.layer = LAYERS[(i + 1) % len(LAYERS)]
            return True
        if key == '+':
            new_zoom = max(1.0, self.zoom / 1.5)
        elif key == '-':
            new_zoom = min(60.0, self.zoom * 1.5)
        else:
            return False
        if new_zoom == self.zoom:
            return False
        self.zoom = new_zoom
        return True

    def intercept(self, action):
        """Route keys to the theme picker; everything else passes through."""
        source = _radar_frames._source
        if not self.picker.handle(action, getattr(source, "themes", None),
                                  getattr(source, "theme", None)):
            return False
        choice = self.picker.take_chosen()
        if choice is not None:
            self.theme = choice
            # same index, no fetch
            _radar_frames._source = source.with_theme(choice)
        return True

    def on_drag(self, dcol, drow, done):
        if not done:
            # mid-drag: update the screen-space preview offset only
            changed = self.pan_preview != (dcol, drow)
            self.pan_preview = (dcol, drow)
            return changed
        had_preview = self.pan_preview[0] or self.pan_preview[1]
        self.pan_preview = (0, 0)
        if not (dcol or drow):
            return bool(had_preview)  # zero-delta release = plain click
        # commit: dragging pulls the map, so the view centre moves the
        # opposite way; the release re-render re-projects for real
        cols, rows = get_terminal_size()
        gw, hc = max(20, cols), max(8, rows - 2)
        minlon, _, maxlon, _ = bbox_for(self.lat, self.lon, self.zoom, gw, hc)
        lon_span = maxlon - minlon
        self.lat = max(-80.0, min(80.0, self.lat + drow * self.zoom / hc))
        self.lon = wrap_lon(self.lon + -dcol * lon_span / gw)
        # crossing the CONUS boundary re-picks the source when the one in
        # hand isn't LibreWXR: the natural moment to retry it after a
        # fallback (a themed RainViewer is still a fallback)
        r = _in_conus(self.lat, self.lon)
        if r != self.region:
            self.region = r
            if getattr(_radar_frames._source, "kind", None) != "lwxr":
                _radar_frames._source = get_source(
                    self.lat, self.lon, N_FRAMES, self.theme)
        return True

    def play_gate(self):
        return not _radar_frames._buffering

    def render(self, play_frame=0, playing=True, mouse_pos=None, **_):
        themes = getattr(_radar_frames._source, "themes", None)
        return render_radar(
            self.lat, self.lon, self.location_name, self.zoom,
            play_frame=play_frame, playing=playing,
            marker=self.home,
            runtime=self.runtime, block=False, mouse_pos=mouse_pos,
            pan_offset=self.pan_preview,
            layers=frozenset(self.layers),
            layer=self.layer,
            theme_menu=((list(themes), self.picker.sel)
                        if self.picker.is_open and themes else None))


def main():
    args = radar_parser().parse_args()
    runtime = RuntimeConfig.from_sources(args)
    set_current(runtime)

    # Sweep day-old frame tiles before fetching new ones — they're keyed by
    # frame timestamp and will never be asked for again.
    from linecast._radar_tiles import prune_tile_cache
    prune_tile_cache()

    if args.search:
        from linecast._weather_sources import _search_locations
        _search_locations(args.search, lang=runtime.lang)
        return

    theme_arg = (args.theme
                 or os.environ.get("LINECAST_RADAR_THEME", "").strip()
                 or DEFAULT_THEME)
    theme = theme_id(theme_arg)
    if theme is None:
        print(f'Unknown radar theme "{theme_arg}". '
              f'Themes: {", ".join(THEMES)}.', file=sys.stderr)
        sys.exit(2)

    layer_arg = (args.layers
                 or os.environ.get("LINECAST_RADAR_LAYERS", "")).strip()
    layers = parse_layers(layer_arg)
    if layers is None:
        print(f'Unknown radar layer in "{layer_arg}". Layers: temp, wind.',
              file=sys.stderr)
        sys.exit(2)

    layer = {"radar": "radar", "satellite": "sat", "sat": "sat"}.get(
        (args.layer or os.environ.get("LINECAST_RADAR_LAYER", "").strip()
         or "radar").lower())
    if layer is None:
        print('Unknown radar layer. Layers: radar, satellite.',
              file=sys.stderr)
        sys.exit(2)

    source_arg = (args.source
                  or os.environ.get("LINECAST_RADAR_SOURCE", "")).strip().lower()
    if source_arg:
        if source_arg not in ("librewxr", "rainviewer", "iem"):
            print('Unknown radar source. Sources: librewxr, rainviewer, iem.',
                  file=sys.stderr)
            sys.exit(2)
        _radar_sources.FORCED_SOURCE = source_arg

    # everything from here to the first paint may block on the network
    # (geocoding, the frame index, static-mode frame fetches) — spin
    spin = Spinner(rs("loading", runtime.lang))
    spin.start()
    try:
        lat, lon, country, location_name = resolve_location(
            args.location, lang=runtime.lang, return_label=True)
        if lat is None:
            spin.stop()
            print("Could not determine location.", file=sys.stderr)
            sys.exit(1)

        # Re-resolve a countryless first-run runtime consistently with the
        # other views. An explicit location only stands in when the user's
        # own country is not known yet.
        own = country_for_defaults(args.location, country, lat, lon)
        if own:
            runtime = RuntimeConfig.from_sources(args, country=own)
            set_current(runtime)

        if not location_name:
            try:
                from linecast._weather_sources import _reverse_geocode
                location_name = _reverse_geocode(
                    lat, lon, lang=runtime.lang)[0] or ""
            except Exception:
                location_name = ""

        _radar_frames._source = get_source(lat, lon, N_FRAMES, theme)

        if not runtime.live:
            # static: play_frame 0 is the present (newest observed) frame
            def render_once():
                return render_radar(lat, lon, location_name, args.zoom,
                                    play_frame=0, playing=False,
                                    runtime=runtime, layers=layers,
                                    layer=layer)

            static_out = render_once()
            if _radar_frames.frame_load_failed and _radar_frames._fall_back():
                # the source answered its index and then could not serve the
                # tiles; the one we fall to keeps its own frame list, so the
                # whole render goes again rather than the frame alone
                _radar_frames.frame_load_failed = False
                static_out = render_once()
    finally:
        spin.stop()

    if not runtime.live:
        print(static_out)
        return

    # a background index refresh that adds a frame repaints the timeline
    _radar_sources.on_index_refresh = _nudge
    RadarApp(runtime, lat, lon, location_name, args.zoom, layers, layer,
             theme).run()
