# Languages

linecast speaks your terminal's language if it knows it, and English otherwise. `linecast language es` saves a choice, `linecast language auto` follows the terminal again, and `--lang es` on any command sets it for one run. `LINECAST_LANG` overrides the saved setting and the terminal's locale.

## The languages

| Code | Language | Code | Language |
| --- | --- | --- | --- |
| `en` | English | `ru` | Russian |
| `fr` | French | `uk` | Ukrainian |
| `es` | Spanish | `el` | Greek |
| `pt` | Portuguese | `tr` | Turkish |
| `it` | Italian | `fa` | Persian (experimental) |
| `ro` | Romanian | `sw` | Swahili |
| `de` | German | `zh` | Chinese, simplified script |
| `nl` | Dutch | `zh-Hant` | Chinese, traditional script |
| `da` | Danish | `ja` | Japanese |
| `no` | Norwegian | `ko` | Korean |
| `sv` | Swedish | `th` | Thai |
| `is` | Icelandic | `vi` | Vietnamese |
| `fi` | Finnish | `id` | Indonesian |
| `cs` | Czech | `eo` | Esperanto |
| `pl` | Polish | | |

## Regional variants

Portuguese is Brazilian, Spanish is Latin American, French is that of France, and Traditional Chinese follows Taiwan. `pt-PT`, `es-ES`, `fr-CA`, and `zh-HK` use the words that differ in Portugal, Spain, Canada, and Hong Kong. Hong Kong Chinese takes the Hong Kong Observatory's words for the weather.

A terminal locale chooses the variant by itself: `pt_PT`, `es_ES`, and `fr_CA` read their variants, `zh_HK` and `zh_MO` read Hong Kong Chinese, `zh_TW` reads Traditional Chinese, and `zh_CN` and `zh_SG` read Simplified. `nb_NO` and `nn_NO` read Norwegian.

## What follows the language

- **Units.** With metric units, wind speeds are in metres per second in Japanese, Korean, Danish, Norwegian, Swedish, Icelandic, Finnish, Russian, Ukrainian, and Czech, as those countries' forecasts give them, and in km/h elsewhere.
- **The moon's calendar.** In Chinese, Japanese, Korean, Vietnamese, and Thai, `moon` shows that language's traditional calendar; in Persian, the Islamic. See [calendars.md](calendars.md).
- **The sky.** In Chinese, `sky` draws the Chinese sky; in every other language, the IAU constellations. Star and constellation names come from Wikidata where the language has them. Swahili names Crux and Scorpius; other stars and constellations keep their catalogue names.
- **The hours.** In Swahili, `sunshine` reads the day in Swahili time. See [hours.md](hours.md).

In India, many weather alerts are published in the state language. `weather --lang hi`, `--lang te`, `--lang mr`, or another Indian language code shows them in that language where it exists; the rest of the app stays in English.

## Persian and right-to-left text

Persian support is experimental. A native reader has not yet checked the translation, and right-to-left text does not work in every terminal. If something reads oddly, please open an [issue](https://github.com/ashuttl/linecast/issues).

It has been tested in [Ghostty](https://ghostty.org/), [Alacritty](https://alacritty.org/), and [foot](https://codeberg.org/dnkl/foot). It does not work well in the Mac's Terminal or in iTerm2, which reorder the text themselves and draw it out of place. On a Mac, use Ghostty or Alacritty for Persian.

In Persian:

- Weather, tides, the Moon's panel and month grid, and sunshine read from the right. Graphs run right to left, with now at the right, and `←` moves forward in time. Maps, radar, the sky, and the Moon itself are not mirrored.
- Dates are in the Solar Hijri calendar. `linecast dates gregorian` switches to the Gregorian; `solar-hijri` works in any language.
- Numbers are in Persian digits. `linecast digits latin` keeps 0–9; `native` goes back.
- The Moon's panel counts down to Nowruz and the year's festivals.
- With the Tehran method, the default in Iran, `sunshine --hours islamic` lists the times Iranian timetables print.

Most terminals draw right-to-left text backwards and leave Arabic letters unjoined, so linecast orders and joins the letters itself and asks the terminal to draw them as sent. The letters join cleanly in a monospace font with Arabic letters, such as [Vazir Code](https://github.com/rastikerdar/vazir-code-font).

Some terminals order the text themselves and ignore that request. linecast recognizes Konsole and the Mac's Terminal, lays out each row, and leaves the ordering and joining to them. `LINECAST_BIDI=terminal` does the same in another terminal that orders text itself, and `LINECAST_BIDI=linecast` goes back to linecast's own ordering, for a Konsole with its bidi rendering turned off. `linecast doctor` shows which is in use, with a line of Persian and Hebrew to show whether your font has the letters.

Names in Hebrew, Arabic, Persian, and Urdu on maps and in the sky are ordered and joined the same way in every language.

[persian-and-rtl.md](persian-and-rtl.md) is the design brief behind this work, with notes on each terminal and what is still open.
