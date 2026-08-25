"""Mapbox Vector Tile (MVT v2.1) decoder in pure stdlib.

Decodes the protobuf wire format by hand — the schema is small enough
that a generic reader for four wire types covers all of it, matching the
project's no-dependency ethos (cf. the PNG decoder in _png.py).

The decoder is deliberately tolerant of real-world tiles: unknown fields
(vendor extensions) are skipped by wire type, tag indices that fall
outside a layer's key/value tables drop that tag rather than raising,
strings decode with errors="replace", and layers with an unsupported
version are ignored.  Truncated or structurally invalid input raises
ValueError — callers treat a bad tile as missing and move on.

decode_tile() accepts raw, gzip-, or zlib-wrapped bytes (servers are
inconsistent about Content-Encoding, so the framing is sniffed from
magic bytes) and returns {layer_name: {"version", "extent", "features"}}
where each feature is {"id", "type", "tags", "geometry"}:

- type: 1 point, 2 linestring, 3 polygon (vector_tile.GeomType)
- geometry: list of parts, each a list of (x, y) ints in tile-local
  coordinates — origin top-left, y down, 0..extent spanning the tile
  (values outside that range are the encoder's buffer; clip, don't drop)
- polygon rings arrive open (first vertex not repeated); group them
  into exterior/hole sets with assemble_polygons()
"""

import gzip
import struct
import zlib
from typing import Any

# vector_tile.GeomType
POINT, LINESTRING, POLYGON = 1, 2, 3


def _varint(buf, i):
    """Little-endian base-128 varint at buf[i] -> (value, next index)."""
    result = shift = 0
    while True:
        try:
            b = buf[i]
        except IndexError:
            raise ValueError("truncated varint") from None
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _fields(buf):
    """Yield (field_number, wire_type, value) for each field in a message.

    value is an int for wire type 0 and bytes for types 1 (8 bytes),
    2 (length-delimited), and 5 (4 bytes).  Unknown field numbers are
    the caller's to ignore — skipping happens for free because every
    wire type's extent is decoded here.
    """
    i, end = 0, len(buf)
    while i < end:
        key, i = _varint(buf, i)
        fn, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(buf, i)
        elif wt == 1:
            v = buf[i:i + 8]
            i += 8
        elif wt == 2:
            ln, i = _varint(buf, i)
            v = buf[i:i + ln]
            i += ln
        elif wt == 5:
            v = buf[i:i + 4]
            i += 4
        else:
            raise ValueError(f"unsupported wire type {wt}")
        if i > end:
            raise ValueError("truncated message")
        yield fn, wt, v


def _uint32s(v, wt):
    """Repeated uint32: packed blob (wt 2) or one unpacked varint (wt 0).

    Conformant decoders must accept both encodings and concatenate
    repeated occurrences; callers += the result per occurrence.
    """
    if wt == 0:
        return [v]
    out, i = [], 0
    while i < len(v):
        n, i = _varint(v, i)
        out.append(n)
    return out


def _unzigzag(n):
    return (n >> 1) ^ -(n & 1)


def _value(buf):
    """Tile.Value message -> str | float | int | bool | None.

    Exactly one field is set per spec; the first recognized one wins.
    int_value (4) is plain two's-complement, sint_value (6) is zigzag —
    only geometry parameters and sint use zigzag, nothing else.
    """
    for fn, _wt, v in _fields(buf):
        if fn == 1:
            return v.decode("utf-8", errors="replace")
        if fn == 2:
            return struct.unpack("<f", v)[0]
        if fn == 3:
            return struct.unpack("<d", v)[0]
        if fn == 4:
            return v - (1 << 64) if v >= (1 << 63) else v
        if fn == 5:
            return v
        if fn == 6:
            return _unzigzag(v)
        if fn == 7:
            return bool(v)
    return None


