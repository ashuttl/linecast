"""Turkish.

en.py is the reference, with every key and notes on each; a key
left out here reads in English.
"""


SETTINGS = {
    "decimal": ",",
    "percent": "%{n}",
}


DAY_NAMES = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


FULL_DAY_NAMES = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
          "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


MOON_PHASES = ["Yeni Ay", "Büyüyen hilal", "İlk dördün", "Büyüyen şişkin Ay",
               "Dolunay", "Küçülen şişkin Ay", "Son dördün", "Küçülen hilal"]


HELP = {
    "hint_help": "yardım",
    "key_wheel": "tekerlek",
    "key_space": "boşluk",
    "key_hover": "üzerine gelme",
    "key_click": "tıklama",
    "key_drag": "sürükleme",
    "key_enter": "enter",
    "forecast": "tahmine göz at",
    "now": "şimdiye dön",
    "alert": "bir uyarıyı oku",
    "browser": "uyarıyı tarayıcıda aç",
    "refresh": "tahmini yenile",
    "time30": "zamanı 30 dakika oynat",
    "time15": "zamanı 15 dakika oynat",
    "year": "gün / yıl görünümü",
    "sun_times": "gün doğumu ve batımı saatleri",
    "turn_moon": "Ay'ı döndür",
    "calendar": "disk / takvim görünümü",
    "months": "bir ay kaydır",
    "moon_times": "evre ve doğuş / batış saatleri",
    "day": "günü disk görünümünde aç",
    "look": "etrafa bak",
    "target": "hedefe git; tekrar basınca doğuş saatine",
    "figures": "takımyıldız şekilleri / adları",
    "cultures": "gök kültürleri",
    "play_time": "zamanı oynat: saniyede saat / gün / hafta",
    "compass": "K, KD, D, GD, G, GB, B, KB yönüne bak",
    "zenith": "tam yukarıya bak",
    "moon": "Ay gökteyken Ay'a bak",
    "frames": "kareleri adımla ve duraklat",
    "play": "oynat / duraklat (duraklatma şimdiye döner)",
    "temperature": "sıcaklık katmanı",
    "wind": "rüzgar katmanı",
    "alerts": "uyarı katmanı",
    "theme": "tema seç",
    "satellite": "radar / uydu",
}


