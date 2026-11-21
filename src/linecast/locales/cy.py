"""Welsh.

en.py is the reference, with every key and notes on each; a key
left out here reads in English.

A Welsh word changes its first letter after many of the words that
come before it: "glaw", but "siawns o law"; "dydd Llun", but "tan
ddydd Llun"; "Caerdydd", but "o Gaerdydd". The strings are written so
that a slot stands where its word keeps its own form, or takes one
mutation the tables carry: the precipitation nouns have their soft
mutation in PRECIP_PARTITIVES, the days theirs in ON_DAY and the
templates of a span, and a place name stands where nothing mutates it.
A number is written in figures, which do not mutate.
"""


SETTINGS = {
    # CLDR's Welsh rule: a form each for 0, 1, 2, 3, and 6, and one for
    # the rest.  The noun after a number is singular, so the forms differ
    # only where the number mutates it, as two does: "2 ddiwrnod".
    "plural": "welsh",
    # Ch and Rh are single letters, which a one-cell label would cut in
    # half, and four months begin with M.
    "numeric_month_axis": True,
}


# CLDR's abbreviations, the stand-alone ones, as BBC Tywydd has them
DAY_NAMES = ["Llun", "Maw", "Mer", "Iau", "Gwe", "Sad", "Sul"]


FULL_DAY_NAMES = ["Dydd Llun", "Dydd Mawrth", "Dydd Mercher", "Dydd Iau", "Dydd Gwener",
                  "Dydd Sadwrn", "Dydd Sul"]


MONTHS = ["Ion", "Chwef", "Maw", "Ebr", "Mai", "Meh",
          "Gorff", "Awst", "Medi", "Hyd", "Tach", "Rhag"]
FULL_MONTHS = ["Ionawr", "Chwefror", "Mawrth", "Ebrill", "Mai", "Mehefin",
               "Gorffennaf", "Awst", "Medi", "Hydref", "Tachwedd", "Rhagfyr"]


MONTH_DAY = "{day} {month}"


# Welsh Wikipedia's names (Gwedd leuad) for the waxing phases; it
# writes the waning ones several ways, and these say that the Moon is
# "ar ei chil", on the wane.
MOON_PHASES = ["Lleuad newydd", "Lleuad gilgant gynyddol", "Chwarter cyntaf",
               "Lleuad amgrwm gynyddol", "Lleuad lawn", "Lleuad amgrwm ar ei chil",
               "Chwarter olaf", "Lleuad gilgant ar ei chil"]


# Commands as verbnouns, as Welsh software labels them
HELP = {
    "hint_colors": "lliwiau",
    "hint_mode": "modd",
    "hint_view": "newid golwg",
    "weather_views": "rhagolwg / mis / blwyddyn",
    "month_colors": "tymheredd / gwyriad o'r cyfartaledd",
    "history_refresh": "adnewyddu'r hanes fesul awr",
    "hint_help": "cymorth",
    "key_wheel": "olwyn",
    "key_space": "bylchwr",
    "key_hover": "hofran",
    "key_click": "clicio",
    "key_drag": "llusgo",
    "key_enter": "enter",
    "forecast": "pori'r rhagolwg",
    "now": "dychwelyd i nawr",
    "alert": "darllen rhybudd",
    "radar_hover": "darllen rhybuddion, tymheredd a gwynt",
    "browser": "agor y rhybudd yn y porwr",
    "refresh": "adnewyddu'r rhagolwg",
    "time30": "symud yr amser fesul 30 munud",
    "time15": "symud yr amser fesul 15 munud",
    "year": "golwg diwrnod / blwyddyn",
    "bar_colors": "lliwiau'r bariau",
    "sun_times": "amseroedd codiad a machlud haul",
    "turn_moon": "troi'r Lleuad",
    "hide_text": "cuddio / dangos y testun",
    "calendar": "golwg disg / calendr",
    "months": "symud fesul mis",
    "years": "symud fesul blwyddyn",
    "tide_views": "golwg diwrnod / mis / blwyddyn / cyfansoddiad",
    "tide_views_no_year": "golwg diwrnod / mis",
    "tide_times": "y dŵr ar yr awr honno",
    "moon_times": "gwedd ac amseroedd codi / machlud",
    "day": "agor y diwrnod yn y golwg disg",
    "look": "edrych o gwmpas",
    "target": "mynd at y targed; eto i'r amser codi",
    "figures": "ffigurau / enwau'r cytserau",
    "cultures": "diwylliannau'r awyr",
    "play_time": "chwarae amser: awr / diwrnod / wythnos yr eiliad",
    "compass": "wynebu G, GDdw, Dw, DDdw, D, DOr, Gor, GOr",
    "zenith": "edrych yn syth i fyny",
    "moon": "wynebu'r Lleuad pan fydd i fyny",
    "frames": "camu drwy'r fframiau ac oedi",
    "play": "chwarae / oedi (mae oedi'n dychwelyd i nawr)",
    "temperature": "haen tymheredd",
    "wind": "haen gwynt",
    "alerts": "haen rhybuddion",
    "theme": "dewis thema",
    "satellite": "radar / lloeren",
    "help_title": "bysellau",
    "help_close": "esc cau",
    "help_pan": "symud",
    "help_hover": "adnabod",
    "help_zoom": "chwyddo",
    "help_search": "chwilio",
    "help_keys": "y rhestr hon",
    "help_quit": "gadael",
}


