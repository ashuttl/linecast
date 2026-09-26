"""Czech.

en.py is the reference, with every key and notes on each; a key
left out here reads in English.
"""


DAY_NAMES = ["po", "út", "st", "čt", "pá", "so", "ne"]


FULL_DAY_NAMES = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]


MONTHS = ["led", "úno", "bře", "dub", "kvě", "čvn",
          "čvc", "srp", "zář", "říj", "lis", "pro"]


MONTH_DAY = "{day}. {month}"


MOON_PHASES = ["Nov", "Dorůstající srpek", "První čtvrť", "Dorůstající Měsíc",
               "Úplněk", "Couvající Měsíc", "Poslední čtvrť", "Couvající srpek"]


HELP = {
    "hint_help": "nápověda",
    "key_wheel": "kolečko",
    "key_space": "mezerník",
    "key_hover": "najetí",
    "key_click": "kliknutí",
    "key_drag": "tažení",
    "key_enter": "enter",
    "forecast": "procházet předpověď",
    "now": "zpět na současnost",
    "alert": "přečíst výstrahu",
    "browser": "otevřít výstrahu v prohlížeči",
    "refresh": "obnovit předpověď",
    "time30": "posunout čas o 30 minut",
    "time15": "posunout čas o 15 minut",
    "year": "zobrazení dne / roku",
    "sun_times": "časy východu a západu slunce",
    "turn_moon": "otočit Měsíc",
    "calendar": "kotouč / kalendář",
    "months": "o měsíc vpřed nebo zpět",
    "moon_times": "fáze a časy východu / západu",
    "day": "otevřít den v zobrazení kotouče",
    "look": "rozhlédnout se",
    "target": "k cíli; podruhé k času východu",
    "figures": "obrazce / názvy souhvězdí",
    "cultures": "nebeské tradice",
    "play_time": "běh času: hodina / den / týden za sekundu",
    "compass": "pohled na S, SV, V, JV, J, JZ, Z, SZ",
    "zenith": "pohled přímo vzhůru",
    "moon": "pohled na Měsíc, když je nad obzorem",
    "frames": "krokovat snímky a pozastavit",
    "play": "přehrát / pozastavit (pauza vrátí na současnost)",
    "temperature": "vrstva teploty",
    "wind": "vrstva větru",
    "alerts": "vrstva výstrah",
    "theme": "zvolit motiv",
    "satellite": "radar / družice",
}


