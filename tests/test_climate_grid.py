"""The vendored climate-family grid the terrain ramps climb by."""

from linecast.maps import climate as _climate


def test_the_tundra_climbs_the_polar_ramp_where_koppen_says_subarctic():
    places = [((69.4, -152.0), _climate.POLAR),    # the North Slope foothills
              ((64.0, -105.0), _climate.POLAR),    # Canada's Barren Grounds
              ((60.8, -161.75), _climate.POLAR),   # Bethel, on the Yukon delta
              ((70.6, -152.0), _climate.POLAR),    # the Arctic coastal plain
              ((64.84, -147.72), _climate.HUMID),  # Fairbanks, in the forest
              ((69.65, 18.95), _climate.HUMID),    # Tromsø, below the fjell
              ((25.0, 10.0), _climate.ARID)]       # the Sahara
    rows = _climate.grid_for_lls([[ll for ll, _ in places]])
    assert list(rows[0]) == [family for _, family in places]
