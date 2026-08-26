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
        # The contact URL is part of the agent because FOSSGIS and
        # Nominatim ask for a client that can be reached, and a bare
        # "linecast/1.17.0" is not enough. Every host sees the same
        # string, so there is one place to change it.
        globals()["USER_AGENT"] = (
            f"linecast/{v} (+https://github.com/ashuttl/linecast)")
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


def _use_os_certificates_on_windows():
    """Verify TLS through Windows rather than Python's view of its store.

    Python's ssl module trusts the roots already cached in the Windows
    certificate store, and Windows fills that store lazily — a fresh
    install can hold barely a dozen.  Anything signed by a root it has
    not met yet dies with CERTIFICATE_VERIFY_FAILED, which is how the
    terrain tiles on s3.amazonaws.com came back empty while every other
    host worked.  truststore hands verification to the OS, which fetches
    roots on demand and honours any an administrator added — so a
    corporate TLS proxy keeps working too, which a bundled CA list would
    have broken.
    """
    import sys
    if sys.platform != "win32":
        return
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass  # not installed or refused: Python's own verification stands


_use_os_certificates_on_windows()
