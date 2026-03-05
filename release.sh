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
# Wait for GH Actions to pick up the tag (filter for non-completed runs to avoid stale matches)
for i in $(seq 1 30); do
  RUN_ID=$(gh run list --workflow=publish.yml --branch="$TAG" --limit=1 --json databaseId,status \
    --jq '[.[] | select(.status == "queued" or .status == "in_progress")][0].databaseId // empty')
  if [ -n "$RUN_ID" ]; then
    break
  fi
  if [ "$i" = "30" ]; then
    echo "Timed out waiting for GitHub Actions to start. Check manually."
    exit 1
  fi
  sleep 5
done

echo "Watching run $RUN_ID..."
gh run watch "$RUN_ID" --exit-status

echo "PyPI publish succeeded."

# --- 4. Get download URL and sha256 from PyPI JSON API ---
PYPI_API="https://pypi.org/pypi/linecast/${NEW_VERSION}/json"
echo "Waiting for PyPI to index version $NEW_VERSION..."

for i in $(seq 1 30); do
  RESPONSE=$(curl -s -w '\n%{http_code}' "$PYPI_API")
  HTTP_CODE=$(echo "$RESPONSE" | tail -1)
  if [ "$HTTP_CODE" = "200" ]; then
    JSON=$(echo "$RESPONSE" | sed '$d')
    PYPI_URL=$(echo "$JSON" | python3 -c "import sys,json; urls=json.load(sys.stdin)['urls']; print(next(u['url'] for u in urls if u['packagetype']=='sdist'))")
    SHA256=$(echo "$JSON" | python3 -c "import sys,json; urls=json.load(sys.stdin)['urls']; print(next(u['digests']['sha256'] for u in urls if u['packagetype']=='sdist'))")
    echo "Package is live on PyPI."
    break
  fi
  if [ "$i" = "30" ]; then
    echo "Timed out waiting for PyPI. You may need to update homebrew manually."
    exit 1
  fi
  sleep 10
done

echo "URL: $PYPI_URL"
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
