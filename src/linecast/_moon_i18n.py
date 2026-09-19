"""Moon command localization strings.

Phase names live in MOON_NAMES_I18N (in _tides_i18n, shared with the tides
chart's moon labels); this module holds the strings specific to the ``moon``
command plus month names for the full/new moon dates.
"""

from linecast._i18n import lang_of, lookup, plural_category
from linecast._tides_i18n import MOON_NAMES_I18N, _moon_name  # noqa: F401 — re-export
from linecast._weather_i18n import DAY_NAMES  # re-export for convenience

_MOON_STRINGS = {
    "en": {
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
    },
    "fr": {
        "illuminated": "{pct} % éclairée",
        "age": "jour {age} sur {total}",
        "lunar_age": "âge lunaire {age} j",
        "up_now": "Levée",
        "above_horizon": "{alt}° au-dessus de l'horizon",
        "below_horizon": "Sous l'horizon",
        "moonrise": "Lever de lune",
        "moonset": "Coucher de lune",
        "in_days": "dans {days} j",
        "begins_at_sunset": "commence au coucher du soleil",
        "in_time": "dans {dur}",
        "year_day": "Jour {n} sur {total}",
        "light_of_moon": "lune croissante",
        "dark_of_moon": "lune décroissante",
        "good_for": "Bon pour {things}",
        "hold_off": "À éviter : {things}",
        "light_good": "semer les cultures aériennes, greffer, repiquer",
        "light_hold": "les légumes-racines",
        "dark_good": "les légumes-racines, tailler, désherber",
        "dark_hold": "semer les cultures aériennes",
        "solunar_major": "Solunaire majeure",
        "solunar_minor": "mineure",
        "spring_equinox": "Équinoxe de printemps",
        "summer_solstice": "Solstice d'été",
        "autumn_equinox": "Équinoxe d'automne",
        "winter_solstice": "Solstice d'hiver",
    },
    "es": {
        "illuminated": "{pct} % iluminada",
        "age": "día {age} de {total}",
        "lunar_age": "edad lunar {age} d",
        "up_now": "Visible ahora",
        "above_horizon": "{alt}° sobre el horizonte",
        "below_horizon": "Bajo el horizonte",
        "moonrise": "Salida de la luna",
        "moonset": "Puesta de la luna",
        "in_days": "en {days} d",
        "begins_at_sunset": "comienza al atardecer",
        "in_time": "en {dur}",
        "year_day": "Día {n} de {total}",
        "light_of_moon": "luna creciente",
        "dark_of_moon": "luna menguante",
        "good_for": "Bueno para {things}",
        "hold_off": "Evitar {things}",
        "light_good": "sembrar cultivos aéreos, injertar, trasplantar",
        "light_hold": "cultivos de raíz",
        "dark_good": "cultivos de raíz, podar, desherbar",
        "dark_hold": "sembrar cultivos aéreos",
        "solunar_major": "Solunar mayor",
        "solunar_minor": "menor",
        "spring_equinox": "Equinoccio de primavera",
        "summer_solstice": "Solsticio de verano",
        "autumn_equinox": "Equinoccio de otoño",
        "winter_solstice": "Solsticio de invierno",
    },
    "de": {
        "illuminated": "{pct} % beleuchtet",
        "age": "Tag {age} von {total}",
        "lunar_age": "Mondalter {age} T",
        "up_now": "Jetzt sichtbar",
        "above_horizon": "{alt}° über dem Horizont",
        "below_horizon": "Unter dem Horizont",
        "moonrise": "Mondaufgang",
        "moonset": "Monduntergang",
        "in_days": "in {days} T",
        "begins_at_sunset": "beginnt bei Sonnenuntergang",
        "in_time": "in {dur}",
        "year_day": "Tag {n} von {total}",
        "light_of_moon": "zunehmender Mond",
        "dark_of_moon": "abnehmender Mond",
        "good_for": "Gut für {things}",
        "hold_off": "Abwarten mit {things}",
        "light_good": "Aussaat oberirdischer Kulturen, Veredeln, Umpflanzen",
        "light_hold": "Wurzelgemüse",
        "dark_good": "Wurzelgemüse, Schneiden, Jäten",
        "dark_hold": "Aussaat oberirdischer Kulturen",
        "solunar_major": "Solunar-Hauptzeit",
        "solunar_minor": "Nebenzeit",
        "spring_equinox": "Frühlingsanfang",
        "summer_solstice": "Sommeranfang",
        "autumn_equinox": "Herbstanfang",
        "winter_solstice": "Winteranfang",
    },
    "it": {
        "illuminated": "{pct}% illuminata",
        "age": "giorno {age} di {total}",
        "lunar_age": "età lunare {age} g",
        "up_now": "Visibile ora",
        "above_horizon": "{alt}° sopra l'orizzonte",
        "below_horizon": "Sotto l'orizzonte",
        "moonrise": "Sorgere della luna",
        "moonset": "Tramonto della luna",
        "in_days": "tra {days} g",
        "begins_at_sunset": "inizia al tramonto",
        "in_time": "tra {dur}",
        "year_day": "Giorno {n} di {total}",
        "light_of_moon": "luna crescente",
        "dark_of_moon": "luna calante",
        "good_for": "Adatto per {things}",
        "hold_off": "Rimandare {things}",
        "light_good": "seminare colture aeree, innestare, trapiantare",
        "light_hold": "ortaggi da radice",
        "dark_good": "ortaggi da radice, potare, diserbare",
        "dark_hold": "seminare colture aeree",
        "solunar_major": "Solunare maggiore",
        "solunar_minor": "minore",
        "spring_equinox": "Equinozio di primavera",
        "summer_solstice": "Solstizio d'estate",
        "autumn_equinox": "Equinozio d'autunno",
        "winter_solstice": "Solstizio d'inverno",
    },
    "pt": {
        "illuminated": "{pct}% iluminada",
        "age": "dia {age} de {total}",
        "lunar_age": "idade lunar {age} d",
        "up_now": "Visível agora",
        "above_horizon": "{alt}° acima do horizonte",
        "below_horizon": "Abaixo do horizonte",
        "moonrise": "Nascer da lua",
        "moonset": "Pôr da lua",
        "in_days": "em {days} d",
        "begins_at_sunset": "começa ao pôr do sol",
        "in_time": "em {dur}",
        "year_day": "Dia {n} de {total}",
        "light_of_moon": "lua crescente",
        "dark_of_moon": "lua minguante",
        "good_for": "Bom para {things}",
        "hold_off": "Adiar {things}",
        "light_good": "semear culturas aéreas, enxertar, transplantar",
        "light_hold": "culturas de raiz",
        "dark_good": "culturas de raiz, podar, mondar",
        "dark_hold": "semear culturas aéreas",
        "solunar_major": "Solunar maior",
        "solunar_minor": "menor",
        "spring_equinox": "Equinócio de primavera",
        "summer_solstice": "Solstício de verão",
        "autumn_equinox": "Equinócio de outono",
        "winter_solstice": "Solstício de inverno",
    },
    "nl": {
        "illuminated": "{pct}% verlicht",
        "age": "dag {age} van {total}",
        "lunar_age": "maanleeftijd {age} d",
        "up_now": "Nu zichtbaar",
        "above_horizon": "{alt}° boven de horizon",
        "below_horizon": "Onder de horizon",
        "moonrise": "Maanopkomst",
        "moonset": "Maanondergang",
        "in_days": "over {days} d",
        "begins_at_sunset": "begint bij zonsondergang",
        "in_time": "over {dur}",
        "year_day": "Dag {n} van {total}",
        "light_of_moon": "wassende maan",
        "dark_of_moon": "afnemende maan",
        "good_for": "Goed voor {things}",
        "hold_off": "Wacht met {things}",
        "light_good": "bovengrondse gewassen zaaien, enten, verplanten",
        "light_hold": "wortelgewassen",
        "dark_good": "wortelgewassen, snoeien, wieden",
        "dark_hold": "bovengrondse gewassen zaaien",
        "solunar_major": "Solunaire hoofdperiode",
        "solunar_minor": "bijperiode",
        "spring_equinox": "Lente-equinox",
        "summer_solstice": "Zomerzonnewende",
        "autumn_equinox": "Herfstequinox",
        "winter_solstice": "Winterzonnewende",
    },
    "pl": {
        "illuminated": "{pct}% oświetlenia",
        "age": "dzień {age} z {total}",
        "lunar_age": "wiek księżyca {age} d",
        "up_now": "Nad horyzontem",
        "above_horizon": "{alt}° nad horyzontem",
        "below_horizon": "Pod horyzontem",
        "moonrise": "Wschód księżyca",
        "moonset": "Zachód księżyca",
        "in_days": "za {days} d",
        "begins_at_sunset": "zaczyna się o zachodzie słońca",
        "in_time": "za {dur}",
        "year_day": "Dzień {n} z {total}",
        "light_of_moon": "Księżyc przybywający",
        "dark_of_moon": "Księżyc ubywający",
        "good_for": "Dobry czas na {things}",
        "hold_off": "Lepiej odłożyć: {things}",
        "light_good": "siew roślin nadziemnych, szczepienie, przesadzanie",
        "light_hold": "rośliny korzeniowe",
        "dark_good": "rośliny korzeniowe, przycinanie, pielenie",
        "dark_hold": "siew roślin nadziemnych",
        "solunar_major": "Solunar główny",
        "solunar_minor": "poboczny",
        "spring_equinox": "Równonoc wiosenna",
        "summer_solstice": "Przesilenie letnie",
        "autumn_equinox": "Równonoc jesienna",
        "winter_solstice": "Przesilenie zimowe",
    },
    "no": {
        "illuminated": "{pct} % belyst",
        "age": "dag {age} av {total}",
        "lunar_age": "månens alder {age} d",
        "up_now": "Oppe nå",
        "above_horizon": "{alt}° over horisonten",
        "below_horizon": "Under horisonten",
        "moonrise": "Måneoppgang",
        "moonset": "Månenedgang",
        "in_days": "om {days} d",
        "begins_at_sunset": "begynner ved solnedgang",
        "in_time": "om {dur}",
        "year_day": "Dag {n} av {total}",
        "light_of_moon": "voksende måne",
        "dark_of_moon": "minkende måne",
        "good_for": "Godt for {things}",
        "hold_off": "Vent med {things}",
        "light_good": "såing av vekster over jorden, poding, omplanting",
        "light_hold": "rotvekster",
        "dark_good": "rotvekster, beskjæring, luking",
        "dark_hold": "såing av vekster over jorden",
        "solunar_major": "Solunar hovedperiode",
        "solunar_minor": "biperiode",
        "spring_equinox": "Vårjevndøgn",
        "summer_solstice": "Sommersolverv",
        "autumn_equinox": "Høstjevndøgn",
        "winter_solstice": "Vintersolverv",
    },
    "sv": {
        "illuminated": "{pct} % belyst",
        "age": "dag {age} av {total}",
        "lunar_age": "månens ålder {age} d",
        "up_now": "Uppe nu",
        "above_horizon": "{alt}° över horisonten",
        "below_horizon": "Under horisonten",
        "moonrise": "Månuppgång",
        "moonset": "Månnedgång",
        "in_days": "om {days} d",
        "begins_at_sunset": "börjar vid solnedgången",
        "in_time": "om {dur}",
        "year_day": "Dag {n} av {total}",
        "light_of_moon": "växande måne",
        "dark_of_moon": "avtagande måne",
        "good_for": "Bra för {things}",
        "hold_off": "Vänta med {things}",
        "light_good": "sådd av ovanjordiska grödor, ympning, omplantering",
        "light_hold": "rotfrukter",
        "dark_good": "rotfrukter, beskärning, rensning",
        "dark_hold": "sådd av ovanjordiska grödor",
        "solunar_major": "Solunar huvudperiod",
        "solunar_minor": "biperiod",
        "spring_equinox": "Vårdagjämning",
        "summer_solstice": "Sommarsolstånd",
        "autumn_equinox": "Höstdagjämning",
        "winter_solstice": "Vintersolstånd",
    },
    "da": {
        "illuminated": "{pct} % belyst",
        "age": "dag {age} af {total}",
        "lunar_age": "månens alder {age} d",
        "up_now": "Oppe nu",
        "above_horizon": "{alt}° over horisonten",
        "below_horizon": "Under horisonten",
        "moonrise": "Måneopgang",
        "moonset": "Månenedgang",
        "in_days": "om {days} d",
        "begins_at_sunset": "begynder ved solnedgang",
        "in_time": "om {dur}",
        "year_day": "Dag {n} af {total}",
        "light_of_moon": "tiltagende måne",
        "dark_of_moon": "aftagende måne",
        "good_for": "Godt for {things}",
        "hold_off": "Vent med {things}",
        "light_good": "såning af afgrøder over jorden, podning, omplantning",
        "light_hold": "rodfrugter",
        "dark_good": "rodfrugter, beskæring, lugning",
        "dark_hold": "såning af afgrøder over jorden",
        "solunar_major": "Solunar hovedperiode",
        "solunar_minor": "biperiode",
        "spring_equinox": "Forårsjævndøgn",
        "summer_solstice": "Sommersolhverv",
        "autumn_equinox": "Efterårsjævndøgn",
        "winter_solstice": "Vintersolhverv",
    },
    "is": {
        "illuminated": "{pct}% upplýst",
        "age": "dagur {age} af {total}",
        "lunar_age": "tunglaldur {age} d",
        "up_now": "Á lofti núna",
        "above_horizon": "{alt}° yfir sjóndeildarhring",
        "below_horizon": "Undir sjóndeildarhring",
        "moonrise": "Tunglris",
        "moonset": "Tunglsetur",
        "in_days": "eftir {days} d",
        "begins_at_sunset": "hefst við sólsetur",
        "in_time": "eftir {dur}",
        "year_day": "Dagur {n} af {total}",
        "light_of_moon": "vaxandi tungl",
        "dark_of_moon": "minnkandi tungl",
        "good_for": "Gott fyrir {things}",
        "hold_off": "Bíddu með {things}",
        "light_good": "sáningu ofanjarðarplantna, ágræðslu, umplöntun",
        "light_hold": "rótargrænmeti",
        "dark_good": "rótargrænmeti, klippingu, illgresishreinsun",
        "dark_hold": "sáningu ofanjarðarplantna",
        "solunar_major": "Solunar aðaltími",
        "solunar_minor": "aukatími",
        "spring_equinox": "Vorjafndægur",
        "summer_solstice": "Sumarsólstöður",
        "autumn_equinox": "Haustjafndægur",
        "winter_solstice": "Vetrarsólstöður",
    },
    "fi": {
        "illuminated": "{pct} % valaistunut",
        "age": "päivä {age} / {total}",
        "lunar_age": "kuun ikä {age} pv",
        "up_now": "Näkyvissä nyt",
        "above_horizon": "{alt}° horisontin yläpuolella",
        "below_horizon": "Horisontin alapuolella",
        "moonrise": "Kuunnousu",
        "moonset": "Kuunlasku",
        "in_days": "{days} pv kuluttua",
        "begins_at_sunset": "alkaa auringonlaskusta",
        "in_time": "{dur} kuluttua",
        "year_day": "Päivä {n} / {total}",
        "light_of_moon": "kasvava kuu",
        "dark_of_moon": "vähenevä kuu",
        "good_for": "Hyvä aika: {things}",
        "hold_off": "Odota vielä: {things}",
        "light_good": "maanpäällisten kasvien kylvö, varttaminen, koulinta",
        "light_hold": "juurikasvit",
        "dark_good": "juurikasvit, leikkaus, kitkeminen",
        "dark_hold": "maanpäällisten kasvien kylvö",
        "solunar_major": "Solunar pääjakso",
        "solunar_minor": "sivujakso",
        "spring_equinox": "Kevätpäiväntasaus",
        "summer_solstice": "Kesäpäivänseisaus",
        "autumn_equinox": "Syyspäiväntasaus",
        "winter_solstice": "Talvipäivänseisaus",
    },
    "ja": {
        "illuminated": "輝面比 {pct}%",
        "age": "月齢 {age} / {total}",
        "lunar_age": "月齢 {age}",
        "up_now": "現在出ています",
        "above_horizon": "高度 {alt}°",
        "below_horizon": "地平線の下",
        "moonrise": "月の出",
        "moonset": "月の入り",
        "in_days": "{days}日後",
        "begins_at_sunset": "日没に始まる",
        "in_time": "{dur}後",
        "year_day": "今年 {n} 日目 / {total} 日",
        "light_of_moon": "満ちゆく月",
        "dark_of_moon": "欠けゆく月",
        "good_for": "{things}に向く",
        "hold_off": "{things}は控える",
        "light_good": "地上作物の播種、接ぎ木、移植",
        "light_hold": "根菜",
        "dark_good": "根菜、剪定、除草",
        "dark_hold": "地上作物の播種",
        "solunar_major": "ソルナー主要",
        "solunar_minor": "副次",
        "spring_equinox": "春分",
        "summer_solstice": "夏至",
        "autumn_equinox": "秋分",
        "winter_solstice": "冬至",
    },
    "ko": {
        "illuminated": "{pct}% 밝음",
        "age": "월령 {age} / {total}",
        "lunar_age": "월령 {age}",
        "up_now": "지금 떠 있음",
        "above_horizon": "고도 {alt}°",
        "below_horizon": "지평선 아래",
        "moonrise": "월출",
        "moonset": "월몰",
        "in_days": "{days}일 후",
        "begins_at_sunset": "일몰에 시작",
        "in_time": "{dur} 후",
        "year_day": "올해 {n}일째 / {total}일",
        "light_of_moon": "차오르는 달",
        "dark_of_moon": "기우는 달",
        "good_for": "{things}에 좋음",
        "hold_off": "{things}은 보류",
        "light_good": "지상 작물 파종, 접목, 이식",
        "light_hold": "뿌리 작물",
        "dark_good": "뿌리 작물, 가지치기, 김매기",
        "dark_hold": "지상 작물 파종",
        "solunar_major": "솔루나 주요",
        "solunar_minor": "보조",
        "spring_equinox": "춘분",
        "summer_solstice": "하지",
        "autumn_equinox": "추분",
        "winter_solstice": "동지",
    },
    "zh": {
        "illuminated": "亮面 {pct}%",
        "age": "月龄 {age} / {total}",
        "lunar_age": "月龄 {age}",
        "up_now": "现在已升起",
        "above_horizon": "高度 {alt}°",
        "below_horizon": "在地平线下",
        "moonrise": "月出",
        "moonset": "月落",
        "in_days": "{days}天后",
        "begins_at_sunset": "日落开始",
        "in_time": "{dur}后",
        "year_day": "今年第 {n} 天 / {total} 天",
        "light_of_moon": "月盈期",
        "dark_of_moon": "月亏期",
        "good_for": "宜{things}",
        "hold_off": "忌{things}",
        "light_good": "播种地上作物、嫁接、移栽",
        "light_hold": "根菜",
        "dark_good": "根菜、修剪、除草",
        "dark_hold": "播种地上作物",
        "solunar_major": "日月主时段",
        "solunar_minor": "次时段",
        "spring_equinox": "春分",
        "summer_solstice": "夏至",
        "autumn_equinox": "秋分",
        "winter_solstice": "冬至",
    },
    "zh-Hant": {
        "illuminated": "亮面 {pct}%",
        "age": "月齡 {age} / {total}",
        "lunar_age": "月齡 {age}",
        "up_now": "現在已升起",
        "above_horizon": "高度 {alt}°",
        "below_horizon": "在地平線下",
        "moonrise": "月出",
        "moonset": "月落",
        "in_days": "{days}天後",
        "begins_at_sunset": "日落開始",
        "in_time": "{dur}後",
        "year_day": "今年第 {n} 天 / {total} 天",
        "light_of_moon": "月盈期",
        "dark_of_moon": "月虧期",
        "good_for": "宜{things}",
        "hold_off": "忌{things}",
        "light_good": "播種地上作物、嫁接、移栽",
        "light_hold": "根菜",
        "dark_good": "根菜、修剪、除草",
        "dark_hold": "播種地上作物",
        "solunar_major": "日月主時段",
        "solunar_minor": "次時段",
        "spring_equinox": "春分",
        "summer_solstice": "夏至",
        "autumn_equinox": "秋分",
        "winter_solstice": "冬至",
    },
    "th": {
        "illuminated": "สว่าง {pct}%",
        "age": "คืนที่ {age} / {total}",
        "lunar_age": "ดวงจันทร์อายุ {age} วัน",
        "up_now": "อยู่บนท้องฟ้า",
        "above_horizon": "{alt}° เหนือขอบฟ้า",
        "below_horizon": "ใต้ขอบฟ้า",
        "moonrise": "ดวงจันทร์ขึ้น",
        "moonset": "ดวงจันทร์ตก",
        "in_days": "อีก {days} วัน",
        "begins_at_sunset": "เริ่มเมื่อพระอาทิตย์ตก",
        "in_time": "อีก {dur}",
        "year_day": "วันที่ {n} จาก {total} ของปี",
        "light_of_moon": "ข้างขึ้น",
        "dark_of_moon": "ข้างแรม",
        "good_for": "เหมาะสำหรับ{things}",
        "hold_off": "งดเว้น{things}",
        "light_good": "หว่านพืชเหนือดิน ต่อกิ่ง ย้ายปลูก",
        "light_hold": "พืชหัว",
        "dark_good": "พืชหัว ตัดแต่งกิ่ง ถอนวัชพืช",
        "dark_hold": "หว่านพืชเหนือดิน",
        "solunar_major": "โซลูนาร์ช่วงหลัก",
        "solunar_minor": "ช่วงรอง",
        "spring_equinox": "วสันตวิษุวัต",
        "summer_solstice": "ครีษมายัน",
        "autumn_equinox": "ศารทวิษุวัต",
        "winter_solstice": "เหมายัน",
    },
    "id": {
        "illuminated": "{pct}% diterangi",
        "age": "hari {age} dari {total}",
        "lunar_age": "umur bulan {age} hr",
        "up_now": "Di atas cakrawala",
        "above_horizon": "{alt}° di atas cakrawala",
        "below_horizon": "Di bawah cakrawala",
        "moonrise": "Bulan terbit",
        "moonset": "Bulan terbenam",
        "in_days": "dalam {days} hr",
        "begins_at_sunset": "mulai saat matahari terbenam",
        "in_time": "dalam {dur}",
        "year_day": "Hari ke-{n} dari {total}",
        "light_of_moon": "bulan membesar",
        "dark_of_moon": "bulan mengecil",
        "good_for": "Baik untuk {things}",
        "hold_off": "Tunda {things}",
        "light_good": "menyemai tanaman di atas tanah, menyambung, memindahkan tanam",
        "light_hold": "tanaman umbi",
        "dark_good": "tanaman umbi, memangkas, menyiangi",
        "dark_hold": "menyemai tanaman di atas tanah",
        "solunar_major": "Solunar utama",
        "solunar_minor": "minor",
        "spring_equinox": "Ekuinoks musim semi",
        "summer_solstice": "Solstis musim panas",
        "autumn_equinox": "Ekuinoks musim gugur",
        "winter_solstice": "Solstis musim dingin",
    },
    "uk": {
        "illuminated": "освітлено {pct}%",
        "age": "день {age} з {total}",
        "lunar_age": "вік Місяця {age} д",
        "up_now": "Над обрієм",
        "above_horizon": "{alt}° над обрієм",
        "below_horizon": "Під обрієм",
        "moonrise": "Схід Місяця",
        "moonset": "Захід Місяця",
        "in_days": "через {days} д",
        "begins_at_sunset": "починається із заходом сонця",
        "in_time": "через {dur}",
        "year_day": "День {n} з {total}",
        "light_of_moon": "Місяць росте",
        "dark_of_moon": "Місяць спадає",
        "good_for": "Сприятливо: {things}",
        "hold_off": "Зачекайте: {things}",
        "light_good": "сівба надземних культур, щеплення, пересаджування",
        "light_hold": "коренеплоди",
        "dark_good": "коренеплоди, обрізання, прополювання",
        "dark_hold": "сівба надземних культур",
        "solunar_major": "Солунар головний",
        "solunar_minor": "другорядний",
        "spring_equinox": "Весняне рівнодення",
        "summer_solstice": "Літнє сонцестояння",
        "autumn_equinox": "Осіннє рівнодення",
        "winter_solstice": "Зимове сонцестояння",
    },
    "vi": {
        "illuminated": "độ sáng {pct}%",
        "age": "ngày {age} trên {total}",
        "lunar_age": "tuổi trăng {age} ngày",
        "up_now": "Đang trên bầu trời",
        "above_horizon": "{alt}° trên chân trời",
        "below_horizon": "Dưới chân trời",
        "moonrise": "Trăng mọc",
        "moonset": "Trăng lặn",
        "in_days": "còn {days} ngày",
        "begins_at_sunset": "bắt đầu lúc mặt trời lặn",
        "in_time": "còn {dur}",
        "year_day": "Ngày {n} trên {total}",
        "light_of_moon": "trăng tròn dần",
        "dark_of_moon": "trăng khuyết dần",
        "good_for": "Tốt cho {things}",
        "hold_off": "Hoãn {things}",
        "light_good": "gieo cây trồng trên mặt đất, ghép cành, trồng lại",
        "light_hold": "cây lấy củ",
        "dark_good": "cây lấy củ, tỉa cành, làm cỏ",
        "dark_hold": "gieo cây trồng trên mặt đất",
        "solunar_major": "Solunar chính",
        "solunar_minor": "phụ",
        "spring_equinox": "Xuân phân",
        "summer_solstice": "Hạ chí",
        "autumn_equinox": "Thu phân",
        "winter_solstice": "Đông chí",
    },
    "eo": {
        "illuminated": "{pct}% lumigita",
        "age": "tago {age} el {total}",
        "lunar_age": "luna aĝo {age} t",
        "up_now": "Nun supre",
        "above_horizon": "{alt}° super la horizonto",
        "below_horizon": "Sub la horizonto",
        "moonrise": "Lunleviĝo",
        "moonset": "Lunsubiro",
        "in_days": "post {days} t",
        "begins_at_sunset": "komenciĝas ĉe sunsubiro",
        "in_time": "post {dur}",
        "year_day": "Tago {n} el {total}",
        "light_of_moon": "kreskanta luno",
        "dark_of_moon": "malkreskanta luno",
        "good_for": "Bona por {things}",
        "hold_off": "Ne nun: {things}",
        "light_good": "semi surterajn kulturojn, grefti, transplanti",
        "light_hold": "radikaj kulturoj",
        "dark_good": "radikaj kulturoj, pritondado, sarkado",
        "dark_hold": "semi surterajn kulturojn",
        "solunar_major": "Solunara ĉefa",
        "solunar_minor": "kroma",
        "spring_equinox": "Printempa ekvinokso",
        "summer_solstice": "Somera solstico",
        "autumn_equinox": "Aŭtuna ekvinokso",
        "winter_solstice": "Vintra solstico",
    },
    "tr": {
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
    },
    "ru": {
        "illuminated": "освещено {pct}%",
        "age": "день {age} из {total}",
        "lunar_age": "возраст Луны {age} д",
        "up_now": "Над горизонтом",
        "above_horizon": "{alt}° над горизонтом",
        "below_horizon": "Под горизонтом",
        "moonrise": "Восход Луны",
        "moonset": "Заход Луны",
        "in_days": "через {days} д",
        "begins_at_sunset": "начинается с заходом солнца",
        "in_time": "через {dur}",
        "year_day": "День {n} из {total}",
        "light_of_moon": "Луна растёт",
        "dark_of_moon": "Луна убывает",
        "good_for": "Благоприятно: {things}",
        "hold_off": "Подождите: {things}",
        "light_good": "посев надземных культур, прививка, пересадка",
        "light_hold": "корнеплоды",
        "dark_good": "корнеплоды, обрезка, прополка",
        "dark_hold": "посев надземных культур",
        "solunar_major": "Солунар главный",
        "solunar_minor": "второстепенный",
        "spring_equinox": "Весеннее равноденствие",
        "summer_solstice": "Летнее солнцестояние",
        "autumn_equinox": "Осеннее равноденствие",
        "winter_solstice": "Зимнее солнцестояние",
    },
    "ro": {
        "illuminated": "{pct}% iluminată",
        "age": "ziua {age} din {total}",
        "lunar_age": "vârsta Lunii {age} zile",
        "up_now": "Pe cer acum",
        "above_horizon": "{alt}° deasupra orizontului",
        "below_horizon": "Sub orizont",
        "moonrise": "Răsăritul Lunii",
        "moonset": "Apusul Lunii",
        # A count of twenty or more takes "de" before its noun: "peste
        # 3 zile", "peste 21 de zile"; one is "peste 1 zi".
        "in_days": "peste {days} zile",
        "in_days_one": "peste {days} zi",
        "in_days_many": "peste {days} de zile",
        "begins_at_sunset": "începe la apus",
        "in_time": "peste {dur}",
        "year_day": "Ziua {n} din {total}",
        "light_of_moon": "Lună în creștere",
        "dark_of_moon": "Lună în descreștere",
        "good_for": "Prielnic: {things}",
        "hold_off": "Amână: {things}",
        "light_good": "semănatul culturilor de suprafață, altoit, transplantat",
        "light_hold": "rădăcinoase",
        "dark_good": "rădăcinoase, tăieri, plivit",
        "dark_hold": "semănatul culturilor de suprafață",
        "solunar_major": "Solunar major",
        "solunar_minor": "minor",
        "spring_equinox": "Echinocțiul de primăvară",
        "summer_solstice": "Solstițiul de vară",
        "autumn_equinox": "Echinocțiul de toamnă",
        "winter_solstice": "Solstițiul de iarnă",
    },
    "cs": {
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
    },
    "sw": {
        "illuminated": "{pct}% imeangazwa",
        "age": "siku ya {age} kati ya {total}",
        "lunar_age": "umri wa mwezi siku {age}",
        "up_now": "Uko juu sasa",
        "above_horizon": "{alt}° juu ya upeo wa macho",
        "below_horizon": "Chini ya upeo wa macho",
        "moonrise": "Mwezi kuchomoza",
        "moonset": "Mwezi kutua",
        "in_days": "baada ya siku {days}",
        "begins_at_sunset": "huanza jua linapotua",
        "in_time": "baada ya {dur}",
        "year_day": "Siku ya {n} kati ya {total}",
        "light_of_moon": "mwezi unaoongezeka",
        "dark_of_moon": "mwezi unaopungua",
        "good_for": "Wakati mzuri wa {things}",
        "hold_off": "Subiri kabla ya {things}",
        "light_good": "kupanda mazao ya juu ya ardhi, kuunganisha miche, kupandikiza",
        "light_hold": "kupanda mazao ya mizizi",
        "dark_good": "kupanda mazao ya mizizi, kupogoa, kupalilia",
        "dark_hold": "kupanda mazao ya juu ya ardhi",
        "solunar_major": "Kipindi kikuu cha jua na mwezi",
        "solunar_minor": "kipindi kidogo",
        "spring_equinox": "Ikwinoksi ya Machi",
        "summer_solstice": "Solstisi ya Juni",
        "autumn_equinox": "Ikwinoksi ya Septemba",
        "winter_solstice": "Solstisi ya Desemba",
    },
    "el": {
        'illuminated': 'φωτισμός {pct}%',
        'age': 'ημέρα {age} από {total}',
        'lunar_age': 'ηλικία Σελήνης: {age} ημ.',
        'up_now': 'Πάνω από τον ορίζοντα',
        'above_horizon': '{alt}° πάνω από τον ορίζοντα',
        'below_horizon': 'Κάτω από τον ορίζοντα',
        'moonrise': 'Ανατολή Σελήνης',
        'moonset': 'Δύση Σελήνης',
        'in_days': 'σε {days} ημέρες',
        'in_days_one': 'σε {days} ημέρα',
        'begins_at_sunset': 'αρχίζει με τη δύση του ήλιου',
        'in_time': 'σε {dur}',
        'year_day': 'Ημέρα {n} από {total}',
        'light_of_moon': 'γέμισμα του φεγγαριού',
        'dark_of_moon': 'χάση του φεγγαριού',
        'good_for': 'Ευνοούνται: {things}',
        'hold_off': 'Αναβάλετε: {things}',
        'light_good': 'σπορά υπέργειων καλλιεργειών, εμβολιασμοί, μεταφυτεύσεις',
        'light_hold': 'καλλιέργειες ριζών',
        'dark_good': 'καλλιέργειες ριζών, κλάδεμα, βοτάνισμα',
        'dark_hold': 'σπορά υπέργειων καλλιεργειών',
        'solunar_major': 'Κύρια ηλιοσεληνιακή περίοδος',
        'solunar_minor': 'δευτερεύουσα',
        'spring_equinox': 'Εαρινή ισημερία',
        'summer_solstice': 'Θερινό ηλιοστάσιο',
        'autumn_equinox': 'Φθινοπωρινή ισημερία',
        'winter_solstice': 'Χειμερινό ηλιοστάσιο',
    },
}


