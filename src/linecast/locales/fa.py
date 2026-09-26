"""Persian.

en.py is the reference, with every key and notes on each; a key
left out here reads in English.
"""


# CLDR's short forms, as Iranian calendars head their columns: the
# days counted from Saturday, "۲ش" the second after it.  A sentence
# names the day in full, by ON_DAY_FORMS.
DAY_NAMES = ["۲ش", "۳ش", "۴ش", "۵ش", "ج", "ش", "۱ش"]


FULL_DAY_NAMES = ["دوشنبه", "سه\u200cشنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


# Persian does not abbreviate the months: ۲۱ مارس.
MONTHS = ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن",
          "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"]


# After fa.wikipedia's گام\u200cهای ماه: ماه نو, تربیع اول, تربیع دوم, and
# افزاینده and کاهنده for waxing and waning; کوژ for gibbous, and
# ماه کامل, the everyday name for بدر.
MOON_PHASES = ["ماه نو", "هلال افزاینده", "تربیع اول", "کوژ افزاینده",
               "ماه کامل", "کوژ کاهنده", "تربیع دوم", "هلال کاهنده"]


# Persian interfaces name an action by its noun or infinitive
# (جستجو، خروج), not by an imperative.
HELP = {
    "hint_help": "راهنما",
    "key_wheel": "چرخ ماوس",
    "key_space": "فاصله",
    "key_hover": "بردن نشانگر",
    "key_click": "کلیک",
    "key_drag": "کشیدن",
    "key_enter": "enter",
    "forecast": "مرور پیش\u200cبینی",
    "now": "بازگشت به اکنون",
    "alert": "خواندن هشدار",
    "browser": "باز کردن هشدار در مرورگر",
    "refresh": "به\u200cروزرسانی پیش\u200cبینی",
    "time30": "جابه\u200cجایی زمان به اندازهٔ ۳۰ دقیقه",
    "time15": "جابه\u200cجایی زمان به اندازهٔ ۱۵ دقیقه",
    "year": "نمای روز / سال",
    "sun_times": "ساعت طلوع و غروب آفتاب",
    "turn_moon": "چرخاندن ماه",
    "calendar": "نمای قرص / تقویم",
    "months": "جابه\u200cجایی یک ماه",
    "moon_times": "گام ماه و ساعت طلوع / غروب",
    "day": "باز کردن روز در نمای قرص",
    "look": "نگاه به اطراف",
    "target": "رفتن به جرم؛ بار دوم، به زمان طلوع آن",
    "figures": "شکل / نام صورت\u200cهای فلکی",
    "cultures": "آسمان در فرهنگ\u200cها",
    "play_time": "گذر زمان: ساعت / روز / هفته در هر ثانیه",
    "compass": "رو به هشت جهت، از شمال تا شمال\u200cغرب",
    "zenith": "نگاه به سمت\u200cالرأس",
    "moon": "رو به ماه، وقتی بالای افق است",
    "frames": "فریم به فریم و توقف",
    "play": "پخش / توقف (توقف: بازگشت به اکنون)",
    "temperature": "لایهٔ دما",
    "wind": "لایهٔ باد",
    "alerts": "لایهٔ هشدارها",
    "theme": "انتخاب پوسته",
    "satellite": "رادار / ماهواره",
}


