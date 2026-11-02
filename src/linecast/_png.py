"""Minimal pure-Python PNG decoder (stdlib only).

Decodes the cases produced by the IEM NEXRAD WMS server and similar web map
sources: non-interlaced, colour types 0/2/3/4/6 at 8 bits, plus the packed
1/2/4-bit indexed and grayscale forms sparse tiles are served in.  Returns raw RGBA
bytes so callers can sample pixels directly.  Keeps linecast dependency-free:
``zlib`` inflates, and the rest is the standard library.
"""

import struct
import sys
import threading
import zlib
from array import array
from collections import OrderedDict
from itertools import accumulate
from operator import add

_SIG = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}  # channels by colour type at 8-bit

# Checked against IHDR before anything is inflated or allocated.  Map
# tiles are 256 or 512 square and the largest bundled image (the climate
# grid) is 3600x1800, 6.5 Mpx; 16 Mpx is 64 MiB of RGBA out, well clear
# of both and far short of what a lying header could ask for.
_MAX_SIDE = 16384
_MAX_PIXELS = 1 << 24


class PNGError(Exception):
    pass


# At most two decodes run at a time across the process.  A decode is
# pure Python, and the tile pool asks for a dozen at once: on one
# interpreter they finish no sooner than two at a time would, and a
# frame painted meanwhile waits its turn behind every one of them.
# Measured on the live terrain map, this is the difference between a
# first frame at 1.7 s and one at 0.2 s.
_decoding = threading.Semaphore(2)


class DecodeMemo:
    """A bounded memo of decoded tiles, for any decoder.

    Map tiles are immutable and a view touches the same ones its
    neighbour did — a pan of one column re-reads nearly every tile the
    last view already decoded, and decoding is the expensive half (a
    Paeth-filtered terrarium tile is ~15 ms to unfilter; a z8 vector
    tile is ~25 ms to parse).  Entries are keyed by the caller and
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

    def has(self, key, data):
        """Whether the decode of these bytes is in the memo under `key`."""
        with self._lock:
            hit = self._hits.get(key)
            return hit is not None and hit[0] == data

    def get(self, key, data, decode, keep=()):
        """The decode of `data`, from the memo when it is the same bytes.

        `keep` names entries this call may not evict: the ones a caller
        found decoded (`has`) for the view it is about to build.  A
        view that needs more tiles than the memo holds would otherwise
        push every one of them out before it came back for them, and
        decode the whole view again on every build.  With its hits
        kept, a miss that could only make room by evicting one of them
        is decoded and let go, and the next build finds the same hits
        waiting.
        """
        with self._lock:
            hit = self._hits.get(key)
            if hit is not None and hit[0] == data:
                self._hits.move_to_end(key)
                return hit[1]
        with _decoding:
            value = decode(data)
        with self._lock:
            old = self._hits.pop(key, None)
            if old is not None:
                self._size -= len(old[0])
            self._hits[key] = (data, value)
            self._size += len(data)
            for k in list(self._hits):   # oldest first
                if not self._over():
                    break
                if k != key and k not in keep:
                    self._drop(k)
            if self._over():
                self._drop(key)
        return value

    def _over(self):
        return len(self._hits) > self._cap or (
            self._budget is not None and self._size > self._budget)

    def _drop(self, key):
        raw, _value = self._hits.pop(key)
        self._size -= len(raw)

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


def _unfilter_up(row, prev):
    """Each byte plus the one above it, mod 256, as one wide addition.

    The two rows are spread to a byte per 16-bit slot and added as
    integers: no slot's sum reaches 511, so none carries into the
    next, and the low bytes are the answer.  All of it runs in C.
    """
    n = len(row)
    wide = bytearray(2 * n)
    wide[0::2] = row
    above = bytearray(2 * n)
    above[0::2] = prev
    total = int.from_bytes(wide, "little") + int.from_bytes(above, "little")
    return total.to_bytes(2 * n, "little")[0::2]


def _unfilter_sub(row, bpp):
    """Each byte plus the one a pixel to its left, mod 256: a running
    sum down each channel's stream, taken by accumulate and read back
    as the low byte of each total."""
    out = bytearray(row)
    for ch in range(bpp):
        sums = array("I", accumulate(row[ch::bpp], add))
        if sys.byteorder != "little":
            sums.byteswap()
        out[ch::bpp] = sums.tobytes()[0::sums.itemsize]
    return out


def _unfilter_avg(row, prev, bpp):
    """Each byte plus the floor of the mean of its left and upper
    neighbours.  The left one is the byte just reconstructed, so each
    channel's stream is walked in Python with it carried in a local."""
    out = bytearray(row)
    for ch in range(bpp):
        res = []
        app = res.append
        a = 0
        for v, b in zip(row[ch::bpp], prev[ch::bpp]):
            a = (v + ((a + b) >> 1)) & 0xFF
            app(a)
        out[ch::bpp] = res
    return out


