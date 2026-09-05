"""The live sky: the camera and the keys that move it.

The moon view's drag-and-settle is the model. One ticker thread wakes
the live loop at 30 Hz while anything is in motion — a flick coasting
to a stop, the view easing back from past the zenith or below the
horizon, a zoom easing in, time playing — and every frame is timed off
the clock, so a slow terminal drops frames rather than slowing the
motion. When nothing moves the ticker exits and the loop waits on input
as usual.

Drag turns the view under the pointer, a trackball on the inside of the
sky: the sky follows the hand, and a drag the width of the screen turns
the view by about the field of view. Let go while moving and the view
coasts, slowing over about a second; let go past the zenith or below the
horizon and it eases back with a small overshoot, the moon's settle.
"""

import math
import threading
import time

from linecast import _live
from linecast._live import LiveApp
from linecast.sky import (
    FIGURES_DEFAULT, FOV_DEFAULT, FOV_MAX, FOV_MIN, Scene, View, default_view,
    focal_length, render,
)
from linecast._framebuffer import get_terminal_size
from linecast._sky_search import (
    SkySearch, Target, describe_rising, next_rising, search_overlay,
)

TICK = 1 / 30
ZOOM_STEP = 1.32          # per + or - press
ZOOM_EASE = 0.28          # seconds for a zoom to land
SETTLE = 0.7              # seconds to ease back from past the edge
COAST_HALF_LIFE = 0.22    # seconds for a flick's speed to halve
COAST_FLOOR = 2.0         # degrees per second below which a coast stops
COAST_CEILING = 360.0     # degrees per second a flick may start at
FLY_EASE = 0.6            # seconds for a key to face somewhere
ALT_MIN, ALT_MAX = -12.0, 90.0    # how far a drag may pull past the edges
SPEEDS = (3600.0, 86400.0, 7 * 86400.0)   # p cycles through, then off


def _ease_out_back(s):
    c1 = 1.2
    return 1.0 + (c1 + 1.0) * (s - 1.0) ** 3 + c1 * (s - 1.0) ** 2


def _ease_in_out(s):
    return s * s * (3.0 - 2.0 * s)


def _wrap(az):
    return az % 360.0


def _az_delta(a, b):
    """The signed shortest turn from azimuth a to b, in (-180, 180]."""
    return (b - a + 180.0) % 360.0 - 180.0


