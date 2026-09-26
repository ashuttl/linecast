"""English: the reference.

Every key any language can have is here, with notes on what it is
for; a key another language leaves out reads in English.
"""


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


FULL_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


MONTH_DAY = "{month} {day}"


MOON_PHASES = ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
               "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"]


HELP = {
    "hint_help": "help",
    "key_wheel": "wheel",
    "key_space": "space",
    "key_hover": "hover",
    "key_click": "click",
    "key_drag": "drag",
    "key_enter": "enter",
    "forecast": "browse forecast",
    "now": "return to now",
    "alert": "read an alert",
    "browser": "open alert in browser",
    "refresh": "refresh forecast",
    "time30": "move time by 30 minutes",
    "time15": "move time by 15 minutes",
    "year": "day / year view",
    "sun_times": "sunrise and sunset times",
    "turn_moon": "turn the Moon",
    "calendar": "disc / calendar view",
    "months": "move by one month",
    "moon_times": "phase and rise / set times",
    "day": "open day in disc view",
    "look": "look around",
    "target": "go to target; again to rising time",
    "figures": "constellation figures / names",
    "cultures": "sky cultures",
    "play_time": "play time: hour / day / week per second",
    "compass": "face N, NE, E, SE, S, SW, W, NW",
    "zenith": "look straight up",
    "moon": "face the Moon when it is up",
    "frames": "step frames and pause",
    "play": "play / pause (pause returns to now)",
    "temperature": "temperature layer",
    "wind": "wind layer",
    "alerts": "alert layer",
    "theme": "choose theme",
    "satellite": "radar / satellite",
}


