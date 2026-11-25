"""scripts/live_issue.sh, run against a stand-in for gh.

The script decides when the daily live provider check opens, updates,
or closes its issue.  The rule under test: a test counts as failing
only when it failed in this report and in the earlier one, so a
provider's bad morning opens nothing.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "live_issue.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sh") is None,
    reason="a POSIX shell script")

# Logs each call, and answers the two questions the script asks: which
# issue is open, and what its last report said.
FAKE_GH = """#!/bin/sh
echo "$@" >> "$GH_LOG"
case "$1 $2" in
    "issue list") cat "$GH_OPEN_ISSUE" 2>/dev/null ;;
    "issue view") cat "$GH_LAST_REPORT" 2>/dev/null ;;
    "issue create"|"issue comment")
        while [ $# -gt 0 ]; do
            if [ "$1" = --body-file ]; then cat "$2" > "$GH_BODY"; fi
            shift
        done ;;
esac
exit 0
"""

PHOTON = "FAILED tests/test_live_providers.py::test_photon_search - SearchUnavailable: timed out"
CROATIA_310 = ("FAILED tests/test_live_providers.py::test_meteoalarm_feed_is_placed[HR]"
               " - AssertionError: HR: 310 areas the region file cannot place")
CROATIA_340 = CROATIA_310.replace("310", "340")
# An open issue's last report, as the script wrote it: the path dropped.
LAST_REPORT = ("Failed on this run:\n\n```\n"
               + CROATIA_310.replace("tests/test_live_providers.py::", "") + "\n```\n")


@pytest.fixture
def run(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.write_text("")
    output = tmp_path / "github_output"

    def go(now, earlier=None, open_issue=None, last_report=None):
        """Run the script on a report and return (gh calls, failing, body)."""
        report = tmp_path / "report.txt"
        report.write_text("\n".join(now) + "\n")
        args = ["sh", str(SCRIPT), "1" if now else "0", str(report)]
        if earlier is not None:
            before = tmp_path / "earlier.txt"
            before.write_text("\n".join(earlier) + "\n")
            args.append(str(before))
        if open_issue:
            (tmp_path / "open").write_text(f"{open_issue}\n")
        if last_report:
            (tmp_path / "last").write_text(last_report)
        output.write_text("")
        env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                   GH_LOG=str(log), GH_OPEN_ISSUE=str(tmp_path / "open"),
                   GH_LAST_REPORT=str(tmp_path / "last"), GH_BODY=str(tmp_path / "body"),
                   GITHUB_OUTPUT=str(output), RUN_URL="https://example.test/run/2",
                   EARLIER_URL="https://example.test/run/1")
        done = subprocess.run(args, env=env, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        calls = [line for line in log.read_text().splitlines()
                 if not line.startswith(("issue list", "issue view"))]
        body = (tmp_path / "body").read_text() if (tmp_path / "body").exists() else ""
        return calls, output.read_text().strip(), body, done.stdout

    return go


def test_a_first_failure_opens_nothing(run):
    calls, failing, _body, out = run([PHOTON], earlier=[])
    assert calls == []
    assert failing == "failing=0"
    assert "::warning title=Failed once::FAILED test_photon_search" in out


def test_no_earlier_report_opens_nothing(run):
    calls, failing, _body, _out = run([PHOTON])
    assert calls == [] and failing == "failing=0"


def test_a_failure_two_days_running_opens_an_issue(run):
    calls, failing, body, _out = run([PHOTON, CROATIA_340], earlier=[CROATIA_310])
    assert failing == "failing=1"
    created = [c for c in calls if c.startswith("issue create")]
    assert len(created) == 1
    assert "Live check failing: meteoalarm_feed_is_placed[HR] " in created[0]
    assert "and 1 more" not in created[0]
    counted, first = body.split("for the first time")
    assert "test_meteoalarm_feed_is_placed[HR]" in counted and "photon" not in counted
    assert "test_photon_search" in first
    assert "-k 'test_meteoalarm_feed_is_placed'" in body
    assert "https://example.test/run/1" in body


def test_the_title_counts_the_rest(run):
    calls, failing, _body, _out = run([PHOTON, CROATIA_340], earlier=[PHOTON, CROATIA_310])
    assert failing == "failing=2"
    assert any("Live check failing: meteoalarm_feed_is_placed[HR] and 1 more" in c
               for c in calls)


def test_a_changed_reason_is_not_a_change(run):
    calls, failing, _body, out = run([CROATIA_340], earlier=[CROATIA_310],
                                     open_issue=7, last_report=LAST_REPORT)
    assert calls == [] and failing == "failing=1"
    assert "#7 already reports these failures" in out


def test_a_changed_set_comments_and_retitles(run):
    calls, _failing, _body, _out = run([PHOTON, CROATIA_340], earlier=[PHOTON, CROATIA_310],
                                       open_issue=7, last_report=LAST_REPORT)
    assert [c.split()[1] for c in calls] == ["comment", "edit"]
    assert "and 1 more" in calls[1]


def test_the_issue_closes_when_the_failing_tests_pass(run):
    calls, failing, _body, _out = run([], earlier=[CROATIA_310], open_issue=7)
    assert failing == "failing=0"
    assert [c.split()[1] for c in calls] == ["comment", "close"]
    assert "Every provider answered" in calls[0]


def test_the_issue_closes_though_something_else_failed_once(run):
    calls, failing, _body, _out = run([PHOTON], earlier=[CROATIA_310], open_issue=7)
    assert failing == "failing=0"
    assert [c.split()[1] for c in calls] == ["comment", "close"]
    assert "What was failing answered" in calls[0]


def test_pytest_failing_without_a_named_test_is_still_a_failure(run):
    # status 1 with no FAILED line: collection or startup broke
    calls, failing, _body, out = run(["no tests ran in 0.01s"], earlier=[])
    assert calls == [] and failing == "failing=0"
    assert "(no test ran)" in out
