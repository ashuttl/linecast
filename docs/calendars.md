# The moon's calendars

`linecast moon` can show the date in a traditional calendar beside the phase. This page says what each calendar shows, how linecast computes it, and what it was checked against.

## Choosing one

In Chinese, Japanese, Korean, Vietnamese, Thai, Persian, and Icelandic the calendar follows the language; Persian's is the Islamic. You can choose any calendar in any language: `linecast moon --calendar hebrew` for one run, or `linecast calendar hebrew` to save it for every run. `linecast calendar none` turns it off, and `linecast calendar auto` goes back to following the language. The names are `chinese`, `japanese`, `korean`, `vietnamese`, `thai`, `hawaiian`, `samoan`, `chamorro`, `refaluwasch`, `islamic`, `hebrew`, `icelandic`, and `almanac`.

Whichever calendar is active, the month grid (press `v`, or open on it with `linecast moon --month`) uses it too: the calendar's months in the title, each day's date in the corner of its cell, the month starts and observances marked, and the full date in the hover chip. Click a day and the disc view opens on it.

## Chinese, Japanese, Korean, and Vietnamese

The lunar date is shown beside the phase name, with the solar term in progress and a countdown to the next festival: 中秋节, 추석, 十五夜, or Tết Trung Thu. In Japanese the night is also called by its own name: 十六夜, 居待月, 更待月. In Vietnamese the date reads as the wall calendars print it, mùng 1 tháng Giêng or rằm tháng 8 âm lịch, and the festivals are the ones the year turns on: Tết, Rằm tháng Giêng, Giỗ Tổ Hùng Vương, Tết Đoan Ngọ, Vu Lan, Tết Trung Thu, and ông Táo về trời. When the app is in another language the same reading is written with the customary English names ("End of Heat · White Dew Sep 7", "Mid-Autumn Festival Sep 25").

The months, leap months, and solar terms are computed from the ephemeris at each calendar's own meridian: UTC+8 for China, UTC+9 for Japan and Korea, UTC+7 for Vietnam, which has kept its calendar there since 1968. Nothing is looked up in a table. The meridian matters: a new moon or a solstice close to midnight falls on different days in Hanoi and Beijing, which is why Tết came on 17 February 2007, a day before 春节, and on 21 January 1985, a month before it. Both are checked.

## Thai

The Thai lunar calendar, ปฏิทินจันทรคติไทย, gives the waxing or waning day beside the phase in Thai numerals, as the printed calendars have it (แรม ๔ ค่ำ เดือน ๙), with the year's animal, a countdown to the next วันพระ (the four Buddhist holy days of each month), and the coming festival, from มาฆบูชา to ลอยกระทง. In other languages it reads "month 9 · waning 4" and "Loy Krathong Nov 24".

This calendar is arithmetic rather than astronomical. The months run on the old Suriyayart reckoning, in which 800 solar years are exactly 292,207 days, the same rule every printed Thai calendar uses. It is checked against the official holy days of 2023 through 2026.

## Hawaiian

