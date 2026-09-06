"""The asterisms: the star patterns people know by a name of their own
that is not a constellation's, the Big Dipper, the Summer Triangle,
Orion's Belt. Each is its stars by Bayer or Flamsteed designation, placed
from the catalogue when first asked for, so `/` can find one and frame
it. They are offered under every tradition, as the planets and the
Messier objects are: the pattern is in the sky whatever figure is drawn
through it.
"""

import math

from linecast._sky_catalogue import star_names, star_vectors

# "stars" are designations, the constellation last. A star the catalogue
# gives a superscript (α¹ Cen) is matched by the bare letter, the
# brighter of the pair. "names" are the display languages' own where a
# language has one; "aliases" are other names in English, or names in
# wide use elsewhere.
ASTERISMS = [
    {"name": "Big Dipper",
     "stars": ["α UMa", "β UMa", "γ UMa", "δ UMa", "ε UMa", "ζ UMa", "η UMa"],
     "aliases": ["Plough", "Charles's Wain", "Charles' Wain", "Dipper"],
     "names": {"fr": "Grande Casserole", "es": "El Carro", "de": "Großer Wagen",
               "it": "Grande Carro", "nl": "Steelpannetje", "pl": "Wielki Wóz",
               "no": "Karlsvogna", "sv": "Karlavagnen", "da": "Karlsvognen",
               "fi": "Otava", "is": "Karlsvagninn", "ja": "北斗七星",
               "ko": "북두칠성", "zh": "北斗七星", "th": "ดาวจระเข้", "id": "Biduk"}},
    {"name": "Little Dipper",
     "stars": ["α UMi", "β UMi", "γ UMi", "δ UMi", "ε UMi", "ζ UMi", "η UMi"],
     "aliases": [],
     "names": {"fr": "Petite Casserole", "es": "Carro Menor", "de": "Kleiner Wagen",
               "it": "Piccolo Carro", "pl": "Mały Wóz", "zh": "小北斗"}},
    {"name": "Summer Triangle",
     "stars": ["α Lyr", "α Cyg", "α Aql"],
     "aliases": [],
     "names": {"fr": "Triangle d'été", "es": "Triángulo de verano", "de": "Sommerdreieck",
               "it": "Triangolo estivo", "pt": "Triângulo de Verão", "nl": "Zomerdriehoek",
               "pl": "Trójkąt letni", "no": "Sommertriangelet", "sv": "Sommartriangeln",
               "da": "Sommertrekanten", "fi": "Kesäkolmio", "ja": "夏の大三角",
               "ko": "여름의 대삼각형", "zh": "夏季大三角"}},
    {"name": "Winter Triangle",
     "stars": ["α CMa", "α CMi", "α Ori"],
     "aliases": [],
     "names": {"fr": "Triangle d'hiver", "es": "Triángulo de invierno", "de": "Winterdreieck",
               "it": "Triangolo invernale", "pt": "Triângulo de Inverno",
               "nl": "Winterdriehoek", "pl": "Trójkąt zimowy", "sv": "Vintertriangeln",
               "da": "Vintertrekanten", "fi": "Talvikolmio", "ja": "冬の大三角",
               "ko": "겨울의 대삼각형", "zh": "冬季大三角"}},
    {"name": "Winter Hexagon",
     "stars": ["α CMa", "α CMi", "β Gem", "α Aur", "α Tau", "β Ori"],
     "aliases": ["Winter Circle"],
     "names": {"fr": "Hexagone d'hiver", "es": "Hexágono de invierno", "de": "Wintersechseck",
               "it": "Esagono invernale", "nl": "Winterzeshoek", "pl": "Sześciokąt zimowy",
               "ja": "冬のダイヤモンド", "ko": "겨울의 대육각형", "zh": "冬季六边形"}},
    {"name": "Spring Triangle",
     "stars": ["α Boo", "α Vir", "α Leo"],
     "aliases": [],
     "names": {"fr": "Triangle de printemps", "es": "Triángulo de primavera",
               "de": "Frühlingsdreieck", "it": "Triangolo primaverile", "nl": "Lentedriehoek",
               "pl": "Trójkąt wiosenny", "ja": "春の大三角", "ko": "봄의 대삼각형",
               "zh": "春季大三角"}},
    {"name": "Great Square of Pegasus",
     "stars": ["α Peg", "β Peg", "γ Peg", "α And"],
     "aliases": ["Great Square", "Square of Pegasus"],
     "names": {"fr": "Grand Carré de Pégase", "es": "Cuadrado de Pegaso", "de": "Herbstviereck",
               "it": "Quadrato di Pegaso", "nl": "Herfstvierkant", "ja": "秋の四辺形",
               "zh": "秋季四边形"}},
    {"name": "Northern Cross",
     "stars": ["α Cyg", "β Cyg", "γ Cyg", "δ Cyg", "ε Cyg"],
     "aliases": [],
     "names": {"fr": "Croix du Nord", "es": "Cruz del Norte", "de": "Kreuz des Nordens",
               "it": "Croce del Nord", "nl": "Noorderkruis", "pl": "Krzyż Północy",
               "ja": "北十字", "zh": "北十字"}},
    {"name": "Orion's Belt",
     "stars": ["δ Ori", "ε Ori", "ζ Ori"],
     "aliases": ["Belt of Orion", "Three Kings", "Three Sisters", "Tres Marías",
                 "Três Marias"],
     "names": {"fr": "Baudrier d'Orion", "es": "Cinturón de Orión", "de": "Oriongürtel",
               "it": "Cintura di Orione", "pt": "Cinturão de Órion", "nl": "Gordel van Orion",
               "pl": "Pas Oriona", "no": "Orions belte", "sv": "Orions bälte",
               "da": "Orions bælte", "fi": "Orionin vyö", "ja": "三つ星",
               "zh": "猎户座腰带"}},
    {"name": "Teapot",
     "stars": ["λ Sgr", "φ Sgr", "δ Sgr", "ε Sgr", "ζ Sgr", "σ Sgr", "τ Sgr", "γ Sgr"],
     "aliases": [],
     "names": {"fr": "Théière", "es": "Tetera", "de": "Teekanne", "it": "Teiera",
               "nl": "Theepot"}},
    {"name": "Sickle of Leo",
     "stars": ["α Leo", "η Leo", "γ Leo", "ζ Leo", "μ Leo", "ε Leo"],
     "aliases": ["Sickle"],
     "names": {"fr": "Faucille du Lion", "es": "Hoz de Leo", "de": "Sichel des Löwen",
               "it": "Falce del Leone", "nl": "Sikkel van de Leeuw", "ja": "ししの大鎌"}},
    {"name": "Keystone",
     "stars": ["ε Her", "ζ Her", "η Her", "π Her"],
     "aliases": ["Keystone of Hercules"],
     "names": {}},
    {"name": "False Cross",
     "stars": ["δ Vel", "κ Vel", "ι Car", "ε Car"],
     "aliases": [],
     "names": {"fr": "Fausse Croix", "es": "Falsa Cruz", "de": "Falsches Kreuz",
               "it": "Falsa Croce", "pt": "Falso Cruzeiro", "zh": "假十字"}},
    {"name": "Southern Pointers",
     "stars": ["α Cen", "β Cen"],
     "aliases": ["Pointers", "The Pointers"],
     "names": {}},
    {"name": "Job's Coffin",
     "stars": ["α Del", "β Del", "γ Del", "δ Del"],
     "aliases": [],
     "names": {}},
]