WEATHER = {
    "today": "Today",
    "today_short": "Tod",
    "forecast_stale": "This forecast is from {day}; a newer one could not be fetched.",
    "forecast_stale_at": ("This forecast is from {day}; a newer one could not be "
                          "fetched at {time}."),
    "forecast_fetching": "Fetching a newer forecast…",
    "alerts_unavailable": "Alerts could not be checked.",
    "alerts_stale": "Alerts as of {when}; could not check for newer ones.",
    "retry_run": "Run again to retry.",
    "retry_key": "Press r to retry.",
    "credit_forecast": "Weather data by {source}",
    "credit_alerts": "Alerts by {source}",
    "credit_current": "Current conditions by {source}",
    "credit_observed": "Observed at {time} from {place}, {distance} away",
    "metric_unit_sep": "",
    "unit_kmh": "km/h",
    "unit_ms": "m/s",
    "unit_mph": "mph",
    "unit_mm": "mm",
    "unit_cm": "cm",
    "feels": "feels",
    "wind": "Wind",
    "gusts": "gusts",
    "humidity": "Humidity",
    "chance": "{p} chance",
    "chance_of": "{p} chance of {what}",
    "amount_between": "{amount} between {a} and {b}",
    "amount_all_day": "{amount} through the day",
    "cloud": "Cloud {p}",
    "heaviest_around": "heaviest around {time}",
    "dew_pt": "Dew pt",
    "uv": "UV",
    "aqi": "AQI",
    "aqhi": "AQHI",
    "precip_inch": "″",
    # Units in running prose, spelled and spaced as a sentence has
    # them: "12 mm of rain", "gusts to 30 mph", "3 inches of snow"
    "metric_unit_sep_prose": "\u00a0",
    "precip_inch_prose": "{n}\u00a0inches",
    "until": "until {time}",
    # Sentence punctuation for the prose lines
    "sentence_end": ".",
    "sentence_join": ". ",
    # Feels-like line
    "feels_humid": "The humidity is making it feel warmer",
    "feels_sun": "The sun is making it feel warmer",
    "feels_wind": "The wind is making it feel cooler",
    "feels_dry": "The dry air is making it feel cooler",
    # In cold air the same push is "colder": a person says cooler of
    # a warm day
    "feels_wind_cold": "The wind is making it feel colder",
    "feels_dry_cold": "The dry air is making it feel colder",
    # Comparative line: the day's high against the other day's,
    # "warmer" and "cooler" as a forecaster says it, not the "high …
    # higher" of the literal.
    # Where the language has the "by" forms, the number stands in
    # for "much" and the plain comparison; a small change stays "a
    # bit".
    "degrees": "{n}°",
    "same_temp": "about the same as {ref_day}",
    "bit_warmer": "a bit warmer than {ref_day}",
    "bit_cooler": "a bit cooler than {ref_day}",
    "warmer": "warmer than {ref_day}",
    "cooler": "cooler than {ref_day}",
    "much_warmer": "much warmer than {ref_day}",
    "much_cooler": "much cooler than {ref_day}",
    "warmer_by": "{diff} warmer than {ref_day}",
    "cooler_by": "{diff} cooler than {ref_day}",
    "today_subj": "Today's high",
    "tomorrow_subj": "Tomorrow's high",
    "yesterday": "yesterday's",
    "today_ref": "today's",
    "will_be": "{subject} will be {comparison}",
    # When the sentence before has already said "tomorrow"
    "will_be_then": "The high will be {comparison}",
    # Precipitation line
    "ending": "{desc} ending {time}",
    "continuing": "{desc} continuing through the day",
    # A turn inside rain that is falling now is one clause with its
    # end, "turning to showers around 9pm and ending overnight"; a
    # turn in rain still to come is a second thing, "then", as a
    # forecaster lists them.
    "ending_becoming": "{desc} turning to {peak} {peak_time} and ending {time}",
    "continuing_becoming": "{desc} turning to {peak} {peak_time} and lasting through the day",
    "starting": "{desc} likely starting {time}",
    "starting_becoming": "{desc} likely starting {time}, then {peak} {peak_time}",
    # Likely in a part of the day, where "starting" would be one word
    # too many: "light drizzle likely in the evening"
    "starting_span": "{desc} likely {time}",
    "starting_span_becoming": "{desc} likely {time}, then {peak} {peak_time}",
    "starting_span_heavier": "{desc} likely {time}, turning heavy {peak_time}",
    # The hedge follows the odds: a chance below sixty percent, likely
    # below eighty, and none from eighty up.
    "starting_chance": "A chance of {desc} {time}",
    "starting_chance_becoming": "A chance of {desc} {time}, then {peak} {peak_time}",
    "starting_sure": "{desc} starting {time}",
    "starting_sure_becoming": "{desc} starting {time}, then {peak} {peak_time}",
    "continuing_night": "{desc} continuing through the night",
    "continuing_night_becoming": "{desc} turning to {peak} {peak_time} and lasting through the night",
    # Rain that only turns heavy is the same rain, harder
    "ending_heavier": "{desc} turning heavy {peak_time} and ending {time}",
    "continuing_heavier": "{desc} turning heavy {peak_time} and lasting through the day",
    "continuing_night_heavier": "{desc} turning heavy {peak_time} and lasting through the night",
    "starting_heavier": "{desc} likely starting {time}, turning heavy {peak_time}",
    "starting_chance_heavier": "A chance of {desc} {time}, turning heavy {peak_time}",
    "starting_sure_heavier": "{desc} starting {time}, turning heavy {peak_time}",
    "more_later": "More {desc} {time}",
    "snow_total": "About {amt} of snow by {time}",
    # Fog: what it does next when it is already out there, and when it
    # closes in and lifts when it is not
    "fog_ending": "Fog clearing {time}",
    "fog_continuing": "Fog through the day",
    "fog_continuing_night": "Fog through the night",
    "fog_starting": "Fog {time}",
    "fog_starting_ending": "Fog {time}, clearing {end}",
    "shortly": "soon",
    "in_about_an_hour": "in about an hour",
    "in_a_couple_hours": "in a couple hours",
    "around": "around {time}",
    # Midday by its name, in either clock
    "around_noon": "around noon",
    # A part of today the sentence before has just named: "Below
    # freezing tonight, down to −2°.  Light snow likely then."  And
    # the same part named twice in one sentence: "turning heavy later"
    "same_time": "then",
    "same_part_later": "later",
    "overnight": "overnight",
    "early_tomorrow_morning": "early tomorrow morning",
    "tomorrow_morning": "tomorrow morning",
    "tomorrow_afternoon": "tomorrow afternoon",
    "tomorrow_evening": "tomorrow evening",
    "on_day": "on {day}",
    # A second time of tomorrow in one sentence, "tomorrow" already
    # said.  A second hour in the part of the day the sentence has
    # already named is later in it, not that part over again.
    "then_early_morning": "early in the morning",
    "then_morning": "in the morning",
    "then_later_morning": "later in the morning",
    "then_afternoon": "in the afternoon",
    "then_later_afternoon": "later in the afternoon",
    "then_evening": "in the evening",
    "then_later_evening": "later in the evening",
    # Parts of today, for things that are not on the hour
    "this_morning": "this morning",
    "this_afternoon": "this afternoon",
    "this_evening": "this evening",
    "tonight": "tonight",
    # The sky, the week, the wind, the cold, the heat
    "sky_clearing": "Clearing {time}",
    "sky_clouding": "Clouding over {time}",
    "on_full_day": "on {day}",
    "rain_next_chance": "A chance of {desc} {time}",
    "rain_next_likely": "{desc} likely {time}",
    "rain_next": "{desc} {time}",
    "on_two_days": "on {first} and {second}",
    "from_day_to_day": "from {first} to {last}",
    "rain_run_heaviest": "{sentence}, heaviest {day}",
    "tomorrow_and_day": "tomorrow and {second}",
    "from_tomorrow_to_day": "from tomorrow to {last}",
    "on_tomorrow": "tomorrow",
    "rain_run_with": "{sentence}, with {with} {day}",
    "rain_run_then": "{sentence}, then {with} {day}",
    "rain_run_heaviest_with": "{sentence}, heaviest {day} with {with}",
    "gusts_to": "Gusts to {speed} {time}",
    "with_gusts": "{sentence}, with gusts to {speed}",
    "freeze_tonight": "Below freezing {time}, down to {temp}",
    "feels_ahead_hot": "It will feel as hot as {temp} {time}",
    "feels_ahead_hot_humid": "The humidity will make it feel as hot as {temp} {time}",
    "feels_ahead_hot_sun": "The sun will make it feel as hot as {temp} {time}",
    "feels_ahead_cold": "It will feel as cold as {temp} {time}",
    "feels_ahead_cold_wind": "The wind will make it feel as cold as {temp} {time}",
    # Past precip
    "past_precip": "{amt} of {ptype} in the last 24 hours",
    "snow": "snow",
    "rain": "rain",
    "mixed_precip": "mixed precipitation",
    # Daily precip types
    "Snow": "Snow",
    "Rain": "Rain",
    "Mix": "Mix",
    # Alert modal hints
    "q_to_close": "q to close",
    "o_to_open": "o to open in browser",
    "scroll": "scroll",
    "space_to_now": "space to return to now",
    # Historical comparison
    "hist_near_avg": "near avg",
    "hist_above_avg": "{diff} above avg",
    "hist_below_avg": "{diff} below avg",
}


