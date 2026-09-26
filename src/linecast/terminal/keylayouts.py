"""Keys typed under a non-Latin keyboard layout, read as the Latin keys they sit on.

With the Persian layout active, the key a US keyboard labels q types ض, and
linecast's single-letter keys would all go dead. `latin_key` maps a character
back to what US QWERTY puts on the same physical key: ض is q, й is q, ㅂ is q.
Shifted positions map to the capital or to the shifted US symbol (Persian ؟,
on the / key, is ?). Only non-ASCII characters are in the table; an ASCII
character keeps its own meaning even where a layout has moved it, so the
Hebrew layout's / on the q key, or Greek's ; there, cannot be told from the
real thing and is read as typed.

The rows below were generated from the X keyboard database, xkeyboard-config
2.48 (/usr/share/X11/xkb/symbols, keysyms resolved through X11/keysymdef.h),
by a throwaway script that followed each layout's includes, read the first two
levels of the keys <AE01>..<AE12>, <AD01>..<AD10>, <AC01>..<AC09>,
<AB01>..<AB07> and <AB10>, and lined them up against xkb's own us layout.
Each layout is its xkb default variant, plus Persian's Windows variant:
Persian is ir(pes), ISIRI 9147. xkb has no Korean letters (the jamo come from
the input method), so kr is the standard two-set Dubeolsik arrangement
(KS X 5002), written by hand; its shift doubles ㅂㅈㄷㄱㅅ and gives ㅒ ㅖ, and
leaves the other jamo as they were.

Layouts in the same script can put one character on different keys: Russian т
is on n, Serbian and Macedonian т is on t; Arabic ظ is on /, Persian ظ on z.
The layout in use settles it where it is known: the terminal's locale names
it (under sr_RS т is t, under fa_IR ظ is z; the locale is read as gettext
reads it, from LANGUAGE, LC_ALL, LC_MESSAGES, and LANG), or else linecast's
own language does. Where neither does, the layout more people type on wins,
since LAYOUTS is in order of use -- except that a character never quits when
another layout puts it on a key the views use: a key meant for something else
that closes the view is worse than one that does nothing. (Bulgarian й is on
x, which nothing uses, so й still quits for Russian and Ukrainian readers.)

A possible refinement: terminals that speak the kitty keyboard protocol can
report the base-layout key with each press (progressive enhancement flag 4,
"report alternate keys"), which is exact where it is available and needs no
table. Not implemented.
"""

import functools
import os
import re

# The US keys each column stands for, unshifted and shifted, in keyboard rows:
# digits, then the three letter rows, the last ending on the / key.
_KEYS = "1234567890-=" "qwertyuiop" "asdfghjkl" "zxcvbnm/"
_SHIFTED = "!@#$%^&*()_+" "QWERTYUIOP" "ASDFGHJKL" "ZXCVBNM?"

