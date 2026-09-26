"""The sun and moon glyphs in each icon set: nerd, emoji, and plain."""


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
