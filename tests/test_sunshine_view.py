"""The sunshine day view's vertical scale."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast.sunshine.view import _solstice_range  # noqa: E402


def test_the_scale_is_the_same_year_round_in_either_hemisphere():
    # Melbourne's summer is December's: its range mirrors a northern
    # place at the same latitude, rather than topping out at a winter noon
    south = _solstice_range(-37.81, 144.96, 10)
    north = _solstice_range(37.81, 144.96, 10)
    assert abs(south[0] - north[0]) < 1.0 and abs(south[1] - north[1]) < 1.0
    assert south[0] > 70
