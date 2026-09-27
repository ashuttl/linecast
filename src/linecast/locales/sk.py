"""Slovak.

en.py is the reference, with every key and notes on each; a key
left out here reads in English.

The forecast prose follows the wording of the Slovak Hydrometeorological
Institute (SHMÚ): jasno, polojasno, oblačno, zamračené; mrholenie, dážď,
sneženie, prehánky, búrky; ráno, dopoludnia, popoludní, večer, v noci.
"""


SETTINGS = {
    "decimal": ",",
    # Unlike Czech, Slovak spaces the sign whether it stands for the
    # noun or the adjective: "40 %", "40 % roztok" (STN 01 6910).
    "percent": "{n}\u00a0%",
    # CLDR's Slovak rule is the Czech one: 1, then 2 to 4, then the rest.
    "plural": "czech",
    # SHMÚ gives the wind in metres per second, with km/h in brackets:
    # "slabý vietor do 5 m/s (20 km/h)".
    "metric_wind": "m/s",
}


DAY_NAMES = ["po", "ut", "st", "št", "pi", "so", "ne"]


FULL_DAY_NAMES = ["pondelok", "utorok", "streda", "štvrtok", "piatok", "sobota", "nedeľa"]


# The nominative abbreviations, as CLDR's stand-alone forms have them
MONTHS = ["jan", "feb", "mar", "apr", "máj", "jún",
          "júl", "aug", "sep", "okt", "nov", "dec"]


MONTH_DAY = "{day}. {month}"


MOON_PHASES = ["Nov", "Dorastajúci kosák", "Prvá štvrť", "Dorastajúci Mesiac",
               "Spln", "Ubúdajúci Mesiac", "Posledná štvrť", "Ubúdajúci kosák"]


# Commands in the infinitive, as Slovak software labels them
HELP = {
    "hint_help": "pomocník",
    "key_wheel": "koliesko",
    "key_space": "medzerník",
    # Microsoft's Slovak for hovering is "ukázať" (myšou na)
    "key_hover": "ukázanie",
    "key_click": "kliknutie",
    "key_drag": "ťahanie",
    "key_enter": "enter",
    "forecast": "prechádzať predpoveď",
    "now": "späť na súčasnosť",
    "alert": "prečítať výstrahu",
    "browser": "otvoriť výstrahu v prehliadači",
    "refresh": "obnoviť predpoveď",
    "time30": "posunúť čas o 30 minút",
    "time15": "posunúť čas o 15 minút",
    "year": "zobrazenie dňa / roka",
    "bar_colors": "farby stĺpcov",
    "sun_times": "časy východu a západu slnka",
    "turn_moon": "otočiť Mesiac",
    "calendar": "kotúč / kalendár",
    "months": "o mesiac dopredu alebo dozadu",
    "moon_times": "fáza a časy východu / západu",
    "day": "otvoriť deň v zobrazení kotúča",
    "look": "rozhliadnuť sa",
    "target": "k cieľu; znova k času východu",
    "figures": "obrazce / názvy súhvezdí",
    "cultures": "tradície oblohy",
    "play_time": "chod času: hodina / deň / týždeň za sekundu",
    "compass": "pohľad na S, SV, V, JV, J, JZ, Z, SZ",
    "zenith": "pohľad priamo nahor",
    "moon": "pohľad na Mesiac, keď je nad obzorom",
    "frames": "krokovať snímky a pozastaviť",
    "play": "prehrať / pozastaviť (pauza vráti na súčasnosť)",
    "temperature": "vrstva teploty",
    "wind": "vrstva vetra",
    "alerts": "vrstva výstrah",
    "theme": "zvoliť motív",
    "satellite": "radar / družica",
}


