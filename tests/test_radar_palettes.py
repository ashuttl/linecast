from unittest.mock import patch

from linecast import _radar_palettes as pal
from linecast import _radar_sources as sources
from linecast import _radar_tiles as tiles


class TestDecode:
    def test_gray_is_dbz_plus_32(self):
        assert pal.decode(42) == (10, False)
        assert pal.decode(85) == (53, False)

    def test_high_bit_flags_snow(self):
        assert pal.decode(128 + 42) == (10, True)


class TestApply:
    def _frame(self, *grays):
        buf = bytearray()
        for g in grays:
            buf += bytes((g, g, g, 255))
        return buf

    def test_colours_through_palette_and_keeps_transparent(self):
        buf = self._frame(60) + bytearray((0, 0, 0, 0))
        pal.apply(buf, pal.PALETTES["ember"])
        assert tuple(buf[:3]) == pal.PALETTES["ember"].rain(28)
        assert buf[3] == pal._alpha(28)
        assert buf[7] == 0  # untouched

    def test_noise_floor_cleared(self):
        buf = self._frame(41)  # 9 dBZ
        pal.apply(buf, pal.PALETTES["ember"])
        assert buf[3] == 0

    def test_snow_uses_snow_ramp(self):
        buf = self._frame(128 + 70)
        pal.apply(buf, pal.PALETTES["ember"])
        assert tuple(buf[:3]) == pal.PALETTES["ember"].snow(38)

    def test_stronger_echo_is_more_opaque(self):
        assert pal._alpha(10) < pal._alpha(20) < pal._alpha(30) == 255
        assert pal._alpha(10) < 80

    def test_terminal_palette_is_dusk_through_themed(self):
        from linecast import _theme
        seen = []
        def fake_themed(c):
            seen.append(c)
            return (1, 2, 3)
        with patch.object(_theme, "themed", fake_themed):
            assert pal.PALETTES["terminal"].dark_rain(45) == (1, 2, 3)
        assert seen == [pal.PALETTES["dusk"].dark_rain(45)]

    def test_ink_flips_with_theme(self):
        from linecast import _theme
        ink = pal.PALETTES["ink"]
        with patch.object(_theme, "is_light_theme", return_value=True):
            assert ink.colour(60, False) == ink.rain(60)
        with patch.object(_theme, "is_light_theme", return_value=False):
            assert ink.colour(60, False) == ink.dark_rain(60)
        assert sum(ink.rain(60)) < sum(ink.dark_rain(60))


class TestMarangai:
    def test_bands_hold_until_the_next(self):
        m = pal.PALETTES["marangai"]
        assert m.dark_rain(16) == m.dark_rain(17)
        assert m.dark_rain(18) != m.dark_rain(19)

    def test_moderate_jumps_to_blue_without_blending(self):
        m = pal.PALETTES["marangai"]
        r, g, b = m.dark_rain(19)
        assert b > r and b > g  # straight to blue, no grey in between


class TestSourceWiring:
    def test_local_theme_fetches_raw_unsmoothed(self):
        with patch.object(sources._TileSource, "_refresh"):
            src = sources.LibreWXRSource("ember")
        assert src.palette is pal.PALETTES["ember"]
        assert src.provider.color == tiles.RAW_COLOR
        assert src.provider.options == "0_1"

    def test_server_theme_unchanged(self):
        with patch.object(sources._TileSource, "_refresh"):
            src = sources.LibreWXRSource(7)
        assert src.palette is None
        assert src.provider.color == 7
        assert src.provider.options == "1_1"

    def test_frame_rgba_recolours_local_theme(self):
        raw = bytearray((60, 60, 60, 255))
        with patch.object(sources._TileSource, "_refresh"), \
                patch.object(tiles, "reproject", return_value=(1, 1, raw)):
            src = sources.LibreWXRSource("ember")
            _w, _h, rgba = src.frame_rgba((0, 0, 1, 1), 1, 1,
                                          sources.Frame(None, "/p"))
        assert tuple(rgba[:3]) == pal.PALETTES["ember"].rain(28)
