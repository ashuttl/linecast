"""Hungarian.

en.py is the reference, with every key and notes on each; a key
left out here reads in English.

Hungarian puts its case endings on the word, and an ending's vowel
follows the word's (-ban/-ben, -tól/-től).  A slot is never given an
ending here unless every value it can take ends in the same word: a
temperature always ends in "fok" ("−2 fokig"), a clock hour in "óra"
("16 óra körül"), and -kor and -ig do not change ("20:00-ig").  A place
name takes no ending at all: it stands before a colon or a comma, or as
the owner in a possessive ("Budapest időjárása").  The weather prose
follows HungaroMet's forecasts: "derült", "erősen felhős", "zápor,
zivatar", "a köd feloszlik", "50-60 km/h-s széllökések".
"""


SETTINGS = {
    "decimal": ",",
}


DAY_NAMES = ["H", "K", "Sze", "Cs", "P", "Szo", "V"]


FULL_DAY_NAMES = ["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"]


# The Academy's abbreviations, with their full stops
MONTHS = ["jan.", "febr.", "márc.", "ápr.", "máj.", "jún.",
          "júl.", "aug.", "szept.", "okt.", "nov.", "dec."]
FULL_MONTHS = ["január", "február", "március", "április", "május", "június",
               "július", "augusztus", "szeptember", "október", "november", "december"]


# The chart's axis takes three letters, without the stops
CHART_MONTHS = ["jan", "feb", "már", "ápr", "máj", "jún",
                "júl", "aug", "szep", "okt", "nov", "dec"]


# "szept. 27.": the day takes its ordinal stop
MONTH_DAY = "{month} {day}."


MOON_PHASES = ["Újhold", "Növő sarló", "Első negyed", "Növő hold",
               "Telihold", "Fogyó hold", "Utolsó negyed", "Fogyó sarló"]


# The keys and what they do, as noun phrases, the way Hungarian
# software labels its commands
HELP = {
    "hint_colors": "színek",
    "weather_views": "előrejelzés / hónap / év",
    "month_colors": "hőmérséklet / eltérés az átlagtól",
    "month_home": "előző naptári hónap",
    "history_refresh": "óránkénti előzmények frissítése",
    "hint_help": "súgó",
    "key_wheel": "görgő",
    "key_space": "szóköz",
    "key_hover": "rámutatás",
    "key_click": "kattintás",
    "key_drag": "húzás",
    "key_enter": "enter",
    "forecast": "az előrejelzés böngészése",
    "now": "vissza a jelenhez",
    "alert": "figyelmeztetés olvasása",
    "browser": "figyelmeztetés megnyitása böngészőben",
    "refresh": "az előrejelzés frissítése",
    "time30": "idő léptetése 30 perccel",
    "time15": "idő léptetése 15 perccel",
    "year": "nap / év nézet",
    "bar_colors": "oszlopok színezése",
    "sun_times": "napkelte és napnyugta ideje",
    "turn_moon": "a Hold forgatása",
    "hide_text": "szöveg elrejtése / megjelenítése",
    "calendar": "korong / naptár nézet",
    "months": "léptetés hónaponként",
    "years": "léptetés évenként",
    "tide_views": "nap / hónap / év / összetétel nézet",
    "tide_views_no_year": "nap / hónap nézet",
    "tide_times": "vízállás abban az órában",
    "moon_times": "holdfázis, kelte és nyugta",
    "day": "nap megnyitása korong nézetben",
    "look": "körülnézés",
    "target": "ugrás a célra; újra: a kelés idejére",
    "figures": "csillagképek alakjai / nevei",
    "cultures": "égbolt-hagyományok",
    "play_time": "idő lejátszása: óra / nap / hét másodpercenként",
    "compass": "É, ÉK, K, DK, D, DNy, Ny, ÉNy felé nézés",
    "zenith": "nézés egyenesen felfelé",
    "moon": "a Hold felé nézés, ha fent van",
    "frames": "képkockák léptetése és szünet",
    "play": "lejátszás / szünet (a szünet visszavisz a jelenhez)",
    "temperature": "hőmérséklet-réteg",
    "wind": "szélréteg",
    "alerts": "figyelmeztetési réteg",
    "theme": "téma választása",
    "satellite": "radar / műhold",
    "help_title": "billentyűk",
    "help_close": "esc bezárás",
    "help_pan": "mozgatás",
    "help_hover": "azonosítás",
    "help_zoom": "nagyítás",
    "help_search": "keresés",
    "help_keys": "ez a lista",
    "help_quit": "kilépés",
}