WEATHER = {
    # A day of the month alone is an ordinal, with its full stop: "po 28."
    "day_of_month": "{d}.",
    "today": "Dnes",
    "today_short": "dnes",
    # "z {day}" would decline the weekday (zo stredy); the day sits
    # in brackets instead.
    "forecast_stale": "Táto predpoveď je zastaraná ({day}); novšiu sa nepodarilo získať.",
    "forecast_stale_at": "Táto predpoveď je zastaraná ({day}); novšiu sa o {time} nepodarilo získať.",
    "forecast_fetching": "Získava sa novšia predpoveď…",
    "alerts_unavailable": "Výstrahy sa nepodarilo overiť.",
    "alerts_stale": "Stav výstrah: {when}; novšie sa nepodarilo získať.",
    "retry_run": "Pre nový pokus spustite znova.",
    "retry_key": "Pre nový pokus stlačte r.",
    "credit_forecast": "Údaje o počasí: {source}",
    "credit_alerts": "Výstrahy: {source}",
    "credit_current": "Aktuálne počasie: {source}",
    # "na stanici {place}" would decline the station's name; it follows
    # a colon.
    "credit_observed": "Pozorované o {time}: {place}, {distance} odtiaľto",
    "metric_unit_sep": "\u00a0",
    "unit_kmh": "km/h",
    "unit_ms": "m/s",
    "unit_mph": "mph",
    "unit_mm": "mm",
    "unit_km": "km",
    "unit_mi": "mi",
    "unit_cm": "cm",
    "feels": "pocitovo",
    "wind": "Vietor",
    "gusts": "nárazy",
    "humidity": "Vlhkosť",
    "chance": "pravdepodobnosť {p}",
    # The kind of precipitation takes the genitive after
    # "pravdepodobnosť" and after an amount alike: dažďa, snehu.
    "chance_of": "pravdepodobnosť {what} {p}",
    "amount_between": "{amount} medzi {a} a {b}",
    "amount_all_day": "{amount} počas dňa",
    "cloud": "Oblačnosť {p}",
    # The adverb, which agrees with nothing: "najsilnejšie okolo 16:00"
    "heaviest_around": "najsilnejšie okolo {time}",
    "dew_pt": "Rosný bod",
    "uv": "UV",
    "aqi": "AQI",
    "precip_inch": "″",
    "until": "do {time}",
    "sentence_end": ".",
    "sentence_join": ". ",
    # One verb for cooler and colder alike, so no "_cold" forms
    "feels_humid": "Vysoká vlhkosť zvyšuje pocitovú teplotu",
    "feels_sun": "Slnko zvyšuje pocitovú teplotu",
    "feels_wind": "Vietor znižuje pocitovú teplotu",
    "feels_dry": "Suchý vzduch znižuje pocitovú teplotu",
    # The comparison agrees with "teplota", feminine; "o" takes the
    # accusative: o 1 stupeň, o 2 stupne, o 5 stupňov.
    "degrees": "{n}\u00a0stupňov",
    "degrees_one": "{n}\u00a0stupeň",
    "degrees_few": "{n}\u00a0stupne",
    "same_temp": "približne rovnaká ako {ref_day}",
    "bit_warmer": "o niečo vyššia ako {ref_day}",
    "bit_cooler": "o niečo nižšia ako {ref_day}",
    "warmer": "vyššia ako {ref_day}",
    "cooler": "nižšia ako {ref_day}",
    "much_warmer": "oveľa vyššia ako {ref_day}",
    "much_cooler": "oveľa nižšia ako {ref_day}",
    "warmer_by": "o {diff} vyššia ako {ref_day}",
    "cooler_by": "o {diff} nižšia ako {ref_day}",
    "today_subj": "Dnešná najvyššia teplota",
    "tomorrow_subj": "Zajtrajšia najvyššia teplota",
    "yesterday": "včerajšia",
    "today_ref": "dnešná",
    "will_be": "{subject} bude {comparison}",
    "will_be_then": "Najvyššia teplota bude {comparison}",
    # Precipitation line.  The verbs are in the future, which does not
    # mark gender, so only the plural nouns (prehánky, búrky, snehové
    # zrná) need a form of their own, "_pl".  What sets in comes last,
    # where Slovak puts new information: "Okolo 16:00 pravdepodobne
    # začne dážď".  A turn is "prejde do" and the genitive: "prejde do
    # dažďa".  After a turn, the end is of the precipitation, "zrážky
    # ustanú", as SHMÚ's "ustávanie zrážok".
    "ending": "{desc} ustane {time}",
    "ending_pl": "{desc} ustanú {time}",
    "continuing": "{desc} potrvá celý deň",
    "continuing_pl": "{desc} potrvajú celý deň",
    "ending_becoming": "{desc} {peak_time} prejde {peak_art} a zrážky ustanú {time}",
    "ending_becoming_pl": "{desc} {peak_time} prejdú {peak_art} a zrážky ustanú {time}",
    "continuing_becoming": "{desc} {peak_time} prejde {peak_art} a zrážky potrvajú celý deň",
    "continuing_becoming_pl": "{desc} {peak_time} prejdú {peak_art} a zrážky potrvajú celý deň",
    "starting": "{time} pravdepodobne začne {desc}",
    "starting_pl": "{time} pravdepodobne začnú {desc}",
    "starting_becoming": "{time} pravdepodobne začne {desc} a {peak_time} prejde {peak_art}",
    "starting_becoming_pl": "{time} pravdepodobne začnú {desc} a {peak_time} prejdú {peak_art}",
    # In a part of the day, the noun alone, as SHMÚ writes it: "Večer
    # pravdepodobne slabé mrholenie"
    "starting_span": "{time} pravdepodobne {desc}",
    "starting_span_becoming": "{time} pravdepodobne {desc}, {peak_time} {peak}",
    "starting_span_heavier": "{time} pravdepodobne {desc}, {peak_time} zosilnie",
    "starting_span_heavier_pl": "{time} pravdepodobne {desc}, {peak_time} zosilnejú",
    "starting_chance": "{time} možno {desc}",
    "starting_chance_becoming": "{time} možno {desc}, {peak_time} {peak}",
    "starting_chance_heavier": "{time} možno {desc}, {peak_time} môže zosilnieť",
    "starting_chance_heavier_pl": "{time} možno {desc}, {peak_time} môžu zosilnieť",
    "starting_sure": "{time} začne {desc}",
    "starting_sure_pl": "{time} začnú {desc}",
    "starting_sure_becoming": "{time} začne {desc} a {peak_time} prejde {peak_art}",
    "starting_sure_becoming_pl": "{time} začnú {desc} a {peak_time} prejdú {peak_art}",
    "starting_sure_heavier": "{time} začne {desc} a {peak_time} zosilnie",
    "starting_sure_heavier_pl": "{time} začnú {desc} a {peak_time} zosilnejú",
    "continuing_night": "{desc} potrvá celú noc",
    "continuing_night_pl": "{desc} potrvajú celú noc",
    "continuing_night_becoming": "{desc} {peak_time} prejde {peak_art} a zrážky potrvajú celú noc",
    "continuing_night_becoming_pl": "{desc} {peak_time} prejdú {peak_art} a zrážky potrvajú celú noc",
    "ending_heavier": "{desc} {peak_time} zosilnie a ustane {time}",
    "ending_heavier_pl": "{desc} {peak_time} zosilnejú a ustanú {time}",
    "continuing_heavier": "{desc} {peak_time} zosilnie a potrvá celý deň",
    "continuing_heavier_pl": "{desc} {peak_time} zosilnejú a potrvajú celý deň",
    "continuing_night_heavier": "{desc} {peak_time} zosilnie a potrvá celú noc",
    "continuing_night_heavier_pl": "{desc} {peak_time} zosilnejú a potrvajú celú noc",
    "starting_heavier": "{time} pravdepodobne začne {desc} a {peak_time} zosilnie",
    "starting_heavier_pl": "{time} pravdepodobne začnú {desc} a {peak_time} zosilnejú",
    "more_later": "{time} opäť {desc}",
    "snow_total": "{time} napadne asi {amt} snehu",
    # Fog "sa rozpustí", as a Slovak forecast has it lifting
    "fog_ending": "Hmla sa rozpustí {time}",
    "fog_continuing": "Hmla sa udrží celý deň",
    "fog_continuing_night": "Hmla sa udrží celú noc",
    "fog_starting": "{time} hmla",
    "fog_starting_ending": "{time} hmla, {end} sa rozpustí",
    # "O hodinu" is Slovak's "in an hour"; "za hodinu" would be "within".
    "shortly": "čoskoro",
    "in_about_an_hour": "asi o hodinu",
    "in_a_couple_hours": "o pár hodín",
    "around": "okolo {time}",
    "around_noon": "okolo poludnia",
    "same_time": "vtedy",
    "same_part_later": "neskôr",
    "overnight": "v noci",
    # The small hours to eight are "ráno"; eight to noon "dopoludnia"
    "early_tomorrow_morning": "zajtra ráno",
    "tomorrow_morning": "zajtra dopoludnia",
    "tomorrow_afternoon": "zajtra popoludní",
    "tomorrow_evening": "zajtra večer",
    # Beyond tomorrow the prose names the day in full, in the accusative
    # after "v", "vo štvrtok"; see ON_DAY.
    "on_day": "v {day}",
    "then_early_morning": "ráno",
    "then_morning": "dopoludnia",
    "then_later_morning": "neskôr dopoludnia",
    "then_afternoon": "popoludní",
    "then_later_afternoon": "neskôr popoludní",
    "then_evening": "večer",
    "then_later_evening": "neskôr večer",
    "this_morning": "dnes dopoludnia",
    "this_afternoon": "dnes popoludní",
    "this_evening": "dnes večer",
    "tonight": "dnes v noci",
    # "By" a part of the day: the snow that is down by then
    "this_morning_by": "do poludnia",
    "this_afternoon_by": "do večera",
    "this_evening_by": "počas večera",
    "tonight_by": "do polnoci",
    "tomorrow_morning_by": "do zajtrajšieho poludnia",
    "tomorrow_afternoon_by": "do zajtrajšieho večera",
    "tomorrow_evening_by": "zajtra do polnoci",
    "sky_clearing": "{time} sa vyjasní",
    "sky_clouding": "{time} sa zamračí",
    "on_full_day": "v {day}",
    # The week, in SHMÚ's nouns without a verb: "V piatok pravdepodobne
    # dážď"
    "rain_next_chance": "{time} možno {desc}",
    "rain_next_likely": "{time} pravdepodobne {desc}",
    "rain_next": "{time} {desc}",
    "on_two_days": "{first} a {second}",
    "from_day_to_day": "od {first} do {last}",
    "tomorrow_and_day": "zajtra a {second}",
    "from_tomorrow_to_day": "od zajtra do {last}",
    "on_tomorrow": "zajtra",
    # "Najviac zrážok", the most precipitation, rather than an adjective
    # that would have to agree with the first noun of a run whose
    # heaviest day may be of the second: "V piatok dážď, potom v sobotu
    # a v nedeľu sneženie, najviac zrážok v sobotu".
    "rain_run_heaviest": "{sentence}, najviac zrážok {day}",
    "rain_run_with": "{sentence}, {day} aj {with}",
    "rain_run_then": "{sentence}, potom {day} {with}",
    "rain_run_heaviest_with": "{sentence}, najviac zrážok {day}, vtedy aj {with}",
    "gusts_to": "{time} nárazy vetra do {speed}",
    "with_gusts": "{sentence}, s nárazmi vetra do {speed}",
    # "Na" takes the accusative: na −1 stupeň, na −3 stupne, na −5 stupňov
    "freeze_tonight": "{time} teplota klesne pod bod mrazu, až na {temp}",
    "feels_ahead_hot": "{time} pocitová teplota vystúpi až na {temp}",
    "feels_ahead_hot_humid": "{time} vysoká vlhkosť zvýši pocitovú teplotu až na {temp}",
    "feels_ahead_hot_sun": "{time} slnko zvýši pocitovú teplotu až na {temp}",
    "feels_ahead_cold": "{time} pocitová teplota klesne až na {temp}",
    "feels_ahead_cold_wind": "{time} vietor zníži pocitovú teplotu až na {temp}",
    "past_precip": "Za posledných 24\u00a0hodín spadlo {amt} {ptype}",
    "snow": "snehu",
    "rain": "dažďa",
    "mixed_precip": "zmiešaných zrážok",
    "Snow": "Sneh",
    "Rain": "Dážď",
    "Mix": "Zmiešané",
    "q_to_close": "q zavrie",
    "o_to_open": "o otvorí v prehliadači",
    "scroll": "posun",
    "space_to_now": "medzerník: späť na súčasnosť",
    "hist_near_avg": "okolo priemeru",
    "hist_above_avg": "o {diff} nad priemerom",
    "hist_below_avg": "o {diff} pod priemerom",
    "avg": "priemer",
    "of_water": "{amt} vody",
}


