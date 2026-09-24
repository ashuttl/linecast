"""Tests for the minimal pure-Python PNG decoder."""

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from linecast._png import decode_rgba, PNGError

_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(ctype, data):
    return (struct.pack(">I", len(data)) + ctype + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _encode_scanline(ftype, cur, prev, bpp):
    """Inverse of the decoder's per-filter reconstruction: raw values -> filtered bytes."""
    n = len(cur)
    out = bytearray(n)
    for x in range(n):
        raw = cur[x]
        a = cur[x - bpp] if x >= bpp else 0
        b = prev[x] if prev is not None else 0
        c = prev[x - bpp] if (prev is not None and x >= bpp) else 0
        if ftype == 0:
            val = raw
        elif ftype == 1:
            val = (raw - a) & 0xFF
        elif ftype == 2:
            val = (raw - b) & 0xFF
        elif ftype == 3:
            val = (raw - ((a + b) >> 1)) & 0xFF
        elif ftype == 4:
            val = (raw - _paeth(a, b, c)) & 0xFF
        else:
            raise ValueError(ftype)
        out[x] = val
    return bytes(out)


def _make_png(width, height, color_type, rows, bpp, palette=None, trns=None,
              depth=8, interlace=0, ftypes=None):
    """Build a PNG. `rows` is a list of per-pixel-channel byte lists (raw,
    unfiltered) of length width*bpp each. `ftypes` (default all-0) gives the
    filter type per scanline.
    """
    if ftypes is None:
        ftypes = [0] * height
    ihdr = struct.pack(">IIBBBBB", width, height, depth, color_type, 0, 0, interlace)
    raw = bytearray()
    prev = None
    for row, ftype in zip(rows, ftypes):
        raw.append(ftype)
        raw += _encode_scanline(ftype, row, prev, bpp)
        prev = row
    idat = zlib.compress(bytes(raw))
    parts = [_SIG, _chunk(b"IHDR", ihdr)]
    if palette is not None:
        parts.append(_chunk(b"PLTE", palette))
    if trns is not None:
        parts.append(_chunk(b"tRNS", trns))
    parts.append(_chunk(b"IDAT", idat))
    parts.append(_chunk(b"IEND", b""))
    return b"".join(parts)


class TestRGBA:
    def test_roundtrip_2x2(self):
        # color type 6, 4 channels/pixel; each row is a flat list of bytes.
        row0 = [255, 0, 0, 255, 0, 255, 0, 128]
        row1 = [0, 0, 255, 0, 10, 20, 30, 40]
        png = _make_png(2, 2, 6, [row0, row1], bpp=4)
        w, h, out = decode_rgba(png)
        assert (w, h) == (2, 2)
        assert len(out) == w * h * 4
        assert list(out[0:4]) == [255, 0, 0, 255]
        assert list(out[4:8]) == [0, 255, 0, 128]
        assert list(out[8:12]) == [0, 0, 255, 0]
        assert list(out[12:16]) == [10, 20, 30, 40]


class TestRGB:
    def test_alpha_filled_255(self):
        row0 = [10, 20, 30, 40, 50, 60]
        png = _make_png(2, 1, 2, [row0], bpp=3)
        w, h, out = decode_rgba(png)
        assert (w, h) == (2, 1)
        assert list(out[0:4]) == [10, 20, 30, 255]
        assert list(out[4:8]) == [40, 50, 60, 255]


class TestGrayscale:
    def test_gray_expanded_to_rgb_opaque(self):
        row0 = [100, 200]
        png = _make_png(2, 1, 0, [row0], bpp=1)
        w, h, out = decode_rgba(png)
        assert list(out[0:4]) == [100, 100, 100, 255]
        assert list(out[4:8]) == [200, 200, 200, 255]


class TestGrayAlpha:
    def test_gray_with_alpha_channel(self):
        # color type 4: 2 channels/pixel (gray, alpha)
        row0 = [50, 128, 200, 10]
        png = _make_png(2, 1, 4, [row0], bpp=2)
        w, h, out = decode_rgba(png)
        assert list(out[0:4]) == [50, 50, 50, 128]
        assert list(out[4:8]) == [200, 200, 200, 10]


class TestPalette:
    def test_without_trns_is_opaque(self):
        palette = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])  # red, green, blue
        row0 = [0, 1, 2]
        png = _make_png(3, 1, 3, [row0], bpp=1, palette=palette)
        w, h, out = decode_rgba(png)
        assert list(out[0:4]) == [255, 0, 0, 255]
        assert list(out[4:8]) == [0, 255, 0, 255]
        assert list(out[8:12]) == [0, 0, 255, 255]

    def test_with_trns_partial_alpha(self):
        palette = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])
        trns = bytes([0, 128])  # index 0 fully transparent, index 1 half
        row0 = [0, 1, 2]
        png = _make_png(3, 1, 3, [row0], bpp=1, palette=palette, trns=trns)
        w, h, out = decode_rgba(png)
        assert out[3] == 0            # idx 0 -> trns[0]
        assert out[7] == 128          # idx 1 -> trns[1]
        assert out[11] == 255         # idx 2 beyond len(trns) -> opaque