WEATHER = {
    "today": "Bugün",
    "today_short": "Bugün",
    # "{day} gününe ait" takes a weekday or an ISO date alike; a bare
    # "{day}'den" would need the suffix to agree with the day's vowels.
    "forecast_stale": "Bu tahmin {day} gününe ait; daha yenisi alınamadı.",
    "forecast_stale_at": "Bu tahmin {day} gününe ait; {time} itibarıyla daha yenisi alınamadı.",
    "forecast_fetching": "Daha yeni tahmin alınıyor…",
    "alerts_unavailable": "Uyarılar kontrol edilemedi.",
    "alerts_stale": "Uyarılar {when} itibarıyla; daha yenileri alınamadı.",
    "retry_run": "Yeniden denemek için tekrar çalıştırın.",
    "retry_key": "Yeniden denemek için r tuşuna basın.",
    "credit_forecast": "Hava verileri: {source}",
    "credit_alerts": "Uyarılar: {source}",
    "credit_current": "Güncel hava durumu: {source}",
    "credit_observed": "{time} gözlemi: {place}, {distance} uzaklıkta",
    "precip_inch": "″",
    # Turkish sets units off with a space, and reads the hour as
    # "saat": 3 mm, 12 km/sa.
    "metric_unit_sep": "\u00a0",
    "unit_kmh": "km/sa",
    "feels": "hissedilen",
    "wind": "Rüzgar",
    "gusts": "hamle",
    "humidity": "Nem",
    "chance": "olasılık {p}",
    "chance_of": "{what} olasılığı {p}",
    "amount_between": "{a} ile {b} arasında {amount}",
    "amount_all_day": "gün boyunca {amount}",
    "cloud": "Bulut {p}",
    "heaviest_around": "en yoğun {time} civarında",
    "dew_pt": "Çiy n.",
    "uv": "UV",
    "aqi": "HKİ",
    # {time_dat} is the time in the dative, its suffix chosen by how the
    # time is read aloud: "20:00'ye", "16:00'ya", "21:30'a".
    "until": "{time_dat} kadar",
    "sentence_end": ".",
    "sentence_join": ". ",
    "feels_humid": "Yüksek nem nedeniyle hava olduğundan daha sıcak hissediliyor",
    "feels_sun": "Güneş nedeniyle hava olduğundan daha sıcak hissediliyor",
    "feels_wind": "Rüzgar nedeniyle hava olduğundan daha serin hissediliyor",
    "feels_dry": "Kuru hava nedeniyle olduğundan daha serin hissediliyor",
    "feels_wind_cold": "Rüzgar nedeniyle hava olduğundan daha soğuk hissediliyor",
    "feels_dry_cold": "Kuru hava nedeniyle olduğundan daha soğuk hissediliyor",
    # The reference day takes a case suffix, "bugünden", "dünle"; both
    # words end in ü, so one spelling of each suffix serves.
    "same_temp": "{ref_day}yle hemen hemen aynı",
    "bit_warmer": "{ref_day}nden biraz daha yüksek",
    "bit_cooler": "{ref_day}nden biraz daha düşük",
    "warmer": "{ref_day}nden daha yüksek",
    "cooler": "{ref_day}nden daha düşük",
    "much_warmer": "{ref_day}nden çok daha yüksek",
    "much_cooler": "{ref_day}nden çok daha düşük",
    "today_subj": "Bugün en yüksek sıcaklık",
    "tomorrow_subj": "Yarın en yüksek sıcaklık",
    "yesterday": "dünkü",
    "today_ref": "bugünkü",
    "will_be": "{subject} {comparison} olacak",
    "ending": "{desc} {time} sona erecek",
    "continuing": "{desc} gün boyunca sürecek",
    "ending_becoming": "{desc} {peak_time} {peak_art} dönüşecek ve {time} sona erecek",
    "continuing_becoming": "{desc} {peak_time} {peak_art} dönüşecek ve gün boyunca sürecek",
    "starting": "{desc} muhtemelen {time} başlayacak",
    "starting_becoming": "{desc} muhtemelen {time} başlayacak, {peak_time} {peak_art} dönüşecek",
    "shortly": "kısa süre içinde",
    "in_about_an_hour": "yaklaşık bir saat içinde",
    "in_a_couple_hours": "birkaç saat içinde",
    "around": "saat {time} civarında",
    "around_noon": "öğle saatlerinde",
    "same_time": "aynı saatlerde",
    "overnight": "gece saatlerinde",
    "early_tomorrow_morning": "yarın sabah erken saatlerde",
    "tomorrow_morning": "yarın sabah",
    "tomorrow_afternoon": "yarın öğleden sonra",
    "tomorrow_evening": "yarın akşam",
    "on_day": "{day} günü",
    "past_precip": "Son 24\u00a0saatte {amt} {ptype} yağdı",
    "snow": "kar",
    "rain": "yağmur",
    "mixed_precip": "karla karışık yağmur",
    "Snow": "Kar",
    "Rain": "Yağmur",
    "Mix": "Karışık",
    "q_to_close": "kapatmak için q",
    "o_to_open": "tarayıcıda açmak için o",
    "scroll": "kaydır",
    "space_to_now": "şimdiye dönmek için boşluk",
    "hist_near_avg": "ortalamaya yakın",
    "hist_above_avg": "ortalamanın {diff} üzerinde",
    "hist_below_avg": "ortalamanın {diff} altında",
    "degrees": "{n}\u00a0derece",
    "warmer_by": "{ref_day}nden {diff} daha yüksek",
    "cooler_by": "{ref_day}nden {diff} daha düşük",
    "starting_chance": "{desc} {time} başlayabilir",
    "starting_chance_becoming": "{desc} {time} başlayabilir, {peak_time} {peak_art} dönüşebilir",
    "starting_sure": "{desc} {time} başlayacak",
    "starting_sure_becoming": "{desc} {time} başlayacak, {peak_time} {peak_art} dönüşecek",
    "continuing_night": "{desc} gece boyunca sürecek",
    "continuing_night_becoming": "{desc} {peak_time} {peak_art} dönüşecek ve gece boyunca sürecek",
    "more_later": "{time} yeniden {desc} bekleniyor",
    "snow_total": "{time} yaklaşık {amt} kar birikecek",
    "fog_ending": "Sis {time} dağılacak",
    "fog_continuing": "Sis gün boyunca sürecek",
    "fog_continuing_night": "Sis gece boyunca sürecek",
    "fog_starting": "{time} sis bekleniyor",
    "fog_starting_ending": "{time} sis bekleniyor, {end} dağılacak",
    "then_early_morning": "sabah erken saatlerde",
    "then_morning": "sabah",
    "then_later_morning": "sabahın ilerleyen saatlerinde",
    "then_afternoon": "öğleden sonra",
    "then_later_afternoon": "öğleden sonra geç saatlerde",
    "then_evening": "akşam",
    "then_later_evening": "akşamın ilerleyen saatlerinde",
    "this_morning": "bu sabah",
    "this_afternoon": "bu öğleden sonra",
    "this_evening": "bu akşam",
    "tonight": "bu gece",
    "sky_clearing": "{time} hava açacak",
    "sky_clouding": "{time} hava kapanacak",
    "on_full_day": "{day} günü",
    "rain_next_chance": "{time} {desc} olasılığı var",
    "rain_next_likely": "{time} {desc} olasılığı yüksek",
    "rain_next": "{time} {desc} bekleniyor",
    "on_two_days": "{first} ve {second} günleri",
    "from_day_to_day": "{first} {last} kadar",
    "rain_run_heaviest": "{sentence}, en yoğun {day}",
    "tomorrow_and_day": "yarın ve {second} günü",
    "from_tomorrow_to_day": "yarından {last} kadar",
    "on_tomorrow": "yarın",
    "rain_run_with": "{sentence}, {day} {with} da bekleniyor",
    "rain_run_then": "{sentence}, ardından {day} {with}",
    "rain_run_heaviest_with": "{sentence}, en yoğun {day}, {with} da bekleniyor",
    "gusts_to": "{time} rüzgar {speed} hıza varan hamlelerle esecek",
    "with_gusts": "{sentence}, rüzgar {speed} hıza varan hamlelerle esecek",
    # A temperature always ends in "derece", so it takes the dative
    # as "dereceye" whatever the number.
    "freeze_tonight": "{time} don bekleniyor, sıcaklık {temp}ye kadar düşecek",
    "feels_ahead_hot": "{time} hissedilen sıcaklık {temp}ye kadar çıkacak",
    "feels_ahead_hot_humid": "Yüksek nem nedeniyle {time} hissedilen sıcaklık {temp}ye kadar çıkacak",
    "feels_ahead_hot_sun": "Güneş nedeniyle {time} hissedilen sıcaklık {temp}ye kadar çıkacak",
    "feels_ahead_cold": "{time} hissedilen sıcaklık {temp}ye kadar düşecek",
    "feels_ahead_cold_wind": "Rüzgar nedeniyle {time} hissedilen sıcaklık {temp}ye kadar düşecek",
    "will_be_then": "En yüksek sıcaklık {comparison} olacak",
    "ending_heavier": "{desc} {peak_time} şiddetlenecek ve {time} sona erecek",
    "continuing_heavier": "{desc} {peak_time} şiddetlenecek ve gün boyunca sürecek",
    "continuing_night_heavier": "{desc} {peak_time} şiddetlenecek ve gece boyunca sürecek",
    "starting_heavier": "{desc} muhtemelen {time} başlayacak, {peak_time} şiddetlenecek",
    "starting_chance_heavier": "{desc} {time} başlayabilir, {peak_time} şiddetlenebilir",
    "starting_sure_heavier": "{desc} {time} başlayacak, {peak_time} şiddetlenecek",
    "this_morning_by": "bu sabaha kadar",
    "this_afternoon_by": "bu öğleden sonraya kadar",
    "this_evening_by": "bu akşama kadar",
    "tonight_by": "bu geceye kadar",
    "tomorrow_morning_by": "yarın sabaha kadar",
    "tomorrow_afternoon_by": "yarın öğleden sonraya kadar",
    "tomorrow_evening_by": "yarın akşama kadar",
}


