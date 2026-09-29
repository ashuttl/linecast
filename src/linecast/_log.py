"""The --debug transcript, and the one line every fallback writes to it.

A provider, cache or decoder that fails returns its documented fallback
and calls log_failure, which prints one line naming the provider, the
operation, the host, the exception and the fallback, and prints nothing
unless --debug is on (docs/architecture.md, "Diagnostics").  Everything
that touches the network or the disk calls it, so it sits at the bottom
of the package and imports nothing of linecast's."""

import sys

_DEBUG = False


def set_debug(value):
    global _DEBUG
    _DEBUG = bool(value)


def debug_enabled():
    """Whether --debug is on, for a caller whose message costs something
    to build."""
    return _DEBUG


def debug_log(msg):
    """Print a diagnostic message to stderr when --debug is active."""
    if _DEBUG:
        print(f"[linecast] {msg}", file=sys.stderr)


def redact_url(url: str) -> str:
    """The URL as a diagnostic may show it: scheme, host and path.

    Userinfo, query and fragment are removed.  The query is represented
    by ``?...`` so the reader can still tell that one was present.
    """
    from urllib.parse import urlsplit, urlunsplit
    try:
        parts = urlsplit(url)
    except ValueError:
        return "(unparseable URL)"
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"  # an IPv6 literal, as it was written
    try:
        port = parts.port
    except ValueError:
        port = None
    if host and port is not None:
        host = f"{host}:{port}"
    query = "..." if parts.query else ""
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def _redact_urls_in_text(text: str) -> str:
    """Replace URL-like substrings with their diagnostic-safe form."""
    import re
    return re.sub(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>\"']+",
                  lambda match: redact_url(match.group(0)), text)


def _host_of(where):
    """The host named by a URL, or the string itself when it is a bare
    host or a file name a caller passed instead of a URL."""
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(where)
    except ValueError:
        return ""  # an unbalanced IPv6 bracket: name nothing, never raise
    if parts.hostname:
        return parts.hostname
    if parts.netloc or parts.scheme:
        return parts.scheme or ""
    # no scheme: a bare host, or a cache file's name
    return parts.path.split("/", 1)[0].rsplit("@", 1)[-1]


def log_failure(provider, operation, exc, url=None, fallback=None, trace=False):
    """One debug line for a failure the caller absorbed, in the house
    style:

        <provider>: <operation> failed (<host>) -- <ExcType>: <message>;
        <fallback>

    Only the URL's host is shown -- never its path, query, userinfo or
    any header. URL-like text in the exception and traceback is redacted,
    and the message is its first line cut at 120 characters, so a server's
    error page cannot spill the rest. Nothing is formatted, let alone
    printed, unless --debug is on: this runs inside the tile pools.

    `trace` follows the line with the traceback, still only with
    --debug on.  It is for a worker that died, not a request that
    failed: what a live view's WorkerWatch shows once the screen is
    back, so a --print run of the same command shows no less.
    """
    if not _DEBUG:
        return
    where = ""
    if url:
        host = _host_of(str(url))
        where = f" ({host})" if host else ""
    text = _redact_urls_in_text(str(exc))
    what = type(exc).__name__
    if text:
        what += ": " + text.splitlines()[0][:120]
    tail = f"; {fallback}" if fallback else ""
    debug_log(f"{provider}: {operation} failed{where} -- {what}{tail}")
    if trace and exc.__traceback__ is not None:
        import traceback
        rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        sys.stderr.write(_redact_urls_in_text(rendered))


def log_skipped(provider, what, skipped, total, exc=None):
    """One debug line when parsing dropped records a provider sent, with
    the last exception standing in for the lot.  Nothing when nothing was
    dropped, so a loop can count skips and call this unconditionally:
    one bad record is a glitch, `40 of 40 skipped` is a schema change.
    """
    if not skipped or not _DEBUG:
        return
    tail = f"{skipped} of {total} skipped"
    if exc is None:
        debug_log(f"{provider}: parse of {what} failed -- {tail}")
    else:
        log_failure(provider, f"parse of {what}", exc, fallback=tail)
