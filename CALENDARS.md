# The moon's calendars

`linecast moon` can read the date by a traditional calendar and show it beside the phase. This page says what each calendar shows, how linecast computes it, and what it was checked against.

## Choosing one

In Chinese, Japanese, Korean, and Thai the calendar follows the language. Any language can ask for any calendar: `linecast moon --calendar hebrew` for one run, or `linecast calendar hebrew` to save it for every run. `linecast calendar none` turns it off, and `linecast calendar auto` goes back to following the language. The names are `chinese`, `japanese`, `korean`, `thai`, `hawaiian`, `samoan`, `chamorro`, `refaluwasch`, `islamic`, `hebrew`, and `almanac`.

Whichever calendar is active, the month grid (`v` in live mode, or `linecast moon --grid`) carries its reading too: the calendar's months in the title, each day's date in the corner of its cell, the month starts and observances marked, and the full date in the hover chip. Click a day and the disc view opens on it.

## Chinese, Japanese, and Korean

The lunar date sits beside the phase name, with the solar term in progress and a countdown to the next festival: 中秋节, 추석, or 十五夜. In Japanese the night is also called by its own name: 十六夜, 居待月, 更待月. When the app is in another language the same reading is written with the customary English names ("End of Heat · White Dew Sep 7", "Mid-Autumn Festival Sep 25").

The months, leap months, and solar terms are computed from the ephemeris at each calendar's own meridian. Nothing is looked up in a table.

## Thai

The Thai lunar calendar, ปฏิทินจันทรคติไทย, gives the waxing or waning day beside the phase in Thai numerals, as the printed calendars have it (แรม ๔ ค่ำ เดือน ๙), with the year's animal, a countdown to the next วันพระ (the four Buddhist holy days of each month), and the coming festival, from มาฆบูชา to ลอยกระทง. In other languages it reads "month 9 · waning 4" and "Loy Krathong Nov 24".

This calendar is arithmetic rather than astronomical. The months run on the old Suriyayart reckoning, in which 800 solar years are exactly 292,207 days, the same bookkeeping behind every printed Thai calendar. It is checked against the official holy days of 2023 through 2026.

## Hawaiian

The Kaulana Mahina names every night: Hilo, Hoaka, the Kū and ʻOle nights, through Māhealani, Kāne, and Muku, each in its ten-night anahulu (hoʻonui waxing, poepoe round, hōʻemi waning). The month begins at Hilo, the first night the young crescent can be seen, so linecast computes it as a visibility date, from the crescent's geometry in the evening sky over Hawaiʻi rather than a fixed step from the new moon. Every month is checked against the [Western Pacific Regional Fishery Management Council's published calendars](https://www.wpcouncil.org/educational-resources/lunar-calendars/).

The panel carries the Council's counsel for the night, the four monthly kapu periods, the unproductive ʻOle nights, and each anahulu's fishing outlook, quoted from their educational materials with a Source: wpcouncil.org line under it.

## Samoan, Chamorro, and Refaluwasch

`samoan` and `chamorro` follow the Council's American Samoa and Guam calendars the same way. Each names thirty nights, Masina Fou through Masina Maunā and Sinahen Håcha through Sinahi, beginning the first evening the crescent can be seen over Pago Pago Harbor or Hagåtña. `refaluwasch` shows the CNMI edition: the CHamoru night with its Refaluwasch name beside it on the eleven nights that tradition names, Sighauru through Arofú.

Each is checked against every month the Council has printed since 2021. In a few months of the 2021 to 2025 editions the printed start departs from the visibility data it otherwise follows; the tests list them. Every month of the 2026 calendars matches to the night.

## Islamic

`islamic` follows the Umm al-Qura calendar, Saudi Arabia's civil calendar and the one Islamic calendar a program can compute. Since 1423 AH its rule has been geometric: a month begins the day after the first sunset at Mecca that follows the new moon with the Moon still above the horizon. linecast evaluates that rule from the same ephemeris the rest of the app draws with. Checked against the published calendar for 1423 through 1500 AH, it matches every month but one, in 2006, where the new moon fell five minutes before Mecca's sunset by one reckoning and after it by the other.

The Hijri date sits beside the phase (23 Ramadan 1447 AH) and turns at your own sunset, since the Hijri day begins in the evening. The coming month and the next observance follow with their civil dates: Islamic New Year, Ashura, Mawlid, the start of Ramadan, Laylat al-Qadr, Eid al-Fitr, the Day of Arafah, and Eid al-Adha. On the day before one, the countdown says it begins at sunset. The months are transliterated in every language, and Indonesian gets its own spellings: Ramadan, Syawal, Zulhijah.

Most countries begin Ramadan and the Eids on a sighting of the crescent, so a country's announced dates may differ from these by a day. Saudi Arabia's own announcements sometimes do.

## Hebrew

`hebrew` follows the Hebrew calendar, which has been pure arithmetic since the fourth century: the year begins at the mean new moon of Tishrei, moved by the four postponement rules, and a thirteenth month, Adar I, comes seven times in nineteen years. linecast computes it from those rules, with Dershowitz and Reingold's *Calendrical Calculations* as the reference. The tests pin every month of 5780 through 5790 and every holiday of 2023 through 2026 against Hebcal.

The date sits beside the phase (20 Elul 5786) and turns at your own sunset, since the Hebrew day begins in the evening. The coming month and the next holiday follow with their civil dates: Rosh Hashanah, Yom Kippur, Sukkot, Shemini Atzeret, Simchat Torah, Hanukkah, Tu BiShvat, Purim, Pesach, Shavuot, and Tisha B'Av. On the day before a holiday, the countdown says it begins at sunset.

The holidays follow the place shown, the way a calendar printed in Jerusalem differs from one printed in Brooklyn. Outside Israel there is a second day of Sukkot and Shavuot and of Pesach's first and last days, and Simchat Torah falls the day after Shemini Atzeret. In Israel each is one day, with Simchat Torah on Shemini Atzeret itself.

Hebrew is not one of the app's languages, so the months and holidays are transliterated in every language. The month grid names each holiday's days, and the hover chip notes each Rosh Chodesh. `--json` adds the date in Hebrew letters as well, כ׳ אלול תשפ״ו, for a consumer that can lay Hebrew out.

## The Old Farmer's Almanac

`almanac` reads the moon the way the Old Farmer's Almanac does: the light or dark of the moon beside the phase, what each half favors in the garden, and the day's solunar activity periods, the majors when the Moon crosses the meridian above or below and the minors at moonrise and moonset. The almanac's full-moon names (Harvest, Wolf, and the rest) show here and in the plain English view; a panel following another tradition's calendar keeps the plain phase name.
