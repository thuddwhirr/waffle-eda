#!/usr/bin/env python3
"""Fan out and bus-route the bus references, then judge the result: connectivity, DRC under the reference's
constraints, every net's length within the original's spread, vias only inside the packages (plan.md, M3).

    python3 scripts/bus_bench.py butterstick logicbone

Writes build/bench/<key>-bus.kicad_pcb and build/bench/<key>-bus.png, prints one line per net that fails.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.bench import constraints, harness, references as refs
from waffle_eda.kicad import board as kb, refill, render
from waffle_eda.route import bus as busr, escape as esc, fanout as fo, length as lengthr
from waffle_eda.route.lattice import Lattice


# Room kept between bus nets outside the pad arrays so that the serpentines of the length tuning fit: a bump of
# amplitude A needs the neighbour at least A away. Overridable for experiments with BUS_SPACING.
SPACING_MM = float(os.environ.get("BUS_SPACING", "0.8"))
OUT_DIR = Path(os.environ.get("BUS_OUT_DIR", "build/bench"))  # where the routed boards and drawings go


def bus_rules(c: constraints.Constraints, spacing_mm: float = SPACING_MM) -> busr.BusRules:
    """The bus runs at the board's narrowest bus track and smallest bus via, on the layers the bus uses."""
    return busr.BusRules(track_mm=c.min_track_mm, clearance_mm=c.clearance_mm, via_mm=c.min_via_mm,
                         via_drill_mm=c.min_drill_mm, layers=tuple(c.layers), hole_clearance_mm=c.hole_to_copper_mm,
                         spacing_mm=spacing_mm)


def partner_sides(board, parts: dict, bus: set[str]) -> dict[str, dict[str, str]]:
    """For each package and bus net, the side of the package that faces the net's pads on the other packages, so
    that an escape leaves toward what the bus router has to reach."""
    pads: dict[str, dict[str, list]] = {}
    for part in parts:
        fp = kb.footprint(board, part)
        for pad in fp.Pads():
            if pad.GetNetname() in bus:
                p = pad.GetPosition()
                pads.setdefault(pad.GetNetname(), {}).setdefault(part, []).append((kb.mm(p.x), kb.mm(p.y)))
    out: dict[str, dict[str, str]] = {part: {} for part in parts}
    for net, by_part in pads.items():
        for part, lat in parts.items():
            others = [xy for p2, xys in by_part.items() if p2 != part for xy in xys]
            if part in by_part and others:
                cx = sum(x for x, _ in others) / len(others)
                cy = sum(y for _, y in others) / len(others)
                out[part][net] = lat.facing_side(cx, cy)
    return out


def run_reference(key: str, draw: bool = True) -> dict:
    ref = refs.REFERENCES[key]
    c = constraints.measure(ref)
    rules = {part: constraints.fanout_rules(c, part) for part in c.packages}
    print(f"== {key}: {constraints.summary(c)}", flush=True)
    problem, _ = harness.strip_bus(ref)
    board = kb.load_board(problem)
    bus = set(kb.nets_matching(board, ref.bus_net_pattern))
    parts = {r: Lattice(kb.footprint(board, r)) for r in ref.bus_parts}
    out = {}
    # The bus router fans out from the pads itself (decisions D22): a fan-out chosen without the bus in mind fills
    # the inner layers under the DRAMs with vias the bus then cannot pass.
    in_pad = tuple(part for part, pc in c.packages.items() if pc.style == "in-pad")
    rules_bus = busr.BusRules(**{**bus_rules(c).__dict__, "in_pad_packages": in_pad})
    t0 = time.time()
    res = busr.route_bus(board, [p for p, l in parts.items() if l.rows >= 4 and l.cols >= 4], bus, rules_bus)
    print(f"   bus: {res.summary()} | {time.time() - t0:.1f}s", flush=True)
    for n, why in sorted(res.failed.items()):
        print(f"      FAILED {n}: {why}")
    # length window: the original's spread (harness.score judges every net against it)
    answer = refs.measure(ref)
    lo, hi = answer["bus"]["length_mm"]["min"], answer["bus"]["length_mm"]["max"]
    arrays = [parts[p] for p in parts if parts[p].rows >= 4 and parts[p].cols >= 4]

    def in_array(x, y):
        return any(l.inside_array(x, y, 0.5) for l in arrays)

    t0 = time.time()
    tuned = lengthr.tune_lengths(board, sorted(bus), lo, hi, c.clearance_mm, c.hole_to_copper_mm,
                                 region_mm=None, skip_region=in_array)
    print(f"   lengths: {tuned.summary()} (window {lo} to {hi} mm) | {time.time() - t0:.1f}s", flush=True)
    for n, why in sorted(tuned.failed.items())[:8]:
        print(f"      SHORT {n}: {why}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result_path = OUT_DIR / f"{key}-bus.kicad_pcb"
    kb.save_board(board, result_path)
    refill.refill_file(result_path)
    work = OUT_DIR / "constraints" / key
    drc = harness.drc_with_rules(result_path, c.rules_text(), work / "bus", bus, tag="bus")
    print(f"   DRC under the reference's constraints: {drc['electrical_bus']} {drc['electrical_bus_by_type']}, "
          f"unconnected bus nets {len(drc['unconnected_bus_nets'])}", flush=True)
    score = harness.score(ref, result_path, work_dir=work / "score")
    print(f"   {score.summary()}", flush=True)
    outside = [(n, v["vias"] - v["vias_in_package"]) for n, v in score.nets.items() if v["vias"] > v["vias_in_package"]]
    short = [(n, v["length_mm"]) for n, v in score.nets.items()
             if not (score.length_spread_mm[0] - 1e-3 <= v["length_mm"] <= score.length_spread_mm[1] + 1e-3)]
    print(f"   lengths within spread {score.length_within_spread}/{score.bus_nets} (spread {score.length_spread_mm}); "
          f"nets with vias outside packages: {len(outside)}", flush=True)
    for n, L in sorted(short, key=lambda x: x[1])[:6]:
        print(f"      length {n}: {L} mm")
    out["bus"] = {"routed": len(res.routed), "total": res.total, "failed": res.failed, "drc": drc,
                  "lengths_failed": tuned.failed,
                  "score": score.summary(), "passed": score.passed, "length_within": score.length_within_spread,
                  "bus_nets": score.bus_nets, "vias_outside": outside}
    if draw:
        boxes = [kb.package_info(kb.footprint(board, r)).bbox_mm for r in ref.bus_parts]
        region = (min(b[0] for b in boxes) - 2, min(b[1] for b in boxes) - 2, max(b[2] for b in boxes) + 2, max(b[3] for b in boxes) + 2)
        px = min(60.0, 2000 / (region[2] - region[0]), 2000 / (region[3] - region[1]))
        svg = render.draw_region_svg(board, region, result_path.with_suffix(".svg"), bus, px, None, None, title=f"{key} bus, ours")
        render.svg_to_png(svg, result_path.with_suffix(".png"), int((region[2] - region[0]) * px) + 1, int((region[3] - region[1]) * px) + 25)
    return out


def main(argv: list[str]) -> int:
    results = {}
    for key in argv or ["butterstick", "logicbone"]:
        results[key] = run_reference(key)
    (OUT_DIR / "bus-results.json").write_text(json.dumps(results, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
