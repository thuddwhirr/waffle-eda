#!/usr/bin/env python3
"""Rerun stage 5's repair alone on a board the wrapper imported, and print the digest, so the repair's
reproducibility and its changes are measured in minutes rather than a Freerouting run each time.

    python3 scripts/repair_only.py <reference key> [--twice]

Reads build/fr/<key>/imported.kicad_pcb (written by `route.freerouting.route_board` before its repair), repairs
it under the reference's measured rules, scores it as the gate does, and with --twice does it again from the
same file and says whether the two digests agree (D25).
"""
from __future__ import annotations

import sys
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.bench import rebuild, references as refs
from waffle_eda.kicad import board as kb
from waffle_eda.route import freerouting as fr


def once(ref, src: Path, work: Path) -> tuple[str, dict, str]:
    board = kb.load_board(src)
    rules = rebuild.measure_rules(ref)
    report = fr.repair_clearances(board, rules, work / "repair")
    digest = fr.geometry_digest(board)
    _bare, info = rebuild.strip_all(ref)
    via_ring, pin_ring = fr.smallest_ring_mm(board)
    rings = [r for r in (via_ring, pin_ring) if r is not None]
    if info["pours"]:
        fr.hole_rule_areas(board, rules)
    fr.add_pours(board, info["pours"], rules, ring_mm=min(rings) if rings else None)
    out = work / f"{ref.key}-routed.kicad_pcb"
    kb.refill_zones(board)
    kb.save_board(board, out)
    return digest, report, rebuild.score(ref, out, work_dir=work / "score").summary()


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in refs.REFERENCES:
        print(__doc__)
        return 2
    ref = refs.REFERENCES[argv[0]]
    src = refs.repo_root() / "build" / "fr" / ref.key / "imported.kicad_pcb"
    if not src.is_file():
        print(f"no imported board at {src}: run the gate on {ref.key} first")
        return 1
    runs = 2 if "--twice" in argv else 1
    digests = []
    for i in range(1, runs + 1):
        digest, report, summary = once(ref, src, refs.repo_root() / "build" / "fr" / ref.key / f"repair-only-{i}")
        digests.append(digest)
        print(f"run {i}: digest {digest} repair {report}\n       {summary}")
    if runs > 1:
        print("reproducible" if len(set(digests)) == 1 else "NOT REPRODUCIBLE: the repair depends on something other than the board")
        return 0 if len(set(digests)) == 1 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
