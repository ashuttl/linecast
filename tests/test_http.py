"""Tests for the bounded response readers in _http.

No network: read_limited takes anything with a .read(n) method and an
optional .length, so a fake response object is enough.
"""

import gzip
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._http import gunzip_limited, read_limited


class FakeResponse(io.BytesIO):
    def __init__(self, body, length=None):
        super().__init__(body)
        self.length = length


def test_small_body_passes_through():
    assert read_limited(FakeResponse(b"hello"), 100) == b"hello"


def test_empty_body():
    assert read_limited(FakeResponse(b""), 100) == b""


def test_body_at_the_limit_is_allowed():
    assert read_limited(FakeResponse(b"x" * 100), 100) == b"x" * 100


def test_oversized_stream_is_cut_off():
    with pytest.raises(ValueError):
        read_limited(FakeResponse(b"x" * 101), 100)


def test_oversized_stream_never_accumulates_past_one_chunk():
    """A huge chunked body is refused after the first chunk past the cap,
    not slurped whole: reading stops as soon as the total crosses it."""

    class Endless:
        length = None  # chunked: no Content-Length

        def __init__(self):
            self.served = 0

        def read(self, n):
            self.served += n
            return b"x" * n

    resp = Endless()
    with pytest.raises(ValueError):
        read_limited(resp, 200_000)
    assert resp.served <= 200_000 + 65536


def test_honest_content_length_is_refused_before_reading():
    class Loud(FakeResponse):
        def read(self, n=-1):
            raise AssertionError("body was read despite oversized Content-Length")

    with pytest.raises(ValueError):
        read_limited(Loud(b"x" * 10, length=10_000), 100)


def test_lying_content_length_still_capped():
    with pytest.raises(ValueError):
        read_limited(FakeResponse(b"x" * 500, length=10), 100)


def test_gunzip_small_body():
    assert gunzip_limited(gzip.compress(b"streets"), 100) == b"streets"


def test_gunzip_bomb_is_refused():
    bomb = gzip.compress(b"\0" * 10_000_000)
    with pytest.raises(ValueError):
        gunzip_limited(bomb, 1_000_000)