LOCATIONS = {
    "locations": "Locations",
    "add": "Add location",
    "clear": "Clear recent locations",
    "loading": "Loading {name}…",
    "failed": "Could not load weather for {name}. Please try again.",
    "save": "Save {name} as default",
    "saved": "Saved {name} as the default for all views.",
    "save_failed": "Could not save the default location. Please try again.",
}


RADAR = {
    "loading": "loading…",
    "hint": "space play/pause · scroll/←→ step · +/- zoom · drag pan / wasd · c temp · W wind · t theme · S satellite · q quit",
    "theme": "theme",
    "now": "now",
    "near": "{dist} {unit} {dir} of {name}",
    "unit_km": "km",
    "unit_mi": "mi",
    "compass": "N NE E SE S SW W NW",
    "forecast": "forecast",
    "echo_pct": "{pct}% echo",
    "cloud_pct": "{pct}% cloud",
    "radar_unavailable": "radar unavailable ({err})",
    "no_frames": "no radar frames available",
}


MAPS = {
    "hint": "wasd · v view · / search · ? help",
    "hint_route": "D directions · n clear",
    "unavailable": "terrain unavailable ({err})",
    "streets_unavailable": "street tiles unavailable ({err})",
    "offline": "no tiles",
    "mode_terrain": "terrain",
    "mode_street": "street",
    "sun_over": "sun over {place}",
    "search_prompt": "search places",
    "search_dest_prompt": "search destination",
    "search_origin_prompt": "search origin",
    "search_hint": "↑↓ select · enter go · esc close",
    "search_none": "no matches",
    "search_error": "search unavailable",
    "dir_wait": "routing…",
    "dir_none": "no route",
    "dir_unavailable": "directions unavailable",
    "profile_car": "driving",
    "profile_bike": "cycling",
    "profile_foot": "walking",
    "dir_from": "from",
    "dir_to": "to",
    "dir_mode": "mode",
    "steps_hint": "↑↓ step · esc close",
    "help_title": "keys",
    "help_close": "esc close",
    "help_pan": "pan",
    "help_zoom_pointer": "zoom at pointer",
    "help_hover": "identify",
    "help_zoom": "zoom",
    "help_reset": "back to start",
    "help_view": "street · terrain",
    "help_labels": "labels & lines",
    "help_sky": "daylight · clouds",
    "help_spin": "spin the globe",
    "help_search": "search",
    "help_directions": "directions",
    "help_origin": "set origin",
    "help_profile": "travel mode",
    "help_keys": "this list",
    "help_quit": "quit",
    "poi_airport": "airport",
    "poi_peak": "peak",
    "poi_station": "station",
    "poi_hospital": "hospital",
    "poi_civic": "civic · school",
    "poi_lodging": "lodging",
    "poi_notable": "museum · sight",
    "poi_worship": "place of worship",
    "poi_ferry": "ferry · marina",
    "poi_other": "place",
    "poi_capital": "capital",
    "hov_motorway": "motorway",
    "hov_ramp": "ramp",
    "hov_trunk": "trunk road",
    "hov_primary": "primary road",
    "hov_secondary": "secondary road",
    "hov_minor": "street",
    "hov_service": "service road",
    "hov_path": "path",
    "hov_rail": "railway",
    "hov_transit": "transit line",
    "hov_ferry": "ferry",
    "hov_river": "river",
    "hov_stream": "stream",
    "hov_runway": "runway",
    "hov_taxiway": "taxiway",
    "hov_border": "border",
    "hov_coast": "coastline",
    "hov_water": "water",
    "hov_park": "park",
    "hov_building": "building",
    "hov_urban": "built-up",
}


