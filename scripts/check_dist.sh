#!/bin/sh
# Check that a built distribution carries linecast's data files.
#
# Usage:
#   scripts/check_dist.sh <dist-dir>
#
# The directory must hold exactly one wheel and one sdist. The wheel
# must carry the five files under linecast/data, and the sdist the same
# five under src/linecast/data plus the test snapshots. The data files
# are what the globe, the climate colours, the radar basemap, and the
# MeteoAlarm alert regions draw from; a wheel without them installs
# cleanly and then fails on first use, which is why CI runs this on
# every build. Run it by hand after
# `uv build --out-dir <dir>` to check a local build the same way.

set -u

dist=${1:?usage: check_dist.sh <dist-dir>}
data="basemap.json.gz climate.png globe_canvas_1.bin globe_canvas_2.bin meteoalarm_regions.bin.gz"
status=0

fail() {
    echo "check_dist: $*" >&2
    status=1
}

count() {
    n=0
    for f in "$@"; do
        [ -e "$f" ] && n=$((n + 1))
    done
    echo "$n"
}

[ -d "$dist" ] || { echo "check_dist: $dist is not a directory" >&2; exit 1; }

if [ "$(count "$dist"/*.whl)" -ne 1 ]; then
    fail "expected exactly one wheel in $dist"
fi
if [ "$(count "$dist"/*.tar.gz)" -ne 1 ]; then
    fail "expected exactly one sdist in $dist"
fi
[ "$status" -eq 0 ] || exit "$status"

wheel=$(echo "$dist"/*.whl)
sdist=$(echo "$dist"/*.tar.gz)

# unzip -l prints "size date time name"; the awk keeps the size check
# and the exact-name match in one place.
wheel_listing=$(unzip -l "$wheel") || fail "could not list $wheel"
for name in $data; do
    if ! echo "$wheel_listing" | awk -v want="linecast/data/$name" \
            '$NF == want && $1 > 0 { found = 1 } END { exit !found }'; then
        fail "wheel is missing linecast/data/$name (or it is empty)"
    fi
done

# The sdist's members sit under a linecast-<version>/ prefix.
sdist_listing=$(tar tzf "$sdist") || fail "could not list $sdist"
for name in $data; do
    if ! echo "$sdist_listing" | grep -q "^[^/]*/src/linecast/data/$name\$"; then
        fail "sdist is missing src/linecast/data/$name"
    fi
done
if ! echo "$sdist_listing" | grep -q '^[^/]*/tests/snapshots/.*\.txt$'; then
    fail "sdist is missing tests/snapshots/"
fi

if [ "$status" -eq 0 ]; then
    echo "check_dist: ok: $(basename "$wheel") and $(basename "$sdist") carry the data"
fi
exit "$status"