# Abbreviated month names, January..December. CJK and Finnish dates are
# formatted numerically via DATE_MD below, so those entries are unused.
MONTHS_I18N = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "fr": ["janv", "févr", "mars", "avr", "mai", "juin",
            "juil", "août", "sept", "oct", "nov", "déc"],
    "es": ["ene", "feb", "mar", "abr", "may", "jun",
            "jul", "ago", "sep", "oct", "nov", "dic"],
    "de": ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
            "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"],
    "it": ["gen", "feb", "mar", "apr", "mag", "giu",
            "lug", "ago", "set", "ott", "nov", "dic"],
    "pt": ["jan", "fev", "mar", "abr", "mai", "jun",
            "jul", "ago", "set", "out", "nov", "dez"],
    "nl": ["jan", "feb", "mrt", "apr", "mei", "jun",
            "jul", "aug", "sep", "okt", "nov", "dec"],
    "pl": ["sty", "lut", "mar", "kwi", "maj", "cze",
            "lip", "sie", "wrz", "paź", "lis", "gru"],
    "no": ["jan", "feb", "mar", "apr", "mai", "jun",
            "jul", "aug", "sep", "okt", "nov", "des"],
    "sv": ["jan", "feb", "mar", "apr", "maj", "jun",
            "jul", "aug", "sep", "okt", "nov", "dec"],
    "da": ["jan", "feb", "mar", "apr", "maj", "jun",
            "jul", "aug", "sep", "okt", "nov", "dec"],
    "is": ["jan", "feb", "mar", "apr", "maí", "jún",
            "júl", "ágú", "sep", "okt", "nóv", "des"],
    "th": ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
            "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."],
    "id": ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
            "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
    "uk": ["січ", "лют", "бер", "кві", "тра", "чер",
           "лип", "сер", "вер", "жов", "лис", "гру"],
    # Vietnamese months are numbered; CLDR's short form.
    "vi": [f"thg {m}" for m in range(1, 13)],
    "eo": ["jan", "feb", "mar", "apr", "maj", "jun",
           "jul", "aŭg", "sep", "okt", "nov", "dec"],
    "tr": ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
           "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"],
    "ru": ["янв", "фев", "мар", "апр", "май", "июн",
           "июл", "авг", "сен", "окт", "ноя", "дек"],
    "ro": ["ian", "feb", "mar", "apr", "mai", "iun",
           "iul", "aug", "sep", "oct", "noi", "dec"],
    "cs": ["led", "úno", "bře", "dub", "kvě", "čvn",
           "čvc", "srp", "zář", "říj", "lis", "pro"],
    "sw": ["Jan", "Feb", "Mac", "Apr", "Mei", "Jun", "Jul", "Ago", "Sep", "Okt", "Nov", "Des"],
    "el": ['Ιαν', 'Φεβ', 'Μαρ', 'Απρ', 'Μαΐ', 'Ιουν', 'Ιουλ', 'Αυγ', 'Σεπ', 'Οκτ', 'Νοε', 'Δεκ'],
}

