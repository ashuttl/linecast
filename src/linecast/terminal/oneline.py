"""How a one-line summary is written: in display order on a terminal, in
logical order for a status bar or a prompt, which orders it itself.

Each view's --oneline builds its line in its own package, <view>/oneline.py.
"""


def emit(line, stream=None):
    """Print a one-line summary: in display order on a terminal, in
    logical order for a status bar, which orders it itself."""
    import sys
    from linecast.terminal.bidi import for_stream
    stream = sys.stdout if stream is None else stream
    print(for_stream(line, stream), file=stream)
