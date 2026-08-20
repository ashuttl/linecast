# linecast

## Commit messages and release notes

Andrew writes these himself, or edits them before they ship. When
committing on his behalf:

- Subject line: `Area: what changed`, stated plainly. "Radar: prune
  cached frames older than a day" — not wordplay, not a line that
  winks at itself. E.B. White is the model: direct and spare. The
  poetry is in what goes unsaid.
- Leave commits unpushed unless asked, so messages can still be
  reworded with `git commit --amend`.
- When a change is user-visible, add a bullet to the Unreleased
  section of CHANGELOG.md in the same plain style. Andrew edits the
  notes at release time; the bullet is a draft, so keep it factual.

## Releases

Andrew runs `./release.sh [major|minor|patch]` himself — it opens his
editor. It takes the Unreleased notes, gives them a final pass, bumps
the version, moves them under a dated heading, commits, tags (the
notes become the annotated tag message), pushes, and creates the
GitHub Release. CI publishes to PyPI on the tag. Homebrew follows
with `./release-homebrew.sh <version>` once PyPI is live.
