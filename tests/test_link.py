"""linecast link makes and removes the short names beside the binary."""

import os
import stat
import sys
import unittest
from unittest.mock import patch

from linecast import link


class LinkTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.binary = os.path.join(self.dir, "linecast")
        with open(self.binary, "w") as f:
            f.write("#!/bin/sh\necho linecast\n")
        os.chmod(self.binary, stat.S_IRWXU)

    def _run(self, *argv):
        from io import StringIO
        out = StringIO()
        with patch.object(sys, "argv", [self.binary, *argv]), \
                patch("sys.stdout", out), self.assertRaises(SystemExit) as cm:
            link.main()
        return cm.exception.code, out.getvalue()

    def test_links_every_name_then_removes_them(self):
        code, out = self._run()
        self.assertEqual(code, 0)
        for name in link.SHORT_NAMES:
            path = os.path.join(self.dir, name)
            self.assertTrue(os.path.lexists(path), name)
            self.assertTrue(link._is_ours(path, self.binary), name)
        # a second run changes nothing and says so
        code, out = self._run()
        self.assertEqual(code, 0)
        self.assertIn("already linked", out)
        code, out = self._run("--remove")
        self.assertEqual(code, 0)
        for name in link.SHORT_NAMES:
            self.assertFalse(os.path.lexists(os.path.join(self.dir, name)), name)

    def test_leaves_another_programs_binary_alone(self):
        other = os.path.join(self.dir, "weather")
        with open(other, "w") as f:
            f.write("#!/bin/sh\necho someone else\n")
        code, out = self._run()
        self.assertEqual(code, 1)
        self.assertIn("weather: something else", out)
        with open(other) as f:
            self.assertIn("someone else", f.read())
        self.assertTrue(os.path.lexists(os.path.join(self.dir, "moon")))
        code, out = self._run("--remove")
        self.assertEqual(code, 1)
        self.assertIn("weather: not a link", out)
        self.assertTrue(os.path.exists(other))

    def test_dir_option(self):
        import tempfile
        target = tempfile.mkdtemp()
        code, out = self._run("--dir", target)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.lexists(os.path.join(target, "tides")))
        self.assertFalse(os.path.lexists(os.path.join(self.dir, "tides")))

    def test_refuses_under_python_m(self):
        with patch.object(sys, "argv", ["/x/linecast/__main__.py"]), \
                patch("sys.stderr"), self.assertRaises(SystemExit) as cm:
            link.main()
        self.assertEqual(cm.exception.code, 1)
