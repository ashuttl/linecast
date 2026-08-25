#!/bin/sh
# Keep one GitHub issue in step with the live provider check.
#
# Usage: live_issue.sh <pytest exit status> <report file>
#
# Needs gh, GH_TOKEN, GH_REPO, and RUN_URL in the environment (the
# workflow sets them). One issue carrying the live-check label is open
# while the check fails and closed once it passes again. While it stays
# red the issue is only touched when the set of failing tests changes,
# so a week-long outage is one issue with a few comments, not seven
# issues or seven identical comments.
set -eu

status=$1
report=$2
label=live-check
title="Live provider check is failing"

failed_lines() {
    # "FAILED tests/test_live_providers.py::test_x - reason" lines, the
    # path dropped; pytest prints them under -rfE.
    grep -E '^(FAILED|ERROR) ' "$1" | sed 's#tests/test_live_providers.py::##' | sort
}

issue=$(gh issue list --label "$label" --state open --limit 1 \
        --json number --jq '.[0].number // empty')

if [ "$status" -eq 0 ]; then
    if [ -n "$issue" ]; then
        gh issue comment "$issue" --body "Every provider answered on [this run]($RUN_URL). Closing."
        gh issue close "$issue"
        echo "closed #$issue"
    else
        echo "all green, no issue open"
    fi
    exit 0
fi

now=$(failed_lines "$report")
body_file=$(mktemp)
{
    echo "The scheduled check found a provider that did not answer, or answered in a shape the code no longer understands. [Run log]($RUN_URL)."
    echo
    echo '```'
    if [ -n "$now" ]; then echo "$now"; else grep -E '^(=|E )' "$report" | head -40; fi
    echo '```'
    echo
    echo "Run \`pytest tests/test_live_providers.py -m integration\` to reproduce. This issue is updated when the set of failing tests changes and closed when the check passes again."
} > "$body_file"

if [ -z "$issue" ]; then
    gh label create "$label" --color d93f0b \
        --description "Opened by the scheduled live provider check" --force
    gh issue create --title "$title" --label "$label" --body-file "$body_file"
    echo "opened an issue"
    exit 0
fi

# The last report is the newest comment, or the body when there is none.
last=$(gh issue view "$issue" --json body,comments \
       --jq 'if (.comments | length) > 0 then .comments[-1].body else .body end')
previous=$(printf '%s\n' "$last" | sed -n '/^```$/,/^```$/p' | grep -v '^```$' | sort)
if [ "$previous" = "$now" ]; then
    echo "#$issue already reports these failures"
    exit 0
fi
gh issue comment "$issue" --body-file "$body_file"
echo "updated #$issue"
