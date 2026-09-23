"""Build a bus plan for a board and check it (M3a, decisions D37, D38).

    python3 scripts/plan_bus.py butterstick --reference     # read the reference's own routing back as a plan
    python3 scripts/plan_bus.py butterstick                 # our planner's plan, once there is one
    python3 scripts/plan_bus.py butterstick --reference --out build/plans/butterstick-reference.json

A plan is what M3a produces and a route is what M3b builds from it. The check is the gate: it runs in seconds, so
a mistake in a plan is caught in the session that makes it rather than after an hour of routing.
"""
import argparse
import sys
import time
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.bench import references as refs
from waffle_eda.kicad import board as kb
from waffle_eda.route import busplan as bp
from waffle_eda.route import busplanner as bpl


def build(key: str, source: str, costs=None, trace=None) -> tuple:
    ref = refs.REFERENCES[key]
    board = kb.load_board(refs.board_path(ref))
    if source == "reference":
        return ref, board, bp.from_reference(board, ref)
    return ref, board, bpl.plan_bus(board, ref, costs, trace)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("keys", nargs="+", help="reference keys, e.g. butterstick logicbone")
    ap.add_argument("--reference", action="store_true", help="read the board's own routing back as a plan")
    ap.add_argument("--out", default=None, help="write the plan as JSON to this path (one file per key if several)")
    ap.add_argument("--quiet", action="store_true", help="do not trace the planner's rounds")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                    help="a planner cost, e.g. --set rounds=8 --set step_mm=0.3")
    args = ap.parse_args(argv)

    costs = bpl.PlanCosts()
    for item in args.set:
        name, _, value = item.partition("=")
        if not hasattr(costs, name):
            raise SystemExit(f"no such planner cost: {name}; try {sorted(costs.__dict__)}")
        setattr(costs, name, type(getattr(costs, name))(value))
    trace = None if args.quiet else (lambda s: print(s, flush=True))

    failures = 0
    for key in args.keys:
        t0 = time.time()
        print(f"== {key}", flush=True)
        ref, board, plan = build(key, "reference" if args.reference else "planner", costs, trace)
        t1 = time.time()
        findings = bp.check(plan, board, ref)
        print(f"   {key}: {len(plan.legs)} legs over {len(plan.nets())} nets, built in {t1 - t0:.1f}s, "
              f"checked in {time.time() - t1:.1f}s")
        print("   " + bp.report(findings).replace("\n", "\n   "))
        failures += bool(findings)
        if args.out:
            path = Path(args.out) if len(args.keys) == 1 else Path(args.out) / f"{key}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(plan.to_json())
            print(f"   written to {path}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