# Date order/format per language: {month} = abbreviated name from
# MONTHS_I18N, {mnum} = month number, {day} = day of month.
_DATE_MD = {
    "en": "{month} {day}",
    "de": "{day}. {month}",
    "cs": "{day}. {month}",
    "fi": "{day}.{mnum}.",
    "ja": "{mnum}月{day}日",
    "zh": "{mnum}月{day}日",
    "zh-Hant": "{mnum}月{day}日",
    "ko": "{mnum}월 {day}일",
}
_DATE_MD_DEFAULT = "{day} {month}"


def _ms(key, runtime, **kwargs):
    """Look up a moon-specific localized string. A count of days takes
    the form the language gives that count where the table has one
    (Romanian's "peste 1 zi", "peste 21 de zile")."""
    lang = lang_of(runtime)
    if key == "in_days" and "days" in kwargs:
        variant = f"in_days_{plural_category(lang, float(kwargs['days']))}"
        if variant in _MOON_STRINGS.get(lang, {}):
            key = variant
    return lookup(_MOON_STRINGS, key, lang, **kwargs)


# Season names for the four events (March equinox, June solstice,
# September equinox, December solstice), by hemisphere.  East Asian
# solar terms (春分, 夏至, …) name the event itself, not the local
# season — Vietnamese Xuân phân and Hạ chí are the same terms — and
# Thai's Sanskrit terms (วสันตวิษุวัต, …) likewise, so those languages
# keep the northern mapping everywhere. Swahili names the months of
# the events, so its labels also stay the same in either hemisphere.
_SEASON_KEYS_NORTH = ("spring_equinox", "summer_solstice",
                      "autumn_equinox", "winter_solstice")