WEATHER = {
    "month_temperature": "Óránkénti hőmérséklet",
    "month_departure": "Eltérés a(z) {span} óránkénti átlagától",
    "month_estimate": "Friss modellbecslés",
    "month_repeat": "Ismétlődő óra: a két érték átlaga",
    "month_small": "Ehhez a nézethez legalább {cols} oszlop és {rows} sor szükséges.",
    "month_loading": "Óránkénti előzmények betöltése…",
    "month_unavailable": "Az óránkénti előzmények nem érhetők el.",
    "month_partial": "Az óránkénti előzmények egy része nem érhető el.",
    "month_average": "Átlag: azonos óra, hét napon belüli dátumok, tíz év.",
    "month_rows": "Alacsony terminálon soronként két nap; mutasson rá mindkettő leolvasásához.",
    "month_missing": "A hiányzó órák üresek; az ismétlődő órák átlaga jelenik meg.",
    "month_extremes": "Jobb oszlop: az egyes sorok legkisebb és legnagyobb óránkénti értéke.",
    # "V 27.": the day of the month takes its ordinal stop
    "day_of_month": "{d}.",
    "today": "Ma",
    "today_short": "ma",
    # "{day}-i" would put an ending on a day name or a date; "not
    # today's" says it, with the day beside it
    "forecast_stale": "Ez az előrejelzés nem mai ({day}); újabbat nem sikerült letölteni.",
    "forecast_stale_at": ("Ez az előrejelzés nem mai ({day}); {time}-kor sem sikerült "
                          "újabbat letölteni."),
    "forecast_fetching": "Újabb előrejelzés letöltése…",
    "alerts_unavailable": "A figyelmeztetéseket nem sikerült ellenőrizni.",
    "alerts_stale": "Figyelmeztetések állapota: {when}; újabbakat nem sikerült lekérni.",
    "retry_run": "Próbálja újra a parancs ismételt futtatásával.",
    "retry_key": "Az újrapróbálkozáshoz nyomja meg az r billentyűt.",
    "credit_forecast": "Időjárási adatok: {source}",
    "credit_alerts": "Figyelmeztetések: {source}",
    "credit_current": "Aktuális időjárás: {source}",
    # The station's name takes no ending: "Megfigyelés: Budapest-Lőrinc,
    # 14:00, 12 km-re"
    "credit_observed": "Megfigyelés: {place}, {time}, {distance} távolságra",
    "metric_unit_sep": "\u00a0",
    "unit_kmh": "km/h",
    "unit_ms": "m/s",
    "unit_mph": "mph",
    "unit_mm": "mm",
    "unit_km": "km",
    "unit_mi": "mérföld",
    "unit_cm": "cm",
    "feels": "hőérzet",
    "wind": "Szél",
    "gusts": "széllökés",
    "humidity": "Páratartalom",
    "chance": "{p} esély",
    "chance_of": "{p} eséllyel {what}",
    "amount_between": "{amount} {a} és {b} között",
    "amount_all_day": "{amount} egész nap",
    "cloud": "Felhőzet {p}",
    "heaviest_around": "legerősebb {time} körül",
    "dew_pt": "Harmatpont",
    "uv": "UV",
    "aqi": "AQI",
    "precip_inch": "″",
    "metric_unit_sep_prose": "\u00a0",
    "precip_inch_prose": "{n}\u00a0hüvelyk",
    # The wind in a sentence is an adjective of the gusts, as HungaroMet
    # writes it: "60 km/h-s széllökések".  The ending follows the unit
    # as it is read: kilométer per órás, méter per szekundumos.
    "unit_kmh_prose": "km/h-s",
    "unit_ms_prose": "m/s-os",
    "unit_mph_prose": "mph-s",
    # -ig keeps its shape after any time: "V 20:00-ig"
    "until": "{time}-ig",
    "sentence_end": ".",
    "sentence_join": ". ",
    # The felt temperature is the hőérzet; it is higher or lower
    "feels_humid": "A magas páratartalom miatt a hőérzet magasabb",
    "feels_sun": "A napsütés miatt a hőérzet magasabb",
    "feels_wind": "A szél miatt a hőérzet alacsonyabb",
    "feels_dry": "A száraz levegő miatt a hőérzet alacsonyabb",
    # "A mai legmagasabb hőmérséklet 5 fokkal alacsonyabb lesz, mint a
    # tegnapi": the high is higher or lower, as HungaroMet has it, and
    # the difference takes -kal, which "fok" fixes as -kal.
    "degrees": "{n}\u00a0fok",
    "degrees_diff": "{n}\u00a0fokkal",
    "same_temp": "nagyjából ugyanannyi lesz, mint {ref_day}",
    "bit_warmer": "valamivel magasabb lesz, mint {ref_day}",
    "bit_cooler": "valamivel alacsonyabb lesz, mint {ref_day}",
    "warmer": "magasabb lesz, mint {ref_day}",
    "cooler": "alacsonyabb lesz, mint {ref_day}",
    "much_warmer": "jóval magasabb lesz, mint {ref_day}",
    "much_cooler": "jóval alacsonyabb lesz, mint {ref_day}",
    "warmer_by": "{diff} magasabb lesz, mint {ref_day}",
    "cooler_by": "{diff} alacsonyabb lesz, mint {ref_day}",
    "today_subj": "A mai legmagasabb hőmérséklet",
    "tomorrow_subj": "A holnapi legmagasabb hőmérséklet",
    "yesterday": "a tegnapi",
    "today_ref": "a mai",
    "will_be": "{subject} {comparison}",
    "will_be_then": "A legmagasabb hőmérséklet {comparison}",
    # The precipitation.  What is falling now is known, so it takes the
    # article ({desc_def}: "az eső", "a havazás"); what is to come is new,
    # and goes bare before its verb ("16 óra körül eső kezdődik").  A
    # turn is a verb phrase of its own, by what it turns to
    # ({peak_art}: "havazásba megy át", "zivatarrá erősödik").  Rain,
    # drizzle and snow begin ("kezdődik"); showers and storms form
    # ("alakul ki"), which the "_zt" forms say, and last the day as
    # "egész nap zápor várható", not as the one shower holding on.
    "ending": "{desc_def} {time} megszűnik",
    "continuing": "{desc_def} egész nap kitart",
    "continuing_zt": "Egész nap {desc} várható",
    "ending_becoming": "{desc_def} {peak_time} {peak_art}, majd {time} megszűnik",
    "continuing_becoming": "{desc_def} {peak_time} {peak_art}, és egész nap kitart",
    "continuing_becoming_zt": "Egész nap {desc} várható, amely {peak_time} {peak_art}",
    "starting": "{time} valószínűleg {desc} kezdődik",
    "starting_zt": "{time} valószínűleg {desc} alakul ki",
    "starting_becoming": "{time} valószínűleg {desc} kezdődik, majd {peak_time} {peak_art}",
    "starting_becoming_zt": "{time} valószínűleg {desc} alakul ki, majd {peak_time} {peak_art}",
    "starting_span": "{time} {desc} valószínű",
    "starting_span_becoming": "{time} {desc} valószínű, majd {peak_time} {peak_art}",
    "starting_span_heavier": "{time} {desc} valószínű, majd {peak_time} felerősödik",
    "starting_chance": "{time} {desc} előfordulhat",
    "starting_chance_becoming": "{time} {desc} előfordulhat, majd {peak_time} {peak_art}",
    "starting_sure": "{time} {desc} kezdődik",
    "starting_sure_zt": "{time} {desc} alakul ki",
    "starting_sure_becoming": "{time} {desc} kezdődik, majd {peak_time} {peak_art}",
    "starting_sure_becoming_zt": "{time} {desc} alakul ki, majd {peak_time} {peak_art}",
    "continuing_night": "{desc_def} egész éjjel kitart",
    "continuing_night_zt": "Egész éjjel {desc} várható",
    "continuing_night_becoming": "{desc_def} {peak_time} {peak_art}, és egész éjjel kitart",
    "continuing_night_becoming_zt": "Egész éjjel {desc} várható, amely {peak_time} {peak_art}",
    "ending_heavier": "{desc_def} {peak_time} felerősödik, majd {time} megszűnik",
    "continuing_heavier": "{desc_def} {peak_time} felerősödik, és egész nap kitart",
    "continuing_heavier_zt": "Egész nap {desc} várható, amely {peak_time} felerősödik",
    "continuing_night_heavier": "{desc_def} {peak_time} felerősödik, és egész éjjel kitart",
    "continuing_night_heavier_zt": "Egész éjjel {desc} várható, amely {peak_time} felerősödik",
    "starting_heavier": "{time} valószínűleg {desc} kezdődik, majd {peak_time} felerősödik",
    "starting_heavier_zt": "{time} valószínűleg {desc} alakul ki, majd {peak_time} felerősödik",
    "starting_chance_heavier": "{time} {desc} előfordulhat, majd {peak_time} felerősödik",
    "starting_sure_heavier": "{time} {desc} kezdődik, majd {peak_time} felerősödik",
    "starting_sure_heavier_zt": "{time} {desc} alakul ki, majd {peak_time} felerősödik",
    "more_later": "{time} újabb {desc} várható",
    # "Estére körülbelül 5 cm hó hullhat": by a time is its -ra/-re form,
    # the "_by" parts of the day below
    "snow_total": "{time} körülbelül {amt} hó hullhat",
    "fog_ending": "A köd {time} feloszlik",
    "fog_continuing": "A köd egész nap megmarad",
    "fog_continuing_night": "A köd egész éjjel megmarad",
    "fog_starting": "{time} köd képződik",
    "fog_starting_ending": "{time} köd képződik, amely {end} feloszlik",
    "shortly": "hamarosan",
    "in_about_an_hour": "körülbelül egy óra múlva",
    "in_a_couple_hours": "néhány óra múlva",
    "around": "{time} körül",
    "around_noon": "dél körül",
    "same_time": "ekkor",
    "same_part_later": "később",
    "overnight": "éjjel",
    "early_tomorrow_morning": "holnap kora reggel",
    "tomorrow_morning": "holnap délelőtt",
    "tomorrow_afternoon": "holnap délután",
    "tomorrow_evening": "holnap este",
    "on_day": "{day}",
    "then_early_morning": "kora reggel",
    "then_morning": "délelőtt",
    "then_later_morning": "késő délelőtt",
    "then_afternoon": "délután",
    "then_later_afternoon": "késő délután",
    "then_evening": "este",
    "then_later_evening": "késő este",
    "this_morning": "ma délelőtt",
    "this_afternoon": "ma délután",
    "this_evening": "ma este",
    "tonight": "ma éjjel",
    "this_morning_by": "délelőttre",
    "this_afternoon_by": "délutánra",
    "this_evening_by": "estére",
    "tonight_by": "késő estére",
    "tomorrow_morning_by": "holnap reggelre",
    "tomorrow_afternoon_by": "holnap délutánra",
    "tomorrow_evening_by": "holnap estére",
    "sky_clearing": "{time} kitisztul az ég",
    "sky_clouding": "{time} beborul az ég",
    "on_full_day": "{day}",
    # The hedges as HungaroMet writes them: "zápor előfordulhat", "eső
    # valószínű", "eső várható"
    "rain_next_chance": "{time} {desc} előfordulhat",
    "rain_next_likely": "{time} {desc} valószínű",
    "rain_next": "{time} {desc} várható",
    # "csütörtökön és pénteken", "szombattól hétfőig": the days' forms
    # are in DAY_SPANS
    "on_two_days": "{first} és {second}",
    "from_day_to_day": "{first} {last}",
    "rain_run_heaviest": "{sentence}, legerősebben {day}",
    "tomorrow_and_day": "holnap és {second}",
    "from_tomorrow_to_day": "holnaptól {last}",
    "on_tomorrow": "holnap",
    "rain_run_with": "{sentence}, {day} {with} is",
    "rain_run_then": "{sentence}, majd {day} {with}",
    "rain_run_heaviest_with": "{sentence}, legerősebben {day}, amikor {with} is lehet",
    "gusts_to": "{time} {speed} széllökések várhatók",
    "with_gusts": "{sentence}, {speed} széllökésekkel",
    "freeze_tonight": "{time} fagypont alá, {temp}ig süllyed a hőmérséklet",
    "feels_ahead_hot": "A hőérzet {time} akár {temp} is lehet",
    "feels_ahead_hot_humid": "A magas páratartalom miatt a hőérzet {time} akár {temp} is lehet",
    "feels_ahead_hot_sun": "A napsütés miatt a hőérzet {time} akár {temp} is lehet",
    "feels_ahead_cold": "A hőérzet {time} akár {temp} is lehet",
    "feels_ahead_cold_wind": "A szél miatt a hőérzet {time} akár {temp} is lehet",
    "past_precip": "Az elmúlt 24\u00a0órában {amt} {ptype} hullott",
    "snow": "hó",
    "rain": "eső",
    # Freezing rain and drizzle, which the "Mix" days hold
    "mixed_precip": "ónos csapadék",
    "Snow": "Hó",
    "Rain": "Eső",
    "Mix": "Ónos eső",
    "q_to_close": "q: bezárás",
    "o_to_open": "o: megnyitás böngészőben",
    "scroll": "görgetés",
    "space_to_now": "szóköz: vissza a jelenhez",
    "hist_near_avg": "átlagos",
    # "3°-kal": the degree sign is read "fok"
    "hist_above_avg": "{diff}-kal az átlag felett",
    "hist_below_avg": "{diff}-kal az átlag alatt",
    "avg": "átlag",
    "of_water": "{amt} víz",
}


