#!/usr/bin/env python3
"""Fan out and bus-route the bus references, then judge the result: connectivity, DRC under the reference's
constraints, every net's length within the original's spread, vias only inside the packages (plan.md, M3).

    python3 scripts/bus_bench.py butterstick logicbone

Writes build/bench/<key>-bus.kicad_pcb and build/bench/<key>-bus.png, prints one line per net that fails.
"""
from __future__ import annotations

import faulthandler
import json
import os
import sys
import time

faulthandler.enable()  # a crash in the bindings prints the Python stack instead of a bare abort
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.bench import bus_design, constraints, harness, references as refs
from waffle_eda.kicad import board as kb, refill, render
from waffle_eda.route import bus as busr, escape as esc, fanout as fo, length as lengthr
from waffle_eda.route.lattice import Lattice


# Room kept between bus nets outside the pad arrays so that the serpentines of the length tuning fit: a bump of
# amplitude A needs the neighbour at least A away. Overridable for experiments with BUS_SPACING.
SPACING_MM = float(os.environ.get("BUS_SPACING", "0.8"))
OUT_DIR = Path(os.environ.get("BUS_OUT_DIR", "build/bench"))  # where the routed boards and drawings go


def bus_costs() -> busr.Costs:
    """``BUS_COSTS`` overrides the router's cost fields, e.g. ``max_vias=3,corridor_mm=6``."""
    costs = busr.Costs()
    for item in filter(None, os.environ.get("BUS_COSTS", "").split(",")):
        key, value = item.split("=")
        current = getattr(costs, key.strip())
        setattr(costs, key.strip(), type(current)(float(value)) if isinstance(current, int) else float(value))
    return costs


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
    out = {"fanout": {}}
    # The bus router fans out from the pads itself (decisions D22): a fan-out chosen without the bus in mind fills
    # the inner layers under the DRAMs with vias the bus then cannot pass. The FPGA is the exception: the bus does
    # not pass through it, its deep balls need every lane, and the escape router assigns those lanes well; so its
    # escapes are kept (BUS_FANOUT=first, the default; none or all for experiments).
    fanout = {"first": ref.bus_parts[:1], "all": list(ref.bus_parts), "none": []}[os.environ.get("BUS_FANOUT", "first")]
    sides = partner_sides(board, parts, bus)
    for part in fanout:
        lat = parts[part]
        others = [l for r, l in parts.items() if r != part]
        cx = sum((o.x0 + o.X(o.cols - 1)) / 2 for o in others) / len(others)
        cy = sum((o.y0 + o.Y(o.rows - 1)) / 2 for o in others) / len(others)
        t0 = time.time()
        r = esc.escape_package(board, part, bus, rules[part], exit_side=lat.facing_side(cx, cy),
                               exit_sides=sides.get(part))
        print(f"   fan-out {part}: {len(r.escaped)}/{r.total} escaped | {time.time() - t0:.1f}s", flush=True)
        out["fanout"][part] = {"placed": len(r.escaped), "total": r.total, "failed": r.failed}
    in_pad = tuple(part for part, pc in c.packages.items() if pc.style == "in-pad")
    # D32: the escape style of each package is measured on the reference and given to the router, so its vias take
    # the offsets from a ball that this package's own design uses. With BUS_STYLE=diagonal the router is given the
    # rule both references obey instead (on the ball or on a diagonal corner, never in the channel between two
    # neighbouring balls), which is what a board with no reference of its own gets.
    style_mode = os.environ.get("BUS_STYLE", "reference")
    diagonal = ((0.0, 0.0), (0.5, 0.5), (0.5, -0.5), (-0.5, 0.5), (-0.5, -0.5))
    ball_via_offsets: dict = {}
    if style_mode != "off":
        measured = bus_design.escape_style(kb.load_board(refs.board_path(ref)), ref)
        for part, lat in parts.items():
            if lat.rows < 4 or lat.cols < 4:
                continue
            if style_mode == "reference" and measured.get(part, {}).get("vias"):
                ball_via_offsets[part] = measured[part]["offsets"]
            else:
                ball_via_offsets[part] = diagonal
        print("   escape style per package: "
              + "; ".join(f"{k} {v}" for k, v in ball_via_offsets.items()), flush=True)
    rules_bus = busr.BusRules(**{**bus_rules(c).__dict__, "in_pad_packages": in_pad,
                                 "ball_via_offsets": ball_via_offsets})
    answer = refs.measure(ref)
    lo, hi = answer["bus"]["length_mm"]["min"], answer["bus"]["length_mm"]["max"]
    t0 = time.time()
    costs = bus_costs()
    # a run has to end with a board and a score: the negotiation stops when it stops improving, and the repair
    # stage spends at most its budget (three runs in a row were killed by a timeout in repair and measured nothing)
    if not costs.stall_stop:
        costs.stall_stop = 15
    if not costs.repair_budget_s:
        costs.repair_budget_s = 900.0
    if not costs.max_vias_per_net:  # D32: the reference's own limit on a net's layer changes, unless overridden
        costs.max_vias_per_net = bus_design.structure(kb.load_board(refs.board_path(ref)), ref)["max_vias_per_net"]
        print(f"   vias per net: at most {costs.max_vias_per_net}, as the reference keeps them", flush=True)
    res = busr.route_bus(board, [p for p, l in parts.items() if l.rows >= 4 and l.cols >= 4], bus, rules_bus,
                         costs=costs, length_windows={n: (lo, hi) for n in bus})
    print(f"   bus: {res.summary()} | {time.time() - t0:.1f}s", flush=True)
    for n, why in sorted(res.failed.items()):
        print(f"      FAILED {n}: {why}")
    # length window: the original's spread (harness.score judges every net against it)
    arrays = [parts[p] for p in parts if parts[p].rows >= 4 and parts[p].cols >= 4]

    def in_array(x, y):
        """Within half a pitch of a pad: the tuner keeps off the fan-out, not off a DRAM's hollow middle, where
        the reference boards put their meanders."""
        for l in arrays:
            fi, fj = (x - l.x0) / l.pitch, (y - l.y0) / l.pitch
            i, j = round(fi), round(fj)
            if abs(fi - i) <= 0.5 + 1e-9 and abs(fj - j) <= 0.5 + 1e-9 and (i, j) in l.by_index:
                return True
        return False

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
    for line in score.matching_lines:
        print(f"      {line}", flush=True)
    # D32: how our structure stands against the reference's, every run, so the distance is measured and not guessed
    ours_st = bus_design.structure(kb.load_board(result_path), ref)
    ref_st = bus_design.structure(kb.load_board(refs.board_path(ref)), ref)
    print("   structure against the reference:", flush=True)
    for line in bus_design.structure_lines(ours_st, ref_st):
        print(f"      {line}", flush=True)
    out["bus"] = {"routed": len(res.routed), "total": res.total, "failed": res.failed, "drc": drc,
                  "lengths_failed": tuned.failed,
                  "score": score.summary(), "passed": score.passed, "length_within": score.length_within_spread,
                  "matching": score.matching_passed, "matching_failures": score.matching_failures,
                  "bus_nets": score.bus_nets, "vias_outside": outside,
                  "structure": ours_st, "structure_reference": ref_st}
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
