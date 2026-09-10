"""Exercise Maps' real input/render/output loop through a POSIX pseudo-terminal.

Network is disabled. Bundled world data and an optional private copy of local
tiles drive the real renderers. --delay adds latency only to background detail
preparation, to check that input and animation continue while it is pending.
--spin adds a real two-second spin and alternating wheel zooms, auditing complete
Earth fill coverage; --fast-drag also exposes a previously hidden hemisphere.
--coast checks a flick, a paused release, and a regrab through real mouse input.
The default sequence remains the original interaction benchmark. Spin-mode
render times include coverage-observer overhead.
This measures application rendering and PTY writes, not native terminal display.
"""

import argparse
import fcntl
import json
import math
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
    parser.add_argument('--spin', action='store_true')
    parser.add_argument('--fast-drag', action='store_true')
    parser.add_argument('--coast', action='store_true')
    parser.add_argument('--sky', action='store_true', help='enable daylight and cloud layers')
    args = parser.parse_args()
    if args.fast_drag and not args.spin:
        parser.error('--fast-drag requires --spin')
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
         '--view', args.view, '--zoom', str(args.zoom), '--delay', str(args.delay),
         *(['--spin'] if args.spin else []), *(['--fast-drag'] if args.fast_drag else []),
         *(['--sky'] if args.sky else []),
         *(['--coast'] if args.coast else [])],
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
        if args.spin or args.coast:
            # Begin after real detail is published, including a complete
            # surface when the opening camera uses world sources.
            deadline = time.monotonic() + 15 + args.delay
            while True:
                log_path = work / 'frames.jsonl'
                lines = log_path.read_text().splitlines() if log_path.exists() else []
                try:
                    latest = json.loads(lines[-1]) if lines else {}
                except json.JSONDecodeError:  # The child may be writing its newest row.
                    latest = {}
                if (latest.get('ready') and
                        (latest.get('motion_ready') or not latest.get('world'))):
                    break
                assert child.poll() is None, 'child exited before preparing a motion surface'
                assert time.monotonic() < deadline, 'motion surface did not become ready'
                drain(.1)
        if args.coast:
            x, y = args.cols // 2, args.rows // 2
            step = max(1, round(min(args.cols, 2 * (args.rows - 2)) * .035))

            def flick(name, pause=0):
                send(f'\x1b[<0;{x};{y}M'.encode(), f'coast_{name}_press')
                drain(.04)
                for n in range(1, 4):
                    send(f'\x1b[<32;{x+n*step};{y}M'.encode(), f'coast_{name}_drag')
                    drain(.045)
                if pause:
                    drain(pause)
                send(f'\x1b[<0;{x+3*step};{y}m'.encode(), f'coast_{name}_release')

            flick('flick')
            drain(1.15 + args.delay)
            flick('paused', pause=.3)
            drain(.4 + args.delay)
            flick('regrab')
            drain(.06)
            send(f'\x1b[<0;{x};{y}M'.encode(), 'coast_hold_press')
            drain(.45 + args.delay)
            send(f'\x1b[<0;{x};{y}m'.encode(), 'coast_hold_release')
            drain(.3)
            events.append(dict(time=time.monotonic(), event='coast_end'))
        if args.spin:
            send(b'r', 'spin_start')
            drain(2.3)
            send(b'r', 'spin_stop')
            drain(.15)
            for _ in range(3):
                send(b'\x1b[<64;55;18M', 'spin_zoom_in')
                drain(.18)
                send(b'\x1b[<65;55;18M', 'spin_zoom_out')
                drain(.18)
            drain(.4)
            if args.fast_drag:
                x0, x1, y = args.cols // 4, args.cols * 3 // 4, args.rows // 2
                send(f'\x1b[<0;{x0};{y}M'.encode(), 'fast_press')
                send(f'\x1b[<32;{x1};{y}M'.encode(), 'fast_drag')
                drain(.2)
                send(f'\x1b[<0;{x1};{y}m'.encode(), 'fast_release')
                drain(.3)
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
    writes = [json.loads(line) for line in (work / 'writes.jsonl').read_text().splitlines()]
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
    spin_summary = {}
    if args.spin:
        spun = [f for f in frames if f.get('spinning')]
        assert len(spun) >= 20, 'continuous spin did not produce enough frames'
        assert all(f.get('coverage') for f in spun), 'spin lost its complete surface'
        elapsed = spun[-1]['start'] - spun[0]['start']
        assert elapsed >= 1.8, 'continuous spin lasted less than two seconds'
        turned = (spun[0]['display'][1] - spun[-1]['display'][1] + 180) % 360 - 180
        assert abs(turned - elapsed) < .15, 'spin no longer follows elapsed time'
        coverage = [f['coverage'] for f in frames if f.get('coverage')]
        assert coverage and all(c['earth'] > 0 for c in coverage)
        assert all(c['missing'] == 0 for c in coverage), 'Earth fill contains missing samples'
        assert all(c['background_gaps'] == 0 for c in coverage), 'Earth fill contains space gaps'
        unseen = [c for c in coverage if not c['source_center_visible']]
        if args.fast_drag:
            assert unseen, 'fast drag never exposed a previously hidden center'
        spin_summary = dict(spin_frames=len(spun), spin_seconds=elapsed,
                            spin_degrees=turned, coverage_frames=len(coverage),
                            unseen_center_frames=len(unseen),
                            max_source_turn_degrees=max(c['source_turn'] for c in coverage),
                            earth_samples=sum(c['earth'] for c in coverage),
                            earth_missing_samples=sum(c['missing'] for c in coverage),
                            earth_background_samples=sum(c['background'] for c in coverage),
                            earth_background_gaps=sum(c['background_gaps'] for c in coverage),
                            coverage_observer_included=True)
    coast_summary = {}
    if args.coast:
        callbacks = [json.loads(line) for line in (work / 'input.jsonl').read_text().splitlines()]
        coast_summary = check_coast(frames, events, callbacks)
    result = dict(work=str(work), view=args.view, size=[args.cols, args.rows],
                  zoom=args.zoom, sky=args.sky, delay_seconds=args.delay, frames=len(frames),
                  output_bytes=len(output), render_median_ms=statistics.median(durations),
                  render_p95_ms=sorted(durations)[int(.95 * (len(durations) - 1))],
                  render_max_ms=max(durations),
                  write_total_ms=sum(w['seconds'] for w in writes) * 1000,
                  write_max_ms=max(w['seconds'] for w in writes) * 1000,
                  exit_code=code, **spin_summary, **coast_summary)
    (work / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


def check_coast(frames, events, callbacks):
    """Use actual callback receipts and rendered cameras, without sampling motion."""
    start = next(event['time'] for event in events if event['event'] == 'coast_flick_press')
    end = next(event['time'] for event in events if event['event'] == 'coast_end')
    inputs = [event for event in callbacks if start <= event['time'] < end]
    presses = [event for event in inputs if event['kind'] == 'interrupt']
    releases = [event for event in inputs if event['kind'] == 'drag' and event['done']]
    assert len(presses) == len(releases) == 4, 'coast gestures did not reach the input hooks'
    assert [event['coasting'] for event in releases] == [True, False, True, False], (
        'flick, paused release, or zero-delta regrab release launched the wrong motion')
    assert presses[3]['coasting_before'], 'regrab did not interrupt an active coast'

    def interval(begin, finish):
        rows = [frame for frame in frames if begin <= frame['start'] < finish]
        assert rows, 'gesture produced no rendered frame'
        return rows

    def arc(a, b):
        lat0, lat1 = math.radians(a[0]), math.radians(b[0])
        dlat, dlon = lat1 - lat0, math.radians(b[1] - a[1])
        hav = math.sin(dlat / 2) ** 2 + math.cos(lat0) * math.cos(lat1) * math.sin(dlon / 2) ** 2
        return 2 * math.atan2(math.sqrt(max(0, hav)), math.sqrt(max(0, 1 - hav)))

    flick = interval(releases[0]['end'], presses[1]['time'])
    moving = [frame for frame in flick if frame['coasting']]
    assert len(moving) >= 2, 'release did not keep the displayed map moving'
    target = flick[0]['target']
    assert all(frame['target'] == target for frame in flick), 'coast target moved between frames'
    remaining = [arc(frame['display'], target) for frame in flick]
    assert all(b <= a + 1e-12 for a, b in zip(remaining, remaining[1:])), 'coast reversed direction'
    assert not flick[-1]['coasting'] and flick[-1]['display'] == target, 'coast did not settle'
    travel = arc(flick[0]['display'], flick[-1]['display'])
    w, h = flick[0]['size']
    fraction = math.degrees(travel) / target[2] * 2 * h / min(w, 2 * h)
    assert 0 < fraction < .5, 'release travel was absent or exceeded half the viewport'

    paused = interval(releases[1]['end'], presses[2]['time'])
    grabbed = interval(presses[3]['end'], end)
    for name, rows in (('paused release', paused), ('regrab', grabbed)):
        assert all(not frame['coasting'] for frame in rows), f'{name} resumed coasting'
        assert all(frame['display'] == frame['target'] == rows[0]['display'] for frame in rows), (
            f'{name} failed to freeze the displayed camera')
    return dict(coast_frames=len(moving), coast_travel_viewport_fraction=fraction,
                paused_release_frames=len(paused), regrab_frozen_frames=len(grabbed))


def child_run(args):
    import socket
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))

    def offline(*_args, **_kwargs):
        raise OSError('offline PTY validation')

    socket.socket.connect = offline
    socket.create_connection = offline
    from linecast._maps_live import MapApp
    from linecast._runtime import RuntimeConfig, set_current
    from linecast import _maps_live, _vtiles, maps
    tilejson = args.work / 'cache' / 'maps' / 'tilejson.json'
    if tilejson.exists():
        data = json.loads(tilejson.read_text())
        _vtiles.tilejson = lambda: data
    runtime = RuntimeConfig(live=True, icons='plain', lang='en', oneline=False)
    set_current(runtime)
    app = MapApp(runtime,
                 43.66787161011749, -70.191650390625, 'Portland', args.zoom,
                 args.view, args.sky, 'car')
    render, prepare = app.render, app._prepare
    draw = _maps_live.render_map
    shown = [app.target_camera()]
    world = [not shown[0].local_tiles]
    motion_ready = [False]
    source = [None]
    complete = [False]
    refining = [False]
    coverage = [None]
    masks = {}
    if args.spin:
        from linecast._maps_preview import PreparedMap
        transform = PreparedMap.transformed

        def audited_transform(self, camera):
            frame = transform(self, camera)
            assert frame.camera.key == camera.key, 'surface changed the displayed camera'
            if self.world and self.surface is not None:
                w, h = camera.gw, camera.hc * 2
                mask_key = w, h, camera.zoom
                if mask_key not in masks:
                    radius2 = (h * 180 / math.pi / camera.zoom) ** 2
                    masks[mask_key] = tuple((x, y) for y in range(h) for x in range(w)
                                           if (x + .5 - w / 2) ** 2 +
                                           (y + .5 - h / 2) ** 2 <= radius2)
                pixels = [frame.fills[y][x] for x, y in masks[mask_key]]
                background = [point for point, pixel in zip(masks[mask_key], pixels)
                              if pixel == maps.BG_PRIMARY]
                background_gaps = 0
                if background and camera.key != self.camera.key:
                    # Ocean shading can legitimately equal the space color.
                    # Only rare ambiguous transformed frames need a complete
                    # surface reference; exact frames use different hillshade.
                    reference = self.surface.render(camera)
                    background_gaps = sum(reference[y][x] != maps.BG_PRIMARY
                                          for x, y in background)
                cos_turn = self.camera._vector(camera.lon, camera.lat)[2]
                coverage[0] = dict(
                    earth=len(pixels), missing=sum(px is None for px in pixels),
                    background=len(background), background_gaps=background_gaps,
                    source_turn=math.degrees(math.acos(max(-1, min(1, cos_turn)))),
                    source_center_visible=self.camera.visible(camera.lon, camera.lat))
            return frame

        PreparedMap.transformed = audited_transform

    def measured_draw(camera, prepared, *a, **kw):
        shown[0] = camera
        world[0] = prepared.world if prepared is not None else not camera.local_tiles
        motion_ready[0] = prepared is not None and prepared.surface is not None
        source[0] = list(prepared.camera.key) if prepared is not None else None
        complete[0] = prepared is not None and getattr(prepared, 'complete', True)
        refining[0] = kw.get('refining', False)
        return draw(camera, prepared, *a, **kw)

    _maps_live.render_map = measured_draw
    snapshots = []
    log = (args.work / 'frames.jsonl').open('w')
    builds = (args.work / 'builds.jsonl').open('w')
    writes = (args.work / 'writes.jsonl').open('w')

    class MeasuredOutput:
        """Observe transport separately; PTY acceptance is not terminal paint."""

        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def write(self, value):
            start = time.monotonic()
            result = self.stream.write(value)
            writes.write(json.dumps(dict(start=start, seconds=time.monotonic() - start,
                                         kind='write', bytes=len(value.encode()))) + '\n')
            writes.flush()
            return result

        def flush(self):
            start = time.monotonic()
            self.stream.flush()
            writes.write(json.dumps(dict(start=start, seconds=time.monotonic() - start,
                                         kind='flush', bytes=0)) + '\n')
            writes.flush()

    sys.stdout = MeasuredOutput(sys.stdout)
    if args.coast:
        inputs = (args.work / 'input.jsonl').open('w')
        drag, interrupt = app.on_drag, app.on_interrupt

        def measured_drag(dcol, drow, done):
            start = time.monotonic()
            result = drag(dcol, drow, done)
            inputs.write(json.dumps(dict(time=start, end=time.monotonic(), kind='drag',
                                         dcol=dcol, drow=drow, done=done,
                                         coasting=app._motion.coasting)) + '\n')
            inputs.flush()
            return result

        def measured_interrupt():
            start, before = time.monotonic(), app._motion.coasting
            result = interrupt()
            inputs.write(json.dumps(dict(time=start, end=time.monotonic(), kind='interrupt',
                                         coasting_before=before,
                                         coasting=app._motion.coasting)) + '\n')
            inputs.flush()
            return result

        app.on_drag, app.on_interrupt = measured_drag, measured_interrupt

    def measured_render(**kw):
        start = time.monotonic()
        cpu = time.thread_time()
        coverage[0] = None
        frame = render(**kw)
        end = time.monotonic()
        # Observe the actual rendered camera without advancing its clock.
        camera = shown[0]
        ready = bool(app._worker and app._worker._ready)
        log.write(json.dumps(dict(start=start, end=end, cpu=time.thread_time() - cpu,
                                 bytes=len(frame.encode()),
                                 source=source[0], complete=complete[0], refining=refining[0],
                                 target=[app.lat, app.lon, app.zoom],
                                 display=[camera.lat, camera.lon, camera.zoom],
                                 size=[camera.gw, camera.hc], ready=ready,
                                 **(dict(motion_ready=motion_ready[0], world=world[0])
                                    if args.spin or args.coast else {}),
                                 **(dict(spinning=app.spinning, coverage=coverage[0])
                                    if args.spin else {}),
                                 **(dict(coasting=app._motion.coasting)
                                    if args.coast else {}))) + '\n')
        log.flush()
        if len(snapshots) % 8 == 0 or not snapshots:
            (args.work / 'latest-frame.ansi').write_text(frame.split('\x00')[0])
        snapshots.append(frame)
        return frame

    def measured_prepare(*a, **kw):
        start = time.monotonic()
        cpu = time.thread_time()
        if args.delay:
            time.sleep(args.delay)
        result = prepare(*a, **kw)
        builds.write(json.dumps(dict(start=start, end=time.monotonic(),
                                     cpu=time.thread_time() - cpu,
                                     camera=list(a[0].key), ready=result is not None)) + '\n')
        builds.flush()
        return result

    app.render, app._prepare = measured_render, measured_prepare
    app.run()
    (args.work / 'last-frame.ansi').write_text(snapshots[-1].split('\x00')[0])
    log.close()
    if args.coast:
        inputs.close()
    # A daemon build may still finish after stop; keep its diagnostic stream
    # alive until process exit, just as its real network request may finish.


if __name__ == '__main__':
    main()