class TestFilters:
    """Each filter is exercised via its exact mathematical inverse (see
    _encode_scanline above), so decode_rgba must reconstruct the original
    raw grayscale values regardless of which filter produced the bytes.
    """

    ROWS = [
        [10, 20, 30, 40],
        [50, 40, 90, 5],
        [200, 210, 190, 250],
    ]

    def _check(self, ftype):
        ftypes = [ftype, ftype, ftype]
        png = _make_png(4, 3, 0, self.ROWS, bpp=1, ftypes=ftypes)
        w, h, out = decode_rgba(png)
        assert (w, h) == (4, 3)
        for y, row in enumerate(self.ROWS):
            for x, val in enumerate(row):
                i = (y * 4 + x) * 4
                assert list(out[i:i + 3]) == [val, val, val], (ftype, y, x)

    def test_sub(self):
        self._check(1)

    def test_up(self):
        self._check(2)

    def test_average(self):
        self._check(3)

    def test_paeth(self):
        self._check(4)

    def test_mixed_filters_per_scanline(self):
        ftypes = [0, 1, 4]
        png = _make_png(4, 3, 0, self.ROWS, bpp=1, ftypes=ftypes)
        w, h, out = decode_rgba(png)
        for y, row in enumerate(self.ROWS):
            for x, val in enumerate(row):
                i = (y * 4 + x) * 4
                assert list(out[i:i + 3]) == [val, val, val]


class TestErrors:
    def test_rejects_non_png_bytes(self):
        with pytest.raises(PNGError):
            decode_rgba(b"not a png at all, just junk bytes")

    def test_rejects_bad_filter_type(self):
        # PNG filter types are 0-4; build a stream with an invalid type (5).
        raw = bytes([5]) + bytes([1, 2])
        idat = zlib.compress(raw)
        ihdr = struct.pack(">IIBBBBB", 2, 1, 8, 0, 0, 0, 0)
        bad = b"".join([
            _SIG,
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", idat),
            _chunk(b"IEND", b""),
        ])
        with pytest.raises(PNGError):
            decode_rgba(bad)


class TestBounds:
    """A header that lies about the image can't make the decoder inflate
    or allocate beyond what the declared size needs."""

    @staticmethod
    def _png(ihdr, idat):
        return b"".join([_SIG, _chunk(b"IHDR", ihdr), _chunk(b"IDAT", idat),
                         _chunk(b"IEND", b"")])

    @staticmethod
    def _rgba_ihdr(width, height):
        return struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    def test_one_pixel_with_megabytes_of_zeros_rejected(self):
        # the issue's probe: one RGBA pixel, 4 MiB of zeros in IDAT —
        # compressed a block at a time so the test never holds 4 MiB
        import tracemalloc
        comp = zlib.compressobj()
        block = bytes(64 * 1024)
        idat = b"".join(comp.compress(block) for _ in range(64)) + comp.flush()
        png = self._png(self._rgba_ihdr(1, 1), idat)
        tracemalloc.start()
        try:
            with pytest.raises(PNGError):
                decode_rgba(png)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < 256 * 1024

    def test_oversized_dimensions_rejected_before_inflating(self):
        # an IDAT that isn't even zlib: were it inflated, the error
        # would be about the stream, not the size
        for w, h in ((100_000, 1), (1, 100_000), (16_384, 16_384),
                     (0xFFFFFFFF, 0xFFFFFFFF)):
            with pytest.raises(PNGError, match="unreasonable size"):
                decode_rgba(self._png(self._rgba_ihdr(w, h), b"junk"))

    def test_zero_dimensions_rejected(self):
        for w, h in ((0, 1), (1, 0), (0, 0)):
            with pytest.raises(PNGError, match="unreasonable size"):
                decode_rgba(self._png(self._rgba_ihdr(w, h),
                                      zlib.compress(b"")))

    def test_missing_or_short_ihdr_rejected(self):
        with pytest.raises(PNGError):
            decode_rgba(_SIG + _chunk(b"IDAT", zlib.compress(b"\0" * 5))
                        + _chunk(b"IEND", b""))
        with pytest.raises(PNGError):
            decode_rgba(self._png(b"\0\0\0\1", zlib.compress(b"\0" * 5)))

    def test_truncated_scanlines_rejected(self):
        # 2x2 RGBA wants 2 * (1 + 8) bytes; give it one row
        raw = b"\0" + bytes(8)
        with pytest.raises(PNGError, match="cut short"):
            decode_rgba(self._png(self._rgba_ihdr(2, 2), zlib.compress(raw)))

    def test_truncated_stream_rejected(self):
        # the right number of bytes to inflate, but the zlib stream
        # itself ends early
        raw = bytes(2 * 9)
        idat = zlib.compress(raw)[:-4]
        with pytest.raises(PNGError):
            decode_rgba(self._png(self._rgba_ihdr(2, 2), idat))

    def test_excess_decoded_bytes_rejected(self):
        raw = bytes(2 * 9) + b"\0"
        with pytest.raises(PNGError, match="more image data"):
            decode_rgba(self._png(self._rgba_ihdr(2, 2), zlib.compress(raw)))

    def test_exact_length_still_decodes(self):
        raw = b"\0" + bytes((1, 2, 3, 4, 5, 6, 7, 8)) + b"\0" + bytes(8)
        w, h, out = decode_rgba(self._png(self._rgba_ihdr(2, 2),
                                          zlib.compress(raw)))
        assert (w, h) == (2, 2)
        assert bytes(out[:8]) == bytes((1, 2, 3, 4, 5, 6, 7, 8))

    def test_bundled_images_still_decode(self):
        data = Path(__file__).parent.parent / "src/linecast/data"
        for name, size in (("moon_albedo.png", (512, 256)),
                           ("climate.png", (3600, 1800))):
            w, h, out = decode_rgba((data / name).read_bytes())
            assert (w, h) == size
            assert len(out) == w * h * 4
