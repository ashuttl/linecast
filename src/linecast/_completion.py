"""Shell completion script generation for linecast commands.

The per-command flags are read from the argparse parsers in _runtime,
so a flag added there reaches every shell's completion without a
parallel list here. Only the pieces argparse does not know about stay
in this module: the top-level `linecast` dispatcher (hand-rolled in
__main__), the location/language/units/clock/icons/calendar/doctor subcommands, and the value lists
for flags whose parsers accept free text.
"""

from __future__ import annotations

from linecast._config import CALENDAR_CHOICES, CULTURE_CHOICES
from linecast._i18n import LANGUAGE_CODES

# --lang accepts any code; the parser lists these in its help text but
# has no `choices`, so the completion offers them from here.
LANG_CODES = (
    "en",
    "fr",
    "es",
    "de",
    "it",
    "pt",
    "nl",
    "pl",
    "no",
    "sv",
    "is",
    "da",
    "fi",
    "ja",
    "ko",
    "zh",
    "th",
    "id",
)

SHELLS = ("bash", "zsh", "fish", "nu", "nushell")

# The argparse-driven commands, in the order their flags are emitted.
COMMANDS = ("weather", "sunshine", "moon", "sky", "tides", "radar", "maps")

GLOBAL_FLAGS = ("--help", "-h", "--version", "-v")
TOP_LEVEL_COMMANDS = ("weather", "sunshine", "moon", "sky", "tides", "radar", "maps",
                      "location", "language", "units", "clock", "icons", "calendar",
                      "culture", "link", "doctor",
                      "completion")
LOCATION_SUBCOMMANDS = ("show", "set", "auto", "search")
LOCATION_FLAGS = ("--help", "-h", "--version")
# `linecast language` takes the codes linecast has strings for; the
# list is _i18n's so the two cannot drift.
LANGUAGE_SUBCOMMANDS = ("show", *LANGUAGE_CODES, "auto")
LANGUAGE_FLAGS = ("--help", "-h", "--version")
UNITS_SUBCOMMANDS = ("show", "metric", "imperial", "auto")
UNITS_FLAGS = ("--help", "-h", "--version")
CLOCK_SUBCOMMANDS = ("show", "12", "24", "auto")
CLOCK_FLAGS = ("--help", "-h", "--version")
ICONS_SUBCOMMANDS = ("show", "nerd", "emoji", "plain", "auto")
ICONS_FLAGS = ("--help", "-h", "--version")
# `linecast calendar` takes the same names as moon's --calendar, plus
# show and auto; the list is _config's so the two cannot drift.
CALENDAR_SUBCOMMANDS = ("show", *CALENDAR_CHOICES, "auto")
CALENDAR_FLAGS = ("--help", "-h", "--version")
# `linecast culture` takes the same names as sky's --culture, plus show
# and auto; the list is _config's so the two cannot drift.
CULTURE_SUBCOMMANDS = ("show", *CULTURE_CHOICES, "auto")
CULTURE_FLAGS = ("--help", "-h", "--version")
DOCTOR_FLAGS = ("--help", "-h", "--version", "--offline", "--json", "--debug")
COMPLETION_FLAGS = ("--help", "-h")

_SPACE = " "


def available_shells():
    return SHELLS


def completion_help():
    shell_list = ", ".join(SHELLS)
    return f"Usage: linecast completion <shell>\nShells: {shell_list}"


def _value_hints():
    """Completion values for flags whose parser has no `choices`."""
    from linecast._maps_route import PROFILES
    from linecast._radar_sources import THEMES
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
    from linecast import _runtime
    if hints is None:
        hints = _value_hints()
    parser = getattr(_runtime, f"{command}_parser")()
    return _parser_flags(parser, hints)


def _parser_flags(parser, hints=None):
    """An argparse parser's options in the form the generators use."""
    hints = {} if hints is None else hints
    flags = []
    for action in parser._actions:
        options = tuple(action.option_strings)
        if not options:
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