CONDITIONS = {
    0: "Açık", 1: "Az bulutlu", 2: "Parçalı bulutlu", 3: "Kapalı",
    45: "Sis", 48: "Kırçlı sis",
    51: "Hafif çisenti", 53: "Çisenti", 55: "Yoğun çisenti",
    56: "Dondurucu çisenti", 57: "Dondurucu çisenti",
    61: "Hafif yağmur", 63: "Yağmur", 65: "Kuvvetli yağmur",
    66: "Dondurucu yağmur", 67: "Dondurucu yağmur",
    71: "Hafif kar", 73: "Kar", 75: "Yoğun kar", 77: "Kar taneleri",
    80: "Hafif sağanak", 81: "Sağanak", 82: "Kuvvetli sağanak",
    85: "Kar sağanağı", 86: "Kuvvetli kar sağanağı",
    95: "Gök gürültülü fırtına", 96: "Gök gürültülü fırtına", 99: "Gök gürültülü fırtına",
    "mostly_cloudy": "Çok bulutlu",
}


PRECIP = {
    51: "hafif çisenti", 53: "çisenti", 55: "yoğun çisenti",
    56: "dondurucu çisenti", 57: "dondurucu çisenti",
    61: "hafif yağmur", 63: "yağmur", 65: "kuvvetli yağmur",
    66: "dondurucu yağmur", 67: "dondurucu yağmur",
    71: "hafif kar", 73: "kar", 75: "yoğun kar", 77: "kar taneleri",
    80: "hafif sağanak", 81: "sağanak", 82: "kuvvetli sağanak",
    85: "kar sağanağı", 86: "kuvvetli kar sağanağı",
    # MGM's word for thunder is "gök gürültülü sağanak"; a "fırtına"
    # is a gale.
    95: "gök gürültülü sağanak", 96: "gök gürültülü sağanak", 99: "gök gürültülü sağanak",
}


