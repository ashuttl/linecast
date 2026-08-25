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


def _use_utf8_on_windows():
    """Keep non-console output UTF-8 on Windows.

    A redirected stdout there gets the locale encoding — usually cp1252 —
    and braille, box drawing and Nerd Font glyphs are not in it, so
    `weather --print > out.txt` or piping to another command dies with
    UnicodeEncodeError.  The console itself is already UTF-8, so this
    only ever matters off-terminal.  Costs one platform check elsewhere.
    """
    import sys
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            if (stream.encoding or "").lower().replace("-", "") != "utf8":
                stream.reconfigure(encoding="utf-8")
        except Exception:
            pass  # replaced or non-reconfigurable stream: leave it alone


_use_utf8_on_windows()
