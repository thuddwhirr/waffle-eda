#!/usr/bin/env python3
"""Run a design through the pipeline's stages, or say where it is (`docs/plan.md`, "Interface").

    python3 scripts/design.py run temperature-sensor            # every stage in order; stops at a failing gate
    python3 scripts/design.py run temperature-sensor --to 3     # stages 1 to 3
    python3 scripts/design.py run temperature-sensor --from 5   # stage 5 onward (the earlier reports must pass)
    python3 scripts/design.py status temperature-sensor         # each gate's state and what waits on the owner

A stage reads the previous stage's files under designs/<name>/ and writes its own, plus reports/stage<N>-<name>.md
(PASS or FAIL first, the failing criteria, what waits on the owner, the numbers). Scratch goes under build/.
"""
from __future__ import annotations

import argparse
import importlib
import sys

import _path  # noqa: F401
from waffle_eda.design.directory import Design, STAGES, designs_dir

MODULES = {1: "stage1_design", 2: "stage2_bom", 3: "stage3_schematic", 4: "stage4_spec", 5: "stage5_layout",
           6: "stage6_outputs"}


def run_stage(design: Design, stage: int):
    mod = importlib.import_module(f"waffle_eda.design.{MODULES[stage]}")
    return mod.run(design)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("run", "status", "list"))
    ap.add_argument("name", nargs="?", help="the design's directory name under designs/")
    ap.add_argument("--from", dest="start", type=int, default=1, choices=range(1, 7))
    ap.add_argument("--to", dest="stop", type=int, default=6, choices=range(1, 7))
    args = ap.parse_args(argv)
    if args.command == "list":
        for d in sorted(designs_dir().glob("*/design.md")):
            print(d.parent.name)
        return 0
    if not args.name:
        ap.error("name the design")
    design = Design.named(args.name)
    if not design.root.is_dir():
        print(f"no design at {design.root}", file=sys.stderr)
        return 2
    if args.command == "status":
        print(design.status())
        return 0
    for stage in range(args.start, args.stop + 1):
        if stage > 1:
            before = design.result(stage - 1)
            if before is None or not before.passed:
                print(f"stage {stage - 1}'s gate has not passed; run it first")
                return 1
        result = run_stage(design, stage)
        print(f"stage {stage} {dict(STAGES)[stage]}: {'PASS' if result.passed else 'FAIL'} "
              f"({len(result.failing)} failing, {len(result.escalated)} waiting on the owner, {result.seconds:.1f} s)")
        for c in result.failing:
            print(f"   FAIL {c.criterion}: {c.detail}")
        for c in result.escalated:
            print(f"   owner {c.criterion}: {c.detail}")
        if not result.passed:
            print(f"   see {design.reports / f'stage{stage}-{dict(STAGES)[stage]}.md'}")
            return 1
    print(design.status())
    return 0


if __name__ == "__main__":
    sys.exit(main())
