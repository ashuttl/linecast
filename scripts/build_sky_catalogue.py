"""Bake the sky: the star catalogue, the constellations, and the Milky Way.

The sky view and the moon view share one set of stars, the Yale Bright
Star Catalogue, 5th revised edition (Hoffleit & Warren, 1991), as served
by the Harvard-Smithsonian Center for Astrophysics. The constellation
figures, the constellation names in many languages, and the star names
are Olaf Frohn's d3-celestial data files (BSD licence), which draw on the
IAU's lists. Wikidata's labels (CC0) give the constellation and star
names in the languages those files lack, and fill their gaps. The Milky
Way is the diffuse layer of NASA's Deep Star Maps 2020 (Scientific
Visualization Studio, public domain), the unresolved starlight of the
Galaxy drawn from Gaia with the dust lanes in it, as an equirectangular
map in celestial coordinates.

    uv run scripts/build_sky_catalogue.py [--from DIR]

The Milky Way step needs ImageMagick (`magick`) to read the EXR.

The sky cultures are Stellarium's collection (github.com/Stellarium/
stellarium-skycultures), the ones whose text and lines are under a
Creative Commons licence that allows redistribution and derived work
(CC BY or CC BY-SA); the no-derivatives, non-commercial and GPL ones are
left out. Their figures name stars by Hipparcos number, so the bake also
reads the Hipparcos main catalogue (CDS I/239) for positions, and
matches Hipparcos stars to ours by HD number for the star names.

- cultures.json.gz: one record per culture with its id, title, region,
  native language, credits and licence, the constellations (english and
  native names, the IAU code where the culture keeps the IAU figures,
  the label position, and the figure as polylines of [ra, dec] in
  hundredths of a degree), the star names by index into stars.bin, and
  the native names again in another script where the culture has one
  (the Chinese sky in the traditional characters, under "zh-Hant").

Writes three files under src/linecast/data/:

- stars.bin: one six-byte record per star to visual magnitude 6.5,
  brightest first — right ascension and declination (J2000) in hundredths
  of a degree as little-endian uint16 and int16, the magnitude in tenths
  as int8, and the B−V colour index in fiftieths as int8.
- sky.json.gz: {"names": [[index, name, designation, {lang: name}], …]
  for every star with a proper name or a Bayer or Flamsteed designation,
  indexed into stars.bin, the last element only where a language names
  the star differently from the IAU; "constellations": one record per constellation with its IAU
  abbreviation, Latin name and genitive, label position, names in the
  languages linecast speaks where they differ from the Latin, and its
  figure as polylines of [ra, dec] in hundredths of a degree}.
- milkyway.bin.gz: a 1080×540 byte raster of the Milky Way's brightness
  in celestial coordinates, right ascension 0h at the centre increasing
  to the left (as the sky is seen from inside), declination +90° at the
  top: the NASA layer downsampled, with the sky's own floor taken off
  and a gamma that keeps the dust lanes legible beside the bulge.

`--from DIR` reads the source files from a directory instead of
downloading them, and keeps Wikidata's answers there too, so a rerun is
offline. The outputs are committed; this script reruns only if the
sources do.
"""

import csv
import gzip
import io
import json
import math
import re
import struct
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BSC_URL = "http://tdc-www.harvard.edu/catalogs/bsc5.dat.gz"
CELESTIAL = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/"
MILKY_WAY_URL = ("https://svs.gsfc.nasa.gov/vis/a000000/a004800/a004851/"
                 "milkyway_2020_4k.exr")
HIPPARCOS_URL = "https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat"
SKYCULTURES = "https://raw.githubusercontent.com/Stellarium/stellarium-skycultures/master/"

# The cultures shipped, by Stellarium's directory name: every one whose
# text and lines the collection puts under CC BY or CC BY-SA.
CULTURES = (
    "anutan", "belarusian", "blackfoot", "boorong", "bugis", "chinese",
    "chinese_contemporary", "hawaiian_starlines", "indian",
    "japanese_moon_stations", "mandar", "maori", "mongolian", "norse",
    "romanian", "ruelle", "sami", "siberian", "tongan", "tukano",
    "western_SnT", "western_rey",
)
LIMIT = 6.5
DATA = Path(__file__).resolve().parent.parent / "src/linecast/data"

# The languages linecast speaks that the d3-celestial data names.
OUR_LANGS = ("fr", "es", "de", "it", "fi", "ja", "ko", "zh")
# Every language linecast speaks but English and Traditional Chinese, and
# the Wikidata label language behind each: Norwegian is filed as Bokmål,
# and "zh" is the simplified script. Traditional Chinese is not asked for:
# Wikidata labels a sixth of the constellations and few of the stars in
# it, so its names are the simplified ones written in the traditional
# characters (see TRADITIONAL below), and the constellations an OVERRIDES
# table checked against the Chinese Wikipedia's zh-tw titles.
WIKIDATA = "https://query.wikidata.org/sparql"
WIKIDATA_LANG = {
    "fr": "fr", "es": "es", "de": "de", "it": "it", "pt": "pt", "nl": "nl",
    "pl": "pl", "no": "nb", "sv": "sv", "is": "is", "da": "da", "fi": "fi",
    "ja": "ja", "ko": "ko", "zh": "zh-hans", "th": "th", "id": "id", "uk": "uk",
    "vi": "vi", "eo": "eo", "tr": "tr", "ru": "ru", "ro": "ro", "cs": "cs", "el": "el",
    "fa": "fa",
}

# The traditional form of each simplified character the Chinese names use,
# as Stellarium's zh_TW translation of the Chinese sky culture and the
# Chinese Wikipedia's zh-tw titles write them: 鉤 and 衛 in Taiwan's
# forms, 積屍 as the modern texts have it. 台 is the same character in
# both scripts in 三台 and its steps but 臺 in the terraces 漸臺 and 靈臺,
# so those two are whole-word rules; 尸, 斗, 咸, 床, and 杠 in these names
# are the same character in both scripts, and the 里 of a transliteration
# (葛羅姆布里吉) stays a 里. The axe 鈇 is 𫓧 in the simplified index. Any
# other character passes through unchanged.
TRADITIONAL_WORDS = {"渐台": "漸臺", "灵台": "靈臺", "积尸": "積屍"}
TRADITIONAL = str.maketrans(
    "万东乌书云从仓传关内军农刍势华卫厕厨厩参吴园国坟垒夹娄孙宝宫将尔师库廪开异张执摄摇"
    "晋权极枢枪楼毕渊渎渐灵玑电盖砺禄离积红纪纲纳织罗罚节虚记说诸谒谗贤败贯贲赵车轩轸辅"
    "辇辐辕辖进郑钤钩钱钺锧键长门闭间阁阙阳阴阵阶陈雳韩顽顿飞马骑鱼鳖鸟鸡鹤齐龟𫓧",
    "萬東烏書雲從倉傳關內軍農芻勢華衛廁廚廄參吳園國墳壘夾婁孫寶宮將爾師庫廩開異張執攝搖"
    "晉權極樞槍樓畢淵瀆漸靈璣電蓋礪祿離積紅紀綱納織羅罰節虛記說諸謁讒賢敗貫賁趙車軒軫輔"
    "輦輻轅轄進鄭鈐鉤錢鉞鑕鍵長門閉間閣闕陽陰陣階陳靂韓頑頓飛馬騎魚鱉鳥雞鶴齊龜鈇",
)


def traditional(text):
    """`text`, a Chinese name in the simplified script, in the traditional."""
    for word, hant in TRADITIONAL_WORDS.items():
        text = text.replace(word, hant)
    return text.translate(TRADITIONAL)

GREEK = {
    "Alp": "α", "Bet": "β", "Gam": "γ", "Del": "δ", "Eps": "ε", "Zet": "ζ",
    "Eta": "η", "The": "θ", "Iot": "ι", "Kap": "κ", "Lam": "λ", "Mu": "μ",
    "Nu": "ν", "Xi": "ξ", "Omi": "ο", "Pi": "π", "Rho": "ρ", "Sig": "σ",
    "Tau": "τ", "Ups": "υ", "Phi": "φ", "Chi": "χ", "Psi": "ψ", "Ome": "ω",
}
SUPERSCRIPT = {"1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
               "7": "⁷", "8": "⁸", "9": "⁹"}

MW_W, MW_H = 1080, 540


def fetch(name, src):
    if src is not None:
        return (src / name).read_bytes()
    url = {"bsc5.dat.gz": BSC_URL, "milkyway_2020_4k.exr": MILKY_WAY_URL,
           "hip_main.dat": HIPPARCOS_URL}.get(name, CELESTIAL + name)
    if name.startswith("sc/"):
        culture, _, filename = name[3:].partition(".")
        if filename.endswith(".po"):
            url = f"{SKYCULTURES}{culture}/po/{filename}"
        else:
            url = (f"{SKYCULTURES}{culture}/"
                   f"{'index.json' if filename == 'json' else 'description.md'}")
    print(f"fetching {url}")
    return urllib.request.urlopen(url).read()


def fetch_wikidata(name, query, src):
    """Wikidata's answer to a SPARQL query, as CSV: from the source
    directory when it has one, else asked, and kept there for next time."""
    if src is not None and (src / name).exists():
        return (src / name).read_text(encoding="utf-8")
    print(f"asking Wikidata for {name}")
    request = urllib.request.Request(
        WIKIDATA, data=urllib.parse.urlencode({"query": query}).encode(),
        headers={"Accept": "text/csv",
                 "User-Agent": "linecast-bake/1 (https://github.com/ashuttl/linecast)"})
    text = urllib.request.urlopen(request, timeout=300).read().decode("utf-8")
    if src is not None:
        (src / name).write_text(text, encoding="utf-8")
    return text


