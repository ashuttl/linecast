"""Shell completion script generation for linecast commands.

The per-command flags are read from the argparse parsers in _parsers,
so a flag added there reaches every shell's completion without a
parallel list here. Only the pieces argparse does not know about stay
in this module: the top-level `linecast` dispatcher (hand-rolled in
__main__), the settings commands' subcommands (SETTING_SUBCOMMANDS,
one table the four scripts are all written from), doctor's flags, and
the value lists for flags whose parsers accept free text.
"""

from __future__ import annotations

from linecast._commands import COMMAND_NAMES, VIEW_NAMES
from linecast._config import (
    CALENDAR_CHOICES, CLOCK_CHOICES, CULTURE_CHOICES, DATES_CHOICES, DIGITS_CHOICES,
    HOURS_CHOICES, ICON_SETS, UNITS_CHOICES, WEEK_STARTS,
)
from linecast._i18n import LANGUAGE_CODES, VARIANTS

# --lang accepts any code; the parser lists these in its help text but
# has no `choices`, so the completion offers them from here.
LANG_CODES = (*LANGUAGE_CODES, *VARIANTS)

SHELLS = ("bash", "zsh", "fish", "nu", "nushell")

# The argparse-driven commands, in the order their flags are emitted.
COMMANDS = VIEW_NAMES

GLOBAL_FLAGS = ("--help", "-h", "--version", "-v")
TOP_LEVEL_COMMANDS = COMMAND_NAMES
# The settings commands, in the order the scripts list them, and the
# words each takes after its name. Past location, each is show and auto
# around the choices the setting's flag takes, from _config (and _i18n
# for the languages) so the two cannot drift. A setting added here
# reaches all four shells.
SETTING_SUBCOMMANDS = {
    "location": ("show", "set", "auto", "search"),
    "language": ("show", *LANGUAGE_CODES, *VARIANTS, "auto"),
    "units": ("show", *UNITS_CHOICES, "auto"),
    "clock": ("show", *CLOCK_CHOICES, "auto"),
    "week": ("show", *WEEK_STARTS, "auto"),
    "dates": ("show", *DATES_CHOICES, "auto"),
    "digits": ("show", *DIGITS_CHOICES, "auto"),
    "icons": ("show", *ICON_SETS, "auto"),
    "calendar": ("show", *CALENDAR_CHOICES, "auto"),
    "culture": ("show", *CULTURE_CHOICES, "auto"),
    "hours": ("show", *HOURS_CHOICES, "auto"),
}
# Every settings command takes the same flags.
SETTING_FLAGS = ("--help", "-h", "--version")
DOCTOR_FLAGS = ("--help", "-h", "--version", "--offline", "--json", "--debug")
COMPLETION_FLAGS = ("--help", "-h")

_SPACE = " "


def available_shells():
    return SHELLS


def completion_help():
    """The --help page.  argparse is imported here, at the call, so a run
    of `linecast` that asks for no parser does not load it."""
    import argparse
    from linecast._commands import formatter_class
    parser = argparse.ArgumentParser(
        prog="linecast completion", usage="%(prog)s <shell>",
        description="Print a completion script for the shell, covering every "
                    "command, flag, and the short names",
        epilog="Bash and zsh: source <(linecast completion bash). Fish: "
               "linecast completion fish | source. Nushell: save the script "
               "under ~/.config/nushell/completions and `use` it from config.nu.",
        formatter_class=formatter_class())
    parser.add_argument("shell", metavar="<shell>", choices=SHELLS,
                        help="bash, zsh, fish, or nu (nushell)")
    return parser.format_help().rstrip()


def _value_hints():
    """Completion values for flags whose parser has no `choices`."""
    from linecast.maps.route import PROFILES
    from linecast.radar.sources import THEMES
    return {
        "--lang": LANG_CODES,
        "--theme": tuple(THEMES),
        # radar.main() maps these onto its internal layer names
        "--layer": ("radar", "satellite"),
        # radar.parse_layers() takes a comma-separated set
        "--layers": ("temp", "wind", "temp,wind"),
        "--source": ("librewxr", "rainviewer", "iem"),
        "--profile": tuple(PROFILES),
    }