WEATHER = {
    "month_temperature": "Tymheredd fesul awr",
    "month_departure": "Gwyriad o'r cyfartaledd fesul awr, {span}",
    "month_from_average": "{value} o'r cyfartaledd",
    "month_at_average": "cyfartaledd",
    "month_estimate": "Amcangyfrif model diweddar",
    "month_repeat": "Awr cloc a ailadroddir: cymedr y ddau ddarlleniad",
    "month_small": "Mae angen o leiaf {cols} colofn a {rows} rhes i ddangos hyn.",
    "month_loading": "Yn llwytho'r hanes fesul awr…",
    "month_unavailable": "Nid yw'r hanes fesul awr ar gael.",
    "month_partial": "Nid yw rhan o'r hanes fesul awr ar gael.",
    "month_average": "Cyfartaledd: yr un awr cloc, dyddiadau o fewn saith diwrnod, deng mlynedd.",
    "month_rows": "Mae dau ddiwrnod yn rhannu rhes mewn terfynellau byr; mae hofran yn darllen y ddau.",
    "month_missing": "Mae oriau coll yn aros yn wag; caiff oriau cloc a ailadroddir eu cyfartalu.",
    "month_extremes": "Colofn dde: y darlleniad isaf a'r uchaf fesul awr ym mhob rhes.",
    "today": "Heddiw",
    "today_short": "Hedd",
    # "O ddydd Llun" would mutate the day, and the day comes abbreviated;
    # it sits in brackets instead.
    "forecast_stale": "Hen ragolwg yw hwn ({day}); nid oedd modd nôl un mwy diweddar.",
    "forecast_stale_at": "Hen ragolwg yw hwn ({day}); nid oedd modd nôl un mwy diweddar am {time}.",
    "forecast_fetching": "Yn nôl rhagolwg mwy diweddar…",
    "alerts_unavailable": "Nid oedd modd gwirio'r rhybuddion.",
    "alerts_stale": "Rhybuddion fel yr oeddent ({when}); nid oedd modd gwirio am rai mwy diweddar.",
    "retry_run": "Rhedwch eto i roi cynnig arall arni.",
    "retry_key": "Pwyswch r i roi cynnig arall arni.",
    "credit_forecast": "Data tywydd gan {source}",
    "credit_alerts": "Rhybuddion gan {source}",
    "credit_current": "Amodau presennol gan {source}",
    # "Yn {place}" would mutate the station's name ("yng Nghaerdydd"); it
    # follows a colon.
    "credit_observed": "Arsylwyd am {time}: {place}, {distance} i ffwrdd",
    "metric_unit_sep": "",
    # Cilometr yr awr and milltir yr awr, as BBC Tywydd abbreviates them
    "unit_kmh": "km/a",
    "unit_mph": "mya",
    "feels": "teimlo fel",
    "wind": "Gwynt",
    "gusts": "hyrddiau",
    "humidity": "Lleithder",
    "chance": "siawns {p}",
    # The kind of precipitation after "o", with its soft mutation: "siawns
    # 40% o law"
    "chance_of": "siawns {p} o {what}",
    "amount_between": "{amount} rhwng {a} a {b}",
    "amount_all_day": "{amount} drwy'r dydd",
    "cloud": "Cwmwl {p}",
    "heaviest_around": "trymaf tua {time}",
    "dew_pt": "Gwlithbwynt",
    "uv": "UV",
    "aqi": "AQI",
    "precip_inch": "″",
    "metric_unit_sep_prose": " ",
    # The noun stays singular after a number: "3 modfedd"
    "precip_inch_prose": "{n} modfedd",
    # "Tan {time}" would mutate the day the time begins with, and the day
    # comes abbreviated: the alert "ends" at the time instead.
    "until": "yn dod i ben {time}",
    "sentence_end": ".",
    "sentence_join": ". ",
    # "Oerach" is cooler and colder alike, so no "_cold" forms
    "feels_humid": "Mae'r lleithder yn gwneud iddi deimlo'n gynhesach",
    "feels_sun": "Mae'r haul yn gwneud iddi deimlo'n gynhesach",
    "feels_wind": "Mae'r gwynt yn gwneud iddi deimlo'n oerach",
    "feels_dry": "Mae'r aer sych yn gwneud iddi deimlo'n oerach",
    # The comparison is of the high, "tymheredd uchaf", which is higher
    # or lower than the other day's: "4° yn uwch na heddiw".  The degree
    # sign, not the word, which the numbers would mutate ("2 radd").
    "degrees": "{n}°",
    "same_temp": "tua'r un fath â {ref_day}",
    "bit_warmer": "ychydig yn uwch na {ref_day}",
    "bit_cooler": "ychydig yn is na {ref_day}",
    "warmer": "yn uwch na {ref_day}",
    "cooler": "yn is na {ref_day}",
    "much_warmer": "yn llawer uwch na {ref_day}",
    "much_cooler": "yn llawer is na {ref_day}",
    "warmer_by": "{diff} yn uwch na {ref_day}",
    "cooler_by": "{diff} yn is na {ref_day}",
    "today_subj": "tymheredd uchaf heddiw",
    "tomorrow_subj": "tymheredd uchaf yfory",
    "yesterday": "ddoe",
    "today_ref": "heddiw",
    "will_be": "Bydd {subject} {comparison}",
    "will_be_then": "Bydd y tymheredd uchaf {comparison}",
    "high_up_to": "Bydd y tymheredd yn codi i {temp} {time}",
    "high_only_up_to": "Dim ond i {temp} y bydd y tymheredd yn codi {time}",
    "highs_warmer": "Cynhesach {day}",
    "highs_cooler": "Oerach {day}",
    "highs_much_warmer": "Llawer cynhesach {day}",
    "highs_much_cooler": "Llawer oerach {day}",
    "highs_then_cooler": "{change}, yna'n oerach eto {then}",
    "highs_then_warmer": "{change}, yna'n gynhesach eto {then}",
    # Precipitation line.  The noun opens the sentence in its own form,
    # and the verbnouns after "yn" agree with nothing, so one template
    # serves the singular and the plural.  After "o" and after "yn troi'n"
    # the noun takes the soft mutation, from PRECIP_PARTITIVES: "siawns o
    # law", "yn troi'n gawodydd".  After "yna" it keeps its own form.
    "ending": "{desc} yn dod i ben {time}",
    "continuing": "{desc} yn parhau drwy'r dydd",
    "ending_becoming": "{desc} ar hyn o bryd, yn troi'n {peak_art} {peak_time}, ac yn dod i ben {time}",
    "continuing_becoming": "{desc} ar hyn o bryd, yn troi'n {peak_art} {peak_time} ac yn parhau drwy'r dydd",
    "starting": "{desc} yn debygol o ddechrau {time}",
    "starting_becoming": "{desc} yn debygol o ddechrau {time}, yna {peak} {peak_time}",
    "starting_span": "{desc} yn debygol {time}",
    "starting_span_becoming": "{desc} yn debygol {time}, yna {peak} {peak_time}",
    "starting_span_heavier": "{desc} yn debygol {time}, gan drymhau {peak_time}",
    "starting_chance": "Siawns o {desc_art} {time}",
    "starting_chance_becoming": "Siawns o {desc_art} {time}, yna {peak} {peak_time}",
    "starting_sure": "{desc} yn dechrau {time}",
    "starting_sure_becoming": "{desc} yn dechrau {time}, yna {peak} {peak_time}",
    "continuing_night": "{desc} yn parhau drwy'r nos",
    "continuing_night_becoming": "{desc} ar hyn o bryd, yn troi'n {peak_art} {peak_time} ac yn parhau drwy'r nos",
    "ending_heavier": "{desc} ar hyn o bryd, yn trymhau {peak_time}, ac yn dod i ben {time}",
    "continuing_heavier": "{desc} ar hyn o bryd, yn trymhau {peak_time} ac yn parhau drwy'r dydd",
    "continuing_night_heavier": "{desc} ar hyn o bryd, yn trymhau {peak_time} ac yn parhau drwy'r nos",
    "starting_heavier": "{desc} yn debygol o ddechrau {time}, gan drymhau {peak_time}",
    "starting_chance_heavier": "Siawns o {desc_art} {time}, gan drymhau {peak_time}",
    "starting_sure_heavier": "{desc} yn dechrau {time}, gan drymhau {peak_time}",
    "more_later": "Rhagor o {desc_art} {time}",
    # The deadline is in the "_by" forms below, "erbyn heno"
    "snow_total": "Tua {amt} o eira {time}",
    "fog_ending": "Niwl yn clirio {time}",
    "fog_continuing": "Niwl drwy'r dydd",
    "fog_continuing_night": "Niwl drwy'r nos",
    "fog_starting": "Niwl {time}",
    "fog_starting_ending": "Niwl {time}, yn clirio {end}",
    "shortly": "cyn hir",
    "in_about_an_hour": "ymhen rhyw awr",
    "in_a_couple_hours": "ymhen awr neu ddwy",
    "around": "tua {time}",
    # "Tua" aspirates: canol, chanol
    "around_noon": "tua chanol dydd",
    "same_time": "bryd hynny",
    "same_part_later": "yn ddiweddarach",
    "overnight": "dros nos",
    # A time said as an adverb takes the soft mutation: bore, "fore
    # yfory"; prynhawn, "brynhawn yfory"
    "early_tomorrow_morning": "yn gynnar fore yfory",
    "tomorrow_morning": "fore yfory",
    "tomorrow_afternoon": "brynhawn yfory",
    "tomorrow_evening": "nos yfory",
    # The days are in ON_DAY, each with its mutation: "ddydd Llun"
    "on_day": "{day}",
    "then_early_morning": "yn gynnar yn y bore",
    "then_morning": "yn y bore",
    "then_later_morning": "yn hwyrach yn y bore",
    "then_afternoon": "yn y prynhawn",
    "then_later_afternoon": "yn hwyrach yn y prynhawn",
    "then_evening": "gyda'r nos",
    "then_later_evening": "yn hwyrach gyda'r nos",
    # "Heno" is this evening and tonight alike
    "this_morning": "y bore yma",
    "this_afternoon": "y prynhawn yma",
    "this_evening": "heno",
    "tonight": "heno",
    # "By" a part of the day, after "erbyn", which does not mutate
    "this_morning_by": "erbyn y bore yma",
    "this_afternoon_by": "erbyn y prynhawn yma",
    "this_evening_by": "erbyn heno",
    "tonight_by": "erbyn heno",
    "tomorrow_morning_by": "erbyn bore yfory",
    "tomorrow_afternoon_by": "erbyn prynhawn yfory",
    "tomorrow_evening_by": "erbyn nos yfory",
    "sky_clearing": "Yr awyr yn clirio {time}",
    "sky_clouding": "Yn cymylu {time}",
    # The days are in ON_FULL_DAY
    "on_full_day": "{day}",
    "rain_next_chance": "Siawns o {desc_art} {time}",
    "rain_next_likely": "{desc} yn debygol {time}",
    "rain_next": "{desc} {time}",
    # The first day of a pair is an adverb and mutates, the second
    # follows "a" and does not.  A longer run is "between" its ends:
    # "o ddydd Mawrth" after "yn debygol" would read as "likely to".
    # The day's name alone fills each slot (DAY_SPANS).
    "on_two_days": "ddydd {first} a dydd {second}",
    "from_day_to_day": "rhwng dydd {first} a dydd {last}",
    "rain_run_heaviest": "{sentence}, trymaf {day}",
    "tomorrow_and_day": "yfory a dydd {second}",
    "from_tomorrow_to_day": "rhwng yfory a dydd {last}",
    "on_tomorrow": "yfory",
    # "Gyda" aspirates c, p, and t; the storms it comes before begin
    # with s.
    "rain_run_with": "{sentence}, gyda {with} {day}",
    "rain_run_then": "{sentence}, yna {with} {day}",
    "rain_run_heaviest_with": "{sentence}, trymaf {day} gyda {with}",
    "gusts_to": "Hyrddiau hyd at {speed} {time}",
    "with_gusts": "{sentence}, gyda hyrddiau hyd at {speed}",
    "freeze_tonight": "O dan y rhewbwynt {time}, i lawr i {temp}",
    "feels_ahead_hot": "Bydd hi'n teimlo mor boeth â {temp} {time}",
    "feels_ahead_hot_humid": "Bydd y lleithder yn gwneud iddi deimlo mor boeth â {temp} {time}",
    "feels_ahead_hot_sun": "Bydd yr haul yn gwneud iddi deimlo mor boeth â {temp} {time}",
    "feels_ahead_cold": "Bydd hi'n teimlo mor oer â {temp} {time}",
    "feels_ahead_cold_wind": "Bydd y gwynt yn gwneud iddi deimlo mor oer â {temp} {time}",
    # "Awr" is feminine, so "diwethaf" mutates after it
    "past_precip": "{amt} o {ptype} yn y 24 awr ddiwethaf",
    # After "o", with the soft mutation.  Rain and snow together are
    # "eirlaw", sleet.
    "snow": "eira",
    "rain": "law",
    "mixed_precip": "eirlaw",
    "Snow": "Eira",
    "Rain": "Glaw",
    "Mix": "Eirlaw",
    "q_to_close": "q i gau",
    "o_to_open": "o i agor yn y porwr",
    "scroll": "sgrolio",
    "space_to_now": "bylchwr i ddychwelyd i nawr",
    "hist_near_avg": "tua'r cyfartaledd",
    "hist_above_avg": "{diff} uwchlaw'r cyfartaledd",
    "hist_below_avg": "{diff} islaw'r cyfartaledd",
    "avg": "cyf.",
    "of_water": "{amt} o ddŵr",
}


