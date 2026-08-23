"""Linecast — terminal weather, solar arc, and tide visualizations."""


def __getattr__(name):
    # importlib.metadata costs ~20ms at import, paid by every command;
    # nothing needs the version string before the first HTTP request,
    # so it resolves on first touch instead.  Modules that want the
    # agent string should call user_agent() at request time rather
    # than `from linecast import USER_AGENT`, which resolves it at
    # import anyway.
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


def user_agent():
    """The User-Agent header value, resolved on first call and cached."""
    return globals().get("USER_AGENT") or __getattr__("USER_AGENT")