WEATHER = {
    "today": "Dnes",
    "today_short": "dnes",
    # "z {day}" would decline the weekday (ze středy); the day sits
    # in brackets instead.
    "forecast_stale": "Tato předpověď je zastaralá ({day}); novější se nepodařilo získat.",
    "forecast_stale_at": "Tato předpověď je zastaralá ({day}); novější se v {time} nepodařilo získat.",
    "forecast_fetching": "Získávání novější předpovědi…",
    "alerts_unavailable": "Výstrahy se nepodařilo ověřit.",
    "alerts_stale": "Stav výstrah: {when}; novější se nepodařilo získat.",
    "retry_run": "Spusťte znovu pro nový pokus.",
    "retry_key": "Stiskněte r pro nový pokus.",
    "credit_forecast": "Data o počasí: {source}",
    "credit_alerts": "Výstrahy: {source}",
    "credit_current": "Aktuální počasí: {source}",
    "credit_observed": "Pozorováno v {time} na {place}, {distance} odsud",
    "precip_inch": "″",
    "metric_unit_sep": "\u00a0",
    "feels": "pocitově",
    "wind": "Vítr",
    "gusts": "nárazy",
    "humidity": "Vlhkost",
    "chance": "pravděpodobnost {p}",
    # The kind of precipitation takes the genitive after
    # "pravděpodobnost" and after an amount alike: deště, sněhu.
    "chance_of": "pravděpodobnost {what} {p}",
    "amount_between": "{amount} mezi {a} a {b}",
    "amount_all_day": "{amount} během dne",
    "cloud": "Oblačnost {p}",
    "heaviest_around": "nejsilnější kolem {time}",
    "dew_pt": "Rosný bod",
    "uv": "UV",
    "aqi": "AQI",
    "until": "do",
    "sentence_end": ".",
    "sentence_join": ". ",
    "feels_humid": "Kvůli vysoké vlhkosti je pocitově tepleji",
    "feels_sun": "Kvůli slunci je pocitově tepleji",
    "feels_wind": "Kvůli větru je pocitově chladněji",
    "feels_dry": "Kvůli suchému vzduchu je pocitově chladněji",
    "same_temp": "přibližně stejná jako {ref_day}",
    "bit_warmer": "o něco vyšší než {ref_day}",
    "bit_cooler": "o něco nižší než {ref_day}",
    "warmer": "vyšší než {ref_day}",
    "cooler": "nižší než {ref_day}",
    "much_warmer": "mnohem vyšší než {ref_day}",
    "much_cooler": "mnohem nižší než {ref_day}",
    "today_subj": "Dnešní nejvyšší teplota",
    "tomorrow_subj": "Zítřejší nejvyšší teplota",
    "yesterday": "včerejší",
    "today_ref": "dnešní",
    "will_be": "{subject} bude {comparison}",
    "ending": "{desc} skončí {time}",
    "continuing": "{desc} potrvá celý den",
    "ending_becoming": "{desc} {peak_time} přejde {peak_art} a srážky ustanou {time}",
    "continuing_becoming": "{desc} {peak_time} přejde {peak_art} a srážky potrvají celý den",
    "starting": "{desc} pravděpodobně začne {time}",
    "starting_becoming": "{desc} pravděpodobně začne {time} a {peak_time} přejde {peak_art}",
    "shortly": "do hodiny",
    "in_about_an_hour": "asi za hodinu",
    "in_a_couple_hours": "za pár hodin",
    "around": "kolem {time}",
    "around_noon": "kolem poledne",
    "same_time": "zároveň",
    "overnight": "v noci",
    "early_tomorrow_morning": "zítra brzy ráno",
    "tomorrow_morning": "zítra ráno",
    "tomorrow_afternoon": "zítra odpoledne",
    "tomorrow_evening": "zítra večer",
    "on_day": "v {day}",
    "past_precip": "Za posledních 24\u00a0hodin spadlo {amt} {ptype}",
    "snow": "sněhu",
    "rain": "deště",
    "mixed_precip": "smíšených srážek",
    "Snow": "Sníh",
    "Rain": "Déšť",
    "Mix": "Smíšené",
    "q_to_close": "q zavře",
    "o_to_open": "o otevře v prohlížeči",
    "scroll": "posun",
    "space_to_now": "mezerník pro návrat na současnost",
    "hist_near_avg": "kolem průměru",
    "hist_above_avg": "o {diff} nad průměrem",
    "hist_below_avg": "o {diff} pod průměrem",
    "degrees": "{n}\u00a0stupňů",
    "warmer_by": "o {diff} vyšší než {ref_day}",
    "cooler_by": "o {diff} nižší než {ref_day}",
    "starting_chance": "{time} možná {desc}",
    "starting_chance_becoming": "{time} možná {desc}, {peak_time} pak {peak}",
    "starting_sure": "{time} {desc}",
    "starting_sure_becoming": "{time} {desc}, {peak_time} pak {peak}",
    "continuing_night": "{desc} potrvá celou noc",
    "continuing_night_becoming": "{desc} {peak_time} přejde {peak_art} a srážky potrvají celou noc",
    "more_later": "{time} znovu {desc}",
    "snow_total": "{time} napadne asi {amt} sněhu",
    "fog_ending": "Mlha se rozplyne {time}",
    "fog_continuing": "Mlha potrvá celý den",
    "fog_continuing_night": "Mlha potrvá celou noc",
    "fog_starting": "{time} mlha",
    "fog_starting_ending": "{time} mlha, {end} se rozplyne",
    "then_early_morning": "brzy ráno",
    "then_morning": "ráno",
    "then_later_morning": "dopoledne",
    "then_afternoon": "odpoledne",
    "then_later_afternoon": "později odpoledne",
    "then_evening": "večer",
    "then_later_evening": "později večer",
    "this_morning": "dnes ráno",
    "this_afternoon": "dnes odpoledne",
    "this_evening": "dnes večer",
    "tonight": "dnes v noci",
    "sky_clearing": "{time} se vyjasní",
    "sky_clouding": "{time} se zatáhne",
    "on_full_day": "v {day}",
    "rain_next_chance": "{time} možná {desc}",
    "rain_next_likely": "{time} pravděpodobně {desc}",
    "rain_next": "{time} {desc}",
    "on_two_days": "{first} a {second}",
    "from_day_to_day": "od {first} do {last}",
    "rain_run_heaviest": "{sentence}, nejsilnější {day}",
    "tomorrow_and_day": "zítra a {second}",
    "from_tomorrow_to_day": "od zítřka do {last}",
    "on_tomorrow": "zítra",
    "rain_run_with": "{sentence}, {day} i {with}",
    "rain_run_then": "{sentence}, {day} pak {with}",
    "rain_run_heaviest_with": "{sentence}, nejsilnější {day}, tehdy i {with}",
    "gusts_to": "{time} nárazy větru až {speed}",
    "with_gusts": "{sentence}, nárazy větru až {speed}",
    "freeze_tonight": "{time} klesne teplota pod bod mrazu, až na {temp}",
    "feels_ahead_hot": "{time} bude pocitově až {temp}",
    "feels_ahead_hot_humid": "Kvůli vysoké vlhkosti bude {time} pocitově až {temp}",
    "feels_ahead_hot_sun": "Kvůli slunci bude {time} pocitově až {temp}",
    "feels_ahead_cold": "{time} bude pocitově až {temp}",
    "feels_ahead_cold_wind": "Kvůli větru bude {time} pocitově až {temp}",
    "starting_pl": "{desc} pravděpodobně začnou {time}",
    "starting_becoming_pl": "{desc} pravděpodobně začnou {time} a {peak_time} přejdou {peak_art}",
    "continuing_pl": "{desc} potrvají celý den",
    "continuing_becoming_pl": "{desc} {peak_time} přejdou {peak_art} a srážky potrvají celý den",
    "degrees_one": "{n}\u00a0stupeň",
    "degrees_few": "{n}\u00a0stupně",
    "will_be_then": "Nejvyšší teplota bude {comparison}",
    "ending_becoming_pl": "{desc} {peak_time} přejdou {peak_art} a srážky ustanou {time}",
    "ending_heavier": "{desc} {peak_time} zesílí a skončí {time}",
    "continuing_heavier": "{desc} {peak_time} zesílí a potrvá celý den",
    "continuing_heavier_pl": "{desc} {peak_time} zesílí a potrvají celý den",
    "continuing_night_pl": "{desc} potrvají celou noc",
    "continuing_night_becoming_pl": "{desc} {peak_time} přejdou {peak_art} a srážky potrvají celou noc",
    "continuing_night_heavier": "{desc} {peak_time} zesílí a potrvá celou noc",
    "continuing_night_heavier_pl": "{desc} {peak_time} zesílí a potrvají celou noc",
    "starting_heavier": "{desc} pravděpodobně začne {time} a {peak_time} zesílí",
    "starting_heavier_pl": "{desc} pravděpodobně začnou {time} a {peak_time} zesílí",
    "this_morning_by": "do poledne",
    "this_afternoon_by": "do večera",
    "this_evening_by": "během večera",
    "tonight_by": "do půlnoci",
    "tomorrow_morning_by": "do zítřejšího rána",
    "tomorrow_afternoon_by": "do zítřejšího odpoledne",
    "tomorrow_evening_by": "do zítřejšího večera",
}


