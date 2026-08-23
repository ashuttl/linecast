"""Client-side radar colour themes.

The server-rendered schemes bake colour into tile pixels; these themes
instead fetch LibreWXR's grayscale scheme (colour 0, unsmoothed) and
colour it here.  In that scheme a pixel's gray level is the reflectivity:
gray = dBZ + 32, and +128 flags snow.  Unsmoothed tiles keep those values
exact; the smoothed variant blurs across the snow bit.

Colouring locally is what lets a theme draw the weather in the terminal's
own colours: ``terminal`` takes the ``dusk`` ladder and re-inks each step
in the terminal palette's hues, so a monochrome theme gets monochrome rain
and a stock theme gets yellow where yellow belongs.  The other palettes
are fixed ramps over dBZ, each with a light- and a dark-background form.
"""

from linecast import _theme
from linecast._color import interp_stops, lerp

GRAY_OFFSET = 32
SNOW_FLAG = 128

# Below this, echoes are noise-level and the server schemes leave them out.
MIN_DBZ = 10


def decode(gray):
    """Scheme-0 gray level → (dBZ, is_snow)."""
    snow = gray >= SNOW_FLAG
    return (gray - (SNOW_FLAG if snow else 0)) - GRAY_OFFSET, snow


def _alpha(dbz):
    """Light rain sits translucent over the map; cores are solid.

    Mirrors the server's dark-sky scheme, where alpha does the work at the
    low end (about 0.2 at 10 dBZ, opaque by 30)."""
    t = (dbz - MIN_DBZ) / 20.0
    return int(255 * (0.25 + 0.75 * max(0.0, min(1.0, t))))


def _ramp(stops):
    def colour(dbz):
        return interp_stops(stops, dbz)
    return colour


def _steps(bands):
    """Discrete colour bands: each (dbz, colour) holds until the next.

    For palettes that change hue at category boundaries, where blending
    across the boundary would invent a colour neither side means.
    """
    def colour(dbz):
        chosen = bands[0][1]
        for floor, rgb in bands:
            if dbz >= floor:
                chosen = rgb
        return chosen
    return colour


def _themed_ramp(stops):
    """A ramp re-inked in the terminal's own hues (see _theme.themed).

    Evaluated per call: the palette probe may refine the theme after
    import.  On a default palette this is close to the plain ramp; on a
    monochrome theme every stop collapses to the theme's one hue while
    the luminance ladder still carries the intensity.
    """
    def colour(dbz):
        return _theme.themed(interp_stops(stops, dbz))
    return colour


class Palette:
    __slots__ = ("rain", "snow", "dark_rain", "dark_snow")

    def __init__(self, rain, snow, dark_rain=None, dark_snow=None):
        # a ramp drawn for light terminals can carry a dark-terminal twin
        self.rain = rain
        self.snow = snow
        self.dark_rain = dark_rain or rain
        self.dark_snow = dark_snow or snow

    def colour(self, dbz, snow):
        if _theme.is_light_theme():
            return (self.snow if snow else self.rain)(dbz)
        return (self.dark_snow if snow else self.dark_rain)(dbz)


# The dark form is the server's dark-sky ladder as measured from its tiles
# — one saturated blue through 20 dBZ with alpha doing the fading, then
# violet, coral and orange to yellow by 45 — with a cream step above it so
# a hail core still tops out on its own.  The light form mirrors its shape.
_DUSK_LIGHT = [(10, (205, 215, 240)), (20, (160, 150, 225)),
               (28, (150, 80, 200)), (35, (210, 60, 130)),
               (40, (235, 90, 60)), (48, (220, 150, 0)), (58, (90, 40, 0))]
_DUSK_LIGHT_SNOW = [(10, (200, 225, 235)), (28, (90, 170, 200)),
                    (42, (20, 90, 140)), (58, (10, 40, 80))]
_DUSK_DARK = [(10, (0, 94, 182)), (20, (0, 94, 182)), (25, (36, 88, 175)),
              (30, (142, 75, 155)), (35, (252, 83, 112)),
              (40, (255, 183, 110)), (45, (255, 253, 5)),
              (52, (255, 253, 5)), (62, (255, 255, 225))]
_DUSK_DARK_SNOW = [(10, (40, 70, 110)), (28, (90, 170, 200)),
                   (42, (180, 230, 240)), (58, (240, 255, 255))]