def wikidata_rows(name, query, src):
    return list(csv.DictReader(io.StringIO(fetch_wikidata(name, query, src))))


# ---------------------------------------------------------------------------
# Stars
# ---------------------------------------------------------------------------
def parse_star(line):
    """A star from a catalogue line, or None if it has no position.

    Fixed columns (1-based) per the catalogue's ReadMe: HR 1-4, Name 5-14
    (Flamsteed 5-7, Bayer 8-10, superscript 11, constellation 12-14),
    HD 26-31, RAh 76-77, RAm 78-79, RAs 80-83, DE- 84, DEd 85-86, DEm
    87-88, DEs 89-90, Vmag 103-107, B-V 110-114. A few entries (novae,
    clusters) have no position.
    """
    try:
        hr = int(line[0:4])
        ra = (int(line[75:77]) + int(line[77:79]) / 60.0
              + float(line[79:83]) / 3600.0) * 15.0
        dec = (int(line[84:86]) + int(line[86:88]) / 60.0
               + int(line[88:90]) / 3600.0)
        if line[83] == "-":
            dec = -dec
        vmag = float(line[102:107])
    except ValueError:
        return None
    try:
        bv = float(line[109:114])
    except ValueError:
        bv = 0.0
    try:
        hd = int(line[25:31])
    except ValueError:
        hd = None
    flam = line[4:7].strip()
    bayer = GREEK.get(line[7:10].strip())
    sup = SUPERSCRIPT.get(line[10], "")
    con = line[11:14].strip()
    desig = ""
    if con and bayer:
        desig = f"{bayer}{sup} {con}"
    elif con and flam:
        desig = f"{flam} {con}"
    return dict(hr=hr, ra=ra, dec=dec, vmag=vmag, bv=bv, hd=hd, desig=desig)


def bake_stars(src):
    raw = gzip.decompress(fetch("bsc5.dat.gz", src))
    stars = [s for s in map(parse_star, raw.decode("latin-1").splitlines())
             if s is not None and s["vmag"] <= LIMIT]
    stars.sort(key=lambda s: (s["vmag"], s["hr"]))
    out = DATA / "stars.bin"
    out.write_bytes(b"".join(
        struct.pack("<Hhbb", round(s["ra"] * 100) % 36000, round(s["dec"] * 100),
                    round(s["vmag"] * 10),
                    max(-128, min(127, round(s["bv"] * 50))))
        for s in stars))
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(stars)} stars to {LIMIT})")
    return stars


GREEK_WORDS = (
    "alpha", "alfa", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi", "rho", "sigma",
    "tau", "upsilon", "phi", "chi", "psi", "omega",
    # The Cyrillic spellings, as Ukrainian titles its stars.
    "альфа", "бета", "гамма", "дельта", "епсилон", "дзета", "зета", "ета", "тета",
    "йота", "каппа", "лямбда", "мю", "ню", "ксі", "омікрон", "пі", "ро", "сигма",
    "тау", "іпсилон", "упсилон", "фі", "хі", "псі", "омега",
    # The Esperanto spellings, as Esperanto titles its stars ("Gama de
    # Kruco", "Epsilono de Oriono", "Alfo Karena").
    "alfo", "beto", "gamo", "gama", "delto", "epsilono", "zeto", "eto", "teto", "teta",
    "joto", "kapo", "kapa", "lambdo", "muo", "nuo", "ksio", "omikrono", "omikron", "pio",
    "roo", "sigmo", "taŭo", "taŭ", "upsilono", "fio", "ĥio", "psio", "omego",
    # The Turkish spellings ("Alfa Centauri", "Gama Crucis").
    "gama", "epsilon", "teta", "kapa", "mü", "nü", "ksi", "omikron", "ro", "ipsilon",
    "fi", "ki", "omega",
    # The Russian spellings, where they differ from the Ukrainian ("эта
    # Кассиопеи", "эпсилон Эридана", "кси Персея").
    "эпсилон", "эта", "кси", "омикрон", "пи", "ипсилон", "фи", "хи", "пси",
    # The Czech spellings ("Mý Cephei", "Éta Ursae Minoris", "Théta Pegasi").
    "zéta", "éta", "théta", "ióta", "mý", "ný", "ksí", "pí", "ró", "ypsilon", "fí",
    "chí", "psí",
    # The Romanian spellings ("Teta Scorpii", "Gama Boötis").
    "miu", "niu", "csi", "hi",
    # The Persian spellings ("آلفا طاووس", "لاندا کژدم", "امیکرون شیر"),
    # with the Latin letters of a variable star's designation as Persian
    # spells them ("آر تاج شمالی", "دبلیو کمان").
    "آلفا", "بتا", "گاما", "دلتا", "اپسیلون", "زتا", "اتا", "تتا", "یوتا", "آیوتا",
    "کاپا", "لاندا", "لامبدا", "مو", "نو", "کسی", "امیکرون", "اومیکرون", "پی", "رو",
    "سیگما", "تاو", "اوپسیلون", "فی", "خی", "پسی", "سای", "امگا",
    "آر", "جی", "کا", "دبلیو",
)
GREEK_LETTERS = "αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
# A variable star's designation: one or two capitals before the genitive.
VARIABLE_PREFIX = re.compile(r"^[A-Z]{1,2} ")
CATALOGUE_PREFIX = re.compile(r"^(hd|hip|hr|gj|gliese|sao|bd|cd|lhs|wolf|ross|luyten)", re.I)


def chart_name(label, iau, genitives, component):
    """A Wikidata label as a chart would print it, or None where the label
    is not a name: the IAU's name again, a Bayer or Flamsteed or catalogue
    designation in the language's spelling (any constellation's genitive
    marks one), or anything with a number in it. `component` says
    Wikidata's item is the bright component of a pair (its English label
    is the name and an A), so a trailing A comes off in every language."""
    text = re.sub(r"\s*\(.*?\)\s*$", "", label).strip()
    if component and len(text) > 1 and text.endswith("A"):
        text = text[:-1].rstrip()
    low = text.lower()
    if not text or text == iau or any(ch.isdigit() for ch in text):
        return None
    if any(genitive.lower() in low for genitive in genitives):
        return None
    # Turkish Wikidata describes some stars in place of naming them
    # ("Kuğu takımyıldızında yıldız", a star in Cygnus).
    if "takımyıldız" in low:
        return None
    if any(low == word or low.startswith(word + " ") for word in GREEK_WORDS):
        return None
    if any(ch in GREEK_LETTERS for ch in text) or CATALOGUE_PREFIX.match(text):
        return None
    if VARIABLE_PREFIX.match(text):
        return None
    return text


def bake_names(stars, genitives, src):
    """[[index, proper name, designation, {lang: name}], …] for the stars
    that have a name or a designation; the names in other languages from
    d3-celestial first and Wikidata behind it, only where they differ from
    the IAU's name, with OVERRIDES the last word."""
    by_hd = {}
    for entry in json.loads(fetch("starnames.json", src)).values():
        hd = entry.get("hd", "").replace("HD", "").replace(" ", "").strip()
        if hd.isdigit() and entry.get("name"):
            by_hd[int(hd)] = entry
    named = sorted({s["hd"] for s in stars if s["hd"] is not None and s["hd"] in by_hd})
    codes = " ".join(f'"HD {hd}"' for hd in named)
    langs = ", ".join(f'"{code}"' for code in sorted({*WIKIDATA_LANG.values(), "en"}))
    rows = wikidata_rows("wikidata_stars.csv", (
        "SELECT ?code ?lang ?l WHERE { VALUES ?code { " + codes + " } "
        "?item wdt:P528 ?code; rdfs:label ?l . BIND(LANG(?l) AS ?lang) "
        "FILTER(?lang IN (" + langs + ")) }"), src)
    labels = {}
    for row in rows:
        labels.setdefault(int(row["code"][3:]), {})[row["lang"]] = row["l"]
    names = []
    counts = {lang: 0 for lang in (*WIKIDATA_LANG, "zh-Hant")}
    for i, s in enumerate(stars):
        entry = by_hd.get(s["hd"]) if s["hd"] is not None else None
        proper = entry["name"] if entry else ""
        if not proper and not s["desig"]:
            continue
        record = [i, proper, s["desig"]]
        if proper:
            found = labels.get(s["hd"], {})
            component = found.get("en", "") == f"{proper} A"
            translated = {}
            for lang, wd_lang in WIKIDATA_LANG.items():
                text = entry.get(lang, "") if lang in OUR_LANGS else ""
                if not text and wd_lang in found:
                    text = chart_name(found[wd_lang], proper, genitives, component)
                mine = OVERRIDES["stars"].get(lang, {})
                text = mine.get(s["desig"] or "-", mine.get(proper, text))
                if text and text != proper:
                    translated[lang] = text
                    counts[lang] += 1
            # The traditional script writes the same Chinese name.
            mine = OVERRIDES["stars"]["zh-Hant"]
            text = mine.get(s["desig"] or "-",
                            mine.get(proper, traditional(translated.get("zh", ""))))
            if text and text != proper:
                translated["zh-Hant"] = text
                counts["zh-Hant"] += 1
            if translated:
                record.append(translated)
        names.append(record)
    print(f"  {sum(1 for n in names if n[1])} named stars, "
          f"{len(names)} with a designation; names in other languages: "
          + ", ".join(f"{lang} {n}" for lang, n in counts.items()))
    return names


