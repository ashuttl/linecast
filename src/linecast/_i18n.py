"""The lookup shared by the per-command string tables.

Each command keeps its own table, {lang: {key: text}}; this module holds
the one way of reading them, so the fallback order lives in one place.
"""


def lang_of(runtime):
    """The runtime's language, or English when there is no runtime."""
    return getattr(runtime, "lang", "en") if runtime else "en"


def lookup(table, key, lang, **kwargs):
    """The text for `key` in `lang`, falling back to English and then to
    the key itself.  Formatted with kwargs only when some are given, so a
    text with literal braces survives a plain lookup."""
    english = table["en"]
    text = table.get(lang, english).get(key, english.get(key, key))
    return text.format(**kwargs) if kwargs else text