CONDITIONS = {
    0: "Clir", 1: "Clir gan mwyaf", 2: "Rhannol gymylog", 3: "Cymylog",
    45: "Niwl", 48: "Niwl rhewllyd",
    51: "Glaw mân ysgafn", 53: "Glaw mân", 55: "Glaw mân trwm",
    56: "Glaw mân rhewllyd", 57: "Glaw mân rhewllyd",
    61: "Glaw ysgafn", 63: "Glaw", 65: "Glaw trwm",
    66: "Glaw rhewllyd", 67: "Glaw rhewllyd",
    71: "Eira ysgafn", 73: "Eira", 75: "Eira trwm", 77: "Eira mân",
    80: "Cawodydd ysgafn", 81: "Cawodydd", 82: "Cawodydd trwm",
    85: "Cawodydd eira", 86: "Cawodydd eira trwm",
    95: "Storm fellt a tharanau", 96: "Storm fellt a tharanau", 99: "Storm fellt a tharanau",
    "mostly_cloudy": "Cymylog gan mwyaf",
}


# Storms are plural in the prose; the header names the one overhead.
PRECIP = {
    51: "glaw mân ysgafn", 53: "glaw mân", 55: "glaw mân trwm",
    56: "glaw mân rhewllyd", 57: "glaw mân rhewllyd",
    61: "glaw ysgafn", 63: "glaw", 65: "glaw trwm",
    66: "glaw rhewllyd", 67: "glaw rhewllyd",
    71: "eira ysgafn", 73: "eira", 75: "eira trwm", 77: "eira mân",
    80: "cawodydd ysgafn", 81: "cawodydd", 82: "cawodydd trwm",
    85: "cawodydd eira", 86: "cawodydd eira trwm",
    95: "stormydd mellt a tharanau", 96: "stormydd mellt a tharanau",
    99: "stormydd mellt a tharanau",
}