# HungaroMet's categories of cloud: derült, gyengén, közepesen, erősen
# felhős, borult
CONDITIONS = {
    0: "Derült", 1: "Gyengén felhős", 2: "Közepesen felhős", 3: "Borult",
    45: "Köd", 48: "Zúzmarás köd",
    51: "Gyenge szitálás", 53: "Szitálás", 55: "Erős szitálás",
    56: "Ónos szitálás", 57: "Ónos szitálás",
    61: "Gyenge eső", 63: "Eső", 65: "Erős eső",
    66: "Ónos eső", 67: "Ónos eső",
    71: "Gyenge havazás", 73: "Havazás", 75: "Erős havazás", 77: "Hószemcse",
    80: "Gyenge zápor", 81: "Zápor", 82: "Erős zápor",
    85: "Hózápor", 86: "Erős hózápor",
    95: "Zivatar", 96: "Zivatar", 99: "Zivatar",
    "mostly_cloudy": "Erősen felhős",
}


# Singular, as HungaroMet has them: "délután zápor valószínű"
PRECIP = {
    51: "gyenge szitálás", 53: "szitálás", 55: "erős szitálás",
    56: "ónos szitálás", 57: "ónos szitálás",
    61: "gyenge eső", 63: "eső", 65: "erős eső",
    66: "ónos eső", 67: "ónos eső",
    71: "gyenge havazás", 73: "havazás", 75: "erős havazás", 77: "hószemcse",
    80: "gyenge zápor", 81: "zápor", 82: "erős zápor",
    85: "hózápor", 86: "erős hózápor",
    95: "zivatar", 96: "zivatar", 99: "zivatar",
}


