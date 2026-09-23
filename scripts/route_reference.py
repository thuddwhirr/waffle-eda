#!/usr/bin/env python3
"""Re-route one class A reference from placement with the stage 5 baseline and score it (the class A gate, for
one board, with the knobs exposed so a measurement can name what it changed).

    python3 scripts/route_reference.py tinkerforge-temperature [--passes N] [--timeout S] [--no-pours]

Writes build/bench/<key>-routed.kicad_pcb and the stage's file trail under build/bench/stage5/<key>/ (the DSN,
session and log of the router, the DRC of every fill round, attempts.json), and prints the score line the gate
prints plus every net that failed and the first violations.
"""
from __future__ import annotations

import argparse
import json
import sys

import _path  # noqa: F401
from waffle_eda.bench import harness, rebuild, references as refs
from waffle_eda.kicad import board as kb
from waffle_eda.route import stage5


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("--passes", type=int, default=100)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--no-pours", action="store_true", help="route the supply nets as tracks instead of pouring them first")
    args = ap.parse_args(argv)
    ref = refs.REFERENCES[args.key]
    if not refs.is_fetched(ref):
        print(f"{ref.key}: not fetched")
        return 2
    bare, _info = rebuild.strip_all(ref)
    rules = rebuild.measure_rules(ref)
    print(rules.summary())
    board = kb.load_board(bare)
    spec = [] if args.no_pours else rebuild.pour_spec(ref)
    work = harness.bench_dir() / "stage5" / ref.key
    out = rebuild.problem_path(ref).with_name(f"{ref.key}-routed.kicad_pcb")
    result = stage5.route(board, rules, spec, work, out_path=out, passes=args.passes, timeout_s=args.timeout)
    print(result.summary())
    s = rebuild.score(ref, out)
    print(s.summary())
    for name, why in sorted(result.failed.items()):
        print("  failed:", why)
    for name, v in sorted(s.per_net.items()):
        if not v["connected"]:
            print("  unconnected:", name, v)
    if s.electrical:
        facts = json.loads((harness.bench_dir() / "rebuild" / ref.key / out.stem / "candidate.json").read_text())
        shown = 0
        for v in facts["violations"]:
            if v["type"] in harness.ELECTRICAL_TYPES and shown < 12:
                shown += 1
                print("  violation:", v["type"], "|", v.get("description", ""), "|",
                      " / ".join(i["description"] for i in v["items"]))
    rebuild.write_score(s)
    return 0 if s.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