# The nouns with the soft mutation, after "o" and "yn": glaw, "o law";
# cawodydd, "yn troi'n gawodydd".  Eira begins with a vowel and stormydd
# with s, which do not mutate.
PRECIP_PARTITIVES = {
    51: "law mân ysgafn", 53: "law mân", 55: "law mân trwm",
    56: "law mân rhewllyd", 57: "law mân rhewllyd",
    61: "law ysgafn", 63: "law", 65: "law trwm",
    66: "law rhewllyd", 67: "law rhewllyd",
    71: "eira ysgafn", 73: "eira", 75: "eira trwm", 77: "eira mân",
    80: "gawodydd ysgafn", 81: "gawodydd", 82: "gawodydd trwm",
    85: "gawodydd eira", 86: "gawodydd eira trwm",
    95: "stormydd mellt a tharanau", 96: "stormydd mellt a tharanau",
    99: "stormydd mellt a tharanau",
}


# A day in a sentence is an adverb, and takes the soft mutation: "ddydd
# Llun".
ON_DAY = {0: "ddydd Llun", 1: "ddydd Mawrth", 2: "ddydd Mercher", 3: "ddydd Iau",
          4: "ddydd Gwener", 5: "ddydd Sadwrn", 6: "ddydd Sul"}


ON_FULL_DAY = {0: "ddydd Llun", 1: "ddydd Mawrth", 2: "ddydd Mercher", 3: "ddydd Iau",
               4: "ddydd Gwener", 5: "ddydd Sadwrn", 6: "ddydd Sul"}


# The day's name without "dydd", which the templates of a span write
# with the mutation each place takes: "ddydd Iau a dydd Gwener",
# "rhwng dydd Sadwrn a dydd Llun".
DAY_SPANS = {
    "and_first": {0: "Llun", 1: "Mawrth", 2: "Mercher", 3: "Iau", 4: "Gwener", 5: "Sadwrn", 6: "Sul"},
    "and_second": {0: "Llun", 1: "Mawrth", 2: "Mercher", 3: "Iau", 4: "Gwener", 5: "Sadwrn", 6: "Sul"},
    "from": {0: "Llun", 1: "Mawrth", 2: "Mercher", 3: "Iau", 4: "Gwener", 5: "Sadwrn", 6: "Sul"},
    "to": {0: "Llun", 1: "Mawrth", 2: "Mercher", 3: "Iau", 4: "Gwener", 5: "Sadwrn", 6: "Sul"},
}


# A place's name would mutate after "o" or "yn"; it follows a verbnoun
# or "ar gyfer", which leave it as it is.
LOCATIONS = {
    "locations": "Lleoliadau",
    "add": "Ychwanegu lleoliad",
    "clear": "Clirio lleoliadau diweddar",
    "loading": "Yn llwytho {name}…",
    "failed": "Nid oedd modd llwytho'r tywydd ar gyfer {name}. Rhowch gynnig arall arni.",
    "save": "Cadw {name} fel y rhagosodiad",
    "saved": "Cadwyd {name} fel y rhagosodiad ar gyfer pob golwg.",
    "save_failed": "Nid oedd modd cadw'r lleoliad rhagosodedig. Rhowch gynnig arall arni.",
}