# SHMÚ's terms: jasno, takmer jasno, polojasno, oblačno, zamračené
CONDITIONS = {
    0: "Jasno", 1: "Takmer jasno", 2: "Polojasno", 3: "Zamračené",
    45: "Hmla", 48: "Mrznúca hmla",
    51: "Slabé mrholenie", 53: "Mrholenie", 55: "Silné mrholenie",
    56: "Mrznúce mrholenie", 57: "Mrznúce mrholenie",
    61: "Slabý dážď", 63: "Dážď", 65: "Silný dážď",
    66: "Mrznúci dážď", 67: "Mrznúci dážď",
    71: "Slabé sneženie", 73: "Sneženie", 75: "Silné sneženie", 77: "Snehové zrná",
    80: "Slabé prehánky", 81: "Prehánky", 82: "Silné prehánky",
    85: "Snehové prehánky", 86: "Silné snehové prehánky",
    95: "Búrka", 96: "Búrka", 99: "Búrka",
    "mostly_cloudy": "Oblačno",
}


# Storms are plural in the prose, as SHMÚ has them ("ojedinele
# búrky"); the header names the one overhead.
PRECIP = {
    51: "slabé mrholenie", 53: "mrholenie", 55: "silné mrholenie",
    56: "mrznúce mrholenie", 57: "mrznúce mrholenie",
    61: "slabý dážď", 63: "dážď", 65: "silný dážď",
    66: "mrznúci dážď", 67: "mrznúci dážď",
    71: "slabé sneženie", 73: "sneženie", 75: "silné sneženie", 77: "snehové zrná",
    80: "slabé prehánky", 81: "prehánky", 82: "silné prehánky",
    85: "snehové prehánky", 86: "silné snehové prehánky",
    95: "búrky", 96: "búrky", 99: "búrky",
}


PRECIP_CLASSES = {"_pl": {77, 80, 81, 82, 85, 86, 95, 96, 99}}


# What the rain turns to, after "prejde do", in the genitive.  A turn
# is to one storm: "prejde do búrky".
PRECIP_PARTITIVES = {
    51: "do slabého mrholenia", 53: "do mrholenia", 55: "do silného mrholenia",
    56: "do mrznúceho mrholenia", 57: "do mrznúceho mrholenia",
    61: "do slabého dažďa", 63: "do dažďa", 65: "do silného dažďa",
    66: "do mrznúceho dažďa", 67: "do mrznúceho dažďa",
    71: "do slabého sneženia", 73: "do sneženia", 75: "do silného sneženia",
    77: "do snehových zŕn",
    80: "do slabých prehánok", 81: "do prehánok", 82: "do silných prehánok",
    85: "do snehových prehánok", 86: "do silných snehových prehánok",
    95: "do búrky", 96: "do búrky", 99: "do búrky",
}


# A day beyond tomorrow is named in full in a sentence, "v stredu", "vo
# štvrtok", not by its two-letter abbreviation.
ON_DAY = {0: "v pondelok", 1: "v utorok", 2: "v stredu", 3: "vo štvrtok",
          4: "v piatok", 5: "v sobotu", 6: "v nedeľu"}


