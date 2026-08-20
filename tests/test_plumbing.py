"""Plumbing regression tests: terminal-size env overrides, atomic writes."""

import os
import unittest
from unittest.mock import patch

from linecast._framebuffer import get_terminal_size


class TerminalSizeTests(unittest.TestCase):
    def test_columns_lines_env_overrides_are_honoured(self):
        # Status bars and tmux panes size captures via COLUMNS/LINES;
        # os.get_terminal_size ignores them, shutil's consults them first.
        with patch.dict(os.environ, {"COLUMNS": "120", "LINES": "40"}):
            self.assertEqual(tuple(get_terminal_size()), (120, 40))

    def test_fallback_without_env_or_tty(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("COLUMNS", "LINES")}
        with patch.dict(os.environ, env, clear=True):
            cols, rows = get_terminal_size()
        self.assertGreaterEqual(cols, 1)
        self.assertGreaterEqual(rows, 1)


if __name__ == "__main__":
    unittest.main()
