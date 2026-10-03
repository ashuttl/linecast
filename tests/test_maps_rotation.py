"""City labels stay readable across frames of the slow globe rotation."""

import re

import pytest

from linecast._geo import wrap_lon
from linecast.maps import globe, places, style
from linecast.maps import view as maps
from linecast.terminal.textwidth import visible_len


def camera(lon=0.0, **kw):
    args = dict(lat=0.0, lon=lon, zoom=120.0, gw=80, hc=22)
    args.update(kw)
    return globe.Camera(**args)


def names(layout):
    return {entry[3] for _col, _row, _name, entry in layout}


@pytest.fixture
def neighbours(monkeypatch):
    # Large starts just behind the label visibility gate and enters
    # Small's space two seconds later.
    cities = [[-80.0, 0.0, 10_000_000, "Large"],
              [-55.0, 0.0, 1_000_000, "Small"]]
    monkeypatch.setattr(places, "load_data", lambda: {"cities": cities})
    return cities


def test_an_incumbent_keeps_its_place_when_a_bigger_neighbour_enters(neighbours):
    rotation = places.RotationLabels(-1.0)
    assert names(rotation.layout(camera(), 0)) == {"Small"}
    for step in range(1, 11):
        assert names(rotation.layout(camera(-step), 0)) == {"Small"}
    assert names(places.layout(camera(-10), 0)) == {"Large"}


def test_a_name_that_will_leave_soon_is_not_flushed_onto_the_screen(monkeypatch):
    cities = [[77.0, 0.0, 10_000_000, "Leaving"],
              [0.0, 0.0, 1_000_000, "Staying"]]
    monkeypatch.setattr(places, "load_data", lambda: {"cities": cities})
    assert names(places.layout(camera(), 0)) == {"Leaving", "Staying"}
    rotation = places.RotationLabels(-1.0)
    assert names(rotation.layout(camera(), 0)) == {"Staying"}
    assert names(places.layout(camera(-3), 0)) == {"Staying"}


def test_a_retained_name_leaves_when_it_reaches_the_hidden_hemisphere(monkeypatch):
    cities = [[70.0, 0.0, 10_000_000, "Leaving"]]
    monkeypatch.setattr(places, "load_data", lambda: {"cities": cities})
    rotation = places.RotationLabels(-1.0)
    assert names(rotation.layout(camera(), 0)) == {"Leaving"}
    for step in range(1, 9):
        assert names(rotation.layout(camera(-step), 0)) == {"Leaving"}
    assert rotation.layout(camera(-9), 0) == []


def test_wrapping_longitude_keeps_the_history(neighbours):
    for entry in neighbours:
        entry[0] = wrap_lon(entry[0] - 179)
    rotation = places.RotationLabels(-1.0)
    for step in range(5):
        cam = camera(wrap_lon(-179.0 - step))
        assert names(rotation.layout(cam, 0)) == {"Small"}
    assert names(places.layout(cam, 0)) == {"Large"}


@pytest.mark.parametrize("change", [
    {"lat": 1.0}, {"zoom": 110.0}, {"gw": 90}, {"hc": 24},
])
def test_a_new_camera_shape_starts_a_fresh_layout(neighbours, change):
    rotation = places.RotationLabels(-1.0)
    rotation.layout(camera(), 0)
    rotation.layout(camera(-1), 0)
    cam = camera(-2, **change)
    assert rotation.layout(cam, 0) == places.RotationLabels(-1.0).layout(cam, 0)


@pytest.mark.parametrize("lang, upper", [("fr", None), ("en", style.CITY_CAPS_POP)])
def test_a_language_or_register_change_releases_old_names(neighbours, lang, upper):
    rotation = places.RotationLabels(-1.0)
    rotation.layout(camera(), 0)
    rotation.layout(camera(-1), 0)
    cam = camera(-2)
    assert (rotation.layout(cam, 0, lang, upper)
            == places.RotationLabels(-1.0).layout(cam, 0, lang, upper))


