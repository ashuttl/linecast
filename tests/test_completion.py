import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

from linecast import __main__ as cli
from linecast._completion import available_shells, render_completion


class CompletionScriptTests(unittest.TestCase):
    def test_available_shells(self):
        self.assertEqual(available_shells(), ("bash", "zsh", "fish"))

    def test_bash_completion_includes_namespace_and_standalone_commands(self):
        script = render_completion("bash")
        self.assertIn("complete -F _linecast_complete linecast", script)
        self.assertIn("complete -F _linecast_complete_weather weather", script)
        self.assertIn("complete -F _linecast_complete_tides tides", script)
        self.assertIn("complete -F _linecast_complete_sunshine sunshine", script)

    def test_zsh_completion_includes_namespace_and_standalone_commands(self):
        script = render_completion("zsh")
        self.assertIn("compdef _linecast linecast weather sunshine tides", script)
        self.assertIn("_linecast_complete_command", script)

    def test_fish_completion_includes_namespace_and_standalone_commands(self):
        script = render_completion("fish")
        self.assertIn(
            "complete -c linecast -f -n '__fish_use_subcommand' -a 'weather sunshine tides completion'",
            script,
        )
        self.assertIn("complete -c weather -f -l print", script)
        self.assertIn("complete -c tides -f -l station -r", script)
        self.assertIn("complete -c sunshine -f -l print", script)

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