# Standard written Persian, as IRIMO's bulletins and the news sites
# write a forecast: the subject first, the verb last, and the future
# in the present tense (آغاز می\u200cشود).  Numbers in the tables are
# Persian digits; the placeholders are localised on output.
WEATHER = {
    "today": "امروز",
    "today_short": "امروز",
    "forecast_stale": "این پیش\u200cبینی مربوط به {day} است؛ پیش\u200cبینی تازه\u200cتری دریافت نشد.",
    "forecast_stale_at": ("این پیش\u200cبینی مربوط به {day} است؛ دریافت پیش\u200cبینی تازه\u200cتر "
                          "در ساعت {time} ناموفق بود."),
    "forecast_fetching": "در حال دریافت پیش\u200cبینی تازه\u200cتر…",
    "alerts_unavailable": "بررسی هشدارها ممکن نشد.",
    "alerts_stale": "هشدارها مربوط به {when} است؛ هشدارهای تازه\u200cتر دریافت نشد.",
    "retry_run": "برای تلاش دوباره، برنامه را دوباره اجرا کنید.",
    "retry_key": "برای تلاش دوباره، کلید r را فشار دهید.",
    "credit_forecast": "داده\u200cهای هواشناسی: {source}",
    "credit_alerts": "هشدارها: {source}",
    "credit_current": "وضعیت کنونی: {source}",
    "credit_observed": "دیدبانی ساعت {time} در {place}، به فاصلهٔ {distance}",
    # Units as CLDR's short Persian forms have them: the wind in Latin
    # letters, km/h, as Persian technical text writes it, and the
    # lengths in words, "۱۲ میلی\u200cمتر", which have no Persian
    # abbreviation.  A space sets each off.
    "metric_unit_sep": "\u00a0",
    "unit_mm": "میلی\u200cمتر",
    "unit_cm": "سانتی\u200cمتر",
    "feels": "دمای احساسی",
    "wind": "باد",
    "gusts": "تندباد",
    "humidity": "رطوبت",
    "chance": "احتمال {p}",
    "chance_of": "احتمال {what} {p}",
    "amount_between": "{amount} از {a} تا {b}",
    "amount_all_day": "{amount} در طول روز",
    "cloud": "پوشش ابر {p}",
    "heaviest_around": "بیشترین شدت حدود {time}",
    "dew_pt": "نقطهٔ شبنم",
    "uv": "UV",
    "aqi": "AQI",
    "precip_inch": "″",
    "metric_unit_sep_prose": "\u00a0",
    "precip_inch_prose": "{n}\u00a0اینچ",
    # A sentence spells the wind's unit out, as the forecasts do:
    # "۵۰ کیلومتر بر ساعت"
    "unit_kmh_prose": "کیلومتر بر ساعت",
    "unit_ms_prose": "متر بر ثانیه",
    "unit_mph_prose": "مایل بر ساعت",
    "until": "تا {time}",
    "sentence_end": ".",
    "sentence_join": ". ",
    "feels_humid": "به دلیل رطوبت بالا، هوا گرم\u200cتر احساس می\u200cشود",
    "feels_sun": "به دلیل تابش آفتاب، هوا گرم\u200cتر احساس می\u200cشود",
    "feels_wind": "به دلیل وزش باد، هوا خنک\u200cتر احساس می\u200cشود",
    "feels_dry": "به دلیل خشکی هوا، خنک\u200cتر احساس می\u200cشود",
    "feels_wind_cold": "به دلیل وزش باد، هوا سردتر احساس می\u200cشود",
    "feels_dry_cold": "به دلیل خشکی هوا، سردتر احساس می\u200cشود",
    # The high is a temperature, so it is higher or lower (بالاتر،
    # پایین\u200cتر), not warmer; the verb is in "will_be".
    "degrees": "{n}\u00a0درجه",
    "same_temp": "تقریباً برابر با {ref_day}",
    "bit_warmer": "کمی بالاتر از {ref_day}",
    "bit_cooler": "کمی پایین\u200cتر از {ref_day}",
    "warmer": "بالاتر از {ref_day}",
    "cooler": "پایین\u200cتر از {ref_day}",
    "much_warmer": "بسیار بالاتر از {ref_day}",
    "much_cooler": "بسیار پایین\u200cتر از {ref_day}",
    "warmer_by": "{diff} بالاتر از {ref_day}",
    "cooler_by": "{diff} پایین\u200cتر از {ref_day}",
    "today_subj": "دمای بیشینهٔ امروز",
    "tomorrow_subj": "دمای بیشینهٔ فردا",
    "yesterday": "دیروز",
    "today_ref": "امروز",
    "will_be": "{subject} {comparison} خواهد بود",
    "will_be_then": "دمای بیشینه {comparison} خواهد بود",
    # Precipitation: a turn to another kind is "تبدیل می\u200cشود", and the
    # same rain harder "شدت می\u200cگیرد"
    "ending": "{desc} {time} قطع می\u200cشود",
    "continuing": "{desc} در تمام طول روز ادامه دارد",
    "ending_becoming": "{desc} {peak_time} به {peak} تبدیل می\u200cشود و {time} قطع می\u200cشود",
    "continuing_becoming": "{desc} {peak_time} به {peak} تبدیل می\u200cشود و تا پایان روز ادامه دارد",
    "starting": "{desc} احتمالاً {time} آغاز می\u200cشود",
    "starting_becoming": "{desc} احتمالاً {time} آغاز می\u200cشود و {peak_time} به {peak} تبدیل می\u200cشود",
    # A chance takes the subjunctive: "احتمال دارد باران … آغاز شود"
    "starting_chance": "احتمال دارد {desc} {time} آغاز شود",
    "starting_chance_becoming": "احتمال دارد {desc} {time} آغاز شود و {peak_time} به {peak} تبدیل شود",
    "starting_sure": "{desc} {time} آغاز می\u200cشود",
    "starting_sure_becoming": "{desc} {time} آغاز می\u200cشود و {peak_time} به {peak} تبدیل می\u200cشود",
    "continuing_night": "{desc} در تمام طول شب ادامه دارد",
    "continuing_night_becoming": "{desc} {peak_time} به {peak} تبدیل می\u200cشود و تا پایان شب ادامه دارد",
    "ending_heavier": "{desc} {peak_time} شدت می\u200cگیرد و {time} قطع می\u200cشود",
    "continuing_heavier": "{desc} {peak_time} شدت می\u200cگیرد و تا پایان روز ادامه دارد",
    "continuing_night_heavier": "{desc} {peak_time} شدت می\u200cگیرد و تا پایان شب ادامه دارد",
    "starting_heavier": "{desc} احتمالاً {time} آغاز می\u200cشود و {peak_time} شدت می\u200cگیرد",
    "starting_chance_heavier": "احتمال دارد {desc} {time} آغاز شود و {peak_time} شدت بگیرد",
    "starting_sure_heavier": "{desc} {time} آغاز می\u200cشود و {peak_time} شدت می\u200cگیرد",
    "more_later": "{time} دوباره {desc} پیش\u200cبینی می\u200cشود",
    # "By" a time is "تا": the "_by" forms carry it, so the "same_time"
    # word can stand in the slot without it
    "snow_total": "{time} حدود {amt} برف می\u200cبارد",
    "fog_ending": "مه {time} برطرف می\u200cشود",
    "fog_continuing": "مه در تمام طول روز ادامه دارد",
    "fog_continuing_night": "مه در تمام طول شب ادامه دارد",
    "fog_starting": "{time} مه تشکیل می\u200cشود",
    "fog_starting_ending": "{time} مه تشکیل می\u200cشود و {end} برطرف می\u200cشود",
    "shortly": "به\u200cزودی",
    "in_about_an_hour": "حدود یک ساعت دیگر",
    "in_a_couple_hours": "تا چند ساعت دیگر",
    "around": "حدود {time}",
    "around_noon": "حدود ظهر",
    "same_time": "در همان ساعات",
    "same_part_later": "کمی بعد",
    # The small hours are "پس از نیمه\u200cشب"; the evening is "عصر", and
    # later in it the night, "شب"
    "overnight": "پس از نیمه\u200cشب",
    "early_tomorrow_morning": "فردا صبح زود",
    "tomorrow_morning": "فردا صبح",
    "tomorrow_afternoon": "فردا بعدازظهر",
    "tomorrow_evening": "فردا عصر",
    "on_day": "روز {day}",
    "then_early_morning": "صبح زود",
    "then_morning": "صبح",
    "then_later_morning": "اواخر صبح",
    "then_afternoon": "بعدازظهر",
    "then_later_afternoon": "اواخر بعدازظهر",
    "then_evening": "عصر",
    "then_later_evening": "شب",
    "this_morning": "امروز صبح",
    "this_afternoon": "امروز بعدازظهر",
    "this_evening": "امروز عصر",
    "tonight": "امشب",
    "this_morning_by": "تا امروز صبح",
    "this_afternoon_by": "تا امروز بعدازظهر",
    "this_evening_by": "تا امروز عصر",
    "tonight_by": "تا امشب",
    "tomorrow_morning_by": "تا فردا صبح",
    "tomorrow_afternoon_by": "تا فردا بعدازظهر",
    "tomorrow_evening_by": "تا فردا عصر",
    "sky_clearing": "آسمان {time} صاف می\u200cشود",
    "sky_clouding": "آسمان {time} ابری می\u200cشود",
    "on_full_day": "روز {day}",
    "rain_next_chance": "{time} احتمال {desc} وجود دارد",
    "rain_next_likely": "{time} احتمال {desc} زیاد است",
    "rain_next": "{time} {desc} پیش\u200cبینی می\u200cشود",
    "on_two_days": "روزهای {first} و {second}",
    "from_day_to_day": "از {first} تا {last}",
    "rain_run_heaviest": "{sentence}؛ بیشترین بارش {day} خواهد بود",
    "tomorrow_and_day": "فردا و روز {second}",
    "from_tomorrow_to_day": "از فردا تا {last}",
    "on_tomorrow": "فردا",
    "rain_run_with": "{sentence}؛ {day} {with} نیز پیش\u200cبینی می\u200cشود",
    "rain_run_then": "{sentence}؛ سپس {day} {with} پیش\u200cبینی می\u200cشود",
    "rain_run_heaviest_with": "{sentence}؛ بیشترین بارش {day} خواهد بود، همراه با {with}",
    "gusts_to": "{time} سرعت تندباد به {speed} می\u200cرسد",
    # A clause of its own, so it reads whole after a subjunctive chance
    "with_gusts": "{sentence}؛ سرعت تندباد نیز به {speed} می\u200cرسد",
    "freeze_tonight": "{time} دمای هوا به زیر صفر می\u200cرسد و تا {temp} پایین می\u200cآید",
    "feels_ahead_hot": "{time} دمای احساسی تا {temp} بالا می\u200cرود",
    "feels_ahead_hot_humid": "{time} به دلیل رطوبت بالا، دمای احساسی تا {temp} بالا می\u200cرود",
    "feels_ahead_hot_sun": "{time} به دلیل تابش آفتاب، دمای احساسی تا {temp} بالا می\u200cرود",
    "feels_ahead_cold": "{time} دمای احساسی تا {temp} پایین می\u200cآید",
    "feels_ahead_cold_wind": "{time} به دلیل وزش باد، دمای احساسی تا {temp} پایین می\u200cآید",
    "past_precip": "در ۲۴ ساعت گذشته {amt} {ptype} باریده است",
    "snow": "برف",
    "rain": "باران",
    "mixed_precip": "برف و باران",
    "Snow": "برف",
    "Rain": "باران",
    "Mix": "برف و باران",
    # Key legends in the noun form Persian interfaces use
    "q_to_close": "بستن با q",
    "o_to_open": "باز کردن در مرورگر با o",
    "scroll": "پیمایش",
    "space_to_now": "بازگشت به اکنون با فاصله",
    "hist_near_avg": "نزدیک به میانگین",
    "hist_above_avg": "{diff} بالاتر از میانگین",
    "hist_below_avg": "{diff} پایین\u200cتر از میانگین",
}


