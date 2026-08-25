import unittest

from linecast import _graphics


class MouseDecodeTests(unittest.TestCase):
    def test_decode_sgr_mouse_press(self):
        got = _graphics._decode_sgr_mouse(b"<0;12;7M")
        self.assertEqual(got, ('mouse', 0, 12, 7, False))

    def test_decode_sgr_mouse_release(self):
        got = _graphics._decode_sgr_mouse(b"<0;12;7m")
        self.assertEqual(got, ('mouse', 0, 12, 7, True))

    def test_decode_legacy_mouse_press(self):
        # Legacy payload is Cb/Cx/Cy bytes, each offset by +32.
        got = _graphics._decode_legacy_mouse(bytes([32, 152, 41]))
        self.assertEqual(got, ('mouse', 0, 120, 9, False))

    def test_decode_legacy_mouse_release(self):
        got = _graphics._decode_legacy_mouse(bytes([35, 50, 60]))
        self.assertEqual(got, ('mouse', 3, 18, 28, True))

    def test_decode_sgr_motion_is_not_a_release(self):
        """Windows Terminal ends button-less motion with 'm'.

        xterm reserves that for releases, so the terminator alone would
        report every hover as a release and the motion would be dropped.
        """
        got = _graphics._decode_sgr_mouse(b"<35;12;7m")
        self.assertEqual(got, ('mouse', 35, 12, 7, False))

    def test_decode_legacy_motion_is_not_a_release(self):
        # cb 35 = motion (0x20) with no button held (0b11).
        got = _graphics._decode_legacy_mouse(bytes([35 + 32, 50, 60]))
        self.assertEqual(got, ('mouse', 35, 18, 28, False))

    def test_decode_legacy_mouse_rejects_invalid(self):
        self.assertIsNone(_graphics._decode_legacy_mouse(bytes([31, 40, 40])))


class MouseWheelTests(unittest.TestCase):
    def test_wheel_codes_are_normalized(self):
        self.assertEqual(_graphics._normalize_wheel_cb(64), 64)
        self.assertEqual(_graphics._normalize_wheel_cb(65), 65)
        # With modifier bit set, keep direction but normalize to 64/65.
        self.assertEqual(_graphics._normalize_wheel_cb(68), 64)
        self.assertEqual(_graphics._normalize_wheel_cb(69), 65)

    def test_non_wheel_returns_none(self):
        self.assertIsNone(_graphics._normalize_wheel_cb(0))
        self.assertIsNone(_graphics._normalize_wheel_cb(3))


if __name__ == "__main__":
    unittest.main()
