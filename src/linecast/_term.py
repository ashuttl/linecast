"""Terminal input, wakeup and resize notice, for POSIX and Windows.

The live loop needs three things that the two platforms spell differently:

  - cbreak input: keys delivered as they are typed, without echo.
  - a wait that returns on a keypress, on a nudge from another thread, or
    on a timeout, whichever comes first.
  - notice that the window changed size.

POSIX gets termios cbreak, select() over stdin and a self-pipe, and
SIGWINCH.  Windows gets console modes, a kbhit() poll, and a comparison of
the reported size in place of the signal.

The one thing that does *not* differ is the byte stream.  With
ENABLE_VIRTUAL_TERMINAL_INPUT set, the Windows console emits the same
ANSI sequences a POSIX terminal does — \\033[A for up, SGR 1006 mouse
reports — so _read_key's escape parsing is shared verbatim and only the
plumbing under it is swapped out here.
"""

from __future__ import annotations

import os
import sys
import time as _time

WINDOWS = sys.platform == "win32"

# How often the Windows wait wakes to re-check kbhit() and the window size.
# Small enough that a keypress feels immediate, large enough to idle cheaply.
_POLL = 0.015

if not WINDOWS:
    import select
    import signal
    import termios
    import tty
else:
    import ctypes
    import msvcrt
    import threading
    from ctypes import wintypes

    _k32 = ctypes.windll.kernel32
    _ENABLE_PROCESSED_INPUT = 0x0001
    _ENABLE_LINE_INPUT = 0x0002
    _ENABLE_ECHO_INPUT = 0x0004
    _ENABLE_WINDOW_INPUT = 0x0008
    _ENABLE_MOUSE_INPUT = 0x0010
    _ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
    _ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

    # The console hands over a whole escape sequence per read, but _read_key
    # walks input a byte at a time; keep the remainder here rather than trust
    # the console to hold it.
    _pending = bytearray()

    def _console_handle(fd):
        """The console handle behind fd, or None if fd is not a console."""
        try:
            handle = msvcrt.get_osfhandle(fd)
        except Exception:
            return None
        mode = wintypes.DWORD()
        if not _k32.GetConsoleMode(handle, ctypes.byref(mode)):
            return None  # a pipe or a file: no console modes to set
        return handle

    def _get_mode(handle):
        mode = wintypes.DWORD()
        if not _k32.GetConsoleMode(handle, ctypes.byref(mode)):
            return None
        return mode.value

    def _pipe_ready(fd):
        """Whether a read on a non-console descriptor would return now.

        select() cannot see a pipe on Windows and a bare os.read would
        block until something arrives, so ask the pipe directly.  A
        handle that is not a pipe -- a plain file -- never blocks, so it
        counts as ready.
        """
        try:
            handle = msvcrt.get_osfhandle(fd)
        except Exception:
            return True
        avail = wintypes.DWORD()
        if not _k32.PeekNamedPipe(handle, None, 0, None,
                                  ctypes.byref(avail), None):
            return True  # not a pipe: the read returns immediately
        return avail.value > 0

    def _ready(fd, console):
        """Input waiting on fd, whether it is a console or a pipe."""
        return msvcrt.kbhit() if console else _pipe_ready(fd)


# ---------------------------------------------------------------------------
# Byte-level input, shared by _read_key
# ---------------------------------------------------------------------------
def read_byte(fd):
    """One byte of input, or None at EOF."""
    if WINDOWS:
        if _pending:
            return bytes([_pending.pop(0)])
        try:
            chunk = os.read(fd, 1024)
        except OSError:
            return None
        if not chunk:
            return None
        _pending.extend(chunk)
        return bytes([_pending.pop(0)])
    try:
        data = os.read(fd, 1)
    except OSError:
        return None
    return data or None


def wait_readable(fd, timeout):
    """Whether a byte is available within `timeout` seconds."""
    if WINDOWS:
        if _pending:
            return True
        console = _console_handle(fd) is not None
        deadline = _time.monotonic() + timeout
        while True:
            if _ready(fd, console):
                return True
            left = deadline - _time.monotonic()
            if left <= 0:
                return False
            _time.sleep(min(_POLL, left))
    try:
        return bool(select.select([fd], [], [], timeout)[0])
    except (InterruptedError, OSError):
        return False