CONDITIONS = {
    0: "Jasno", 1: "Skoro jasno", 2: "Polojasno", 3: "Zataženo",
    45: "Mlha", 48: "Námrazová mlha",
    51: "Slabé mrholení", 53: "Mrholení", 55: "Silné mrholení",
    56: "Mrznoucí mrholení", 57: "Mrznoucí mrholení",
    61: "Slabý déšť", 63: "Déšť", 65: "Silný déšť",
    66: "Mrznoucí déšť", 67: "Mrznoucí déšť",
    71: "Slabé sněžení", 73: "Sněžení", 75: "Silné sněžení", 77: "Sněhové krupky",
    80: "Slabé přeháňky", 81: "Přeháňky", 82: "Silné přeháňky",
    85: "Sněhové přeháňky", 86: "Silné sněhové přeháňky",
    95: "Bouřka", 96: "Bouřka", 99: "Bouřka",
    "mostly_cloudy": "Oblačno",
}


PRECIP = {
    51: "slabé mrholení", 53: "mrholení", 55: "silné mrholení",
    56: "mrznoucí mrholení", 57: "mrznoucí mrholení",
    61: "slabý déšť", 63: "déšť", 65: "silný déšť",
    66: "mrznoucí déšť", 67: "mrznoucí déšť",
    71: "slabé sněžení", 73: "sněžení", 75: "silné sněžení", 77: "sněhové krupky",
    80: "slabé přeháňky", 81: "přeháňky", 82: "silné přeháňky",
    85: "sněhové přeháňky", 86: "silné sněhové přeháňky",
    95: "bouřka", 96: "bouřka", 99: "bouřka",
}


