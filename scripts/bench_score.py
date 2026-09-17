#!/usr/bin/env python3
"""Strip a reference's bus and score a candidate against the original copper.

    python3 scripts/bench_score.py butterstick                 # strip, then score the problem board ("do nothing")
    python3 scripts/bench_score.py butterstick --answer        # score the original copper (must pass)
    python3 scripts/bench_score.py butterstick path/to/candidate.kicad_pcb
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.bench import harness, references as refs


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("reference", choices=sorted(refs.REFERENCES))
    ap.add_argument("candidate", nargs="?")
    ap.add_argument("--answer", action="store_true", help="score the reference's own copper")
    args = ap.parse_args(argv)
    ref = refs.REFERENCES[args.reference]
    if not refs.is_fetched(ref):
        print(f"{ref.key}: not fetched (run scripts/fetch_references.py)")
        return 1
    problem, removed = harness.strip_bus(ref)
    print(f"problem board {problem} (removed {removed})")
    if args.answer:
        candidate = refs.board_path(ref)
    elif args.candidate:
        candidate = Path(args.candidate)
    else:
        candidate = problem
    s = harness.score(ref, candidate)
    print(s.summary())
    print("->", harness.write_score(s))
    return 0 if s.passed or candidate == problem else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
