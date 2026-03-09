"""Shell completion script generation for linecast commands."""

from __future__ import annotations

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
)

THEME_VALUES = ("classic", "legacy", "old")
SHELLS = ("bash", "zsh", "fish")

GLOBAL_FLAGS = ("--help", "-h", "--version", "-v")
TOP_LEVEL_COMMANDS = ("weather", "sunshine", "tides", "completion")

WEATHER_FLAGS = (
    "--help",
    "-h",
    "--version",
    "--print",
    "--live",
    "--location",
    "--search",
    "--emoji",
    "--metric",
    "--celsius",
    "--fahrenheit",
    "--shading",
    "--lang",
    "--classic-colors",
    "--legacy-colors",
    "--theme",
)

TIDES_FLAGS = (
    "--help",
    "-h",
    "--version",
    "--print",
    "--live",
    "--station",
    "--search",
    "--metric",
    "--lang",
    "--classic-colors",
    "--legacy-colors",
    "--theme",
)

SUNSHINE_FLAGS = (
    "--help",
    "-h",
    "--version",
    "--print",
    "--live",
    "--emoji",
    "--classic-colors",
    "--legacy-colors",
    "--theme",
)

COMPLETION_FLAGS = ("--help", "-h")

_SPACE = " "


def available_shells():
    return SHELLS


def completion_help():
    shell_list = ", ".join(SHELLS)
    return f"Usage: linecast completion <shell>\nShells: {shell_list}"


def render_completion(shell: str):
    key = (shell or "").strip().lower()
    if key == "bash":
        return _bash_script()
    if key == "zsh":
        return _zsh_script()
    if key == "fish":
        return _fish_script()
    raise ValueError(f"unknown shell '{shell}'")


def _bash_script():
    langs = _SPACE.join(LANG_CODES)
    themes = _SPACE.join(THEME_VALUES)
    top = _SPACE.join((*TOP_LEVEL_COMMANDS, *GLOBAL_FLAGS))
    weather = _SPACE.join(WEATHER_FLAGS)
    tides = _SPACE.join(TIDES_FLAGS)
    sunshine = _SPACE.join(SUNSHINE_FLAGS)
    completion = _SPACE.join(COMPLETION_FLAGS)
    shells = _SPACE.join(SHELLS)

    return f"""# bash completion for linecast
_linecast_lang_values="{langs}"
_linecast_theme_values="{themes}"

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
    --lang)
      COMPREPLY=( $(compgen -W "$_linecast_lang_values" -- "$cur") )
      return 0
      ;;
    --theme)
      COMPREPLY=( $(compgen -W "$_linecast_theme_values" -- "$cur") )
      return 0
      ;;
    --location|--search|--station)
      return 0
      ;;
  esac

  if [[ "$cur" == --lang=* ]]; then
    _linecast_complete_value_list "--lang=" "$_linecast_lang_values"
    return 0
  fi
  if [[ "$cur" == --theme=* ]]; then
    _linecast_complete_value_list "--theme=" "$_linecast_theme_values"
    return 0
  fi
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
    weather)
      _linecast_complete_flags {weather}
      ;;
    tides)
      _linecast_complete_flags {tides}
      ;;
    sunshine)
      _linecast_complete_flags {sunshine}
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
    weather|tides|sunshine|completion)
      _linecast_complete_command "$cmd"
      ;;
  esac
}}

_linecast_complete_weather() {{
  local cur prev
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev=""
  if (( COMP_CWORD > 0 )); then
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  fi
  _linecast_complete_command weather
}}

_linecast_complete_tides() {{
  local cur prev
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev=""
  if (( COMP_CWORD > 0 )); then
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  fi
  _linecast_complete_command tides
}}

_linecast_complete_sunshine() {{
  local cur prev
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev=""
  if (( COMP_CWORD > 0 )); then
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  fi
  _linecast_complete_command sunshine
}}

complete -F _linecast_complete linecast
complete -F _linecast_complete_weather weather
complete -F _linecast_complete_tides tides
complete -F _linecast_complete_sunshine sunshine
"""