PRECIP_CLASSES = {"_pl": {77, 80, 81, 82, 85, 86}}


PRECIP_PARTITIVES = {
    51: "ve slabé mrholení", 53: "v mrholení", 55: "v silné mrholení",
    56: "v mrznoucí mrholení", 57: "v mrznoucí mrholení",
    61: "ve slabý déšť", 63: "v déšť", 65: "v silný déšť",
    66: "v mrznoucí déšť", 67: "v mrznoucí déšť",
    71: "ve slabé sněžení", 73: "ve sněžení", 75: "v silné sněžení",
    77: "ve sněhové krupky",
    80: "ve slabé přeháňky", 81: "v přeháňky", 82: "v silné přeháňky",
    85: "ve sněhové přeháňky", 86: "v silné sněhové přeháňky",
    95: "v bouřku", 96: "v bouřku", 99: "v bouřku",
}


PRECIP_RUNS = {95: "bouřky", 96: "bouřky", 99: "bouřky"}


ON_DAY = {2: "ve {day}", 3: "ve {day}"}


ON_FULL_DAY = {2: "ve středu", 3: "ve čtvrtek", 5: "v sobotu", 6: "v neděli"}


DAY_SPANS = {
    "and_first": {0: "v pondělí", 1: "v úterý", 2: "ve středu", 3: "ve čtvrtek", 4: "v pátek", 5: "v sobotu", 6: "v neděli"},
    "and_second": {0: "v pondělí", 1: "v úterý", 2: "ve středu", 3: "ve čtvrtek", 4: "v pátek", 5: "v sobotu", 6: "v neděli"},
    "from": {0: "pondělí", 1: "úterý", 2: "středy", 3: "čtvrtka", 4: "pátku", 5: "soboty", 6: "neděle"},
    "to": {0: "pondělí", 1: "úterý", 2: "středy", 3: "čtvrtka", 4: "pátku", 5: "soboty", 6: "neděle"},
}


LOCATIONS = {
    "locations": "Místa",
    "add": "Přidat místo",
    "clear": "Vymazat nedávná místa",
    "loading": "Načítání {name}…",
    "failed": "Nepodařilo se načíst počasí pro {name}. Zkuste to znovu.",
    "save": "Uložit {name} jako výchozí",
    "saved": "{name} je výchozí místo pro všechna zobrazení.",
    "save_failed": "Nepodařilo se uložit výchozí místo. Zkuste to znovu.",
}


RADAR = {
    "loading": "načítání…",
    "hint": "mezerník přehrát/pauza · kolečko/←→ krok · +/- zoom · tažení / wasd · c teplota · W vítr · t motiv · S družice · q konec",
    "theme": "motiv",
    "now": "nyní",
    # "12 km SV od Prahy" would put the genitive on the place name;
    # the place comes first, and the distance after a comma.
    "near": "{name}, {dist} {unit} {dir}",
    "compass": "S SV V JV J JZ Z SZ",
    "forecast": "předpověď",
    # Czech sets the percent sign off with a space: 40 %.
    "echo_pct": "{pct} % odraz",
    "cloud_pct": "{pct} % oblačnost",
    "radar_unavailable": "radar není k dispozici ({err})",
    "no_frames": "žádné snímky radaru",
}


