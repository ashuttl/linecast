"""Chart headings with a fine rule and a quieter unit label."""

from linecast.terminal.color import RESET, fg
from linecast.terminal.textwidth import fit, visible_len


def render_heading(title, width, *, text_rgb, dim_rgb, overline="", unit="", ruled=True):
    """Fit a heading to display cells, ruling only the title, never its unit.

    An optional date sits on its own line above the title, so it keeps
    the language's date order without needing to fit into a sentence.
    Callers can omit the rule when vertical space is tight.
    """
    text, dim = fg(*text_rgb), fg(*dim_rgb)
    suffix = f"  {dim}{unit}{RESET}" if unit else ""
    title = fit(title, max(0, width - visible_len(suffix)))
    lines = [f"{text}{fit(overline, width)}{RESET}"] if overline else []
    lines.append(f"{text}{title}{RESET}{suffix}")
    if ruled:
        lines.append(f"{dim}{'─' * visible_len(title)}{RESET}")
    return lines
