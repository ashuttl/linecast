# Languages

linecast speaks your terminal's language if it knows it, and English otherwise. `linecast language es` saves a choice, `linecast language auto` follows the terminal again, and `--lang es` on any command sets it for one run. `LINECAST_LANG` overrides the saved setting and the terminal's locale.

## The languages

| Code | Language | Code | Language |
| --- | --- | --- | --- |
| `en` | English | `pl` | Polish |
| `fr` | French (France) | `hu` | Hungarian |
| `fr-CA` | French (Canada) | `ru` | Russian |
| `es` | Spanish (Latin America) | `uk` | Ukrainian |
| `es-ES` | Spanish (Spain) | `el` | Greek |
| `pt` | Portuguese (Brazil) | `tr` | Turkish |
| `pt-PT` | Portuguese (Portugal) | `fa` | Persian (experimental) |
| `it` | Italian | `sw` | Swahili |
| `ro` | Romanian | `zh` | Chinese, simplified script |
| `de` | German | `zh-Hant` | Chinese, traditional script (Taiwan) |
| `nl` | Dutch | `zh-HK` | Chinese, traditional script (Hong Kong) |
| `da` | Danish | `ja` | Japanese |
| `no` | Norwegian | `ko` | Korean |
| `sv` | Swedish | `th` | Thai |
| `is` | Icelandic | `vi` | Vietnamese |
| `fi` | Finnish | `id` | Indonesian |
| `cs` | Czech | `eo` | Esperanto |
| `sk` | Slovak | `he` | Hebrew (experimental) |
| `ar` | Arabic (experimental) | | |

A regional variant changes only the words that differ in its country, and Hong Kong Chinese also uses the Hong Kong Observatory's words for the weather. The terminal's locale chooses the variant, so `fr_CA` reads Canadian French and `pt_BR` reads Portuguese. Macau's `zh_MO` reads Hong Kong Chinese, Singapore's `zh_SG` reads simplified Chinese, and Norway's `nb_NO` and `nn_NO` both read Norwegian.

## What follows the language

- **Units.** With metric units, wind speeds are in metres per second in Japanese, Korean, Danish, Norwegian, Swedish, Icelandic, Finnish, Russian, Ukrainian, Czech, and Slovak, as those countries' forecasts give them, and in km/h elsewhere.
- **The moon's calendar.** In Chinese, Japanese, Korean, Vietnamese, and Thai, `moon` shows that language's traditional calendar; in Persian and Arabic, the Islamic; in Hebrew, the Hebrew calendar. See [calendars.md](calendars.md).
- **The sky.** In Chinese, `sky` draws the Chinese sky; in every other language, the IAU constellations. Star and constellation names come from Wikidata where the language has them. Swahili names Crux and Scorpius; other stars and constellations keep their catalogue names.
- **The hours.** In Swahili, `sunshine` reads the day in Swahili time. See [hours.md](hours.md).

In India, many weather alerts are published in the state language. `weather --lang hi`, `--lang te`, `--lang mr`, or another Indian language code shows them in that language where it exists; the rest of the app stays in English.

## Persian and right-to-left text

Hebrew (`he`) and Modern Standard Arabic (`ar`) are experimental too, using the same RTL layout and output pass. Try `linecast weather --lang he` or `linecast weather --lang ar`. Neither translation has had native-speaker review. The terminal results below are from the Persian experiment; Hebrew and Arabic still need hands-on testing across terminals.

Arabic uses shared formal written Arabic, with January as يناير and Arabic-Indic digits (٠١٢٣٤٥٦٧٨٩). Regional month names and digit preferences differ; this first pass does not provide regional Arabic variants. `linecast digits latin` selects 0–9. Hebrew uses 0–9 by default, and the older locale code `iw` also selects Hebrew. Both keep Gregorian civil dates; the Moon adds the Islamic calendar in Arabic and the Hebrew calendar in Hebrew.

Review is particularly welcome for forecast sentences assembled from several phrases, astronomical and tidal terminology, and narrow labels. The Arabic translation follows the written variety described by [W3C’s Arabic layout requirements](https://www.w3.org/TR/alreq/), which also discuss regional digit conventions.

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
