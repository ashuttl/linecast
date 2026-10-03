"""The sun and moon glyphs in each icon set: nerd, emoji, and plain, and
the arrows that point the eight ways."""

from linecast._geo import octant

# One arrow for each of the eight ways, from north clockwise.
ARROWS = "↑↗→↘↓↙←↖"


def arrow_toward(bearing):
    """The arrow pointing the way of *bearing*, in degrees clockwise from
    north. A wind is named for where it comes from, so it points toward
    its direction and a half turn."""
    return ARROWS[octant(bearing)]


_EMOJI_ICONS = {
    "sun_char": "\u25cf",         # ●
    "sun_icon": "\U0001f305",     # 🌅
    "sunset_icon": "\U0001f307",  # 🌇
    "moon_icons": [
        "\U0001f311",  # 🌑 New Moon
        "\U0001f312",  # 🌒 Waxing Crescent
        "\U0001f313",  # 🌓 First Quarter
        "\U0001f314",  # 🌔 Waxing Gibbous
        "\U0001f315",  # 🌕 Full Moon
        "\U0001f316",  # 🌖 Waning Gibbous
        "\U0001f317",  # 🌗 Last Quarter
        "\U0001f318",  # 🌘 Waning Crescent
    ],
}

_NERD_ICONS = {
    "sun_char": "\U000F0F62",      # 󰽢
    "sun_icon": "\U000F059C",      # 󰖜
    "sunset_icon": "\U000F059B",   # 󰖛
    "moon_icons": [
        "\U000F0F64",  # New Moon
        "\U000F0F67",  # Waxing Crescent
        "\U000F0F61",  # First Quarter
        "\U000F0F68",  # Waxing Gibbous
        "\U000F0F62",  # Full Moon
        "\U000F0F66",  # Waning Gibbous
        "\U000F0F63",  # Last Quarter
        "\U000F0F65",  # Waning Crescent
    ],
}


# Text-presentation glyphs only: the phase dial ○ ◔ ◑ ◕ ● loses the
# waxing/waning mirror, but every font can draw it.
_PLAIN_ICONS = {
    "sun_char": "●",
    "sun_icon": "↑",
    "sunset_icon": "↓",
    "moon_icons": [
        "○",  # New Moon
        "◔",  # Waxing Crescent
        "◑",  # First Quarter
        "◕",  # Waxing Gibbous
        "●",  # Full Moon
        "◕",  # Waning Gibbous
        "◑",  # Last Quarter
        "◔",  # Waning Crescent
    ],
}


def _icon_set(runtime):
    return {"nerd": _NERD_ICONS, "emoji": _EMOJI_ICONS,
            "plain": _PLAIN_ICONS}[runtime.icons]


def moon_icon(index, runtime, *, bg_color=None):
    """A phase glyph for its drawing surface; None keeps the named icon.

    Nerd Font moons paint the lit part in the foreground. On a light
    surface the ink is the shadow instead: the opposite phase supplies
    its shape, preserving the side that is lit. Emoji carry their own
    colors, and the plain set is a dial showing the fraction filled.
    """
    if runtime.icons == "nerd" and bg_color is not None:
        from linecast.terminal.theme import is_light_theme
        if is_light_theme(bg_color):
            index = (index + 4) % 8
    return _icon_set(runtime)["moon_icons"][index]