# Turkish turns one thing into another in the dative, "sağanağa
# dönüşecek", and the suffix follows the noun's last vowel and
# softens its last consonant.
PRECIP_PARTITIVES = {
    51: "hafif çisentiye", 53: "çisentiye", 55: "yoğun çisentiye",
    56: "dondurucu çisentiye", 57: "dondurucu çisentiye",
    61: "hafif yağmura", 63: "yağmura", 65: "kuvvetli yağmura",
    66: "dondurucu yağmura", 67: "dondurucu yağmura",
    71: "hafif kara", 73: "kara", 75: "yoğun kara", 77: "kar tanelerine",
    80: "hafif sağanağa", 81: "sağanağa", 82: "kuvvetli sağanağa",
    85: "kar sağanağına", 86: "kuvvetli kar sağanağına",
    95: "gök gürültülü sağanağa", 96: "gök gürültülü sağanağa", 99: "gök gürültülü sağanağa",
}


DAY_SPANS = {
    "from": {0: "Pazartesiden", 1: "Salıdan", 2: "Çarşambadan", 3: "Perşembeden", 4: "Cumadan", 5: "Cumartesiden", 6: "Pazardan"},
    "to": {0: "Pazartesiye", 1: "Salıya", 2: "Çarşambaya", 3: "Perşembeye", 4: "Cumaya", 5: "Cumartesiye", 6: "Pazara"},
}


LOCATIONS = {
    "locations": "Konumlar",
    "add": "Konum ekle",
    "clear": "Son konumları temizle",
    "loading": "{name} yükleniyor…",
    "failed": "{name} için hava durumu yüklenemedi. Lütfen tekrar deneyin.",
    "save": "{name} varsayılan olsun",
    "saved": "{name} tüm görünümler için varsayılan konum olarak kaydedildi.",
    "save_failed": "Varsayılan konum kaydedilemedi. Lütfen tekrar deneyin.",
}


