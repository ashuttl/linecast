"""Tests for the pure-stdlib Mapbox Vector Tile decoder.

No network and no binary fixtures: every tile is hand-encoded in-test
with an independent minimal protobuf writer, so a decoder bug can't be
masked by an encoder sharing its assumptions.
"""

import gzip
import struct
import sys
import zlib
from pathlib import Path

# Ensure the worktree src is preferred over any installed version.
# (No sys.modules purge here: this file is collected after other test
# modules that hold references into already-imported linecast modules.)
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast._mvt import (assemble_polygons, decode_tile, ring_sign,
                           _unzigzag)


# ---------------------------------------------------------------------------
# Minimal protobuf writer (independent of the decoder)
# ---------------------------------------------------------------------------
def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def field(num, wt, payload):
    """payload: int for wt 0, bytes for wt 1/2/5."""
    key = varint((num << 3) | wt)
    if wt == 0:
        return key + varint(payload)
    if wt == 2:
        return key + varint(len(payload)) + payload
    return key + payload  # wt 1 and 5: fixed-size bytes


def zigzag(n):
    return (n << 1) ^ (n >> 63) if n < 0 else n << 1


def packed(nums):
    return b"".join(varint(n) for n in nums)


def cmd(cid, count):
    return (count << 3) | cid


def geom_ints(commands):
    """[('move'|'line', [(dx, dy), ...])] or [('close',)] -> uint32 list."""
    out = []
    for c in commands:
        if c[0] == "close":
            out.append(cmd(7, 1))
        else:
            cid = 1 if c[0] == "move" else 2
            deltas = c[1]
            out.append(cmd(cid, len(deltas)))
            for dx, dy in deltas:
                out.append(zigzag(dx))
                out.append(zigzag(dy))
    return out


def value_str(s):
    return field(1, 2, s.encode())


def make_feature(fid=None, ftype=1, tags=(), geometry=(), pack=True,
                 extra=b""):
    out = b""
    if fid is not None:
        out += field(1, 0, fid)
    if tags:
        if pack:
            out += field(2, 2, packed(tags))
        else:
            for t in tags:
                out += field(2, 0, t)
    out += field(3, 0, ftype)
    if geometry:
        if pack:
            out += field(4, 2, packed(geometry))
        else:
            for g in geometry:
                out += field(4, 0, g)
    return out + extra


def make_layer(name="test", features=(), keys=(), values=(), extent=4096,
               version=2, extra=b"", features_first=False):
    parts = []
    feat_bytes = b"".join(field(2, 2, f) for f in features)
    if features_first:
        # keys/values legally follow features on the wire; the decoder
        # must not resolve tags until the whole layer is walked
        parts.append(feat_bytes)
    parts.append(field(15, 0, version))
    parts.append(field(1, 2, name.encode()))
    if not features_first:
        parts.append(feat_bytes)
    for k in keys:
        parts.append(field(3, 2, k.encode()))
    for v in values:
        parts.append(field(4, 2, v))
    parts.append(field(5, 0, extent))
    parts.append(extra)
    return b"".join(parts)


def make_tile(*layers, extra=b""):
    return extra + b"".join(field(3, 2, lyr) for lyr in layers)