def _unfilter_paeth(row, prev, bpp):
    """Each byte plus the Paeth predictor of its left, upper and
    upper-left neighbours.

    The left neighbour is the byte just reconstructed, which rules
    out a slice operation; what can be done is to walk each channel's
    stream with that byte, and the upper-left one, carried in locals
    rather than read back out of the rows, and to take the predictor's
    three distances as b - c, a - c and their sum, which is what the
    spec's |p - a|, |p - b| and |p - c| come to.  Terrarium tiles are
    nearly all Paeth rows, and this is most of their decode.
    """
    out = bytearray(row)
    for ch in range(bpp):
        res = []
        app = res.append
        a = c = 0
        for v, b in zip(row[ch::bpp], prev[ch::bpp]):
            pa = b - c
            pb = a - c
            pc = pa + pb
            if pa < 0:
                pa = -pa
            if pb < 0:
                pb = -pb
            if pc < 0:
                pc = -pc
            if pa <= pb and pa <= pc:
                a = (v + a) & 0xFF
            elif pb <= pc:
                a = (v + b) & 0xFF
            else:
                a = (v + c) & 0xFF
            app(a)
            c = b
        out[ch::bpp] = res
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
            if len(body) != 13:
                raise PNGError("bad IHDR")
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

    if width is None:
        raise PNGError("no IHDR")
    if not (0 < width <= _MAX_SIDE and 0 < height <= _MAX_SIDE
            and width * height <= _MAX_PIXELS):
        raise PNGError(f"unreasonable size {width}x{height}")
    if depth != 8 and not (depth in (1, 2, 4) and color_type in (0, 3)):
        raise PNGError(f"unsupported bit depth {depth}")
    if interlace:
        raise PNGError("interlaced PNG not supported")
    if color_type not in _CHANNELS:
        raise PNGError(f"unsupported colour type {color_type}")

    channels = _CHANNELS[color_type]
    stride = (width * channels * depth + 7) // 8
    # the declared size fixes the inflated length exactly — a filter
    # byte and a stride per row — so inflate no further than one byte
    # past it: a small IDAT can't expand beyond the image it claims
    expected = height * (1 + stride)
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(bytes(idat), expected + 1)
    except zlib.error as exc:
        raise PNGError(f"bad image data: {exc}") from exc
    if len(raw) > expected:
        raise PNGError("more image data than the header declares")
    if len(raw) < expected or not inflater.eof:
        raise PNGError("image data cut short")

    # unfilter scanlines — the hot loop of every map the terminal draws.
    # None, Up and Sub have no dependency on the byte just written and
    # run as whole-row operations in C; Average and Paeth do, and walk
    # each channel's stream in Python with that byte carried along.
    recon = bytearray(stride * height)
    bpp = max(1, channels * depth // 8)
    prev = bytes(stride)  # the row above the first is all zeros
    for y in range(height):
        fi = y * (stride + 1)
        ftype = raw[fi]
        row = raw[fi + 1:fi + 1 + stride]
        if ftype == 0:
            pass
        elif ftype == 2:
            row = _unfilter_up(row, prev)
        elif ftype == 1:
            row = _unfilter_sub(row, bpp)
        elif ftype == 3:
            row = _unfilter_avg(row, prev, bpp)
        elif ftype == 4:
            row = _unfilter_paeth(row, prev, bpp)
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
