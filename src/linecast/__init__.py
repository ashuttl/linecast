"""Linecast — terminal weather, solar arc, and tide visualizations."""


def __getattr__(name):
    # importlib.metadata costs ~40ms at import, paid by every command;
    # nothing needs the version string before the first HTTP request,
    # so it resolves on first touch instead.
    if name in ("__version__", "USER_AGENT"):
        try:
            from importlib.metadata import version
            v = version("linecast")
        except Exception:
            v = "dev"
        globals()["__version__"] = v
        globals()["USER_AGENT"] = f"linecast/{v}"
        return globals()[name]
    raise AttributeError(name)
