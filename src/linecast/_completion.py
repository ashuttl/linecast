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
    "id",
)

# radar --theme palettes; keep in sync with _radar_sources.THEMES
THEME_VALUES = ("dark-sky", "universal-blue", "rainbow", "nexrad", "original",
                "titan", "twc", "meteored", "datameteo", "viper", "mrms",
                "max-storm", "black-white")
# radar --layer display layers; keep in sync with radar.LAYERS
LAYER_VALUES = ("radar", "satellite")
# maps --view modes; keep in sync with _maps_style.MODES
MAPS_VIEW_VALUES = ("street", "terrain", "now")
# maps --profile values; keep in sync with _maps_route.PROFILES
MAPS_PROFILE_VALUES = ("car", "bike", "foot")
# radar --layers condition layers; keep in sync with radar.LAYER_NAMES
CONDITION_VALUES = ("temp", "wind", "temp,wind")
SHELLS = ("bash", "zsh", "fish", "nu", "nushell")

GLOBAL_FLAGS = ("--help", "-h", "--version", "-v")
TOP_LEVEL_COMMANDS = ("weather", "sunshine", "moon", "tides", "radar", "maps",
                      "location", "units", "completion")
LOCATION_SUBCOMMANDS = ("show", "set", "auto", "search")
LOCATION_FLAGS = ("--help", "-h", "--version")
UNITS_SUBCOMMANDS = ("show", "metric", "imperial", "auto")
UNITS_FLAGS = ("--help", "-h", "--version")

WEATHER_FLAGS = (
    "--help",
    "-h",
    "--version",
    "--print",
    "--live",
    "--oneline",
    "--json",
    "--location",
    "--search",
    "--emoji",
    "--metric",
    "--celsius",
    "--fahrenheit",
    "--no-shading",
    "--lang",
    "--classic-colors",
    "--legacy-colors",
    "--debug",
)

TIDES_FLAGS = (
    "--help",
    "-h",
    "--version",
    "--print",
    "--live",
    "--oneline",
    "--json",
    "--station",
    "--search",
    "--nearby",
    "--metric",
    "--lang",
    "--classic-colors",
    "--legacy-colors",
    "--debug",
)

SUNSHINE_FLAGS = (
    "--help",
    "-h",
    "--version",
    "--print",
    "--live",
    "--oneline",
    "--json",
    "--emoji",
    "--classic-colors",
    "--legacy-colors",
    "--debug",
)

MOON_FLAGS = (
    "--help",
    "-h",
    "--version",
    "--print",
    "--live",
    "--oneline",
    "--json",
    "--emoji",
    "--lang",
    "--classic-colors",
    "--legacy-colors",
    "--debug",
)

RADAR_FLAGS = (
    "--help",
    "-h",
    "--version",
    "--print",
    "--live",
    "--oneline",
    "--location",
    "--search",
    "--zoom",
    "--theme",
    "--layer",
    "--layers",
    "--emoji",
    "--lang",
    "--classic-colors",
    "--legacy-colors",
    "--debug",
)