ON_FULL_DAY = {0: "v pondelok", 1: "v utorok", 2: "v stredu", 3: "vo štvrtok",
               4: "v piatok", 5: "v sobotu", 6: "v nedeľu"}


# "V stredu a vo štvrtok", "od soboty do pondelka"
DAY_SPANS = {
    "and_first": {0: "v pondelok", 1: "v utorok", 2: "v stredu", 3: "vo štvrtok", 4: "v piatok", 5: "v sobotu", 6: "v nedeľu"},
    "and_second": {0: "v pondelok", 1: "v utorok", 2: "v stredu", 3: "vo štvrtok", 4: "v piatok", 5: "v sobotu", 6: "v nedeľu"},
    "from": {0: "pondelka", 1: "utorka", 2: "stredy", 3: "štvrtka", 4: "piatka", 5: "soboty", 6: "nedele"},
    "to": {0: "pondelka", 1: "utorka", 2: "stredy", 3: "štvrtka", 4: "piatka", 5: "soboty", 6: "nedele"},
}


# A place's name would decline after "pre" or as an object; it comes
# first, or is the subject.
LOCATIONS = {
    "locations": "Miesta",
    "add": "Pridať miesto",
    "clear": "Vymazať nedávne miesta",
    "loading": "Načítava sa {name}…",
    "failed": "{name}: počasie sa nepodarilo načítať. Skúste to znova.",
    "save": "Nastaviť ako predvolené: {name}",
    "saved": "{name} je teraz predvolené miesto pre všetky zobrazenia.",
    "save_failed": "Predvolené miesto sa nepodarilo uložiť. Skúste to znova.",
}