# Each layout: its unshifted row and its shifted row, column for column with
# the two above. Most-used first; the order settles conflicts.
LAYOUTS = {
    "ru": (  # Russian
        "1234567890-=" "йцукенгшщз" "фывапролд" "ячсмить.",
        "!\"№;%:?*()_+" "ЙЦУКЕНГШЩЗ" "ФЫВАПРОЛД" "ЯЧСМИТЬ,",
    ),
    "ara": (  # Arabic
        "1234567890-=" "ضصثقفغعهخح" "شسيبلاتنم" "ئءؤرﻻىةظ",
        "!@#$%^&*)(_+" "\u064e\u064b\u064f\u064cﻹإ`÷×؛" "\u0650\u064d][ﻷأـ،/" "~\u0652}{ﻵآ'؟",
    ),
    "ir(pes)": (  # Persian, ISIRI 9147
        "۱۲۳۴۵۶۷۸۹۰-=" "ضصثقفغعهخح" "شسیبلاتنم" "ظطزرذدپ/",
        "!٬٫﷼٪×،*)(ـ+" "\u0652\u064c\u064d\u064b\u064f\u0650\u064e\u0651]["
        "ؤئيإأآة»«" "ك\u0653ژ\u0670\u200c\u0654ء؟",
    ),
    "ir(winkeys)": (  # Persian, Windows
        "1234567890-=" "ضصثقفغعهخح" "شسیبلاتنم" "ظطزرذدئ/",
        "!@#$%^&*)(_+" "\u064b\u064c\u064d﷼،؛,][\\" "\u064e\u064f\u0650\u0651ۀآـ«»" "ةيژؤأإء؟",
    ),
    "ua": (  # Ukrainian
        "1234567890-=" "йцукенгшщз" "фівапролд" "ячсмить.",
        "!\"№;%:?*()_+" "ЙЦУКЕНГШЩЗ" "ФІВАПРОЛД" "ЯЧСМИТЬ,",
    ),
    "th": (  # Thai, Kedmanee
        "ๅ/-ภถ\u0e38\u0e36คตจขช" "ๆไำพะ\u0e31\u0e35รนย"
        "ฟหกดเ\u0e49\u0e48าส" "ผปแอ\u0e34\u0e37ทฝ",
        "+๑๒๓๔\u0e39฿๕๖๗๘๙" "๐\"ฎฑธ\u0e4d\u0e4aณฯญ" "ฤฆฏโฌ\u0e47\u0e4bษศ" "()ฉฮ\u0e3a\u0e4c?ฦ",
    ),
    "kr": (  # Korean, Dubeolsik
        "1234567890-=" "ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔ" "ㅁㄴㅇㄹㅎㅗㅓㅏㅣ" "ㅋㅌㅊㅍㅠㅜㅡ/",
        "!@#$%^&*()_+" "ㅃㅉㄸㄲㅆㅛㅕㅑㅒㅖ" "ㅁㄴㅇㄹㅎㅗㅓㅏㅣ" "ㅋㅌㅊㅍㅠㅜㅡ?",
    ),
    # Greek shifts both ς and σ to Σ; the row keeps it on S alone (W marks
    # the gap: an ASCII character is never an entry).
    "gr": (  # Greek
        "1234567890-=" ";ςερτυθιοπ" "ασδφγηξκλ" "ζχψωβνμ/",
        "!@#$%^&*()_+" ":WΕΡΤΥΘΙΟΠ" "ΑΣΔΦΓΗΞΚΛ" "ΖΧΨΩΒΝΜ?",
    ),
    "il": (  # Hebrew
        "1234567890-=" "/'קראטוןםפ" "שדגכעיחלך" "זסבהנמצ.",
        "!@#$%^&*)(_+" "QWERTYUIOP" "ASDFGHJKL" "ZXCVBNM?",
    ),
    "pk": (  # Urdu, phonetic
        "1234567890-=" "قوعرتےءیہپ" "اسدفگحجکل" "زشچطبنم/",
        "!@#$%^&*)(_+" "\u0652ؤ\u0670ڑٹ\u064eئ\u0650ۃ\u064f"
        "آصڈ\u0651غھضخ\u0654" "ذژثظ.ں\u0658؟",
    ),
    "bg": (  # Bulgarian, BDS
        "1234567890-." ",уеишщксдз" "ьяаожгтнв" "юйъэфхпб",
        "!?+\"%=:/–№$€" "ыУЕИШЩКСДЗ" "ѝЯАОЖГТНВ" "ЮЙЪЭФХПБ",
    ),
    "by": (  # Belarusian
        "1234567890-=" "йцукенгшўз" "фывапролд" "ячсміть.",
        "!\"№;%:?*()_+" "ЙЦУКЕНГШЎЗ" "ФЫВАПРОЛД" "ЯЧСМІТЬ,",
    ),
    "rs": (  # Serbian, Cyrillic
        "1234567890'+" "љњертзуиоп" "асдфгхјкл" "жџцвбнм-",
        "!\"#$%&/()=?*" "ЉЊЕРТЗУИОП" "АСДФГХЈКЛ" "ЖЏЦВБНМ_",
    ),
    "ge": (  # Georgian
        "1234567890-=" "ქწერტყუიოპ" "ასდფგჰჯკლ" "ზხცვბნმ/",
        "!@#$%^&*()_+" "QჭEღთYUIOP" "AშDFGHჟKL" "ძXჩVBNM?",
    ),
    "am": (  # Armenian
        "ֆձ֊,։՞․՛)օէղ" "ճփբսմուկըթ" "ջվգեանիտհ" "ժդչյզլքռ",
        "ՖՁ—$…%և՚(ՕԷՂ" "ՃՓԲՍՄՈՒԿԸԹ" "ՋՎԳԵԱՆԻՏՀ" "ԺԴՉՅԶԼՔՌ",
    ),
    "mk": (  # Macedonian
        "1234567890-=" "љњертѕуиоп" "асдфгхјкл" "зџцвбнм/",
        "!„“$%^&*()_+" "ЉЊЕРТЅУИОП" "АСДФГХЈКЛ" "ЗЏЦВБНМ?",
    ),
}

