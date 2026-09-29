"""The live moon view: the disc and the month calendar, and the keys
between them.

A wheel notch or arrow key scrubs the disc view a quarter of an hour
and the calendar a month; space returns each to now. The two keep their
own place, so flipping between them with v returns to where each was
left. On the disc view t puts the text away, leaving the Moon alone in
its sky, and brings it back, and a drag turns the Moon, which settles
back when let go. A click on a calendar day opens the disc view on that
day, at this hour.
"""

from datetime import timedelta, timezone

from linecast._i18n import lang_of
from linecast.astro.calendars.civil import SOLAR_HIJRI, civil_calendar
from linecast.moon.disc import Turn
from linecast.moon.view import next_year_turn, place_credit, render
from linecast.terminal import bidi as _bidi
from linecast.terminal.live import LiveApp


class MoonApp(LiveApp):
    """The live moon view: which view is up, how far each is scrubbed,
    whether the disc view's text is showing, and the way the disc has
    been turned."""

    def __init__(self, now_fn, lat, lng, runtime, calendar_name=None, israel=False,
                 month=False, place=""):
        self.now_fn = now_fn
        self.lat, self.lng = lat, lng
        self.runtime = runtime
        self.calendar_name = calendar_name   # the traditional calendar, or None
        self.israel = israel                 # the place keeps Israel's holidays
        self.month = month                   # the calendar view is up
        self.minutes = 0                     # the disc view's scrub
        self.months = 0                      # the calendar's
        self.text = True                     # the disc view's corners are showing
        self.turn = Turn()
        self.place = place                   # the place's name, for help
        self.solar_hijri = civil_calendar(lang_of(runtime)) == SOLAR_HIJRI

    def interval(self):
        """Seconds to the next repaint: once a minute, except in the last
        day before the Solar Hijri year turns, when the panel counts down
        to the second. Asked at every repaint, so a view left open
        reaches the last day too."""
        if self.solar_hijri:
            now = self.now_fn()
            if next_year_turn(now)[1] - now.astimezone(timezone.utc) < timedelta(days=1):
                return 1
        return 60

    def name_the_place(self):
        """Ask the (cached) reverse geocoder what the place is called:
        run off the loop, since it may go to the network."""
        from linecast._geocode import place_label
        self.place = place_label(self.lat, self.lng, self.place, self.runtime.lang)

    @property
    def help_view(self):
        return 'moon_calendar' if self.month else 'moon'

    def help_panel(self):
        # The controls follow the view on screen, and help credits the
        # place the Moon is seen from, where the weather's names its
        # sources.
        from linecast.terminal.help import HelpPanel, entries
        return HelpPanel(None, self.runtime.lang, content=lambda cols, rows: entries(
            self.help_view, self.runtime.lang,
            credits=(place_credit(self.lat, self.lng, self.place, self.runtime),)))

    def render(self, mouse_pos=None, **_):
        # The loop's offset_minutes goes unused: each view keeps its own
        # scrub (step).
        if self.month:
            from linecast.moon.calendar import render_calendar
            return render_calendar(self.now_fn(), self.lat, self.lng, self.runtime,
                                   month_offset=self.months,
                                   fullscreen=self.runtime.live, mouse_pos=mouse_pos,
                                   calendar_name=self.calendar_name, israel=self.israel)
        moment = self.now_fn()
        if self.minutes:
            moment += timedelta(minutes=self.minutes)
        return render(moment, self.lat, self.lng, self.runtime,
                      fullscreen=self.runtime.live, offset_minutes=self.minutes,
                      calendar_name=self.calendar_name, israel=self.israel,
                      turn=self.turn, show_text=self.text)

    def step(self, n):
        """n months of the calendar, or n quarter hours of the disc."""
        if self.month:
            self.months += n
        else:
            self.minutes += self.scroll_step * n
        return True

    def intercept(self, action):
        if action == "fwd":
            return self.step(1)
        if action == "back":
            return self.step(-1)
        if action == "reset":
            if self.month:
                self.months = 0
            else:
                self.minutes = 0
            return True
        return False

    def on_wheel(self, direction, _col, _row):
        return self.step(direction)

    def on_action(self, key):
        if key == "v":
            self.month = not self.month
            return True
        if key == "t" and not self.month:
            # Put the text away, and leave the Moon alone in its sky.
            self.text = not self.text
            return True
        return False

    def on_drag(self, dcol, drow, done):
        # Drag the disc to turn the Moon; let go and it settles back.
        # The calendar has nothing to drag, but the loop only tracks
        # clicks while a drag callback is set, so it answers here too.
        if self.month:
            return False
        # The disc is never mirrored, so a drag turns it the way the
        # hand moved even when the view reads from the right
        if _bidi.mirrored():
            dcol = -dcol
        return self.turn.release() if done else self.turn.drag(dcol, drow)

    def on_click(self, col, row):
        # A calendar day is a doorway: click it and the disc view opens
        # on that day, at this hour, with space the way back to now.
        if not self.month:
            return False
        from linecast.moon.calendar import clicked_day
        target = clicked_day(col, row)
        if target is None:
            return False
        self.minutes = (target - self.now_fn().date()).days * 1440
        self.month = False
        return True