_SEASON_KEYS_SOUTH = ("autumn_equinox", "winter_solstice",
                      "spring_equinox", "summer_solstice")
_SEASON_ABSOLUTE_LANGS = frozenset({"ja", "ko", "zh", "zh-Hant", "vi", "th", "sw"})


def _season_label(event, lat, runtime):
    """Localized name for a season event index, seen from latitude *lat*."""
    south = lat is not None and lat < 0
    if south and lang_of(runtime) not in _SEASON_ABSOLUTE_LANGS:
        return _ms(_SEASON_KEYS_SOUTH[event], runtime)
    return _ms(_SEASON_KEYS_NORTH[event], runtime)


def _fmt_month_day(dt, runtime):
    """Format a month + day date in the runtime language's convention."""
    lang = lang_of(runtime)
    fmt = _DATE_MD.get(lang, _DATE_MD_DEFAULT)
    months = MONTHS_I18N.get(lang, MONTHS_I18N["en"])
    return fmt.format(month=months[dt.month - 1], mnum=dt.month, day=dt.day)


def _day_abbrev(dt, runtime):
    """Localized three-letter-ish weekday abbreviation."""
    return DAY_NAMES.get(lang_of(runtime), DAY_NAMES["en"])[dt.weekday()]


# ---------------------------------------------------------------------------
# The lunisolar calendar's names (see _calendars/lunisolar.py for the calendar
# itself). Each calendar reads in its own script for its own language;
# every other UI language gets the customary English renderings, the
# same fallback the string tables use.
# ---------------------------------------------------------------------------

