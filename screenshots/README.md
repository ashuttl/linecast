# Refreshing the gallery

The README gallery is captured from linecast's live terminal UI with
[`termshot`](https://github.com/ashuttl/dotfiles-omarchy/tree/main/termshot).
It renders each app on a temporary offscreen Hyprland monitor at 2× density,
so refreshing the gallery does not move, resize, or focus anything on the real
desktop.

From the repository root:

```sh
scripts/capture_screenshots.sh all
```

Individual targets are also available:

```sh
scripts/capture_screenshots.sh weather sunshine moon tides radar maps hero
```

Weather, tides, radar, and maps use current public data. Sunshine and Moon use
fixed local moments through `scripts/capture_moment.py`, keeping those frames
repeatable at any time of day.

The current hero is not from the script at all: it is a hand-composed
whole-laptop-screen screenshot — weather, dusk sunshine, tides, and radar
tiled on the real desktop, bar and all — taken live and kept deliberately
uncropped. For that reason `all` skips the hero. Running the `hero` target
explicitly *overwrites* it with an auto-capture: four apps tiled by Hyprland
on the offscreen monitor (termshot's `--pane` mode), where the compositor's
own gaps and borders do the alignment. Its long settle gives the full-height
radar pane time to load all 18 animation frames — at that size
"loading… n/18" lingers in its header well past a minute.

The default places can be overridden without editing the script:

```sh
LINECAST_CAPTURE_RADAR_PLACE="Tokyo, Japan" \
  scripts/capture_screenshots.sh radar hero

LINECAST_CAPTURE_TERRAIN_PLACE="Chamonix" \
  scripts/capture_screenshots.sh maps
```

Other overrides are listed by `scripts/capture_screenshots.sh --help`. Radar is
the one frame worth art-directing each time: choose somewhere with active echo,
then read every PNG and the GIF back before committing. A completed command is
not proof that the captured frame finished loading.

The radar GIF capture oversamples the live terminal, removes repeated screen
states, and keeps one complete pass through LibreWXR's 18-frame window. The
final GIF plays at 2 fps, matching the animation's observed terminal cadence
at the gallery size rather than its faster nominal timer.
