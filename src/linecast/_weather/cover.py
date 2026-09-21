"""Cloud cover in words, on the National Weather Service's scale.

Open-Meteo names a dry sky with WMO codes 0 to 3, which it takes as
clear, mainly clear, partly cloudy and overcast. In the WMO's own table
those four codes say how the sky changed over the past hour; the amount
of cloud is measured in eighths of the sky, and the national services
name it on scales of their own. The NWS uses five steps:

    Clear            1/8 or less
    Mostly Clear     1/8 to 3/8
    Partly Cloudy    3/8 to 5/8
    Mostly Cloudy    5/8 to 7/8
    Overcast         7/8 to 8/8

An airport report's FEW, SCT, BKN and OVC are one step each above clear.
Where a cloud cover is known, a dry sky is named by it on this scale;
the weather code itself is left as the source gave it.
"""

# The one step the WMO codes have no number for. Not a weather code:
# a key for the condition's name and icon, never written out as a code.
MOSTLY_CLOUDY = "mostly_cloudy"

_SKY_CODES = (0, 1, 2, 3)

# The upper edge of each step, in percent: 1/8, 3/8, 5/8, 7/8.
_STEPS = ((12.5, 0), (37.5, 1), (62.5, 2), (87.5, MOSTLY_CLOUDY))


def sky_condition(code, cover):
    """The condition to name: `code` itself where it is weather (rain,
    fog, snow) or no cover is known, else the cover's step on the NWS
    scale."""
    if code not in _SKY_CODES or cover is None:
        return code
    for edge, step in _STEPS:
        if cover <= edge:
            return step
    return 3


# An airport report's cloud amount as a cover in the middle of its step,
# so that sky_condition reads it back as the step it is.
REPORT_COVER = {"FEW": 25, "SCT": 50, "BKN": 75, "OVC": 100}