# The sky as IRIMO grades it: صاف، کمی ابری، نیمه\u200cابری، ابری،
# تمام\u200cابری.  Drizzle is نم\u200cنم باران, and a thunderstorm what
# people call it, رعد و برق.
CONDITIONS = {
    0: "صاف", 1: "کمی ابری", 2: "نیمه\u200cابری", 3: "تمام\u200cابری",
    45: "مه", 48: "مه یخ\u200cزده",
    51: "نم\u200cنم باران", 53: "نم\u200cنم باران", 55: "نم\u200cنم باران شدید",
    56: "نم\u200cنم باران یخ\u200cزده", 57: "نم\u200cنم باران یخ\u200cزده",
    61: "باران خفیف", 63: "باران", 65: "باران شدید",
    66: "باران یخ\u200cزده", 67: "باران یخ\u200cزده",
    71: "برف خفیف", 73: "برف", 75: "برف شدید", 77: "برف دانه\u200cای",
    80: "رگبار خفیف", 81: "رگبار", 82: "رگبار شدید",
    85: "رگبار برف", 86: "رگبار شدید برف",
    95: "رعد و برق", 96: "رعد و برق", 99: "رعد و برق",
    "mostly_cloudy": "ابری",
}


# IRIMO names a thunderstorm by what comes with it, "رگبار و رعد و
# برق".  The templates' verbs (آغاز می\u200cشود، قطع می\u200cشود، ادامه
# دارد) fit every noun here, so no code needs a variant.
PRECIP = {
    51: "نم\u200cنم باران", 53: "نم\u200cنم باران", 55: "نم\u200cنم باران شدید",
    56: "نم\u200cنم باران یخ\u200cزده", 57: "نم\u200cنم باران یخ\u200cزده",
    61: "باران خفیف", 63: "باران", 65: "باران شدید",
    66: "باران یخ\u200cزده", 67: "باران یخ\u200cزده",
    71: "برف خفیف", 73: "برف", 75: "برف شدید", 77: "برف دانه\u200cای",
    80: "رگبار خفیف", 81: "رگبار", 82: "رگبار شدید",
    85: "رگبار برف", 86: "رگبار شدید برف",
    95: "رگبار و رعد و برق", 96: "رگبار و رعد و برق", 99: "رگبار و رعد و برق",
}