def _var(name):
    return f"_linecast_{name[2:]}_values"


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
    location = _SPACE.join(LOCATION_FLAGS)
    location_sub = _SPACE.join(LOCATION_SUBCOMMANDS)
    language = _SPACE.join(LANGUAGE_FLAGS)
    language_sub = _SPACE.join(LANGUAGE_SUBCOMMANDS)
    units = _SPACE.join(UNITS_FLAGS)
    units_sub = _SPACE.join(UNITS_SUBCOMMANDS)
    clock = _SPACE.join(CLOCK_FLAGS)
    clock_sub = _SPACE.join(CLOCK_SUBCOMMANDS)
    icons = _SPACE.join(ICONS_FLAGS)
    icons_sub = _SPACE.join(ICONS_SUBCOMMANDS)
    calendar = _SPACE.join(CALENDAR_FLAGS)
    calendar_sub = _SPACE.join(CALENDAR_SUBCOMMANDS)
    culture = _SPACE.join(CULTURE_FLAGS)
    culture_sub = _SPACE.join(CULTURE_SUBCOMMANDS)
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
  local token
  for token in "${{COMP_WORDS[@]}}"; do
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
    location)
      _linecast_complete_flags {location}
      COMPREPLY+=( $(compgen -W "{location_sub}" -- "$cur") )
      ;;
    language)
      _linecast_complete_flags {language}
      COMPREPLY+=( $(compgen -W "{language_sub}" -- "$cur") )
      ;;
    units)
      _linecast_complete_flags {units}
      COMPREPLY+=( $(compgen -W "{units_sub}" -- "$cur") )
      ;;
    clock)
      _linecast_complete_flags {clock}
      COMPREPLY+=( $(compgen -W "{clock_sub}" -- "$cur") )
      ;;
    icons)
      _linecast_complete_flags {icons}
      COMPREPLY+=( $(compgen -W "{icons_sub}" -- "$cur") )
      ;;
    calendar)
      _linecast_complete_flags {calendar}
      COMPREPLY+=( $(compgen -W "{calendar_sub}" -- "$cur") )
      ;;
    culture)
      _linecast_complete_flags {culture}
      COMPREPLY+=( $(compgen -W "{culture_sub}" -- "$cur") )
      ;;
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
    weather|tides|sunshine|moon|sky|radar|maps|location|language|units|clock|icons|calendar|culture|link|doctor|completion)
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
    location = _SPACE.join(LOCATION_FLAGS)
    location_sub = _SPACE.join(LOCATION_SUBCOMMANDS)
    language = _SPACE.join(LANGUAGE_FLAGS)
    language_sub = _SPACE.join(LANGUAGE_SUBCOMMANDS)
    units = _SPACE.join(UNITS_FLAGS)
    units_sub = _SPACE.join(UNITS_SUBCOMMANDS)
    clock = _SPACE.join(CLOCK_FLAGS)
    clock_sub = _SPACE.join(CLOCK_SUBCOMMANDS)
    icons = _SPACE.join(ICONS_FLAGS)
    icons_sub = _SPACE.join(ICONS_SUBCOMMANDS)
    calendar = _SPACE.join(CALENDAR_FLAGS)
    calendar_sub = _SPACE.join(CALENDAR_SUBCOMMANDS)
    culture = _SPACE.join(CULTURE_FLAGS)
    culture_sub = _SPACE.join(CULTURE_SUBCOMMANDS)
    doctor = _SPACE.join(DOCTOR_FLAGS)
    link = _words(link_flags)
    shells = _SPACE.join(SHELLS)
    standalone = _SPACE.join(flags_by_command)

    declarations = "\n".join(
        f"typeset -a {_var(name)}\n"
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

    return f"""#compdef linecast {standalone}

{declarations}

_linecast_seen_flag() {{
  local needle="$1"
  local token
  for token in "${{words[@]}}"; do
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
    location)
      _linecast_add_flags {location}
      compadd -- {location_sub}
      ;;
    language)
      _linecast_add_flags {language}
      compadd -- {language_sub}
      ;;
    units)
      _linecast_add_flags {units}
      compadd -- {units_sub}
      ;;
    clock)
      _linecast_add_flags {clock}
      compadd -- {clock_sub}
      ;;
    icons)
      _linecast_add_flags {icons}
      compadd -- {icons_sub}
      ;;
    calendar)
      _linecast_add_flags {calendar}
      compadd -- {calendar_sub}
      ;;
    culture)
      _linecast_add_flags {culture}
      compadd -- {culture_sub}
      ;;
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
      weather|tides|sunshine|moon|sky|radar|maps|location|language|units|clock|icons|calendar|culture|link|doctor|completion)
        _linecast_complete_command "$cmd"
        ;;
    esac
    return 0
  fi

  _linecast_complete_command "$svc"
  return 0
}}

compdef _linecast linecast {standalone}
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
    location_sub = _SPACE.join(LOCATION_SUBCOMMANDS)
    language_sub = _SPACE.join(LANGUAGE_SUBCOMMANDS)
    units_sub = _SPACE.join(UNITS_SUBCOMMANDS)
    clock_sub = _SPACE.join(CLOCK_SUBCOMMANDS)
    icons_sub = _SPACE.join(ICONS_SUBCOMMANDS)
    calendar_sub = _SPACE.join(CALENDAR_SUBCOMMANDS)
    culture_sub = _SPACE.join(CULTURE_SUBCOMMANDS)
    lines = [
        "# fish completion for linecast",
        f"complete -c linecast -f -n '__fish_use_subcommand' -a '{commands}'",
        "complete -c linecast -f -n '__fish_use_subcommand' -l help -s h",
        "complete -c linecast -f -n '__fish_use_subcommand' -l version -s v",
        f"complete -c linecast -f -n '__fish_seen_subcommand_from completion' -a '{shells}'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from completion' -l help -s h",
        f"complete -c linecast -f -n '__fish_seen_subcommand_from location' -a '{location_sub}'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from location' -l help -s h",
        f"complete -c linecast -f -n '__fish_seen_subcommand_from language' -a '{language_sub}'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from language' -l help -s h",
        f"complete -c linecast -f -n '__fish_seen_subcommand_from units' -a '{units_sub}'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from units' -l help -s h",
        f"complete -c linecast -f -n '__fish_seen_subcommand_from clock' -a '{clock_sub}'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from clock' -l help -s h",
        f"complete -c linecast -f -n '__fish_seen_subcommand_from icons' -a '{icons_sub}'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from icons' -l help -s h",
        f"complete -c linecast -f -n '__fish_seen_subcommand_from calendar' -a '{calendar_sub}'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from calendar' -l help -s h",
        f"complete -c linecast -f -n '__fish_seen_subcommand_from culture' -a '{culture_sub}'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from culture' -l help -s h",
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
    lines.extend(_nu_value_list("linecast-location-subcommands",
                                LOCATION_SUBCOMMANDS))
    lines.extend(_nu_value_list("linecast-language-subcommands",
                                LANGUAGE_SUBCOMMANDS))
    lines.extend(_nu_value_list("linecast-units-subcommands",
                                UNITS_SUBCOMMANDS))
    lines.extend(_nu_value_list("linecast-clock-subcommands",
                                CLOCK_SUBCOMMANDS))
    lines.extend(_nu_value_list("linecast-icons-subcommands",
                                ICONS_SUBCOMMANDS))
    lines.extend(_nu_value_list("linecast-calendar-subcommands",
                                CALENDAR_SUBCOMMANDS))
    lines.extend(_nu_value_list("linecast-culture-subcommands",
                                CULTURE_SUBCOMMANDS))
    lines.extend([
        'export extern "linecast" [',
        "    --version(-v) # Show version",
        "]",
        "",
    ])

    nu_flags = {cmd: _nu_flags(flags)
                for cmd, flags in flags_by_command.items()}
    version_only = ["    --version # Show version"]

    def dispatcher(prefix):
        # linecast's own subcommands, and the same commands standalone
        for cmd in TOP_LEVEL_COMMANDS:
            if cmd in nu_flags:
                lines.extend(_nu_extern(f"{prefix}{cmd}", nu_flags[cmd]))
        lines.extend(_nu_extern(
            f"{prefix}location",
            version_only,
            ['subcommand?: string@"nu-complete linecast-location-subcommands"'],
        ))
        for sub in LOCATION_SUBCOMMANDS:
            positional = ["query?: string"] if sub in ("set", "search") else []
            lines.extend(_nu_extern(f"{prefix}location {sub}", version_only,
                                    positional))
        lines.extend(_nu_extern(
            f"{prefix}language",
            version_only,
            ['subcommand?: string@"nu-complete linecast-language-subcommands"'],
        ))
        for sub in LANGUAGE_SUBCOMMANDS:
            lines.extend(_nu_extern(f"{prefix}language {sub}", version_only))
        lines.extend(_nu_extern(
            f"{prefix}units",
            version_only,
            ['subcommand?: string@"nu-complete linecast-units-subcommands"'],
        ))
        for sub in UNITS_SUBCOMMANDS:
            lines.extend(_nu_extern(f"{prefix}units {sub}", version_only))
        lines.extend(_nu_extern(
            f"{prefix}clock",
            version_only,
            ['subcommand?: string@"nu-complete linecast-clock-subcommands"'],
        ))
        for sub in CLOCK_SUBCOMMANDS:
            lines.extend(_nu_extern(f"{prefix}clock {sub}", version_only))
        lines.extend(_nu_extern(
            f"{prefix}icons",
            version_only,
            ['subcommand?: string@"nu-complete linecast-icons-subcommands"'],
        ))
        for sub in ICONS_SUBCOMMANDS:
            lines.extend(_nu_extern(f"{prefix}icons {sub}", version_only))
        lines.extend(_nu_extern(
            f"{prefix}calendar",
            version_only,
            ['subcommand?: string@"nu-complete linecast-calendar-subcommands"'],
        ))
        for sub in CALENDAR_SUBCOMMANDS:
            lines.extend(_nu_extern(f"{prefix}calendar {sub}", version_only))
        lines.extend(_nu_extern(
            f"{prefix}culture",
            version_only,
            ['subcommand?: string@"nu-complete linecast-culture-subcommands"'],
        ))
        for sub in CULTURE_SUBCOMMANDS:
            lines.extend(_nu_extern(f"{prefix}culture {sub}", version_only))
        lines.extend(_nu_extern(f"{prefix}doctor", [
            *version_only, "    --offline", "    --json", "    --debug"]))

    dispatcher("linecast ")
    lines.extend(_nu_extern("linecast link", _nu_flags(_link_flags())))
    lines.extend(_nu_extern(
        "linecast completion",
        [],
        ['shell?: string@"nu-complete linecast-shells"'],
    ))
    dispatcher("")

    return "\n".join(lines) + "\n"