MAPS_FLAGS = (
    "--help",
    "-h",
    "--version",
    "--print",
    "--live",
    "--oneline",
    "--location",
    "--search",
    "--zoom",
    "--view",
    "--to",
    "--from",
    "--profile",
    "--emoji",
    "--lang",
    "--classic-colors",
    "--legacy-colors",
    "--debug",
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
    if key in ("nu", "nushell"):
        return _nu_script()
    raise ValueError(f"unknown shell '{shell}'")


def _bash_script():
    langs = _SPACE.join(LANG_CODES)
    themes = _SPACE.join(THEME_VALUES)
    layers = _SPACE.join(LAYER_VALUES)
    views = _SPACE.join(MAPS_VIEW_VALUES)
    profiles = _SPACE.join(MAPS_PROFILE_VALUES)
    conditions = _SPACE.join(CONDITION_VALUES)
    top = _SPACE.join((*TOP_LEVEL_COMMANDS, *GLOBAL_FLAGS))
    weather = _SPACE.join(WEATHER_FLAGS)
    tides = _SPACE.join(TIDES_FLAGS)
    sunshine = _SPACE.join(SUNSHINE_FLAGS)
    moon = _SPACE.join(MOON_FLAGS)
    radar = _SPACE.join(RADAR_FLAGS)
    maps = _SPACE.join(MAPS_FLAGS)
    completion = _SPACE.join(COMPLETION_FLAGS)
    location = _SPACE.join(LOCATION_FLAGS)
    location_sub = _SPACE.join(LOCATION_SUBCOMMANDS)
    units = _SPACE.join(UNITS_FLAGS)
    units_sub = _SPACE.join(UNITS_SUBCOMMANDS)
    shells = _SPACE.join(SHELLS)

    return f"""# bash completion for linecast
_linecast_lang_values="{langs}"
_linecast_theme_values="{themes}"
_linecast_layer_values="{layers}"
_linecast_view_values="{views}"
_linecast_profile_values="{profiles}"
_linecast_condition_values="{conditions}"

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
    --layer)
      COMPREPLY=( $(compgen -W "$_linecast_layer_values" -- "$cur") )
      return 0
      ;;
    --layers)
      COMPREPLY=( $(compgen -W "$_linecast_condition_values" -- "$cur") )
      return 0
      ;;
    --view)
      COMPREPLY=( $(compgen -W "$_linecast_view_values" -- "$cur") )
      return 0
      ;;
    --profile)
      COMPREPLY=( $(compgen -W "$_linecast_profile_values" -- "$cur") )
      return 0
      ;;
    --location|--search|--station|--zoom|--to|--from)
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
  if [[ "$cur" == --layers=* ]]; then
    _linecast_complete_value_list "--layers=" "$_linecast_condition_values"
    return 0
  fi
  if [[ "$cur" == --layer=* ]]; then
    _linecast_complete_value_list "--layer=" "$_linecast_layer_values"
    return 0
  fi
  if [[ "$cur" == --view=* ]]; then
    _linecast_complete_value_list "--view=" "$_linecast_view_values"
    return 0
  fi
  if [[ "$cur" == --profile=* ]]; then
    _linecast_complete_value_list "--profile=" "$_linecast_profile_values"
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
    moon)
      _linecast_complete_flags {moon}
      ;;
    radar)
      _linecast_complete_flags {radar}
      ;;
    maps)
      _linecast_complete_flags {maps}
      ;;
    location)
      _linecast_complete_flags {location}
      COMPREPLY+=( $(compgen -W "{location_sub}" -- "$cur") )
      ;;
    units)
      _linecast_complete_flags {units}
      COMPREPLY+=( $(compgen -W "{units_sub}" -- "$cur") )
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
    weather|tides|sunshine|moon|radar|maps|location|units|completion)
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

_linecast_complete_moon() {{
  local cur prev
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev=""
  if (( COMP_CWORD > 0 )); then
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  fi
  _linecast_complete_command moon
}}

_linecast_complete_radar() {{
  local cur prev
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev=""
  if (( COMP_CWORD > 0 )); then
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  fi
  _linecast_complete_command radar
}}

_linecast_complete_maps() {{
  local cur prev
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev=""
  if (( COMP_CWORD > 0 )); then
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  fi
  _linecast_complete_command maps
}}

complete -F _linecast_complete linecast
complete -F _linecast_complete_weather weather
complete -F _linecast_complete_tides tides
complete -F _linecast_complete_sunshine sunshine
complete -F _linecast_complete_moon moon
complete -F _linecast_complete_radar radar
complete -F _linecast_complete_maps maps
"""


def _zsh_script():
    langs = _SPACE.join(LANG_CODES)
    themes = _SPACE.join(THEME_VALUES)
    layers = _SPACE.join(LAYER_VALUES)
    views = _SPACE.join(MAPS_VIEW_VALUES)
    profiles = _SPACE.join(MAPS_PROFILE_VALUES)
    conditions = _SPACE.join(CONDITION_VALUES)
    top = _SPACE.join((*TOP_LEVEL_COMMANDS, *GLOBAL_FLAGS))
    weather = _SPACE.join(WEATHER_FLAGS)
    tides = _SPACE.join(TIDES_FLAGS)
    sunshine = _SPACE.join(SUNSHINE_FLAGS)
    moon = _SPACE.join(MOON_FLAGS)
    radar = _SPACE.join(RADAR_FLAGS)
    maps = _SPACE.join(MAPS_FLAGS)
    completion = _SPACE.join(COMPLETION_FLAGS)
    location = _SPACE.join(LOCATION_FLAGS)
    location_sub = _SPACE.join(LOCATION_SUBCOMMANDS)
    units = _SPACE.join(UNITS_FLAGS)
    units_sub = _SPACE.join(UNITS_SUBCOMMANDS)
    shells = _SPACE.join(SHELLS)

    return f"""#compdef linecast weather sunshine moon tides radar maps

typeset -a _linecast_lang_values
_linecast_lang_values=({langs})
typeset -a _linecast_theme_values
_linecast_theme_values=({themes})
typeset -a _linecast_layer_values
_linecast_layer_values=({layers})
typeset -a _linecast_view_values
_linecast_view_values=({views})
typeset -a _linecast_profile_values
_linecast_profile_values=({profiles})
typeset -a _linecast_condition_values
_linecast_condition_values=({conditions})

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
    --layer)
      compadd -- "${{_linecast_layer_values[@]}}"
      return 0
      ;;
    --layers)
      compadd -- "${{_linecast_condition_values[@]}}"
      return 0
      ;;
    --view)
      compadd -- "${{_linecast_view_values[@]}}"
      return 0
      ;;
    --profile)
      compadd -- "${{_linecast_profile_values[@]}}"
      return 0
      ;;
    --location|--search|--station|--zoom|--to|--from)
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
  if [[ "$cur" == --layers=* ]]; then
    _linecast_complete_value_eq "--layers=" "${{_linecast_condition_values[@]}}"
    return 0
  fi
  if [[ "$cur" == --layer=* ]]; then
    _linecast_complete_value_eq "--layer=" "${{_linecast_layer_values[@]}}"
    return 0
  fi
  if [[ "$cur" == --view=* ]]; then
    _linecast_complete_value_eq "--view=" "${{_linecast_view_values[@]}}"
    return 0
  fi
  if [[ "$cur" == --profile=* ]]; then
    _linecast_complete_value_eq "--profile=" "${{_linecast_profile_values[@]}}"
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
    moon)
      _linecast_add_flags {moon}
      ;;
    radar)
      _linecast_add_flags {radar}
      ;;
    maps)
      _linecast_add_flags {maps}
      ;;
    location)
      _linecast_add_flags {location}
      compadd -- {location_sub}
      ;;
    units)
      _linecast_add_flags {units}
      compadd -- {units_sub}
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
      weather|tides|sunshine|moon|radar|maps|location|units|completion)
        _linecast_complete_command "$cmd"
        ;;
    esac
    return 0
  fi

  _linecast_complete_command "$svc"
  return 0
}}

compdef _linecast linecast weather sunshine moon tides radar maps
"""


def _fish_command_flags(command, flags, lang=False, theme=False, layer=False,
                        layers=False, view=False, profile=False,
                        value_flags=()):
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
        if flag == "--layer" and layer:
            values = _SPACE.join(LAYER_VALUES)
            lines.append(
                f"complete -c linecast -f -n '{cond}' -l layer -r -a '{values}'"
            )
            continue
        if flag == "--layers" and layers:
            values = _SPACE.join(CONDITION_VALUES)
            lines.append(
                f"complete -c linecast -f -n '{cond}' -l layers -r -a '{values}'"
            )
            continue
        if flag == "--view" and view:
            values = _SPACE.join(MAPS_VIEW_VALUES)
            lines.append(
                f"complete -c linecast -f -n '{cond}' -l view -r -a '{values}'"
            )
            continue
        if flag == "--profile" and profile:
            values = _SPACE.join(MAPS_PROFILE_VALUES)
            lines.append(
                f"complete -c linecast -f -n '{cond}' -l profile -r "
                f"-a '{values}'"
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


def _fish_standalone_flags(command, flags, lang=False, theme=False,
                           layer=False, layers=False, view=False,
                           profile=False, value_flags=()):
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
        if flag == "--layer" and layer:
            values = _SPACE.join(LAYER_VALUES)
            lines.append(
                f"complete -c {command} -f -l layer -r -a '{values}'"
            )
            continue
        if flag == "--layers" and layers:
            values = _SPACE.join(CONDITION_VALUES)
            lines.append(
                f"complete -c {command} -f -l layers -r -a '{values}'"
            )
            continue
        if flag == "--view" and view:
            values = _SPACE.join(MAPS_VIEW_VALUES)
            lines.append(
                f"complete -c {command} -f -l view -r -a '{values}'"
            )
            continue
        if flag == "--profile" and profile:
            values = _SPACE.join(MAPS_PROFILE_VALUES)
            lines.append(
                f"complete -c {command} -f -l profile -r -a '{values}'"
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
        "complete -c linecast -f -n '__fish_use_subcommand' -a 'weather sunshine moon tides radar maps location units completion'",
        "complete -c linecast -f -n '__fish_use_subcommand' -l help -s h",
        "complete -c linecast -f -n '__fish_use_subcommand' -l version -s v",
        "complete -c linecast -f -n '__fish_seen_subcommand_from completion' -a 'bash zsh fish'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from completion' -l help -s h",
        "complete -c linecast -f -n '__fish_seen_subcommand_from location' -a 'show set auto search'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from location' -l help -s h",
        "complete -c linecast -f -n '__fish_seen_subcommand_from units' -a 'show metric imperial auto'",
        "complete -c linecast -f -n '__fish_seen_subcommand_from units' -l help -s h",
    ]

    lines.extend(
        _fish_command_flags(
            "weather",
            WEATHER_FLAGS,
            lang=True,
            value_flags=("--location", "--search"),
        )
    )
    lines.extend(
        _fish_command_flags(
            "tides",
            TIDES_FLAGS,
            lang=True,
            value_flags=("--station", "--search"),
        )
    )
    lines.extend(
        _fish_command_flags(
            "sunshine",
            SUNSHINE_FLAGS,
        )
    )
    lines.extend(
        _fish_command_flags(
            "moon",
            MOON_FLAGS,
            lang=True,
        )
    )
    lines.extend(
        _fish_command_flags(
            "radar",
            RADAR_FLAGS,
            lang=True,
            theme=True,
            layer=True,
            layers=True,
            value_flags=("--location", "--search", "--zoom"),
        )
    )
    lines.extend(
        _fish_command_flags(
            "maps",
            MAPS_FLAGS,
            lang=True,
            view=True,
            profile=True,
            value_flags=("--location", "--search", "--zoom", "--to",
                         "--from"),
        )
    )

    lines.extend(
        _fish_standalone_flags(
            "weather",
            WEATHER_FLAGS,
            lang=True,
            value_flags=("--location", "--search"),
        )
    )
    lines.extend(
        _fish_standalone_flags(
            "tides",
            TIDES_FLAGS,
            lang=True,
            value_flags=("--station", "--search"),
        )
    )
    lines.extend(
        _fish_standalone_flags(
            "sunshine",
            SUNSHINE_FLAGS,
        )
    )
    lines.extend(
        _fish_standalone_flags(
            "moon",
            MOON_FLAGS,
            lang=True,
        )
    )
    lines.extend(
        _fish_standalone_flags(
            "radar",
            RADAR_FLAGS,
            lang=True,
            theme=True,
            layer=True,
            layers=True,
            value_flags=("--location", "--search", "--zoom"),
        )
    )
    lines.extend(
        _fish_standalone_flags(
            "maps",
            MAPS_FLAGS,
            lang=True,
            view=True,
            profile=True,
            value_flags=("--location", "--search", "--zoom", "--to",
                         "--from"),
        )
    )

    return "\n".join(lines) + "\n"


def _nu_flags(flags, lang=False, theme=False, layer=False,
              layers=False, view=False, profile=False,
              value_flags=()):
    lines = []
    for flag in flags:
        if flag in ("-h", "-v"):
            continue
        if flag == "--help":
            lines.append("    --help(-h) # Show help")
            continue
        if flag == "--version":
            if "-v" in flags:
                lines.append("    --version(-v) # Show version")
            else:
                lines.append("    --version # Show version")
            continue
        if flag == "--lang" and lang:
            lines.append('    --lang: string@"nu-complete linecast-lang"')
            continue
        if flag == "--theme" and theme:
            lines.append('    --theme: string@"nu-complete linecast-theme"')
            continue
        if flag == "--layer" and layer:
            lines.append('    --layer: string@"nu-complete linecast-layer"')
            continue
        if flag == "--layers" and layers:
            lines.append('    --layers: string@"nu-complete linecast-layers"')
            continue
        if flag == "--view" and view:
            lines.append('    --view: string@"nu-complete linecast-view"')
            continue
        if flag == "--profile" and profile:
            lines.append('    --profile: string@"nu-complete linecast-profile"')
            continue
        if flag in value_flags:
            lines.append(f"    {flag}: string")
            continue
        if flag.startswith("--"):
            lines.append(f"    {flag}")
    return lines


def _nu_extern(cmd_name, flags_lines, positional_args=()):
    lines = [f'export extern "{cmd_name}" [']
    for pos in positional_args:
        lines.append(f"    {pos}")
    lines.extend(flags_lines)
    lines.append("]")
    lines.append("")
    return lines


def _nu_script():
    lines = [
        "# nushell completion for linecast",
        "",
        'def "nu-complete linecast-lang" [] {',
        "    [ " + " ".join(f'"{code}"' for code in LANG_CODES) + " ]",
        "}",
        "",
        'def "nu-complete linecast-theme" [] {',
        "    [ " + " ".join(f'"{theme}"' for theme in THEME_VALUES) + " ]",
        "}",
        "",
        'def "nu-complete linecast-layer" [] {',
        "    [ " + " ".join(f'"{layer}"' for layer in LAYER_VALUES) + " ]",
        "}",
        "",
        'def "nu-complete linecast-layers" [] {',
        "    [ " + " ".join(f'"{c}"' for c in CONDITION_VALUES) + " ]",
        "}",
        "",
        'def "nu-complete linecast-view" [] {',
        "    [ " + " ".join(f'"{v}"' for v in MAPS_VIEW_VALUES) + " ]",
        "}",
        "",
        'def "nu-complete linecast-profile" [] {',
        "    [ " + " ".join(f'"{p}"' for p in MAPS_PROFILE_VALUES) + " ]",
        "}",
        "",
        'def "nu-complete linecast-shells" [] {',
        "    [ " + " ".join(f'"{s}"' for s in SHELLS) + " ]",
        "}",
        "",
        'def "nu-complete linecast-location-subcommands" [] {',
        "    [ " + " ".join(f'"{sub}"' for sub in LOCATION_SUBCOMMANDS) + " ]",
        "}",
        "",
        'export extern "linecast" [',
        "    --help(-h) # Show help",
        "    --version(-v) # Show version",
        "]",
        "",
    ]

    weather_flags = _nu_flags(
        WEATHER_FLAGS,
        lang=True,
        value_flags=("--location", "--search"),
    )
    tides_flags = _nu_flags(
        TIDES_FLAGS,
        lang=True,
        value_flags=("--station", "--search"),
    )
    sunshine_flags = _nu_flags(SUNSHINE_FLAGS)
    moon_flags = _nu_flags(MOON_FLAGS, lang=True)
    radar_flags = _nu_flags(
        RADAR_FLAGS,
        lang=True,
        theme=True,
        layer=True,
        layers=True,
        value_flags=("--location", "--search", "--zoom"),
    )
    maps_flags = _nu_flags(
        MAPS_FLAGS,
        lang=True,
        view=True,
        profile=True,
        value_flags=(
            "--location",
            "--search",
            "--zoom",
            "--to",
            "--from",
        ),
    )

    # linecast subcommands
    lines.extend(_nu_extern("linecast weather", weather_flags))
    lines.extend(_nu_extern("linecast sunshine", sunshine_flags))
    lines.extend(_nu_extern("linecast moon", moon_flags))
    lines.extend(_nu_extern("linecast tides", tides_flags))
    lines.extend(_nu_extern("linecast radar", radar_flags))
    lines.extend(_nu_extern("linecast maps", maps_flags))

    # linecast location
    lines.extend(_nu_extern(
        "linecast location",
        ["    --help(-h) # Show help", "    --version # Show version"],
        ['subcommand?: string@"nu-complete linecast-location-subcommands"'],
    ))
    lines.extend(_nu_extern(
        "linecast location show",
        ["    --help(-h) # Show help", "    --version # Show version"],
    ))
    lines.extend(_nu_extern(
        "linecast location set",
        ["    --help(-h) # Show help", "    --version # Show version"],
        ["query?: string"],
    ))
    lines.extend(_nu_extern(
        "linecast location auto",
        ["    --help(-h) # Show help", "    --version # Show version"],
    ))
    lines.extend(_nu_extern(
        "linecast location search",
        ["    --help(-h) # Show help", "    --version # Show version"],
        ["query?: string"],
    ))

    # linecast completion
    lines.extend(_nu_extern(
        "linecast completion",
        ["    --help(-h) # Show help"],
        ['shell?: string@"nu-complete linecast-shells"'],
    ))

    # standalone commands
    lines.extend(_nu_extern("weather", weather_flags))
    lines.extend(_nu_extern("sunshine", sunshine_flags))
    lines.extend(_nu_extern("moon", moon_flags))
    lines.extend(_nu_extern("tides", tides_flags))
    lines.extend(_nu_extern("radar", radar_flags))
    lines.extend(_nu_extern("maps", maps_flags))
    lines.extend(_nu_extern(
        "location",
        ["    --help(-h) # Show help", "    --version # Show version"],
        ['subcommand?: string@"nu-complete linecast-location-subcommands"'],
    ))
    lines.extend(_nu_extern(
        "location show",
        ["    --help(-h) # Show help", "    --version # Show version"],
    ))
    lines.extend(_nu_extern(
        "location set",
        ["    --help(-h) # Show help", "    --version # Show version"],
        ["query?: string"],
    ))
    lines.extend(_nu_extern(
        "location auto",
        ["    --help(-h) # Show help", "    --version # Show version"],
    ))
    lines.extend(_nu_extern(
        "location search",
        ["    --help(-h) # Show help", "    --version # Show version"],
        ["query?: string"],
    ))

    return "\n".join(lines) + "\n"