# ---------------------------------------------------------------------------
# Names in other languages
# ---------------------------------------------------------------------------
# Where neither source has the name a chart in the language would print:
# Wikidata's label may be a phrase, a designation, or missing. Keyed by
# language, then by the IAU star name or the constellation's abbreviation;
# a star entry keyed by designation ("ζ Cen") names one star where the
# data gives two the same IAU name. An empty string keeps the IAU's or
# the Latin name. Each language was reviewed against its Wikipedia.
OVERRIDES = {
    "stars": {
        "da": {
            "Diphda": "", "Marfak": "", "Pearce's Star": "",
        },
        "de": {
            "Abt's Star": "", "Acrux": "", "Adhafera": "", "Algedi": "Algiedi", "Alnair": "",
            "Imai": "", "Mimosa": "",
            "Alpherg": "", "Alrescha": "Alrischa", "Alshain": "Alschain", "Aludra": "",
            "Andrews' star": "", "Aspidiske": "", "Avior": "", "Becklin's Star": "",
            "Bidelman's Helium Variable Star": "", "Biham": "", "Double Double": "",
            "Fuyue": "", "Grafias": "", "Kurhah": "Alkurah", "Meissa": "", "Pearce's Star": "",
            "Persian": "", "Plaskett's Star": "", "Rasalgethi": "Ras Algethi",
            "Revenant of the Swan": "", "Saclateni": "", "Saik": "", "Sargas": "",
            "Secunda Hyadum": "", "Shedar": "Schedir", "Sualocin": "",
            "Variabilis Coronae": "", "Zubenelgenubi": "Zuben-el-dschenubi",
            "Zubenelhakrabi": "",
        },
        "es": {
            "Acrux": "Ácrux", "Alderamin": "", "Algedi": "Al Giedi", "Alkaphrah": "",
            "Imai": "", "Mimosa": "",
            "Altair": "Altaír", "Andrews' star": "Estrella de Andrews",
            "Athebyne": "Aldhibain", "Bidelman's Helium Variable Star": "", "Brachium": "",
            "Castor": "Cástor", "Chara": "", "Copernicus": "Copérnico", "Double Double": "",
            "Fuyue": "", "Ginan": "", "Grafias": "", "Markeb": "", "Merope": "", "Polis": "",
            "Rasalgethi": "Ras Algethi", "Revenant of the Swan": "", "Sterope": "",
            "Taiyangshou": "", "The Garnet Star": "Estrella Granate", "The Ruby Star": "",
            "Variabilis Coronae": "",
        },
        "fi": {
            "Achird": "", "Double Double": "", "La Superba": "", "Persian": "",
            "Revenant of the Swan": "",
        },
        "fr": {
            "Ain": "", "Albireo": "Albiréo", "Alshain": "", "Altais": "",
            "Bidelman's Helium Variable Star": "", "Celaeno": "Céléno", "Dubhe": "Dubhé",
            "Fuyue": "", "Grafias": "", "Pearce's Star": "", "Polaris": "Étoile polaire",
            "Regulus": "Régulus", "Revenant of the Swan": "",
            "The Garnet Star": "Étoile Grenat", "The Ruby Star": "", "Variabilis Coronae": "",
        },
        "id": {
            "Pearce's Star": "",
        },
        "is": {
            "Merope": "", "Pollux": "Pollúx", "Rigel": "Rígel", "Sirius": "Síríus",
        },
        "it": {
            "Alcyone": "", "Alphecca": "Gemma", "Atik": "", "Atlas": "", "Brachium": "",
            "Copernicus": "", "Diadem": "Diadema", "Fuyue": "", "Kaus Australis": "",
            "Kaus Borealis": "", "Peacock": "", "Pearce's Star": "", "Persian": "",
            "Phact": "", "Pherkad Minor": "", "Revenant of the Swan": "", "Sceptrum": "",
            "Scheat": "", "Seat": "", "Sterope": "", "Talitha": "",
            "The Garnet Star": "Stella Granata", "The Ruby Star": "", "Variabilis Coronae": "",
        },
        "ja": {
            "Abt's Star": "", "Achird": "", "Aggia": "", "Akfa Farkadain": "", "Al Aghnam": "",
            "Al Athfar": "", "Al Butain": "", "Al Dafirah": "", "Al Dhih": "", "Al Jabhah": "",
            "Al Kidr": "", "Al Kiladah": "", "Al Minlear al Asad": "", "Al Sharasif": "",
            "Al Ukud": "", "Alahakan": "", "Alava": "", "Albulaan": "", "Albulan": "",
            "Aldhiba": "", "Aldhibah": "", "Aldulfin": "", "Alhiba": "", "Alkalbain": "",
            "Alkaphrah": "", "Alkarab": "", "Almizan": "", "Alpherg": "", "Alsafi": "",
            "Alshat": "", "Ankaa": "", "Anwa Farkadain": "", "Apami-Atsa": "",
            "Arcturus": "アークトゥルス", "Arm": "", "Asellus Secundus": "", "Ashlesha": "",
            "Athafi": "", "Aulad Alnathlat": "", "Azmidi": "", "Bunda": "", "Choo": "",
            "Circitores": "", "Dalim": "", "Dheneb": "", "Elkurud": "", "Errai": "",
            "Fang": "", "Fawaris": "", "Fulu": "", "Fum al Faras": "", "Fum al Hui": "",
            "Fumalsamakah": "", "Fuyue": "", "Garafsa": "", "Ginan": "",
            "Gorgonea Secunda": "", "Gorgonea Tertia": "", "Gudja": "", "Haedus": "",
            "Hamalwarid": "", "Homam": "", "Hydor": "", "Iklil": "", "Imai": "", "Isis": "",
            "Jabbah": "", "Jishui": "", "Kabalfird": "", "Kang": "", "Kastra": "",
            "Ke Kwan": "", "KeKouan": "", "Koleon": "", "Kursi al Jabbar": "",
            "Kursi al Jauzah": "", "Kuton": "", "La Superba": "ラ・スペルバ", "Labr": "",
            "Larawag": "", "Mahasim": "", "Manubrij": "", "Men": "", "Minazal": "",
            "Minchir": "", "Misam": "", "Mizan": "", "Muhlifain": "", "Mula": "", "Nahn": "",
            "Namalsadirah": "", "Nasak Shamiya": "", "Nasak Yamani": "", "Nash": "",
            "Nucatai": "", "Okab": "", "Paikauhale": "", "Pearce's Star": "", "Persian": "",
            "Piautos": "", "Polaris Australis": "", "Regor": "", "Revati": "",
            "Revenant of the Swan": "", "Rijl al Awwa": "", "Rutilicus": "", "Saclateni": "",
            "Sadalmatar": "", "Sadalmulk": "", "Sadalnazi": "", "Saif al Jabbar": "",
            "Salm": "", "Seat": "", "Situla": "", "Suudalnujum": "", "Tais": "",
            "Taiyangshou": "", "Tarf": "", "Thabit": "", "The Ruby Star": "", "Thiba": "",
            "Tianguan": "", "Torcular": "", "Ukdah": "", "Variabilis Coronae": "", "Wei": "",
            "Wurren": "", "Xuange": "", "Yen": "",
        },
        "ko": {
            "Al Jabhah": "알 자바", "Al Thalimain Posterior": "", "Al Thalimain Prior": "",
            "Alava": "", "Alula Australis": "", "Alula Borealis": "", "Anser": "안세르",
            "Arcturus": "아르크투루스", "Arkab Posterior": "", "Arkab Prior": "",
            "Asellus Australis": "", "Asellus Borealis": "", "Asellus Primus": "",
            "Asellus Secundus": "", "Asellus Tertius": "", "Ashlesha": "아슐레샤",
            "Aulad Alnathlat": "아울라드 알나틀라트", "Bharani": "바라니",
            "Ceginus": "케기누스", "Choo": "", "Circitores": "키르키토레스", "Dabih Minor": "",
            "Deneb Kaitos Shemali": "데네브 카이토스 셰말리", "Deneb al Okab Borealis": "",
            "Errai": "에라이", "Fulu": "푸루", "Fum al Hui": "품 알 후이",
            "Fumalsamakah": "푸말사마카", "Furud": "푸루드", "Gorgonea Quarta": "",
            "Gorgonea Secunda": "", "Gorgonea Tertia": "", "Gudja": "",
            "Kaus Australis": "카우스 오스트랄리스", "Kaus Borealis": "카우스 보레알리스",
            "Kaus Media": "카우스 메디아", "Ke Kwan": "", "KeKouan": "",
            "Kornephoros": "코르네포로스", "Manubrij": "", "Marsic": "마르시크", "Men": "",
            "Minelauva": "미넬라우바", "Muliphein": "물리페인", "Muscida": "무스키다",
            "Nembus": "넴부스", "Pherkad Minor": "", "Pipirima": "피피리마",
            "Polaris": "북극성", "Prima Giedi": "", "Prima Hyadum": "", "Propus": "프로푸스",
            "Revenant of the Swan": "", "Rutilicus": "", "Sceptrum": "스켑트룸",
            "Scheat": "셰아트", "Secunda Hyadum": "", "Seginus": "세기누스", "Skat": "스카트",
            "Talitha": "탈리타", "Tania Australis": "", "Tania Borealis": "",
            "Terebellum": "테레벨룸", "Thail": "", "The Garnet Star": "", "Tianyi": "톈이",
            "Wei": "", "Xuange": "쉬안거", "Yed Posterior": "", "Yed Prior": "",
            "Zubanah": "주바나",
        },
        "nl": {
            "Alula Borealis": "", "Asellus Secundus": "", "Diadem": "", "Fuyue": "", "Mimosa": "",
            "Marsic": "", "Meissa": "", "Pearce's Star": "", "Plaskett's Star": "",
            "Polaris": "Poolster", "Rasalgethi": "", "Variabilis Coronae": "",
        },
        "no": {
            "Alcor": "", "Aljanah": "", "Diphda": "", "Elnath": "", "Hamal": "", "Marfak": "",
            "Phecda": "", "Rasalhague": "", "Shedar": "",
        },
        "pl": {
            "Castor": "Kastor", "Fuyue": "", "Pearce's Star": "", "Polaris": "Gwiazda Polarna",
            "Variabilis Coronae": "",
        },
        "pt": {
            "La Superba": "", "Mimosa": "", "Pearce's Star": "",
            "Plaskett's Star": "Estrela de Plaskett", "Polaris": "Estrela Polar", "Sterope": "",
            "Variabilis Coronae": "",
        },
        "sv": {
            "Acubens": "", "Ainalrami": "", "Akfa Farkadain": "", "Al Minlear al Asad": "",
            "Al Thalimain Posterior": "", "Algedi": "", "Alkaphrah": "", "Alpherg": "",
            "Anwa Farkadain": "", "Aulad Alnathlat": "", "Azmidi": "", "Diphda": "",
            "Errai": "", "Fumalsamakah": "", "Fuyue": "", "Giausar": "", "Hatysa": "",
            "Kabalfird": "", "Khambaliya": "", "Marfak": "", "Minelauva": "", "Mula": "",
            "Nasak Shamiya": "", "Pearce's Star": "", "Rasalhague": "", "Saif al Jabbar": "",
            "Saik": "", "Salm": "", "Shedar": "", "Talitha": "", "Tejat": "", "Tianguan": "",
            "Variabilis Coronae": "", "Wazn": "", "Yildun": "", "Zubenelhakrabi": "",
        },
        "th": {
            "Achernar": "ดาวอะเคอร์นาร์", "Aldebaran": "ดาวโรหิณี", "Alderamin": "",
            "Alnilam": "ดาวอัลนิลแลม", "Alnitak": "ดาวอัลนิแทค", "Alpheratz": "",
            "Altair": "ดาวอัลแตร์", "Bellatrix": "ดาวเบลลาทริกซ์", "Castor": "ดาวคาสเตอร์",
            "Cervantes": "", "Deneb": "ดาวเดเนบ", "Denebola": "ดาวเดเนโบลา", "Dubhe": "",
            "Errai": "", "Fomalhaut": "ดาวโฟมัลฮอต", "Mintaka": "ดาวมินตากา",
            "Procyon": "ดาวโพรซิออน", "Regulus": "ดาวหัวใจสิงห์", "Sirius": "ดาวโจร",
            "Titawin": "",
        },
        "uk": {
            "Albireo": "Альбірео", "Alderamin": "Альдерамін", "Algieba": "Альгейба",
            "Alkaid": "Алькаїд", "Alnasl": "Альназль", "Alnitak": "Альнітак",
            "Alpheratz": "Альферац", "Ankaa": "Анкаа", "Avior": "Авіор",
            "Castor": "Кастор", "Cebalrai": "Цебальрай", "Chertan": "Чертан",
            "Cor Caroli": "Серце Карла", "Dabih": "Дабіх", "Elnath": "Ельнат",
            "Fomalhaut": "Фомальгаут", "Gacrux": "Гакрукс", "Gienah": "Гієна",
            "Hadar": "Хадар", "Kochab": "Кохаб", "Lesath": "Лесат", "Markeb": "Маркеб",
            "Matar": "Матар", "Menkalinan": "Менкалінан", "Merak": "Мерак",
            "Miaplacidus": "Міаплацидус", "Mizar": "Міцар", "Muhlifain": "Мухліфайн",
            "Muphrid": "Муфрід", "Sabik": "Сабік", "Seginus": "Сегінус",
            "Shedar": "Шедар", "Sirius": "Сіріус", "Suhail": "Сухайль",
            "Sulafat": "Сулафат", "Talitha": "Таліта", "Toliman": "Толіман",
            "Zubenelgenubi": "Зубенельгенубі",
        },
        # Vietnamese charts print the Latin names; these few have
        # Sino-Vietnamese names in everyday use, as Vietnamese
        # Wikipedia titles them. Wikidata files Deneb as "Sao Deneb".
        "vi": {
            "Altair": "Sao Ngưu Lang", "Arcturus": "Sao Đại Giác",
            "Canopus": "Sao Lão Nhân", "Deneb": "Sao Thiên Tân",
            "Polaris": "Sao Bắc Cực", "Sirius": "Sao Thiên Lang",
            "Vega": "Sao Chức Nữ",
        },
        # Wikidata files Sirius under its A component ("Sirius A") and
        # has no Esperanto label for Mizar; these two are as Esperanto
        # Wikipedia titles them.
        "eo": {
            "Mizar": "Mizaro", "Sirius": "Siriuso",
        },
        # Turkish Wikipedia titles its star articles by the IAU name or
        # the Bayer letter, and gives a Turkish name to a handful (Ağız,
        # Elektra, Kutup Yıldızı, Miraç), which come through Wikidata's
        # labels. These three labels are not how it titles the star.
        "tr": {
            "Aldulfin": "", "Capella": "", "Mintaka": "",
        },
        # Russian Wikipedia titles most stars by the Bayer letter and the
        # named ones as Wikidata labels them, with these exceptions:
        # Wikidata files Sirius and Fomalhaut under their A components,
        # gives Elnath its other name (Нат), and describes Aludra, Sargas,
        # and Yildun by their letters where the articles carry the names.
        # Aspidiske is titled by its letter and named in the first line.
        "ru": {
            "Sirius": "Сириус", "Fomalhaut": "Фомальгаут", "Elnath": "Эльнат",
            "Aludra": "Алудра", "Aspidiske": "Аспидиске", "Sargas": "Саргас",
            "Yildun": "Йильдун",
        },
        # Romanian charts print the IAU names; Wikidata's two Romanian
        # labels are a French spelling and a variant. Polaris is the one
        # star with a Romanian name in everyday use.
        "ro": {
            "Aldulfin": "", "Merope": "", "Polaris": "Steaua Polară",
        },
        # Czech Wikipedia titles these by the IAU name where Wikidata's
        # label is another spelling or an older name (Deneb Kaitos, Ksora,
        # Altarf, Turais, Zuben Eschemali, Gemma, Becrux); Almach has no
        # article to check Alamak against. Schedir, Polárka, Betelgeuze,
        # Prokyon, Alkor, and Ras Alhague are the titles.
        "cs": {
            "Almach": "", "Alphecca": "", "Diphda": "", "Meridiana": "", "Mimosa": "",
            "Ruchbah": "", "Tarf": "", "Tureis": "", "Zubeneschamali": "",
        },
        "zh": {
            "Abt's Star": "阿布特星", "Aldhibah": "紫微左垣四", "Alhiba": "天潢五",
            "Almizan": "右旗三", "Alya": "天市左垣七", "Andrews' star": "",
            "Athafi": "紫微左垣五", "Athebyne": "紫微左垣三", "Becklin's Star": "",
            "Bessel's Star": "天津增廿九", "Bidelman's Helium Variable Star": "",
            "Diadem": "太微左垣五", "Ginan": "十字架增一", "Hydor": "垒壁阵七",
            "Jabbah": "键闭", "Kabalfird": "天钩四", "Kaus Australis": "箕宿三",
            "KeKouan": "骑官四", "Kochab": "北极二", "Kornephoros": "天市右垣一",
            "La Superba": "", "Meleph": "积尸增三", "Men": "骑官十", "Minelauva": "太微左垣三",
            "Nasak Shamiya": "天市右垣五", "Nasak Yamani": "天市右垣六", "Okab": "天市左垣六",
            "Pearce's Star": "皮尔斯星", "Plaskett's Star": "普拉斯基特星",
            "Porrima": "太微左垣二", "Saik": "天市右垣十一", "Sarin": "天市左垣一",
            "Seginus": "招摇", "Suhail": "天记", "Unukalhai": "天市右垣七", "Vanant": "",
            "Variabilis Coronae": "", "Vindemiatrix": "太微左垣四",
            "Yed Posterior": "天市右垣十", "Yed Prior": "天市右垣九", "ζ Cen": "库楼一",
            "ζ Per": "卷舌四", "κ Cyg": "奚仲一", "κ Hya": "张宿五", "λ Cet": "天囷三",
            "τ¹ Hya": "星宿二",
        },
        # The traditional script's exceptions to the character table: the
        # names that are transliterations, and one that is a description
        # in either script.
        "zh-Hant": {
            "Abt's Star": "阿布特星", "Pearce's Star": "皮爾斯星",
            "Plaskett's Star": "普拉斯基特星",
        },
        # Greek observing names: Eugenides Foundation, "Το βάθος του ουρανού",
        # https://www.eef.edu.gr/el/arthra/to-bathos-tou-ouranou/
        # NOA, "Η Μεγάλη Άρκτος και ένας ουρανός που αγνοούμε",
        # https://magazine.noa.gr/archives/3144
        # and the Ainos Dark Sky Guide (Kefalonia Geopark, 2021).
        "el": {
            'Sirius': 'Σείριος',
            'Arcturus': 'Αρκτούρος',
            'Vega': 'Βέγας',
            'Altair': 'Αλτάιρ',
            'Deneb': 'Ντένεμπ',
            'Antares': 'Αντάρης',
            'Polaris': 'Πολικός Αστέρας',
            'Rigel': 'Ρίγκελ',
            'Aldebaran': 'Αλντεμπαράν',
        },
        # Persian: the name fa.wikipedia titles the star's article with,
        # or where the title is a designation, the traditional name its
        # first sentence gives (Hadar, حضار; Saiph, سیف‌الجبار). Labels
        # that describe the star ("ستاره کربن") or name another (Mimosa's
        # بکروکس is Becrux) are dropped, and so is Pleione's پروین, the
        # Persian name of the whole cluster. The query service drops the
        # zero-width non-joiner from every label (ابط‌الجوزا comes back
        # ابطالجوزا), so the names that write one are here.
        "fa": {
            "Sirius": "شباهنگ", "Arcturus": "ژوبین\u200cدار", "Rigil Kentaurus": "رجل قنطورس",
            "Vega": "کرکس نشسته", "Betelgeuse": "ابط\u200cالجوزا", "Hadar": "حضار",
            "Altair": "کرکس پرنده", "Antares": "قلب\u200cالعقرب", "Spica": "بی\u200cژوبین",
            "Pollux": "سرپسین", "Fomalhaut": "فم\u200cالحوت", "Mimosa": "",
            "Regulus": "قلب\u200cالاسد", "Adhara": "عذارا", "Miaplacidus": "میاه\u200cپلاسیدوس",
            "α Gru": "بطن\u200cالنایر", "Regor": "سهیل\u200cالمحلف",
            "Mirfak": "مرفق\u200cالثریا", "Menkalinan": "منکب ذی\u200cالعنان",
            "Castor": "سرپیشین", "Alphard": "قلب\u200cالفرد", "Hamal": "حمل", "Alnitak": "نطاق",
            "Mirach": "جنب\u200cالمسلسله", "Saiph": "سیف\u200cالجبار", "Kochab": "کوکب شمالی",
            "Algol": "رأس\u200cالغول", "Denebola": "ذنب\u200cالاسد", "Shedar": "صدر",
            "Almach": "عناق\u200cالارض", "Caph": "کف\u200cالخضیب", "Mizar": "مئزر",
            "Larawag": "", "Ankaa": "عنقا", "Enif": "انف", "α Peg": "مرکب\u200cالفرس",
            "Ascella": "نعائم", "Algieba": "جبهه", "Unukalhai": "عنق\u200cالحیه",
            "Ruchbah": "رکبةذات\u200cالکرسی", "Alcyone": "نیرثریا",
            "Deneb Algedi": "ذنب\u200cالجدی", "Tejat": "پس\u200cپای", "Cor Caroli": "کبدالاسد",
            "Okab": "ذنب\u200cالعقاب", "Furud": "فرد", "Mira": "شگفت\u200cاختر",
            "Albireo": "منقار ماکیان", "Alfirk": "کوکب\u200cالفرق", "η Gem": "پیش\u200cپای",
            "Mothallah": "راس\u200cالمثلث", "Rasalgethi": "رأس\u200cالجاثی",
            "Wasat": "وسط\u200cالسماء", "Meissa": "هقعه", "Alahakan": "بطن\u200cالثعبان شمالی",
            "Atlas": "اطلس", "Electra": "الکترا", "Marfik": "مرفق\u200cالحوا", "Maia": "مایا",
            "Asellus Primus": "خرک یکم", "The Garnet Star": "ستارهٔ نارسنگ", "Merope": "میروپ",
            "Aldhiba": "بطن\u200cالثعبان جنوبی", "Alsciaukat": "شوکه", "Taygeta": "تحیه",
            "Akfa Farkadain": "اخفی\u200cالفرقدین", "θ Cas": "مرفق ذات\u200cالکرسی",
            "Fumalsamakah": "فم\u200cالسمکه", "Azelfafage": "ظلف\u200cالفرس",
            "La Superba": "لا سوپربا", "Pleione": "", "Pearce's Star": "",
        },
    },
    "constellations": {
        # Noorali T. Jiwaji, "Namna Ya Kuelewa Nyota Za Mbinguni":
        # https://sites.google.com/site/astronomyintanzania/astronomiakwakiswahili
        # Only these attested Swahili names are included; the rest keep
        # their Latin names. This is a display language, not a sky culture.
        "sw": {"Cru": "Msalaba wa Kusini", "Sco": "Ng'e"},
        # Czech Wikipedia titles the articles "Souhvězdí Velké medvědice",
        # in the genitive, and Wikidata carries the nominative names the
        # charts print; two of its labels are the article's phrase, and
        # Ursa Minor is Malý medvěd, as the article and the charts have it.
        "cs": {
            "Car": "Lodní kýl", "Cru": "Jižní kříž", "UMi": "Malý medvěd",
        },
        "de": {
            "CMa": "Großer Hund", "CMi": "Kleiner Hund", "Car": "Kiel des Schiffs",
            "Com": "Haar der Berenike", "CrA": "Südliche Krone", "CrB": "Nördliche Krone",
            "Cru": "Kreuz des Südens", "Dor": "Schwertfisch", "For": "Chemischer Ofen",
            "Hyi": "Kleine Wasserschlange", "Ind": "Indianer", "LMi": "Kleiner Löwe",
            "Phe": "Phönix", "PsA": "Südlicher Fisch", "Pup": "Achterdeck des Schiffs",
            "TrA": "Südliches Dreieck", "UMa": "Großer Bär", "UMi": "Kleiner Bär",
            "Vel": "Segel des Schiffs", "Vol": "Fliegender Fisch",
        },
        "fr": {
            "Eri": "Éridan", "Hya": "Hydre",
        },
        "id": {
            "Aqr": "", "Boo": "", "CMa": "Canis Major", "Cap": "", "Cen": "", "Cnc": "",
            "Her": "", "Oph": "", "Psc": "", "Sco": "", "Sgr": "", "UMa": "Ursa Major",
        },
        "is": {
            "CMa": "Stórihundur", "CMi": "Litlihundur", "Cap": "Steingeitin", "Cep": "Sefeus",
            "Com": "Bereníkuhaddur", "Ori": "Óríon",
        },
        "it": {
            "Cae": "Bulino", "Cas": "Cassiopea", "Crt": "Cratere", "Dor": "",
            "Equ": "Cavallino", "Eri": "Eridano", "Hya": "Idra", "Hyi": "Idra Maschio",
            "Nor": "Regolo", "Oph": "Ofiuco", "Vel": "Vele", "Vol": "Pesce Volante",
        },
        "ko": {
            "Cyg": "백조자리", "Oph": "땅꾼자리", "Vul": "여우자리",
        },
        "no": {
            "CMi": "Lille hund",
        },
        "pl": {
            "And": "Andromeda", "Ant": "Pompa", "Aps": "Ptak Rajski", "Aql": "Orzeł",
            "Aqr": "Wodnik", "Ara": "Ołtarz", "Ari": "Baran", "Aur": "Woźnica",
            "Boo": "Wolarz", "CMa": "Wielki Pies", "CMi": "Mały Pies", "CVn": "Psy Gończe",
            "Cae": "Rylec", "Cam": "Żyrafa", "Cap": "Koziorożec", "Car": "Kil",
            "Cas": "Kasjopeja", "Cen": "Centaur", "Cep": "Cefeusz", "Cet": "Wieloryb",
            "Cha": "Kameleon", "Cir": "Cyrkiel", "Cnc": "Rak", "Col": "Gołąb",
            "Com": "Warkocz Bereniki", "CrA": "Korona Południowa", "CrB": "Korona Północna",
            "Crt": "Puchar", "Cru": "Krzyż Południa", "Crv": "Kruk", "Cyg": "Łabędź",
            "Del": "Delfin", "Dor": "Złota Ryba", "Dra": "Smok", "Equ": "Źrebię",
            "Eri": "Erydan", "For": "Piec", "Gem": "Bliźnięta", "Gru": "Żuraw",
            "Her": "Herkules", "Hor": "Zegar", "Hya": "Hydra", "Hyi": "Wąż Wodny",
            "Ind": "Indianin", "LMi": "Mały Lew", "Lac": "Jaszczurka", "Leo": "Lew",
            "Lep": "Zając", "Lib": "Waga", "Lup": "Wilk", "Lyn": "Ryś", "Lyr": "Lutnia",
            "Men": "Góra Stołowa", "Mic": "Mikroskop", "Mon": "Jednorożec", "Mus": "Mucha",
            "Nor": "Węgielnica", "Oct": "Oktant", "Oph": "Wężownik", "Ori": "Orion",
            "Pav": "Paw", "Peg": "Pegaz", "Per": "Perseusz", "Phe": "Feniks", "Pic": "Malarz",
            "PsA": "Ryba Południowa", "Psc": "Ryby", "Pup": "Rufa", "Pyx": "Kompas",
            "Ret": "Sieć", "Scl": "Rzeźbiarz", "Sco": "Skorpion", "Sct": "Tarcza",
            "Ser": "Wąż", "Sex": "Sekstant", "Sge": "Strzała", "Sgr": "Strzelec", "Tau": "Byk",
            "Tel": "Luneta", "TrA": "Trójkąt Południowy", "Tri": "Trójkąt", "Tuc": "Tukan",
            "UMa": "Wielka Niedźwiedzica", "UMi": "Mała Niedźwiedzica", "Vel": "Żagiel",
            "Vir": "Panna", "Vol": "Ryba Latająca", "Vul": "Lisek",
        },
        # Romanian Wikipedia titles Aquila "Vulturul" and Ophiuchus
        # "Ofiucus"; Wikidata keeps the Latin for both.
        "ro": {
            "Aql": "Vulturul", "Oph": "Ofiucus",
        },
        "pt": {
            "And": "", "Ant": "Máquina Pneumática", "Aps": "Ave-do-Paraíso", "Aql": "Águia",
            "Aqr": "Aquário", "Ara": "Altar", "Ari": "Carneiro", "Aur": "Cocheiro",
            "Boo": "Boieiro", "CMa": "Cão Maior", "CMi": "Cão Menor", "CVn": "Cães de Caça",
            "Cae": "Cinzel", "Cam": "Girafa", "Cap": "Capricórnio", "Car": "Quilha", "Cas": "",
            "Cen": "Centauro", "Cep": "Cefeu", "Cet": "Baleia", "Cha": "Camaleão",
            "Cir": "Compasso", "Cnc": "Caranguejo", "Col": "Pomba",
            "Com": "Cabeleira de Berenice", "CrA": "Coroa Austral", "CrB": "Coroa Boreal",
            "Crt": "Taça", "Cru": "Cruzeiro do Sul", "Crv": "Corvo", "Cyg": "Cisne",
            "Del": "Golfinho", "Dor": "Dourado", "Dra": "Dragão", "Equ": "Cavalo Menor",
            "Eri": "Erídano", "For": "Fornalha", "Gem": "", "Gru": "Grou", "Her": "Hércules",
            "Hor": "Relógio", "Hya": "Hidra", "Hyi": "Hidra Macho", "Ind": "Índio",
            "LMi": "Leão Menor", "Lac": "Lagarto", "Leo": "Leão", "Lep": "Lebre",
            "Lib": "Balança", "Lup": "Lobo", "Lyn": "Lince", "Lyr": "Lira", "Men": "Mesa",
            "Mic": "Microscópio", "Mon": "Unicórnio", "Mus": "Mosca", "Nor": "Régua",
            "Oct": "Oitante", "Oph": "Serpentário", "Ori": "", "Pav": "Pavão", "Peg": "Pégaso",
            "Per": "Perseu", "Phe": "", "Pic": "Pintor", "PsA": "Peixe Austral",
            "Psc": "Peixes", "Pup": "Popa", "Pyx": "Bússola", "Ret": "Retículo",
            "Scl": "Escultor", "Sco": "Escorpião", "Sct": "Escudo", "Ser": "Serpente",
            "Sex": "Sextante", "Sge": "Flecha", "Sgr": "Sagitário", "Tau": "Touro",
            "Tel": "Telescópio", "TrA": "Triângulo Austral", "Tri": "Triângulo",
            "Tuc": "Tucano", "UMa": "Ursa Maior", "UMi": "Ursa Menor", "Vel": "",
            "Vir": "Virgem", "Vol": "Peixe Voador", "Vul": "Raposa",
        },
        "zh": {
            "And": "仙女座", "Ant": "唧筒座", "Aps": "天燕座", "Aql": "天鹰座",
            "Aqr": "宝瓶座", "Ara": "天坛座", "Ari": "白羊座", "Aur": "御夫座",
            "Boo": "牧夫座", "CMa": "大犬座", "CMi": "小犬座", "CVn": "猎犬座",
            "Cae": "雕具座", "Cam": "鹿豹座", "Cap": "摩羯座", "Car": "船底座",
            "Cas": "仙后座", "Cen": "半人马座", "Cep": "仙王座", "Cet": "鲸鱼座",
            "Cha": "蝘蜓座", "Cir": "圆规座", "Cnc": "巨蟹座", "Col": "天鸽座",
            "Com": "后发座", "CrA": "南冕座", "CrB": "北冕座", "Crt": "巨爵座",
            "Cru": "南十字座", "Crv": "乌鸦座", "Cyg": "天鹅座", "Del": "海豚座",
            "Dor": "剑鱼座", "Dra": "天龙座", "Equ": "小马座", "Eri": "波江座",
            "For": "天炉座", "Gem": "双子座", "Gru": "天鹤座", "Her": "武仙座",
            "Hor": "时钟座", "Hya": "长蛇座", "Hyi": "水蛇座", "Ind": "印第安座",
            "LMi": "小狮座", "Lac": "蝎虎座", "Leo": "狮子座", "Lep": "天兔座",
            "Lib": "天秤座", "Lup": "豺狼座", "Lyn": "天猫座", "Lyr": "天琴座",
            "Men": "山案座", "Mic": "显微镜座", "Mon": "麒麟座", "Mus": "苍蝇座",
            "Nor": "矩尺座", "Oct": "南极座", "Oph": "蛇夫座", "Ori": "猎户座",
            "Pav": "孔雀座", "Peg": "飞马座", "Per": "英仙座", "Phe": "凤凰座",
            "Pic": "绘架座", "PsA": "南鱼座", "Psc": "双鱼座", "Pup": "船尾座",
            "Pyx": "罗盘座", "Ret": "网罟座", "Scl": "玉夫座", "Sco": "天蝎座",
            "Sct": "盾牌座", "Ser": "巨蛇座", "Sex": "六分仪座", "Sge": "天箭座",
            "Sgr": "人马座", "Tau": "金牛座", "Tel": "望远镜座", "TrA": "南三角座",
            "Tri": "三角座", "Tuc": "杜鹃座", "UMa": "大熊座", "UMi": "小熊座",
            "Vel": "船帆座", "Vir": "室女座", "Vol": "飞鱼座", "Vul": "狐狸座",
        },
        # The same names in the traditional script, as the Chinese
        # Wikipedia titles the articles for a reader in Taiwan or Hong
        # Kong (the two variants agree on all eighty-eight).
        "zh-Hant": {
            "And": "仙女座", "Ant": "唧筒座", "Aps": "天燕座", "Aql": "天鷹座",
            "Aqr": "寶瓶座", "Ara": "天壇座", "Ari": "白羊座", "Aur": "御夫座",
            "Boo": "牧夫座", "CMa": "大犬座", "CMi": "小犬座", "CVn": "獵犬座",
            "Cae": "雕具座", "Cam": "鹿豹座", "Cap": "摩羯座", "Car": "船底座",
            "Cas": "仙后座", "Cen": "半人馬座", "Cep": "仙王座", "Cet": "鯨魚座",
            "Cha": "蝘蜓座", "Cir": "圓規座", "Cnc": "巨蟹座", "Col": "天鴿座",
            "Com": "后髮座", "CrA": "南冕座", "CrB": "北冕座", "Crt": "巨爵座",
            "Cru": "南十字座", "Crv": "烏鴉座", "Cyg": "天鵝座", "Del": "海豚座",
            "Dor": "劍魚座", "Dra": "天龍座", "Equ": "小馬座", "Eri": "波江座",
            "For": "天爐座", "Gem": "雙子座", "Gru": "天鶴座", "Her": "武仙座",
            "Hor": "時鐘座", "Hya": "長蛇座", "Hyi": "水蛇座", "Ind": "印第安座",
            "LMi": "小獅座", "Lac": "蝎虎座", "Leo": "獅子座", "Lep": "天兔座",
            "Lib": "天秤座", "Lup": "豺狼座", "Lyn": "天貓座", "Lyr": "天琴座",
            "Men": "山案座", "Mic": "顯微鏡座", "Mon": "麒麟座", "Mus": "蒼蠅座",
            "Nor": "矩尺座", "Oct": "南極座", "Oph": "蛇夫座", "Ori": "獵戶座",
            "Pav": "孔雀座", "Peg": "飛馬座", "Per": "英仙座", "Phe": "鳳凰座",
            "Pic": "繪架座", "PsA": "南魚座", "Psc": "雙魚座", "Pup": "船尾座",
            "Pyx": "羅盤座", "Ret": "網罟座", "Scl": "玉夫座", "Sco": "天蠍座",
            "Sct": "盾牌座", "Ser": "巨蛇座", "Sex": "六分儀座", "Sge": "天箭座",
            "Sgr": "人馬座", "Tau": "金牛座", "Tel": "望遠鏡座", "TrA": "南三角座",
            "Tri": "三角座", "Tuc": "杜鵑座", "UMa": "大熊座", "UMi": "小熊座",
            "Vel": "船帆座", "Vir": "室女座", "Vol": "飛魚座", "Vul": "狐狸座",
        },
        # Turkish Wikipedia titles the articles by the Latin name, "Ursa
        # Major (takımyıldız)", and opens each with the Turkish name,
        # "Büyükayı"; Wikidata carries only two of those as labels. The
        # Turkish names are these, as the articles give them; Andromeda,
        # Perseus, and the rest keep the Latin, as Turkish charts print it.
        "tr": {
            "Ant": "Pompa", "Aps": "Cennetkuşu", "Aql": "Kartal", "Aqr": "Kova",
            "Ara": "Sunak", "Ari": "Koç", "Aur": "Arabacı", "Boo": "Çoban",
            "CMa": "Büyük Köpek", "CMi": "Küçük Köpek", "CVn": "Av Köpekleri",
            "Cae": "Çelikkalem", "Cam": "Zürafa", "Cap": "Oğlak", "Car": "Karina",
            "Cas": "Kraliçe", "Cen": "Erboğa", "Cep": "Kral", "Cet": "Balina",
            "Cha": "Bukalemun", "Cir": "Pergel", "Cnc": "Yengeç", "Col": "Güvercin",
            "Com": "Berenis'in Saçı", "CrA": "Güneytacı", "CrB": "Kuzeytacı", "Crt": "Kupa",
            "Cru": "Güneyhaçı", "Crv": "Karga", "Cyg": "Kuğu", "Del": "Yunus",
            "Dor": "Kılıçbalığı", "Dra": "Ejderha", "Equ": "Tay", "Eri": "Irmak",
            "For": "Ocak", "Gem": "İkizler", "Gru": "Turna", "Her": "Herkül", "Hor": "Saat",
            "Hya": "Suyılanı", "Hyi": "Küçüksuyılanı", "Ind": "Hint", "Lac": "Kertenkele",
            "Leo": "Aslan", "Lep": "Tavşan", "Lib": "Terazi", "Lup": "Kurt", "Lyn": "Vaşak",
            "Lyr": "Çalgı", "Men": "Masa", "Mic": "Mikroskop", "Mon": "Tekboynuz",
            "Mus": "Sinek", "Nor": "Cetvel", "Oct": "Sekizlik", "Oph": "Yılancı",
            "Ori": "Avcı", "Pav": "Tavus", "Phe": "Anka", "Pic": "Ressam",
            "PsA": "Güneybalığı", "Psc": "Balıklar", "Pup": "Pupa", "Pyx": "Kumpas",
            "Ret": "Ağcık", "Scl": "Yontar", "Sco": "Akrep", "Sct": "Kalkan", "Ser": "Yılan",
            "Sex": "Altılık", "Sge": "Okçuk", "Sgr": "Yay", "Tau": "Boğa", "Tel": "Dürbün",
            "TrA": "Güney Üçgeni", "Tri": "Üçgen", "Tuc": "Tukan", "UMa": "Büyükayı",
            "UMi": "Küçükayı", "Vel": "Yelken", "Vir": "Başak", "Vol": "Uçanbalık",
            "Vul": "Tilkicik",
        },
        # Greek chart names: https://www.astronomia.gr/wiki/index.php?title=Αστερισμός
        # Use the IAU codes (the source table has typos for Scl and Hor).
        "el": {
            'And': 'Ανδρομέδα', 'Ant': 'Αντλία', 'Aps': 'Πτηνόν',
            'Aqr': 'Υδροχόος', 'Aql': 'Αετός', 'Ara': 'Βωμός',
            'Ari': 'Κριός', 'Aur': 'Ηνίοχος', 'Boo': 'Βοώτης',
            'Cae': 'Γλυφείον', 'Cam': 'Καμηλοπάρδαλις', 'Cnc': 'Καρκίνος',
            'CVn': 'Θηρευτικοί Κύνες', 'CMa': 'Μέγας Κύων', 'CMi': 'Μικρός Κύων',
            'Cap': 'Αιγόκερως', 'Car': 'Τρόπις', 'Cas': 'Κασσιόπη',
            'Cen': 'Κένταυρος', 'Cep': 'Κηφεύς', 'Cet': 'Κήτος',
            'Cha': 'Χαμαιλέων', 'Cir': 'Διαβήτης', 'Col': 'Περιστερά',
            'Com': 'Κόμη Βερενίκης', 'CrA': 'Νότιος Στέφανος', 'CrB': 'Βόρειος Στέφανος',
            'Crv': 'Κόραξ', 'Crt': 'Κρατήρ', 'Cru': 'Νότιος Σταυρός',
            'Cyg': 'Κύκνος', 'Del': 'Δελφίνι', 'Dor': 'Δοράς',
            'Dra': 'Δράκων', 'Equ': 'Ιππάριον', 'Eri': 'Ηριδανός',
            'For': 'Κάμινος', 'Gem': 'Δίδυμοι', 'Gru': 'Γερανός',
            'Her': 'Ηρακλής', 'Hor': 'Ωρολόγιον', 'Hya': 'Ύδρα',
            'Hyi': 'Ύδρος', 'Ind': 'Ινδός', 'Lac': 'Σαύρα',
            'Leo': 'Λέων', 'LMi': 'Μικρός Λέων', 'Lep': 'Λαγωός',
            'Lib': 'Ζυγός', 'Lup': 'Λύκος', 'Lyn': 'Λυγξ',
            'Lyr': 'Λύρα', 'Men': 'Τράπεζα', 'Mic': 'Μικροσκόπιον',
            'Mon': 'Μονόκερως', 'Mus': 'Μυία', 'Nor': 'Γνώμων',
            'Oct': 'Οκτάς', 'Oph': 'Οφιούχος', 'Ori': 'Ωρίωνας',
            'Pav': 'Ταώς', 'Peg': 'Πήγασος', 'Per': 'Περσεύς',
            'Phe': 'Φοίνιξ', 'Pic': 'Οκρίβας', 'Psc': 'Ιχθύες',
            'PsA': 'Νότιος Ιχθύς', 'Pup': 'Πρύμνη', 'Pyx': 'Πυξίς',
            'Ret': 'Δίκτυον', 'Sge': 'Βέλος', 'Sgr': 'Τοξότης',
            'Sco': 'Σκορπιός', 'Scl': 'Γλύπτης', 'Sct': 'Ασπίς',
            'Ser': 'Όφις', 'Sex': 'Εξάς', 'Tau': 'Ταύρος',
            'Tel': 'Τηλεσκόπιον', 'Tri': 'Τρίγωνον', 'TrA': 'Νότιον Τρίγωνον',
            'Tuc': 'Τουκάνα', 'UMa': 'Μεγάλη Άρκτος', 'UMi': 'Μικρή Άρκτος',
            'Vel': 'Ιστία', 'Vir': 'Παρθένος', 'Vol': 'Ιπτάμενος Ιχθύς',
            'Vul': 'Αλώπηξ',
        },
        # Persian: the names fa.wikipedia titles the articles with (دب اکبر,
        # سدس), which Wikidata's labels mostly are; the labels lose their
        # zero-width non-joiners to the query service (ذات\u200cالکرسی).
        "fa": {
            "And": "آندرومدا", "Aur": "ارابه\u200cران", "CVn": "تازی\u200cها",
            "Car": "شاه\u200cتخته", "Cas": "ذات\u200cالکرسی", "Cha": "آفتاب\u200cپرست",
            "Lyn": "سیاه\u200cگوش", "Mon": "تک\u200cشاخ", "Peg": "اسب بزرگ", "Per": "برساوش",
            "Pic": "سه\u200cپایه", "Pup": "کشتی\u200cدم", "Pyx": "قطب\u200cنما", "Sex": "سدس",
            "Tri": "سه\u200cسو", "UMa": "دب اکبر", "UMi": "دب اصغر",
        },
    },
}