class _Flag:
    """One parser option as the generators see it."""

    __slots__ = ("options", "name", "takes_value", "values")

    def __init__(self, options, takes_value, values):
        self.options = options
        self.name = next((o for o in options if o.startswith("--")),
                         options[0])
        self.takes_value = takes_value
        self.values = values

    @property
    def is_help(self):
        return "--help" in self.options

    @property
    def is_version(self):
        return "--version" in self.options


def command_flags(command, hints=None):
    """The flags of a command's argparse parser, in parser order."""
    from linecast import _parsers
    if hints is None:
        hints = _value_hints()
    parser = getattr(_parsers, f"{command}_parser")()
    return _parser_flags(parser, hints)


def _parser_flags(parser, hints=None):
    """An argparse parser's options in the form the generators use."""
    import argparse   # already loaded: the parser is argparse's
    hints = {} if hints is None else hints
    flags = []
    for action in parser._actions:
        options = tuple(action.option_strings)
        # an old name the help no longer offers is not offered here either
        if not options or action.help == argparse.SUPPRESS:
            continue
        takes_value = action.nargs != 0
        values = None
        if takes_value:
            long = next(o for o in options if o.startswith("--"))
            values = (tuple(action.choices) if action.choices
                      else hints.get(long))
        flags.append(_Flag(options, takes_value, values))
    return flags


def _link_flags():
    from linecast.link import link_parser
    return _parser_flags(link_parser())


def _all_command_flags():
    hints = _value_hints()
    return {cmd: command_flags(cmd, hints) for cmd in COMMANDS}


def _value_lists(flags_by_command):
    """{flag name: values} for every flag with a value list, in the
    order the flags are first met."""
    lists = {}
    for flags in flags_by_command.values():
        for flag in flags:
            if flag.values is not None and flag.name not in lists:
                lists[flag.name] = flag.values
    return lists


def _free_value_flags(flags_by_command):
    """Flag names that take a value the completion cannot suggest."""
    names = []
    for flags in flags_by_command.values():
        for flag in flags:
            if (flag.takes_value and flag.values is None
                    and flag.name not in names):
                names.append(flag.name)
    return names


def _words(flags):
    return _SPACE.join(o for flag in flags for o in flag.options)


def _dispatched():
    """The case pattern for the words after `linecast` whose own words
    the scripts complete: the views, the settings, and the three
    housekeeping commands."""
    return "|".join(("weather", "tides", "sunshine", "moon", "sky", "radar", "maps",
                     *SETTING_SUBCOMMANDS, "link", "doctor", "completion"))


def _var(name):
    """The bash/zsh variable that holds a flag's value list. A shell
    identifier cannot contain a hyphen, so --week-start's list lives in
    _linecast_week_start_values; the flag itself keeps its hyphen."""
    return f"_linecast_{name[2:].replace('-', '_')}_values"


def render_completion(shell: str):
    key = (shell or "").strip().lower()
    if key == "bash":
        return _bash_script(_all_command_flags())
    if key == "zsh":
        return _zsh_script(_all_command_flags())
    if key == "fish":
        return _fish_script(_all_command_flags())
    if key in ("nu", "nushell"):
        return _nu_script(_all_command_flags())
    raise ValueError(f"unknown shell '{shell}'")