# a simple 3-vertex line: move to (2,3), line to (4,4) then (2,2)
LINE_GEOM = geom_ints([("move", [(2, 3)]), ("line", [(2, 1), (-2, -2)])])
LINE_PARTS = [[(2, 3), (4, 4), (2, 2)]]


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------
class TestWireFormat:
    def test_empty_input_is_empty_tile(self):
        # OpenFreeMap returns HTTP 200 with 0 bytes for empty tiles
        assert decode_tile(b"") == {}

    def test_line_feature_round_trip(self):
        tile = make_tile(make_layer(features=[
            make_feature(fid=7, ftype=2, geometry=LINE_GEOM)]))
        out = decode_tile(tile)
        assert set(out) == {"test"}
        lyr = out["test"]
        assert lyr["version"] == 2 and lyr["extent"] == 4096
        (feat,) = lyr["features"]
        assert feat["id"] == 7 and feat["type"] == 2
        assert feat["geometry"] == LINE_PARTS

    def test_unknown_fields_skipped_at_every_level(self):
        # vendor extensions: varint, fixed64, len-delim, fixed32
        junk = (field(99, 0, 12345) + field(98, 1, b"\x01" * 8)
                + field(97, 2, b"junk") + field(96, 5, b"\x02" * 4))
        tile = make_tile(
            make_layer(features=[make_feature(ftype=2, geometry=LINE_GEOM,
                                              extra=junk)],
                       extra=junk),
            extra=junk)
        (feat,) = decode_tile(tile)["test"]["features"]
        assert feat["geometry"] == LINE_PARTS

    def test_unpacked_geometry_and_tags_accepted(self):
        tile = make_tile(make_layer(
            features=[make_feature(ftype=2, tags=[0, 0],
                                   geometry=LINE_GEOM, pack=False)],
            keys=["name"], values=[value_str("Main St")]))
        (feat,) = decode_tile(tile)["test"]["features"]
        assert feat["geometry"] == LINE_PARTS
        assert feat["tags"] == {"name": "Main St"}

    def test_gzip_and_zlib_framing_sniffed(self):
        tile = make_tile(make_layer(features=[
            make_feature(ftype=2, geometry=LINE_GEOM)]))
        for wrapped in (gzip.compress(tile), zlib.compress(tile)):
            out = decode_tile(wrapped)
            assert out["test"]["features"][0]["geometry"] == LINE_PARTS

    def test_truncated_input_raises(self):
        tile = make_tile(make_layer(features=[
            make_feature(ftype=2, geometry=LINE_GEOM)]))
        try:
            decode_tile(tile[:-4])
        except ValueError:
            pass
        else:
            raise AssertionError("truncated tile did not raise")

    def test_unzigzag(self):
        # zigzag maps 0,-1,1,-2,2... to 0,1,2,3,4...
        assert [_unzigzag(n) for n in range(5)] == [0, -1, 1, -2, 2]


# ---------------------------------------------------------------------------
# Layer / value semantics
# ---------------------------------------------------------------------------
class TestLayerSemantics:
    def test_unsupported_layer_version_skipped(self):
        good = make_layer(name="ok", features=[
            make_feature(ftype=2, geometry=LINE_GEOM)])
        bad = make_layer(name="future", version=3, features=[
            make_feature(ftype=2, geometry=LINE_GEOM)])
        assert set(decode_tile(make_tile(bad, good))) == {"ok"}

    def test_custom_extent_respected(self):
        tile = make_tile(make_layer(extent=512))
        assert decode_tile(tile)["test"]["extent"] == 512

    def test_all_seven_value_types(self):
        values = [
            value_str("s"),
            field(2, 5, struct.pack("<f", 1.5)),
            field(3, 1, struct.pack("<d", 2.5)),
            field(4, 0, (1 << 64) - 3),      # int64 -3, two's complement
            field(5, 0, 7),                   # uint64
            field(6, 0, zigzag(-9)),          # sint64
            field(7, 0, 1),                   # bool
        ]
        tags = []
        for i in range(7):
            tags += [i, i]
        tile = make_tile(make_layer(
            features=[make_feature(ftype=1,
                                   geometry=geom_ints([("move", [(1, 1)])]),
                                   tags=tags)],
            keys=[f"k{i}" for i in range(7)], values=values))
        (feat,) = decode_tile(tile)["test"]["features"]
        assert feat["tags"] == {"k0": "s", "k1": 1.5, "k2": 2.5, "k3": -3,
                                "k4": 7, "k5": -9, "k6": True}

    def test_out_of_range_tag_index_dropped_not_raised(self):
        tile = make_tile(make_layer(
            features=[make_feature(ftype=1,
                                   geometry=geom_ints([("move", [(1, 1)])]),
                                   tags=[0, 0, 5, 9])],  # 5/9 out of range
            keys=["name"], values=[value_str("x")]))
        (feat,) = decode_tile(tile)["test"]["features"]
        assert feat["tags"] == {"name": "x"}

    def test_features_before_keys_on_the_wire(self):
        tile = make_tile(make_layer(
            features=[make_feature(ftype=1,
                                   geometry=geom_ints([("move", [(1, 1)])]),
                                   tags=[0, 0])],
            keys=["name"], values=[value_str("late")], features_first=True))
        (feat,) = decode_tile(tile)["test"]["features"]
        assert feat["tags"] == {"name": "late"}


