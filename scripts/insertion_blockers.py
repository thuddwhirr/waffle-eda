#!/usr/bin/env python3
"""What blocked each of the router's failed insertions (D126): the lines a jar built with the `diag` patch
(`tools/freerouting-2.4.1-diag.patch`) logs under `WAFFLE_DIAG_INSERT=1`, one per failed insertion, each naming
every item of another net within the clearance of the segments the inserter was laying and how deep its
violation is without the clearance matrix's safety margin, in board units (0.1 um).

    python3 scripts/patch_freerouting.py <fork checkout> d107 diag      # build/tools/freerouting-2.4.1-d107-diag.jar
    WAFFLE_DIAG_INSERT=1 WAFFLE_FREEROUTING_JAR=$PWD/build/tools/freerouting-2.4.1-d107-diag.jar \\
        WAFFLE_ROUTER_PASSES=4 python3 scripts/gate.py b upduino-v3.01
    python3 scripts/insertion_blockers.py build/fr/upduino-v3.01/freerouting.log [list]

The jar appends to `freerouting.log` across runs: delete it before the run. A failure whose deepest blocker is
inside (-16, 0] is the margin's alone (the geometry meets the rule); a blocker at the trace's own half width
plus the clearance is copper the segment crosses, which the maze meant the shove to move.
"""
import re
import sys
from collections import Counter

MARGIN = 16  # ClearanceMatrix.clearance_safety_margin in 2.4.1, in board units


def parse(path: str) -> list[dict]:
    rows = []
    for line in open(path, errors="replace"):
        at = line.find("WAFFLE_DIAG insert_fail")
        if at < 0:
            continue
        head, *blocks = line[at:].strip().split(" | ")
        m = re.search(r"net=(\d+) layer=(\d+) corner=(\d+)/(\d+) from=(\d+) half=(\d+) ok=(\S+) target=(\S+)",
                      head)
        net, layer, k, n, _frm, _half, _ok, target = m.groups()
        blockers = []
        for b in blocks:
            bm = re.match(r"(\S+) seg=(\d+) fixed=(\S+) net=(-?\d+) cl=(\d+) deficit=(-?\d+)", b)
            if bm:
                name, _seg, fixed, bnet, cl, deficit = bm.groups()
                blockers.append(dict(name=name, kind="pin" if name.startswith("Pin:") else name, fixed=fixed,
                                     net=int(bnet), cl=int(cl), deficit=int(deficit)))
        rows.append(dict(net=int(net), layer=int(layer), k=int(k), n=int(n), target=target, blockers=blockers))
    return rows


def kind(row: dict) -> str:
    real = [b for b in row["blockers"] if b["deficit"] > 0]
    if not row["blockers"]:
        return "no blocker found"
    if not real:
        return ("the margin alone (deficit in (-16, 0])" if any(b["deficit"] > -MARGIN for b in row["blockers"])
                else "blockers clear of the margin")
    if any(b["kind"] == "pin" for b in real):
        return "a pad inside its clearance"
    return "another net's " + "/".join(sorted({b["kind"] for b in real}))


def main() -> int:
    rows = parse(sys.argv[1])
    print(f"failed insertions: {len(rows)}; at the last corner {sum(r['k'] == r['n'] for r in rows)}, "
          f"into a pad {sum(r['target'] != 'none' for r in rows)}")
    for what, count in Counter(kind(r) for r in rows).most_common():
        print(f"  {count:4d}  {what}")
    if len(sys.argv) > 2:
        for r in rows:
            print(r["net"], r["layer"], f"{r['k']}/{r['n']}", r["target"], kind(r),
                  [(b["name"], b["fixed"], b["deficit"]) for b in r["blockers"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
