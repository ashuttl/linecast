from unittest.mock import patch

from linecast import _radar_palettes as pal
from linecast import _radar_sources as sources
from linecast import _radar_tiles as tiles
from linecast import _radar_ub as ub


class TestDecode:
    def test_gray_is_dbz_plus_32(self):
        assert pal.decode(42) == (10, False)
        assert pal.decode(85) == (53, False)

    def test_high_bit_flags_snow(self):
        assert pal.decode(128 + 42) == (10, True)


class TestUniversalBlue:
    def _tile(self, *colours):
        buf = bytearray()
        for c in colours:
            buf += bytes(c)
        return buf

    def test_known_colours_decode_to_their_gray(self):
        # published table: dBZ 20 rain is #00a3e0, so gray 52
        buf = self._tile((0x00, 0xa3, 0xe0, 0xff))
        ub.to_gray(buf)
        assert tuple(buf) == (52, 52, 52, 255)
        assert pal.decode(52) == (20, False)

    def test_snow_colours_carry_the_snow_flag(self):
        # every colour in the snow half of the table decodes back to snow
        snow = [g for g in range(128, 256) if ub._TABLE[g * 4 + 3]]
        assert snow, "snow rows expected in the table"
        buf = self._tile(*(ub._TABLE[g * 4:g * 4 + 4] for g in snow))
        ub.to_gray(buf)
        for i in range(len(snow)):
            _, is_snow = pal.decode(buf[i * 4])
            assert is_snow

    def test_round_trip_is_exact_for_every_visible_gray(self):
        # a table colour maps to a gray whose own colour is that colour —
        # a saturated run collapses to its first gray, same colour either way
        vis = [g for g in range(256) if ub._TABLE[g * 4 + 3]]
        buf = self._tile(*(ub._TABLE[g * 4:g * 4 + 4] for g in vis))
        ub.to_gray(buf)
        for i, g in enumerate(vis):
            got = buf[i * 4]
            assert ub._TABLE[got * 4:got * 4 + 4] == ub._TABLE[g * 4:g * 4 + 4]
            assert got <= g  # the run's first gray stands for it

    def test_transparent_stays_transparent(self):
        buf = self._tile((0, 0, 0, 0))
        ub.to_gray(buf)
        assert tuple(buf) == (0, 0, 0, 0)

    def test_a_drifted_colour_snaps_to_the_nearest_entry(self):
        buf = self._tile((0x00, 0xa4, 0xe0, 0xff))  # one green off dBZ 20
        ub.to_gray(buf)
        assert tuple(buf) == (52, 52, 52, 255)


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

    def test_rainviewer_local_theme_decodes_then_recolours(self):
        seen = {}

        def fake_reproject(*a, **k):
            seen.update(k)
            # a dBZ-28 Universal Blue pixel, as the decode hook gets it
            tile = bytearray(ub._TABLE[60 * 4:60 * 4 + 4])
            k["transform"](tile)
            return 1, 1, tile

        with patch.object(sources._TileSource, "_refresh"), \
                patch.object(tiles, "reproject", fake_reproject):
            src = sources.RainViewerSource("ember")
            _w, _h, rgba = src.frame_rgba((0, 0, 1, 1), 1, 1,
                                          sources.Frame(None, "/p"))
        assert seen["smooth"] is True
        assert seen["transform"] is ub.to_gray
        assert tuple(rgba[:3]) == pal.PALETTES["ember"].rain(28)

    def test_rainviewer_server_theme_unchanged(self):
        with patch.object(sources._TileSource, "_refresh"):
            src = sources.RainViewerSource(2)
        assert src.palette is None and src.transform is None
        assert src.provider.options == "1_1"