# The layouts a locale's language moves to the front, in its own order.
LOCALE_LAYOUTS = {
    "ar": ("ara",), "be": ("by",), "bg": ("bg",), "el": ("gr",),
    "fa": ("ir(pes)", "ir(winkeys)"), "he": ("il",), "hy": ("am",), "iw": ("il",),
    "ka": ("ge",), "ko": ("kr",), "mk": ("mk",), "ru": ("ru",), "sr": ("rs",),
    "th": ("th",), "uk": ("ua",), "ur": ("pk",),
}

# The locale variables, in the order gettext consults them.
_LOCALE_VARS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")


def _entries(name):
    for row, keys in zip(LAYOUTS[name], (_KEYS, _SHIFTED)):
        for ch, key in zip(row, keys):
            if not ch.isascii():
                yield ch, key


# The keys linecast's views answer to (terminal.live._read_key).
_BOUND = frozenset("qQoOnN+=-_tTcCwasdWSDvVpPlLmMyYrR/?0123456789")


@functools.lru_cache(maxsize=None)
def table(first=()):
    """Character -> US key, the layouts in `first` ahead of the rest,
    which take a disputed character in order of use unless it would quit."""
    out = {}
    for name in first:
        for ch, key in _entries(name):
            out.setdefault(ch, key)
    keys = {}
    for name in LAYOUTS:
        for ch, key in _entries(name):
            keys.setdefault(ch, []).append(key)
    for ch, found in keys.items():
        if ch in out:
            continue
        # A character the first layout puts on q, which another puts on
        # a key the views use: pressed there on purpose, it would quit
        if found[0] in "qQ" and any(key in _BOUND for key in found[1:]
                                    if key not in "qQ"):
            continue
        out[ch] = found[0]
    return out


def locale_layouts(environ=None):
    """The layouts the locale's language puts first, or () for none.

    The first locale variable that names a language decides; "C" and
    "POSIX" name none and are passed over.
    """
    env = os.environ if environ is None else environ
    for var in _LOCALE_VARS:
        for value in env.get(var, "").split(":"):
            m = re.match(r"[a-z]+", value.strip().lower())
            if m and len(m.group()) >= 2 and m.group() != "posix":
                return LOCALE_LAYOUTS.get(m.group(), ())
    return ()


def _language_layouts():
    """The layouts linecast's own language points to, when the locale
    names none: a Persian reader with an English locale types Persian."""
    try:
        from linecast._i18n import base_language
        from linecast._runtime import current_runtime
        lang = base_language(getattr(current_runtime(), "lang", "en"))
    except Exception:
        return ()
    return LOCALE_LAYOUTS.get(lang.split("-")[0], ())


def latin_key(ch, environ=None):
    """The US key a layout puts `ch` on, or None when no layout here has
    it, or when layouts disagree and none of them is known to be in use."""
    if ch.isascii():
        return None
    first = locale_layouts(environ) or _language_layouts()
    return table(first).get(ch)