# Solar terms in longitude order, index 0 at the March equinox — the
# indexing current_term() and next_term() use. The terms are common to
# all four calendars; only the writing differs.
SOLAR_TERMS_I18N = {
    "en": ["Spring Equinox", "Clear and Bright", "Grain Rain",
           "Start of Summer", "Grain Buds", "Grain in Ear",
           "Summer Solstice", "Minor Heat", "Major Heat",
           "Start of Autumn", "End of Heat", "White Dew",
           "Autumn Equinox", "Cold Dew", "Frost's Descent",
           "Start of Winter", "Minor Snow", "Major Snow",
           "Winter Solstice", "Minor Cold", "Major Cold",
           "Start of Spring", "Rain Water", "Awakening of Insects"],
    "zh": ["春分", "清明", "谷雨", "立夏", "小满", "芒种",
           "夏至", "小暑", "大暑", "立秋", "处暑", "白露",
           "秋分", "寒露", "霜降", "立冬", "小雪", "大雪",
           "冬至", "小寒", "大寒", "立春", "雨水", "惊蛰"],
    "zh-Hant": ["春分", "清明", "穀雨", "立夏", "小滿", "芒種",
                "夏至", "小暑", "大暑", "立秋", "處暑", "白露",
                "秋分", "寒露", "霜降", "立冬", "小雪", "大雪",
                "冬至", "小寒", "大寒", "立春", "雨水", "驚蟄"],
    "ja": ["春分", "清明", "穀雨", "立夏", "小満", "芒種",
           "夏至", "小暑", "大暑", "立秋", "処暑", "白露",
           "秋分", "寒露", "霜降", "立冬", "小雪", "大雪",
           "冬至", "小寒", "大寒", "立春", "雨水", "啓蟄"],
    "ko": ["춘분", "청명", "곡우", "입하", "소만", "망종",
           "하지", "소서", "대서", "입추", "처서", "백로",
           "추분", "한로", "상강", "입동", "소설", "대설",
           "동지", "소한", "대한", "입춘", "우수", "경칩"],
    "vi": ["Xuân phân", "Thanh minh", "Cốc vũ", "Lập hạ", "Tiểu mãn", "Mang chủng",
           "Hạ chí", "Tiểu thử", "Đại thử", "Lập thu", "Xử thử", "Bạch lộ",
           "Thu phân", "Hàn lộ", "Sương giáng", "Lập đông", "Tiểu tuyết", "Đại tuyết",
           "Đông chí", "Tiểu hàn", "Đại hàn", "Lập xuân", "Vũ thủy", "Kinh trập"],
}

