"""New cloud data invalidates retained scenes without camera or input changes."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _globe_now, _maps_live
from linecast._maps_scene import Scene, SceneWorker


@pytest.fixture
def source(monkeypatch):
    state = {"stamp": None, "canvas": None, "checked": 0.0, "revision": 0}
    index = {"host": "unused", "satellite": {"infrared": [{"path": "first"}]}}
    monkeypatch.setattr(_globe_now, "_cloud", state)
    monkeypatch.setattr(_globe_now, "_noise_grid", lambda: None)
    monkeypatch.setattr(_globe_now, "_provider", lambda: None)
    monkeypatch.setattr(_globe_now, "_source_zoom", lambda zoom, h: int(zoom))
    monkeypatch.setattr(_globe_now.tiles, "fetch_index", lambda *args: index)
    monkeypatch.setattr(_globe_now.tiles, "stitch_xyz", lambda *args: object())
    monkeypatch.setattr(_globe_now, "_mosaic_white", lambda canvas: .5)
    monkeypatch.setattr(_globe_now, "_ring_cover", lambda *args: {})
    return state, index


def test_revision_changes_only_when_a_new_canvas_is_published(source):
    state, index = source
    assert _globe_now.revision() == 0
    assert _globe_now.refresh(1, 100)
    first = _globe_now.peek()
    assert _globe_now.revision() == 1
    assert not _globe_now.refresh(1, 100)
    assert _globe_now.peek() is first and _globe_now.revision() == 1
    index["satellite"]["infrared"][0]["path"] = "newer"
    assert _globe_now.refresh(1, 100)
    assert _globe_now.peek() is not first and _globe_now.revision() == 2
    assert _globe_now.refresh(2, 100)  # same weather, newly prepared resolution
    assert _globe_now.revision() == 3
    index.clear()
    assert not _globe_now.refresh(2, 100)
    assert state["revision"] == 3


def test_failed_refresh_keeps_the_canvas_and_revision(source, monkeypatch):
    _, index = source
    assert _globe_now.refresh(1, 100)
    previous = _globe_now.peek()
    index["satellite"]["infrared"][0]["path"] = "newer"

    def fail(*args):
        raise RuntimeError("offline")

    monkeypatch.setattr(_globe_now.tiles, "stitch_xyz", fail)
    with pytest.raises(RuntimeError, match="offline"):
        _globe_now.refresh(1, 100)
    assert _globe_now.peek() is previous and _globe_now.revision() == 1


def test_cloud_publication_refreshes_a_stationary_live_scene(source, monkeypatch):
    state, _ = source
    jobs, frames = [], []

    def thread_factory(*, target, daemon):
        return SimpleNamespace(start=lambda: jobs.append(target))

    def render(*args, **kwargs):
        frames.append(kwargs)
        return "frame"

    monkeypatch.setattr(_maps_live, "map_cells", lambda: (40, 20))
    monkeypatch.setattr(_maps_live, "render_map", render)
    app = _maps_live.MapApp(SimpleNamespace(lang="en"), 40, -73, "Home", 10,
                            "terrain", True, "car")
    app._worker = SceneWorker(wake=lambda: None, thread_factory=thread_factory)

    def prepare(camera, options, generation):
        frame = SimpleNamespace(camera=camera, revision=_globe_now.revision())
        return Scene(frame, frame)

    monkeypatch.setattr(app, "_prepare", prepare)
    app.render()
    jobs.pop(0)()
    app.render()
    original = frames[-1]["prepared"]
    assert original.revision == 0
    state["revision"] = 1  # async refresh publishes and nudges the live loop
    app.render()
    assert frames[-1]["refining"] and len(jobs) == 1
    assert frames[-1]["prepared"] is original  # refresh keeps the base map visible
    jobs.pop(0)()
    app.render()
    assert frames[-1]["prepared"].revision == 1
    assert frames[-1]["camera"].key == original.camera.key
    app.clouds = False
    app.render()
    jobs.pop(0)()
    app.render()
    clear = frames[-1]["prepared"]
    state["revision"] = 2
    app.render()
    assert frames[-1]["prepared"] is clear and not jobs
    app.stop()
