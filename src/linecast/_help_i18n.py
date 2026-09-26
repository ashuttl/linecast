"""Descriptions for the shared live-view help panel."""

from linecast._i18n import LocaleTable, lookup

_STRINGS = LocaleTable("HELP")


def hs(key, lang):
    return lookup(_STRINGS, key, lang)
