"""The command-line text toggle reaches live and printed astronomy views."""

import importlib
import sys
from datetime import timezone

import pytest


@pytest.mark.parametrize("command", ["sunshine", "moon"])
@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("hidden", [False, True])
def test_no_text_launch(monkeypatch, command, live, hidden):
    view = importlib.import_module(f"linecast.{command}.view")
    app_type = getattr(importlib.import_module(f"linecast.{command}.live"),
                       "SunshineApp" if command == "sunshine" else "MoonApp")
    flags = ["--live" if live else "--print", "--location", "43.68,-70.37",
             "--hours" if command == "sunshine" else "--calendar", "none"]
    if hidden:
        flags.append("--no-text")
    monkeypatch.setattr(sys, "argv", [command, *flags])
    monkeypatch.setattr(view, "place_for",
                        lambda args, runtime: (43.68, -70.37, "US", "Westbrook", runtime))
    monkeypatch.setattr(view, "location_tzinfo", lambda *a: timezone.utc)
    monkeypatch.setattr("linecast._geocode.place_label", lambda *a: "Westbrook")
    seen = []
    monkeypatch.setattr(app_type, "run", lambda app: seen.append(app.text))
    monkeypatch.setattr("linecast.terminal.live.print_view",
                        lambda render: seen.append(render.__self__.text))
    view.main()
    assert seen == [not hidden]