def _bash_script(flags_by_command):
    link_flags = _link_flags()
    value_lists = _value_lists(flags_by_command)
    free = "|".join((*_free_value_flags(flags_by_command),
                     *_free_value_flags({"link": link_flags})))
    top = _SPACE.join((*TOP_LEVEL_COMMANDS, *GLOBAL_FLAGS))
    completion = _SPACE.join(COMPLETION_FLAGS)
    doctor = _SPACE.join(DOCTOR_FLAGS)
    link = _words(link_flags)
    shells = _SPACE.join(SHELLS)

    declarations = "\n".join(
        f'{_var(name)}="{_SPACE.join(values)}"'
        for name, values in value_lists.items()
    )
    prev_arms = "\n".join(
        f"    {name})\n"
        f'      COMPREPLY=( $(compgen -W "${_var(name)}" -- "$cur") )\n'
        f"      return 0\n"
        f"      ;;"
        for name in value_lists
    )
    eq_arms = "\n".join(
        f'  if [[ "$cur" == {name}=* ]]; then\n'
        f'    _linecast_complete_value_list "{name}=" "${_var(name)}"\n'
        f"    return 0\n"
        f"  fi"
        for name in value_lists
    )
    command_arms = "\n".join(
        f"    {cmd})\n"
        f"      _linecast_complete_flags {_words(flags)}\n"
        f"      ;;"
        for cmd, flags in flags_by_command.items()
    )
    setting_arms = "\n".join(
        f"    {name})\n"
        f"      _linecast_complete_flags {_SPACE.join(SETTING_FLAGS)}\n"
        f'      COMPREPLY+=( $(compgen -W "{_SPACE.join(words)}" -- "$cur") )\n'
        f"      ;;"
        for name, words in SETTING_SUBCOMMANDS.items()
    )
    standalone = "\n".join(
        f"_linecast_complete_{cmd}() {{\n"
        f"  local cur prev\n"
        f"  COMPREPLY=()\n"
        f'  cur="${{COMP_WORDS[COMP_CWORD]}}"\n'
        f'  prev=""\n'
        f"  if (( COMP_CWORD > 0 )); then\n"
        f'    prev="${{COMP_WORDS[COMP_CWORD-1]}}"\n'
        f"  fi\n"
        f"  _linecast_complete_command {cmd}\n"
        f"}}\n"
        for cmd in flags_by_command
    )
    registrations = "\n".join(
        f"complete -F _linecast_complete_{cmd} {cmd}"
        for cmd in flags_by_command
    )

    return f"""# bash completion for linecast
{declarations}

_linecast_seen_flag() {{
  local needle="$1"
  local i token
  for i in "${{!COMP_WORDS[@]}}"; do
    # The word being completed is not a flag already given: it is the
    # one being offered, so `--lay` must still reach --layer beside
    # --layers, and a flag typed in full still gets its space.
    if (( i == COMP_CWORD )); then
      continue
    fi
    token="${{COMP_WORDS[i]}}"
    if [[ "$token" == "$needle" || "$token" == "$needle="* ]]; then
      return 0
    fi
  done
  return 1
}}

_linecast_filter_flags() {{
  local token
  for token in "$@"; do
    if ! _linecast_seen_flag "$token"; then
      printf '%s\\n' "$token"
    fi
  done
}}

_linecast_complete_value_list() {{
  local prefix="$1"
  local values="$2"
  local value="${{cur#${{prefix}}}}"
  local i
  COMPREPLY=( $(compgen -W "$values" -- "$value") )
  for i in "${{!COMPREPLY[@]}}"; do
    COMPREPLY[$i]="${{prefix}}${{COMPREPLY[$i]}}"
  done
}}

_linecast_complete_common_values() {{
  # bash's default COMP_WORDBREAKS has = in it, so `--lang=f` arrives as
  # three words, --lang, = and f, and `--lang=` as two, with = the word
  # being completed. Readline puts a bare value back after the =, so the
  # flag is the word before it and the values are offered as they are.
  # The --flag=value arms below still serve a user who has taken = out
  # of COMP_WORDBREAKS, where the flag and value arrive as one word.
  local cur="$cur"
  local prev="$prev"
  if [[ "$cur" == "=" ]]; then
    cur=""
  elif [[ "$prev" == "=" ]] && (( COMP_CWORD >= 2 )); then
    prev="${{COMP_WORDS[COMP_CWORD-2]}}"
  fi

  case "$prev" in
{prev_arms}
    {free})
      return 0
      ;;
  esac

{eq_arms}
  return 1
}}

_linecast_complete_flags() {{
  local opts="$(_linecast_filter_flags "$@")"
  COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
}}

_linecast_complete_command() {{
  local cmd="$1"
  if _linecast_complete_common_values; then
    return 0
  fi

  case "$cmd" in
{command_arms}
{setting_arms}
    doctor)
      _linecast_complete_flags {doctor}
      ;;
    link)
      _linecast_complete_flags {link}
      ;;
    completion)
      _linecast_complete_flags {completion}
      COMPREPLY+=( $(compgen -W "{shells}" -- "$cur") )
      ;;
  esac
}}

_linecast_complete() {{
  local cur prev cmd
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev=""
  if (( COMP_CWORD > 0 )); then
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  fi

  if (( COMP_CWORD == 1 )); then
    _linecast_complete_flags {top}
    return 0
  fi

  cmd="${{COMP_WORDS[1]}}"
  case "$cmd" in
    {_dispatched()})
      _linecast_complete_command "$cmd"
      ;;
  esac
}}

{standalone}
complete -F _linecast_complete linecast
{registrations}
"""