The Kaulana Mahina names every night: Hilo, Hoaka, the Kū and ʻOle nights, through Māhealani, Kāne, and Muku, each in its ten-night anahulu (hoʻonui waxing, poepoe round, hōʻemi waning). The month begins at Hilo, the first night the young crescent can be seen, so linecast computes when the crescent first becomes visible in the evening sky over Hawaiʻi, rather than counting a fixed number of days from the new moon. Every month is checked against the [Western Pacific Regional Fishery Management Council's published calendars](https://www.wpcouncil.org/educational-resources/lunar-calendars/).

The panel shows the Council's advice for the night, the four monthly kapu periods, the unproductive ʻOle nights, and each anahulu's fishing outlook, quoted from its educational materials with a Source: wpcouncil.org line under it.

## Samoan, Chamorro, and Refaluwasch

`samoan` and `chamorro` follow the Council's American Samoa and Guam calendars the same way. Each names thirty nights, Masina Fou through Masina Maunā and Sinahen Håcha through Sinahi, beginning the first evening the crescent can be seen over Pago Pago Harbor or Hagåtña. `refaluwasch` shows the CNMI edition: the CHamoru night with its Refaluwasch name beside it on the eleven nights that tradition names, Sighauru through Arofú.

Each is checked against every month the Council has printed since 2021. In a few months of the 2021 to 2025 editions the printed month starts on a different night from the one the visibility rule gives; the tests list those months. Every month of the 2026 calendars matches to the night.

## Islamic

`islamic` follows the Umm al-Qura calendar, Saudi Arabia's civil calendar and the one Islamic calendar a program can compute. Since 1423 AH its rule has been geometric: a month begins the day after the first sunset at Mecca that follows the new moon with the Moon still above the horizon. linecast applies that rule with the same ephemeris the rest of the app uses. Checked against the published calendar for 1423 through 1500 AH, it matches every month but one, in 2006, where the new moon fell five minutes before Mecca's sunset by one reckoning and after it by the other.

The Hijri date is shown beside the phase (23 Ramadan 1447 AH) and changes at sunset where you are, since the Hijri day begins in the evening. The coming month and the next observance follow with their civil dates: Islamic New Year, Ashura, Mawlid, the start of Ramadan, Laylat al-Qadr, Eid al-Fitr, the Day of Arafah, and Eid al-Adha. On the day before one, the countdown says it begins at sunset. The months are transliterated in every language, and Indonesian gets its own spellings: Ramadan, Syawal, Zulhijah.

Most countries begin Ramadan and the Eids on a sighting of the crescent, so a country's announced dates may differ from these by a day. Saudi Arabia's own announcements sometimes do.

In Persian the months are named as Iranian calendars print them (محرم، صفر، ربیع‌الاول) with the era ق, and the Islamic date is the moon's calendar by default, since Iranian calendars print it beside the solar date. Iran fixes its lunar months by its own sighting, so its dates can differ by a day from these; the grid's hover says so. Iran also keeps some observances on other days than Umm al-Qura's tradition, Mawlid on 17 Rabi' al-Awwal and the nights of Qadr on the 19th, 21st, and 23rd of Ramadan; linecast does not yet follow them.

## Hebrew

`hebrew` follows the Hebrew calendar, which has been pure arithmetic since the fourth century: the year begins at the mean new moon of Tishrei, moved by the four postponement rules, and a thirteenth month, Adar I, comes seven times in nineteen years. linecast computes it from those rules, with Dershowitz and Reingold's *Calendrical Calculations* as the reference. The tests check every month of 5780 through 5790 and every holiday of 2023 through 2026 against Hebcal.

The date is shown beside the phase (20 Elul 5786) and changes at sunset where you are, since the Hebrew day begins in the evening. The coming month and the next holiday follow with their civil dates: Rosh Hashanah, Yom Kippur, Sukkot, Shemini Atzeret, Simchat Torah, Hanukkah, Tu BiShvat, Purim, Pesach, Shavuot, and Tisha B'Av. On the day before a holiday, the countdown says it begins at sunset.

The holidays follow the place shown, the way a calendar printed in Jerusalem differs from one printed in Brooklyn. Outside Israel there is a second day of Sukkot and Shavuot and of Pesach's first and last days, and Simchat Torah falls the day after Shemini Atzeret. In Israel each is one day, with Simchat Torah on Shemini Atzeret itself.

Hebrew is not one of the app's languages, so the months and holidays are transliterated in every language. The month grid names each holiday's days, and the hover chip notes each Rosh Chodesh. `--json` adds the date in Hebrew letters as well, כ׳ אלול תשפ״ו, for a program that can display Hebrew.

## Icelandic

`icelandic` follows the old Icelandic calendar, the misseristal. Icelanders used it for everyday dates until the eighteenth century, and the University of Iceland's almanac, Almanak Háskóla Íslands, still prints it. The year has two halves, summer and winter, made of whole weeks: 52 of them, or 53 in a year that takes a leap week, the sumarauki. Summer begins on a Thursday between 19 and 25 April, the first day of summer (sumardagurinn fyrsti), which is still a public holiday in Iceland. Winter begins on a Saturday between 21 and 28 October, the first day of winter (fyrsti vetrardagur).

Dates in this calendar were given by the week, never by month and day, so the panel shows the week beside the phase: week 23 of summer, or 23. vika sumars in Icelandic. Next comes the month and the one after it, from Harpa to Einmánuður, with the four extra nights (aukanætur), and the leap week in the years that have it, between Sólmánuður and Heyannir. Last is a countdown to the next of the days the almanac names: the first days of summer and winter; the fardagar, the old moving days; miðsumar; the veturnætur, the last two days of summer; bóndadagur and konudagur, which open Þorri and Góa; þorraþræll and góuþræll, which close them; and the sumarmál, the last days of winter. The names are Icelandic in every language. The month grid marks each named day and month start, and the title names the Icelandic months the civil month runs through.

The almanac also names six of the moons, each from the new moon that lights it to the next. The jólatungl is the moon Epiphany falls in, and the páskatungl the moon Easter falls in. The two moons before the páskatungl are the þorratungl and the góutungl, the second moon before the jólatungl is the vetrartungl, near the first day of winter, and the moon after the páskatungl is the sumartungl, near the first day of summer. When Easter comes late and three moons fall between the jólatungl and the páskatungl, the first of them is the aukatungl, the extra moon. While a named moon is up, its name goes beside the week, and before it is lit it takes the place of "New Moon" in the line of coming phases. The month grid marks the day each one is lit. The almanac prints the names at the true new moons, but it finds the jólatungl by the church's tables, the same tables Easter is reckoned by, which have the moon new a day or two after it truly is. A moon that is new on Epiphany itself is usually new by the tables only after it, so it is not the jólatungl. In 2000 and 2019, when Easter was late as well, the moon new on 6 January was the aukatungl; the next is in 2038.

Everything is counted from the first day of summer, which has been the first Thursday after 18 April since Iceland changed to the Gregorian calendar in 1700. The leap week goes in whenever the next first day of summer would otherwise come before 19 April. About once in 28 years, when summer begins on 20 April and a Gregorian leap year follows, the year takes the leap week, and midsummer and the winter months fall a day later than they can in any other year, until the leap day. This is the rímspillir, most recently in 2023. Until 1928 the printed almanac put the leap week at the end of summer rather than before Heyannir, and linecast does the same for those years.

**Checked against:** the dates the almanac lists for 2024 to 2027; each month's weekday, week, and range of dates, as the almanac's glossary gives them, for every year from 1929 to 2399; the leap weeks and rímspillir years named by the University's Science Web; and every year's month starts from 1929 to 2098 against the tables in Svante Janson's "The Icelandic calendar" (2010), whose arithmetic linecast follows. For the moons: an old rhyme says that when the þorratungl is ten nights old, the next Sunday is nine weeks before Easter. It holds by the church's tables but not always by the true moon, and Þorsteinn Sæmundsson listed the thirteen years from 1878 to 2000 in which it fails in the almanac for 1978. linecast's þorratungl fails it in the same thirteen years and no others.

In Icelandic this is the moon's calendar by default.

## Solar Hijri, the civil date in Persian

The Solar Hijri calendar is Iran's civil calendar, and in Persian it is the date linecast writes everywhere: the moon panel, the month grid, the sunshine year, and every date in between (۱ مهر ۱۴۰۵). The Gregorian date stays in the hover chips. `linecast dates gregorian` or `solar-hijri` fixes the choice in every language, `LINECAST_DATES` sets it for one run, and `linecast dates auto` follows the language again. `--json` keeps ISO Gregorian dates whatever the setting.

The months are fixed, six of 31 days, five of 30, and Esfand of 29 or 30, so only the first day of the year needs astronomy. The University of Tehran's Calendar Center begins the year on the day of the March equinox if the equinox falls before true noon at the 52.5° E meridian, and on the next day if not. linecast computes it the same way, from the equinox of the app's ephemeris less ΔT, and the true noon of the same. Other statements of the rule differ slightly: Borkowski's uses mean noon at Tehran, and the two first part in 2124 (1503 SH), whose equinox falls two minutes before one noon and half a minute after the other. The 2820-year arithmetic calendar often printed in software is not the official one and differs in 1403, 1436, and 1469, where it makes the following year the leap year.

The month grid in Persian is a Solar Hijri month laid out from its 1st, with the week opening on Saturday in Iran. Each cell carries the Gregorian day small in a corner, and the Islamic day in the other; the title names the Gregorian and Hijri months the Solar Hijri month spans. The sunshine year marks the Solar Hijri months, which begin near the 21st of the Gregorian ones, by name where they fit and by number (1405/7/1) where they do not.

The panel counts down to the year's observances: Chaharshanbe Suri, the eve of the year's last Wednesday; Nowruz; Sizdah Bedar (13 Farvardin); Tirgan (13 Tir); Mehregan (10 Mehr, as the official calendar prints it); Yalda, the night of 30 Azar; and Sadeh (10 Bahman). In the month before Nowruz the turn of the year (تحویل سال) gets a line of its own, counted down to the equinox itself, to the second on its last day. On Yalda the sunshine line names the night.

**Checked against:** Wikipedia's table of Nowruz dates and leap years for 1354–1419 SH, Borkowski's leap years for 1300–1501 SH (every year agrees), and the Calendar Center's announced instants of the equinox for 1396–1405 SH, which the computed ones match within 26 seconds. The closest year to the noon line between 1300 and 1500 SH is 1470 (2091), whose equinox falls four minutes after true noon.

## The Old Farmer's Almanac

`almanac` shows what the Old Farmer's Almanac says about the moon: the light or dark of the moon beside the phase, the gardening advice for each, and the day's solunar activity periods, the majors when the Moon crosses the meridian above or below and the minors at moonrise and moonset. The almanac's full-moon names (Harvest, Wolf, and the rest) show here and in English when no calendar is chosen; with another calendar, the phase keeps its plain name.