# Showers and storms form rather than begin, and last the day as "egész
# nap zápor várható"
PRECIP_CLASSES = {"_zt": {80, 81, 82, 85, 86, 95, 96, 99}}


# What is falling now, with the article: "az eső", "a havazás"
PRECIP_DEFINITES = {
    51: "a gyenge szitálás", 53: "a szitálás", 55: "az erős szitálás",
    56: "az ónos szitálás", 57: "az ónos szitálás",
    61: "a gyenge eső", 63: "az eső", 65: "az erős eső",
    66: "az ónos eső", 67: "az ónos eső",
    71: "a gyenge havazás", 73: "a havazás", 75: "az erős havazás", 77: "a hószemcse",
    80: "a gyenge zápor", 81: "a zápor", 82: "az erős zápor",
    85: "a hózápor", 86: "az erős hózápor",
    95: "a zivatar", 96: "a zivatar", 99: "a zivatar",
}


# A turn to each, as the verb phrase the turn takes: rain goes over
# into snow ("havazásba megy át"), as the forecasts say; showers
# strengthen into storms ("zivatarrá erősödik").  The week sentence's
# {with_art} is not used, so these are the turn's alone.
PRECIP_PARTITIVES = {
    51: "gyenge szitálásba megy át", 53: "szitálásba megy át",
    55: "erős szitálásba megy át",
    56: "ónos szitálásba megy át", 57: "ónos szitálásba megy át",
    61: "gyenge esőbe megy át", 63: "esőbe megy át", 65: "erős esőbe megy át",
    66: "ónos esőbe megy át", 67: "ónos esőbe megy át",
    71: "gyenge havazásba megy át", 73: "havazásba megy át",
    75: "erős havazásba megy át", 77: "hószemcsébe megy át",
    80: "gyenge záporba megy át", 81: "záporba megy át", 82: "erős záporba megy át",
    85: "hózáporba megy át", 86: "erős hózáporba megy át",
    95: "zivatarrá erősödik", 96: "zivatarrá erősödik", 99: "zivatarrá erősödik",
}