PALETTES = {
    # terminal: dusk's ladder, re-inked in the terminal's own colours
    "terminal": Palette(_themed_ramp(_DUSK_LIGHT),
                        _themed_ramp(_DUSK_LIGHT_SNOW),
                        _themed_ramp(_DUSK_DARK),
                        _themed_ramp(_DUSK_DARK_SNOW)),
    # embers: maroon → orange → yellow → white, for dark terminals
    "ember": Palette(
        _ramp([(10, (70, 20, 30)), (25, (160, 50, 30)), (40, (230, 130, 30)),
               (50, (250, 220, 90)), (60, (255, 255, 240))]),
        _ramp([(10, (80, 70, 110)), (30, (170, 160, 220)),
               (50, (240, 235, 255))])),
    # dusk: hue carries intensity — navy through violet and magenta to
    # coral and yellow, so a core is a different colour, not just a
    # brighter one.  The light-terminal twin starts pale and ends deep.
    "dusk": Palette(_ramp(_DUSK_LIGHT), _ramp(_DUSK_LIGHT_SNOW),
                    _ramp(_DUSK_DARK), _ramp(_DUSK_DARK_SNOW)),
    # marangai (te reo Māori: rainstorm): after MetService New Zealand's national radar.
    # Light rain walks green to orange, moderate jumps to the blues, heavy
    # to red and magenta, and hail is drawn in its own greens and pinks —
    # stepped, as they draw it.  Moderate begins at 19 dBZ (about half a
    # millimetre an hour), matched by eye against their map rather than
    # derived.  The light form deepens the top bands.
    "marangai": Palette(
        _steps([(10, (140, 170, 40)), (12, (190, 200, 30)),
                (14, (240, 220, 0)), (16, (250, 180, 0)),
                (18, (245, 120, 10)),
                (19, (20, 60, 170)), (23, (30, 110, 230)),
                (27, (40, 160, 240)), (31, (0, 180, 180)),
                (35, (210, 30, 20)), (39, (200, 20, 140)),
                (43, (130, 40, 170)), (47, (60, 20, 110)),
                (50, (0, 120, 40)), (55, (170, 20, 110))]),
        _steps([(10, (120, 160, 190)), (19, (40, 110, 160)),
                (35, (20, 60, 120)), (50, (60, 20, 110))]),
        _steps([(10, (120, 160, 40)), (12, (180, 200, 30)),
                (14, (240, 230, 0)), (16, (255, 190, 0)),
                (18, (255, 130, 20)),
                (19, (30, 70, 190)), (23, (40, 120, 240)),
                (27, (60, 180, 250)), (31, (20, 210, 210)),
                (35, (230, 40, 30)), (39, (220, 40, 160)),
                (43, (220, 150, 230)), (47, (245, 245, 255)),
                (50, (90, 220, 90)), (55, (250, 80, 200))]),
        _steps([(10, (150, 190, 220)), (19, (200, 225, 245)),
                (35, (235, 245, 255)), (50, (255, 255, 255))])),
    # ink: one blue, the quietest option — deepening on a light terminal,
    # brightening on a dark one, so the cores always lie furthest from
    # the page
    "ink": Palette(
        _ramp([(10, (190, 210, 235)), (25, (110, 150, 205)),
               (40, (40, 80, 160)), (55, (10, 25, 80)), (65, (0, 0, 30))]),
        _ramp([(10, (215, 200, 230)), (35, (150, 110, 190)),
               (55, (80, 30, 120))]),
        _ramp([(10, (30, 45, 90)), (25, (40, 80, 160)),
               (40, (110, 150, 205)), (55, (190, 210, 235)),
               (65, (240, 245, 255))]),
        _ramp([(10, (70, 40, 100)), (35, (150, 110, 190)),
               (55, (225, 205, 240))])),
}


def apply(rgba, palette):
    """Recolour a decoded scheme-0 frame in place through `palette`.

    Echoes below MIN_DBZ are cleared; everything else gets the palette's
    colour and a reflectivity-driven alpha (scaled by any coverage alpha
    the resample left on the pixel), so the result drops straight into
    build_radar_buffer like a server-coloured frame would.
    """
    cache = {}
    for i in range(0, len(rgba), 4):
        a = rgba[i + 3]
        if a == 0:
            continue
        gray = rgba[i]
        px = cache.get(gray)
        if px is None:
            dbz, snow = decode(gray)
            if dbz < MIN_DBZ:
                px = (0, 0, 0, 0)
            else:
                px = palette.colour(dbz, snow) + (_alpha(dbz),)
            cache[gray] = px
        rgba[i], rgba[i + 1], rgba[i + 2] = px[:3]
        rgba[i + 3] = px[3] * a // 255
    return rgba
