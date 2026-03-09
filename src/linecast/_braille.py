"""Shared braille line-graph rendering.

Provides a single reusable function for building multi-row braille curve
graphs from any numeric data series.  Used by both the weather hourly chart
and the tides chart.
"""


def build_braille_curve(values, graph_w, n_rows=2, pad_frac=0.0, value_range=None):
    """Build an n_rows-high braille line graph from numeric data.

    Returns list of n_rows rows, each a list of (char, avg_value) tuples.
    Together the rows form a (n_rows*4)-dot-high graph spanning graph_w chars.
    Uses proper column assignment for thin diagonal lines.

    pad_frac: fraction of value range to pad above/below (0.0 = no padding).
              Useful for curves that need room for overlay labels.
    value_range: optional (min, max) to fix the y-axis scale.
    """
    n = 2 * graph_w  # samples: 2 per braille char (left col, right col)
    total_dots = n_rows * 4

    # Interpolate values to n evenly spaced samples
    samples = []
    for i in range(n):
        t = i / max(1, n - 1) * max(0, len(values) - 1)
        lo_i = int(t)
        hi_i = min(lo_i + 1, len(values) - 1)
        frac = t - lo_i
        samples.append(values[lo_i] + (values[hi_i] - values[lo_i]) * frac)

    if value_range is not None:
        s_min, s_max = value_range
    else:
        s_min, s_max = min(samples), max(samples)
    if pad_frac > 0:
        pad = max(0.3, (s_max - s_min) * pad_frac)
        s_min -= pad
        s_max += pad

    # Map to float y: 0=top(max), total_dots-1=bottom(min)
    if s_max == s_min:
        ys = [total_dots / 2] * n
    else:
        s_range = s_max - s_min
        ys = [(total_dots - 1) * (1 - (s - s_min) / s_range) for s in samples]

    # Round to integer dot positions
    ys_i = [max(0, min(total_dots - 1, int(round(y)))) for y in ys]

    # Braille dot bit positions: BITS[col][row] for 2x4 grid within each char
    bits = [[0x01, 0x02, 0x04, 0x40], [0x08, 0x10, 0x20, 0x80]]

    # Bit storage per (braille_row, char_col)
    rows_bits = [[0] * graph_w for _ in range(n_rows)]

    def _set_dot(ci, y, col):
        """Set a single braille dot at char index ci, dot row y, column col."""
        if ci < 0 or ci >= graph_w or y < 0 or y >= total_dots:
            return
        rows_bits[y // 4][ci] |= bits[col][y % 4]

    for i in range(graph_w):
        left_y = ys_i[2 * i]
        right_y = ys_i[2 * i + 1]

        # Place endpoint dots
        _set_dot(i, left_y, 0)
        _set_dot(i, right_y, 1)

        # Connect left->right: assign intermediate dots to correct column
        if left_y != right_y:
            y_lo, y_hi = min(left_y, right_y), max(left_y, right_y)
            for y in range(y_lo, y_hi + 1):
                x_frac = (y - left_y) / (right_y - left_y)
                col = 0 if abs(x_frac) < 0.5 else 1
                _set_dot(i, y, col)

        # Cross-char continuity: bridge from previous char's right col
        if i > 0:
            prev_y = ys_i[2 * i - 1]
            if prev_y != left_y:
                y_lo, y_hi = min(prev_y, left_y), max(prev_y, left_y)
                for y in range(y_lo, y_hi + 1):
                    _set_dot(i, y, 0)

    # Convert to (char, avg_value) tuples per row
    result = []
    for r in range(n_rows):
        row = []
        for ci in range(graph_w):
            avg_val = (samples[2 * ci] + samples[2 * ci + 1]) / 2
            row.append((chr(0x2800 + rows_bits[r][ci]), avg_val))
        result.append(row)

    return result