# Festivals dated by the lunar calendar, (month, day) → {lang: name}, per
# calendar: the name in the calendar's own language (Chinese in both its
# scripts) and the customary English one. Japan moved its festivals to
# Gregorian dates in 1873; the two moon-viewing nights are what remains
# on the old calendar. Vietnam's are the public holidays and the days
# every household keeps: the Hùng Kings' day is a holiday by law, and the
# Kitchen Gods' departure a week before Tết opens the new year's rites.
_FESTIVALS = {
    "chinese": {
        (1, 1): {"zh": "春节", "zh-Hant": "春節", "en": "Chinese New Year"},
        (1, 15): {"zh": "元宵节", "zh-Hant": "元宵節", "en": "Lantern Festival"},
        (5, 5): {"zh": "端午节", "zh-Hant": "端午節", "en": "Dragon Boat Festival"},
        (7, 7): {"zh": "七夕", "zh-Hant": "七夕", "en": "Qixi"},
        (8, 15): {"zh": "中秋节", "zh-Hant": "中秋節", "en": "Mid-Autumn Festival"},
        (9, 9): {"zh": "重阳节", "zh-Hant": "重陽節", "en": "Double Ninth"},
    },
    "japanese": {
        (8, 15): {"ja": "十五夜", "en": "Tsukimi"},
        (9, 13): {"ja": "十三夜", "en": "Jūsan'ya"},
    },
    "korean": {
        (1, 1): {"ko": "설날", "en": "Seollal"},
        (1, 15): {"ko": "정월대보름", "en": "Daeboreum"},
        (5, 5): {"ko": "단오", "en": "Dano"},
        (8, 15): {"ko": "추석", "en": "Chuseok"},
    },
    "vietnamese": {
        (1, 1): {"vi": "Tết Nguyên Đán", "en": "Tết"},
        (1, 15): {"vi": "Rằm tháng Giêng", "en": "Tết Nguyên Tiêu"},
        (3, 10): {"vi": "Giỗ Tổ Hùng Vương", "en": "Hùng Kings' Day"},
        (5, 5): {"vi": "Tết Đoan Ngọ", "en": "Tết Đoan Ngọ"},
        (7, 15): {"vi": "Lễ Vu Lan", "en": "Vu Lan"},
        (8, 15): {"vi": "Tết Trung Thu", "en": "Mid-Autumn Festival"},
        (12, 23): {"vi": "Ông Táo về trời", "en": "Kitchen Gods' Day"},
    },
}


def festival_table(calendar, lang):
    """(month, day) → name for a calendar's festivals, in *lang* where
    that is the calendar's own language, else the customary English."""
    return {md: names.get(lang, names["en"])
            for md, names in _FESTIVALS[calendar].items()}

# Chinese months and days have names, not numbers: the eleventh and
# twelfth months are 冬月 and 腊月, the first ten days take 初, the
# twenties 廿. The traditional script writes 臘月 and 閏 for a leap month.
_ZH_MONTHS = ["正月", "二月", "三月", "四月", "五月", "六月",
              "七月", "八月", "九月", "十月", "冬月", "腊月"]
_ZH_MONTHS_HANT = [*_ZH_MONTHS[:11], "臘月"]
_ZH_DIGITS = "一二三四五六七八九十"


def zh_month_label(month, leap, lang):
    """The Chinese month's name, 正月, 闰六月, 臘月, in either script."""
    if lang == "zh-Hant":
        return ("閏" if leap else "") + _ZH_MONTHS_HANT[month - 1]
    return ("闰" if leap else "") + _ZH_MONTHS[month - 1]


def _zh_day_name(day):
    if day <= 10:
        return "初" + _ZH_DIGITS[day - 1]
    if day < 20:
        return "十" + _ZH_DIGITS[day - 11]
    if day == 20:
        return "二十"
    if day < 30:
        return "廿" + _ZH_DIGITS[day - 21]
    return "三十"


# Vietnamese months are numbered but for the first and the last, tháng
# Giêng and tháng Chạp; a leap month takes nhuận after its number. The
# first ten days are mùng, the fifteenth is rằm, the full-moon day.
_VI_MONTHS = {1: "Giêng", 12: "Chạp"}


def vi_month_label(month, leap, short=False):
    """tháng Giêng, tháng 8, tháng 6 nhuận, tháng Chạp — or, for the
    grid's cells, the printed calendars' thg 8."""
    name = _VI_MONTHS.get(month, str(month))
    word = "thg" if short and name.isdigit() else "tháng"
    label = name if short and not name.isdigit() else f"{word} {name}"
    return f"{label} nhuận" if leap else label


def lunar_date_label(month, day, leap, lang):
    """The lunar date as its own calendar writes it, English otherwise."""
    if lang == "vi":
        if day <= 10:
            day_name = f"mùng {day}"
        elif day == 15:
            day_name = "rằm"
        else:
            day_name = f"ngày {day}"
        return f"{day_name} {vi_month_label(month, leap)} âm lịch"
    if lang == "zh":
        return f"农历{zh_month_label(month, leap, lang)}{_zh_day_name(day)}"
    if lang == "zh-Hant":
        return f"農曆{zh_month_label(month, leap, lang)}{_zh_day_name(day)}"
    if lang == "ja":
        leap_mark = "閏" if leap else ""
        return f"旧暦{leap_mark}{month}月{day}日"
    if lang == "ko":
        leap_mark = "윤" if leap else ""
        return f"음력 {leap_mark}{month}월 {day}일"
    leap_mark = "leap " if leap else ""
    return f"{leap_mark}month {month} day {day}"


def term_label(index, lang):
    """The name of solar term *index* (0 = March equinox)."""
    return SOLAR_TERMS_I18N.get(lang, SOLAR_TERMS_I18N["en"])[index]