# Persian abbreviates the days by number ("۲ش"), which running text
# does not; the sentence names the day in full
ON_DAY = {0: "روز دوشنبه", 1: "روز سه\u200cشنبه", 2: "روز چهارشنبه", 3: "روز پنجشنبه",
          4: "روز جمعه", 5: "روز شنبه", 6: "روز یکشنبه"}


LOCATIONS = {
    "locations": "مکان\u200cها",
    "add": "افزودن مکان",
    "clear": "پاک کردن مکان\u200cهای اخیر",
    "loading": "در حال بارگذاری {name}…",
    "failed": "بارگذاری وضعیت هوای {name} ممکن نشد. لطفاً دوباره امتحان کنید.",
    "save": "ذخیرهٔ {name} به\u200cعنوان پیش\u200cفرض",
    "saved": "{name} به\u200cعنوان مکان پیش\u200cفرض همهٔ نماها ذخیره شد.",
    "save_failed": "ذخیرهٔ مکان پیش\u200cفرض ممکن نشد. لطفاً دوباره امتحان کنید.",
}


RADAR = {
    "loading": "در حال بارگیری…",
    "hint": "فاصله پخش/توقف · چرخ ماوس/←→ فریم · +/- بزرگ\u200cنمایی · کشیدن / wasd جابه\u200cجایی · c دما · W باد · t پوسته · S ماهواره · q خروج",
    "theme": "پوسته",
    "now": "اکنون",
    # "۱۲ کیلومتری شمال\u200cشرق تهران": the distance takes the -ی of
    # an adverb of place, so the unit is written into the phrase.
    "near": "{dist} {unit}ی {dir} {name}",
    "unit_km": "کیلومتر",
    "unit_mi": "مایل",
    "compass": "شمال شمال\u200cشرق شرق جنوب\u200cشرق جنوب جنوب\u200cغرب غرب شمال\u200cغرب",
    "forecast": "پیش\u200cبینی",
    "echo_pct": "بازتاب {pct}٪",
    "cloud_pct": "ابر {pct}٪",
    "radar_unavailable": "رادار در دسترس نیست ({err})",
    "no_frames": "هیچ فریم راداری در دسترس نیست",
}