# ---------------------------------------------------------------------------
# Constellations
# ---------------------------------------------------------------------------
def hundredths(ra, dec):
    return [round(ra * 100) % 36000, round(dec * 100)]


# The data's Latin names as Wikidata's English labels have them.
WIKIDATA_NAME = {"Bootes": "Boötes"}


def constellation_label(label, latin):
    """A Wikidata constellation label as a chart would print it, or None:
    the Latin again, or a label that is a phrase about the constellation
    rather than its name (Polish files them all as "constellation of the
    X" with X declined, which OVERRIDES puts right)."""
    text = re.sub(r"\s*\(.*?\)\s*$", "", label).strip()
    text = re.sub(r"-sterrenbeeld$", "", text)
    if not text or text == latin or text.lower().startswith("gwiazdozbiór "):
        return None
    return text


def plain(text):
    """A name from the data as a chart prints it: plain spaces for its
    four-per-em ones, and the IAU's Major for its Maior (its genitives
    already say Majoris)."""
    return text.replace("\u2005", " ").replace("Maior", "Major")


# Genitives the source data has wrong; the IAU's take their place.
GENITIVES = {"Cru": "Crucis", "CrA": "Coronae Australis"}


def constellation_labels(latins, src):
    """{Latin name: {wikidata lang: label}} for the constellations, matched
    by their English label or alias among Wikidata's constellations, the
    label preferred where both match."""
    values = " ".join(f'"{WIKIDATA_NAME.get(name, name)}"@en' for name in sorted(latins))
    langs = ", ".join(f'"{code}"' for code in set(WIKIDATA_LANG.values()))
    rows = wikidata_rows("wikidata_constellations.csv", (
        "SELECT ?en ?lang ?l ?direct WHERE { VALUES ?en { " + values + " } "
        "{ ?item rdfs:label ?en . BIND(1 AS ?direct) } UNION "
        "{ ?item skos:altLabel ?en . BIND(0 AS ?direct) } "
        "?item wdt:P31/wdt:P279* wd:Q8928; rdfs:label ?l . BIND(LANG(?l) AS ?lang) "
        "FILTER(?lang IN (" + langs + ")) }"), src)
    back = {WIKIDATA_NAME.get(name, name): name for name in latins}
    out = {}
    for row in sorted(rows, key=lambda r: -int(r["direct"])):
        out.setdefault(back[row["en"]], {}).setdefault(row["lang"], row["l"])
    return out


