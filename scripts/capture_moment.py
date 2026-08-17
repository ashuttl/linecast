#!/usr/bin/env python3
"""Run an astronomy view at a fixed local moment for documentation captures.

This is deliberately capture-only: the public CLI continues to show the real
sky.  Freezing the clock here makes the README's midday, dusk, and Moon frames
repeatable no matter when the screenshot pipeline runs.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from datetime import datetime as RealDateTime


def _coordinates(value: str) -> tuple[float, float]:
    try:
        lat, lng = value.split(",", 1)
        return float(lat), float(lng)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected LAT,LNG") from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="run sunshine or moon at a fixed local moment",
    )
    parser.add_argument("app", choices=("sunshine", "moon"))
    parser.add_argument("--at", required=True, help="local ISO time")
    parser.add_argument(
        "--location",
        type=_coordinates,
        default=(43.676, -70.371),
        metavar="LAT,LNG",
    )
    parser.add_argument("app_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    moment = RealDateTime.fromisoformat(args.at)
    if moment.tzinfo is not None:
        raise SystemExit("--at must be a local time without a UTC offset")

    class FixedDateTime(RealDateTime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.fromtimestamp(moment.timestamp())
            return cls.fromtimestamp(moment.timestamp(), tz)

    module = importlib.import_module(f"linecast.{args.app}")
    module.datetime = FixedDateTime
    lat, lng = args.location
    module.get_location = lambda: (lat, lng, "US")

    app_args = args.app_args
    if app_args[:1] == ["--"]:
        app_args = app_args[1:]
    sys.argv = [args.app, *app_args]
    module.main()


if __name__ == "__main__":
    main()
