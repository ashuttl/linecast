"""Linecast — terminal weather, solar arc, and tide visualizations."""

try:
    from importlib.metadata import version
    __version__ = version("linecast")
except Exception:
    __version__ = "dev"

USER_AGENT = f"linecast/{__version__}"