_SUPERSCRIPTS = str.maketrans("", "", "¹²³⁴⁵⁶⁷⁸⁹")
_records = None


def asterisms():
    """One record per asterism: `name`, `aliases`, `names` by language,
    `stars` as indices into the catalogue, `at` the centroid as an
    equatorial unit vector, and `spread`, the angular radius about it in
    degrees. An asterism the catalogue cannot place is left out."""
    global _records
    if _records is None:
        by_desig = _by_designation()
        vectors = star_vectors()
        out = []
        for a in ASTERISMS:
            stars = [by_desig[d] for d in a["stars"] if d in by_desig]
            if len(stars) < 2:
                continue
            x = sum(vectors[i][0] for i in stars)
            y = sum(vectors[i][1] for i in stars)
            z = sum(vectors[i][2] for i in stars)
            norm = math.sqrt(x * x + y * y + z * z) or 1.0
            at = (x / norm, y / norm, z / norm)
            spread = 0.0
            for i in stars:
                dot = max(-1.0, min(1.0, sum(p * q for p, q in zip(at, vectors[i]))))
                spread = max(spread, math.degrees(math.acos(dot)))
            out.append({"name": a["name"], "aliases": a["aliases"], "names": a["names"],
                        "stars": stars, "at": at, "spread": spread})
        _records = out
    return _records


def asterism_name(record, lang):
    """The asterism's name in *lang*, or the English one."""
    return record["names"].get(lang, record["name"])


def _by_designation():
    """{designation without superscripts: index of the brightest star so
    designated}. The stars are brightest first, so the lowest index wins."""
    out = {}
    for i, (_proper, desig) in star_names().items():
        bare = desig.translate(_SUPERSCRIPTS)
        if bare and (bare not in out or i < out[bare]):
            out[bare] = i
    return out