RADAR = {
    "loading": "yükleniyor…",
    "hint": "boşluk oynat/duraklat · kaydırma/←→ adımla · +/- yakınlaştır · sürükle / wasd · c sıcaklık · W rüzgar · t tema · S uydu · q çık",
    "theme": "tema",
    "now": "şimdi",
    # "12 km NE of Paris" would put the genitive on the place name;
    # the place comes first, and the distance after a comma.
    "near": "{name}, {dist} {unit} {dir}",
    "compass": "K KD D GD G GB B KB",
    "forecast": "tahmin",
    "echo_pct": "%{pct} yankı",
    "cloud_pct": "%{pct} bulut",
    "radar_unavailable": "radar kullanılamıyor ({err})",
    "no_frames": "radar karesi yok",
}


MAPS = {
    "hint": "wasd · v görünüm · / ara · ? yardım",
    "hint_route": "D yol tarifi · n temizle",
    "unavailable": "arazi kullanılamıyor ({err})",
    "streets_unavailable": "sokak karoları kullanılamıyor ({err})",
    "offline": "karo yok",
    "mode_terrain": "arazi",
    "mode_street": "sokak",
    "sun_over": "{place} üzerinde güneş",
    "search_prompt": "yer ara",
    "search_dest_prompt": "varış noktası ara",
    "search_origin_prompt": "başlangıç noktası ara",
    "search_hint": "↑↓ seç · enter git · esc kapat",
    "search_none": "sonuç yok",
    "search_error": "arama kullanılamıyor",
    "dir_wait": "rota hesaplanıyor…",
    "dir_none": "rota yok",
    "dir_unavailable": "yol tarifi kullanılamıyor",
    "profile_car": "arabayla",
    "profile_bike": "bisikletle",
    "profile_foot": "yürüyerek",
    "dir_from": "nereden",
    "dir_to": "nereye",
    "dir_mode": "ulaşım",
    "steps_hint": "↑↓ adım · esc kapat",
    "help_title": "tuşlar",
    "help_close": "esc kapat",
    "help_pan": "kaydır",
    "help_zoom_pointer": "imleçte yakınlaştır",
    "help_hover": "tanımla",
    "help_zoom": "yakınlaştır",
    "help_reset": "başa dön",
    "help_view": "sokak · arazi",
    "help_labels": "etiketler ve çizgiler",
    "help_sky": "gün ışığı · bulutlar",
    "help_spin": "küreyi döndür",
    "help_search": "ara",
    "help_directions": "yol tarifi",
    "help_origin": "başlangıcı ayarla",
    "help_profile": "ulaşım şekli",
    "help_keys": "bu liste",
    "help_quit": "çık",
    "poi_airport": "havalimanı",
    "poi_peak": "zirve",
    "poi_station": "istasyon",
    "poi_hospital": "hastane",
    "poi_civic": "kamu · okul",
    "poi_lodging": "konaklama",
    "poi_notable": "müze · gezilecek yer",
    "poi_worship": "ibadet yeri",
    "poi_ferry": "feribot · marina",
    "poi_other": "yer",
    "poi_capital": "başkent",
    "hov_motorway": "otoyol",
    "hov_ramp": "bağlantı yolu",
    "hov_trunk": "devlet yolu",
    "hov_primary": "ana yol",
    "hov_secondary": "ikincil yol",
    "hov_minor": "sokak",
    "hov_service": "servis yolu",
    "hov_path": "patika",
    "hov_rail": "demiryolu",
    "hov_transit": "toplu taşıma hattı",
    "hov_ferry": "feribot",
    "hov_river": "nehir",
    "hov_stream": "dere",
    "hov_runway": "pist",
    "hov_taxiway": "taksi yolu",
    "hov_border": "sınır",
    "hov_coast": "kıyı",
    "hov_water": "su",
    "hov_park": "park",
    "hov_building": "bina",
    "hov_urban": "yerleşim alanı",
}


TIDES = {
    "space_to_now": "şimdiye dönmek için boşluk",
    "waves": "Dalgalar",
    "swell": "Soluğan",
    "tide_model": "Open-Meteo gelgit modeli",
    "no_tides": "{name} için gelgit tahmini yok.",
    "load_failed": "{name} için gelgit bilgisi yüklenemedi. Lütfen tekrar deneyin.",
}