# "On" a day is its superessive: hétfőn, szerdán, pénteken; Sunday
# stays as it is.  The abbreviations take no ending, so the full forms
# stand in.
ON_DAY = {0: "hétfőn", 1: "kedden", 2: "szerdán", 3: "csütörtökön", 4: "pénteken",
          5: "szombaton", 6: "vasárnap"}


ON_FULL_DAY = {0: "hétfőn", 1: "kedden", 2: "szerdán", 3: "csütörtökön", 4: "pénteken",
               5: "szombaton", 6: "vasárnap"}


# "csütörtökön és pénteken", "szombattól hétfőig"
DAY_SPANS = {
    "and_first": {0: "hétfőn", 1: "kedden", 2: "szerdán", 3: "csütörtökön", 4: "pénteken",
                  5: "szombaton", 6: "vasárnap"},
    "and_second": {0: "hétfőn", 1: "kedden", 2: "szerdán", 3: "csütörtökön", 4: "pénteken",
                   5: "szombaton", 6: "vasárnap"},
    "from": {0: "hétfőtől", 1: "keddtől", 2: "szerdától", 3: "csütörtöktől", 4: "péntektől",
             5: "szombattól", 6: "vasárnaptól"},
    "to": {0: "hétfőig", 1: "keddig", 2: "szerdáig", 3: "csütörtökig", 4: "péntekig",
           5: "szombatig", 6: "vasárnapig"},
}