# The road classes are Iran's own: آزادراه, بزرگراه, راه اصلی,
# راه فرعی, the ladder Iranian road law and signage use; OSM's
# Persian wiki also gives آزادراه for a motorway.
MAPS = {
    "hint": "wasd · v نما · / جستجو · ? راهنما",
    "hint_route": "D مسیریابی · n پاک کردن",
    "unavailable": "نقشهٔ عوارض زمین در دسترس نیست ({err})",
    "streets_unavailable": "کاشی\u200cهای نقشهٔ خیابان در دسترس نیست ({err})",
    "offline": "بدون کاشی",
    "mode_terrain": "عوارض زمین",
    "mode_street": "خیابان",
    "sun_over": "خورشید بر فراز {place}",
    "search_prompt": "جستجوی مکان",
    "search_dest_prompt": "جستجوی مقصد",
    "search_origin_prompt": "جستجوی مبدأ",
    "search_hint": "↑↓ انتخاب · enter رفتن · esc بستن",
    "search_none": "نتیجه\u200cای پیدا نشد",
    "search_error": "جستجو در دسترس نیست",
    "dir_wait": "در حال مسیریابی…",
    "dir_none": "مسیری پیدا نشد",
    "dir_unavailable": "مسیریابی در دسترس نیست",
    "profile_car": "خودرو",
    "profile_bike": "دوچرخه",
    "profile_foot": "پیاده",
    "dir_from": "مبدأ",
    "dir_to": "مقصد",
    "dir_mode": "وسیله",
    "steps_hint": "↑↓ مرحله · esc بستن",
    "help_title": "کلیدها",
    "help_close": "esc بستن",
    "help_pan": "جابه\u200cجایی",
    "help_zoom_pointer": "بزرگ\u200cنمایی در محل نشانگر",
    "help_hover": "شناسایی",
    "help_zoom": "بزرگ\u200cنمایی",
    "help_reset": "بازگشت به آغاز",
    "help_view": "خیابان · عوارض زمین",
    "help_labels": "برچسب\u200cها و خطوط",
    "help_sky": "روشنایی روز · ابرها",
    "help_spin": "چرخاندن کره",
    "help_search": "جستجو",
    "help_directions": "مسیریابی",
    "help_origin": "تعیین مبدأ",
    "help_profile": "شیوهٔ سفر",
    "help_keys": "همین فهرست",
    "help_quit": "خروج",
    "poi_airport": "فرودگاه",
    "poi_peak": "قله",
    "poi_station": "ایستگاه",
    "poi_hospital": "بیمارستان",
    "poi_civic": "اداره · مدرسه",
    "poi_lodging": "اقامتگاه",
    "poi_notable": "موزه · جاذبه",
    "poi_worship": "عبادتگاه",
    "poi_ferry": "کشتی · اسکله",
    "poi_other": "مکان",
    "poi_capital": "پایتخت",
    "hov_motorway": "آزادراه",
    "hov_ramp": "رمپ",
    "hov_trunk": "بزرگراه",
    "hov_primary": "راه اصلی",
    "hov_secondary": "راه فرعی",
    "hov_minor": "خیابان",
    "hov_service": "راه دسترسی",
    "hov_path": "مسیر پیاده",
    "hov_rail": "راه\u200cآهن",
    "hov_transit": "خط حمل\u200cونقل عمومی",
    "hov_ferry": "خط کشتی",
    "hov_river": "رود",
    "hov_stream": "نهر",
    "hov_runway": "باند فرودگاه",
    "hov_taxiway": "خزش\u200cراه",
    "hov_border": "مرز",
    "hov_coast": "خط ساحلی",
    "hov_water": "آب",
    "hov_park": "پارک",
    "hov_building": "ساختمان",
    "hov_urban": "منطقهٔ شهری",
}


