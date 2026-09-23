#!/usr/bin/env python3
"""Run a design's stages and gates, or print where it stands (plan.md, Interface).

    python3 scripts/design.py temperature-sensor status       # where the design is, which gate, what it waits on
    python3 scripts/design.py temperature-sensor 1            # run stage 1's gate (the design document)
    python3 scripts/design.py temperature-sensor 3            # generate the schematic, ERC, netlist check
    python3 scripts/design.py temperature-sensor all          # every stage in order, stopping at the first FAIL
    python3 scripts/design.py temperature-sensor 5 --passes 100 --timeout 600

Every stage writes reports/stage<N>.json in the design directory; the exit code is 0 on PASS.
"""
from __future__ import annotations

import argparse
import sys

import _path  # noqa: F401
from waffle_eda.design import pipeline


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("stage", help="1 to 6, all, or status")
    ap.add_argument("--passes", type=int, default=100)
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args(argv)
    d = pipeline.design_dir(args.name)
    if not d.is_dir():
        print(f"no design directory {d}")
        return 2
    if args.stage == "status":
        print(pipeline.status(d, args.name))
        return 0
    stages = range(1, 7) if args.stage == "all" else [int(args.stage)]
    for n in stages:
        kw = {"passes": args.passes, "timeout_s": args.timeout} if n == 5 else {}
        result = pipeline.run(args.name, n, **kw)
        print(result.summary())
        if not result.passed:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
