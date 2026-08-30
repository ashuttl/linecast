"""Decoding RainViewer's Universal Blue tiles back to reflectivity.

RainViewer's free tier serves every request in one colour scheme —
Universal Blue — whatever colour id the URL asks for, so its tiles can't
be fetched as the raw grayscale our palettes want.  But the scheme is
published (rainviewer.com/api/color-schemes.html) as a table keyed by the
same gray byte LibreWXR's scheme 0 uses (gray = dBZ + 32, +128 for snow),
and unsmoothed tiles carry those exact colours, one per dBZ step.  So the
mapping inverts: look each pixel up and an Universal Blue tile becomes a
scheme-0 tile, and everything downstream — the bilinear gray resample,
the palettes — never knows the difference.

_TABLE is that published column, 256 RGBA entries indexed by gray byte,
vendored so decoding needs no fetch.  A few runs of grays share a colour
(the ramp saturates above 65 dBZ); the lowest gray stands for the run,
which no palette can tell apart.
"""

# rainviewer.com/api/color-schemes.html, the Universal Blue column,
# RGBA hex per gray byte 0..255
_TABLE = bytes.fromhex(
    "000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000006361591466635a1969665c"
    "1e6c685d246f6b5f29726e612e75706234787364397c75653e7f786744827b6949"
    "857d6a4e88806c548b826d598e856f5e928871649e93756eaa9e7978b6a97e82c2"
    "b4828ccec08796d2c48ba0d6c88faadacc93b4ded097be88ddeeff6cd1ebff51c5"
    "e8ff36bae5ff1baee2ff00a3e0ff009ad5ff0091caff0088bfff007fb4ff0077aa"
    "ff0070a3ff00699cff006295ff005b8eff005588ff005180ff004e78ff004a70ff"
    "004768ffffee00ffffe000ffffd200ffffc500ffffb700ffffaa00ffff9f00ffff"
    "9500ffff8b00ffff8100ffff4400fff23600ffe62800ffd91b00ffcd0d00ffc100"
    "00ffa80000ff8f0000ff760000ff5d0000ffffaaffffff9fffffff95ffffff8bff"
    "ffff81ffffff77ffffff6cffffff62ffffff58ffffff4effffffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff00"
    "ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff"
    "00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00"
    "ff00ff00ff00ff00ff00ff00ff00ff00ff00000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000cfffff00ceffff0ccdffff19ccffff26cbffff33cbffff3fcaffff"
    "4cc9ffff59c8ffff66c7ffff72c7ffff7fc6ffff8cc5ffff99c4ffffa5c3ffffb2"
    "c3ffffbfc2ffffccc1ffffd8c0ffffe5bffffff2bfffffffb8f8ffffb2f2ffffab"
    "ebffffa5e5ffff9fdfffff98d8ffff92d2ffff8bcbffff85c5ffff7fbfffff78b8"
    "ffff72b2ffff6babffff65a5ffff5f9fffff5b9bffff5898ffff5595ffff5292ff"
    "ff4f8fffff4b8bffff4888ffff4585ffff4282ffff3f7fffff3b7bffff3878ffff"
    "3575ffff3272ffff2f6fffff2b6bffff2868ffff2565ffff2262ffff1f5fffff1b"
    "5bffff1858ffff1555ffff1252ffff0f4fffff0c4bffff0948ffff0645ffff0242"
    "ffff003fffff003bffff0038ffff0035ffff0032ffff002fffff002bffff0028ff"
    "ff0025ffff0022ffff001fffff001bffff0018ffff0015ffff0012ffff000fffff"
    "000cffff0009ffff0006ffff0002ffff0000ffff0000ffff0000ffff0000ffff00"
    "00ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000"
    "ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000ffff0000ff"
    "ff")
assert len(_TABLE) == 256 * 4

# colour → gray; ascending, so the lowest gray stands for a shared colour
_INVERSE: dict[tuple[int, int, int, int], int] = {}
for _g in range(256):
    _c = tuple(_TABLE[_g * 4:_g * 4 + 4])
    if _c[3]:
        _INVERSE.setdefault(_c, _g)
del _g, _c


def _nearest(colour):
    """The table colour closest to one not in it (the scheme drifted)."""
    r, g, b, a = colour
    return min(_INVERSE.items(),
               key=lambda kv: ((kv[0][0] - r) ** 2 + (kv[0][1] - g) ** 2
                               + (kv[0][2] - b) ** 2 + (kv[0][3] - a) ** 2))[1]


def to_gray(rgba: bytearray) -> bytearray:
    """Rewrite a Universal Blue RGBA tile as scheme-0 grayscale, in place.

    Covered pixels come out opaque, like a raw grayscale tile's, so the
    bilinear resample weighs them the same either way.  A colour off the
    table — the server nudged the scheme — snaps to the nearest entry
    rather than dropping the echo.
    """
    cache: dict[tuple[int, int, int, int], int] = {}
    for i in range(0, len(rgba), 4):
        if rgba[i + 3] == 0:
            continue
        key = (rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3])
        gray = cache.get(key)
        if gray is None:
            gray = _INVERSE.get(key)
            if gray is None:
                gray = _nearest(key)
            cache[key] = gray
        rgba[i] = rgba[i + 1] = rgba[i + 2] = gray
        rgba[i + 3] = 255
    return rgba