TIDES = {
    "space_to_now": "فاصله برای بازگشت به اکنون",
    "waves": "امواج",
    "swell": "خیزاب",
    "tide_model": "مدل جزر و مد Open-Meteo",
    "period": " ({s} ثانیه)",
    "no_tides": "پیش\u200cبینی جزر و مد برای {name} در دسترس نیست.",
    "load_failed": "بارگیری جزر و مد {name} ممکن نشد. لطفاً دوباره امتحان کنید.",
}


# The twilights as fa.wikipedia's شفق names them; شفق is the
# twilight at either end of the night, so one word serves both.
SUNSHINE = {
    "today": "امروز",
    "in_day": "{n} روز دیگر",
    "in_days": "{n} روز دیگر",
    "day_ago": "{n} روز پیش",
    "days_ago": "{n} روز پیش",
    "sky_night": "شب",
    "sky_astronomical": "شفق اخترشناختی",
    "sky_nautical": "شفق دریایی",
    "sky_civil": "شفق مدنی",
    "sky_day": "روز",
    "midnight_sun": "خورشید نیمه\u200cشب",
    "polar_night": "شب قطبی",
    "solar_noon": "ظهر خورشیدی",
    "sunrise": "طلوع آفتاب",
    "sunset": "غروب آفتاب",
}


