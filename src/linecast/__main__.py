"""python -m linecast entry point."""

import sys
from linecast import __version__

HELP = f"""\
linecast {__version__} — terminal weather, solar arc, and tide visualizations

Commands:
  weather     Weather dashboard with braille temperature curve and alerts
  sunshine    Solar arc inspired by the Apple Watch Solar face
  tides       NOAA tide chart with half-block rendering

Each command is installed separately. Run with --help for options.
"""

print(HELP.rstrip())
sys.exit(0)