TIDES = {
    "space_to_now": "space to return to now",
    "waves": "Waves",
    "swell": "Swell",
    "tide_model": "Open-Meteo tide model",
    # A wave's period, after its height: "Waves 0.4m @ 3s"
    "period": " @ {s}s",
    # The live view's location menu: a place without tides, or a failed load.
    "no_tides": "No tide predictions for {name}.",
    "load_failed": "Could not load tides for {name}. Please try again.",
}


SUNSHINE = {
    "today": "today",
    "in_day": "in {n} day",
    "in_days": "in {n} days",
    "day_ago": "{n} day ago",
    "days_ago": "{n} days ago",
    "sky_night": "night",
    "sky_astronomical": "astronomical twilight",
    "sky_nautical": "nautical twilight",
    "sky_civil": "civil twilight",
    "sky_day": "daylight",
    "midnight_sun": "midnight sun",
    "polar_night": "polar night",
    "solar_noon": "solar noon",
    "sunrise": "sunrise",
    "sunset": "sunset",
}


HOURS = {"night": "night", "in_time": "in {dur}", "koku": "1 koku", "fast": "fast",
         "midnight": "midnight", "iftar": "iftar"}


MOON = {
    "illuminated": "{pct}% illuminated",
    "age": "day {age} of {total}",
    "lunar_age": "lunar age {age}d",
    "up_now": "Up now",
    "above_horizon": "{alt}° above the horizon",
    "below_horizon": "Below the horizon",
    "moonrise": "Moonrise",
    "moonset": "Moonset",
    "in_days": "in {days}d",
    "begins_at_sunset": "begins at sunset",
    "in_time": "in {dur}",
    "year_day": "Day {n} of {total}",
    "light_of_moon": "light of the moon",
    "dark_of_moon": "dark of the moon",
    "good_for": "Good for {things}",
    "hold_off": "Hold off {things}",
    "light_good": "sowing above-ground crops, grafting, transplanting",
    "light_hold": "root crops",
    "dark_good": "root crops, pruning, weeding",
    "dark_hold": "sowing above-ground crops",
    "solunar_major": "Solunar major",
    "solunar_minor": "minor",
    "spring_equinox": "Spring equinox",
    "summer_solstice": "Summer solstice",
    "autumn_equinox": "Autumn equinox",
    "winter_solstice": "Winter solstice",
}


