"""Measure complete warmed Moon/Sky frame generation, excluding terminal I/O."""

import argparse
import platform
import sys
import time
from pathlib import Path

from support import BASE, LAT, LNG, Results, _color, fn_for, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    results = Results(args.output_dir, "baseline.jsonl")
    results.write({
        "python": sys.version, "platform": platform.platform(),
        "cpu": platform.processor(), "color": _color.color_mode(),
        "datetime": str(BASE), "lat": LAT, "lng": LNG, "n": 50,
    })
    workloads = [
        ("moon", "drag", False, 100),
        ("sky", "drag", False, 100),
        ("sky", "hover", False, 100),
        ("sky", "drag", True, 100),
        ("sky", "drag", False, 6),
    ]
    for size in ((80, 24), (120, 40), (200, 60)):
        for which, mode, day, fov in workloads:
            render_frame = fn_for(which, mode, size, day, fov)
            for index in range(4):
                render_frame(index)
            wall, cpu, encoded_bytes = [], [], []
            for index in range(50):
                started_wall, started_cpu = time.perf_counter(), time.process_time()
                frame = render_frame(index)
                cpu.append((time.process_time() - started_cpu) * 1000)
                wall.append((time.perf_counter() - started_wall) * 1000)
                encoded_bytes.append(len(frame.encode()))
            results.write({
                "view": which, "mode": mode, "size": size, "day": day,
                "fov": fov, "wall_ms": summary(wall), "cpu_ms": summary(cpu),
                "bytes": summary(encoded_bytes),
            })


if __name__ == "__main__":
    main()