def _zsh_script(flags_by_command):
    link_flags = _link_flags()
    value_lists = _value_lists(flags_by_command)
    free = "|".join((*_free_value_flags(flags_by_command),
                     *_free_value_flags({"link": link_flags})))
    top = _SPACE.join((*TOP_LEVEL_COMMANDS, *GLOBAL_FLAGS))
    completion = _SPACE.join(COMPLETION_FLAGS)
    doctor = _SPACE.join(DOCTOR_FLAGS)
    link = _words(link_flags)
    shells = _SPACE.join(SHELLS)
    standalone = _SPACE.join(flags_by_command)

    # -g: dropped into fpath as _linecast, this whole file is the body
    # of the autoloaded function, and a plain typeset there would make
    # the lists locals of its first call, gone by the time completion
    # asks for them.
    declarations = "\n".join(
        f"typeset -ga {_var(name)}\n"
        f"{_var(name)}=({_SPACE.join(values)})"
        for name, values in value_lists.items()
    )
    prev_arms = "\n".join(
        f"    {name})\n"
        f'      compadd -- "${{{_var(name)}[@]}}"\n'
        f"      return 0\n"
        f"      ;;"
        for name in value_lists
    )
    eq_arms = "\n".join(
        f'  if [[ "$cur" == {name}=* ]]; then\n'
        f'    _linecast_complete_value_eq "{name}=" "${{{_var(name)}[@]}}"\n'
        f"    return 0\n"
        f"  fi"
        for name in value_lists
    )
    command_arms = "\n".join(
        f"    {cmd})\n"
        f"      _linecast_add_flags {_words(flags)}\n"
        f"      ;;"
        for cmd, flags in flags_by_command.items()
    )
    setting_arms = "\n".join(
        f"    {name})\n"
        f"      _linecast_add_flags {_SPACE.join(SETTING_FLAGS)}\n"
        f"      compadd -- {_SPACE.join(words)}\n"
        f"      ;;"
        for name, words in SETTING_SUBCOMMANDS.items()
    )

    return f"""#compdef linecast {standalone}

{declarations}

_linecast_seen_flag() {{
  local needle="$1"
  local i token
  for (( i = 1; i <= ${{#words[@]}}; i++ )); do
    # The word being completed is not a flag already given: it is the
    # one being offered, so `--lay` must still reach --layer beside
    # --layers, and a flag typed in full still gets its space.
    if (( i == CURRENT )); then
      continue
    fi
    token="${{words[i]}}"
    if [[ "$token" == "$needle" || "$token" == ${{needle}}=* ]]; then
      return 0
    fi
  done
  return 1
}}

_linecast_add_flags() {{
  local -a opts out
  local opt
  opts=("$@")
  out=()
  for opt in "${{opts[@]}}"; do
    if ! _linecast_seen_flag "$opt"; then
      out+=("$opt")
    fi
  done
  if (( ${{#out[@]}} )); then
    compadd -- "${{out[@]}}"
  fi
}}

_linecast_complete_value_eq() {{
  local prefix="$1"
  shift
  local cur="${{words[CURRENT]}}"
  local value="${{cur#${{prefix}}}}"
  local candidate
  local -a out
  out=()
  for candidate in "$@"; do
    if [[ "$candidate" == ${{value}}* ]]; then
      out+=("${{prefix}}${{candidate}}")
    fi
  done
  if (( ${{#out[@]}} )); then
    compadd -- "${{out[@]}}"
  fi
}}

_linecast_complete_common_values() {{
  local prev="${{words[CURRENT-1]}}"
  local cur="${{words[CURRENT]}}"

  case "$prev" in
{prev_arms}
    {free})
      return 0
      ;;
  esac

{eq_arms}
  return 1
}}

_linecast_complete_command() {{
  local cmd="$1"
  if _linecast_complete_common_values; then
    return 0
  fi

  case "$cmd" in
{command_arms}
{setting_arms}
    doctor)
      _linecast_add_flags {doctor}
      ;;
    link)
      _linecast_add_flags {link}
      ;;
    completion)
      _linecast_add_flags {completion}
      compadd -- {shells}
      ;;
  esac
}}

_linecast() {{
  local cmd
  local svc="${{service:-linecast}}"

  if [[ "$svc" == "linecast" ]]; then
    if (( CURRENT == 2 )); then
      _linecast_add_flags {top}
      return 0
    fi
    cmd="${{words[2]}}"
    case "$cmd" in
      {_dispatched()})
        _linecast_complete_command "$cmd"
        ;;
    esac
    return 0
  fi

  _linecast_complete_command "$svc"
  return 0
}}

# Autoloaded from fpath, this file runs as _linecast itself and must
# complete the line it was called for; sourced from the README's
# `source <(linecast completion zsh)`, it only has to register.
if [[ "${{funcstack[1]}}" == "_linecast" ]]; then
  _linecast "$@"
else
  compdef _linecast linecast {standalone}
fi
"""