# A place name takes no ending: it is the owner ("Budapest
# időjárása") or stands alone after a colon
LOCATIONS = {
    "locations": "Helyek",
    "add": "Hely hozzáadása",
    "clear": "Legutóbbi helyek törlése",
    "loading": "{name} betöltése…",
    "failed": "Nem sikerült betölteni {name} időjárását. Próbálja újra.",
    "save": "{name} mentése alapértelmezettként",
    "saved": "{name} lett az alapértelmezett hely minden nézetben.",
    "save_failed": "Nem sikerült menteni az alapértelmezett helyet. Próbálja újra.",
}


RADAR = {
    "loading": "betöltés…",
    "hint": "szóköz lejátszás/szünet · görgetés/←→ léptetés · +/- nagyítás · húzás / wasd mozgatás · c hőmérséklet · W szél · t téma · S műhold · q kilépés",
    "theme": "téma",
    "now": "most",
    # "Budapesttől 12 km-re északkeletre" would put -tól on the place;
    # the place comes first, and the distance after a comma
    "near": "{name}, {dist} {unit} {dir}",
    # É, K, D, Ny, and between them ÉK, DK, DNy, ÉNy; the sixteen points
    # join them as Hungarian does, ÉÉK, KDK, NyDNy
    "compass": "É ÉK K DK D DNy Ny ÉNy",
    "forecast": "előrejelzés",
    "echo_pct": "{pct}% visszaverődés",
    "cloud_pct": "{pct}% felhőzet",
    "radar_unavailable": "a radar nem érhető el ({err})",
    "no_frames": "nincsenek radarképek",
}