def _zsh_script():
    langs = _SPACE.join(LANG_CODES)
    themes = _SPACE.join(THEME_VALUES)
    top = _SPACE.join((*TOP_LEVEL_COMMANDS, *GLOBAL_FLAGS))
    weather = _SPACE.join(WEATHER_FLAGS)
    tides = _SPACE.join(TIDES_FLAGS)
    sunshine = _SPACE.join(SUNSHINE_FLAGS)
    completion = _SPACE.join(COMPLETION_FLAGS)
    shells = _SPACE.join(SHELLS)

    return f"""#compdef linecast weather sunshine tides

typeset -a _linecast_lang_values
_linecast_lang_values=({langs})
typeset -a _linecast_theme_values
_linecast_theme_values=({themes})

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
    --lang)
      compadd -- "${{_linecast_lang_values[@]}}"
      return 0
      ;;
    --theme)
      compadd -- "${{_linecast_theme_values[@]}}"
      return 0
      ;;
    --location|--search|--station)
      return 0
      ;;
  esac

  if [[ "$cur" == --lang=* ]]; then
    _linecast_complete_value_eq "--lang=" "${{_linecast_lang_values[@]}}"
    return 0
  fi
  if [[ "$cur" == --theme=* ]]; then
    _linecast_complete_value_eq "--theme=" "${{_linecast_theme_values[@]}}"
    return 0
  fi
  return 1
}}

_linecast_complete_command() {{
  local cmd="$1"
  if _linecast_complete_common_values; then
    return 0
  fi

  case "$cmd" in
    weather)
      _linecast_add_flags {weather}
      ;;
    tides)
      _linecast_add_flags {tides}
      ;;
    sunshine)
      _linecast_add_flags {sunshine}
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
      weather|tides|sunshine|completion)
        _linecast_complete_command "$cmd"
        ;;
    esac
    return 0
  fi

  _linecast_complete_command "$svc"
  return 0
}}

compdef _linecast linecast weather sunshine tides
"""


def _fish_command_flags(command, flags, lang=False, theme=False, value_flags=()):
    lines = []
    cond = f"__fish_seen_subcommand_from {command}"

    for flag in flags:
        if flag == "-h":
            lines.append(
                f"complete -c linecast -f -n '{cond}' -s h"
            )
            continue
        if flag == "--help":
            lines.append(
                f"complete -c linecast -f -n '{cond}' -l help"
            )
            continue
        if flag == "--version":
            lines.append(
                f"complete -c linecast -f -n '{cond}' -l version"
            )
            continue
        if flag == "--lang" and lang:
            values = _SPACE.join(LANG_CODES)
            lines.append(
                f"complete -c linecast -f -n '{cond}' -l lang -r -a '{values}'"
            )
            continue
        if flag == "--theme" and theme:
            values = _SPACE.join(THEME_VALUES)
            lines.append(
                f"complete -c linecast -f -n '{cond}' -l theme -r -a '{values}'"
            )
            continue
        if flag in value_flags:
            lines.append(
                f"complete -c linecast -f -n '{cond}' -l {flag[2:]} -r"
            )
            continue
        if flag.startswith("--"):
            lines.append(
                f"complete -c linecast -f -n '{cond}' -l {flag[2:]}"
            )

    return lines


def _fish_standalone_flags(command, flags, lang=False, theme=False, value_flags=()):
    lines = []
    for flag in flags:
        if flag == "-h":
            lines.append(f"complete -c {command} -f -s h")
            continue
        if flag == "--help":
            lines.append(f"complete -c {command} -f -l help")
            continue
        if flag == "--version":
            lines.append(f"complete -c {command} -f -l version")
            continue
        if flag == "--lang" and lang:
            values = _SPACE.join(LANG_CODES)
            lines.append(
                f"complete -c {command} -f -l lang -r -a '{values}'"
            )
            continue
        if flag == "--theme" and theme:
            values = _SPACE.join(THEME_VALUES)
            lines.append(
                f"complete -c {command} -f -l theme -r -a '{values}'"
            )
            continue
        if flag in value_flags:
            lines.append(f"complete -c {command} -f -l {flag[2:]} -r")
            continue
        if flag.startswith("--"):
            lines.append(f"complete -c {command} -f -l {flag[2:]}")
    return lines


def _fish_script():
    lines = [
        "# fish completion for linecast",
        "complete -c linecast -f -n '__fish_use_subcommand' -a 'weather sunshine tides completion'",
        "complete -c linecast -f -n '__fish_use_subcommand' -l help -s h",
        "complete -c linecast -f -n '__fish_use_subcommand' -l version -s v",
        "complete -c linecast -f -n '__fish_seen_subcommand_from completion' -a 'bash zsh fish'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from completion' -l help -s h",
    ]

    lines.extend(
        _fish_command_flags(
            "weather",
            WEATHER_FLAGS,
            lang=True,
            theme=True,
            value_flags=("--location", "--search"),
        )
    )
    lines.extend(
        _fish_command_flags(
            "tides",
            TIDES_FLAGS,
            lang=True,
            theme=True,
            value_flags=("--station", "--search"),
        )
    )
    lines.extend(
        _fish_command_flags(
            "sunshine",
            SUNSHINE_FLAGS,
            theme=True,
        )
    )

    lines.extend(
        _fish_standalone_flags(
            "weather",
            WEATHER_FLAGS,
            lang=True,
            theme=True,
            value_flags=("--location", "--search"),
        )
    )
    lines.extend(
        _fish_standalone_flags(
            "tides",
            TIDES_FLAGS,
            lang=True,
            theme=True,
            value_flags=("--station", "--search"),
        )
    )
    lines.extend(
        _fish_standalone_flags(
            "sunshine",
            SUNSHINE_FLAGS,
            theme=True,
        )
    )

    return "\n".join(lines) + "\n"
