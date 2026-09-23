"""argv[0] dispatch: a binary named for a command runs that command.

A distro package ships the short commands as symlinks to the linecast
binary and leaves out any name another package already owns, so the
dispatcher must honour the name it was invoked by before it reads a
single argument.
"""

import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

from linecast import __main__ as cli


class Argv0DispatchTests(unittest.TestCase):
    def _dispatch(self, argv0, *args):
        """Run cli.main() with a stubbed import; report what it ran."""
        ran = {}

        def fake_import(name):
            ran["module"] = name
            return mock.Mock(main=lambda: ran.setdefault("argv", list(sys.argv)))

        old_argv = sys.argv
        try:
            sys.argv = [argv0, *args]
            with mock.patch("importlib.import_module", side_effect=fake_import):
                cli.main()
        finally:
            sys.argv = old_argv
        return ran

    def test_symlink_name_runs_the_command(self):
        ran = self._dispatch("/usr/bin/tides", "--print")
        self.assertEqual(ran["module"], "linecast.tides")
        self.assertEqual(ran["argv"], ["linecast tides", "--print"])

    def test_symlink_name_with_no_arguments(self):
        ran = self._dispatch("/usr/local/bin/weather")
        self.assertEqual(ran["module"], "linecast.weather.view")
        self.assertEqual(ran["argv"], ["linecast weather"])

    def test_windows_copy_with_exe_suffix(self):
        # os.path splits the directories per-platform; the case and the
        # extension are what the dispatcher itself must absorb.
        ran = self._dispatch("Sunshine.EXE", "--json")
        self.assertEqual(ran["module"], "linecast.sunshine")
        self.assertEqual(ran["argv"], ["linecast sunshine", "--json"])

    def test_flags_pass_through_untouched(self):
        # `weather --help` is the weather command's help, not the
        # dispatcher's: the name decides before the arguments do.
        ran = self._dispatch("/usr/bin/weather", "--help")
        self.assertEqual(ran["module"], "linecast.weather.view")
        self.assertEqual(ran["argv"], ["linecast weather", "--help"])

    def test_subcommand_still_dispatches(self):
        ran = self._dispatch("/usr/bin/linecast", "moon", "--oneline")
        self.assertEqual(ran["module"], "linecast.moon.view")
        self.assertEqual(ran["argv"], ["linecast moon", "--oneline"])

    def test_clock_dispatches_and_is_listed_in_help(self):
        ran = self._dispatch("/usr/bin/linecast", "clock", "12")
        self.assertEqual(ran["module"], "linecast.clock")
        self.assertEqual(ran["argv"], ["linecast clock", "12"])
        self.assertIn("linecast clock", self._help_output("/usr/bin/linecast"))

    def test_every_standalone_name_is_a_command(self):
        for name in cli.STANDALONE:
            with self.subTest(name=name):
                ran = self._dispatch(f"/usr/bin/{name}")
                self.assertEqual(ran["module"], cli.COMMANDS[name])

    def _help_output(self, argv0):
        old_argv = sys.argv
        out = StringIO()
        try:
            sys.argv = [argv0]
            with redirect_stdout(out), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    cli.main()
        finally:
            sys.argv = old_argv
        self.assertEqual(exc.exception.code, 0)
        return out.getvalue()

    def _unwrapped_help(self, argv0):
        # argparse wraps the page to the terminal; a sentence is compared
        # on one line
        return " ".join(self._help_output(argv0).split())

    def _expect_help(self, argv0):
        self.assertIn("linecast weather", self._help_output(argv0))

    def test_plain_linecast_is_not_dispatched(self):
        self._expect_help("/usr/bin/linecast")

    def test_utility_names_are_not_dispatched(self):
        # location, units and doctor have no standalone spelling; a
        # binary named for one behaves as plain linecast.
        self._expect_help("/usr/bin/doctor")

    def test_python_m_linecast_is_not_dispatched(self):
        self._expect_help("/somewhere/linecast/__main__.py")

    def test_help_names_every_command(self):
        out = self._help_output("/usr/bin/linecast")
        for name in (*cli.COMMANDS, "completion"):
            with self.subTest(name=name):
                self.assertIn(f"  linecast {name} ", out)

    def test_help_names_every_language(self):
        from linecast._i18n import LANGUAGE_CODES
        out = self._help_output("/usr/bin/linecast")
        for code in LANGUAGE_CODES:
            with self.subTest(code=code):
                self.assertRegex(out, rf"\b{code}\b")

    def test_help_names_every_calendar(self):
        from linecast._config import CALENDAR_CHOICES
        out = self._help_output("/usr/bin/linecast")
        for name in CALENDAR_CHOICES:
            with self.subTest(name=name):
                self.assertRegex(out, rf"\b{name}\b")

    def test_help_shares_the_commands_own_blurbs(self):
        # `linecast --help` and `linecast weather --help` open with the
        # same line, so the two pages cannot drift
        from linecast._runtime import weather_parser, maps_parser
        for parser in (weather_parser(), maps_parser()):
            with self.subTest(prog=parser.prog):
                self.assertIn(parser.description, self._unwrapped_help("/usr/bin/linecast"))

    def test_help_ends_with_the_moon_tonight(self):
        # The one thing the help page can say about the sky without a
        # place or a network: the phase, from the clock alone.
        out = self._help_output("/usr/bin/linecast")
        self.assertRegex(out.rstrip().splitlines()[-1], r"^\S+ \w[\w ]+, \d+% lit$")

    def test_help_survives_the_moon_going_wrong(self):
        with mock.patch("linecast.sunshine.moon_phase", side_effect=RuntimeError("no sky")):
            out = self._unwrapped_help("/usr/bin/linecast")
        self.assertTrue(out.endswith("Run any command with --help for options."))


if __name__ == "__main__":
    unittest.main()


class ScriptModeStdlibShadowTests(unittest.TestCase):
    def test_a_reader_that_closes_early_is_not_an_error(self):
        """`linecast ... | head` ends with EPIPE on stdout; the run exits
        quietly, with nothing on stderr, and not a second time from the
        interpreter flushing the same broken pipe on its way out."""
        import os
        import subprocess
        import sys
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "src"
        read_end, write_end = os.pipe()
        os.close(read_end)   # the reader is gone before a byte is written
        try:
            result = subprocess.run(
                [sys.executable, "-m", "linecast", "--help"],
                stdin=subprocess.DEVNULL, stdout=write_end, stderr=subprocess.PIPE,
                text=True, env=dict(os.environ, PYTHONPATH=str(src)), timeout=60,
            )
        finally:
            os.close(write_end)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_running_a_command_file_directly_keeps_the_stdlib_calendar(self):
        """python src/linecast/moon.py must not shadow stdlib modules.

        Running a file inside the package as a script puts the package
        directory itself first on sys.path, so a module named after a
        standard library one (the calendar command was briefly
        calendar.py) breaks every `import calendar` in the package.
        """
        import subprocess
        import sys
        from pathlib import Path

        package = Path(__file__).resolve().parent.parent / "src" / "linecast"
        code = (
            "import sys; sys.path.insert(0, r'%s'); "
            "import calendar; calendar.isleap(2026)" % package
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
