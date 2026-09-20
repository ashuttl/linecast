import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from linecast import __main__ as cli
from linecast import _runtime
from linecast._completion import COMMANDS, available_shells, render_completion
from linecast.link import link_parser


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
        self.assertIn('export extern "linecast doctor"', script)
        # The settings commands have no short name (__main__.STANDALONE
        # is the seven views), and an extern named `units` or `calendar`
        # would have nushell parse some other program's arguments by
        # linecast's signature and refuse them.
        self.assertNotIn('export extern "location"', script)
        self.assertNotIn('export extern "units"', script)
        self.assertNotIn('export extern "doctor"', script)
        self.assertIn('nu-complete linecast-units-subcommands', script)
        self.assertIn('--metric', script)
        self.assertIn('--theme', script)
        self.assertIn('--lang', script)
        # --help and -h must be omitted so Nushell does not hijack help display
        self.assertNotIn('--help', script)
        # -h as a flag, not the "-h" inside "linecast-hours"
        self.assertNotRegex(script, r'(?<![\w-])-h\b')

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
        self.assertIn("compdef _linecast linecast weather sunshine moon sky tides radar maps",
                      script)
        self.assertIn("_linecast_complete_command", script)

    def test_fish_completion_includes_namespace_and_standalone_commands(self):
        script = render_completion("fish")
        self.assertIn(
            "complete -c linecast -f -n '__fish_use_subcommand' "
            "-a 'weather sunshine moon sky tides radar maps location language units clock "
            "week icons calendar culture hours link doctor completion'",
            script,
        )
        self.assertIn(
            "complete -c linecast -f -n '__fish_seen_subcommand_from location' "
            "-a 'show set auto search'",
            script,
        )
        self.assertIn(
            "complete -c linecast -f -n '__fish_seen_subcommand_from units' "
            "-a 'show metric imperial auto'",
            script,
        )
        self.assertIn("complete -c weather -f -l print", script)
        self.assertIn("complete -c tides -f -l station -r", script)
        self.assertIn("complete -c sunshine -f -l print", script)
        self.assertIn("complete -c moon -f -l print", script)
        self.assertIn("complete -c radar -f -l theme -r -a 'terminal", script)

    def test_fish_completion_offers_every_shell(self):
        script = render_completion("fish")
        self.assertIn(
            "complete -c linecast -f -n '__fish_seen_subcommand_from completion' "
            "-a 'bash zsh fish nu nushell'",
            script,
        )

    def test_radar_theme_values_track_source_themes(self):
        from linecast._radar_sources import THEMES
        themes = " ".join(THEMES)
        self.assertIn(f"complete -c radar -f -l theme -r -a '{themes}'",
                      render_completion("fish"))

    def test_value_list_variables_are_shell_identifiers(self):
        """--week-start and --temp-range hold value lists; the variable
        that carries one must not carry the flag's hyphen (#108)."""
        identifier = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        for shell, pattern in (
            ("bash", r"^(_linecast_\S+?_values)="),
            ("zsh", r"^typeset -ga (\S+)$"),
        ):
            script = render_completion(shell)
            names = re.findall(pattern, script, re.MULTILINE)
            with self.subTest(shell=shell):
                self.assertIn("_linecast_week_start_values", names)
                self.assertIn("_linecast_temp_range_values", names)
                for name in names:
                    self.assertRegex(name, identifier)
                self.assertNotIn("-start_values", script)
                self.assertNotIn("-range_values", script)

    def _run_in_shell(self, shell, script, command, name=None):
        """Write `script` to a file and run `command` in `shell` with no
        user config, the file's path in $1 (or $argv[1] in fish); return
        what it prints. nushell reads its path at parse time, so there
        the path is spliced into the command in single quotes, which
        nushell reads with no escapes at all. `name` fixes the file's
        basename, for a zsh function file that fpath must find as
        _linecast.

        A shell that is not installed skips the test, unless the shell
        is named in LINECAST_REQUIRE_SHELLS: CI sets that where it has
        installed the shells, so a missing one fails instead of quietly
        skipping (#108 shipped through a skip)."""
        exe = shutil.which(shell)
        if exe is None:
            required = os.environ.get("LINECAST_REQUIRE_SHELLS", "").split()
            if shell in required:
                self.fail(f"{shell} is required here and is not installed")
            self.skipTest(f"{shell} is not installed")
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, name or f"completion.{shell}")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        try:
            # The path rides as an argument so a Windows path's
            # backslashes are not read as escapes.
            if shell == "nu":
                argv = [exe, "-n", "-c", command.replace("$1", f"'{path}'")]
            elif shell == "fish":
                argv = [exe, "--no-config", "-c", command.replace("$1", "$argv[1]"),
                        path]
            else:
                argv = [exe, "-f", "-c", command, exe, path]
            result = subprocess.run(argv, capture_output=True, text=True,
                                    check=False)
        finally:
            shutil.rmtree(directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout.strip()

    def test_bash_completion_sources_cleanly(self):
        out = self._run_in_shell(
            "bash", render_completion("bash"),
            'source "$1" && echo "$_linecast_week_start_values"')
        self.assertEqual(out, "monday sunday saturday")

    def test_bash_completes_a_hyphenated_flags_values(self):
        """Not just that the script loads: bash's own completion entry
        point, fed the words on the line, offers the flag's values.
        --week-start is the flag whose hyphen broke the scripts (#108)."""
        out = self._run_in_shell(
            "bash", render_completion("bash"),
            'source "$1" && COMP_WORDS=(linecast moon --week-start s) '
            '&& COMP_CWORD=3 && _linecast_complete '
            '&& printf "%s\\n" "${COMPREPLY[@]}"')
        self.assertEqual(out.split(), ["sunday", "saturday"])

    def test_bash_completes_the_short_names(self):
        out = self._run_in_shell(
            "bash", render_completion("bash"),
            'source "$1" && COMP_WORDS=(moon --week-start "") '
            '&& COMP_CWORD=2 && _linecast_complete_moon '
            '&& printf "%s\\n" "${COMPREPLY[@]}"')
        self.assertEqual(out.split(), ["monday", "sunday", "saturday"])

    def test_bash_completes_a_value_after_an_equals_sign(self):
        """bash's default COMP_WORDBREAKS has = in it, so `--lang=f`
        reaches the function as --lang, = and f, and `--lang=` with the
        = as the word being completed; both must offer the values."""
        out = self._run_in_shell(
            "bash", render_completion("bash"),
            'source "$1" && COMP_WORDS=(linecast weather --lang = f) '
            '&& COMP_CWORD=4 && _linecast_complete '
            '&& printf "%s\\n" "${COMPREPLY[@]}"')
        self.assertEqual(out.split(), ["fr", "fi", "fr-CA"])
        out = self._run_in_shell(
            "bash", render_completion("bash"),
            'source "$1" && COMP_WORDS=(linecast moon --week-start =) '
            '&& COMP_CWORD=3 && _linecast_complete '
            '&& printf "%s\\n" "${COMPREPLY[@]}"')
        self.assertEqual(out.split(), ["monday", "sunday", "saturday"])
        # With = taken out of COMP_WORDBREAKS the flag and value are one
        # word, and the reply must carry the flag back.
        out = self._run_in_shell(
            "bash", render_completion("bash"),
            'source "$1" && COMP_WORDS=(linecast weather --lang=f) '
            '&& COMP_CWORD=2 && _linecast_complete '
            '&& printf "%s\\n" "${COMPREPLY[@]}"')
        self.assertEqual(out.split(), ["--lang=fr", "--lang=fi", "--lang=fr-CA"])

    def test_bash_offers_the_flag_being_typed(self):
        """The word under the cursor is not a flag already given: --lay
        must reach --layer beside --layers, and a flag typed in full is
        still offered so bash appends its space. A flag given earlier
        on the line is still left out."""
        out = self._run_in_shell(
            "bash", render_completion("bash"),
            'source "$1" && COMP_WORDS=(linecast radar --layer) '
            '&& COMP_CWORD=2 && _linecast_complete '
            '&& printf "%s\\n" "${COMPREPLY[@]}"')
        self.assertEqual(out.split(), ["--layer", "--layers"])
        out = self._run_in_shell(
            "bash", render_completion("bash"),
            'source "$1" && COMP_WORDS=(weather --print) '
            '&& COMP_CWORD=1 && _linecast_complete_weather '
            '&& printf "%s\\n" "${COMPREPLY[@]}"')
        self.assertEqual(out.split(), ["--print"])
        out = self._run_in_shell(
            "bash", render_completion("bash"),
            'source "$1" && COMP_WORDS=(linecast weather --print --) '
            '&& COMP_CWORD=3 && _linecast_complete '
            '&& printf "%s\\n" "${COMPREPLY[@]}"')
        self.assertNotIn("--print", out.split())
        self.assertIn("--json", out.split())

    def test_zsh_completion_sources_cleanly(self):
        """The README's `source <(linecast completion zsh)` must not
        fail; `compdef` is stubbed because -f skips compinit."""
        out = self._run_in_shell(
            "zsh", render_completion("zsh"),
            'compdef() { : }; source "$1" '
            '&& print -r -- "${_linecast_week_start_values[@]}"')
        self.assertEqual(out, "monday sunday saturday")

    # A stand-in for zsh's compadd that prints what it was given; the
    # real one filters by the word under the cursor, this one shows the
    # whole offer, `--` first.
    _ZSH_STUBS = 'compdef() { : }; compadd() { print -r -- "$@" }; '

    def test_zsh_completes_through_autoload(self):
        """Saved as _linecast in fpath, the #compdef route: the file is
        the body of the autoloaded function, so its value lists must be
        globals, and it must complete the line it was called for, on
        the first call and every one after."""
        out = self._run_in_shell(
            "zsh", render_completion("zsh"),
            self._ZSH_STUBS + 'fpath=("${1:h}" $fpath); autoload -Uz _linecast; '
            'words=(linecast moon --week-start s); CURRENT=4; '
            '_linecast; _linecast',
            name="_linecast")
        self.assertEqual(out.splitlines(), ["-- monday sunday saturday"] * 2)

    def test_zsh_offers_the_flag_being_typed(self):
        """The word under the cursor is not a flag already given: --lay
        must reach --layer beside --layers. A flag given earlier on the
        line is still left out."""
        out = self._run_in_shell(
            "zsh", render_completion("zsh"),
            self._ZSH_STUBS + 'source "$1"; '
            'words=(linecast radar --layer); CURRENT=3; _linecast')
        self.assertIn("--layer", out.split())
        self.assertIn("--layers", out.split())
        out = self._run_in_shell(
            "zsh", render_completion("zsh"),
            self._ZSH_STUBS + 'source "$1"; '
            'words=(linecast weather --print --); CURRENT=4; _linecast')
        self.assertNotIn("--print", out.split())
        self.assertIn("--json", out.split())

    def test_fish_completes_a_hyphenated_flags_values(self):
        """The README's `linecast completion fish | source`, then fish's
        own completer asked what it would offer on the line."""
        out = self._run_in_shell(
            "fish", render_completion("fish"),
            'source $1; and complete -C "linecast moon --week-start s"')
        self.assertEqual(sorted(out.split()), ["saturday", "sunday"])
        out = self._run_in_shell(
            "fish", render_completion("fish"),
            'source $1; and complete -C "moon --week-start "')
        self.assertEqual(sorted(out.split()), ["monday", "saturday", "sunday"])

    def test_nu_completion_loads_as_a_module(self):
        """The README's `use linecast_completions.nu *`: nushell parses
        the whole file, and the flag's completer is wired to its extern."""
        out = self._run_in_shell(
            "nu", render_completion("nu"),
            "use $1 *; scope commands | where name == 'linecast moon' "
            "| get 0.signatures.any | where parameter_name == 'week-start' "
            "| get 0.completion")
        self.assertEqual(out, "nu-complete linecast-week-start")
        out = self._run_in_shell(
            "nu", render_completion("nu"),
            "source $1; nu-complete linecast-week-start | str join ' '")
        self.assertEqual(out, "monday sunday saturday")

    def test_invalid_shell_raises(self):
        with self.assertRaises(ValueError):
            render_completion("powershell")

    def test_doctor_flags_track_its_parser(self):
        """doctor is not a standalone binary, so its flags are listed by
        hand; they must still be the parser's."""
        from linecast._completion import DOCTOR_FLAGS
        parser = _runtime.doctor_parser()
        expected = {o for a in parser._actions for o in a.option_strings}
        self.assertEqual(set(DOCTOR_FLAGS), expected)
        bash = render_completion("bash")
        zsh = render_completion("zsh")
        fish = render_completion("fish")
        nu = render_completion("nu")
        for flag in expected:
            if flag.startswith("--"):
                self.assertIn(
                    f"complete -c linecast -f -n '__fish_seen_subcommand_from doctor' "
                    f"-l {flag[2:]}", fish)
        self.assertIn(f"    doctor)\n      _linecast_complete_flags {' '.join(DOCTOR_FLAGS)}",
                      bash)
        self.assertIn(f"    doctor)\n      _linecast_add_flags {' '.join(DOCTOR_FLAGS)}",
                      zsh)
        self.assertIn("    --offline\n    --json\n    --debug\n]", nu)

    def test_top_level_commands_track_the_dispatcher(self):
        """The `linecast` dispatcher's table is hand-rolled, and so is the
        completion's list of its commands; a command added to one must
        reach the other."""
        from linecast._completion import TOP_LEVEL_COMMANDS
        self.assertEqual(set(TOP_LEVEL_COMMANDS), set(cli.COMMANDS) | {"completion"})
        for shell in ("bash", "zsh", "fish", "nu"):
            script = render_completion(shell)
            for command in cli.COMMANDS:
                with self.subTest(shell=shell, command=command):
                    self.assertIn(command, script)

    def test_standalone_names_track_the_dispatcher(self):
        """Every shell registers the short names the binary answers to
        as argv[0], and no others: a nushell extern named for a command
        linecast does not own would parse that program's arguments by
        linecast's signature and refuse them."""
        expected = set(cli.STANDALONE)
        bash = render_completion("bash")
        self.assertEqual(
            set(re.findall(r"^complete -F _linecast_complete_\w+ (\S+)$", bash, re.M)),
            expected)
        zsh = render_completion("zsh")
        self.assertEqual(set(re.search(r"^\s*compdef _linecast linecast (.*)$", zsh,
                                       re.M).group(1).split()), expected)
        fish = render_completion("fish")
        self.assertEqual(set(re.findall(r"^complete -c (?!linecast\b)(\S+) ", fish, re.M)),
                         expected)
        nu = render_completion("nu")
        bare = set(re.findall(r'^export extern "(?!linecast\b)([^" ]+)', nu, re.M))
        self.assertEqual(bare, expected)

    def test_calendar_subcommands_track_its_parser(self):
        """`linecast calendar` takes the calendar names moon's --calendar
        takes, plus show and auto; every shell offers them all."""
        from linecast._completion import CALENDAR_SUBCOMMANDS
        moon_choices = self._moon_calendar_choices()
        self.assertEqual(set(CALENDAR_SUBCOMMANDS), moon_choices | {"show", "auto"})
        bash = render_completion("bash")
        zsh = render_completion("zsh")
        fish = render_completion("fish")
        nu = render_completion("nu")
        joined = " ".join(CALENDAR_SUBCOMMANDS)
        self.assertIn(f'COMPREPLY+=( $(compgen -W "{joined}" -- "$cur") )', bash)
        self.assertIn(f"compadd -- {joined}", zsh)
        self.assertIn(f"complete -c linecast -f -n '__fish_seen_subcommand_from calendar' "
                      f"-a '{joined}'", fish)
        for sub in CALENDAR_SUBCOMMANDS:
            self.assertIn(f'export extern "linecast calendar {sub}"', nu)
            self.assertNotIn(f'export extern "calendar {sub}"', nu)

    def test_hours_subcommands_track_its_parser(self):
        """`linecast hours` takes the names sunshine's --hours takes,
        plus show and auto; every shell offers them all."""
        from linecast._completion import HOURS_SUBCOMMANDS
        choices = None
        for action in _runtime.sunshine_parser()._actions:
            if "--hours" in action.option_strings:
                choices = set(action.choices)
        self.assertIsNotNone(choices, "sunshine has no --hours")
        self.assertEqual(set(HOURS_SUBCOMMANDS), choices | {"show", "auto"})
        bash = render_completion("bash")
        zsh = render_completion("zsh")
        fish = render_completion("fish")
        nu = render_completion("nu")
        joined = " ".join(HOURS_SUBCOMMANDS)
        self.assertIn(f'COMPREPLY+=( $(compgen -W "{joined}" -- "$cur") )', bash)
        self.assertIn(f"compadd -- {joined}", zsh)
        self.assertIn(f"complete -c linecast -f -n '__fish_seen_subcommand_from hours' "
                      f"-a '{joined}'", fish)
        for sub in HOURS_SUBCOMMANDS:
            self.assertIn(f'export extern "linecast hours {sub}"', nu)
            self.assertNotIn(f'export extern "hours {sub}"', nu)

    def test_language_subcommands_list_every_language(self):
        """`linecast language` takes every code linecast has strings for,
        plus show and auto; every shell offers them all."""
        from linecast._completion import LANGUAGE_SUBCOMMANDS
        from linecast._i18n import LANGUAGE_CODES, VARIANTS
        self.assertEqual(set(LANGUAGE_SUBCOMMANDS),
                         set(LANGUAGE_CODES) | set(VARIANTS) | {"show", "auto"})
        bash = render_completion("bash")
        zsh = render_completion("zsh")
        fish = render_completion("fish")
        nu = render_completion("nu")
        joined = " ".join(LANGUAGE_SUBCOMMANDS)
        self.assertIn(f'COMPREPLY+=( $(compgen -W "{joined}" -- "$cur") )', bash)
        self.assertIn(f"compadd -- {joined}", zsh)
        self.assertIn(f"complete -c linecast -f -n '__fish_seen_subcommand_from language' "
                      f"-a '{joined}'", fish)
        for sub in LANGUAGE_SUBCOMMANDS:
            self.assertIn(f'export extern "linecast language {sub}"', nu)
            self.assertNotIn(f'export extern "language {sub}"', nu)

    def _moon_calendar_choices(self):
        for action in _runtime.moon_parser()._actions:
            if "--calendar" in action.option_strings:
                return set(action.choices)
        self.fail("moon has no --calendar")


def _bash_zsh_flags(script, command):
    """The flag words in a command's case arm."""
    match = re.search(rf"^    {command}\)\n      \S+ (.*)$", script, re.M)
    return set(match.group(1).split())


def _fish_flags(script, command):
    flags = set()
    for line in script.splitlines():
        if line.startswith(f"complete -c {command} -f "):
            flags.update("--" + m for m in re.findall(r"-l (\S+)", line))
            flags.update("-" + m for m in re.findall(r"-s (\S+)", line))
    return flags


def _nu_flags(script, command):
    match = re.search(rf'^export extern "{command}" \[\n(.*?)^\]', script,
                      re.M | re.S)
    return set(re.findall(r"^    (--[\w-]+)", match.group(1), re.M))


class CompletionTracksParserTests(unittest.TestCase):
    """Every option a command's argparse parser defines is offered by
    every shell's completion, with its choices."""

    def _parser_options(self, command):
        parser = getattr(_runtime, f"{command}_parser")()
        options = {}
        for action in parser._actions:
            for option in action.option_strings:
                options[option] = action
        return options

    def test_every_parser_option_is_completed(self):
        extract = {
            "bash": _bash_zsh_flags,
            "zsh": _bash_zsh_flags,
            "fish": _fish_flags,
            "nu": _nu_flags,
        }
        for command in COMMANDS:
            expected = set(self._parser_options(command))
            for shell, flags_of in extract.items():
                with self.subTest(shell=shell, command=command):
                    offered = flags_of(render_completion(shell), command)
                    if shell == "nu":
                        # left out on purpose; see _nu_flags in _completion
                        # (--12h/--24h are not Nushell identifiers)
                        expected = expected - {"-h", "--help", "--12h", "--24h"}
                    self.assertEqual(offered, expected)

    def test_parser_choices_are_completed(self):
        scripts = {shell: render_completion(shell)
                   for shell in ("bash", "zsh", "fish", "nu")}
        checked = 0
        for command in COMMANDS:
            for option, action in self._parser_options(command).items():
                if not action.choices:
                    continue
                checked += 1
                for shell, script in scripts.items():
                    if shell == "nu":
                        values = " ".join(f'"{v}"' for v in action.choices)
                    else:
                        values = " ".join(action.choices)
                    with self.subTest(shell=shell, option=option):
                        self.assertIn(values, script)
        self.assertGreater(checked, 0)

    def test_value_taking_flags_are_marked(self):
        fish = render_completion("fish")
        nu = render_completion("nu")
        for command in COMMANDS:
            for option, action in self._parser_options(command).items():
                if not option.startswith("--") or action.nargs == 0:
                    continue
                with self.subTest(command=command, option=option):
                    self.assertRegex(
                        fish,
                        rf"(?m)^complete -c {command} -f -l {option[2:]} -r",
                    )
                    self.assertRegex(nu, rf"(?m)^    {option}: string")

    def test_link_flags_are_completed_in_every_shell(self):
        expected = {
            option
            for action in link_parser()._actions
            for option in action.option_strings
        }
        for shell in ("bash", "zsh"):
            self.assertEqual(_bash_zsh_flags(render_completion(shell), "link"),
                             expected)

        fish = render_completion("fish")
        offered = set()
        for line in fish.splitlines():
            if "__fish_seen_subcommand_from link" not in line:
                continue
            offered.update("--" + name for name in re.findall(r"-l (\S+)", line))
            offered.update("-" + name for name in re.findall(r"-s (\S+)", line))
        self.assertEqual(offered, expected)
        self.assertRegex(
            fish,
            r"(?m)^complete -c linecast -f "
            r"-n '__fish_seen_subcommand_from link' -l dir -r$",
        )

        # Nushell owns help itself and represents only the long spellings.
        self.assertEqual(_nu_flags(render_completion("nu"), "linecast link"),
                         {"--version", "--dir", "--remove"})


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
        self.assertIn("Expected one of: " + ", ".join(available_shells()), err)

    def test_version_flag_prints_version(self):
        from linecast import __version__
        code, out, err = self._run_main("--version")
        self.assertEqual(code, 0)
        self.assertEqual(out, f"linecast {__version__}\n")
        self.assertEqual(err, "")

    def test_help_mentions_version_and_commands(self):
        from linecast import __version__
        code, out, err = self._run_main("--help")
        self.assertEqual(code, 0)
        self.assertIn(f"linecast {__version__} ", out)
        self.assertIn("linecast completion", out)
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