def bake_constellations(src):
    lines = {f["id"]: f["geometry"]["coordinates"]
             for f in json.loads(fetch("constellations.lines.json", src))["features"]}
    features = json.loads(fetch("constellations.json", src))["features"]
    labels = constellation_labels({plain(f["properties"]["la"] or f["properties"]["name"])
                                   for f in features}, src)
    # The data sets its multi-word names with four-per-em spaces, which
    # no one types into a search; every name goes out with plain ones.
    records = []
    counts = {lang: 0 for lang in (*WIKIDATA_LANG, "zh-Hant", "sw")}
    for f in features:
        p = f["properties"]
        # Serpens is one constellation in two parts; the data carries the
        # parts as Ser1 and Ser2 with one name, and both are kept.
        latin = plain(p["la"] or p["name"])
        found = labels.get(latin, {})
        names = {}
        # Swahili uses only the sourced overrides, not unchecked labels.
        for lang in (*WIKIDATA_LANG, "sw"):
            wd_lang = WIKIDATA_LANG.get(lang)
            text = plain(p.get(lang, "")) if lang in OUR_LANGS else ""
            if not text and wd_lang in found:
                text = constellation_label(found[wd_lang], latin)
            text = OVERRIDES["constellations"].get(lang, {}).get(f["id"].rstrip("12"), text)
            if text and text != latin:
                names[lang] = text
                counts[lang] += 1
        text = OVERRIDES["constellations"]["zh-Hant"].get(f["id"].rstrip("12"))
        if text:
            names["zh-Hant"] = text
            counts["zh-Hant"] += 1
        ra, dec = f["geometry"]["coordinates"]
        records.append({
            "id": f["id"], "name": latin,
            "gen": GENITIVES.get(f["id"], plain(p["gen"])),
            "at": hundredths(ra, dec), "names": names,
            "lines": [[hundredths(ra, dec) for ra, dec in line]
                      for line in lines.get(f["id"], [])],
        })
    print(f"  {len(records)} constellations, "
          f"{sum(len(r['lines']) for r in records)} figure lines; names in other "
          "languages: " + ", ".join(f"{lang} {n}" for lang, n in counts.items()))
    return records


