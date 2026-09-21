"""Each bus net's length to each memory, measured against that memory's clock (D30, D45).

    python3 scripts/segment_lengths.py butterstick logicbone orangecrab-r0.2.1

The length criteria in play are stated three different ways and only one of them is what we measure today:

* **D27**, the criterion in force, is the spread of **total net length** within a group, as wide as the reference
  itself achieves.
* **Lattice** (FPGA-TN-02038-2.1 section 9, D45) gives +/-50 mil from a DQ to its DQS and +/-100 mil from address
  and command to CK, as physical length in mils, and never says whether it means the whole net or one leg of it.
* **TI**, the only vendor that states the convention (D45), measures address and command **from the controller to
  each SDRAM separately**.

On a fly-by or dual-rank net the total is the sum of its legs, so the spread of totals and the spread of legs are
different quantities and a rule written for one cannot be judged by the other. Every class C reference exceeds
Lattice's address-and-command rule on total length while being a board that was built and works, which is the
evidence that the convention, not the number, is what is wrong. This prints both, per memory, so the owner can
decide D30 against the measurement rather than against an assumption.

Each row is one signal group at one memory: the spread of the legs reaching that memory, and the spread of those
legs relative to the clock leg reaching the same memory, which is the quantity the vendor rules name.
"""
import argparse
import sys
from collections import defaultdict

import _path  # noqa: F401
from waffle_eda.bench import bus_design as bd, references as refs
from waffle_eda.kicad import board as kb

MIL = 0.0254
LATTICE = {  # FPGA-TN-02038-2.1 section 9, as tolerances; the window a group may occupy is twice each
    "data to its strobe": 50 * MIL,
    "address/command to CK": 100 * MIL,
    "lane to lane": 100 * MIL,
    "pair": 10 * MIL,
}


def legs(board, ref) -> dict:
    """net -> {package -> length of the run from the controller to that package's pin}."""
    d = bd.measure_board(board, ref)
    out = {}
    for net, nd in d["nets"].items():
        per = {}
        for pad, p in (nd.get("paths") or {}).items():
            part = pad.split(".")[0]
            if part in ref.bus_parts and part != ref.bus_parts[0]:
                per[part] = min(per.get(part, 1e9), p["length_mm"])
        if per:
            out[net] = per
    return out, d


def report(key: str) -> None:
    """Each group against the signal its own rule names: a data bit against its byte lane's strobe, address and
    command against the clock. Lattice states no data-to-clock tolerance and no strobe-to-clock tolerance at all
    (D45), so neither is compared here -- a verdict against a rule the vendor does not write is worse than none."""
    ref = refs.REFERENCES[key]
    board = kb.load_board(refs.board_path(ref))
    per_net, d = legs(board, ref)
    memories = sorted({m for v in per_net.values() for m in v})
    group_of = {n: d["nets"][n]["group"] for n in per_net}
    role_of = {n: d["nets"][n]["role"] for n in per_net}
    total = {n: d["nets"][n]["length_mm"] for n in per_net}

    print(f"== {key}: controller {ref.bus_parts[0]}, memories {', '.join(memories)}")
    for mem in memories:
        print(f"   at {mem}")
        by_group = defaultdict(list)
        for n, v in per_net.items():
            if mem in v:
                by_group[group_of[n]].append((v[mem], bd.short_name(n), role_of[n]))
        for group, members in sorted(by_group.items()):
            if len(members) < 2:
                continue
            # the signal this group's rule is measured against, and the tolerance the vendor states
            if group == "address/command":
                anchor = [a for a, _n, role in members if role == "clock"]
                anchor_name, tol = "CK", LATTICE["address/command to CK"]
            elif group.startswith("lane"):
                anchor = [a for a, _n, role in members if role == "strobe"]
                anchor_name, tol = "its DQS", LATTICE["data to its strobe"]
            else:
                continue
            lens = [a for a, _n, _r in members]
            span = max(lens) - min(lens)
            tot = [total[n] for n in per_net if group_of[n] == group and mem in per_net[n]]
            span_total = max(tot) - min(tot)
            window = 2 * tol
            print(f"      {group:18s} {len(members):3d} nets   legs {min(lens):6.2f}-{max(lens):6.2f} "
                  f"spread {span:5.2f} mm   totals spread {span_total:5.2f} mm   "
                  f"Lattice window {window:.2f} mm: "
                  f"{'within' if span <= window + 1e-9 else 'OUTSIDE'} on legs, "
                  f"{'within' if span_total <= window + 1e-9 else 'OUTSIDE'} on totals")
            if not anchor:
                print(f"      {'':18s}       no {anchor_name} leg reaches {mem}: the rule cannot be applied here")
                continue
            ref_len = sum(anchor) / len(anchor)
            rel = [a - ref_len for a, _n, role in members if role != ("clock" if group == "address/command" else "strobe")]
            worst = max(abs(min(rel)), abs(max(rel))) if rel else 0.0
            print(f"      {'':18s}       against {anchor_name} at {mem} ({ref_len:.2f} mm): "
                  f"{min(rel):+6.2f} to {max(rel):+6.2f} mm, worst {worst:.2f} mm "
                  f"against a tolerance of {tol:.2f} mm: {'within' if worst <= tol + 1e-9 else 'OUTSIDE'}")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("keys", nargs="+")
    args = ap.parse_args(argv)
    for key in args.keys:
        ref = refs.REFERENCES[key]
        if not refs.is_fetched(ref):
            print(f"{key} is not fetched", file=sys.stderr)
            continue
        report(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
