"""Minimal pure-Python PNG decoder (stdlib only).

Decodes the cases produced by the IEM NEXRAD WMS server and similar web map
sources: non-interlaced, colour types 0/2/3/4/6 at 8 bits, plus the packed
1/2/4-bit indexed and grayscale forms sparse tiles are served in.  Returns raw RGBA
bytes so callers can sample pixels directly.  Keeps linecast dependency-free —
the only import is stdlib ``zlib``.
"""

import struct
import zlib

_SIG = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}  # channels by colour type at 8-bit


class PNGError(Exception):
    pass


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


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

    # unfilter scanlines
    recon = bytearray(stride * height)
    bpp = max(1, channels * depth // 8)
    for y in range(height):
        fi = y * (stride + 1)
        ftype = raw[fi]
        line = raw[fi + 1:fi + 1 + stride]
        ro = y * stride
        for x in range(stride):
            val = line[x]
            a = recon[ro + x - bpp] if x >= bpp else 0
            b = recon[ro - stride + x] if y > 0 else 0
            c = recon[ro - stride + x - bpp] if (y > 0 and x >= bpp) else 0
            if ftype == 1:
                val = (val + a) & 0xFF
            elif ftype == 2:
                val = (val + b) & 0xFF
            elif ftype == 3:
                val = (val + ((a + b) >> 1)) & 0xFF
            elif ftype == 4:
                val = (val + _paeth(a, b, c)) & 0xFF
            elif ftype != 0:
                raise PNGError(f"bad filter type {ftype}")
            recon[ro + x] = val

    if depth < 8:
        recon = _unpack_bits(recon, width, height, stride, depth, color_type)

    # expand to RGBA
    out = bytearray(width * height * 4)
    for i in range(width * height):
        si, di = i * channels, i * 4
        if color_type == 6:
            out[di:di + 4] = recon[si:si + 4]
        elif color_type == 2:
            out[di:di + 3] = recon[si:si + 3]
            out[di + 3] = 255
        elif color_type == 0:
            g = recon[si]
            out[di] = out[di + 1] = out[di + 2] = g
            out[di + 3] = 255
        elif color_type == 4:
            g = recon[si]
            out[di] = out[di + 1] = out[di + 2] = g
            out[di + 3] = recon[si + 1]
        elif color_type == 3:
            idx = recon[si]
            out[di] = palette[idx * 3]
            out[di + 1] = palette[idx * 3 + 1]
            out[di + 2] = palette[idx * 3 + 2]
            out[di + 3] = trns[idx] if (trns and idx < len(trns)) else 255

    return width, height, out
