"""Replay a reference's bus structure (D26, step 3): the stripped problem board gets the reference's vias back, the
router is told each net's single-layer runs between its terminals (the reference's plan) and has to find the paths;
then the tuner matches the lanes as the reference does (D27) and the result is checked by DRC and by the D27
judgement. What this tests: the search and the negotiation under the reference's plan, and the tuner's ability to
make the lengths in the reference's spaces.

With ``REPLAY_PLANNER=1`` (D26 step 4) only the reference's escapes are kept as they are: its vias and its short
top-layer runs from a pad to a via. Every other run (via to via, and the long runs to a pad) is given to the bus
planner, which chooses the layer and a coarse route under channel capacities, with the length a net still needs
reserved beside its route; those routes become the bands the detailed search stays in."""
import json
import math
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import _path  # noqa: F401
import pcbnew
from waffle_eda.bench import bus_design, constraints, harness, references as refs
from waffle_eda.kicad import board as kb, refill, render
from waffle_eda.route import bus as busr, length as lengthr, plan as planr
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
    use_planner = os.environ.get("REPLAY_PLANNER", "") == "1"
    band_mm = float(os.environ.get("REPLAY_BAND_MM", "0.35" if use_planner else "0"))  # > 0: each link's search stays this close to the reference's route
    escape_mm = float(os.environ.get("REPLAY_ESCAPE_MM", "8"))  # a top-layer run from a pad shorter than this is an escape
    parts = {r: Lattice(kb.footprint(board, r)) for r in ref.bus_parts}
    in_pad = tuple(part for part, pc in c.packages.items() if pc.style == "in-pad")
    rules_bus = busr.BusRules(**{**bus_bench.bus_rules(c, 0.0).__dict__, "in_pad_packages": in_pad})
    layer_ids = {lname: lid for lid, lname in kb.copper_layers(board)}
    bus_layers = tuple(layer_ids[n] for n in rules_bus.layers if n in layer_ids)

    def pad_layers(label, name):
        """The layers a run may end on at a pad: the pad's own, or every bus layer when a via sits in the pad."""
        part, number = label.split(".", 1)
        pad = kb.footprint(board, part).FindPadByNumber(number)
        x, y = kb.mm(pad.GetPosition().x), kb.mm(pad.GetPosition().y)
        if any(math.hypot(vx - x, vy - y) < 0.05 for (vx, vy, _, _) in plan[name]["vias"]):
            return set(bus_layers)
        return {L for L in pad.GetLayerSet().CuStack() if L in bus_layers}

    boxes = {r: kb.package_info(kb.footprint(board, r)).bbox_mm for r in ref.bus_parts}

    def package_at(x, y) -> str:
        """The bus package a terminal belongs to: the one whose footprint box (grown a little) holds it, else the nearest."""
        def dist(bb):
            return math.hypot(max(bb[0] - x, 0, x - bb[2]), max(bb[1] - y, 0, y - bb[3]))
        return min(boxes, key=lambda r: dist(boxes[r]))

    plans = {}
    runs = []
    fixed_mm = {}
    kept_escapes = []  # (layer id, polyline, half-width): fixed copper for the planner
    skipped = 0
    for name, d in plan.items():
        pos = {label: (x, y) for (label, x, y) in d["pads"]}
        links = []
        fixed_mm[name] = 0.0
        for (a, b, layer, L, points) in d["links"]:
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
            link = (xy[0][0], xy[0][1], xy[1][0], xy[1][1], layer)
            is_pad = [lab in pos for lab in (a, b)]
            escape = layer == "F.Cu" and any(is_pad) and L < escape_mm
            if use_planner and not escape:
                allowed = set(bus_layers)
                for lab, p in zip((a, b), is_pad):
                    if p:
                        allowed &= pad_layers(lab, name)
                group = (bus_design.classify(name)[0], tuple(sorted((package_at(*xy[0]), package_at(*xy[1])))))
                runs.append(planr.Run(name, xy[0], xy[1], tuple(sorted(allowed)) or bus_layers,
                                      tag=(name, len(links), layer_ids[layer], points), group=group))
                links.append(link)  # layer and band filled in by the planner below
            else:
                fixed_mm[name] += L
                kept_escapes.append((layer_ids[layer], points, rules_bus.track_mm / 2, name))
                links.append(link + ((points, band_mm),) if band_mm > 0 else link)
        plans[name] = links
    print(f"   plan: {added} vias placed, {sum(len(v) for v in plans.values())} links over {len(plans)} nets, "
          f"{skipped} links without a terminal" + (f", searches within {band_mm} mm of the reference's routes" if band_mm else ""), flush=True)
    if use_planner:
        boxes = [kb.package_info(kb.footprint(board, r)).bbox_mm for r in ref.bus_parts]
        m = rules_bus.margin_mm
        region = (min(b[0] for b in boxes) - m, min(b[1] for b in boxes) - m, max(b[2] for b in boxes) + m, max(b[3] for b in boxes) + m)
        groups = []
        lanes_of, pairs_of = {}, {}
        for n in bus:
            g, role, pair = bus_design.classify(n)
            if g in reference["groups"] and g != "reset":
                lanes_of.setdefault(g, []).append(n)
            if pair:
                pairs_of.setdefault(pair, []).append(n)
        for g, members in lanes_of.items():
            groups.append((members, reference["groups"][g]["total_length_mm"]["spread"]))
        for members in pairs_of.values():
            if len(members) == 2:
                groups.append((members, 0.2))
        pcosts = planr.PlanCosts(layer_bias={pcbnew.F_Cu: float(os.environ.get("PLAN_TOP_BIAS", "0.1"))})
        for item in filter(None, os.environ.get("PLAN_COSTS", "").split(",")):
            key, value = item.split("=")
            current = getattr(pcosts, key.strip())
            setattr(pcosts, key.strip(), type(current)(float(value)) if isinstance(current, int) else float(value))
        print(f"   planner: {len(runs)} runs over {len(set(r.net for r in runs))} nets, "
              f"{sum(len(v) for v in plans.values()) - len(runs)} escapes kept from the reference, "
              f"{len(groups)} length groups, region {tuple(round(v, 1) for v in region)}", flush=True)
        t0 = time.time()
        stats = planr.plan_runs(board, region, list(bus_layers), rules_bus.track_mm, rules_bus.clearance_mm, runs,
                                groups=groups, fixed_mm=fixed_mm, costs=pcosts, trace=lambda s: print(s, flush=True),
                                extra=kept_escapes, grid_mm=min(l.pitch for l in parts.values()) / 4)
        cells = stats["cells_obj"]
        last = stats.get("pass2", stats["pass1"])
        agree = sum(1 for r in runs if r.layer == r.tag[2])
        confusion = Counter((board.GetLayerName(r.tag[2]), board.GetLayerName(r.layer) if r.layer is not None else "-") for r in runs)
        print(f"   planner: {last['rounds']} rounds, {last['unrouted']} runs unrouted, {last['contested']} runs contested: "
              f"{last['overflow']} boundaries over capacity, {len(last['crossings'])} crossings | {time.time() - t0:.1f}s", flush=True)
        for a, b, L, (x, y) in last["crossings"]:
            print(f"      CROSSING {runs[a].net.split('/')[-1]}/{runs[a].tag[1]} x {runs[b].net.split('/')[-1]}/{runs[b].tag[1]} "
                  f"on {board.GetLayerName(L)} at ({x:.1f}, {y:.1f})")
        print(f"   planner: layer as the reference's on {agree}/{len(runs)} runs; reference -> planner: "
              + ", ".join(f"{a}->{b} {n}" for (a, b), n in sorted(confusion.items(), key=lambda kv: -kv[1])), flush=True)
        for r in runs:
            if r.layer is None:
                caps = {board.GetLayerName(L): [sum(cells.capacity(L, k) for k in cells.boundaries_of(cells.cell_of(*t))) for t in (r.a, r.b)]
                        for L in r.layers}
                print(f"      UNROUTED {r.net.split('/')[-1]} link {r.tag[1]}: no path on {[board.GetLayerName(L) for L in r.layers]} "
                      f"from {tuple(round(v, 2) for v in r.a)} to {tuple(round(v, 2) for v in r.b)}; capacity around the terminals {caps}")
        if last["contested_runs"]:
            print("      over capacity: " + ", ".join(f"{runs[k].net.split('/')[-1]}/{runs[k].tag[1]} wants {runs[k].units}"
                                                      for k in last["contested_runs"]), flush=True)
            print("      worst boundaries: " + ", ".join(f"{board.GetLayerName(L)} ({x}, {y}) over by {o} of {cap}"
                                                         for (L, x, y, o, cap) in last["spots"]), flush=True)
        by_group = Counter()
        for r in runs:
            if r.layer is not None:
                by_group[(r.group, board.GetLayerName(r.layer))] += 1
        bundles = {}
        for (g, lname), n in by_group.items():
            bundles.setdefault(g, []).append(f"{lname} {n}")
        print("      bundles: " + "; ".join(f"{g[0]} {'-'.join(g[1])}: {', '.join(sorted(v))}" for g, v in sorted(bundles.items())), flush=True)
        # the planned lengths per group against the reference's
        planned = dict(fixed_mm)
        for r in runs:
            planned[r.net] += r.length_mm
        for g, members in sorted(lanes_of.items()):
            vals = sorted((planned[n], n.split("/")[-1]) for n in members)
            print(f"      planned {g}: {vals[0][0]:.1f} to {vals[-1][0]:.1f} mm (spread {vals[-1][0] - vals[0][0]:.1f}, reference "
                  f"{reference['groups'][g]['total_length_mm']['min']} to {reference['groups'][g]['total_length_mm']['max']}): "
                  + ", ".join(f"{n} {v:.1f}" for v, n in vals))
        for r in runs:
            if r.layer is None:
                continue
            name, idx, _, _ = r.tag
            link = plans[name][idx]
            plans[name][idx] = link[:4] + (r.layer, r.guide(cells))
        # runs without a path keep the reference's layer and route
        for r in runs:
            if r.layer is None:
                name, idx, _, points = r.tag
                link = plans[name][idx]
                plans[name][idx] = link[:5] + ((points, band_mm),) if band_mm > 0 else link[:5]
        if os.environ.get("REPLAY_PLAN_ONLY") == "1":
            return {"planner": stats}
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