def _fish_flag_lines(head, flags):
    """One `complete` line per flag; `head` names the command and any
    condition, e.g. "-c linecast -f -n '__fish_seen_subcommand_from radar'"
    or "-c radar -f"."""
    lines = []
    for flag in flags:
        parts = [f"complete {head}"]
        for option in flag.options:
            if option.startswith("--"):
                parts.append(f"-l {option[2:]}")
            else:
                parts.append(f"-s {option[1:]}")
        if flag.takes_value:
            parts.append("-r")
        if flag.values is not None:
            parts.append(f"-a '{_SPACE.join(flag.values)}'")
        lines.append(_SPACE.join(parts))
    return lines


def _fish_script(flags_by_command):
    commands = _SPACE.join(TOP_LEVEL_COMMANDS)
    shells = _SPACE.join(SHELLS)
    lines = [
        "# fish completion for linecast",
        f"complete -c linecast -f -n '__fish_use_subcommand' -a '{commands}'",
        "complete -c linecast -f -n '__fish_use_subcommand' -l help -s h",
        "complete -c linecast -f -n '__fish_use_subcommand' -l version -s v",
        f"complete -c linecast -f -n '__fish_seen_subcommand_from completion' -a '{shells}'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from completion' -l help -s h",
    ]
    for name, words in SETTING_SUBCOMMANDS.items():
        seen = f"-c linecast -f -n '__fish_seen_subcommand_from {name}'"
        lines.append(f"complete {seen} -a '{_SPACE.join(words)}'")
        lines.append(f"complete {seen} -l help -s h")
    lines += [
        "complete -c linecast -f -n '__fish_seen_subcommand_from doctor' -l help -s h",
        "complete -c linecast -f -n '__fish_seen_subcommand_from doctor' -l version",
        "complete -c linecast -f -n '__fish_seen_subcommand_from doctor' -l offline",
        "complete -c linecast -f -n '__fish_seen_subcommand_from doctor' -l json",
        "complete -c linecast -f -n '__fish_seen_subcommand_from doctor' -l debug",
    ]

    lines.extend(_fish_flag_lines(
        "-c linecast -f -n '__fish_seen_subcommand_from link'", _link_flags()))

    for cmd, flags in flags_by_command.items():
        head = f"-c linecast -f -n '__fish_seen_subcommand_from {cmd}'"
        lines.extend(_fish_flag_lines(head, flags))
    for cmd, flags in flags_by_command.items():
        lines.extend(_fish_flag_lines(f"-c {cmd} -f", flags))

    return "\n".join(lines) + "\n"


