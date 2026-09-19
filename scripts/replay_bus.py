"""Replay a reference's bus structure (D26, step 3): the stripped problem board gets the reference's vias back, the
router is told each net's single-layer runs between its terminals (the reference's plan) and has to find the paths;
then the tuner matches the lanes as the reference does (D27) and the result is checked by DRC and by the D27
judgement. What this tests: the search and the negotiation under the reference's plan, and the tuner's ability to
make the lengths in the reference's spaces."""
import json
import os
import re
import sys
import time
from pathlib import Path

import _path  # noqa: F401
import pcbnew
from waffle_eda.bench import bus_design, constraints, harness, references as refs
from waffle_eda.kicad import board as kb, refill, render
from waffle_eda.route import bus as busr, length as lengthr
from waffle_eda.route.lattice import Lattice
import bus_bench

OUT_DIR = Path(os.environ.get("BUS_OUT_DIR", "build/replay"))


def replay(key: str) -> dict:
    ref = refs.REFERENCES[key]
    c = constraints.measure(ref)
    print(f"== replay {key}: {constraints.summary(c)}", flush=True)
    ref_board = kb.load_board(refs.board_path(ref))
    reference = bus_design.measure_board(ref_board, ref)
    problem, _ = harness.strip_bus(ref)
    board = kb.load_board(problem)
    bus = sorted(kb.nets_matching(board, ref.bus_net_pattern))
    plan = bus_design.reference_plan(ref_board, bus, ref.bus_parts[0])
    nets_by_name = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() in plan and pad.GetNetname() not in nets_by_name:
                nets_by_name[pad.GetNetname()] = pad.GetNet()
    # the reference's vias go back on the board as the nets' own copper
    added = 0
    for name, d in plan.items():
        for (x, y, dia, drill) in d["vias"]:
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(kb.nm(x), kb.nm(y)))
            v.SetWidth(kb.nm(dia))
            v.SetDrill(kb.nm(drill))
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            v.SetNet(nets_by_name[name])
            board.Add(v)
            added += 1
    # the plan's links as (x_a, y_a, x_b, y_b, layer name)
    plans = {}
    skipped = 0
    for name, d in plan.items():
        pos = {label: (x, y) for (label, x, y) in d["pads"]}
        links = []
        for (a, b, layer, L) in d["links"]:
            xy = []
            for lab in (a, b):
                if lab in pos:
                    xy.append(pos[lab])
                else:
                    m = re.fullmatch(r"via@([\d.]+),([\d.]+)", lab)
                    xy.append((float(m.group(1)), float(m.group(2))) if m else None)
            if None in xy:
                skipped += 1
                continue
            links.append((xy[0][0], xy[0][1], xy[1][0], xy[1][1], layer))
        plans[name] = links
    print(f"   plan: {added} vias placed, {sum(len(v) for v in plans.values())} links over {len(plans)} nets, "
          f"{skipped} links without a terminal", flush=True)
    parts = {r: Lattice(kb.footprint(board, r)) for r in ref.bus_parts}
    in_pad = tuple(part for part, pc in c.packages.items() if pc.style == "in-pad")
    rules_bus = busr.BusRules(**{**bus_bench.bus_rules(c, 0.0).__dict__, "in_pad_packages": in_pad})
    t0 = time.time()
    res = busr.route_bus(board, [p for p, l in parts.items() if l.rows >= 4 and l.cols >= 4], set(bus), rules_bus,
                         costs=bus_bench.bus_costs(), plans=plans)
    print(f"   bus: {res.summary()} | {time.time() - t0:.1f}s", flush=True)
    for n, why in sorted(res.failed.items()):
        print(f"      FAILED {n}: {why}")
    # lengths as the reference matches them (D27): lanes on total length, pairs within 0.2 mm
    lanes, pairs = {}, {}
    for n in bus:
        g, role, pair = bus_design.classify(n)
        if g.startswith("lane"):
            lanes.setdefault(g, ([], reference["groups"][g]["total_length_mm"]["spread"]))[0].append(n)
        if pair:
            pairs.setdefault(pair, []).append(n)
    pairs = {k: v for k, v in pairs.items() if len(v) == 2}
    arrays = list(parts.values())

    def near_pad(x, y):
        for l in arrays:
            fi, fj = (x - l.x0) / l.pitch, (y - l.y0) / l.pitch
            i, j = round(fi), round(fj)
            if abs(fi - i) <= 0.5 + 1e-9 and abs(fj - j) <= 0.5 + 1e-9 and (i, j) in l.by_index:
                return True
        return False

    t0 = time.time()
    windows = lengthr.lane_windows(board, lanes, pairs)
    tuned = lengthr.tune_lengths(board, sorted(windows), 0.0, float("inf"), c.clearance_mm, c.hole_to_copper_mm,
                                 skip_region=near_pad, windows=windows)
    print(f"   lanes: {tuned.summary()} | {time.time() - t0:.1f}s", flush=True)
    for n, why in sorted(tuned.failed.items())[:12]:
        print(f"      SHORT {n}: {why}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result_path = OUT_DIR / f"{key}-replay.kicad_pcb"
    kb.save_board(board, result_path)
    refill.refill_file(result_path)
    drc = harness.drc_with_rules(result_path, c.rules_text(), OUT_DIR / "constraints" / key, set(bus), tag="replay")
    print(f"   DRC under the reference's constraints: {drc['electrical_bus']} {drc['electrical_bus_by_type']}, "
          f"unconnected bus nets {len(drc['unconnected_bus_nets'])}", flush=True)
    candidate = bus_design.measure_board(kb.load_board(result_path), ref)
    verdict = bus_design.judge(candidate, reference)
    print(f"   matching (D27): {'PASS' if verdict['passed'] else 'FAIL'}")
    for line in verdict["lines"]:
        print(f"      {line}")
    for line in verdict["failures"]:
        print(f"      FAIL {line}")
    (OUT_DIR / f"{key}-replay-design.json").write_text(json.dumps(candidate, indent=1, default=str))
    boxes = [kb.package_info(kb.footprint(board, r)).bbox_mm for r in ref.bus_parts]
    region = (min(b[0] for b in boxes) - 2, min(b[1] for b in boxes) - 2, max(b[2] for b in boxes) + 2, max(b[3] for b in boxes) + 2)
    px = min(60.0, 2000 / (region[2] - region[0]), 2000 / (region[3] - region[1]))
    svg = render.draw_region_svg(kb.load_board(result_path), region, result_path.with_suffix(".svg"), set(bus), px, None, None,
                                 title=f"{key} bus, replayed from the reference's plan")
    render.svg_to_png(svg, result_path.with_suffix(".png"), 1600, 1200)
    return {"routed": len(res.routed), "total": res.total, "failed": res.failed, "drc": drc["electrical_bus"],
            "matching": verdict}


if __name__ == "__main__":
    import faulthandler
    faulthandler.enable()
    for key in sys.argv[1:] or ["butterstick"]:
        replay(key)
