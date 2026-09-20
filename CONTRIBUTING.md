# Contributing

Questions, requests, and ideas are welcome in [Discussions](https://github.com/ashuttl/linecast/discussions). Pull requests are very welcome for contained changes: a new data provider, an improvement to a view, a bug fix. Larger contributions are welcome too, but for those, start a discussion before you write code. Every view here was found slowly, and a new view or command needs that same care from the start, which is hard to give a pull request that arrives finished. [docs/architecture.md](docs/architecture.md) is the map of the code.

## Branches

`main` is the released version. It moves only when a release is cut, and it matches the latest tag on PyPI and Homebrew.

`next` is where the next release collects. Base your branch on `next` and open your pull request against `next`. A pull request against `main` is missing everything since the last release and will not merge cleanly.

```sh
git fetch origin next
git checkout -b my-change origin/next
```

The exception is a fix that cannot wait for the next release. For that, branch from `main`, make the fix there, and merge it back into `main`, where it ships as a patch release. The fix then needs to reach `next` as well, by a separate merge, or the next release will lose it. That is the path for urgent fixes only. A bug that can wait is fixed on `next` like everything else.

## Before you open a pull request

Run the tests and the lint. Both work without the network and without touching your home directory.

```sh
uv run --with pytest pytest tests -q
uvx ruff check src tests scripts
```

The render tests compare each view against a snapshot in `tests/snapshots`. If your change is meant to alter what a view draws, delete the affected snapshot and run the tests again to write a new one, then read the diff.

## Changelog and commit messages

If a user would notice the change, add a bullet under **Unreleased** in CHANGELOG.md, in the style of the ones around it: the area, a colon, and one or two sentences on what the user gets. Not how it was done. The mechanism belongs in the commit body. The notes get a final edit at release time, so a plain draft is fine.

Commit subjects read `Area: what changed`. "Maps: keep the map on screen while the next street view loads."

Prose in the markdown files is not hard-wrapped. One paragraph is one line.

## Releases

A release merges `next` into `main` and runs `release.sh` there. Contributors do not need to touch any of this.