# ---------------------------------------------------------------------------
# The Milky Way
# ---------------------------------------------------------------------------
# The sky's floor and the band's working ceiling, as fractions of the
# layer's full scale: below the floor is the dark sky's own glow and the
# grain of the source, above the ceiling only a few knots in the bulge.
# Between them a gamma under one lifts the faint outer band and keeps
# the dust lanes legible.
MW_FLOOR, MW_CEILING, MW_GAMMA = 0.016, 0.30, 0.6


def smooth(grid):
    """One pass of a 3x3 box over the raster, wrapping in right ascension:
    the layer's grain averaged away, the dust lanes (many cells wide at
    this size) kept."""
    w, h = MW_W, MW_H
    out = [0.0] * (w * h)
    for r in range(h):
        r0, r1 = max(0, r - 1), min(h - 1, r + 1)
        for x in range(w):
            acc = 0.0
            n = 0
            for rr in (r0, r, r1):
                base = rr * w
                for xx in (x - 1, x, x + 1):
                    acc += grid[base + xx % w]
                    n += 1
            out[r * w + x] = acc / n
    return out


def bake_milky_way(src):
    import subprocess
    import tempfile
    exr = fetch("milkyway_2020_4k.exr", src)
    with tempfile.TemporaryDirectory() as tmp:
        exr_path = Path(tmp) / "milkyway.exr"
        pgm_path = Path(tmp) / "milkyway.pgm"
        exr_path.write_bytes(exr)
        # Grey, area-averaged down to the raster's size, as plain-text
        # floating point so there is nothing to decode but numbers.
        subprocess.run(["magick", str(exr_path), "-colorspace", "Gray",
                        "-define", "quantum:format=floating-point", "-depth", "32",
                        "-resize", f"{MW_W}x{MW_H}!", "-compress", "none",
                        str(pgm_path)], check=True)
        tokens = pgm_path.read_text().split()
    assert tokens[0] == "P2" and (int(tokens[1]), int(tokens[2])) == (MW_W, MW_H)
    scale = float(tokens[3])
    values = smooth([int(t) / scale for t in tokens[4:]])
    out = DATA / "milkyway.bin.gz"
    out.write_bytes(gzip.compress(bytes(
        int(round(255.0 * max(0.0, min(1.0, (v - MW_FLOOR) / (MW_CEILING - MW_FLOOR)))
                  ** MW_GAMMA))
        for v in values), 9))
    print(f"wrote {out} ({out.stat().st_size} bytes, {MW_W}x{MW_H})")