class Camera:
    """Where the view looks, and how it is moving.

    Holds the azimuth, altitude and field of view, plus whatever motion
    is under way: a drag in hand, a coast after a flick, a settle back
    inside the edges, a zoom easing to its target, a flight to a
    direction. `view()` gives the View for this instant and advances
    the motions to it; `moving()` says whether the ticker should keep
    waking the loop.
    """

    def __init__(self, az, alt, fov, figures=FIGURES_DEFAULT):
        self.az, self.alt, self.fov = az, alt, fov
        self.figures = figures
        self.focal = 40.0             # sub-pixels per unit, from the last frame
        self.graph_w = 78
        self._drag_base = None        # (az, alt) at the press
        self._drag_trail = []         # (time, az, alt) through the drag
        self._coast = None            # (vaz, valt, last_time)
        self._settle = None           # (from_alt, to_alt, started)
        self._zoom = None             # (from_fov, to_fov, started)
        self._fly = None              # (from_az, from_alt, to_az, to_alt, started)

    # -- reading ---------------------------------------------------------
    def moving(self):
        return any((self._coast, self._settle, self._zoom, self._fly))

    def view(self):
        """The View for now, motions advanced."""
        now = time.monotonic()
        if self._fly is not None:
            az0, alt0, az1, alt1, started = self._fly
            s = (now - started) / FLY_EASE
            if s >= 1.0:
                self.az, self.alt = _wrap(az1), alt1
                self._fly = None
            else:
                e = _ease_in_out(s)
                self.az = _wrap(az0 + _az_delta(az0, az1) * e)
                self.alt = alt0 + (alt1 - alt0) * e
        if self._coast is not None:
            vaz, valt, last = self._coast
            dt = now - last
            decay = 0.5 ** (dt / COAST_HALF_LIFE)
            # Integrate the exponentially decaying speed over the step.
            step = COAST_HALF_LIFE / math.log(2.0) * (1.0 - decay)
            self.az = _wrap(self.az + vaz * step)
            self.alt = self.alt + valt * step
            vaz, valt = vaz * decay, valt * decay
            if math.hypot(vaz, valt) < COAST_FLOOR or not (0.0 <= self.alt <= 90.0):
                self._coast = None
                self._start_settle()
            else:
                self._coast = (vaz, valt, now)
        if self._settle is not None:
            from_alt, to_alt, started = self._settle
            s = (now - started) / SETTLE
            if s >= 1.0:
                self.alt = to_alt
                self._settle = None
            else:
                self.alt = to_alt + (from_alt - to_alt) * (1.0 - _ease_out_back(s))
        if self._zoom is not None:
            from_fov, to_fov, started = self._zoom
            s = (now - started) / ZOOM_EASE
            if s >= 1.0:
                self.fov = to_fov
                self._zoom = None
            else:
                # Zoom eases in log space, so each step feels the same.
                e = _ease_in_out(s)
                self.fov = math.exp(math.log(from_fov)
                                    + (math.log(to_fov) - math.log(from_fov)) * e)
        return View(self.az, self.alt, self.fov, self.figures)

    # -- moving ----------------------------------------------------------
    def _deg_per_subpixel(self):
        """How far the sky turns for a sub-pixel of drag at the centre."""
        return math.degrees(1.0 / self.focal)

    def drag(self, dcol, drow):
        if self._drag_base is None:
            self._drag_base = (self.az, self.alt)
            self._drag_trail = []
            self._coast = self._settle = self._fly = None
        base_az, base_alt = self._drag_base
        rate = self._deg_per_subpixel()
        az = _wrap(base_az - dcol * rate)
        alt = base_alt + drow * 2.0 * rate
        # Past the edges the sky resists: the overshoot is a fraction of
        # the pull, and bounded.
        if alt > 90.0:
            alt = 90.0 + min(ALT_MAX - 90.0 + 8.0, (alt - 90.0) * 0.35)
        elif alt < 0.0:
            alt = max(ALT_MIN, alt * 0.35)
        self.az, self.alt = az, alt
        now = time.monotonic()
        self._drag_trail.append((now, az, alt))
        self._drag_trail = [t for t in self._drag_trail if now - t[0] < 0.25]
        return True

    def release(self):
        if self._drag_base is None:
            return False
        self._drag_base = None
        trail = self._drag_trail
        self._drag_trail = []
        if len(trail) >= 2 and time.monotonic() - trail[-1][0] < 0.12:
            (t0, az0, alt0), (t1, az1, alt1) = trail[0], trail[-1]
            dt = t1 - t0
            if dt >= 0.03:
                vaz, valt = _az_delta(az0, az1) / dt, (alt1 - alt0) / dt
                speed = math.hypot(vaz, valt)
                if speed > COAST_CEILING:
                    vaz, valt = (vaz * COAST_CEILING / speed, valt * COAST_CEILING / speed)
                if speed >= COAST_FLOOR and 0.0 <= self.alt <= 90.0:
                    self._coast = (vaz, valt, time.monotonic())
                    return True
        self._start_settle()
        return True

    def _start_settle(self):
        target = max(0.0, min(90.0, self.alt))
        if abs(target - self.alt) > 1e-3:
            self._settle = (self.alt, target, time.monotonic())

    def zoom(self, factor):
        target = self._zoom[1] if self._zoom is not None else self.fov
        return self.zoom_to(target * factor)

    def zoom_to(self, target):
        target = max(FOV_MIN, min(FOV_MAX, target))
        if abs(target - self.fov) < 1e-6:
            return False
        self._zoom = (self.fov, target, time.monotonic())
        # Zoomed far out, the view lies back: the widest field is the
        # whole dome, looked at from beneath.
        if target > 160.0:
            lie_back = (target - 160.0) / (FOV_MAX - 160.0) * 90.0
            if self.alt < lie_back:
                self.fly_to(self.az, lie_back)
        return True

    def fly_to(self, az, alt):
        self._coast = self._settle = None
        self._fly = (self.az, self.alt, az, max(0.0, min(90.0, alt)), time.monotonic())
        return True