def test_names_fit_whole_in_terminal_cells(monkeypatch):
    cities = [[77.0, 0.0, 10_000_000, "A very long name near the edge"],
              [0.0, 0.0, 1_000_000, "東京e\N{COMBINING ACUTE ACCENT}"]]
    monkeypatch.setattr(places, "load_data", lambda: {"cities": cities})
    rotation = places.RotationLabels(-1.0)
    for step in range(5):
        cam = camera(-step)
        layout = rotation.layout(cam, 0)
        assert names(layout) == {cities[1][3]}
        for col, row, name, entry in layout:
            assert name == entry[3]
            assert 0 <= col < col + 1 + visible_len(name) <= cam.gw
            assert 0 <= row < cam.hc
        overlays = places.terrain_overlays(cam, 0, rotation=rotation)
        assert len(overlays) == 1 + visible_len(cities[1][3])


def _spin(place, lat, lon, zoom, gw, hc, upper):
    previous, starts, durations, counts = set(), {}, [], []
    for frame in range(301):
        elapsed = frame / 5
        cam = camera(wrap_lon(lon - elapsed), lat=lat, zoom=zoom, gw=gw, hc=hc)
        layout = place(cam, 0, upper_pop=upper)
        current = {id(entry) for _col, _row, _name, entry in layout}
        for key in current - previous:
            starts[key] = elapsed if frame else None
        for key in previous - current:
            start = starts.pop(key)
            if start is not None:
                durations.append(elapsed - start)
        previous = current
        counts.append(len(current))
        occupied = set()
        for col, row, name, _entry in layout:
            cells = {(c, row) for c in range(col, col + 1 + visible_len(name))}
            assert not occupied & cells
            assert 0 <= row < hc and 0 <= col and col + 1 + visible_len(name) <= gw
            occupied.update(cells)
    return sum(d < 2.99 for d in durations), sum(counts)


@pytest.mark.parametrize("view", [
    (25.0, 140.0, 70.0, 188, 41, style.CITY_CAPS_POP),
    (46.8, 8.2, 120.0, 160, 43, None),
    (0.0, -179.0, 120.0, 80, 22, None),
])
def test_a_minute_of_rotation_suppresses_flashes_without_emptying_the_map(view):
    flashes_before, count_before = _spin(places.layout, *view)
    rotation = places.RotationLabels(-1.0)
    flashes_after, count_after = _spin(rotation.layout, *view)
    assert flashes_before > 0
    assert flashes_after == 0
    assert count_after >= 0.9 * count_before


def test_a_slow_frame_does_not_extend_the_forecast(neighbours):
    rotation = places.RotationLabels(-1.0)
    rotation.layout(camera(), 0)
    # After a discontinuity, a forecast from the old view is stale.
    cam = camera(-20)
    assert rotation.layout(cam, 0) == places.RotationLabels(-1.0).layout(cam, 0)


@pytest.mark.parametrize("view, label", [("terrain", "Small"), ("street", "SMALL")])
def test_both_renderers_use_the_rotation_history(neighbours, monkeypatch, view, label):
    monkeypatch.setattr(maps, "get_terminal_size", lambda: (80, 22))
    monkeypatch.setattr(maps, "_load_register",
                        lambda loader, win, block, source, what: (what[0], False, None))
    rotation = places.RotationLabels(-1.0)
    for step in range(4):
        frame = maps.render_map(0.0, -float(step), "Somewhere", 120.0,
                                view=view, show_text=False, rotation_labels=rotation)
        text = re.sub(r"\033\[[^m]*m", "", frame)
        assert label in text
        assert "LARGE" not in text and "Large" not in text
    frame = maps.render_map(0.0, -3.0, "Somewhere", 120.0, view=view,
                            show_text=False, show_labels=False, rotation_labels=rotation)
    assert label not in re.sub(r"\033\[[^m]*m", "", frame)