# ---------------------------------------------------------------------------
# The sky cultures
# ---------------------------------------------------------------------------
def hipparcos(src):
    """{HIP: (ra_deg, dec_deg, HD or None)} from the main catalogue."""
    out = {}
    for line in fetch("hip_main.dat", src).decode("latin-1").splitlines():
        f = line.split("|")
        try:
            hip, ra, dec = int(f[1]), float(f[8]), float(f[9])
        except (ValueError, IndexError):
            continue
        hd = f[71].strip()
        out[hip] = (ra, dec, int(hd) if hd.isdigit() else None)
    return out


def section(markdown, heading):
    """The text under a level-two heading, on one line, links reduced to
    their text and footnote marks dropped."""
    m = re.search(rf"^## {heading}s?\s*$(.*?)(?=^## |\Z)", markdown, re.S | re.M | re.I)
    if not m:
        return ""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", m.group(1))
    text = re.sub(r"\[#?\d+\]", "", text)
    return " ".join(text.replace("_", "").split())


# The Chinese star names in Stellarium's index are English only:
# "Northern Pole II", "Curved Array Added IV". The Chinese name behind
# each is systematic, the asterism's name and an ordinal, 北极二, with 增
# for an added star, 勾陈增四, so the bake derives it from the asterism's
# native name. The asterisms with no native name in the index, and the
# stars named for themselves alone ("Crown Prince", 太子), come from the
# culture's own zh_CN translation. The contemporary culture has the same
# star names and is given the same language, so a Chinese reader sees
# them in Chinese there too. The traditional script's names are the same
# names in the traditional characters, kept as a variant of the culture.
CHINESE_CULTURES = ("chinese", "chinese_contemporary")
_CHINESE_DIGITS = "零一二三四五六七八九"


