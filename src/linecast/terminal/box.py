"""Floating chrome: where a panel goes on the screen, and the pieces it is
drawn with.  The help panel, the menus, the toasts, the search panels and
the alert modal all go out on overlay()'s floating channel as rows placed
by cursor address, so they share the placing and the centring here."""

from linecast.terminal.color import RESET, bg
from linecast.terminal.textwidth import pad

REVERSE = "\033[7m"         # the selected row, and a text field's caret
REVERSE_OFF = "\033[27m"
CARET = f"{REVERSE} {REVERSE_OFF}"


def at(row, col):
    """The cursor address of *row*, *col*, counted from 1.  In exactly
    this form, which bidi's pass looks for (_CUP) when it mirrors a
    frame."""
    return f"\033[{row};{col}H"


def place(lines, top, left):
    """*lines* one under another from row *top*, each from column *left*."""
    return "".join(f"{at(top + i, left)}{line}" for i, line in enumerate(lines))


def centre(cols, rows, width, height):
    """The top row and left column that centre a *width* by *height* box
    on the screen, the odd row or column below and to the right, and
    never above or left of the first."""
    return max(1, (rows - height) // 2 + 1), max(1, (cols - width) // 2 + 1)


def panel_row(n, body, width, surface):
    """Row *n* of a panel against the left edge: *body* filled out to
    *width* on the *surface* colour."""
    return f"{at(n, 1)}{bg(*surface)}{pad(body, width)}{RESET}"
