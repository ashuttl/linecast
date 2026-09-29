"""The live sunshine view: the day's arc and the year, and the keys
between them.

A wheel notch or arrow key scrubs the day view a quarter of an hour;
the year view takes them without moving, since the mouse hovers it
instead. v flips between the two, and y still does, since the year
view is --year's. The two keep their own place, so flipping returns to
where each was left, and space brings the day back to now.
"""

from datetime import timedelta

from linecast.terminal.live import LiveApp
from linecast.sunshine.view import _offset_hours, render


class SunshineApp(LiveApp):
    """The live sunshine view: which view is up, and how far the day is
    scrubbed."""

    def __init__(self, now_fn, lat, lng, runtime, tz=None, hours_at=None, year=False,
                 dst=False, location_label=""):
        self.now_fn = now_fn
        self.lat, self.lng = lat, lng
        self.runtime = runtime
        self.tz = tz              # the place's zone, or None for the machine's
        self.hours_at = hours_at  # callable(moment) -> the traditional hours, or None
        self.dst = dst
        self.location_label = location_label
        self.year = year          # the year view is up
        self.minutes = 0          # the day view's scrub

    @property
    def help_view(self):
        # The controls follow the view on screen
        return 'sunshine_year' if self.year else 'sunshine'

    def render(self, mouse_pos=None, **_):
        # The loop's offset_minutes goes unused: the day view keeps its
        # own scrub (step), which the year view leaves where it was.
        fullscreen = self.runtime.live
        if self.year:
            from linecast.sunshine.year import render_year
            return render_year(
                self.lat, self.lng, self.now_fn(), self.runtime, tz=self.tz,
                fullscreen=fullscreen, dst=self.dst,
                location_label=self.location_label, mouse_pos=mouse_pos,
            )
        now = self.now_fn()
        if self.minutes:
            now = now + timedelta(minutes=self.minutes)
        doy = now.timetuple().tm_yday
        now_hour = now.hour + now.minute / 60 + now.second / 3600
        return render(
            self.lat,
            self.lng,
            doy,
            now_hour,
            fullscreen=fullscreen,
            offset_minutes=self.minutes,
            runtime=self.runtime,
            tz_offset_h=_offset_hours(now),
            location_label=self.location_label,
            now=now,
            hours=self.hours_at(now) if self.hours_at else None,
        )

    def step(self, n):
        """n quarter hours through the day; the year view stays put."""
        if not self.year:
            self.minutes += self.scroll_step * n
        return True

    def intercept(self, action):
        if action == "fwd":
            return self.step(1)
        if action == "back":
            return self.step(-1)
        if action == "reset":
            self.minutes = 0
            return True
        return False

    def on_wheel(self, direction, _col, _row):
        return self.step(direction)

    def on_action(self, key):
        if key in ("v", "y"):
            self.year = not self.year
            return True
        return False