MAPS = {
    "hint": "wasd · v zobrazení · / hledat · ? nápověda",
    "hint_route": "D trasa · n smazat",
    "unavailable": "terén není k dispozici ({err})",
    "streets_unavailable": "dlaždice ulic nejsou k dispozici ({err})",
    "offline": "žádné dlaždice",
    "mode_terrain": "terén",
    "mode_street": "ulice",
    # "slunce nad Prahou" would decline the place name; the sun is
    # at the zenith there, and the place follows a colon.
    "sun_over": "slunce v zenitu: {place}",
    "search_prompt": "hledat místo",
    "search_dest_prompt": "hledat cíl",
    "search_origin_prompt": "hledat výchozí bod",
    "search_hint": "↑↓ výběr · enter přejít · esc zavřít",
    "search_none": "nic nenalezeno",
    "search_error": "hledání není k dispozici",
    "dir_wait": "plánování trasy…",
    "dir_none": "žádná trasa",
    "dir_unavailable": "trasy nejsou k dispozici",
    "profile_car": "autem",
    "profile_bike": "na kole",
    "profile_foot": "pěšky",
    "dir_from": "odkud",
    "dir_to": "kam",
    "dir_mode": "způsob",
    "steps_hint": "↑↓ krok · esc zavřít",
    "help_title": "klávesy",
    "help_close": "esc zavřít",
    "help_pan": "posunout",
    "help_zoom_pointer": "přiblížit u ukazatele",
    "help_hover": "rozpoznat",
    "help_zoom": "přiblížit",
    "help_reset": "na začátek",
    "help_view": "ulice · terén",
    "help_labels": "popisky a čáry",
    "help_sky": "denní světlo · oblačnost",
    "help_spin": "otáčet glóbem",
    "help_search": "hledat",
    "help_directions": "trasa",
    "help_origin": "nastavit výchozí bod",
    "help_profile": "způsob dopravy",
    "help_keys": "tento seznam",
    "help_quit": "ukončit",
    "poi_airport": "letiště",
    "poi_peak": "vrchol",
    "poi_station": "nádraží",
    "poi_hospital": "nemocnice",
    "poi_civic": "úřad · škola",
    "poi_lodging": "ubytování",
    "poi_notable": "muzeum · pamětihodnost",
    "poi_worship": "kostel · chrám",
    "poi_ferry": "přívoz · přístav",
    "poi_other": "místo",
    "poi_capital": "hlavní město",
    "hov_motorway": "dálnice",
    "hov_ramp": "nájezd",
    "hov_trunk": "rychlostní silnice",
    "hov_primary": "hlavní silnice",
    "hov_secondary": "vedlejší silnice",
    "hov_minor": "ulice",
    "hov_service": "obslužná komunikace",
    "hov_path": "stezka",
    "hov_rail": "železnice",
    "hov_transit": "linka MHD",
    "hov_ferry": "přívoz",
    "hov_river": "řeka",
    "hov_stream": "potok",
    "hov_runway": "ranvej",
    "hov_taxiway": "pojezdová dráha",
    "hov_border": "hranice",
    "hov_coast": "pobřeží",
    "hov_water": "voda",
    "hov_park": "park",
    "hov_building": "budova",
    "hov_urban": "zástavba",
}


TIDES = {
    "space_to_now": "mezerník pro návrat na současnost",
    "waves": "Vlny",
    "swell": "Mrtvé vlnění",
    "tide_model": "Slapový model Open-Meteo",
    "no_tides": "Pro {name} není předpověď přílivu a odlivu.",
    "load_failed": "Nepodařilo se načíst příliv a odliv pro {name}. Zkuste to znovu.",
}