# ---------------------------------------------------------------------------
# Geometry semantics
# ---------------------------------------------------------------------------
class TestGeometry:
    def test_multipoint_single_moveto(self):
        # MoveTo count=2: (5,5) then delta (3,0) -> (8,5)
        tile = make_tile(make_layer(features=[make_feature(
            ftype=1, geometry=geom_ints([("move", [(5, 5), (3, 0)])]))]))
        (feat,) = decode_tile(tile)["test"]["features"]
        assert feat["geometry"] == [[(5, 5)], [(8, 5)]]

    def test_multilinestring_cursor_persists(self):
        # second line's MoveTo is a delta from the first line's end
        geom = geom_ints([("move", [(0, 0)]), ("line", [(10, 0)]),
                          ("move", [(0, 5)]), ("line", [(-10, 0)])])
        tile = make_tile(make_layer(features=[
            make_feature(ftype=2, geometry=geom)]))
        (feat,) = decode_tile(tile)["test"]["features"]
        # cursor after line 1 is (10,0); move (0,5) -> (10,5)
        assert feat["geometry"] == [[(0, 0), (10, 0)], [(10, 5), (0, 5)]]

    def test_polygon_ring_open_and_cursor_through_closepath(self):
        # square (0,0)-(4,0)-(4,4)-(0,4); ClosePath implies the last edge
        # and does not move the cursor, so the hole's MoveTo is a delta
        # from (0,4)
        geom = geom_ints([
            ("move", [(0, 0)]), ("line", [(4, 0), (0, 4), (-4, 0)]),
            ("close",),
            ("move", [(1, -3)]), ("line", [(0, 2), (2, 0), (0, -2)]),
            ("close",),
        ])
        tile = make_tile(make_layer(features=[
            make_feature(ftype=3, geometry=geom)]))
        (feat,) = decode_tile(tile)["test"]["features"]
        outer, hole = feat["geometry"]
        assert outer == [(0, 0), (4, 0), (4, 4), (0, 4)]  # open ring
        assert hole == [(1, 1), (1, 3), (3, 3), (3, 1)]

    def test_winding_and_hole_assembly(self):
        # y grows down, so the outer ring above is CW on screen ->
        # positive shoelace sum -> exterior; the hole runs CCW -> negative
        outer = [(0, 0), (4, 0), (4, 4), (0, 4)]
        hole = [(1, 1), (1, 3), (3, 3), (3, 1)]
        assert ring_sign(outer) > 0
        assert ring_sign(hole) < 0
        polys = assemble_polygons([outer, hole])
        assert polys == [[outer, hole]]

    def test_degenerate_and_orphan_rings_dropped(self):
        line = [(0, 0), (5, 5)]  # zero area
        hole = [(1, 1), (1, 3), (3, 3), (3, 1)]  # negative, no exterior yet
        outer = [(0, 0), (4, 0), (4, 4), (0, 4)]
        assert assemble_polygons([line, hole, outer]) == [[outer]]

    def test_multipolygon_sequence(self):
        a = [(0, 0), (2, 0), (2, 2), (0, 2)]
        b = [(5, 5), (7, 5), (7, 7), (5, 7)]
        hole_b = [(5, 5), (5, 6), (6, 6), (6, 5)]
        assert assemble_polygons([a, b, hole_b]) == [[a], [b, hole_b]]
