# Refreshing the gallery

`minitel-terminatel-258.jpg` is a period photograph from [minitel-alcatel.fr](https://www.minitel-alcatel.fr/), credited in the main README's Lineage section. Keep it as supplied.

The README gallery is captured from linecast's live terminal UI by `scripts/offscreen_terminal.py`. It needs no display and leaves the desktop untouched. Captures draw text at 2× density as foot does, inside an Omarchy window, with scripted typing, hovering, clicks, and drags. An empty config directory keeps captures independent of your saved settings; the script's flags choose the place, units, and clock. `LINECAST_CAPTURE_FONT` selects the typeface and `LINECAST_CAPTURE_THEME` selects the theme, which defaults to Tokyo Night.

The script needs [uv](https://docs.astral.sh/uv/), fontconfig, ImageMagick, and ffmpeg for the recordings. Pillow draws the glyphs; the scripts name it in their headers, and uv fetches it. The Omarchy themes are read from `/usr/share/omarchy/themes` and `~/.local/share/omarchy/themes`.

`LINECAST_CAPTURE_TOOL=termshot` photographs a real foot on an offscreen Hyprland output with [`termshot`](https://github.com/ashuttl/dotfiles-omarchy/tree/main/termshot) instead; the options are the same.

The READMEs and the gallery page refer to these files by relative path, so on GitHub each branch shows its own: new frames can live on `next` for a while before they reach `main`. PyPI renders the README with no repository behind it, so the package build first runs `scripts/pin_readme.py`, which points the package's copy at the commit it was built from.

From the repository root:

```sh
scripts/capture_screenshots.sh all
```

Individual targets are also available:

```sh
scripts/capture_screenshots.sh weather sunshine year moon sky tides radar maps globe gallery tours hero languages themes
```

`all` leaves out the three desktops, `hero`, `languages`, and `themes`, since they are composed from live panes and a hand-taken screenshot may stand in for the hero; name them to run them.

The `gallery` target fills `screenshots/gallery/` with the frames [the gallery](../docs/gallery.md) shows and the README does not: the radar in its fixed themes and its satellite and condition layers, the sky in more traditions, the weather in a short window, with a day's hours under the pointer, and in its month view, the moon's month grid, terrain over Cook Strait and the Alps, a continent under the hour's clouds (centred where it is mid-afternoon at capture time, like the globe), and a walking route. The maps target itself makes the README's street and terrain frames, the terrain over New Zealand for its seafloor, and the five-zoom series over Portland that the README shows three of. The README's own frames stay in this directory; a new state belongs in the gallery target and on the gallery page, not in the README, unless it earns a place there.

Weather, tides, radar, and maps use current public data. Sunshine, Moon, and sky use fixed local moments through `scripts/capture_moment.py`, keeping those frames repeatable at any time of day. The weather target makes four frames: Dublin at 110×34, where the dashboard is at its densest; two smaller ones, Reykjavík in Icelandic and Kyoto in Japanese, both metric; and the year view for Westbrook at 130×38, with the pointer on a week in May so that week's chip is in the frame. The gallery target adds the month view for Westbrook at 110×40, twice: the hourly temperatures of the previous calendar month, as `--month` opens, and the same month as departures from the ten-year average, with the pointer on the afternoon of the 10th so that hour's chip is in the frame. The year target adds the pointer: termshot moves it onto the December solstice so the hover tooltip is in the frame. Its main frame is Reykjavík, in Icelandic, and the two polar frames are Longyearbyen and Vostok Station, at 78° either side of the equator.

The tides target makes five frames. Four are Portland, Maine: the day's curve, then the month, the year, and the view of what moves the tide there, each reached by pressing `v`. The year has the pointer on the middle of June 2026, where the highest water of the year passed the flood stage, so the chip with the predicted and the measured water is in the frame. The fifth is the last of those views for Tokyo, in Japanese, for `README.ja.md`. The year and the makeup wait about half a minute, since a year of highs and lows is a dozen requests when nothing is cached.

The three month frames in [About the tides](../docs/tides.md), `tides-month-portland.png`, `tides-month-quarry-bay.png`, and `tides-month-tokyo.png`, are not made by the script: the page describes October 2026, and the month view opens on the current month. They were drawn during that October with the same tool, at 100×38, from `linecast tides --month --station 8418150 --metric --24h` and the same for stations `QUB` and `jma:TK`.

The moon target also captures Okinawa in Japanese on the evening after the mid-autumn full moon of 2026, once as the disc (the night named 十六夜) and once after pressing `v`, with the pointer on the 25th so the calendar's hover chip reads 十五夜. Then it presses `t` for the Moon alone (`moon-alone.png`) and records `moon-spin.gif`: the pointer drags the Moon round and lets go, and it settles back to the face it really shows. The recording is kept as cells, so it is drawn twice, at 1× for the GIF, where the Moon's blocks land on whole pixels and compress well, and at 2× for `moon-spin.mp4`. The MP4s stay out of git: they are for editing, or for uploading to GitHub where a video is wanted.

The sky target is three fixed nights over Westbrook: Orion on a January evening, framed by `--at Orion`; the whole August sky at once, zoomed out with `-` until the view lies back and the horizon is a circle overhead (opening at `--fov 236` does not lie back, so the circle would sit off-centre); and the same January sky in the Hawaiian tradition. Then it records `sky-time.gif`: the same zoomed-out view, facing south so north is at the top, played forward with `p` at an hour a second from 3 p.m. on August 18, 2026, when a half Moon is up with the Sun, into the night.

The globe target is honestly unrepeatable by design: it makes two frames, the terrain planet with `S` pressed for this hour's daylight and city lights, and with `c` pressed as well for this hour's clouds, and then both again with the labels put away by `l` and the text by `t`. The last is what `--view now` opens on. The target reaches it by keys because `--view now` also sets the planet turning, and by the time the clouds arrive the sunset line has left the frame. By default it centres the view 45° east of wherever the sun is overhead at capture time, so the sunset line always crosses the right half of the disk; which continents are in the frame depends on the hour, so pick one you like or set `LINECAST_CAPTURE_GLOBE_PLACE` to a fixed `LAT,LNG`. Read both frames back before committing.

The desktops are composed by `scripts/capture_offscreen.py`, which runs every pane at once on one clock and tiles them the way Hyprland's dwindle layout does, on a 1920×1200 screen drawn at 2×. The hero follows the arrangement of Andrew's second desktop: the Westbrook weather over its year on the left; the radar over Portland on the right, above the Moon over Okinawa in Japanese and the year of daylight in Reykjavík in Icelandic. All five are live, so the hero is whatever the day is; run it when the weather and the Moon are worth it. `LINECAST_CAPTURE_RADAR_PLACE` moves its radar. There is no bar along the top, since there is no bar to draw; a hand-taken whole-screen screenshot, bar and all, is still the alternative, and still welcome.

The languages desktop is the second one: Montréal's weather in Canadian French; October in Reykjavík by the Icelandic calendar, with the pointer on the first day of winter; the Moon over Hilo by the Hawaiian calendar and over Okinawa in Japanese; and the January sky in the Hawaiian tradition, with the navigators' star compass along the horizon. Everything but the weather is a fixed moment.

The themes target records the hero desktop while the theme changes under it every two seconds, through ten of Omarchy's themes, light ones included. It does what `omarchy-theme-set` does to a running terminal: new colours at once, and the theme marker touched, so each app asks again and redraws in the new palette. The radar is paused so the GIF holds still between changes. The GIF cuts from one settled theme to the next, at 1×, the laptop's own screen pixel for pixel; `themes.mp4` keeps the half second in which each pane catches up. `scripts/capture_offscreen.py themes --themes gruvbox nord` picks the run.

The `tours` target records two GIFs for the gallery from mouse scripts in `scripts/tours`: the globe spun by dragging and the January sky panned. A script file takes the same words as the command line: `press`, `key`, `sleep`, `hover`, `click`, `drag`, `scroll`.

The default places can be overridden without editing the script:

```sh
LINECAST_CAPTURE_RADAR_PLACE="Tokyo, Japan" \
  scripts/capture_screenshots.sh radar hero

LINECAST_CAPTURE_TERRAIN_PLACE="Chamonix" \
  scripts/capture_screenshots.sh maps
```

Other overrides are listed by `scripts/capture_screenshots.sh --help`. Radar is the one frame that depends on the weather: by default the target asks `scripts/scout_radar.py` which of some sixty candidate cities inside real radar coverage has the most echo on it right now, and shoots there in that city's language. Run the scout on its own for the ranked table, or name a place with `LINECAST_CAPTURE_RADAR_PLACE`. Either way, read every PNG and the GIF back before committing. A completed command is not proof that the captured frame finished loading.

The radar GIF keeps one complete pass through LibreWXR's 18-frame window, with repeated frames removed. It plays at 2 fps, matching the animation in the terminal at the gallery size.
