#!/usr/bin/env bash
set -euo pipefail

# Usage: ./release.sh [major|minor|patch]
# Default: patch
#
# Release notes come from the Unreleased section of CHANGELOG.md.
# The script opens them in $EDITOR for a final pass, then bumps the
# version, moves the notes under a dated heading, commits, tags
# (notes become the tag message), pushes, and creates a GitHub
# Release. CI publishes to PyPI on the tag.

BUMP="${1:-patch}"
LINECAST_DIR="$(cd "$(dirname "$0")" && pwd)"

# Releases are cut from main: the script pushes main and tags it.
BRANCH=$(git -C "$LINECAST_DIR" branch --show-current)
if [ "$BRANCH" != "main" ]; then
  echo "On branch '$BRANCH'. Merge to main first, then release from there."
  exit 1
fi
CHANGELOG="$LINECAST_DIR/CHANGELOG.md"

# GNU sed wants -i, BSD/macOS sed wants -i '' — releases happen from both
sed_i() {
  if sed --version >/dev/null 2>&1; then sed -i "$@"; else sed -i '' "$@"; fi
}

# --- 1. Collect notes from the Unreleased section ---
NOTES_FILE=$(mktemp)
trap 'rm -f "$NOTES_FILE"' EXIT

awk '/^## Unreleased/{grab=1; next} /^## /{grab=0} grab' "$CHANGELOG" \
  | sed -e '/[^[:space:]]/,$!d' > "$NOTES_FILE"

if ! grep -q '[^[:space:]]' "$NOTES_FILE"; then
  echo "Nothing under Unreleased in CHANGELOG.md. Write the notes first."
  exit 1
fi

# --- 2. Compute the new version ---
CURRENT=$(grep '^version' "$LINECAST_DIR/pyproject.toml" | sed 's/version = "\(.*\)"/\1/')
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

case "$BUMP" in
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  patch) PATCH=$((PATCH + 1)) ;;
  *) echo "Usage: $0 [major|minor|patch]"; exit 1 ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"
TAG="v$NEW_VERSION"

# --- 3. Final pass on the notes ---
if [ -t 0 ] && [ -t 1 ]; then
  echo "Opening notes for $TAG in ${EDITOR:-vi}. Save and quit to release."
  ${EDITOR:-vi} "$NOTES_FILE"
  if ! grep -q '[^[:space:]]' "$NOTES_FILE"; then
    echo "Notes emptied — release aborted. CHANGELOG.md is untouched."
    exit 1
  fi
fi

echo "Bumping $CURRENT -> $NEW_VERSION"
sed_i "s/^version = \".*\"/version = \"$NEW_VERSION\"/" "$LINECAST_DIR/pyproject.toml"

# --- 4. Move the notes under a dated heading in the changelog ---
python3 - "$CHANGELOG" "$NOTES_FILE" "$NEW_VERSION" <<'EOF'
import datetime, re, sys

changelog, notes_path, version = sys.argv[1:4]
text = open(changelog).read()
notes = open(notes_path).read().strip()
today = datetime.date.today().isoformat()

section = f"## Unreleased\n\n## {version} — {today}\n\n{notes}\n\n"
text, n = re.subn(r"## Unreleased\n(.*?)(?=^## |\Z)", section,
                  text, count=1, flags=re.S | re.M)
if n != 1:
    sys.exit("No '## Unreleased' heading in CHANGELOG.md")
open(changelog, "w").write(text)
EOF

# --- 5. Sync the lockfile so it never trails the tag ---
cd "$LINECAST_DIR"
if command -v uv >/dev/null 2>&1; then
  uv lock --quiet
fi

# --- 6. Commit, tag with the notes, push, publish the release ---
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "$TAG"
git tag -a "$TAG" -F "$NOTES_FILE"
git push origin main "$TAG"

gh release create "$TAG" --title "$TAG" --notes-file "$NOTES_FILE"

echo "Pushed $TAG and published its GitHub Release. CI will publish to PyPI."
echo "Homebrew follows on its own: BrewTestBot bumps homebrew/core from PyPI."