def _geometry(cmds):
    """Command stream -> list of parts, each a list of (x, y) ints.

    The cursor starts at (0, 0) per feature and every parameter is a
    delta from it; deltas accumulate across ALL commands including
    MoveTo — resetting per ring corrupts every multi-part geometry.
    ClosePath takes no parameters and does not move the cursor (the
    closing edge back to the ring's first vertex is implied).
    """
    parts, part, x, y = [], [], 0, 0
    i, n = 0, len(cmds)
    while i < n:
        cid, count = cmds[i] & 0x7, cmds[i] >> 3
        i += 1
        if cid == 1:  # MoveTo; count > 1 means MultiPoint
            for _ in range(count):
                x += _unzigzag(cmds[i])
                y += _unzigzag(cmds[i + 1])
                i += 2
                if part:
                    parts.append(part)
                part = [(x, y)]
        elif cid == 2:  # LineTo
            for _ in range(count):
                x += _unzigzag(cmds[i])
                y += _unzigzag(cmds[i + 1])
                i += 2
                part.append((x, y))
        elif cid == 7:  # ClosePath
            if part:
                parts.append(part)
            part = []
        else:
            raise ValueError(f"bad geometry command {cid}")
        if i > n:
            raise ValueError("truncated geometry")
    if part:
        parts.append(part)
    return parts


def _feature(buf, keys, values):
    fid, ftype, tag_ids, geom = None, 0, [], []
    for fn, wt, v in _fields(buf):
        if fn == 1:
            fid = v
        elif fn == 2:
            tag_ids += _uint32s(v, wt)
        elif fn == 3:
            ftype = v
        elif fn == 4:
            geom += _uint32s(v, wt)
    # tag pairs index the layer's key/value tables; an out-of-range
    # index means a corrupt tile — drop the pair, keep the feature
    tags = {}
    for j in range(0, len(tag_ids) - 1, 2):
        k, v = tag_ids[j], tag_ids[j + 1]
        if k < len(keys) and v < len(values):
            tags[keys[k]] = values[v]
    return {"id": fid, "type": ftype, "tags": tags,
            "geometry": _geometry(geom)}


def decode_tile(data: bytes) -> dict[str, dict[str, Any]]:
    """MVT bytes (raw, gzip-, or zlib-wrapped) -> {layer_name: layer}.

    Empty input (a 0-byte "empty tile" response) decodes to {}.
    """
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    elif data[:1] == b"\x78":
        data = zlib.decompress(data)
    layers = {}
    for fn, _wt, v in _fields(data):
        if fn != 3:  # Tile.layers
            continue
        name, version, extent = None, 1, 4096
        keys, values, raw_feats = [], [], []
        # features may appear before keys/values on the wire, so
        # collect bytes first and decode features after the walk
        for lfn, lwt, lv in _fields(v):
            if lfn == 1:
                name = lv.decode("utf-8", errors="replace")
            elif lfn == 2:
                raw_feats.append(lv)
            elif lfn == 3:
                keys.append(lv.decode("utf-8", errors="replace"))
            elif lfn == 4:
                values.append(_value(lv))
            elif lfn == 5:
                extent = lv
            elif lfn == 15:
                version = lv
        if name is None or version not in (1, 2) or extent <= 0:
            continue
        layers[name] = {
            "version": version,
            "extent": extent,
            "features": [_feature(fb, keys, values) for fb in raw_feats],
        }
    return layers


def ring_sign(ring: list[tuple[int, int]]) -> int:
    """2x signed shoelace area in tile coords (y down), closing edge
    included.  > 0 exterior, < 0 hole (v2 winding), 0 degenerate."""
    s = 0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        s += x1 * y2 - x2 * y1
    return s


def assemble_polygons(rings: list[list[tuple[int, int]]]
                      ) -> list[list[list[tuple[int, int]]]]:
    """A polygon feature's ring list -> [[exterior, hole, ...], ...].

    Uses MVT v2 winding: positive-area rings open a polygon, negative
    ones are holes in the most recent exterior.  Degenerate rings and
    holes with no preceding exterior are dropped.  (v1 tiles carry no
    winding guarantee — fill all rings even-odd instead.)
    """
    polys = []
    for ring in rings:
        s = ring_sign(ring)
        if s > 0:
            polys.append([ring])
        elif s < 0 and polys:
            polys[-1].append(ring)
    return polys
