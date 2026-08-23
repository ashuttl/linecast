

class TestPackedDepths:
    """Sparse tiles arrive as 1/2/4-bit indexed or grayscale PNGs."""

    def _png(self, width, height, depth, color_type, rows, palette=None,
             trns=None):
        import struct, zlib
        def chunk(t, b):
            return (struct.pack(">I", len(b)) + t + b
                    + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF))
        ihdr = struct.pack(">IIBBBBB", width, height, depth, color_type, 0, 0, 0)
        raw = b"".join(b"\x00" + r for r in rows)
        out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
        if palette:
            out += chunk(b"PLTE", palette)
        if trns:
            out += chunk(b"tRNS", trns)
        return out + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

    def test_4bit_indexed(self):
        from linecast._png import decode_rgba
        pal = bytes((0, 0, 0, 10, 20, 30, 40, 50, 60))
        # indices 1,2 then 0 padded: 0x12, 0x00
        w, h, rgba = decode_rgba(self._png(3, 1, 4, 3, [bytes((0x12, 0x00))],
                                           palette=pal, trns=bytes((0,))))
        assert tuple(rgba[0:4]) == (10, 20, 30, 255)
        assert tuple(rgba[4:8]) == (40, 50, 60, 255)
        assert rgba[11] == 0

    def test_1bit_gray_scales_to_white(self):
        from linecast._png import decode_rgba
        w, h, rgba = decode_rgba(self._png(2, 2, 1, 0, [b"\x80", b"\x40"]))
        assert tuple(rgba[0:3]) == (255, 255, 255)
        assert tuple(rgba[4:7]) == (0, 0, 0)
        assert tuple(rgba[12:15]) == (255, 255, 255)

    def test_2bit_indexed_across_rows_with_filter(self):
        from linecast._png import decode_rgba
        pal = bytes(range(12))
        png = self._png(4, 1, 2, 3, [bytes((0b00011011,))], palette=pal)
        w, h, rgba = decode_rgba(png)
        assert [rgba[i * 4] for i in range(4)] == [0, 3, 6, 9]