# ---------------------------------------------------------------------------
# The live loop's terminal
# ---------------------------------------------------------------------------
_current = None  # the LiveTerminal a loop is running on, for nudge()


class LiveTerminal:
    """Cbreak input plus a wakeup any thread can pull.

    install() takes over the terminal's settings and, on POSIX, the signal
    handlers; close() puts all of it back and is safe to call twice.
    """

    def __init__(self, fd):
        self.fd = fd
        self._closed = False
        self._old_settings = None
        self._prev_handlers = {}
        self._wake_r = self._wake_w = None
        self._event = None
        self._old_in_mode = self._old_out_mode = None
        self._handle_in = self._handle_out = None
        self._size = None
        self._console = None

    # -- setup -------------------------------------------------------------
    def install(self):
        """Take the wakeup channel and resize notification."""
        global _current
        if WINDOWS:
            self._event = threading.Event()
            self._size = _terminal_size()
        else:
            self._wake_r, self._wake_w = os.pipe()
            os.set_blocking(self._wake_r, False)
            os.set_blocking(self._wake_w, False)
            # os.write to a pipe is async-signal-safe per POSIX;
            # threading.Event.set() is not, and deadlocks when SIGWINCH
            # re-enters itself during a rapid resize.
            def _on_winch(*_):
                if self._wake_w is None:
                    return  # the loop has ended and its pipe is closed
                try:
                    os.write(self._wake_w, b'\x00')
                except OSError:
                    pass
            self._prev_handlers[signal.SIGWINCH] = signal.signal(
                signal.SIGWINCH, _on_winch)

            # Route SIGTERM/SIGHUP/SIGQUIT through SystemExit so `pkill
            # radar` or a closed terminal still runs the caller's finally --
            # otherwise the alternate screen and mouse reporting are left on.
            def _exit_on_signal(signum, _frame):
                sys.exit(128 + signum)

            for _sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
                try:
                    self._prev_handlers[_sig] = signal.signal(
                        _sig, _exit_on_signal)
                except (ValueError, OSError):
                    pass
        _current = self

    def set_cbreak(self):
        """Keys as they are typed, no echo."""
        if WINDOWS:
            self._handle_in = _console_handle(self.fd)
            # stdout may be captured or replaced, in which case it has no
            # descriptor to ask about; the console's own is 1 regardless.
            try:
                out_fd = sys.stdout.fileno()
            except Exception:
                out_fd = 1
            self._handle_out = _console_handle(out_fd)
            if self._handle_in is not None:
                self._old_in_mode = _get_mode(self._handle_in)
                mode = self._old_in_mode & ~(
                    _ENABLE_LINE_INPUT | _ENABLE_ECHO_INPUT
                    | _ENABLE_PROCESSED_INPUT)
                # VIRTUAL_TERMINAL_INPUT is what makes the console speak
                # ANSI; WINDOW and MOUSE input keep those events flowing
                # into the same stream rather than being dropped.
                mode |= (_ENABLE_VIRTUAL_TERMINAL_INPUT
                         | _ENABLE_WINDOW_INPUT | _ENABLE_MOUSE_INPUT)
                _k32.SetConsoleMode(self._handle_in, mode)
            if self._handle_out is not None:
                self._old_out_mode = _get_mode(self._handle_out)
                _k32.SetConsoleMode(
                    self._handle_out,
                    self._old_out_mode | _ENABLE_VIRTUAL_TERMINAL_PROCESSING)
            return
        self._old_settings = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        # Cbreak keeps ISIG, so the tty still turns the QUIT character
        # (^\, 0x1C) into SIGQUIT -- and terminals following xterm send
        # 0x1C for ctrl-4, which macOS's screenshot shortcut (cmd-ctrl-
        # shift-4) delivers to the terminal on its way through.  The
        # default action kills the process without the finally block, and
        # the shell inherits a terminal with mouse reporting still on.
        # Disable the character: the keypress becomes an ordinary byte the
        # loop ignores, and a screenshot leaves the view standing.
        try:
            attrs = termios.tcgetattr(self.fd)
            vdisable = getattr(termios, "_POSIX_VDISABLE", None)
            if vdisable is None:
                # Only ask the fd when the constant is missing: fpathconf
                # refuses anything that is not a terminal.
                vdisable = os.fpathconf(self.fd, "PC_VDISABLE")
            attrs[6][termios.VQUIT] = vdisable
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        except (OSError, ValueError, IndexError, termios.error):
            pass

    # -- running -----------------------------------------------------------
    def wake(self):
        """Ask the loop to repaint now. Safe from any thread."""
        if WINDOWS:
            if self._event is not None:
                self._event.set()
            return
        if self._wake_w is None:
            return
        try:
            os.write(self._wake_w, b'\x00')
        except OSError:
            pass

    def _is_console(self):
        if self._console is None:
            self._console = _console_handle(self.fd) is not None
        return self._console

    def drain(self):
        """Discard wakeups queued before the frame about to be drawn."""
        if WINDOWS:
            if self._event is not None:
                self._event.clear()
            return
        if self._wake_r is None:
            return
        try:
            os.read(self._wake_r, 512)
        except OSError:
            pass

    def wait(self, timeout):
        """Block up to `timeout`. Returns 'input', 'wake' or 'timeout'."""
        if WINDOWS:
            if _pending:
                return 'input'
            deadline = _time.monotonic() + timeout
            while True:
                if self._event.is_set():
                    self._event.clear()
                    return 'wake'
                if _ready(self.fd, self._is_console()):
                    return 'input'
                size = _terminal_size()
                if size != self._size:
                    self._size = size
                    return 'wake'  # stands in for SIGWINCH
                left = deadline - _time.monotonic()
                if left <= 0:
                    return 'timeout'
                _time.sleep(min(_POLL, left))
        try:
            ready, _, _ = select.select(
                [self.fd, self._wake_r], [], [], timeout)
        except (InterruptedError, OSError):
            return 'timeout'
        if self._wake_r in ready:
            try:
                os.read(self._wake_r, 512)  # coalesce a burst of resizes
            except OSError:
                pass
            return 'wake'
        if self.fd in ready:
            return 'input'
        return 'timeout'

    # -- teardown ----------------------------------------------------------
    def close(self):
        """Put the terminal, the handlers and the wakeup channel back."""
        global _current
        if self._closed:
            return
        self._closed = True
        if _current is self:
            _current = None
        if WINDOWS:
            if self._handle_in is not None and self._old_in_mode is not None:
                _k32.SetConsoleMode(self._handle_in, self._old_in_mode)
            if self._handle_out is not None and self._old_out_mode is not None:
                _k32.SetConsoleMode(self._handle_out, self._old_out_mode)
            _pending.clear()
            return
        # The SIGWINCH handler goes back before the pipe closes.  A background
        # fetch that lands after the loop still calls nudge(); with the
        # handler left installed, its write would go to whatever file reused
        # the pipe's descriptor number.
        for _sig, _handler in self._prev_handlers.items():
            try:
                signal.signal(_sig, _handler)
            except (ValueError, OSError):
                pass
        for _fd in (self._wake_r, self._wake_w):
            if _fd is not None:
                try:
                    os.close(_fd)
                except OSError:
                    pass
        self._wake_r = self._wake_w = None
        if self._old_settings is not None:
            try:
                termios.tcsetattr(
                    self.fd, termios.TCSADRAIN, self._old_settings)
            except Exception:
                pass  # the tty may already be gone (SIGHUP)


def _terminal_size():
    try:
        return os.get_terminal_size()
    except OSError:
        return None


def nudge():
    """Ask a running live loop to repaint now, from any thread.

    Coalesces harmlessly when several arrive at once, and does nothing when
    no loop is running, so background work can call it unconditionally.
    """
    term = _current
    if term is not None:
        term.wake()
