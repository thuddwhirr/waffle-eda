"""Each bus net's run to each memory, as copper length and as delay, measured against the signal whose rule names
it (D30, D45, D47, D48).

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

Every row is then printed a second time as **delay** (D48). Copper length is a proxy for delay only while a group
stays on one kind of layer: outer copper carries a signal at about 5.6 ps/mm and inner copper at about 7.1, so a
group routed across both is matched in length and skewed in time, or the reverse. The delay rows give the spread
in picoseconds, the same figure as the stripline length of equal delay (TI's convention, the only one a vendor
states) for comparison with Lattice's millimetres, and the comparison against ISSI's picoseconds, which needs no
convention at all. Where the two disagree the delay row is the physical one.
"""
import argparse
import sys
from collections import defaultdict

import _path  # noqa: F401
from waffle_eda.bench import bus_design as bd, delay, references as refs
from waffle_eda.kicad import board as kb

MIL = 0.0254
LATTICE = {  # FPGA-TN-02038-2.1 section 9, as tolerances; the window a group may occupy is twice each
    "data to its strobe": 50 * MIL,
    "address/command to CK": 100 * MIL,
    "lane to lane": 100 * MIL,
    "pair": 10 * MIL,
}
ISSI_PS = {  # ISSI's DDR3 layout guidelines, which state the same two rules in picoseconds (D45)
    "data to its strobe": 10.0,
    "address/command to CK": 10.0,
}


def legs(board, ref) -> dict:
    """net -> {package -> the run from the controller to that package's pin}, as the whole path record so the
    same leg can be read as copper length or as delay. Where a net reaches a package at more than one pad (a
    dual-rank board does), the shortest run is the leg, as it was when only length was measured."""
    d = bd.measure_board(board, ref)
    out = {}
    for net, nd in d["nets"].items():
        per = {}
        for pad, p in (nd.get("paths") or {}).items():
            part = pad.split(".")[0]
            if part in ref.bus_parts and part != ref.bus_parts[0]:
                if part not in per or p["length_mm"] < per[part]["length_mm"]:
                    per[part] = p
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
    stack = delay.stackup_of(board)
    memories = sorted({m for v in per_net.values() for m in v})
    group_of = {n: d["nets"][n]["group"] for n in per_net}
    role_of = {n: d["nets"][n]["role"] for n in per_net}
    total = {n: d["nets"][n]["length_mm"] for n in per_net}
    # the same leg in the units the rule could mean: copper millimetres, and the stripline length of equal delay
    equiv = {n: {m: stack.equivalent_stripline_mm(p["per_layer_mm"]) for m, p in v.items()} for n, v in per_net.items()}

    print(f"== {key}: controller {ref.bus_parts[0]}, memories {', '.join(memories)}")
    print(f"   stackup: {stack.describe()}")
    for mem in memories:
        print(f"   at {mem}")
        by_group = defaultdict(list)
        for n, v in per_net.items():
            if mem in v:
                by_group[group_of[n]].append((v[mem]["length_mm"], bd.short_name(n), role_of[n], equiv[n][mem], n))
        for group, members in sorted(by_group.items()):
            if len(members) < 2:
                continue
            # the signal this group's rule is measured against, and the tolerance the vendor states
            anchor_role = "clock" if group == "address/command" else "strobe"
            if group == "address/command":
                anchor = [a for a, _n, role, _e, _f in members if role == "clock"]
                anchor_eq = [e for _a, _n, role, e, _f in members if role == "clock"]
                anchor_name, rule = "CK", "address/command to CK"
            elif group.startswith("lane"):
                anchor = [a for a, _n, role, _e, _f in members if role == "strobe"]
                anchor_eq = [e for _a, _n, role, e, _f in members if role == "strobe"]
                anchor_name, rule = "its DQS", "data to its strobe"
            else:
                continue
            tol, tol_ps = LATTICE[rule], ISSI_PS[rule]
            lens = [a for a, _n, _r, _e, _f in members]
            eqs = [e for _a, _n, _r, e, _f in members]
            span = max(lens) - min(lens)
            span_eq = max(eqs) - min(eqs)
            tot = [total[n] for n in per_net if group_of[n] == group and mem in per_net[n]]
            span_total = max(tot) - min(tot)
            window = 2 * tol
            print(f"      {group:18s} {len(members):3d} nets   legs {min(lens):6.2f}-{max(lens):6.2f} "
                  f"spread {span:5.2f} mm   totals spread {span_total:5.2f} mm   "
                  f"Lattice window {window:.2f} mm: "
                  f"{'within' if span <= window + 1e-9 else 'OUTSIDE'} on legs, "
                  f"{'within' if span_total <= window + 1e-9 else 'OUTSIDE'} on totals")
            # the same legs as delay, in the stripline length of equal delay (TI's convention), so the vendor's
            # millimetres can be compared against them without assuming which layer the vendor meant
            print(f"      {'':18s}       as delay: legs {min(eqs) * stack.stripline_ps_per_mm:6.1f}-"
                  f"{max(eqs) * stack.stripline_ps_per_mm:6.1f} ps, spread {span_eq * stack.stripline_ps_per_mm:5.1f} ps "
                  f"= {span_eq:5.2f} mm stripline-equivalent: "
                  f"{'within' if span_eq <= window + 1e-9 else 'OUTSIDE'} the {window:.2f} mm window "
                  f"({span_eq - span:+.2f} mm against copper length)")
            if not anchor:
                print(f"      {'':18s}       no {anchor_name} leg reaches {mem}: the rule cannot be applied here")
                continue
            ref_len = sum(anchor) / len(anchor)
            ref_eq = sum(anchor_eq) / len(anchor_eq)
            rel = [a - ref_len for a, _n, role, _e, _f in members if role != anchor_role]
            rel_eq = [e - ref_eq for _a, _n, role, e, _f in members if role != anchor_role]
            worst = max(abs(min(rel)), abs(max(rel))) if rel else 0.0
            worst_eq = max(abs(min(rel_eq)), abs(max(rel_eq))) if rel_eq else 0.0
            print(f"      {'':18s}       against {anchor_name} at {mem} ({ref_len:.2f} mm): "
                  f"{min(rel):+6.2f} to {max(rel):+6.2f} mm, worst {worst:.2f} mm "
                  f"against a tolerance of {tol:.2f} mm: {'within' if worst <= tol + 1e-9 else 'OUTSIDE'}")
            worst_ps = worst_eq * stack.stripline_ps_per_mm
            print(f"      {'':18s}       against {anchor_name} as delay ({ref_eq * stack.stripline_ps_per_mm:.1f} ps): "
                  f"{min(rel_eq) * stack.stripline_ps_per_mm:+6.1f} to {max(rel_eq) * stack.stripline_ps_per_mm:+6.1f} ps, "
                  f"worst {worst_ps:.1f} ps = {worst_eq:.2f} mm "
                  f"against {tol:.2f} mm: {'within' if worst_eq <= tol + 1e-9 else 'OUTSIDE'} "
                  f"({worst_eq - worst:+.2f} mm against copper length)")
            # ISSI publishes the same two rules in picoseconds, so this comparison assumes no convention at all:
            # neither which layer the vendor's millimetres meant nor whether the rule is per leg or per net
            print(f"      {'':18s}       against {anchor_name} in ISSI's own unit: worst {worst_ps:.1f} ps "
                  f"against {tol_ps:.0f} ps: {'within' if worst_ps <= tol_ps + 1e-9 else 'OUTSIDE'}")
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
