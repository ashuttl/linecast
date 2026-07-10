"""Tests for temperature-extrema label placement on the hourly chart."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._braille import interpolate
from linecast._weather_hourly import _find_temperature_extrema

# A ~48h temperature curve shaped like a real two-day forecast:
#   Sun: rise to a broad ~85 peak, decline overnight to the 59 global min
#   Mon: rise to the 89 global max, decline with a small late-evening wobble
#   Tue: settle into a broad ~70 valley, then rise toward the chart edge
_SUN = [76, 79, 82, 84, 85, 85, 84, 82, 80, 77, 74,
        71, 68, 66, 64, 62, 61, 60, 59, 59, 60, 62]
_MON = [65, 70, 76, 82, 86, 88, 89, 89, 88, 86, 84,
        81, 78, 76, 77, 78, 77, 75, 73]
_TUE = [72, 71, 70, 70, 70, 71, 73, 76, 79]
_TWO_DAY = _SUN + _MON + _TUE
_GRAPH_W = 185


def _labels(temps, graph_w=_GRAPH_W):
    """Return (rounded_temp, is_peak) tuples for the placed extrema."""
    col_temps = interpolate(temps, graph_w)
    return {(round(t), p) for _, t, p in _find_temperature_extrema(col_temps, graph_w)}


class TestFindTemperatureExtrema:
    def test_global_max_and_min_always_labelled(self):
        labels = _labels(_TWO_DAY)
        assert (89, True) in labels   # Monday global max
        assert (59, False) in labels  # Monday-morning global min

    def test_secondary_peak_labelled(self):
        # Sunday's broad ~85 peak should get a label, not be crowded out by a
        # spurious curvature bend on its shoulder.
        assert (85, True) in _labels(_TWO_DAY)

    def test_broad_valley_near_edge_labelled(self):
        # Tuesday's broad, flat ~70 valley is wider than any fixed window and
        # sits near the chart edge; topographic prominence still catches it.
        assert (70, False) in _labels(_TWO_DAY)

    def test_flat_bottomed_valley_still_labelled(self):
        # Even with an almost-flat floor and barely any rise back up at the
        # edge, a broad secondary valley keeps its label.
        flat = _SUN + _MON + [72, 71, 70, 70, 70, 70, 70, 71, 72]
        assert (70, False) in _labels(flat)

    def test_curvature_bend_never_evicts_a_real_extremum(self):
        # The real Sunday peak and the greedy placement must both survive:
        # peaks/valleys are placed before decorative curvature bends.
        labels = _labels(_TWO_DAY)
        assert (85, True) in labels
        assert (89, True) in labels

    def test_daily_peak_and_valley_both_survive_on_wide_canvas(self):
        # On the full multi-day canvas the min-gap can exceed a single day's
        # morning-valley-to-afternoon-peak span.  Because peaks are drawn above
        # the curve and valleys below, they must not evict each other: every
        # day should keep both a peak and a valley label.
        days = [(60, 82), (62, 88), (59, 90), (66, 95), (64, 84), (61, 80)]
        temps = []
        for lo, hi in days:
            for h in range(24):
                import math
                frac = -math.cos(2 * math.pi * (h - 5) / 24)
                temps.append(round((lo + hi) / 2 + (hi - lo) / 2 * frac, 1))
        # A wide canvas so min_gap > intra-day peak/valley spacing.
        graph_w = 185 * len(days) // 2
        labels = _labels(temps, graph_w)
        peaks = sum(1 for _, p in labels if p)
        valleys = sum(1 for _, p in labels if not p)
        assert peaks >= len(days) - 1, f"too few peaks labelled: {labels}"
        assert valleys >= len(days) - 1, f"too few valleys labelled: {labels}"
