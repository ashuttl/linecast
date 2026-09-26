"""Sky command localization strings.

The constellation names and the star names come with the catalogue (see
catalogue), in each language where it has its own; the compass
points are the radar's, and the twilight names the sunshine view's. What
is left is the Sun, the Moon, the planets, the cultures' titles, and a
few phrases.
"""

from linecast._i18n import LocaleTable, lang_of, lookup

_SKY_STRINGS = LocaleTable("SKY")


# The cultures' titles, for the status line, the culture command, and the
# search panel, keyed by the short name `linecast culture` takes.
# Stellarium's data gives each culture an English title; the locale
# files give the other languages'.
_CULTURES = LocaleTable("SKY_CULTURES")


def culture_title_text(short, lang):
    """The culture's title in `lang`, falling back to English, or None
    for a culture the table does not know."""
    if short not in _CULTURES["en"]:
        return None
    return lookup(_CULTURES, short, lang)


def _sk(key, runtime, **kwargs):
    return lookup(_SKY_STRINGS, key, lang_of(runtime), **kwargs)


def body_name(key, runtime):
    """The Sun, the Moon, or a planet by its key, in the display language."""
    return _sk(key, runtime)
