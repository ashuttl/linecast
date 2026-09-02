#!/bin/sh
# Open an issue when the Western Pacific council publishes a new
# year's lunar calendars.
#
# Usage: edition_watch.sh
#
# Needs gh, GH_TOKEN and GH_REPO in the environment (the workflow sets
# them). The newest edition the tests pin is LATEST_EDITION in
# tests/test_pacific.py; the council's page lists each year's PDFs
# under a "YYYY Lunar Calendars" heading. When the page shows a later
# year than the tests know, one issue is opened for it, once. The
# issue closes by hand; bumping LATEST_EDITION is what stops the
# script from noticing that year again.
set -eu

page=https://www.wpcouncil.org/educational-resources/lunar-calendars/
label=lunar-calendars

known=$(sed -n 's/^LATEST_EDITION = \([0-9][0-9]*\).*/\1/p' tests/test_pacific.py)
if [ -z "$known" ]; then
    echo "LATEST_EDITION not found in tests/test_pacific.py" >&2
    exit 1
fi

# The site answers 403 to a bare fetcher; a browser's User-Agent gets the page.
newest=$(curl -fsSL --max-time 60 \
             -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36" \
             "$page" \
         | grep -oE '<h[1-6][^>]*>[[:space:]]*[0-9]{4} Lunar Calendars' \
         | grep -oE '[0-9]{4}' | sort -n | tail -1)
if [ -z "$newest" ]; then
    echo "no 'YYYY Lunar Calendars' heading on $page; has the page changed shape?" >&2
    exit 1
fi

echo "page lists editions through $newest; tests pin through $known"
if [ "$newest" -le "$known" ]; then
    exit 0
fi

title="Pin the $newest lunar calendars"
existing=$(gh issue list --search "\"$title\" in:title" --state all --limit 1 \
           --json number,title --jq ".[] | select(.title == \"$title\") | .number")
if [ -n "$existing" ]; then
    echo "#$existing already covers the $newest editions"
    exit 0
fi

body_file=$(mktemp)
{
    echo "The council has published its $newest lunar calendars: $page"
    echo
    echo "The Pacific calendars derive each first night from crescent visibility, and the tests check them against every month the council prints. The new edition's months belong in \`tests/test_pacific.py\`: \`PUBLISHED_MONTHS\` from the Hawaiʻi classroom PDF, \`SAMOAN_MONTHS\` from the American Samoa one, and \`MARIANAS_MONTHS\` from the Guam or CNMI one (they print the same dates); then bump \`LATEST_EDITION\` there. If a month disagrees with the engine, the cutoff is what to recalibrate — the docstring of \`src/linecast/_pacific.py\` says how."
    echo
    echo "Opened by the scheduled edition watch. It will not open another issue for $newest."
} > "$body_file"

gh label create "$label" --color 0e8a16 \
    --description "A new year of WPRFMC lunar calendars is out" --force
gh issue create --title "$title" --label "$label" --body-file "$body_file"
echo "opened an issue for the $newest editions"
