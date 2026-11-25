#!/bin/sh
# Keep one GitHub issue in step with the live provider check.
#
# Usage: live_issue.sh <pytest exit status> <report file> [<earlier report file>]
#
# Needs gh, GH_TOKEN, GH_REPO, and RUN_URL in the environment (the
# workflow sets them); EARLIER_URL, when set, links the earlier run.
#
# Most failures are a provider's bad morning and are gone by the next
# day, so a test counts as failing only when it also failed in the
# earlier report, which the workflow takes from a run a day or so
# before. A first failure is a warning on the run and nothing more.
#
# One issue carrying the live-check label is open while any test is
# failing in that sense, titled with what is failing, and closed once
# none is. While it stays open it is only touched when the set of
# failing tests changes, so a week-long outage is one issue with a few
# comments, not seven issues or seven identical comments. A reason
# that changes from day to day ("310 areas", "340 areas") is not a
# change in the set.
#
# Writes failing=<count> to $GITHUB_OUTPUT when that is set.
set -eu

status=$1
report=$2
earlier=${3:-}
label=live-check

failed_lines() {
    # "FAILED tests/test_live_providers.py::test_x - reason" lines, the
    # path dropped; pytest prints them under -rfE.
    grep -E '^(FAILED|ERROR) ' "$1" | sed 's#tests/test_live_providers.py::##' | sort -u || true
}

ids() {
    # "FAILED test_x[param] - reason" -> "test_x[param]"
    sed -E 's/^(FAILED|ERROR) //; s/ - .*$//'
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

failed_lines "$report" > "$work/now"
if [ "$status" -ne 0 ] && [ ! -s "$work/now" ]; then
    # pytest failed without naming a test: it could not start or collect
    echo "FAILED (no test ran) - pytest exited with status $status" > "$work/now"
fi

: > "$work/earlier_ids"
if [ -n "$earlier" ] && [ -r "$earlier" ]; then
    failed_lines "$earlier" | ids > "$work/earlier_ids"
fi

# again: failed now and in the earlier report.  first: failed only now.
: > "$work/again"
: > "$work/first"
while IFS= read -r line; do
    id=$(printf '%s\n' "$line" | ids)
    if grep -qxF -- "$id" "$work/earlier_ids"; then
        printf '%s\n' "$line" >> "$work/again"
    else
        printf '%s\n' "$line" >> "$work/first"
    fi
done < "$work/now"

failing=$(grep -c '' "$work/again" || true)
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "failing=$failing" >> "$GITHUB_OUTPUT"
fi

while IFS= read -r line; do
    echo "::warning title=Failed once::$line"
done < "$work/first"

issue=$(gh issue list --label "$label" --state open --limit 1 \
        --json number --jq '.[0].number // empty')

if [ "$failing" -eq 0 ]; then
    if [ -n "$issue" ]; then
        if [ -s "$work/first" ]; then
            said="What was failing answered on [this run]($RUN_URL). Closing."
        else
            said="Every provider answered on [this run]($RUN_URL). Closing."
        fi
        gh issue comment "$issue" --body "$said"
        gh issue close "$issue"
        echo "closed #$issue"
    elif [ -s "$work/first" ]; then
        echo "failed once; no issue until it fails again a day on"
    else
        echo "all green, no issue open"
    fi
    exit 0
fi

# "Live check failing: photon_search and 2 more"
name=$(ids < "$work/again" | sed -n '1s/^test_//p')
[ -n "$name" ] || name=$(ids < "$work/again" | sed -n 1p)
title="Live check failing: $name"
if [ "$failing" -gt 1 ]; then
    title="$title and $((failing - 1)) more"
fi

# -k 'test_alerts or test_photon_search': the functions, parameters dropped
only=$(ids < "$work/again" | sed 's/\[.*$//' | grep '^test_' | sort -u \
       | awk 'NR > 1 { printf " or " } { printf "%s", $0 }' || true)

if [ -n "${EARLIER_URL:-}" ]; then
    before="[the one a day before]($EARLIER_URL)"
else
    before="the one a day before"
fi

body_file="$work/body"
{
    echo "Failed on [this run]($RUN_URL) and on $before:"
    echo
    echo '```'
    cat "$work/again"
    echo '```'
    if [ -s "$work/first" ]; then
        echo
        echo "Failed on this run for the first time, and not yet counted:"
        echo
        echo '```'
        cat "$work/first"
        echo '```'
    fi
    echo
    if [ -n "$only" ]; then
        echo "To reproduce: \`pytest tests/test_live_providers.py -m integration -k '$only'\`"
    else
        echo "To reproduce: \`pytest tests/test_live_providers.py -m integration\`"
    fi
    echo
    echo "A test is reported once it has failed on two runs a day apart. This issue is updated when the set of failing tests changes and closed when they pass."
} > "$body_file"

if [ -z "$issue" ]; then
    gh label create "$label" --color d93f0b \
        --description "Opened by the scheduled live provider check" --force
    gh issue create --title "$title" --label "$label" --body-file "$body_file"
    echo "opened an issue"
    exit 0
fi

# The last report is the newest comment, or the body when there is
# none; the failing tests are its first code block.
last=$(gh issue view "$issue" --json body,comments \
       --jq 'if (.comments | length) > 0 then .comments[-1].body else .body end')
printf '%s\n' "$last" | awk '/^```$/ { n++; next } n == 1' | ids | sort -u > "$work/reported"
ids < "$work/again" | sort -u > "$work/again_ids"
if cmp -s "$work/reported" "$work/again_ids"; then
    echo "#$issue already reports these failures"
    exit 0
fi
gh issue comment "$issue" --body-file "$body_file"
gh issue edit "$issue" --title "$title"
echo "updated #$issue"
