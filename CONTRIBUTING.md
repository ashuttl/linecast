# Contributing to linecast

This is the practical companion to ARCHITECTURE.md. That file says
where the code lives and how the parts talk to each other; this one
says how to get a working copy running, what the shared pieces expect
of new code, and how a change travels from a commit to a release.

## Getting set up

Clone the repository and run everything through
[uv](https://docs.astral.sh/uv/); it is the one tool the project
assumes. There is nothing to install first; `uv run` makes the
environment on the first call.

```sh
git clone https://github.com/ashuttl/linecast
cd linecast
uv run --with pytest pytest tests -q
```

The suite runs in under ten seconds, reaches no network, and never
touches your home directory: `tests/conftest.py` points `HOME`, the
XDG directories and the two `LINECAST_*_DIR` variables at a temporary
tree before any test module is imported, clears every variable
linecast reads, and refuses every outbound connection at the socket.
Pytest is not a project dependency, which is why it arrives through
`--with`. The wheel claims Python 3.10 and up, and code that runs on
3.14 does not always run on 3.10; to try another interpreter, let uv
fetch it:

```sh
uv run --no-project --python 3.10 --with pytest --with-editable . pytest tests -q
```

The lint is ruff, configured under `[tool.ruff]` in `pyproject.toml`,
and CI runs the same command:

```sh
uvx ruff check src tests scripts
```

To run your working copy, put `uv run` in front of a command. If
linecast is installed as a uv tool, the installed commands keep
running the build they were installed from until you reinstall from
the checkout:

```sh
uv run linecast weather --print
uv run linecast doctor --offline
uv tool install --reinstall .
```

## How a command runs

Every command runs through the one console script (`[project.scripts]`
in `pyproject.toml`): `linecast weather` goes through `__main__.py` to
`main()` in the command's module, and a binary or alias named `weather`
reaches the same `main()` by argv[0] dispatch, so the two are one code
path.

`main()` does the same things in the same order in every command. It
parses arguments with the command's parser factory from `_runtime.py`
(`weather_parser()` and so on, all built on `_base_parser`, which is
where `--print`, `--lang` and `--debug` come from). It turns the
namespace into a frozen `RuntimeConfig` with `from_sources`, which
also switches debug logging on and writes the first line of the
transcript, and registers it with `set_current` so a render helper
deep in the call can ask `current_runtime()` for it. It resolves the
location with `_location.resolve_location`, which takes `--location`,
then `WEATHER_LOCATION`, then the saved location, then the IP lookup.
It fetches what it needs, usually in a thread pool behind a spinner.
Then it either prints one frame, for `--print`, `--json`, `--oneline`,
or whenever stdout is not a terminal, or it builds the command's
`LiveApp` and calls `run()`, which hands the terminal to
`_live.live_loop` until the user quits.

Stdout carries the frame and nothing else, so `--json` output can be
piped straight into another program. Stderr carries a sentence for
the user when the command cannot go on ("Could not determine
location.") and otherwise nothing at all unless `--debug` is on. The
one exception is the line after a live session in which a background
thread crashed: "linecast: a background task failed; run with --debug
for details". Anything else you want to say while a command runs goes
through `debug_log`, where it is silent by default.

## The shared parts

Each of these is one module, and each has one or two names a
contributor will actually call.

**HTTP.** Every request goes through `_http.fetch_bytes(url, headers,
timeout, limit)`. It keeps one open connection per host per thread,
attaches the User-Agent, follows redirects, and reads the body in
chunks against a hard size cap (8 MiB for JSON, 16 MiB otherwise).
`fetch_json` decodes; `fetch_json_cached(cache_file, max_age, url,
fallback=...)` and `fetch_bytes_cached` try a fresh cache file first,
then the network, then the stale file, then the fallback. A URL that
reaches the debug log goes through `_http.redact_url`, which keeps
scheme, host and path and drops the query string; use it for any URL
you log.

**Paths and cache.** `_paths.py` decides where files go, and nothing
else does: `cache_root()` and `config_root()` read the environment
each time they are called, and `cache_dir("maps", "tile.png")` is a
path under the cache root. On Linux the cache is
`$XDG_CACHE_HOME/linecast`, which is `~/.cache/linecast` by default;
on macOS it is `~/Library/Caches/linecast`, unless an older
`~/.cache/linecast` is there and the new directory is not.
`LINECAST_CACHE_DIR` and `LINECAST_CONFIG_DIR` override both, used
exactly as given. `_cache.write_cache` writes through a sibling temp
file and `os.replace`, so a reader never sees a torn file, and it is
best effort: a directory that cannot be written costs the next run a
refetch and never costs this run its answer. `read_cache(path,
max_age)` treats a file that is too old, missing or unreadable as a
miss; `read_stale` reads it regardless of age, for the fallback when
the network is down.

**Theme and colour.** `_theme.py` asks the terminal for its own
foreground, background and sixteen ANSI colours, and every palette in
the package is derived from the answer. A module that builds colours
at import registers a rebuild with `_theme.on_reload`, and the live
loop re-probes now and then so a theme switch re-inks the view in
place. `_color.py` turns an RGB triple into the escape code for what
the terminal supports (`fg`, `bg` and `color_mode`), honouring
`NO_COLOR`, `CLICOLOR` and `LINECAST_COLOR`; nothing else in the
package writes an escape code of its own.

**The live loop.** A view with keys subclasses `_live.LiveApp`,
overrides the hooks it needs (`render`, `on_action`, `on_wheel`,
`on_drag`, `on_click`, `intercept`, `text_mode`, `play_gate`) and
tunes the loop through class attributes (`interval`, `mouse`,
`scroll_step`, `auto_play`, `play_interval`). A hook you do not
override is not handed to the loop, so its defaults stay in force.
`render` returns a string; anything floating over it goes through
`_live.overlay(body, floating, motion=...)`. Background work never
draws: it changes state and calls `_live.nudge()`, which wakes the
loop for a repaint from any thread.

**Scenes.** `_scenes.py` holds what a view keeps between repaints. A
`Memo` is a bounded dictionary that answers or builds on the calling
thread. A `SceneCache` holds a view's worth of fetched data and, when
live, loads a miss in the background, answers `empty` so the frame
can say "loading", and nudges the loop when the data lands. A
`FetchHold` gates it, so a run of zoom taps repaints at once but only
the view you stop on reaches the network.

**Diagnostics.** `_runtime.debug_log(msg)` prints one line on stderr
when `--debug` is on and nothing otherwise.
`_runtime.log_failure(provider, operation, exc, url=None, fallback=None, trace=False)`
is the line every absorbed failure goes through, in the house style:

    <provider>: <operation> failed (<host>) -- <ExcType>: <message>; <fallback>

It shows only the host of the URL, redacts URLs quoted by the
exception, cuts the exception's first line at 120 characters, and
formats nothing at all with `--debug` off, so it
is safe to call from inside a tile pool. `_live.WorkerWatch` is the
`threading.excepthook` the live loop installs, so a crashed worker is
logged at once and reported once the terminal is the user's again.
`linecast doctor` (`doctor.py`) collects the same facts on demand and
probes every provider host; `doctor.providers()` is the list to
extend when you add one.

## Providers and graceful degradation

A provider is a function that talks to one service and returns data
the renderer can use. The contract has three parts. It returns a
documented fallback rather than raising: an empty list, `None`, the
stale cache. When it takes that fallback it calls `log_failure` with
its tag (`"tides/noaa"`, `"maps/vtiles"`, `"radar/iem"`; the tag is
`command/service`, and `"cache"`, `"http"` and `"worker"` are the
shared ones). And it never prints. The user sees a partial display, a
forecast without air quality or a map without terrain shading, and
the reason waits in the `--debug` transcript. A partial display beats
a crash.

Normalisation is the other half of the contract: every provider of
the same kind hands the renderer the same shape, so the renderer
knows nothing about which service answered. The eight alert sources
in `_weather_sources.py` each return a list of dicts with the keys
`event`, `headline`, `description`, `effective`, `expires`,
`severity` and `url`, whatever the service called them. The five tide
providers behind `_tides_providers.TideProvider` all return
`(datetime, height_ft)` points and `(datetime, height_ft, "H"/"L")`
extremes, in feet because that is what the NOAA pipeline was built
on; a metric source converts on the way in.

To add a provider, put it in its own `_<command>_<service>.py`, fetch
through `_http`, cache through `_cache` with a maximum age, and
return the documented fallback on every failure, logged with a new
tag in the same form. Register it beside its siblings (the provider
list in `_tides_providers.py`, the routing in `_radar_sources.py`,
the country table in `fetch_alerts`), add its host to
`doctor.providers()`, and name it in the README's data sources. In
the tests, save one real response under `tests/fixtures/`, stub the
fetch, and check both the normalised shape and the fallback when the
fetch raises.

## Tests

A test file covers one module or one concern and is named for it:
`tests/test_<module>.py`, so `_paths.py` is tested by
`tests/test_paths.py` and the debug contract by
`tests/test_diagnostics.py`. The live apps are tested as objects:
build a `MapApp` or `RadarApp` with the terminal size patched and
drive its hooks (`tests/test_maps_live.py`,
`tests/test_radar_live.py`). Key decoding is tested by writing bytes
to a pipe and reading them back through `_read_key`
(`tests/test_live_input.py`). `tests/snapshots/` holds rendered frames
for fixed data, sizes and clock; a missing snapshot is written on the
first run and compared on every run after. When you change how
something looks on purpose, delete the affected file, run the suite
once to regenerate it, and read the diff:

```sh
rm tests/snapshots/weather_120x40.txt
uv run --with pytest pytest tests/test_render_snapshots.py -q
git diff tests/snapshots
```

`tests/conftest.py` gives every test a private home: a cache
directory shared by the session (so the 7 MB basemap is built once),
a fresh config directory per test (so a saved location can never leak
between tests), every variable linecast reads cleared, and every
outbound connection refused. A test that genuinely needs the network
or the real home marks itself `@pytest.mark.integration`; pytest
leaves those out unless asked for them with `-m integration`, and the
CI job that runs the suite with a read-only `HOME` is there to keep
the rest hermetic.

The one integration file is `tests/test_live_providers.py`: a test per
provider that makes a real request and runs the reply through the
same code the commands use. `.github/workflows/live.yml` runs it once
a day and keeps an issue open while any provider is down or has
changed its feed. When you add a provider, add a live test for it
there as well as the fixture-backed tests.

A fetch is stubbed at the `_http` boundary and nowhere lower: patch
`fetch_json` or `fetch_bytes` where the module under test imported it
(`patch.object(_location, "fetch_json", return_value=payload)`), or
patch `_http.fetch_bytes` itself, and hand back a fixture. Keep the
suite fast; it runs on every push on every supported interpreter, and
a test that sleeps or waits on a timer is a test someone will soon
skip.

## Commits and the changelog

A commit subject is `Area: what changed`, stated plainly: "Radar:
prune cached frames older than a day", "Paths: one module decides
where the cache and the config live". The area is the command or the
shared part the change belongs to. The subject carries the fact; the
body, when there is one, carries the mechanism and the reasoning.

A change the user can see gets one bullet under **Unreleased** in
`CHANGELOG.md`, in the same style: one or two sentences on what the
user gets, not how it was done, not the timings, not the file names.
"Maps: Fixed a bug that could have caused rendering the globe to fail
until the user interacted with it." The bullet is a draft; the
maintainer edits the notes at release time, so keep it factual and do
not labour the wording. Pull requests are welcome. Keep one coherent
change per commit, and expect the maintainer to reword subjects and
notes on merge.

Releases are the maintainer's. `./release.sh [major|minor|patch]`
takes the Unreleased notes, opens them for a final pass, bumps the
version, moves them under a dated heading, commits, tags, pushes and
creates the GitHub Release. The tag runs the full test workflow
again, including the wheel build checked by `scripts/check_dist.sh`
and the `scripts/smoke_wheel.sh` and `scripts/check_get_sh.sh` runs
against the built wheel, and `publish.yml` then sends that same wheel
to PyPI, byte for byte. Homebrew follows with
`./release-homebrew.sh <version>` once PyPI has it.

## Packaging for a distribution

The wheel installs one command: `linecast`. The short names
(`weather`, `sunshine`, `moon`, `tides`, `radar`, `maps`) are common
words, and on some systems one of them is already taken —
`/usr/bin/sunshine` belongs to the Sunshine streaming server on a
machine that has it, and a package that ships the file anyway cannot
be installed there at all (issue #20). So the wheel ships none of
them, and `scripts/smoke_wheel.sh` fails if one creeps back in.

The `linecast` binary answers to the name it is invoked by: a symlink
to it called `weather` runs the weather command, arguments untouched.
So a distribution package may ship any of the short commands as
symlinks where its ecosystem allows, and a user may make their own
symlink or shell alias (`linecast link` makes the six of them, and
skips any name another program owns). Every command stays reachable
as `linecast <command>`, so a short name left out costs the short
spelling and nothing else.

Two things a package should not do: rename the commands to something
of its own, and declare the short names as provided or virtual
packages — linecast is not a substitute for another program that
happens to share a name.

## Why there are no dependencies

linecast has no runtime dependencies, and a pull request that adds
one will be asked to take it out. There are three reasons.

Startup. A command should draw in well under 100 ms of Python.
Importing `linecast.weather` costs about 30 ms on top of the
interpreter, and the modules a command does not need on every run are
imported inside the function that needs them. A dependency that
imports at startup is paid on every run of every command, and a
status bar that calls `linecast moon --oneline` once a minute notices.

Installability. `get.sh` runs linecast on a machine with nothing but
`python3`, installing the package into a small venv of its own;
`uvx linecast`, `pipx run linecast`, the Homebrew formula and the AUR
package all resolve the same wheel. A pure-Python wheel with no
dependencies installs everywhere the interpreter runs, needs no
compiler, and has no version to conflict with anything else the user
has. The curl quick start at the top of the README depends on this
staying true, and the Homebrew formula and the AUR package would each
have to carry any list of dependencies by hand.

Owning the code. Everything that runs is in `src/linecast/`, which
means everything that runs can be read, tested and fixed in one
place. The PNG decoder, the vector tile decoder, the astronomical
equations and the HTTP client are all here, each a few hundred lines,
each doing exactly what one program needs.

When you are tempted, do one of two things. If the function you want
is small, vendor it: write the fifty lines linecast needs, with a
comment saying where the idea came from, and test them. If it is not
small (a real parser, a format that will keep changing), open an
issue and make the case.