# ژوئن and ژوئیه share their first letters, and the rest are too
# long to cut; month numbers, as for Greek.
CHART_MONTHS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]


HOURS = {"night": "شب", "in_time": "{dur} دیگر", "koku": "۱ کوکو", "fast": "روزه",
         "midnight": "نیمه\u200cشب شرعی", "iftar": "افطار"}


MOON = {
    "illuminated": "روشنایی {pct}٪",
    "age": "روز {age} از {total}",
    "lunar_age": "سن ماه {age} روز",
    "up_now": "اکنون در آسمان",
    "above_horizon": "{alt}° بالای افق",
    "below_horizon": "زیر افق",
    "moonrise": "طلوع ماه",
    "moonset": "غروب ماه",
    "in_days": "{days} روز دیگر",
    "begins_at_sunset": "از غروب آفتاب آغاز می\u200cشود",
    "in_time": "{dur} دیگر",
    "year_day": "روز {n} از {total}",
    "light_of_moon": "ماه افزاینده",
    "dark_of_moon": "ماه کاهنده",
    "good_for": "مناسب برای {things}",
    "hold_off": "{things} را به بعد موکول کنید",
    "light_good": "کاشت محصولات روی\u200cزمینی، پیوند زدن، نشاکاری",
    "light_hold": "کاشت محصولات ریشه\u200cای",
    "dark_good": "کاشت محصولات ریشه\u200cای، هرس، وجین",
    "dark_hold": "کاشت محصولات روی\u200cزمینی",
    "solunar_major": "دورهٔ اصلی سولونار",
    "solunar_minor": "فرعی",
    "spring_equinox": "اعتدال بهاری",
    "summer_solstice": "انقلاب تابستانی",
    "autumn_equinox": "اعتدال پاییزی",
    "winter_solstice": "انقلاب زمستانی",
}


HIJRI_MONTHS = ("محرم", "صفر", "ربیع\u200cالاول", "ربیع\u200cالثانی",
                "جمادی\u200cالاول", "جمادی\u200cالثانی", "رجب", "شعبان",
                "رمضان", "شوال", "ذی\u200cالقعده", "ذی\u200cالحجه")


HIJRI_ERA = "ق"


HIJRI_SIGHTING_NOTE = "به تقویم ام\u200cالقری؛ در ایران ممکن است یک روز فرق کند"


YEAR_TURN = "تحویل سال {year}"


SKY = {
    "sun": "خورشید", "moon": "ماه",
    "mercury": "عطارد", "venus": "زهره", "mars": "مریخ",
    "jupiter": "مشتری", "saturn": "زحل", "uranus": "اورانوس",
    "neptune": "نپتون",
    "facing": "رو به {dir}",
    "field_of_view": "میدان دید {deg}°",
    "overhead": "در سمت\u200cالرأس",
    "planets_none": "هیچ سیاره\u200cای بالای افق نیست",
    "star": "ستاره",
    "search_prompt": "نام یا شمارهٔ کاتالوگ",
    "search_none": "چیزی با این نام پیدا نشد",
    "rises_at": "{name} ساعت {time} از {dir} طلوع می\u200cکند",
    "never_rises": "{name} از اینجا هرگز طلوع نمی\u200cکند",
    "search_jump": "برای رفتن به آن لحظه، دوباره enter",
    "tradition": "سنت",
}


SKY_CULTURES = {
    "anutan": "آنوتا",
    "belarusian": "بلاروسی",
    "blackfoot": "بلک\u200cفوت",
    "boorong": "بورونگ",
    "bugis": "بوگیس",
    "chinese": "چینی",
    "chinese-modern": "چینی معاصر",
    "hawaiian": "هاوایی",
    "indian": "ودایی هند",
    "japanese": "منازل قمر ژاپنی",
    "mandar": "ماندار",
    "maori": "مائوری",
    "mongolian": "مغولی",
    "norse": "اسکاندیناویایی",
    "romanian": "رومانیایی",
    "ruelle": "روئل",
    "sami": "سامی",
    "siberian": "سیبریایی",
    "tongan": "تونگایی",
    "tukano": "توکانو",
    "snt": "غربی (Sky & Telescope)",
    "rey": "غربی (H.A.Rey)",
}
