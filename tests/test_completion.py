import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

from linecast import __main__ as cli
from linecast._completion import available_shells, render_completion


class CompletionScriptTests(unittest.TestCase):
    def test_available_shells(self):
        self.assertEqual(available_shells(), ("bash", "zsh", "fish", "nu", "nushell"))

    def test_nu_completion_includes_namespace_and_standalone_commands(self):
        script = render_completion("nu")
        self.assertEqual(script, render_completion("nushell"))
        self.assertIn('export extern "linecast"', script)
        self.assertIn('export extern "linecast weather"', script)
        self.assertIn('export extern "linecast tides"', script)
        self.assertIn('export extern "linecast sunshine"', script)
        self.assertIn('export extern "linecast moon"', script)
        self.assertIn('export extern "linecast radar"', script)
        self.assertIn('export extern "linecast maps"', script)
        self.assertIn('export extern "linecast location"', script)
        self.assertIn('export extern "linecast units"', script)
        self.assertIn('export extern "linecast completion"', script)
        self.assertIn('export extern "weather"', script)
        self.assertIn('export extern "tides"', script)
        self.assertIn('export extern "sunshine"', script)
        self.assertIn('export extern "moon"', script)
        self.assertIn('export extern "radar"', script)
        self.assertIn('export extern "maps"', script)
        self.assertIn('export extern "location"', script)
        self.assertIn('export extern "units"', script)
        self.assertIn('nu-complete linecast-units-subcommands', script)
        self.assertIn('--metric', script)
        self.assertIn('--theme', script)
        self.assertIn('--lang', script)
        # --help and -h must be omitted so Nushell does not hijack help display
        self.assertNotIn('--help', script)
        self.assertNotIn('-h', script)

    def test_bash_completion_includes_namespace_and_standalone_commands(self):
        script = render_completion("bash")
        self.assertIn("complete -F _linecast_complete linecast", script)
        self.assertIn("complete -F _linecast_complete_weather weather", script)
        self.assertIn("complete -F _linecast_complete_tides tides", script)
        self.assertIn("complete -F _linecast_complete_sunshine sunshine", script)
        self.assertIn("complete -F _linecast_complete_moon moon", script)
        self.assertIn("complete -F _linecast_complete_radar radar", script)

    def test_zsh_completion_includes_namespace_and_standalone_commands(self):
        script = render_completion("zsh")
        self.assertIn("compdef _linecast linecast weather sunshine moon tides radar maps",
                      script)
        self.assertIn("_linecast_complete_command", script)

    def test_fish_completion_includes_namespace_and_standalone_commands(self):
        script = render_completion("fish")
        self.assertIn(
            "complete -c linecast -f -n '__fish_use_subcommand' -a 'weather sunshine moon tides radar maps location units completion'",
            script,
        )
        self.assertIn(
            "complete -c linecast -f -n '__fish_seen_subcommand_from location' -a 'show set auto search'",
            script,
        )
        self.assertIn(
            "complete -c linecast -f -n '__fish_seen_subcommand_from units' -a 'show metric imperial auto'",
            script,
        )
        self.assertIn("complete -c weather -f -l print", script)
        self.assertIn("complete -c tides -f -l station -r", script)
        self.assertIn("complete -c sunshine -f -l print", script)
        self.assertIn("complete -c moon -f -l print", script)
        self.assertIn("complete -c radar -f -l theme -r -a 'terminal", script)

    def test_radar_theme_values_track_source_themes(self):
        from linecast._completion import THEME_VALUES
        from linecast._radar_sources import THEMES
        self.assertEqual(tuple(THEMES), THEME_VALUES)

    def test_invalid_shell_raises(self):
        with self.assertRaises(ValueError):
            render_completion("powershell")


class CompletionCommandTests(unittest.TestCase):
    def _run_main(self, *args):
        old_argv = sys.argv
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            sys.argv = ["linecast", *args]
            with redirect_stdout(stdout), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exc:
                    cli.main()
            return exc.exception.code, stdout.getvalue(), stderr.getvalue()
        finally:
            sys.argv = old_argv

    def test_completion_subcommand_prints_script(self):
        code, out, err = self._run_main("completion", "bash")
        self.assertEqual(code, 0)
        self.assertIn("complete -F _linecast_complete linecast", out)
        self.assertEqual(err, "")

    def test_completion_subcommand_prints_script_nu(self):
        for shell in ("nu", "nushell"):
            code, out, err = self._run_main("completion", shell)
            self.assertEqual(code, 0)
            self.assertIn('export extern "linecast"', out)
            self.assertEqual(err, "")

    def test_completion_subcommand_help(self):
        code, out, err = self._run_main("completion", "--help")
        self.assertEqual(code, 0)
        self.assertIn("Usage: linecast completion <shell>", out)
        self.assertEqual(err, "")

    def test_completion_subcommand_unknown_shell(self):
        code, out, err = self._run_main("completion", "pwsh")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("unknown shell", err)


if __name__ == "__main__":
    unittest.main()
