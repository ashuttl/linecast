#!/usr/bin/env bash
set -euo pipefail

# Usage: ./release-homebrew.sh <version>
# Example: ./release-homebrew.sh 1.0.8

VERSION="${1:?Usage: $0 <version>}"
TAG="v$VERSION"

# GNU sed wants -i, BSD/macOS sed wants -i '' — releases happen from both
sed_i() {
  if sed --version >/dev/null 2>&1; then sed -i "$@"; else sed -i '' "$@"; fi
}
LINECAST_DIR="$(cd "$(dirname "$0")" && pwd)"
HOMEBREW_DIR="$LINECAST_DIR/../homebrew-linecast"

PYPI_API="https://pypi.org/pypi/linecast/${VERSION}/json"

echo "Fetching linecast $VERSION from PyPI..."
JSON=$(curl -sf "$PYPI_API") || { echo "Version $VERSION not found on PyPI."; exit 1; }

PYPI_URL=$(echo "$JSON" | python3 -c "import sys,json; urls=json.load(sys.stdin)['urls']; print(next(u['url'] for u in urls if u['packagetype']=='sdist'))")
SHA256=$(echo "$JSON" | python3 -c "import sys,json; urls=json.load(sys.stdin)['urls']; print(next(u['digests']['sha256'] for u in urls if u['packagetype']=='sdist'))")

echo "URL: $PYPI_URL"
echo "SHA256: $SHA256"

# releases can come from any machine: sync the tap before editing the
# formula so the push below can't be rejected as non-fast-forward
git -C "$HOMEBREW_DIR" pull --rebase origin main

FORMULA="$HOMEBREW_DIR/Formula/linecast.rb"
sed_i "s|url \".*\"|url \"$PYPI_URL\"|" "$FORMULA"
sed_i "s|sha256 \".*\"|sha256 \"$SHA256\"|" "$FORMULA"

cd "$HOMEBREW_DIR"
git add Formula/linecast.rb
git commit -m "linecast $TAG"
git push origin main

echo "Done! Homebrew tap updated for linecast $TAG"
