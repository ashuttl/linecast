import io
import unittest
from contextlib import redirect_stdout

from linecast import _config, calendar_cmd
from test_units import ConfigDirMixin


class CalendarCommandTests(ConfigDirMixin):
    def test_set_saves_and_show_reports_it(self):
        with redirect_stdout(io.StringIO()):
            calendar_cmd._cmd_set("hebrew")
        self.assertEqual(_config.saved_calendar(), "hebrew")

        out = io.StringIO()
        with redirect_stdout(out):
            calendar_cmd._cmd_show()
        self.assertIn("hebrew  [fixed]", out.getvalue())

    def test_none_is_saved_as_a_choice_of_its_own(self):
        """'none' pins the calendar off; it is not the same as auto."""
        with redirect_stdout(io.StringIO()):
            calendar_cmd._cmd_set("none")
        self.assertEqual(_config.saved_calendar(), "none")

        out = io.StringIO()
        with redirect_stdout(out):
            calendar_cmd._cmd_show()
        self.assertIn("none  [fixed]", out.getvalue())

    def test_auto_clears_the_saved_calendar(self):
        with redirect_stdout(io.StringIO()):
            calendar_cmd._cmd_set("islamic")
            calendar_cmd._cmd_auto()
        self.assertIsNone(_config.saved_calendar())

        out = io.StringIO()
        with redirect_stdout(out):
            calendar_cmd._cmd_show()
        self.assertTrue(out.getvalue().startswith("auto"))

    def test_auto_leaves_the_other_settings_alone(self):
        _config.write_config({"units": "metric", "calendar": "thai"})
        with redirect_stdout(io.StringIO()):
            calendar_cmd._cmd_auto()
        self.assertIsNone(_config.saved_calendar())
        self.assertEqual(_config.saved_units(), "metric")

    def test_saved_calendar_ignores_junk_values(self):
        _config.write_config({"calendar": "mayan"})
        self.assertIsNone(_config.saved_calendar())

    def test_every_choice_has_a_confirmation(self):
        """Each name is echoed back in its confirmation, and 'none' says
        the calendar is off."""
        for choice in _config.CALENDAR_CHOICES:
            out = io.StringIO()
            with redirect_stdout(out), self.subTest(choice=choice):
                calendar_cmd._cmd_set(choice)
                self.assertIn("turned off" if choice == "none" else choice,
                              out.getvalue())


if __name__ == "__main__":
    unittest.main()
