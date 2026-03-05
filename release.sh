#!/usr/bin/env bash
set -euo pipefail

# Usage: ./release.sh [major|minor|patch]
# Default: patch

BUMP="${1:-patch}"
LINECAST_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- 1. Bump version in pyproject.toml ---
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

echo "Bumping $CURRENT -> $NEW_VERSION"

sed -i '' "s/^version = \".*\"/version = \"$NEW_VERSION\"/" "$LINECAST_DIR/pyproject.toml"

# --- 2. Commit, tag, and push ---
cd "$LINECAST_DIR"
git add pyproject.toml
git commit -m "$TAG"
git tag "$TAG"
git push origin main "$TAG"

echo "Pushed $TAG. GitHub Actions will publish to PyPI."
echo "Once live, run: ./release-homebrew.sh $NEW_VERSION"