RADAR = {
    "loading": "yn llwytho…",
    "hint": "bylchwr chwarae/oedi · sgrolio/←→ cam · +/- chwyddo · llusgo i symud / wasd · c tymheredd · W gwynt · t thema · S lloeren · q gadael",
    "theme": "thema",
    "now": "nawr",
    # "12 km i'r GDdw o Gaerdydd" would mutate the place name; the place
    # comes first, and the distance after a colon.
    "near": "{name}: {dist} {unit} i'r {dir}",
    # BBC Tywydd's abbreviations: gogledd, dwyrain, de, gorllewin
    "compass": "G GDdw Dw DDdw D DOr Gor GOr",
    "forecast": "rhagolwg",
    "echo_pct": "{pct}% adlais",
    "cloud_pct": "{pct}% cwmwl",
    "radar_unavailable": "radar ddim ar gael ({err})",
    "no_frames": "dim fframiau radar ar gael",
}


MAPS = {
    "hint": "wasd · v golwg · / chwilio · ? cymorth",
    "hint_route": "D cyfarwyddiadau · n clirio",
    "unavailable": "tirwedd ddim ar gael ({err})",
    "streets_unavailable": "teils strydoedd ddim ar gael ({err})",
    "offline": "dim teils",
    "mode_terrain": "tirwedd",
    "mode_street": "strydoedd",
    # "Uwchben" leaves the place name as it is
    "sun_over": "haul uwchben {place}",
    "search_prompt": "chwilio am leoedd",
    "search_dest_prompt": "chwilio am gyrchfan",
    "search_origin_prompt": "chwilio am fan cychwyn",
    "search_hint": "↑↓ dewis · enter mynd · esc cau",
    "search_none": "dim canlyniadau",
    "search_error": "chwilio ddim ar gael",
    "dir_wait": "yn llwybro…",
    "dir_none": "dim llwybr",
    "dir_unavailable": "cyfarwyddiadau ddim ar gael",
    "profile_car": "gyrru",
    "profile_bike": "beicio",
    "profile_foot": "cerdded",
    "dir_from": "o",
    "dir_to": "i",
    "dir_mode": "dull",
    "steps_hint": "↑↓ cam · esc cau",
    "help_zoom_pointer": "chwyddo wrth y pwyntydd",
    "help_reset": "yn ôl i'r dechrau",
    "help_view": "strydoedd · tirwedd",
    "help_labels": "labeli a llinellau",
    "help_sky": "golau dydd · cymylau",
    "sky_daylight": "golau dydd",
    "sky_clouds": "cymylau",
    "help_spin": "troelli'r glôb",
    "help_directions": "cyfarwyddiadau",
    "help_origin": "gosod man cychwyn",
    "help_profile": "dull teithio",
    "poi_airport": "maes awyr",
    "poi_peak": "copa",
    "poi_station": "gorsaf",
    "poi_hospital": "ysbyty",
    "poi_civic": "dinesig · ysgol",
    "poi_lodging": "llety",
    "poi_notable": "amgueddfa · atyniad",
    "poi_worship": "addoldy",
    "poi_ferry": "fferi · marina",
    "poi_other": "lle",
    "poi_capital": "prifddinas",
    "hov_motorway": "traffordd",
    "hov_ramp": "slipffordd",
    "hov_trunk": "cefnffordd",
    "hov_primary": "prif ffordd",
    "hov_secondary": "ffordd eilaidd",
    "hov_minor": "stryd",
    "hov_service": "ffordd wasanaeth",
    "hov_path": "llwybr",
    "hov_rail": "rheilffordd",
    "hov_transit": "llinell drafnidiaeth",
    "hov_ferry": "fferi",
    "hov_river": "afon",
    "hov_stream": "nant",
    "hov_runway": "rhedfa",
    "hov_taxiway": "llwybr tacsïo",
    "hov_border": "ffin",
    "hov_coast": "arfordir",
    "hov_water": "dŵr",
    "hov_park": "parc",
    "hov_building": "adeilad",
    "hov_urban": "ardal adeiledig",
}