# Japan names the nights, not just the phases: after the full moon the
# names narrate the lengthening wait for moonrise — stand and wait,
# sit and wait, lie down, wait past midnight. The named nights are the
# traditional ones; the days between take the plain counted form.
_JA_NIGHT_NAMES = (
    "新月", "二日月", "三日月", "四日月", "五日月",
    "六日月", "七日月", "八日月", "九日月", "十日夜",
    "十一日月", "十二日月", "十三夜", "小望月", "十五夜",
    "十六夜", "立待月", "居待月", "寝待月", "更待月",
    "二十一日月", "二十二日月", "二十三夜", "二十四日月", "二十五日月",
    "二十六夜", "二十七日月", "二十八日月", "二十九日月", "三十日月",
)


def ja_night_name(day):
    """The Japanese name of the old calendar's night *day* (1-30)."""
    return _JA_NIGHT_NAMES[day - 1]


# ---------------------------------------------------------------------------
# The Thai calendar's names (see _calendars/thai_lunar.py for the calendar
# itself). Thai lunar dates are traditionally printed in Thai numerals
# — ขึ้น ๘ ค่ำ เดือน ๓ — so the native labels keep them; the rest of
# the UI stays with Arabic digits, as modern Thai print does.
# ---------------------------------------------------------------------------

_TH_DIGITS = "๐๑๒๓๔๕๖๗๘๙"


def _th_num(n):
    return "".join(_TH_DIGITS[ord(c) - 48] for c in str(n))


def thai_month_label(month, doubled, lang):
    """เดือนอ้าย, เดือนยี่, เดือน ๓ … เดือน ๘๘ — the months as the
    printed calendars name them: the first two by their archaic names,
    the doubled eighth by its doubled numeral."""
    if lang == "th":
        if doubled:
            return "เดือน ๘๘"
        if month == 1:
            return "เดือนอ้าย"
        if month == 2:
            return "เดือนยี่"
        return f"เดือน {_th_num(month)}"
    return f"month {'8/8' if doubled else month}"


def thai_lunar_label(month, day, doubled, lang):
    """The Thai lunar date as the printed calendars write it."""
    if lang == "th":
        phase, d = ("ขึ้น", day) if day <= 15 else ("แรม", day - 15)
        return f"{phase} {_th_num(d)} ค่ำ {thai_month_label(month, doubled, lang)}"
    phase, d = ("waxing", day) if day <= 15 else ("waning", day - 15)
    return f"{thai_month_label(month, doubled, lang)} · {phase} {d}"


# The twelve-animal cycle, indexed as year_animal_index counts it
# (0 = ชวด, the rat).
_TH_ANIMALS = ("ชวด", "ฉลู", "ขาล", "เถาะ", "มะโรง", "มะเส็ง",
               "มะเมีย", "มะแม", "วอก", "ระกา", "จอ", "กุน")
_TH_ANIMALS_EN = ("Rat", "Ox", "Tiger", "Rabbit", "Dragon", "Snake",
                  "Horse", "Goat", "Monkey", "Rooster", "Dog", "Pig")


def thai_year_label(animal_index, lang):
    """ปีมะเมีย — the lunar year named by its animal."""
    if lang == "th":
        return "ปี" + _TH_ANIMALS[animal_index]
    return f"Year of the {_TH_ANIMALS_EN[animal_index]}"


def wan_phra_label(today, lang):
    """The Buddhist holy day, named — today's, or the coming one's."""
    if lang == "th":
        return "วันนี้วันพระ" if today else "วันพระ"
    return "Wan Phra today" if today else "Wan Phra"


# Festival names by the keys thai_lunar's next_thai_festival returns,
# (native, customary English).
_TH_FESTIVALS = {
    "makha": ("มาฆบูชา", "Makha Bucha"),
    "visakha": ("วิสาขบูชา", "Visakha Bucha"),
    "asalha": ("อาสาฬหบูชา", "Asalha Bucha"),
    "khao_phansa": ("เข้าพรรษา", "Khao Phansa"),
    "ok_phansa": ("ออกพรรษา", "Ok Phansa"),
    "loy_krathong": ("ลอยกระทง", "Loy Krathong"),
    "songkran": ("สงกรานต์", "Songkran"),
}


def thai_festival_name(key, lang):
    native, english = _TH_FESTIVALS[key]
    return native if lang == "th" else english


# Hawaiʻi names the nights too — the pō mahina, as the WPRFMC's annual
# Kaulana Mahina prints them (after Clarice Taylor's Hawaiian Almanac,
# Oʻahu). Proper nouns with no customary English renderings, so every
# UI language reads them in Hawaiian. Three ten-night anahulu: the four
# waxing ʻOle nights, then three waning ones, keep the count at thirty.
_PO_MAHINA = (
    "Hilo", "Hoaka", "Kūkahi", "Kūlua", "Kūkolu",
    "Kūpau", "ʻOlekūkahi", "ʻOlekūlua", "ʻOlekūkolu", "ʻOlepau",
    "Huna", "Mōhalu", "Hua", "Akua", "Hoku",
    "Māhealani", "Kulu", "Lāʻaukūkahi", "Lāʻaukūlua", "Lāʻaupau",
    "ʻOlekūkahi", "ʻOlekūlua", "ʻOlepau", "Kāloakūkahi", "Kāloakūlua",
    "Kāloapau", "Kāne", "Lono", "Mauli", "Muku",
)

_ANAHULU = ("hoʻonui", "poepoe", "hōʻemi")


# American Samoa names its nights too — the masina, as the Council's
# annual American Samoa lunar calendar prints them, the same thirty in
# every edition since 2021. Two nights carry a second name on the
# page, the first and the full moon, written here as printed.
_MASINA = (
    "Masina Fou/Faatoavaaia", "Masina Tofilofilo", "Masina Tolu",
    "Masina Faalao", "Masina Salefuga", "Masina Tulalupe",
    "Masina Motuega", "Masina Aufasa", "Masina Matuatua",
    "Masina Loloatai",
    "Masina Malupeaua", "Masina Mātofitofi", "Masina Aiaina",
    "Masina Punifaga", "Masina Atoa/Atoa Liʻo le Masina",
    "Masina Leʻaleʻa", "Masina Feetetele", "Masina Ataatatai",
    "Masina Fagaeleele", "Masina Sulutele",
    "Masina Nauna", "Masina Usunoa", "Masina Motusaga",
    "Masina Tatelega", "Masina Faasagafulu", "Masina Tāfaleu",
    "Masina Fataleu", "Masina Mitiloa", "Masina Fanoloa", "Masina Maunā",
)

# The CHamoru nights — the pulan — as the Council's Guam calendar
# prints them, and as its CNMI calendar has printed them since 2025.
# Pulan Gualåffon, the sixteenth, is the full moon.
_PULAN = (
    "Sinahen Håcha", "Sinahen Hugua", "Sinahen Tulu", "Sumahi I Pilan",
    "Sinahen Lima", "Sinahen Gunum", "Sinahen Fiti", "Kuåtto",
    "Kuåtto Kosiente", "E’egeng",
    "Dengnga", "Luma’annok", "Gumofatanon", "Pånglao Tunas/Echong",
    "Atahguen Atdao", "Pulan Gualåffon", "Mumalilingu Empe’",
    "Ketai’ Empe’", "Sumenhomhom", "Kuåtto Mangguånte",
    "Humunaohuyong Pulan", "Humomhom", "Tunas Talo’", "Hihot Talo’",
    "Halomsahguan", "Sinahen Ulu", "Finaloffan Puti’on", "Dalalai Pulan",
    "Kumaninifes", "Sinahi",
)

# The Refaluwasch (Carolinian) names the CNMI calendar sets beside the
# CHamoru ones, keyed by position in the thirty: eleven nights, the
# same eleven in the 2025 and 2026 editions. The 2022–2024 editions
# printed a Refaluwasch name for every night; the Council trimmed the
# list, and these are the names it kept.
_REFALUWASCH = {
    1: "Sighauru", 2: "Eling", 3: "Meseling", 9: "Eschúw",
    14: "Emmasch", 15: "Úúr", 16: "Letiw", 17: "Ghiney", 18: "Ara",
    21: "Arosan Efnágh", 27: "Arofú",
}

_PACIFIC_NIGHTS = {
    "hawaiian": _PO_MAHINA, "samoan": _MASINA,
    "chamorro": _PULAN, "refaluwasch": _PULAN,
}