def chinese_numeral(n):
    """1..99 as the numeral a star name carries: 一, 十, 十一, 二十三."""
    if n < 10:
        return _CHINESE_DIGITS[n]
    tens, ones = divmod(n, 10)
    return ((_CHINESE_DIGITS[tens] if tens > 1 else "") + "十"
            + (_CHINESE_DIGITS[ones] if ones else ""))


def roman_numeral(text):
    value = {"I": 1, "V": 5, "X": 10, "L": 50}
    total = 0
    for i, ch in enumerate(text):
        if i + 1 < len(text) and value[text[i + 1]] > value[ch]:
            total -= value[ch]
        else:
            total += value[ch]
    return total


def po_translations(name, src):
    """{msgid: msgstr} from a culture's translation file."""
    po = fetch(name, src).decode("utf-8")
    pairs = re.findall(r'msgid "((?:[^"\\]|\\.)*)"\nmsgstr "((?:[^"\\]|\\.)*)"', po)
    return {a: b for a, b in pairs if a and b}


_STAR_NAME = re.compile(r"^(.*?)( Added)? ([IVXL]+)$")


def chinese_native(english, asterisms, translated):
    """The Chinese name behind an English star name, or ''."""
    m = _STAR_NAME.match(english)
    if m:
        asterism = asterisms.get(m.group(1)) or translated.get(m.group(1))
        if asterism:
            # An asterism two enclosures keep carries the enclosure in
            # its name, 三公 (紫微垣); its stars are 三公二 in each, as the
            # charts have them, and the chip's designation tells which.
            asterism = re.sub(r"\s*\([^)]*\)", "", asterism)
            return asterism + ("增" if m.group(2) else "") + chinese_numeral(
                roman_numeral(m.group(3)))
    return translated.get(english, "")


def bake_cultures(stars, src):
    hip = hipparcos(src)
    by_hd = {s["hd"]: i for i, s in enumerate(stars) if s["hd"] is not None}
    cultures = []
    for name in CULTURES:
        index = json.loads(fetch(f"sc/{name}.json", src))
        md = fetch(f"sc/{name}.md", src).decode("utf-8")
        constellations = []
        for record in index["constellations"]:
            lines = []
            for line in record.get("lines", []):
                pts = [hip[v] for v in line if isinstance(v, int) and v in hip]
                if len(pts) >= 2:
                    lines.append([hundredths(ra, dec) for ra, dec, _hd in pts])
            if not lines:
                continue
            # The label sits at the figure's centroid on the sphere.
            xs = ys = zs = 0.0
            seen = set()
            for line in record["lines"]:
                for v in line:
                    if isinstance(v, int) and v in hip and v not in seen:
                        seen.add(v)
                        ra, dec = math.radians(hip[v][0]), math.radians(hip[v][1])
                        xs += math.cos(dec) * math.cos(ra)
                        ys += math.cos(dec) * math.sin(ra)
                        zs += math.sin(dec)
            ra = math.degrees(math.atan2(ys, xs)) % 360.0
            dec = math.degrees(math.atan2(zs, math.hypot(xs, ys)))
            common = record.get("common_name", {})
            entry = {"english": common.get("english", ""),
                     "native": common.get("native", ""),
                     "at": hundredths(ra, dec), "lines": lines}
            if record.get("iau"):
                entry["iau"] = record["iau"]
            constellations.append(entry)
        native_lang = (index.get("native_lang") or "").split("_")[0]
        translated = {}
        if name in CHINESE_CULTURES:
            native_lang = "zh"
            translated = po_translations(f"sc/{name}.zh_CN.po", src)
            for entry in constellations:
                entry["native"] = entry["native"] or translated.get(entry["english"], "")
        asterisms = {e["english"]: e["native"] for e in constellations if e["native"]}
        star_names = {}
        for key, entries in index.get("common_names", {}).items():
            try:
                hip_id = int(key.split()[1])
            except (IndexError, ValueError):
                continue
            hd = hip.get(hip_id, (0, 0, None))[2]
            if hd is None or hd not in by_hd or not entries:
                continue
            first = entries[0]
            english, native = first.get("english", ""), first.get("native", "")
            if name in CHINESE_CULTURES and not native:
                native = chinese_native(english, asterisms, translated)
            star_names[str(by_hd[hd])] = [english, native]
        variants = {}
        if name in CHINESE_CULTURES:
            variants["zh-Hant"] = {
                "constellations": [traditional(e["native"]) for e in constellations],
                "star_names": {k: traditional(n) for k, (_e, n) in star_names.items()},
            }
        cultures.append({
            "id": name, "title": md.split("\n", 1)[0].strip("# ").strip(),
            "region": index.get("region", ""),
            "native_lang": native_lang,
            "fallback": bool(index.get("fallback_to_international_names")),
            "authors": section(md, "Author"), "license": section(md, "License"),
            "constellations": constellations, "star_names": star_names,
            "variants": variants,
        })
        print(f"  {name:24} {len(constellations):3} figures, {len(star_names):4} star names"
              f"  [{cultures[-1]['license'][:40]}]")
    out = DATA / "cultures.json.gz"
    out.write_bytes(gzip.compress(
        json.dumps(cultures, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(cultures)} cultures)")


def main():
    src = None
    if len(sys.argv) == 3 and sys.argv[1] == "--from":
        src = Path(sys.argv[2])
    stars = bake_stars(src)
    constellations = bake_constellations(src)
    genitives = sorted({r["gen"] for r in constellations})
    sky = {"names": bake_names(stars, genitives, src),
           "constellations": constellations}
    out = DATA / "sky.json.gz"
    out.write_bytes(gzip.compress(
        json.dumps(sky, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    bake_cultures(stars, src)
    bake_milky_way(src)


if __name__ == "__main__":
    main()
