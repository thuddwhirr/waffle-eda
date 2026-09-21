#!/usr/bin/env python3
"""M4's benchmark: strip every net's copper from a board and score a candidate that re-routes all of it (D49).

    python3 scripts/rebuild_bench.py tinkerforge-temperature            # strip, then score the answer and the bare board
    python3 scripts/rebuild_bench.py libresolar-mppt-2420 --rules       # just the rules the board demonstrates
    python3 scripts/rebuild_bench.py open-book-c1 --candidate b.kicad_pcb

With no candidate this prints the benchmark's two sanity checks, which are the reason to trust its number: the
original copper has to score 1.000 and the stripped board 0.000. Anything else means the benchmark is crediting
work nobody did, or failing the reference for something it demonstrably does.
"""
import argparse
import sys
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.bench import rebuild, references as refs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("keys", nargs="+", help="reference keys (docs/references.md)")
    ap.add_argument("--rules", action="store_true", help="print the measured rules and stop")
    ap.add_argument("--candidate", type=Path, help="a routed board to score instead of the sanity pair")
    ap.add_argument("--force", action="store_true", help="re-measure the rules and re-strip, ignoring the cache")
    args = ap.parse_args(argv)

    if args.candidate and len(args.keys) != 1:
        print("--candidate scores one board, so name one reference", file=sys.stderr)
        return 2

    bad = 0
    for key in args.keys:
        if key not in refs.REFERENCES:
            print(f"{key}: not in the registry", file=sys.stderr)
            bad += 1
            continue
        ref = refs.REFERENCES[key]
        if not refs.is_fetched(ref):
            print(f"{key}: not fetched (python3 scripts/fetch_references.py)", file=sys.stderr)
            bad += 1
            continue
        rules = rebuild.measure_rules(ref, force=args.force)
        print(rules.summary())
        if args.rules:
            continue
        if args.candidate:
            score = rebuild.score(ref, args.candidate)
            print("  ", score.summary())
            bad += not score.passed
            continue
        bare, info = rebuild.strip_all(ref, reuse=not args.force)
        print(f"   stripped: {info['tracks']} tracks, {info['vias']} vias, {info['zones']} zones; "
              f"{info.get('routable_nets', '?')} nets to route")
        answer = rebuild.score(ref, refs.board_path(ref))
        empty = rebuild.score(ref, bare)
        print("   answer:", answer.summary())
        print("   bare  :", empty.summary())
        ok = answer.passed and answer.score == 1.0 and not empty.passed and empty.score == 0.0
        print(f"   sanity: {'ok' if ok else 'FAILED: the benchmark does not bracket this board'}")
        bad += not ok
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