RADAR = {
    "loading": "načítava sa…",
    "hint": "medzerník prehrať/pauza · koliesko/←→ krok · +/- zoom · ťahanie / wasd · c teplota · W vietor · t motív · S družica · q koniec",
    "theme": "motív",
    "now": "teraz",
    # "12 km SV od Bratislavy" would put the genitive on the place name;
    # the place comes first, and the distance after a comma.
    "near": "{name}, {dist} {unit} {dir}",
    "compass": "S SV V JV J JZ Z SZ",
    "forecast": "predpoveď",
    "echo_pct": "{pct}\u00a0% odraz",
    "cloud_pct": "{pct}\u00a0% oblačnosť",
    "radar_unavailable": "radar nie je k dispozícii ({err})",
    "no_frames": "žiadne snímky radaru",
}


MAPS = {
    "hint": "wasd · v zobrazenie · / hľadať · ? pomocník",
    "hint_route": "D trasa · n zmazať",
    "unavailable": "terén nie je k dispozícii ({err})",
    "streets_unavailable": "mapové dlaždice nie sú k dispozícii ({err})",
    "offline": "žiadne dlaždice",
    "mode_terrain": "terén",
    "mode_street": "ulice",
    # "slnko nad Bratislavou" would decline the place name; the sun is
    # at the zenith there, and the place follows a colon.
    "sun_over": "slnko v zenite: {place}",
    "search_prompt": "hľadať miesto",
    "search_dest_prompt": "hľadať cieľ",
    "search_origin_prompt": "hľadať východiskový bod",
    "search_hint": "↑↓ výber · enter prejsť · esc zavrieť",
    "search_none": "nič sa nenašlo",
    "search_error": "vyhľadávanie nie je k dispozícii",
    "dir_wait": "plánovanie trasy…",
    "dir_none": "žiadna trasa",
    "dir_unavailable": "plánovanie trasy nie je k dispozícii",
    "profile_car": "autom",
    "profile_bike": "na bicykli",
    "profile_foot": "pešo",
    "dir_from": "odkiaľ",
    "dir_to": "kam",
    "dir_mode": "spôsob",
    "steps_hint": "↑↓ krok · esc zavrieť",
    "help_title": "klávesy",
    "help_close": "esc zavrieť",
    "help_pan": "posunúť",
    "help_zoom_pointer": "priblížiť na mieste kurzora",
    "help_hover": "identifikovať",
    "help_zoom": "priblížiť / oddialiť",
    "help_reset": "späť na začiatok",
    "help_view": "ulice · terén",
    "help_labels": "popisy a čiary",
    "help_sky": "denné svetlo · oblačnosť",
    "help_spin": "otáčať glóbus",
    "help_search": "hľadať",
    "help_directions": "trasa",
    "help_origin": "nastaviť východiskový bod",
    "help_profile": "spôsob dopravy",
    "help_keys": "tento zoznam",
    "help_quit": "ukončiť",
    "poi_airport": "letisko",
    "poi_peak": "vrchol",
    "poi_station": "stanica",
    "poi_hospital": "nemocnica",
    "poi_civic": "úrad · škola",
    "poi_lodging": "ubytovanie",
    "poi_notable": "múzeum · pamätihodnosť",
    "poi_worship": "kostol · chrám",
    "poi_ferry": "kompa · prístav",
    "poi_other": "miesto",
    "poi_capital": "hlavné mesto",
    # The road classes as Slovakia numbers them, as OpenStreetMap's
    # Slovak tagging maps them: primary is a first-class road
    "hov_motorway": "diaľnica",
    "hov_ramp": "privádzač",
    "hov_trunk": "rýchlostná cesta",
    "hov_primary": "cesta I. triedy",
    "hov_secondary": "cesta II. triedy",
    "hov_minor": "ulica",
    "hov_service": "obslužná komunikácia",
    "hov_path": "chodník",
    "hov_rail": "železnica",
    "hov_transit": "linka MHD",
    "hov_ferry": "kompa",
    "hov_river": "rieka",
    "hov_stream": "potok",
    "hov_runway": "vzletová a pristávacia dráha",
    "hov_taxiway": "rolovacia dráha",
    "hov_border": "hranica",
    "hov_coast": "pobrežie",
    "hov_water": "voda",
    "hov_park": "park",
    "hov_building": "budova",
    "hov_urban": "zástavba",
}


TIDES = {
    "space_to_now": "medzerník: späť na súčasnosť",
    "waves": "Vlny",
    "swell": "Mŕtve vlnenie",
    "tide_model": "Slapový model Open-Meteo",
    "no_tides": "{name}: predpoveď prílivu a odlivu nie je k dispozícii.",
    "load_failed": "{name}: príliv a odliv sa nepodarilo načítať. Skúste to znova.",
}