MAPS = {
    "unit_m": "m",
    "unit_km": "km",
    "unit_ft": "láb",
    "unit_mi": "mérföld",
    "hint": "wasd · v nézet · / keresés · ? súgó",
    "hint_route": "D útvonal · n törlés",
    "unavailable": "a domborzat nem érhető el ({err})",
    "streets_unavailable": "az utcatérkép csempéi nem érhetők el ({err})",
    "offline": "nincsenek csempék",
    "mode_terrain": "domborzat",
    "mode_street": "utca",
    # "a Nap Budapest fölött" would need the place in its own form; the
    # Sun is at the zenith, and the place follows a colon
    "sun_over": "a Nap a zenitben: {place}",
    "search_prompt": "helyek keresése",
    "search_dest_prompt": "úti cél keresése",
    "search_origin_prompt": "kiindulási pont keresése",
    "search_hint": "↑↓ kiválasztás · enter ugrás · esc bezárás",
    "search_none": "nincs találat",
    "search_error": "a keresés nem érhető el",
    "dir_wait": "útvonaltervezés…",
    "dir_none": "nincs útvonal",
    "dir_unavailable": "az útvonaltervezés nem érhető el",
    "profile_car": "autóval",
    "profile_bike": "kerékpárral",
    "profile_foot": "gyalog",
    "dir_from": "honnan",
    "dir_to": "hová",
    "dir_mode": "mód",
    "steps_hint": "↑↓ lépés · esc bezárás",
    "help_zoom_pointer": "nagyítás a mutatónál",
    "help_reset": "vissza a kezdőnézethez",
    "help_view": "utca · domborzat",
    "help_labels": "feliratok és vonalak",
    "help_sky": "napfény · felhők",
    "help_spin": "a földgömb forgatása",
    "help_directions": "útvonal",
    "help_origin": "kiindulási pont megadása",
    "help_profile": "közlekedési mód",
    "poi_airport": "repülőtér",
    "poi_peak": "csúcs",
    "poi_station": "állomás",
    "poi_hospital": "kórház",
    "poi_civic": "hivatal · iskola",
    "poi_lodging": "szállás",
    "poi_notable": "múzeum · látnivaló",
    "poi_worship": "templom · imahely",
    "poi_ferry": "komp · kikötő",
    "poi_other": "hely",
    "poi_capital": "főváros",
    "hov_motorway": "autópálya",
    "hov_ramp": "felhajtó",
    "hov_trunk": "gyorsforgalmi út",
    "hov_primary": "főút",
    "hov_secondary": "mellékút",
    "hov_minor": "utca",
    "hov_service": "szervizút",
    "hov_path": "ösvény",
    "hov_rail": "vasútvonal",
    "hov_transit": "tömegközlekedési vonal",
    "hov_ferry": "kompjárat",
    "hov_river": "folyó",
    "hov_stream": "patak",
    "hov_runway": "futópálya",
    "hov_taxiway": "gurulóút",
    "hov_border": "határ",
    "hov_coast": "partvonal",
    "hov_water": "víz",
    "hov_park": "park",
    "hov_building": "épület",
    "hov_urban": "beépített terület",
}


TIDES = {
    "space_to_now": "szóköz: vissza a jelenhez",
    "waves": "Hullámok",
    "swell": "Hullámzás",
    "tide_model": "Open-Meteo árapálymodell",
    "period": " @ {s}\u00a0mp",
    "no_tides": "Ehhez a helyhez nincs árapály-előrejelzés: {name}.",
    "load_failed": "Nem sikerült betölteni az árapály-adatokat: {name}. Próbálja újra.",
    "high": "Dagály",
    "low": "Apály",
    "no_data": "Nincs árapály-adat",
    "flood_stage": "árvízi szint",
    "highest_on": "legmagasabb {h} {date}",
    "predicted": "előrejelzés",
    "measured": "mérés",
    "modeled": "modell",
    "makeup_headline": "Ami itt az árapályt mozgatja",
    "makeup_twice": "Naponta kétszer",
    "makeup_once": "Naponta egyszer",
    "makeup_moon": "A Hold",
    "makeup_sun": "A Nap",
    "makeup_distance": "A Hold távolsága",
    # "A Hold dőlése" would read as the Moon itself leaning over; the
    # tilt is given to its path, and to the Sun's
    "makeup_moon_tilt": "A holdpálya dőlése",
    "makeup_sun_tilt": "A nappálya dőlése",
    "makeup_key_size": "Minden magasság az adott okból eredő apály–dagály különbség fele.",
    "makeup_key_gain": "A × ezt azzal veti össze, amit ugyanez az ok egy ideális óceánban keltene.",
    "makeup_key_sea": "A tenger alakja és mélysége változtat azon, hogy ez itt mekkora lesz.",
    "makeup_key_phases": "újhold, telihold",
    # f for földközel, the Hungarian for perigee
    "makeup_mark_near": "f",
    "makeup_key_near": "a Hold földközelben",
    "makeup_key_far": "legészakabbra, legdélebbre",
    "makeup_key_equator": "az Egyenlítő felett",
}


