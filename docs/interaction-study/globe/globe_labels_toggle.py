"""Compare the existing label toggle without changing geometry construction.

The first timed frame intentionally repeats the warmup view, reproducing the
historical capture. Use moving_frame_median_ms for the changing-camera result.
"""

import json
import statistics
import time

from globe_lod_diagnostic import Diagnostic, parser, write_output


def run(diagnostic, samples=12):
    result = []
    for diagonal in (False, True):
        for labels in (True, False):
            diagnostic.reset()
            diagnostic.maps.render_map(
                43, -70, "Diagnostic", diagnostic.zoom, block=True,
                marker=(43, -70), show_labels=labels)
            durations = []
            for i in range(samples):
                start = time.perf_counter()
                diagnostic.maps.render_map(
                    43 + i * 0.21 if diagonal else 43, -70 + i * 0.37,
                    "Diagnostic", diagnostic.zoom, block=True,
                    marker=(43, -70), show_labels=labels)
                durations.append((time.perf_counter() - start) * 1000)
            result.append(dict(
                diagonal=diagonal, show_labels=labels,
                median_ms=statistics.median(durations),
                moving_frame_median_ms=statistics.median(durations[1:]),
                cached_first_frame=True, samples_ms=durations))
    return json.dumps(result, indent=2)


def main():
    cli = parser(__doc__)
    args = cli.parse_args()
    if args.samples < 2:
        cli.error("--samples must be at least 2 to include a moving frame")
    diagnostic = Diagnostic(args.repo)
    with diagnostic.offline():
        result = run(diagnostic, args.samples)
    write_output(result, args.output)


if __name__ == "__main__":
    main()
