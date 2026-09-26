"""Tides localization strings."""

from linecast._i18n import LocaleTable, lang_of, lookup, table_for

_TIDES_STRINGS = LocaleTable("TIDES")



MOON_NAMES_I18N = LocaleTable("MOON_PHASES")


def _moon_name(idx, runtime):
    """Return a localized moon phase name for the given index (0-7)."""
    names = table_for(MOON_NAMES_I18N, lang_of(runtime))
    return names[idx]


def _ts(key, runtime, **kwargs):
    """Look up a tides-specific localized string."""
    return lookup(_TIDES_STRINGS, key, lang_of(runtime), **kwargs)
