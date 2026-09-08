"""Exercise Maps' real input/render/output loop through a POSIX pseudo-terminal.

Network is disabled. Bundled world data and an optional private copy of local
tiles drive the real renderers. --delay adds latency only to background detail
preparation, to check that input and animation continue while it is pending.
This measures application rendering and PTY writes, not native terminal display.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import statistics
import struct
import subprocess
import sys
import tempfile
import termios
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--work', type=Path)
    parser.add_argument('--cache-source', type=Path)
    parser.add_argument('--view', choices=('street', 'terrain'), default='terrain')
    parser.add_argument('--zoom', type=float, default=130)
    parser.add_argument('--delay', type=float, default=0)
    parser.add_argument('--cols', type=int, default=120)
    parser.add_argument('--rows', type=int, default=40)
    args = parser.parse_args()
    if args.child:
        child_run(args)
        return
    work = Path(tempfile.mkdtemp(prefix='linecast-maps-pty-'))
    if args.cache_source:
        shutil.copytree(args.cache_source / 'maps', work / 'cache' / 'maps')
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ,
                struct.pack('HHHH', args.rows, args.cols, 0, 0))
    env = dict(os.environ, TERM='xterm-256color', LINECAST_COLOR='truecolor',
               LINECAST_CACHE_DIR=str(work / 'cache'), LINECAST_CONFIG_DIR=str(work / 'config'))
    for key in ('NO_COLOR', 'COLUMNS', 'LINES'):
        env.pop(key, None)
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), '--child', '--work', str(work),
         '--view', args.view, '--zoom', str(args.zoom), '--delay', str(args.delay)],
        stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True)
    os.close(slave)
    output, events = bytearray(), []

    def drain(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], max(0, deadline - time.monotonic()))
            if ready:
                try:
                    data = os.read(master, 262144)
                except OSError:
                    return
                if not data:
                    return
                output.extend(data)

    def send(data, name):
        events.append(dict(time=time.monotonic(), event=name))
        os.write(master, data)

    try:
        drain(1.2 + args.delay)
        send(b'\x1b[<0;45;17M', 'press')
        for i in range(1, 21):
            send(f'\x1b[<32;{45+i};{17+i//5}M'.encode(), 'drag')
            drain(.025)
        send(b'\x1b[<0;65;21m', 'release')
        drain(.4)
        for _ in range(3):
            send(b'\x1b[<64;55;18M', 'zoom_in')
            drain(.12)
        drain(.5)
        for _ in range(3):
            send(b'\x1b[<65;55;18M', 'zoom_out')
            drain(.12)
        drain(.5)
        send(b'wasd', 'keyboard_pan')
        drain(.45)
        send(b'?', 'help')
        drain(.12)
        send(b'\x1b', 'close_help')
        drain(.15)
        send(b'/', 'search')
        drain(.08)
        send(b'test', 'search_text')
        drain(.15)
        send(b'\x1b', 'close_search')
        drain(.15)
        fcntl.ioctl(master, termios.TIOCSWINSZ,
                    struct.pack('HHHH', args.rows + 4, args.cols - 10, 0, 0))
        os.kill(child.pid, signal.SIGWINCH)
        events.append(dict(time=time.monotonic(), event='resize'))
        drain(.6 + args.delay)
        send(b'n', 'reset')
        drain(.65 + args.delay)
        send(b'q', 'quit')
        drain(.4)
        code = child.wait(timeout=5)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
        os.close(master)
        (work / 'terminal.ansi').write_bytes(output)
        (work / 'events.json').write_text(json.dumps(events, indent=2))
    frames = [json.loads(line) for line in (work / 'frames.jsonl').read_text().splitlines()]
    durations = [(f['end'] - f['start']) * 1000 for f in frames[1:]]
    assert code == 0, (code, output[-3000:])
    assert b'Traceback' not in output
    assert b'\x1b[?1049h' in output and b'\x1b[?1049l' in output
    assert len(frames) > 35, len(frames)
    assert any(f['display'][2] != f['target'][2] for f in frames), 'zoom never eased'
    assert min(f['display'][2] for f in frames) < args.zoom / 2
    assert frames[-1]['display'] == frames[-1]['target'], 'camera did not settle'
    assert frames[-1]['display'][:2] == [43.66787161011749, -70.191650390625]
    assert frames[-1]['size'] == [args.cols - 10, args.rows + 2]
    assert any(f['ready'] for f in frames), 'no real detail frame rendered'
    result = dict(work=str(work), view=args.view, size=[args.cols, args.rows],
                  zoom=args.zoom, delay_seconds=args.delay, frames=len(frames),
                  output_bytes=len(output), render_median_ms=statistics.median(durations),
                  render_p95_ms=sorted(durations)[int(.95 * (len(durations) - 1))],
                  render_max_ms=max(durations), exit_code=code)
    (work / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


def child_run(args):
    import socket
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))

    def offline(*_args, **_kwargs):
        raise OSError('offline PTY validation')

    socket.socket.connect = offline
    socket.create_connection = offline
    from linecast._maps_live import MapApp
    from linecast._runtime import RuntimeConfig, set_current
    from linecast import _maps_live, _vtiles
    tilejson = args.work / 'cache' / 'maps' / 'tilejson.json'
    if tilejson.exists():
        data = json.loads(tilejson.read_text())
        _vtiles.tilejson = lambda: data
    runtime = RuntimeConfig(live=True, icons='plain', lang='en', oneline=False)
    set_current(runtime)
    app = MapApp(runtime,
                 43.66787161011749, -70.191650390625, 'Portland', args.zoom,
                 args.view, False, 'car')
    render, prepare = app.render, app._prepare
    draw = _maps_live.render_map
    shown = [app.target_camera()]

    def measured_draw(camera, *a, **kw):
        shown[0] = camera
        return draw(camera, *a, **kw)

    _maps_live.render_map = measured_draw
    snapshots = []
    log = (args.work / 'frames.jsonl').open('w')
    builds = (args.work / 'builds.jsonl').open('w')

    def measured_render(**kw):
        start = time.monotonic()
        frame = render(**kw)
        end = time.monotonic()
        # Observe the actual rendered camera without advancing its clock.
        camera = shown[0]
        ready = bool(app._worker and app._worker._ready)
        log.write(json.dumps(dict(start=start, end=end, bytes=len(frame.encode()),
                                 target=[app.lat, app.lon, app.zoom],
                                 display=[camera.lat, camera.lon, camera.zoom],
                                 size=[camera.gw, camera.hc], ready=ready)) + '\n')
        log.flush()
        if len(snapshots) % 8 == 0 or not snapshots:
            (args.work / 'latest-frame.ansi').write_text(frame.split('\x00')[0])
        snapshots.append(frame)
        return frame

    def measured_prepare(*a, **kw):
        start = time.monotonic()
        if args.delay:
            time.sleep(args.delay)
        result = prepare(*a, **kw)
        builds.write(json.dumps(dict(start=start, end=time.monotonic(),
                                     camera=list(a[0].key), ready=result is not None)) + '\n')
        builds.flush()
        return result

    app.render, app._prepare = measured_render, measured_prepare
    app.run()
    (args.work / 'last-frame.ansi').write_text(snapshots[-1].split('\x00')[0])
    log.close()
    # A daemon build may still finish after stop; keep its diagnostic stream
    # alive until process exit, just as its real network request may finish.


if __name__ == '__main__':
    main()
