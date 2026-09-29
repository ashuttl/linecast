"""Descriptions for the shared live-view help panel."""

from linecast._i18n import LocaleTable, lookup

_STRINGS = LocaleTable("HELP")


def hs(key, lang):
    return lookup(_STRINGS, key, lang)


def is_help_word(key):
    """Whether *key* is one of the panel's shared words, which English,
    holding every key, says."""
    return key in _STRINGS["en"]