def _nu_flags(flags):
    lines = []
    for flag in flags:
        # --help and -h are left out so Nushell does not hijack help display
        if flag.is_help:
            continue
        # Nushell flag names must be identifiers, which --12h/--24h are
        # not; they stay completable in the other shells only
        if not flag.name.lstrip("-")[:1].isalpha():
            continue
        if flag.is_version:
            lines.append(f"    {flag.name} # Show version")
            continue
        if flag.values is not None:
            lines.append(
                f'    {flag.name}: string@"nu-complete linecast-{flag.name[2:]}"'
            )
            continue
        if flag.takes_value:
            lines.append(f"    {flag.name}: string")
            continue
        lines.append(f"    {flag.name}")
    return lines


def _nu_extern(cmd_name, flags_lines, positional_args=()):
    lines = [f'export extern "{cmd_name}" [']
    for pos in positional_args:
        lines.append(f"    {pos}")
    lines.extend(flags_lines)
    lines.append("]")
    lines.append("")
    return lines


def _nu_value_list(name, values):
    return [
        f'def "nu-complete {name}" [] {{',
        "    [ " + " ".join(f'"{value}"' for value in values) + " ]",
        "}",
        "",
    ]


def _nu_script(flags_by_command):
    lines = ["# nushell completion for linecast", ""]
    for name, values in _value_lists(flags_by_command).items():
        lines.extend(_nu_value_list(f"linecast-{name[2:]}", values))
    lines.extend(_nu_value_list("linecast-shells", SHELLS))
    for name, words in SETTING_SUBCOMMANDS.items():
        lines.extend(_nu_value_list(f"linecast-{name}-subcommands", words))
    lines.extend([
        'export extern "linecast" [',
        "    --version(-v) # Show version",
        "]",
        "",
    ])

    nu_flags = {cmd: _nu_flags(flags)
                for cmd, flags in flags_by_command.items()}
    version_only = ["    --version # Show version"]

    for cmd in COMMANDS:
        lines.extend(_nu_extern(f"linecast {cmd}", nu_flags[cmd]))

    def settings(prefix):
        for name, words in SETTING_SUBCOMMANDS.items():
            lines.extend(_nu_extern(
                f"{prefix}{name}",
                version_only,
                [f'subcommand?: string@"nu-complete linecast-{name}-subcommands"'],
            ))
            for sub in words:
                # `location set` and `location search` take a place
                positional = (["query?: string"] if name == "location"
                              and sub in ("set", "search") else [])
                lines.extend(_nu_extern(f"{prefix}{name} {sub}", version_only,
                                        positional))
        lines.extend(_nu_extern(f"{prefix}doctor", [
            *version_only, "    --offline", "    --json", "    --debug"]))

    settings("linecast ")
    lines.extend(_nu_extern("linecast link", _nu_flags(_link_flags())))
    lines.extend(_nu_extern(
        "linecast completion",
        [],
        ['shell?: string@"nu-complete linecast-shells"'],
    ))

    # The seven view commands again under their short names, as the
    # other shells register them. Only those answer to their own name
    # (__main__.STANDALONE); a bare `units` or `calendar` is some other
    # program's, and an extern by that name would have nushell parse
    # that program's arguments by linecast's signature and refuse them.
    for cmd in COMMANDS:
        lines.extend(_nu_extern(cmd, nu_flags[cmd]))

    return "\n".join(lines) + "\n"