SUNSHINE = {
    "today": "dnes",
    # "před" takes the instrumental, whose plural is "dny" for every
    # count above one; "za" takes the accusative, "dny" to four
    # and "dní" beyond.
    "in_day": "za {n} den",
    "in_days_few": "za {n} dny",
    "in_days": "za {n} dní",
    "day_ago": "před {n} dnem",
    "days_ago_few": "před {n} dny",
    "days_ago": "před {n} dny",
    "sky_night": "noc",
    "sky_astronomical": "astronomický soumrak",
    "sky_nautical": "nautický soumrak",
    "sky_civil": "občanský soumrak",
    "sky_astronomical_dawn": "astronomické svítání",
    "sky_nautical_dawn": "nautické svítání",
    "sky_civil_dawn": "občanské svítání",
    "sky_day": "den",
    "midnight_sun": "půlnoční slunce",
    "polar_night": "polární noc",
    "solar_noon": "sluneční poledne",
    "sunrise": "východ slunce",
    "sunset": "západ slunce",
}


HOURS = {"night": "noc", "in_time": "za {dur}", "koku": "1 koku", "fast": "půst",
         "midnight": "půlnoc", "iftar": "iftár"}


MOON = {
    "illuminated": "osvětleno {pct} %",
    "age": "den {age} z {total}",
    "lunar_age": "stáří Měsíce {age} d",
    "up_now": "Nad obzorem",
    "above_horizon": "{alt}° nad obzorem",
    "below_horizon": "Pod obzorem",
    "moonrise": "Východ Měsíce",
    "moonset": "Západ Měsíce",
    "in_days": "za {days} d",
    "begins_at_sunset": "začíná západem slunce",
    "in_time": "za {dur}",
    "year_day": "Den {n} z {total}",
    "light_of_moon": "Měsíc dorůstá",
    "dark_of_moon": "Měsíc couvá",
    "good_for": "Vhodné: {things}",
    "hold_off": "Počkejte: {things}",
    "light_good": "setí nadzemních plodin, roubování, přesazování",
    "light_hold": "kořenová zelenina",
    "dark_good": "kořenová zelenina, řez, pletí",
    "dark_hold": "setí nadzemních plodin",
    "solunar_major": "Solunární hlavní",
    "solunar_minor": "vedlejší",
    "spring_equinox": "Jarní rovnodennost",
    "summer_solstice": "Letní slunovrat",
    "autumn_equinox": "Podzimní rovnodennost",
    "winter_solstice": "Zimní slunovrat",
}


SKY = {
    "sun": "Slunce", "moon": "Měsíc",
    "mercury": "Merkur", "venus": "Venuše", "mars": "Mars",
    "jupiter": "Jupiter", "saturn": "Saturn", "uranus": "Uran",
    "neptune": "Neptun",
    "facing": "pohled na {dir}",
    "field_of_view": "zorné pole {deg}°",
    "overhead": "v zenitu",
    "planets_none": "žádná planeta nad obzorem",
    "star": "hvězda",
    "search_prompt": "název nebo katalogové číslo",
    "search_none": "nic takového jména",
    "rises_at": "{name} vychází v {time} na {dir}",
    "never_rises": "{name} odsud nikdy nevychází",
    "search_jump": "enter znovu pro přechod na tento okamžik",
    "tradition": "tradice",
}


SKY_CULTURES = {
    "anutan": "Anuta",
    "belarusian": "běloruská",
    "blackfoot": "Blackfoot",
    "boorong": "Boorong",
    "bugis": "Bugis",
    "chinese": "čínská",
    "chinese-modern": "čínská současná",
    "hawaiian": "havajská",
    "indian": "védská (Indie)",
    "japanese": "japonské lunární domy",
    "mandar": "Mandar",
    "maori": "maorská",
    "mongolian": "mongolská",
    "norse": "severská",
    "romanian": "rumunská",
    "ruelle": "Ruelle",
    "sami": "sámská",
    "siberian": "sibiřská",
    "tongan": "tonžská",
    "tukano": "Tukano",
    "snt": "západní (Sky & Telescope)",
    "rey": "západní (H.A.Rey)",
}
