"""The lookup shared by the per-command string tables.

Each command keeps its own table, {lang: {key: text}}; this module holds
the one way of reading them, so the fallback order lives in one place.
"""

# The languages linecast speaks, as (code, English name), in the order the
# README lists them. Every per-command table has an entry for each; the
# `linecast language` command and the help page take their list from here.
LANGUAGES = (
    ("en", "English"), ("fr", "French"), ("es", "Spanish"), ("de", "German"),
    ("it", "Italian"), ("pt", "Portuguese"), ("nl", "Dutch"), ("pl", "Polish"),
    ("no", "Norwegian"), ("sv", "Swedish"), ("is", "Icelandic"), ("da", "Danish"),
    ("fi", "Finnish"), ("ja", "Japanese"), ("ko", "Korean"), ("zh", "Chinese"),
    ("th", "Thai"), ("id", "Indonesian"),
)
LANGUAGE_CODES = tuple(code for code, _name in LANGUAGES)
LANGUAGE_NAMES = dict(LANGUAGES)


def is_language_code(value):
    """A two-letter code, whether or not linecast has strings for it: an
    unlisted one leaves the app in English and still reaches the providers
    that publish in it, as India's alerts do."""
    return isinstance(value, str) and len(value) == 2 and value.isalpha()


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