SOLAR_TERMS = ["Spring Equinox", "Clear and Bright", "Grain Rain",
               "Start of Summer", "Grain Buds", "Grain in Ear",
               "Summer Solstice", "Minor Heat", "Major Heat",
               "Start of Autumn", "End of Heat", "White Dew",
               "Autumn Equinox", "Cold Dew", "Frost's Descent",
               "Start of Winter", "Minor Snow", "Major Snow",
               "Winter Solstice", "Minor Cold", "Major Cold",
               "Start of Spring", "Rain Water", "Awakening of Insects"]


HIJRI_MONTHS = ("Muharram", "Safar", "Rabiʻ al-Awwal", "Rabiʻ al-Thani",
                "Jumada al-Ula", "Jumada al-Thani", "Rajab", "Shaʻban",
                "Ramadan", "Shawwal", "Dhu al-Qaʻdah", "Dhu al-Hijjah")


HIJRI_ERA = "AH"


YEAR_TURN = "Nowruz {year}"


SKY = {
    "sun": "Sun", "moon": "Moon",
    "mercury": "Mercury", "venus": "Venus", "mars": "Mars",
    "jupiter": "Jupiter", "saturn": "Saturn", "uranus": "Uranus",
    "neptune": "Neptune",
    "facing": "facing {dir}",
    "field_of_view": "{deg}° wide",
    "overhead": "overhead",
    "planets_none": "no planets up",
    "star": "star",
    "search_prompt": "name or catalog ID",
    "search_none": "nothing by that name",
    "rises_at": "{name} rises at {time} in the {dir}",
    "never_rises": "{name} never rises from here",
    "search_jump": "enter again to go to that moment",
    "tradition": "tradition",
}


# The cultures' titles. A proper name (Boorong, Tukano) stays as it is
# in the Latin-script languages and is transliterated in the others; a
# name that is an adjective (Chinese, Norse) takes the language's own word.
SKY_CULTURES = {
    "anutan": "Anutan",
    "belarusian": "Belarusian",
    "blackfoot": "Blackfoot",
    "boorong": "Boorong",
    "bugis": "Bugis",
    "chinese": "Chinese",
    "chinese-modern": "Chinese Contemporary",
    "hawaiian": "Hawaiian",
    "indian": "Indian Vedic",
    "japanese": "Japanese Lunar Stations",
    "mandar": "Mandar",
    "maori": "Maori",
    "mongolian": "Mongolian",
    "norse": "Norse",
    "romanian": "Romanian",
    "ruelle": "Ruelle",
    "sami": "Sami",
    "siberian": "Siberian",
    "tongan": "Tongan",
    "tukano": "Tukano",
    "snt": "Western (Sky & Telescope)",
    "rey": "Western (H.A.Rey)",
}
