"""Minimal pure-Python PNG decoder (stdlib only).

Decodes the cases produced by the IEM NEXRAD WMS server and similar web map
sources: non-interlaced, colour types 0/2/3/4/6 at 8 bits, plus the packed
1/2/4-bit indexed and grayscale forms sparse tiles are served in.  Returns raw RGBA
bytes so callers can sample pixels directly.  Keeps linecast dependency-free —
the only import is stdlib ``zlib``.
"""

import struct
import threading
import zlib
from collections import OrderedDict

_SIG = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}  # channels by colour type at 8-bit


class PNGError(Exception):
    pass


class DecodeMemo:
    """A bounded memo of decoded tiles, for any decoder.

    Map tiles are immutable and a view touches the same ones its
    neighbour did — a pan of one column re-reads nearly every tile the
    last view already decoded, and decoding is the expensive half (a
    Paeth-filtered terrarium tile is ~35 ms to unfilter; a z7 vector
    tile is ~30 ms to parse).  Entries are keyed by the caller and
    checked against the raw bytes they were decoded from, so a tile
    that changes on disk (a test fixture, a refreshed tileset) never
    serves a stale decode.  The newest `cap` entries stay, within a
    `budget` of raw bytes for formats whose decoded form is much larger
    than the source.
    """

    def __init__(self, cap=16, budget=None):
        self._cap = cap
        self._budget = budget
        self._hits = OrderedDict()   # key -> (raw bytes, decoded)
        self._size = 0
        self._lock = threading.Lock()

    def get(self, key, data, decode):
        """The decode of `data`, from the memo when it is the same bytes."""
        with self._lock:
            hit = self._hits.get(key)
            if hit is not None and hit[0] == data:
                self._hits.move_to_end(key)
                return hit[1]
        value = decode(data)
        with self._lock:
            old = self._hits.pop(key, None)
            if old is not None:
                self._size -= len(old[0])
            self._hits[key] = (data, value)
            self._size += len(data)
            while self._hits and (len(self._hits) > self._cap or (
                    self._budget is not None and self._size > self._budget)):
                _, (raw, _v) = self._hits.popitem(last=False)
                self._size -= len(raw)
        return value

    def clear(self):
        with self._lock:
            self._hits.clear()
            self._size = 0


def _unpack_bits(recon, width, height, stride, depth, color_type):
    """Spread packed sub-byte samples to one byte each, MSB first.

    Indexed samples stay palette indices; grayscale samples are scaled to
    the full 0–255 range as the PNG spec describes.
    """
    out = bytearray(width * height)
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    scale = 255 // mask if color_type == 0 else 1
    for y in range(height):
        ro, oo = y * stride, y * width
        for x in range(width):
            byte = recon[ro + x // per_byte]
            shift = 8 - depth * (x % per_byte + 1)
            out[oo + x] = ((byte >> shift) & mask) * scale
    return out


def decode_rgba(data):
    """Decode PNG *bytes* → (width, height, bytearray of RGBA, 4 bytes/pixel)."""
    if data[:8] != _SIG:
        raise PNGError("not a PNG")

    pos = 8
    width = height = depth = color_type = interlace = None
    idat = bytearray()
    palette = None
    trns = None

    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length  # length + type + data + CRC

        if ctype == b"IHDR":
            (width, height, depth, color_type, _c, _f, interlace) = struct.unpack(
                ">IIBBBBB", body)
        elif ctype == b"PLTE":
            palette = body
        elif ctype == b"tRNS":
            trns = body
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break

    if depth != 8 and not (depth in (1, 2, 4) and color_type in (0, 3)):
        raise PNGError(f"unsupported bit depth {depth}")
    if interlace:
        raise PNGError("interlaced PNG not supported")
    if color_type not in _CHANNELS:
        raise PNGError(f"unsupported colour type {color_type}")

    channels = _CHANNELS[color_type]
    stride = (width * channels * depth + 7) // 8
    raw = zlib.decompress(bytes(idat))

    # unfilter scanlines — the hot loop of every map the terminal draws,
    # so the two filters with no left-neighbour dependency (None, Up)
    # take slice/zip paths and only Sub/Average/Paeth walk byte by byte
    recon = bytearray(stride * height)
    bpp = max(1, channels * depth // 8)
    prev = bytes(stride)  # the row above the first is all zeros
    for y in range(height):
        fi = y * (stride + 1)
        ftype = raw[fi]
        row = bytearray(raw[fi + 1:fi + 1 + stride])
        if ftype == 0:
            pass
        elif ftype == 2:
            row = bytearray((v + p) & 0xFF for v, p in zip(row, prev))
        elif ftype == 1:
            for x in range(bpp, stride):
                row[x] = (row[x] + row[x - bpp]) & 0xFF
        elif ftype == 3:
            for x in range(stride):
                a = row[x - bpp] if x >= bpp else 0
                row[x] = (row[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif ftype == 4:
            for x in range(stride):
                if x >= bpp:
                    a, c = row[x - bpp], prev[x - bpp]
                else:
                    a = c = 0
                b = prev[x]
                p = a + b - c
                pa = p - a if p >= a else a - p
                pb = p - b if p >= b else b - p
                pc = p - c if p >= c else c - p
                if pa <= pb and pa <= pc:
                    val = a
                elif pb <= pc:
                    val = b
                else:
                    val = c
                row[x] = (row[x] + val) & 0xFF
        else:
            raise PNGError(f"bad filter type {ftype}")
        ro = y * stride
        recon[ro:ro + stride] = row
        prev = row

    if depth < 8:
        recon = _unpack_bits(recon, width, height, stride, depth, color_type)

    # expand to RGBA — strided slice assignment and bytes.translate keep
    # this at C speed; at 8-bit depth the rows are contiguous (stride is
    # exactly width * channels), which is what makes the striding valid
    if color_type == 6:
        return width, height, recon
    n = width * height
    out = bytearray(n * 4)
    if color_type == 2:
        out[0::4] = recon[0::3]
        out[1::4] = recon[1::3]
        out[2::4] = recon[2::3]
        out[3::4] = b"\xff" * n
    elif color_type == 0:
        g = recon[:n]
        out[0::4] = g
        out[1::4] = g
        out[2::4] = g
        out[3::4] = b"\xff" * n
    elif color_type == 4:
        g = recon[0::2]
        out[0::4] = g
        out[1::4] = g
        out[2::4] = g
        out[3::4] = recon[1::2]
    elif color_type == 3:
        idx = bytes(recon[:n])
        plen = len(palette) // 3
        for chan in range(3):
            table = bytes(palette[i * 3 + chan] if i < plen else 0
                          for i in range(256))
            out[chan::4] = idx.translate(table)
        if trns:
            alpha = bytes(trns[i] if i < len(trns) else 255
                          for i in range(256))
            out[3::4] = idx.translate(alpha)
        else:
            out[3::4] = b"\xff" * n

    return width, height, out
