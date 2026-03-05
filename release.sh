#!/usr/bin/env bash
set -euo pipefail

# Usage: ./release.sh [major|minor|patch]
# Default: patch

BUMP="${1:-patch}"
LINECAST_DIR="$(cd "$(dirname "$0")" && pwd)"
HOMEBREW_DIR="$LINECAST_DIR/../homebrew-linecast"

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

echo "Pushed $TAG — waiting for PyPI publish..."

# --- 3. Wait for GitHub Action to succeed ---
# Give GH Actions a moment to pick up the tag
sleep 5

RUN_ID=$(gh run list --workflow=publish.yml --limit=1 --json databaseId --jq '.[0].databaseId')
echo "Watching run $RUN_ID..."
gh run watch "$RUN_ID" --exit-status

echo "PyPI publish succeeded."

# --- 4. Wait for PyPI to serve the new sdist ---
PYPI_URL="https://files.pythonhosted.org/packages/source/l/linecast/linecast-${NEW_VERSION}.tar.gz"
echo "Waiting for $PYPI_URL to become available..."

for i in $(seq 1 30); do
  HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "$PYPI_URL")
  if [ "$HTTP_CODE" = "200" ]; then
    echo "Package is live on PyPI."
    break
  fi
  if [ "$i" = "30" ]; then
    echo "Timed out waiting for PyPI. You may need to update homebrew manually."
    exit 1
  fi
  sleep 10
done

# --- 5. Compute sha256 ---
SHA256=$(curl -sL "$PYPI_URL" | shasum -a 256 | awk '{print $1}')
echo "SHA256: $SHA256"

# --- 6. Update homebrew formula ---
FORMULA="$HOMEBREW_DIR/Formula/linecast.rb"
sed -i '' "s|url \".*\"|url \"$PYPI_URL\"|" "$FORMULA"
sed -i '' "s|sha256 \".*\"|sha256 \"$SHA256\"|" "$FORMULA"

echo "Updated homebrew formula."

# --- 7. Commit and push homebrew tap ---
cd "$HOMEBREW_DIR"
git add Formula/linecast.rb
git commit -m "linecast $TAG"
git push origin main

echo "Done! Released linecast $TAG"