def _night_index(night, nights):
    """Where *night* of a month of *nights* (29 or 30) sits in the thirty.

    A 29-night month drops the twenty-ninth name, never the last — the
    convention of every published 29-night month in all three
    calendars: Mauli goes and Muku closes, Masina Fanoloa goes and
    Masina Maunā closes, Kumaninifes goes and Sinahi closes.
    """
    if night >= nights:
        return 29                            # the last name closes the month
    if night == nights - 1 and nights >= 30:
        return 28                            # the twenty-ninth keeps its place
    return min(night, 28) - 1


def pacific_night_name(cal, night, nights):
    """The name of *night* in a month of *nights*, in *cal*'s tradition."""
    return _PACIFIC_NIGHTS[cal][_night_index(night, nights)]


def po_mahina_name(night, nights):
    """The Hawaiian name of *night* in a month of *nights* (29 or 30)."""
    return pacific_night_name("hawaiian", night, nights)


def refaluwasch_name(night, nights):
    """The Refaluwasch name of *night*, or None on a night without one."""
    return _REFALUWASCH.get(_night_index(night, nights) + 1)


def pacific_night_label(cal, night, nights):
    """The headline for a night: its name, with the Refaluwasch beside
    the CHamoru where the CNMI calendar prints one."""
    name = pacific_night_name(cal, night, nights)
    if cal == "refaluwasch":
        other = refaluwasch_name(night, nights)
        if other:
            return f"{name} · {other}"
    return name


def anahulu_name(night):
    """The anahulu (ten-night span) that *night* falls in."""
    return _ANAHULU[min((night - 1) // 10, 2)]


# ---------------------------------------------------------------------------
# The Islamic calendar's names (see _calendars/hijri.py for the calendar itself).
# Arabic is not a UI language, so the months are transliterated for
# every reader; Indonesian, the one UI language of a Muslim-majority
# country, gets the spellings its dictionary standardizes.
# ---------------------------------------------------------------------------

_HIJRI_MONTHS = {
    "en": ("Muharram", "Safar", "Rabiʻ al-Awwal", "Rabiʻ al-Thani",
           "Jumada al-Ula", "Jumada al-Thani", "Rajab", "Shaʻban",
           "Ramadan", "Shawwal", "Dhu al-Qaʻdah", "Dhu al-Hijjah"),
    "id": ("Muharam", "Safar", "Rabiulawal", "Rabiulakhir",
           "Jumadilawal", "Jumadilakhir", "Rajab", "Syakban",
           "Ramadan", "Syawal", "Zulkaidah", "Zulhijah"),
}

# Observance names by the keys hijri's next_observance returns.
_HIJRI_OBSERVANCES = {
    "new_year": ("Islamic New Year", "Tahun Baru Islam"),
    "ashura": ("Ashura", "Asyura"),
    "mawlid": ("Mawlid", "Maulid Nabi"),
    "ramadan": ("Ramadan begins", "Awal Ramadan"),
    "qadr": ("Laylat al-Qadr", "Lailatulqadar"),
    "eid_fitr": ("Eid al-Fitr", "Idulfitri"),
    "arafah": ("Day of Arafah", "Hari Arafah"),
    "eid_adha": ("Eid al-Adha", "Iduladha"),
}


def hijri_lang(lang):
    """The language the Islamic calendar's names are written in."""
    return "id" if lang == "id" else "en"


def hijri_month_name(month, lang):
    return _HIJRI_MONTHS[hijri_lang(lang)][month - 1]


def hijri_date_label(year, month, day, lang):
    """23 Ramadan 1447 AH — the Hijri date as it is customarily written."""
    era = "H" if hijri_lang(lang) == "id" else "AH"
    return f"{day} {hijri_month_name(month, lang)} {year} {era}"


def hijri_observance_name(key, lang):
    english, indonesian = _HIJRI_OBSERVANCES[key]
    return indonesian if hijri_lang(lang) == "id" else english


# ---------------------------------------------------------------------------
# The Hebrew calendar's names (see _calendars/hebrew.py for the calendar itself).
# Hebrew is not a UI language and terminals lay its script out
# unreliably, so the months and holidays are transliterated, one
# spelling for every reader: Tishrei, Cheshvan, Pesach.
# ---------------------------------------------------------------------------

_HEBREW_MONTHS = ("Nisan", "Iyar", "Sivan", "Tammuz", "Av", "Elul",
                  "Tishrei", "Cheshvan", "Kislev", "Tevet", "Shevat",
                  "Adar", "Adar II")
_HEBREW_MONTHS_HE = ("ניסן", "אייר", "סיון", "תמוז", "אב", "אלול",
                     "תשרי", "חשון", "כסלו", "טבת", "שבט",
                     "אדר", "אדר ב׳")

# The letter numerals: units, tens, and hundreds each have a letter,
# read by adding them up; 15 and 16 are written ט״ו and ט״ז rather
# than with the letters of the divine name.
_GEMATRIA = ((400, "ת"), (300, "ש"), (200, "ר"), (100, "ק"), (90, "צ"),
             (80, "פ"), (70, "ע"), (60, "ס"), (50, "נ"), (40, "מ"),
             (30, "ל"), (20, "כ"), (10, "י"), (9, "ט"), (8, "ח"),
             (7, "ז"), (6, "ו"), (5, "ה"), (4, "ד"), (3, "ג"),
             (2, "ב"), (1, "א"))
_GERESH, _GERSHAYIM = "\u05f3", "\u05f4"

# Holiday names by the keys hebrew's next_holiday returns.
_HEBREW_HOLIDAYS = {
    "rosh_hashanah": "Rosh Hashanah",
    "yom_kippur": "Yom Kippur",
    "sukkot": "Sukkot",
    "shemini_atzeret": "Shemini Atzeret",
    "simchat_torah": "Simchat Torah",
    # One day in Israel, so a printed calendar names it with both.
    "shemini_atzeret_simchat_torah": "Shemini Atzeret / Simchat Torah",
    "hanukkah": "Hanukkah",
    "tu_bishvat": "Tu BiShvat",
    "purim": "Purim",
    "pesach": "Pesach",
    "shavuot": "Shavuot",
    "tisha_bav": "Tisha B'Av",
}


def hebrew_month_name(year, month):
    """The month's name; the twelfth is Adar I in a year with two Adars."""
    from linecast._calendars.hebrew import is_leap_year
    if month == 12 and is_leap_year(year):
        return "Adar I"
    return _HEBREW_MONTHS[month - 1]


def hebrew_date_label(year, month, day):
    """23 Tishrei 5787 — the Hebrew date as it is customarily written."""
    return f"{day} {hebrew_month_name(year, month)} {year}"


def hebrew_holiday_name(key):
    return _HEBREW_HOLIDAYS[key]


def hebrew_numeral(n):
    """*n* in Hebrew letters: כ׳ for 20, כ״ג for 23, ט״ו for 15."""
    letters = ""
    while n:
        for value, letter in _GEMATRIA:
            if value <= n:
                letters += letter
                n -= value
                break
    letters = letters.replace("יה", "טו").replace("יו", "טז")
    if len(letters) == 1:
        return letters + _GERESH
    return letters[:-1] + _GERSHAYIM + letters[-1]


def hebrew_year_numeral(year):
    """The year as it is written, without its thousands: תשפ״ו for 5786.

    A round thousand has nothing left to write, so the thousands
    stand alone: ו׳ for 6000.
    """
    rest = year % 1000
    return hebrew_numeral(rest if rest else year // 1000)


def hebrew_date_hebrew(year, month, day):
    """כ״ג תשרי תשפ״ז — the date in Hebrew letters, for --json."""
    from linecast._calendars.hebrew import is_leap_year
    name = _HEBREW_MONTHS_HE[month - 1]
    if month == 12 and is_leap_year(year):
        name = "אדר א׳"
    return f"{hebrew_numeral(day)} {name} {hebrew_year_numeral(year)}"


def rosh_chodesh_label(year, month):
    return f"Rosh Chodesh {hebrew_month_name(year, month)}"
