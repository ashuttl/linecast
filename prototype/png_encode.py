"""Minimal pure-Python PNG encoder (stdlib only) — for previews.

Writes 8-bit RGB, non-interlaced, filter type 0. Just enough to save a
Framebuffer render to an image so the composited result can be eyeballed.
"""

import struct
import zlib


def _chunk(tag, body):
    return (
        struct.pack(">I", len(body))
        + tag
        + body
        + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    )


def encode_rgb(width, height, get_px):
    """Encode via get_px(x, y) -> (r, g, b). Returns PNG bytes."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: None
        for x in range(width):
            r, g, b = get_px(x, y)
            raw += bytes((int(r) & 0xFF, int(g) & 0xFF, int(b) & 0xFF))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # colour type 2 = RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )
