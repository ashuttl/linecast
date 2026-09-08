"""Deterministic scheduler probes of actual live_loop; no terminal or sleeps."""
import argparse
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
args = parser.parse_args()
sys.path.insert(0, str(args.repo / 'src'))

from linecast import _live, _theme  # noqa: E402


def run(actions, ready, interval=3600):
    clock = [0.0]
    actions = iter(actions)
    ready = iter(ready)
    frames, handled = [], []
    state = [0]

    def wait(timeout):
        clock[0] += 0.001
        return "input"

    def render(**kw):
        frames.append({"ms": round(clock[0] * 1000, 3), "state": state[0]})
        return "body"

    def key(key):
        state[0] += 1
        handled.append(key)
        return True

    def drag(dc, dr, done):
        state[0] = dc
        handled.append((dc, dr, done))
        return True

    terminal = SimpleNamespace(fd=0, install=lambda: None, set_cbreak=lambda: None,
                               drain=lambda: None, close=lambda: None, wait=wait)
    with patch.object(_live._term, "LiveTerminal", lambda fd: terminal), \
         patch.object(_live._term, "wait_readable", lambda fd, timeout: next(ready)), \
         patch.object(_live.sys, "stdin", SimpleNamespace(fileno=lambda: 0)), \
         patch.object(_live.sys, "stdout", io.StringIO()), \
         patch.object(_live, "_read_key", lambda fd, text=False: next(actions)), \
         patch.object(_live._time, "time", lambda: clock[0]), \
         patch.object(_theme, "poll_interval", lambda: 0), \
         patch.object(_theme, "watch_path", lambda: None):
        _live.live_loop(render, mouse=True, interval=interval, on_action=key, on_drag=drag)
    return {"frames": frames, "final_state": state[0], "handled": len(handled)}


print(json.dumps({
    "changed_key_then_ignored_byte": run(["key:d", None, "quit"], [True]),
    "one_second_continuous_drag": run(
        [("mouse", 0, 1, 1, False)] +
        [("mouse", 32, n + 1, 1, False) for n in range(1, 1001)] + ["quit"],
        [True] * 999 + [False]),
}, indent=2))