SUNSHINE = {
    "today": "bugün",
    "in_day": "{n} gün sonra",
    "in_days": "{n} gün sonra",
    "day_ago": "{n} gün önce",
    "days_ago": "{n} gün önce",
    "sky_night": "gece",
    "sky_astronomical": "astronomik alacakaranlık",
    "sky_nautical": "denizcilik alacakaranlığı",
    "sky_civil": "sivil alacakaranlık",
    "sky_day": "gündüz",
    "midnight_sun": "gece yarısı güneşi",
    "polar_night": "kutup gecesi",
    "solar_noon": "güneş öğlesi",
    "sunrise": "gün doğumu",
    "sunset": "gün batımı",
}


HOURS = {"night": "gece", "in_time": "{dur} sonra", "koku": "1 koku", "fast": "oruç",
         "midnight": "gece yarısı", "iftar": "iftar"}


MOON = {
    "illuminated": "%{pct} aydınlık",
    "age": "gün {age} / {total}",
    "lunar_age": "Ay yaşı {age} g",
    "up_now": "Şu an gökte",
    "above_horizon": "ufkun {alt}° üzerinde",
    "below_horizon": "Ufkun altında",
    "moonrise": "Ay doğuşu",
    "moonset": "Ay batışı",
    "in_days": "{days} g sonra",
    "begins_at_sunset": "gün batımında başlar",
    "in_time": "{dur} sonra",
    "year_day": "{n}. gün / {total}",
    "light_of_moon": "büyüyen ay",
    "dark_of_moon": "küçülen ay",
    "good_for": "{things} için uygun",
    "hold_off": "{things} için bekleyin",
    "light_good": "toprak üstü bitkileri ekmek, aşılamak, fide dikmek",
    "light_hold": "kök bitkileri",
    "dark_good": "kök bitkileri, budama, yabani ot temizliği",
    "dark_hold": "toprak üstü bitkileri ekmek",
    "solunar_major": "Solunar ana",
    "solunar_minor": "ikincil",
    "spring_equinox": "İlkbahar ekinoksu",
    "summer_solstice": "Yaz gündönümü",
    "autumn_equinox": "Sonbahar ekinoksu",
    "winter_solstice": "Kış gündönümü",
}


SKY = {
    "sun": "Güneş", "moon": "Ay",
    "mercury": "Merkür", "venus": "Venüs", "mars": "Mars",
    "jupiter": "Jüpiter", "saturn": "Satürn", "uranus": "Uranüs",
    "neptune": "Neptün",
    "facing": "{dir} yönüne bakış",
    "field_of_view": "{deg}° genişlik",
    "overhead": "başucunda",
    "planets_none": "gökte gezegen yok",
    "star": "yıldız",
    "search_prompt": "ad veya katalog numarası",
    "search_none": "bu adla bir şey yok",
    # The clock time comes after the verb so it carries no suffix;
    # "02:14'te" would spell the suffix by the hour's last syllable.
    "rises_at": "{name} {dir} yönünden doğar, saat {time}",
    "never_rises": "{name} buradan hiç doğmaz",
    "search_jump": "o ana gitmek için tekrar enter",
    "tradition": "gelenek",
}


SKY_CULTURES = {
    "anutan": "Anuta",
    "belarusian": "Belarus",
    "blackfoot": "Blackfoot",
    "boorong": "Boorong",
    "bugis": "Bugis",
    "chinese": "Çin",
    "chinese-modern": "çağdaş Çin",
    "hawaiian": "Hawaii",
    "indian": "Vedik Hint",
    "japanese": "Japon ay durakları",
    "mandar": "Mandar",
    "maori": "Maori",
    "mongolian": "Moğol",
    "norse": "İskandinav",
    "romanian": "Rumen",
    "ruelle": "Ruelle",
    "sami": "Sami",
    "siberian": "Sibirya",
    "tongan": "Tonga",
    "tukano": "Tukano",
    "snt": "Batı (Sky & Telescope)",
    "rey": "Batı (H.A.Rey)",
}
