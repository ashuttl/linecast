#!/usr/bin/env python3
"""Drive a linecast maps live view in a pty and time its frames.

Usage: bench_maps_live.py <worktree> <scenario> [cols rows]

<worktree> is a checkout to run (`uv run --project` it); the scenarios
open the live map, drive it with SGR mouse drags and keys, and time
every frame the loop paints, on both the synchronized-update loop and
the older cursor-home loop.  Frame headers and ink density per frame
are written beside the script as frames-<worktree>-<scenario>.txt.

Scenarios: globe, street, terrain.  Prints one JSON line of metrics.
The pty answers cursor-position queries at once, so the loop's frame
sync never waits on us; every other terminal query is ignored.
"""
import fcntl
import json
import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import time

ESC = b"\x1b"
SYNC_BEGIN = b"\x1b[?2026h"
SYNC_END = b"\x1b[?2026l"
CPR = b"\x1b[6n"
HOME = b"\x1b[H"
ROW_RE = re.compile(rb"\x1b\[\d+;1H")
ANSI_RE = re.compile(rb"\x1b\[[0-9;?<>=]*[A-Za-z~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|\x1b[=>]")


class Session:
    def __init__(self, worktree, args, cols, rows, log):
        self.cols, self.rows = cols, rows
        env = dict(os.environ)
        env.update({
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "LINECAST_THEME": "dark",
            "LINECAST_THEME_POLL": "0",
            "LINECAST_CELL_ASPECT": "0.5",
            "COLUMNS": str(cols), "LINES": str(rows),
            "PYTHONUNBUFFERED": "1",
        })
        env.pop("TMUX", None)
        m, s = pty.openpty()
        fcntl.ioctl(s, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.master = m
        self.t0 = time.monotonic()
        self.proc = subprocess.Popen(
            ["uv", "run", "--project", worktree, "python", "-m", "linecast.maps",
             *args],
            stdin=s, stdout=s, stderr=log, env=env, cwd=worktree,
            preexec_fn=os.setsid, close_fds=True)
        os.close(s)
        self.buf = b""
        self.frames = []      # (t_end, text)
        self.in_frame = None  # (t_begin, bytes)
        self.raw_bytes = 0
        self.events = []
        self.synced = False
        self.carry = b""
        self.last_byte = 0.0

    def now(self):
        return time.monotonic() - self.t0

    def pump(self, timeout):
        """Read whatever the app wrote for up to `timeout` s."""
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            r, _, _ = select.select([self.master], [], [], min(left, 0.03))
            if not r:
                if (not self.synced and self.in_frame is not None
                        and self.now() - self.last_byte > 0.03):
                    self._close_frame(b"")
                continue
            try:
                data = os.read(self.master, 65536)
            except OSError:
                return
            if not data:
                return
            self.raw_bytes += len(data)
            self._ingest(data)

    def _ingest(self, data):
        self.buf += data
        self.last_byte = self.now()
        while True:
            if self.in_frame is None:
                i = self.buf.find(SYNC_BEGIN)
                mark = SYNC_BEGIN
                if i < 0 and not self.synced:
                    i = self.buf.find(HOME)
                    mark = HOME
                if i < 0:
                    self._answer(self.buf)
                    self.buf = b""
                    return
                if mark is SYNC_BEGIN:
                    self.synced = True
                self._answer(self.buf[:i])
                self.buf = self.buf[i + len(mark):]
                self.in_frame = (self.now(), b"")
            if self.synced:
                j = self.buf.find(SYNC_END)
                if j < 0:
                    return
                self._close_frame(self.buf[:j])
                self.buf = self.buf[j + len(SYNC_END):]
            else:
                # legacy loop: a frame runs to the next cursor-home, or
                # to quiet (see pump)
                j = self.buf.find(HOME)
                if j < 0:
                    self.in_frame = (self.in_frame[0], self.in_frame[1] + self.buf)
                    self._answer(self.buf)
                    self.buf = b""
                    return
                self._close_frame(self.buf[:j])
                self.buf = self.buf[j + len(HOME):]
                self.in_frame = (self.now(), b"")

    def _close_frame(self, tail):
        body = self.in_frame[1] + tail
        self._answer(tail)
        body = ROW_RE.sub(b"\n", body)
        text = ANSI_RE.sub(b"", body).decode("utf-8", "replace").lstrip("\n")
        self.frames.append((self.in_frame[0], self.now(), text))
        self.in_frame = None

    def _answer(self, chunk):
        # a query can straddle two reads, so the tail of the last chunk
        # is carried into the next before counting
        data = self.carry + chunk
        n = data.count(CPR)
        self.carry = data[-(len(CPR) - 1):]
        for _ in range(n):
            os.write(self.master, f"\x1b[{self.rows};1R".encode())

    def send(self, data):
        os.write(self.master, data)

    def mark(self, name):
        self.events.append((name, self.now(), len(self.frames)))

    def drag(self, c0, r0, c1, r1, steps, seconds):
        self.send(f"\x1b[<0;{c0};{r0}M".encode())
        dt = seconds / steps
        for i in range(1, steps + 1):
            c = round(c0 + (c1 - c0) * i / steps)
            r = round(r0 + (r1 - r0) * i / steps)
            self.send(f"\x1b[<32;{c};{r}M".encode())
            self.pump(dt)
        self.send(f"\x1b[<0;{c1};{r1}m".encode())

    def close(self):
        self.send(b"q")
        t = self.now()
        # keep answering the terminal's queries while the loop winds down,
        # or its exit drain waits out the ack timeout on us, not on itself
        while self.proc.poll() is None and self.now() - t < 30:
            self.pump(0.05)
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        return self.now() - t

    def wait_settled(self, timeout, since=None):
        """Pump until a frame without a loading tag has been drawn after
        `since` (a frame index), or timeout.  Returns that frame's index
        or None."""
        end = time.monotonic() + timeout
        start = len(self.frames) if since is None else since
        while time.monotonic() < end:
            for k in range(start, len(self.frames)):
                if not is_loading(self.frames[k][2]):
                    return k
            self.pump(0.05)
        return None


def is_loading(text):
    head = text.split("\n", 1)[0]
    return "loading" in head.lower() or "chargement" in head.lower()


def ink_density(text):
    body = "\n".join(text.split("\n")[1:-1])
    if not body:
        return 0.0
    inked = sum(1 for ch in body if ch not in " \n")
    return inked / max(1, len(body.replace("\n", "")))


def frame_stats(frames, t_from, t_to):
    ts = [f[1] for f in frames if t_from <= f[1] <= t_to]
    if len(ts) < 2:
        return {"n": len(ts)}
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    return {"n": len(ts), "mean_gap_ms": round(1000 * sum(gaps) / len(gaps), 1),
            "max_gap_ms": round(1000 * max(gaps), 1),
            "fps": round(len(ts) / max(1e-6, t_to - t_from), 1)}


def scenario_globe(s):
    out = {}
    s.pump(0.5)
    k = s.wait_settled(60)
    out["first_frame_s"] = round(s.frames[0][1], 2) if s.frames else None
    out["settled_s"] = round(s.frames[k][1], 2) if k is not None else None
    s.pump(1.0)
    # a drag across the disk, 60 Hz motion for 2 s
    n0 = len(s.frames)
    t0 = s.now()
    s.drag(s.cols // 2 - 30, s.rows // 2, s.cols // 2 + 30, s.rows // 2 - 6, 120, 2.0)
    t_release = s.now()
    k = s.wait_settled(30, since=len(s.frames))
    t_settle = s.frames[k][1] if k is not None else None
    s.pump(1.0)
    out["drag"] = frame_stats(s.frames, t0, t_release)
    out["drag_settle_after_release_s"] = (round(t_settle - t_release, 2)
                                          if t_settle else None)
    out["drag_frames_after_release"] = len(s.frames) - n0 - out["drag"].get("n", 0)
    # a second drag: caches warm now
    t0 = s.now()
    s.drag(s.cols // 2 + 20, s.rows // 2 - 5, s.cols // 2 - 40, s.rows // 2 + 5, 120, 2.0)
    t_release = s.now()
    k = s.wait_settled(30, since=len(s.frames))
    t_settle = s.frames[k][1] if k is not None else None
    s.pump(1.0)
    out["drag2"] = frame_stats(s.frames, t0, t_release)
    out["drag2_settle_after_release_s"] = (round(t_settle - t_release, 2)
                                           if t_settle else None)
    # spin for 4 s
    t0 = s.now()
    s.send(b"r")
    s.pump(4.0)
    s.send(b"r")
    t1 = s.now()
    out["spin"] = frame_stats(s.frames, t0, t1)
    s.pump(1.0)
    # zoom in two steps toward the flat hand-off, then out
    n = len(s.frames)
    t0 = s.now()
    s.send(b"+")
    s.pump(0.15)
    s.send(b"+")
    k = s.wait_settled(60, since=n)
    out["zoom_in2_settle_s"] = round(s.frames[k][1] - t0, 2) if k is not None else None
    out["zoom_in2_frames"] = len(s.frames) - n
    s.pump(1.0)
    n = len(s.frames)
    t0 = s.now()
    s.send(b"-")
    s.pump(0.15)
    s.send(b"-")
    k = s.wait_settled(60, since=n)
    out["zoom_out2_settle_s"] = round(s.frames[k][1] - t0, 2) if k is not None else None
    s.pump(1.0)
    out["quit_s"] = round(s.close(), 2)
    out["frames_total"] = len(s.frames)
    out["raw_kb"] = s.raw_bytes // 1024
    return out


def scenario_flat(s):
    out = {}
    s.pump(0.5)
    k = s.wait_settled(90)
    out["first_frame_s"] = round(s.frames[0][1], 2) if s.frames else None
    out["settled_s"] = round(s.frames[k][1], 2) if k is not None else None
    s.pump(1.0)
    # pan: drag a third of the width, release, wait for the real view
    n0 = len(s.frames)
    t0 = s.now()
    s.drag(s.cols // 2, s.rows // 2, s.cols // 2 - s.cols // 3, s.rows // 2 + 4, 60, 1.0)
    t_release = s.now()
    k = s.wait_settled(90, since=len(s.frames))
    t_settle = s.frames[k][1] if k is not None else None
    s.pump(1.0)
    out["pan"] = frame_stats(s.frames, t0, t_release)
    out["pan_settle_after_release_s"] = (round(t_settle - t_release, 2)
                                         if t_settle else None)
    after = [f for f in s.frames[n0:] if f[1] > t_release]
    out["pan_ink_after_release"] = [round(ink_density(f[2]), 3) for f in after[:4]]
    # zoom in two taps, wait; then out two taps, wait
    for label, key in (("zoom_in2", b"+"), ("zoom_out2", b"-")):
        n = len(s.frames)
        t0 = s.now()
        s.send(key)
        s.pump(0.15)
        s.send(key)
        k = s.wait_settled(90, since=n)
        out[label + "_settle_s"] = (round(s.frames[k][1] - t0, 2)
                                    if k is not None else None)
        after = [f for f in s.frames[n:]]
        out[label + "_ink"] = [round(ink_density(f[2]), 3) for f in after[:4]]
        s.pump(1.0)
    # keyboard pan
    n = len(s.frames)
    t0 = s.now()
    s.send(b"d")
    k = s.wait_settled(90, since=n)
    out["key_pan_settle_s"] = round(s.frames[k][1] - t0, 2) if k is not None else None
    s.pump(1.0)
    out["quit_s"] = round(s.close(), 2)
    out["frames_total"] = len(s.frames)
    out["raw_kb"] = s.raw_bytes // 1024
    return out


SCENARIOS = {
    "globe": (["--view", "now", "--location", "40.7,-74.0"], scenario_globe),
    "street": (["--view", "street", "--location", "40.7128,-74.006",
                "--zoom", "0.05"], scenario_flat),
    "terrain": (["--view", "terrain", "--location", "46.8,8.2",
                 "--zoom", "2"], scenario_flat),
}


def main():
    worktree, name = sys.argv[1], sys.argv[2]
    cols = int(sys.argv[3]) if len(sys.argv) > 3 else 160
    rows = int(sys.argv[4]) if len(sys.argv) > 4 else 45
    args, fn = SCENARIOS[name]
    args = args + os.environ.get("BENCH_EXTRA", "").split()
    logpath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           f"log-{os.path.basename(worktree)}-{name}.txt")
    with open(logpath, "w") as log:
        s = Session(worktree, args, cols, rows, log)
        try:
            out = fn(s)
        finally:
            if s.proc.poll() is None:
                s.proc.kill()
    with open(logpath.replace("log-", "frames-"), "w") as fh:
        for a, b, text in s.frames:
            head = text.split("\n", 1)[0].strip()
            fh.write(f"{a:8.3f} {b:8.3f} {b-a:6.3f} ink={ink_density(text):.3f} {head[:100]}\n")
    out["worktree"] = os.path.basename(worktree)
    out["scenario"] = name
    print(json.dumps(out))


if __name__ == "__main__":
    main()
