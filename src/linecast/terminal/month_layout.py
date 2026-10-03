"""Shared vertical spacing for the weather and tides month charts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MonthLayout:
    ruled: bool
    days_per_row: int
    field_rows: int
    field_top: int
    header_gap: int
    heading_gap: int
    legend_gap: int
    footer_gap: int


def month_layout(rows, ndays, *, heading_rows=1, legend_rows=1, footer_rows=1):
    """Fit a day or two per row, then space the chart between the window edges.

    Keep the header clear of the heading, and the legend clear of the
    footer, before adding gaps beside the field. Any remaining space
    goes outside the heading and legend, centering the whole chart.
    The heading's rule gives way when two days per row would not fit.
    """
    fixed = 1 + heading_rows + 1 + legend_rows + footer_rows  # header and hour axis
    ruled = rows >= fixed + 1 + (ndays + 1) // 2
    available = max(4, rows - fixed - int(ruled))
    per_row = 1 if available >= ndays else 2
    field_rows = min(available, (ndays + per_row - 1) // per_row)
    spare = available - field_rows
    header_gap = int(spare > 0)
    footer_gap = int(spare > 1)
    heading_gap = int(spare > 2)
    legend_gap = int(spare > 3)
    spare -= header_gap + footer_gap + heading_gap + legend_gap
    header_gap += spare // 2
    footer_gap += spare - spare // 2
    field_top = 1 + header_gap + heading_rows + int(ruled) + heading_gap
    return MonthLayout(ruled, per_row, field_rows, field_top,
                       header_gap, heading_gap, legend_gap, footer_gap)
