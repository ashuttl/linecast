# Refreshing the gallery

One file here is not a capture: `minitel-terminatel-258.jpg` is a period
photograph from [minitel-alcatel.fr](https://www.minitel-alcatel.fr/),
credited in the main README's Lineage section. Leave it be.

The README gallery is captured from linecast's live terminal UI with
[`termshot`](https://github.com/ashuttl/dotfiles-omarchy/tree/main/termshot).
It renders each app in a private headless sway at 2× density, with the desktop's border colour and wallpaper borrowed for the frame, so refreshing the gallery never moves, resizes, or focuses anything on the real desktop, and never borrows the pointer or the keyboard. Every frame is set in one typeface, `LINECAST_CAPTURE_FONT`, so the gallery does not follow whatever font the desktop terminal happens to be using.

From the repository root:

```sh
scripts/capture_screenshots.sh all
```

Individual targets are also available:

```sh
scripts/capture_screenshots.sh weather sunshine year moon sky tides radar maps globe gallery hero
```

The `gallery` target fills `screenshots/gallery/` with the frames [the gallery](../docs/gallery.md) shows and the README does not: the radar in its fixed themes and its satellite and condition layers, the sky in more traditions, the weather in a short window, the moon's month grid, terrain over Cook Strait and the Alps, a continent under the hour's clouds (centred where it is mid-afternoon at capture time, like the globe), and a walking route. The maps target itself makes the README's street and terrain frames, the terrain over New Zealand for its seafloor, and the five-zoom series over Portland that the README shows three of. The README's own frames stay in this directory; a new state belongs in the gallery target and on the gallery page, not in the README, unless it earns a place there.

Weather, tides, radar, and maps use current public data. Sunshine, Moon, and sky use fixed local moments through `scripts/capture_moment.py`, keeping those frames repeatable at any time of day. The weather target makes three frames: Dublin at 110×34, where the dashboard is at its densest, and two smaller ones, Reykjavík in Icelandic and Kyoto in Japanese, both metric. The year target adds the pointer: termshot moves it onto the December solstice so the hover tooltip is in the frame. Its main frame is Reykjavík, in Icelandic, and the two polar frames are Longyearbyen and Vostok Station, at 78° either side of the equator.
The moon target also captures Okinawa in Japanese on the evening after the
mid-autumn full moon of 2026, once as the disc (the night named 十六夜) and
once after pressing `v`, with the pointer on the 25th so the calendar's hover
chip reads 十五夜.

The sky target is three fixed nights over Westbrook: Orion on a January evening, framed by `--at Orion`; the whole August sky at once at the widest field of view; and the same January sky in the Hawaiian tradition.

The globe target is honestly unrepeatable by design: it makes two frames, the terrain planet with `S` pressed for this hour's daylight and city lights, and `--view now` with this hour's clouds as well. By default it centres the view 45° east of wherever the sun is overhead at capture time, so the sunset line always crosses the right half of the disk; which continents are in the frame depends on the hour, so pick one you like or set `LINECAST_CAPTURE_GLOBE_PLACE` to a fixed `LAT,LNG`. Read both frames back before committing.

The hero is a composed desktop the size of this laptop's screen: five apps tiled two above three by termshot's private compositor, with the real bar read off the real screen and pasted along the top, so the frame carries the real clock and workspace dots. Weather and radar are live and the radar goes wherever the scout finds weather; the moon, the year, and the dusk are fixed moments. `LINECAST_CAPTURE_HERO_PLACE` and `LINECAST_CAPTURE_HERO_LOCATION` move it; Juneau is the default. Because it composes rather than photographs, `all` still leaves it alone; run `hero` when the weather is worth it. A hand-taken whole-screen screenshot is still the alternative, and still welcome.

The `tours` target records two GIFs for the gallery from mouse scripts in `scripts/tours`: the globe spun by dragging and the January sky panned. termshot reads the same words from a script file as it takes on the command line: `press`, `key`, `sleep`, `hover`, `click`, `drag`, `scroll`.

The default places can be overridden without editing the script:

```sh
LINECAST_CAPTURE_RADAR_PLACE="Tokyo, Japan" \
  scripts/capture_screenshots.sh radar hero

LINECAST_CAPTURE_TERRAIN_PLACE="Chamonix" \
  scripts/capture_screenshots.sh maps
```

Other overrides are listed by `scripts/capture_screenshots.sh --help`. Radar is the one frame that depends on the weather: by default the target asks `scripts/scout_radar.py` which of some sixty candidate cities inside real radar coverage has the most echo on it right now, and shoots there in that city's language. Run the scout on its own for the ranked table, or name a place with `LINECAST_CAPTURE_RADAR_PLACE`. Either way, read every PNG and the GIF back before committing. A completed command is not proof that the captured frame finished loading.

The radar GIF capture oversamples the live terminal, removes repeated screen
states, and keeps one complete pass through LibreWXR's 18-frame window. The
final GIF plays at 2 fps, matching the animation's observed terminal cadence
at the gallery size rather than its faster nominal timer.