TIDES = {
    "space_to_now": "bylchwr i ddychwelyd i nawr",
    "waves": "Tonnau",
    "swell": "Ymchwydd",
    "tide_model": "Model llanw Open-Meteo",
    "no_tides": "Dim rhagolygon llanw ar gyfer {name}.",
    "load_failed": "Nid oedd modd llwytho'r llanw ar gyfer {name}. Rhowch gynnig arall arni.",
    # High water and low water, as a Welsh tide table names them
    "high": "Penllanw",
    "low": "Distyll",
    "no_data": "Dim data llanw",
    "flood_stage": "lefel llifogydd",
    "highest_on": "uchaf {h} {date}",
    "predicted": "rhagfynegiad",
    "measured": "mesuriad",
    "modeled": "model",
    "makeup_headline": "Beth sy'n symud y llanw yma",
    "makeup_twice": "Ddwywaith y dydd",
    "makeup_once": "Unwaith y dydd",
    "makeup_moon": "Y Lleuad",
    "makeup_sun": "Yr Haul",
    "makeup_distance": "Pellter y Lleuad",
    # "Gogwydd y Lleuad" would read as a tilted axis; this says off the
    # equator
    "makeup_moon_tilt": "Y Lleuad oddi ar y cyhydedd",
    "makeup_sun_tilt": "Yr Haul oddi ar y cyhydedd",
    "makeup_key_size": "Mae pob uchder yn hanner yr amrediad o ddistyll i benllanw o'r achos hwnnw.",
    "makeup_key_gain": "Mae × yn ei gymharu â'r un cyfraniad mewn cefnfor delfrydol.",
    "makeup_key_sea": "Mae siâp a dyfnder y môr yn newid pa mor fawr yw yma.",
    "makeup_key_phases": "lleuad newydd, lleuad lawn",
    "makeup_mark_near": "p",
    "makeup_key_near": "Lleuad agosaf",
    "makeup_key_far": "pellaf i'r gogledd, i'r de",
    "makeup_key_equator": "uwchben y cyhydedd",
}


SUNSHINE = {
    "today": "heddiw",
    # The noun stays singular after a number, and two mutates it: "2
    # ddiwrnod"
    "in_day": "ymhen {n} diwrnod",
    "in_days": "ymhen {n} diwrnod",
    "in_days_two": "ymhen {n} ddiwrnod",
    "day_ago": "{n} diwrnod yn ôl",
    "days_ago": "{n} diwrnod yn ôl",
    "days_ago_two": "{n} ddiwrnod yn ôl",
    "sky_night": "nos",
    "sky_astronomical": "cyfnos seryddol",
    "sky_nautical": "cyfnos morwrol",
    "sky_civil": "cyfnos sifil",
    # "Cyfnos" is the evening's; the morning's twilight is the dawn,
    # "gwawr", which is feminine and mutates "morwrol"
    "sky_astronomical_dawn": "gwawr seryddol",
    "sky_nautical_dawn": "gwawr forwrol",
    "sky_civil_dawn": "gwawr sifil",
    "sky_day": "golau dydd",
    "midnight_sun": "haul canol nos",
    "polar_night": "noson begynol",
    "solar_noon": "canol dydd solar",
    "sunrise": "codiad haul",
    "sunset": "machlud haul",
}