class SkyApp(LiveApp):
    """The live sky view: a camera, a clock that can run, and the keys."""

    interval = 60
    mouse = True
    scroll_step = 15

    def __init__(self, now_fn, lat, lng, runtime, facing=None, fov=FOV_DEFAULT,
                 location_label="", aim=None):
        self.now_fn = now_fn
        self.lat, self.lng = lat, lng
        self.runtime = runtime
        self.location_label = location_label
        self.search = SkySearch(runtime)
        self._panel_was_open = False
        self.minutes = 0            # the scrub, whole minutes
        self.played = 0.0           # seconds added by play
        self.speed = None           # seconds per second while playing
        self._play_mark = None      # monotonic time of the last play step
        self._ticker = None
        self._lock = threading.Lock()
        cols, rows = get_terminal_size()
        from datetime import timezone
        now = now_fn()
        view = default_view(Scene(now.astimezone(timezone.utc), lat, lng), cols, rows,
                            facing, fov, aim=aim)
        self.camera = Camera(view.az, view.alt, view.fov)
        self.scene = None

    # -- time ------------------------------------------------------------
    def moment(self):
        from datetime import timedelta
        return self.now_fn() + timedelta(minutes=self.minutes, seconds=self.played)

    def offset_minutes(self):
        return int(round(self.minutes + self.played / 60.0))

    # -- the ticker ------------------------------------------------------
    def _wake(self):
        """Start the ticker if anything is moving and it is not running."""
        with self._lock:
            if self._ticker is None or not self._ticker.is_alive():
                self._ticker = threading.Thread(target=self._tick, daemon=True)
                self._ticker.start()

    def _tick(self):
        while True:
            time.sleep(TICK)
            if self.speed is not None:
                now = time.monotonic()
                if self._play_mark is not None:
                    self.played += (now - self._play_mark) * self.speed
                self._play_mark = now
            _live.nudge()
            if self.speed is None and not self.camera.moving():
                return

    # -- search ----------------------------------------------------------
    def scene_at(self, moment):
        from datetime import timezone
        return Scene(moment.astimezone(timezone.utc), self.lat, self.lng)

    def go_to(self, target):
        """Fly to a found thing if it is up; otherwise say when it rises
        and offer that moment."""
        now = self.moment()
        alt, az = target.place(self.scene_at(now))
        if alt > 1.0:
            self.camera.fly_to(az, alt)
            self.camera.zoom_to(target.fov(self.camera.fov))
            self.search.close()
            self._wake()
            return True
        rising = next_rising(target, self.scene_at, now)
        self.search.note = describe_rising(target, rising, self.runtime)
        self.search.jump = (rising[0], target) if rising else None
        return True

    def jump(self):
        """Take the offered moment: the clock moves to a little after the
        rising, and the view turns to the thing."""
        from datetime import timedelta
        when, target = self.search.jump
        self.minutes = int(round((when + timedelta(minutes=25) - self.now_fn())
                                 .total_seconds() / 60.0))
        self.played = 0.0
        alt, az = target.place(self.scene_at(self.moment()))
        self.camera.fly_to(az, max(alt, 8.0))
        self.camera.zoom_to(target.fov(self.camera.fov))
        self.search.close()
        self._wake()
        return True

    # -- hooks -----------------------------------------------------------
    def render(self, offset_minutes=0, mouse_pos=None, **_):
        view = self.camera.view()
        now = self.moment()
        cols, rows = get_terminal_size()
        self.camera.graph_w = max(20, cols - 2)
        self.camera.focal = focal_length(self.camera.graph_w, view.fov)
        frame = render(now, self.lat, self.lng, self.runtime, view, fullscreen=True,
                       offset_minutes=self.offset_minutes(),
                       mouse_pos=None if self.search.open else mouse_pos,
                       location_label=self.location_label, speed=self.speed)
        body, _sep, floating = frame.partition("\x00")
        if self.search.open:
            # The field owns the keys; motion reporting is off while it is
            # open, since a torn motion sequence reads as ESC.
            self._panel_was_open = True
            return _live.overlay(body, floating + search_overlay(
                self.search, cols, rows, self.runtime), motion=False)
        if self._panel_was_open:
            self._panel_was_open = False
            return _live.overlay(body, floating, motion=True)
        return frame

    def text_mode(self):
        return self.search.open

    def intercept(self, action):
        if self.search.open:
            result = self.search.handle(action)
            if isinstance(result, Target):
                return self.go_to(result)
            if result == "jump":
                return self.jump()
            return True
        if action == "key:/":
            self.search.start()
            return True
        if action == "fwd":
            self.minutes += self.scroll_step
            return True
        if action == "back":
            self.minutes -= self.scroll_step
            return True
        if action == "reset":
            self.minutes, self.played, self.speed = 0, 0.0, None
            self._play_mark = None
            return True
        return False

    def on_wheel(self, direction, _col, _row):
        self.minutes += self.scroll_step * direction
        return True

    def on_action(self, key):
        cam = self.camera
        if key in ("+", "="):
            changed = cam.zoom(1.0 / ZOOM_STEP)
        elif key == "-":
            changed = cam.zoom(ZOOM_STEP)
        elif key == "c":
            cam.figures = (cam.figures + 2) % 3   # 2 → 1 → 0 → 2
            return True
        elif key == "p":
            if self.speed is None:
                self.speed = SPEEDS[0]
            else:
                i = SPEEDS.index(self.speed) + 1 if self.speed in SPEEDS else 0
                self.speed = SPEEDS[i] if i < len(SPEEDS) else None
            self._play_mark = time.monotonic() if self.speed is not None else None
            if self.speed is not None:
                self._wake()
            return True
        elif key == "m":
            from datetime import timezone
            scene = Scene(self.moment().astimezone(timezone.utc), self.lat, self.lng)
            if scene.moon_alt < 0.0:
                return False
            changed = cam.fly_to(scene.moon_az, max(cam.alt, min(60.0, scene.moon_alt)))
        elif key in "12345678" and key:
            changed = cam.fly_to((int(key) - 1) * 45.0, cam.alt if cam.alt < 75.0 else 20.0)
        elif key == "9":
            changed = cam.fly_to(cam.az, 90.0)
        else:
            return False
        if changed:
            self._wake()
        return changed

    def on_drag(self, dcol, drow, done):
        if done:
            moved = self.camera.release()
            if self.camera.moving():
                self._wake()
            return moved
        return self.camera.drag(dcol, drow)

    def on_click(self, col, row):
        return False

    def stop(self):
        self.speed = None


def place_name(lat, lng, override):
    """The place for the status line: the geocoder's label for a place-name
    override, else the (cached) reverse geocoder's, else the coordinates."""
    from linecast._location import resolve_location
    label = ""
    try:
        if override:
            _lat, _lng, _country, label = resolve_location(override, return_label=True)
    except SystemExit:
        label = ""
    if not label:
        try:
            from linecast._weather_sources import _reverse_geocode
            label = _reverse_geocode(lat, lng)[0] or ""
        except Exception:
            label = ""
    return label.split(",")[0].strip() or f"{lat:.2f},{lng:.2f}"