SUNSHINE = {
    "today": "dnes",
    # "O" takes the accusative, "dni" to four and "dní" beyond; "pred"
    # the instrumental, whose plural is "dňami" for every count above one.
    "in_day": "o {n} deň",
    "in_days_few": "o {n} dni",
    "in_days": "o {n} dní",
    "day_ago": "pred {n} dňom",
    "days_ago_few": "pred {n} dňami",
    "days_ago": "pred {n} dňami",
    "sky_night": "noc",
    "sky_astronomical": "astronomický súmrak",
    "sky_nautical": "nautický súmrak",
    "sky_civil": "občiansky súmrak",
    "sky_astronomical_dawn": "astronomické svitanie",
    "sky_nautical_dawn": "nautické svitanie",
    "sky_civil_dawn": "občianske svitanie",
    "sky_day": "deň",
    "midnight_sun": "polnočné slnko",
    "polar_night": "polárna noc",
    "solar_noon": "pravé poludnie",
    "sunrise": "východ slnka",
    "sunset": "západ slnka",
}


HOURS = {"night": "noc", "in_time": "o {dur}", "koku": "1 koku", "fast": "pôst",
         "midnight": "polnoc", "iftar": "iftár"}


MOON = {
    "illuminated": "osvetlenie {pct}\u00a0%",
    "age": "deň {age} z {total}",
    "lunar_age": "vek Mesiaca {age} d",
    "up_now": "Nad obzorom",
    "above_horizon": "{alt}° nad obzorom",
    "below_horizon": "Pod obzorom",
    "moonrise": "Východ Mesiaca",
    "moonset": "Západ Mesiaca",
    "in_days": "o {days} d",
    # "Začínať sa", reflexive where nothing is begun by anyone
    "begins_at_sunset": "začína sa západom slnka",
    "in_time": "o {dur}",
    "year_day": "Deň {n} z {total}",
    "light_of_moon": "Mesiac dorastá",
    "dark_of_moon": "Mesiac ubúda",
    "good_for": "Vhodné: {things}",
    "hold_off": "Nevhodné: {things}",
    "light_good": "sejba nadzemných plodín, štepenie, presádzanie",
    "light_hold": "koreňová zelenina",
    "dark_good": "koreňová zelenina, rez, pletie",
    "dark_hold": "sejba nadzemných plodín",
    # Neuter, for an implied "obdobie"
    "solunar_major": "Solunárne hlavné",
    "solunar_minor": "vedľajšie",
    "spring_equinox": "Jarná rovnodennosť",
    "summer_solstice": "Letný slnovrat",
    "autumn_equinox": "Jesenná rovnodennosť",
    "winter_solstice": "Zimný slnovrat",
}


SKY = {
    "sun": "Slnko", "moon": "Mesiac",
    "mercury": "Merkúr", "venus": "Venuša", "mars": "Mars",
    "jupiter": "Jupiter", "saturn": "Saturn", "uranus": "Urán",
    "neptune": "Neptún",
    "facing": "pohľad na {dir}",
    "field_of_view": "zorné pole {deg}°",
    "overhead": "v zenite",
    "planets_none": "žiadna planéta nad obzorom",
    "star": "hviezda",
    "search_prompt": "názov alebo katalógové číslo",
    "search_none": "nič s takým názvom",
    "rises_at": "{name} vychádza o {time} na {dir}",
    "never_rises": "{name} odtiaľto nikdy nevychádza",
    "search_jump": "znova enter: prejsť na tento okamih",
    "tradition": "tradícia",
}


# The titles agree with "tradícia", feminine: "čínska"
SKY_CULTURES = {
    "anutan": "Anuta",
    "belarusian": "bieloruská",
    "blackfoot": "Blackfoot",
    "boorong": "Boorong",
    "bugis": "Bugis",
    "chinese": "čínska",
    "chinese-modern": "čínska súčasná",
    "hawaiian": "havajská",
    "indian": "védska (India)",
    "japanese": "japonské lunárne domy",
    "mandar": "Mandar",
    "maori": "maorská",
    "mongolian": "mongolská",
    "norse": "severská",
    "romanian": "rumunská",
    "ruelle": "Ruelle",
    "sami": "saamská",
    "siberian": "sibírska",
    "tongan": "tongská",
    "tukano": "Tukano",
    "snt": "západná (Sky & Telescope)",
    "rey": "západná (H.A.Rey)",
}
