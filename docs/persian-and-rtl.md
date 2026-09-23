# Persian, and right-to-left: a brief

Written 2026-09-22 against `next` at b0bffbf as a plan, and built on 2026-09-23. The design below is what was built, except where [What was built](#what-was-built) says otherwise; that section, at the end, also lists what is still open.

## The short answer

Yes, it can be done properly. The translation is the smaller part of the work, about the size of the Czech or Turkish additions. The larger part is that terminals mostly do not draw right-to-left text at all, and the ones that try do it per line, in a way that scrambles a full-screen layout. linecast has to do the work itself: put the text in display order, join the letters, and tell the terminals that would otherwise reorder it again not to. Done once, in one output pass, that also fixes a bug every language has today, and it is most of what Hebrew, Arabic, and Urdu will need later.

## What a Persian reader should get

- Text that reads right in the terminals they actually use: letters joined, words in order, numbers and Latin names placed as they would be in a Persian book.
- Persian digits (۱۴۰۵), the Persian decimal separator (۱۱٫۳) and percent sign (۴۰٪), Persian punctuation (، ؛ ؟ « »), and the zero-width non-joiner (نیم‌فاصله) where the language needs it: می‌شود, ابرها.
- Dates in the Solar Hijri calendar (۳۱ شهریور ۱۴۰۵), weeks that open on Saturday, and the year turning at Nowruz, counted down to the moment of the equinox (لحظهٔ تحویل سال), which Iranians watch for.
- A layout that reads from the right: headings and prose anchored right, menus and chips on the right, tables in right-to-left order.
- Persian names for places, map labels, stars, and constellations.
- Weather prose in the register of the Iranian Meteorological Organization (IRIMO, هواشناسی), written as a Persian forecaster would say it, not translated from English.
- Keys that work with the Persian keyboard layout switched on. Pressing `q` on that layout types ض.
- If their terminal does something unusual, a line in `linecast doctor` that says what linecast saw and what to change.

## Why a terminal makes this hard

Persian is written right to left, and its letters change shape by position (initial, medial, final, isolated). Strings in memory are in logical order, first letter first. A terminal that does neither bidirectional reordering nor shaping (Alacritty, foot, kitty, Ghostty, xterm, st, Windows Terminal, and tmux, which passes cells through) shows a logical Persian string backwards, with every letter in its isolated form. That is what linecast does today with every Arabic-script or Hebrew name it draws, in every UI language: map labels around Tehran, Cairo, or Tel Aviv, a Nominatim place name with no translation, an alert feed's text.

The terminals that do reorder do it per line, treating the whole row as one paragraph. VTE (GNOME Terminal, Ptyxis, GNOME Console, Tilix, xfce4-terminal) implements Egmont Koblinger's "BiDi in Terminal Emulators" recommendation, which by default reorders each line implicitly. A row that holds a graph, a column of numbers, and a Persian label is not a paragraph, and reordering it as one moves things that must not move. That recommendation's answer for full-screen programs is the one to follow here: the program does its own reordering and shaping, and switches the terminal to explicit mode (BDSM reset, `CSI 8 l`) so it draws cells as sent. Unknown modes are ignored by terminals that do not implement it, so the escape is safe to send everywhere.

Terminal behaviour to confirm in Stage 0 (only Alacritty and foot are installed on this laptop):

| Terminal | Reorders? | Shapes? | Expected with linecast's pass | Status |
| --- | --- | --- | --- | --- |
| Alacritty, foot | no | no | correct | installed here; to capture |
| kitty, Ghostty, xterm, st, Windows Terminal | no | no | correct | to confirm |
| WezTerm | only with `bidi_enabled` (off by default) | with it | correct by default | to confirm |
| VTE terminals | implicitly, by default | yes | correct once `CSI 8 l` is sent | to confirm; the most important one |
| Konsole | yes, a profile option that is on by default | yes | probably reordered twice: Konsole is not known to honour BDSM | to confirm; needs a decision |
| mlterm | yes | yes | should honour BDSM | low priority |
| tmux inside VTE | tmux: no; VTE: yes | | VTE never sees `CSI 8 l` unless linecast sends it through tmux's passthrough (`allow-passthrough on`) | to confirm |
| iTerm2, Apple Terminal | has some bidi support | | not on Linux; check once on the Mac | to confirm |

Fonts: the glyphs linecast will send are the Arabic Presentation Forms (U+FB50–FDFF, U+FE70–FEFF). Noto Sans Arabic, DejaVu Sans Mono, and Vazir Code (the monospace Persian font many Iranian developers use) are believed to cover them; Noto Sans Arabic is installed here and can be checked with `fc-query`. A terminal without such a font falls back to boxes, which `doctor` can warn about.

## Design

### Strings stay in logical order

Tables, templates, geocoder results, and tile names stay as they are, in logical order. Wrapping (`wrap_display_width`) and truncation (`truncate_display_width`) keep working on logical text, which is correct: a Persian paragraph breaks at the same words whatever the display order, and the ellipsis added at the logical end appears at the left, where the Persian line ends. Only the output changes.

### Marking the runs

Each place that puts text into a frame wraps it in a Unicode isolate: RLI (U+2067) … PDI (U+2069) for UI text in a right-to-left language, FSI (U+2068) … PDI for data whose direction is not known in advance (a place name, a map label, a star name, an alert headline). Isolates are the standard way of saying "this span is its own paragraph with its own direction". They take no cells, and the output pass removes them. Inside an isolate the text is ordered as its own paragraph; outside, the row stays where the view put it. Numbers and Latin words inside Persian text land where a Persian reader expects them, and nothing around the isolate moves.

Unmarked text still gets the standard algorithm, so a lone Hebrew label in an English row comes out right even before every emission point is marked. Marking matters where direction must be forced (a Persian sentence that begins with a Latin place name) and where two right-to-left runs share a row with plain spaces between them (two map labels over water), which the algorithm would otherwise join into one run and swap.

About 150 `visible_len` sites in 25 files lay out text, plus the overlay helpers (`menu_box`, `pointer_chip`, `toast_box`, the help panel) at 15 sites. Most of these do not need a change: the helpers and the text-drawing functions of each view are the places to mark.

### One output pass: `_bidi.py`

A new stdlib-only module that turns a row of logical text with SGR escapes into a row of display-order cells:

1. Parse the row into cells, each a character (with any zero-width characters attached) and the SGR state it was drawn with. Rows with no character from the right-to-left blocks (U+0590–08FF, U+FB1D–FDFF, U+FE70–FEFF, and the historic scripts above U+10800) and no bidi control skip everything below, a check a precompiled regex does in one scan; the half blocks and braille that fill graph rows are outside those blocks; this fast path is what keeps `maps` and `radar` as fast as they are now. Check with `scripts/bench_maps_live.py`.
2. Run the Unicode Bidirectional Algorithm (UAX #9) with a left-to-right base direction for the row: explicit isolates, weak and neutral resolution, rule L1, reordering (L2), and mirroring of brackets and quotes inside right-to-left runs (L4, a small pair table: `()`, `[]`, `{}`, `<>`, `«»`). `unicodedata.bidirectional()` gives every character's class. Block elements (U+2580–259F), braille, box drawing, and the icon ranges count as segment separators, so a graph between two runs of text never reverses and a run never crosses one.
3. Shape: replace each Arabic-script letter with its presentation form by its neighbours' joining. The table comes from `unicodedata` alone: each presentation form decomposes as `<initial>`, `<medial>`, `<final>`, or `<isolated>` of its base letter. Checked this session: every Persian letter (پ چ ژ گ ک ی included) and the Urdu letters (ٹ ڈ ڑ ں ے ہ ھ) have their forms there, so no dependency and no hand-typed table are needed. A letter with only final and isolated forms (ا د ذ ر ز ژ و) does not join to the next one. Marks (harakat) are transparent. ZWNJ breaks a join, ZWJ and tatweel make one, and the pass drops ZWNJ and ZWJ once they have done their work.
4. Localise digits (see Numbers).
5. Emit the cells in display order, each with its SGR state.

The cell count must not change: a frame is laid out in columns before the pass runs, so the pass may permute cells but not add or remove any. That rules out the lam-alef ligature (ﻻ, two letters in one glyph). لا is drawn as lam in its initial form and alef in its final form, in two joined cells, which is how a cell-grid terminal generally draws it. A property test states the invariant: display width in equals display width out, for any row.

Where the pass runs: on each body row in `frame_paint`, on each line of the floating overlays, in `print_frame`, on `--oneline` when stdout is a terminal, and through a small `display()` helper for the plain CLI output (`--help`, `linecast language`, `doctor`, error messages). Where it does not run: `--json`, and `--oneline` to a pipe. waybar and polybar hand the text to Pango or their own renderer, which reorders and shapes by itself, so they must get logical text. `--print` is a picture of the screen, so it gets the display order even when piped.

Terminal mode: send `CSI 8 l` when the live loop starts, beside the other modes in `live_loop`'s init, and `CSI 8 h` on exit; wrap `--print` output in the same pair, as `print_frame` already does for autowrap. Inside tmux, also send it through tmux's passthrough. `LINECAST_BIDI=terminal` sends logical text and leaves the reordering to the terminal, an escape hatch for Konsole users. Konsole's `KONSOLE_VERSION` in the environment might let this be chosen automatically; Stage 0 decides.

Width fixes, needed now for every language: `char_width` gives LRM, RLM, ALM, and the isolates (U+200E, U+200F, U+061C, U+2066–2069) one cell each; checked this session. They are format characters with no width, and OSM names do carry them. Give every `Cf` character zero width. `calibrate_from_terminal` could add a presentation-form probe (ﺏ) to learn whether the terminal draws Arabic in one cell.

Text fields: the location search in `weather` and the search in `maps` and `sky` show a buffer the user is typing into. In a right-to-left language the field shows the logical buffer through the pass with a right-to-left base, and the caret goes at the display column of the logical insertion point, which the reordering map gives directly. Typing تهران into the location search is the first thing a Persian user will do, so this cannot wait for polish.

### Numbers

- Digits: Persian digits by default in Persian, which is what CLDR, Iranian print, and Persian-language weather sites use. The pass converts ASCII digits in rows drawn in Persian. Identifiers keep Latin digits: a station id, a version, a key name, a URL. They are marked by an LRI isolate or a small no-convert marker. A setting (`LINECAST_DIGITS=latin` and a config key) serves developers who prefer Latin digits. The digit set is per language: Persian and Urdu use U+06F0–06F9; Arabic uses U+0660–0669 in the Mashriq and Latin digits in the Maghreb, a regional variant; Hebrew uses Latin digits. Persian digits have bidi class EN and Arabic-Indic digits class AN, and the algorithm treats the two differently, which a test should pin.
- Decimal and percent go through `fmt_decimal` and `fmt_percent`, not a blind replace: `DECIMAL_COMMA` becomes a per-language mark table (٫ for Persian), and `fmt_percent` gets the Persian sign, ۴۰٪.
- Minus and degree signs: check that ‎−۳° comes out whole in every place a temperature is drawn, including the graph's axis labels, which sit outside any text isolate.

### Layout that reads from the right

The pass alone gives correct text in left-to-right positions. That is a large step up on its own and could ship first. Mirroring the layout is per view, keyed off `is_rtl(lang)` from an `RTL_LANGUAGES` set in `_i18n.py`:

- Always: headings, labels, prose, and lists anchored to the right edge; prose right-aligned; panels in reversed order; menus, chips, and toasts opened from the right; the help panel's two columns swapped; the location control, which sits top right in `weather`, moved to top left.
- Charts whose horizontal axis is time: this is the decision below. If mirrored, add a `mirror` flag to `Framebuffer` that reverses columns at render, with a glyph mirror table (the braille dot columns swapped, ▌▐, ▖▗, ▘▝, ▙▟, ▛▜, box corners, arrows, slashes), hit-testing that maps a mouse column back to the data index, and input that follows the axis (← goes forward in time, and a scroll or drag moves the way the chart runs).
- Never: pictures of the world. `maps`, `radar`, the globe, `sky`, and the moon disc keep east where it is; only their text mirrors.

| View | Text | Chart |
| --- | --- | --- |
| weather | header, prose, daily list, alerts, AQI line | hourly graph: decision 1 |
| sunshine | day length, times, hours list | day arc pictures the sky facing the equator, keep; year view axis is dates, decision 1 |
| moon | panel, countdowns | disc kept; month grid mirrored, Saturday in the right-hand column |
| sky, maps, radar | labels, panels, search, directions steps | never mirrored |
| tides | station, highs and lows | curve: decision 1 |
| clock, week, calendar and hours commands | all | none |

### The language

The tables: a block in every `*i18n*.py` table and in `_hours/i18n.py`, plus everything the adding-a-language checklist names (in Claude's project memory; it belongs in CONTRIBUTING.md) (`LANGUAGES`, `LANG_CODES`, the `--lang` help, the README count and language paragraphs, `fmt_hour_phrase`, `CULTURE_TITLES`, the asterisms, `WIKIDATA_LANG`). Roughly 500 strings, most of them the weather prose. Translate as earlier languages were: agents working from a written brief, one JSON file per table, merged by script, then read against real forecasts with `linecast prose --lang fa`.

Guidance for the translators:

- Register: standard written Persian (فارسی نوشتاری), plain and neutral, as IRIMO and Persian news sites write forecasts. Key legends use the short noun or infinitive forms Persian interfaces use (جستجو، خروج, not imperatives). Full sentences addressed to the user take the polite plural (دوباره امتحان کنید).
- Orthography: the Academy of Persian Language and Literature's rules (دستور خط فارسی). Persian ک and ی, never Arabic ك and ي; a test should reject U+0643, U+064A, and U+0649 in Persian strings. The ZWNJ in می‌, ها attached to its noun, and one consistent spelling of the ezafe after a silent he (ـهٔ). Persian digits in the tables themselves, so the tables read right without the pass.
- Grammar the templates must allow, per the agreement mechanisms already in `weather/i18n.py` (`_PRECIP_CLASSES`, elision, the `_by` and degree-word forms): a noun after a numeral stays singular (۳ روز), so `plural_category` returns "one" for 1 and "many" otherwise, as CLDR's fa rule has it, and the forms coincide. Place names take prepositions, not cases (در تهران), so none of the declension traps that Turkish and Russian needed dodging. The verb goes at the end, so templates where English puts a time or a name last will be reordered freely, which the placeholder scheme already allows.
- Clock: 24-hour in running text, `_HOUR_24["fa"] = "ساعت {h}"` or close to it; not in `SENTENCE_12H`.
- Units: IRIMO writes کیلومتر بر ساعت in public forecasts. Whether compact labels keep `km/h` in Latin letters or use a Persian abbreviation is for a native reviewer. Whether IRIMO gives wind in m/s anywhere (which would put fa in `WIND_MS_LANGUAGES`) needs checking against its published bulletins.
- Vocabulary to check against IRIMO text: رگبار (shower), وزش باد شدید, مه (fog), غبار and گرد و خاک (dust, which Iran reports and linecast's codes may not name), آسمان صاف, نیمه‌ابری, ابری.

Data sources:

- Geocoding: Open-Meteo answers `language=fa` in Persian; checked this session (اصفهان، استان اصفهان، ایران). Nominatim takes `Accept-Language: fa`.
- Maps: tiles carry `name:fa`, and `maps/labels.py` already builds `name:{lang}`. Check that the Natural Earth basemap in `radar/basemap.py` has a Persian key.
- Sky: add `"fa": "fa"` to `WIKIDATA_LANG` and rebake as that checklist describes. Wikidata labels 86 constellations in Persian; checked this session, and the same count holds for Hebrew, Arabic, and Urdu (Urdu's might be transliterations; check). Check the star labels against fa.wikipedia's first sentences, since many labels will be transliterations of the IAU names. Persian has its own traditional star names through al-Sufi (عبدالرحمن صوفی رازی), whose *Book of Fixed Stars* is behind many IAU names. A Persian or Arabic sky culture could be added later; Stellarium has Arabic cultures to start from.
- Alerts: Iran is not among the 45 alert countries, and IRIMO does not appear to publish a CAP feed. Leave it, and say so in SOURCES.md.
- Prayer times: the Tehran method is already the default for Iran (`_hours/prayer_times.py`, `"IR": "tehran"`), and Saturday is already Iran's first day of the week (`SATURDAY_FIRST_COUNTRIES`). Name the times as Iranian timetables (اوقات شرعی) do: اذان صبح، طلوع آفتاب، اذان ظهر، غروب آفتاب، اذان مغرب، نیمه‌شب شرعی. Check whether the module gives the Shia midnight.

### Calendars

A new `_calendars/solar_hijri.py`. The months are fixed: six of 31 days, five of 30, and Esfand of 29 or 30. Only the first day of the year needs astronomy: 1 Farvardin is the day of the March equinox if the equinox falls before noon at 52.5° E (Iran Standard Time, UTC+3:30), and the day after if it falls later. The app's ephemeris already computes the equinox. Test cases: the 2025 equinox at 09:01 UTC is 12:31 IRST, after noon, so 1 Farvardin 1404 is 21 March 2025; the 2026 equinox at 14:46 UTC puts 1 Farvardin 1405 on 21 March 2026. Check a span of years against the tables of the Calendar Center of the University of Tehran's Institute of Geophysics, as the Hijri module was checked against Umm al-Qura's.

Where it shows:

- Dates across the app: the daily list, the moon panel's dates, the moon month grid (a Solar Hijri month such as مهر ۱۴۰۵, with Gregorian dates small in the cells or on hover), and the sunshine year view's month ticks, which fall around the 21st of each Gregorian month. This is new architecture: linecast has no civil calendar besides the Gregorian today, only the traditional calendars the moon shows beside it. It needs a `civil_calendar(lang)` with an override; decision 3.
- Observances counted down in the moon panel: Nowruz, to the second of the equinox (تحویل سال); Chaharshanbe Suri, the eve of the year's last Wednesday; Sizdah Bedar (13 Farvardin); Tirgan (13 Tir); Mehregan (16 Mehr); Yalda, the night of 30 Azar, the longest of the year, which `sunshine` could name on its day; Sadeh (10 Bahman).
- The Islamic calendar with Persian month names (محرم، صفر، …), with one caveat: Iran fixes the lunar months by its own sighting, so Tasua, Ashura, and the Ramadan dates can differ by a day from Umm al-Qura. The panel should say so, as the Hijri docstring already does for other countries.
- docs/calendars.md gets a Solar Hijri section, with sources.

### Keys under a Persian layout

With the Persian layout active, every single-letter key in the app types a Persian letter. On the standard ISIRI 9147 layout, `q` is ض, `l` is م, `v` is ر, `t` is ف. Map those characters back to the Latin keys they sit on, one table per layout, before key dispatch in `_live.py`. The same gap exists today for Russian, Ukrainian, Greek, and Korean users, so this is a fix for every non-Latin layout, and could go first. Terminals that speak the kitty keyboard protocol can report the base-layout key directly (progressive enhancement flag 4), which is exact where it is available. Check the table against the ISIRI 9147 standard, not memory.

## Toward Hebrew, Arabic, and Urdu

Shared with Persian: `RTL_LANGUAGES`, the output pass, isolates, layout mirroring, text fields, the terminal mode, and the doctor check. Shaping already covers Arabic and Urdu letters.

Each has its own questions:

- Hebrew: no shaping; niqqud are combining marks and already take no width. Latin digits. linecast already has the Hebrew calendar and the halachic hours, so Hebrew may be the easiest second right-to-left language, and a good way to check that nothing in the design is Persian-specific. Week opens Sunday (IL is already in `SUNDAY_FIRST_COUNTRIES`).
- Arabic: CLDR's six plural categories (zero, one, two, few, many, other), dual forms, and noun–adjective gender agreement, so `plural_category` and the prose templates grow; Modern Standard Arabic as the base, with digit and vocabulary variants by region (ar-EG, ar-MA) as overlays in the existing `VARIANTS` scheme. Umm al-Qura and prayer times are already there.
- Urdu: written in Nastaliq, which a cell grid cannot draw; the presentation forms give Naskh. That is how most terminals and many phones show Urdu, but the brief for that language should say so plainly. Urdu shares the extended digits with Persian but draws ۴ ۶ ۷ differently, which is the font's business, not linecast's.

## What was built

All of Stages 0 to 6 are on `next`, each in its own commits: the output pass (`_bidi.py`), keys under non-Latin layouts (`_keylayouts.py`), the Solar Hijri calendar and the civil-date hook (`_calendars/solar_hijri.py`, `_calendars/civil.py`), the Persian strings and the sky names, the right-to-left layout, the Iranian prayer timetable, `linecast dates` and `linecast digits`, the doctor rows, and these docs.

Andrew's decisions: time charts are mirrored; Persian digits by default; Solar Hijri as the date throughout; لا in two joined cells; no native reader yet.

Where the build differs from the plan above:

- The layout is not mirrored view by view. A view says it reads from the right (`_bidi.set_mirror`) and the output pass lays each row out from the right: segments trade sides, box drawing, blocks, and braille are flipped, and the live loop mirrors the pointer and the arrow keys. A picture inside a mirrored view is drawn flipped for the row's flip to undo, as the Moon is on the disc and in the grid. Weather, tides, sunshine (both views), and the Moon (both views) are mirrored; maps, radar, and the sky are not, and their help panel lays itself out from the right instead.
- The sunshine day's arc is plotted by the hour, midnight to midnight, and never flips by hemisphere, so it is a time chart and is mirrored; the plan had called it a picture of the sky.
- Each gap-separated segment of a row is its own paragraph, right to left when the interface is and the segment holds right-to-left text, else by its first strong character, so the views needed no isolates around their text. The pass also keeps a minus sign and °C with their numbers, writes ، beside a Persian word, and draws the ezafe ـهٔ as ۀ, which has presentation forms of its own.
- Durations are written in words in Persian (۶ ساعت و ۷ دقیقه), through `_i18n.fmt_duration_parts`.
- Where a map label has no name in the reader's language, a local name in the reader's script comes before the Latin transliteration.
- Mehregan is on 10 Mehr, as the official calendar prints it, not 16. The equinox instants now take off ΔT, which fixed the moon's season countdowns for every language.
- Iranian timetables print no separate imsak, so the Tehran method lost its ten-minute one.

Terminals: foot and Alacritty draw it correctly, checked with Vazir Code and without. Konsole (26.08) ignores `CSI 8 l` and reorders every line itself, which reversed each word a second time; linecast now recognizes it by the name it reports (XTVERSION, or `KONSOLE_VERSION` when it does not say) and hands each piece of right-to-left text over in logical order inside an isolate, which Konsole honours, checked in a live Konsole. The general alternatives were tested and fail: marking display-ordered text with LRM or LRO makes Konsole keep the order but it reshapes the letters wrongly, and Alacritty draws the marks as visible glyphs; Konsole drops a zero-width character sent at column 1; and no query tells a terminal that reorders from one that does not (neither Konsole nor foot answers DECRQM for mode 8; XTVERSION names both). With a proportional fallback font the letters are the right forms but do not touch. VTE, WezTerm, kitty, Ghostty, tmux inside VTE, and the Mac terminals are unchecked. Doctor says which mode is in use and what to change.

Still open:

- A native Persian reader, for the strings (the list of doubts is in each translation commit and the agents' notes: عصر for evening, تندباد, the day abbreviations in the moon grid, the sky's title-versus-traditional star names), and for how the mirrored layout feels.
- Iran's own dates for Mawlid (17 Rabi' al-Awwal) and the nights of Qadr (19, 21, 23 Ramadan), which differ from Umm al-Qura's tradition.
- A Persian frame in the gallery, which needs a choice of font: the gallery's MonaspiceNe has no Arabic.
- Hebrew, Arabic, and Urdu, which the pass, the mirroring, and the keys already serve; each needs its strings and the questions under "Toward Hebrew, Arabic, and Urdu".