HOURS = {"night": "nos", "in_time": "ymhen {dur}", "koku": "1 koku", "fast": "ympryd",
         "midnight": "canol nos", "iftar": "iftar"}


MOON = {
    # The Moon is feminine: "wedi'i goleuo"
    "illuminated": "{pct}% wedi'i goleuo",
    "age": "diwrnod {age} o {total}",
    "lunar_age": "oed y lleuad {age}d",
    "up_now": "I fyny nawr",
    "above_horizon": "{alt}° uwchben y gorwel",
    "below_horizon": "O dan y gorwel",
    "moonrise": "Codiad y lleuad",
    "moonset": "Machlud y lleuad",
    "in_days": "ymhen {days}d",
    "begins_at_sunset": "yn dechrau ar fachlud haul",
    "in_time": "ymhen {dur}",
    "year_day": "Diwrnod {n} o {total}",
    "week_of_summer": "wythnos {n} yr haf",
    "week_of_winter": "wythnos {n} y gaeaf",
    # The halves of the month as Welsh country lore names them, the
    # Moon's increase and its weakness
    "light_of_moon": "cynnydd y lleuad",
    "dark_of_moon": "gwendid y lleuad",
    "good_for": "Da ar gyfer {things}",
    "hold_off": "Gwell gohirio {things}",
    "light_good": "hau cnydau uwchben y ddaear, impio, trawsblannu",
    "light_hold": "gwreiddlysiau",
    "dark_good": "gwreiddlysiau, tocio, chwynnu",
    "dark_hold": "hau cnydau uwchben y ddaear",
    "solunar_major": "Solunar: prif gyfnod",
    "solunar_minor": "cyfnod llai",
    "spring_equinox": "Cyhydnos y gwanwyn",
    "summer_solstice": "Heuldro'r haf",
    "autumn_equinox": "Cyhydnos yr hydref",
    "winter_solstice": "Heuldro'r gaeaf",
}


# The planets share their names with the days: Mercher, Gwener, Mawrth,
# Iau, Sadwrn
SKY = {
    "sun": "Haul", "moon": "Lleuad",
    "mercury": "Mercher", "venus": "Gwener", "mars": "Mawrth",
    "jupiter": "Iau", "saturn": "Sadwrn", "uranus": "Wranws",
    "neptune": "Neifion",
    "facing": "yn wynebu'r {dir}",
    "field_of_view": "{deg}° o led",
    "overhead": "uwchben",
    "planets_none": "dim planedau i'w gweld",
    "star": "seren",
    "search_prompt": "enw neu ID catalog",
    "search_none": "dim byd o'r enw hwnnw",
    "rises_at": "Mae {name} yn codi am {time} yn y {dir}",
    "never_rises": "Nid yw {name} byth yn codi o'r fan hon",
    "search_jump": "enter eto i fynd i'r foment honno",
    "tradition": "traddodiad",
}


SKY_CULTURES = {
    "anutan": "Anuta",
    "belarusian": "Belarwsaidd",
    "blackfoot": "Blackfoot",
    "boorong": "Boorong",
    "bugis": "Bugis",
    "chinese": "Tsieineaidd",
    "chinese-modern": "Tsieineaidd cyfoes",
    "hawaiian": "Hawaiaidd",
    "indian": "Fedaidd Indiaidd",
    "japanese": "Gorsafoedd lleuad Japan",
    "mandar": "Mandar",
    "maori": "Māori",
    "mongolian": "Mongolaidd",
    "norse": "Llychlynnaidd",
    "romanian": "Rwmanaidd",
    "ruelle": "Ruelle",
    "sami": "Sami",
    "siberian": "Siberaidd",
    "tongan": "Tongaidd",
    "tukano": "Tukano",
    "snt": "Gorllewinol (Sky & Telescope)",
    "rey": "Gorllewinol (H.A.Rey)",
}
