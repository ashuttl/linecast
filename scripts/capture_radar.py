#!/usr/bin/env python3
"""Run radar slowly enough for a screenshot recorder to catch every frame.

This is a gallery-capture helper, not a user-facing playback mode.  ``grim``
takes long enough per screenshot that recording the normal animation can skip
terminal frames.  Slowing the live loop here lets ``capture_screenshots.sh``
sample every downloaded weather frame before re-encoding at the README speed.
"""

from linecast import _radar_live

_radar_live.RadarApp.play_interval = 0.5


if __name__ == "__main__":
    _radar_live.main()