# Hungarian counts in the singular after a number: "3 nap múlva"
SUNSHINE = {
    "today": "ma",
    "in_day": "{n} nap múlva",
    "in_days": "{n} nap múlva",
    "day_ago": "{n} napja",
    "days_ago": "{n} napja",
    "sky_night": "éjszaka",
    "sky_astronomical": "csillagászati szürkület",
    "sky_nautical": "navigációs szürkület",
    "sky_civil": "polgári szürkület",
    "sky_day": "nappal",
    "midnight_sun": "éjféli nap",
    "polar_night": "sarki éjszaka",
    "solar_noon": "delelés",
    "sunrise": "napkelte",
    "sunset": "napnyugta",
}


HOURS = {"night": "éjszaka", "in_time": "{dur} múlva", "koku": "1 koku", "fast": "böjt",
         "midnight": "éjfél", "iftar": "iftár"}


MOON = {
    "illuminated": "megvilágítottság: {pct}%",
    # The age has a decimal, so it takes no ordinal stop: "16,6/29,5 nap"
    "age": "{age}/{total} nap",
    "lunar_age": "holdkor: {age} nap",
    "up_now": "Most a horizont felett",
    # "12°-kal": the degree sign is read "fok"
    "above_horizon": "{alt}°-kal a horizont felett",
    "below_horizon": "A horizont alatt",
    "moonrise": "Holdkelte",
    "moonset": "Holdnyugta",
    "in_days": "{days} nap múlva",
    "begins_at_sunset": "napnyugtakor kezdődik",
    "in_time": "{dur} múlva",
    "year_day": "{n}. nap / {total}",
    "week_of_summer": "a nyár {n}. hete",
    "week_of_winter": "a tél {n}. hete",
    # The almanac's növő hold and fogyó hold
    "light_of_moon": "növő hold",
    "dark_of_moon": "fogyó hold",
    "good_for": "Kedvező: {things}",
    "hold_off": "Kedvezőtlen: {things}",
    "light_good": "föld feletti növények vetése, oltás, átültetés",
    "light_hold": "gyökérzöldségek",
    "dark_good": "gyökérzöldségek, metszés, gyomlálás",
    "dark_hold": "föld feletti növények vetése",
    "solunar_major": "Szolunáris fő",
    "solunar_minor": "mellék",
    "spring_equinox": "Tavaszi napéjegyenlőség",
    "summer_solstice": "Nyári napforduló",
    "autumn_equinox": "Őszi napéjegyenlőség",
    "winter_solstice": "Téli napforduló",
}


SKY = {
    "sun": "Nap", "moon": "Hold",
    "mercury": "Merkúr", "venus": "Vénusz", "mars": "Mars",
    "jupiter": "Jupiter", "saturn": "Szaturnusz", "uranus": "Uránusz",
    "neptune": "Neptunusz",
    "facing": "{dir} felé",
    "field_of_view": "{deg}° széles",
    "overhead": "fejünk felett",
    "planets_none": "nincs bolygó a horizont felett",
    "star": "csillag",
    "search_prompt": "név vagy katalógusszám",
    "search_none": "nincs ilyen nevű égitest",
    # -kor keeps its shape after any time: "02:14-kor"
    "rises_at": "{name} {time}-kor kel, {dir} irányban",
    "never_rises": "{name} innen sosem kel fel",
    "search_jump": "újabb enter: ugrás erre az időpontra",
    "tradition": "hagyomány",
}


# The cultures' titles as adjectives, lower case as Hungarian writes
# them; a people's own name stays as it is
SKY_CULTURES = {
    "anutan": "anutai",
    "belarusian": "fehérorosz",
    "blackfoot": "feketeláb",
    "boorong": "Boorong",
    "bugis": "bugis",
    "chinese": "kínai",
    "chinese-modern": "kínai (mai)",
    "hawaiian": "hawaii",
    "indian": "indiai (védikus)",
    "japanese": "japán holdházak",
    "mandar": "mandar",
    "maori": "maori",
    "mongolian": "mongol",
    "norse": "skandináv",
    "romanian": "román",
    "ruelle": "Ruelle",
    "sami": "számi",
    "siberian": "szibériai",
    "tongan": "tongai",
    "tukano": "tukano",
    "snt": "nyugati (Sky & Telescope)",
    "rey": "nyugati (H.A.Rey)",
}
