"""Labels and notices for weather's location picker."""

from linecast._i18n import LocaleTable, lookup

# Kept together so the menu, its keyboard help, and load notices agree.
_STRINGS = LocaleTable("LOCATIONS")


def ls(key, lang, **kwargs):
    return lookup(_STRINGS, key, lang, **kwargs)
