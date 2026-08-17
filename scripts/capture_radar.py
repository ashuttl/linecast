#!/usr/bin/env python3
"""Run radar slowly enough for a screenshot recorder to catch every frame.

This is a gallery-capture helper, not a user-facing playback mode.  ``grim``
takes long enough per screenshot that recording the normal animation can skip
terminal frames.  Slowing the live loop here lets ``capture_screenshots.sh``
sample every downloaded weather frame before re-encoding at the README speed.
"""

from linecast import radar
from linecast._graphics import live_loop as _live_loop


def _capture_live_loop(*args, **kwargs):
    kwargs["play_interval"] = 0.5
    return _live_loop(*args, **kwargs)


radar.live_loop = _capture_live_loop


if __name__ == "__main__":
    radar.main()
