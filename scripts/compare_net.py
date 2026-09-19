"""Compare a reference board's routing of a net with ours, and say what is different.

    python3 scripts/compare_net.py butterstick CKE0 DQ5
    python3 scripts/compare_net.py butterstick --failed --candidate build/bench/butterstick-bus.kicad_pcb

For each net it prints the reference's structure (pads, vias and where they sit, the single-layer runs between
terminals, lengths per layer), then ours from the candidate board, and then the test that answers "why is the
reference not blocked here": the reference's own route is laid over our board and every point of it is checked
against our copper, so the output names the nets of ours that sit in the corridor the reference used, with the
spans where they do. ``--failed`` does this for every bus net our board leaves in pieces.
"""
import argparse
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import _path  # noqa: F401
import pcbnew
from waffle_eda.bench import bus_design, constraints, references as refs
from waffle_eda.kicad import board as kb
from waffle_eda.route import plan as planr
from waffle_eda.route.lattice import Lattice


# --- the copper a net has on a board, and whether it is in one piece -------------------------------------------------
def net_items(board, net: str) -> dict:
    """The net's pads, tracks and vias as geometry, with the lengths per layer."""
    pads, tracks, vias = [], [], []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() == net:
                p = pad.GetPosition()
                size = pad.GetSize()
                pads.append({"label": f"{fp.GetReference()}.{pad.GetNumber()}", "x": kb.mm(p.x), "y": kb.mm(p.y),
                             "r": max(kb.mm(size.x), kb.mm(size.y)) / 2,
                             "layers": frozenset(pad.GetLayerSet().CuStack())})
    for item in board.GetTracks():
        if item.GetNetname() != net:
            continue
        if item.GetClass() == "PCB_VIA":
            p = item.GetPosition()
            vias.append({"x": kb.mm(p.x), "y": kb.mm(p.y), "d": kb.via_diameter_mm(item)})
        else:
            a, b = item.GetStart(), item.GetEnd()
            tracks.append({"ax": kb.mm(a.x), "ay": kb.mm(a.y), "bx": kb.mm(b.x), "by": kb.mm(b.y),
                           "L": item.GetLayer(), "len": kb.mm(item.GetLength()), "w": kb.mm(item.GetWidth())})
    per_layer: Counter = Counter()
    for t in tracks:
        per_layer[board.GetLayerName(t["L"])] += t["len"]
    return {"pads": pads, "tracks": tracks, "vias": vias, "per_layer": per_layer,
            "length_mm": sum(t["len"] for t in tracks)}


def _seg_point(ax, ay, bx, by, x, y) -> float:
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
    return math.hypot(x - (ax + t * dx), y - (ay + t * dy))


def _seg_seg(p, q) -> float:
    """Distance between two segments, enough for a touching test (the crossing case returns 0 by sampling both
    ends against the other segment, which is exact for touching copper and conservative elsewhere)."""
    ax, ay, bx, by = p
    cx, cy, dx_, dy_ = q
    # proper crossing
    def side(x1, y1, x2, y2, x3, y3):
        return (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)
    d1, d2 = side(cx, cy, dx_, dy_, ax, ay), side(cx, cy, dx_, dy_, bx, by)
    d3, d4 = side(ax, ay, bx, by, cx, cy), side(ax, ay, bx, by, dx_, dy_)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(_seg_point(cx, cy, dx_, dy_, ax, ay), _seg_point(cx, cy, dx_, dy_, bx, by),
               _seg_point(ax, ay, bx, by, cx, cy), _seg_point(ax, ay, bx, by, dx_, dy_))


def components(items: dict) -> list:
    """The net's copper split into pieces that touch: the pad labels in each piece. Copper touches where the
    shapes overlap, a T-junction included (a track ending on another track's middle), so this agrees with the
    board's own connectivity rather than with a tidier idea of it."""
    parts = []  # (kind, label, geometry, radius, layers or None for a via)
    for p in items["pads"]:
        parts.append(("pad", p["label"], (p["x"], p["y"]), p["r"], p["layers"]))
    for v in items["vias"]:
        parts.append(("via", None, (v["x"], v["y"]), v["d"] / 2, None))  # a via reaches every layer
    for t in items["tracks"]:
        parts.append(("track", None, (t["ax"], t["ay"], t["bx"], t["by"]), t["w"] / 2, frozenset({t["L"]})))
    parent = list(range(len(parts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        a, b = find(i), find(j)
        if a != b:
            parent[a] = b

    def distance(p, q) -> float:
        if p[0] == "track" and q[0] == "track":
            return _seg_seg(p[2], q[2])
        if p[0] == "track":
            return _seg_point(*p[2], *q[2])
        if q[0] == "track":
            return _seg_point(*q[2], *p[2])
        return math.hypot(p[2][0] - q[2][0], p[2][1] - q[2][1])

    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            li, lj = parts[i][4], parts[j][4]
            if li is not None and lj is not None and not (li & lj):
                continue
            if distance(parts[i], parts[j]) <= parts[i][3] + parts[j][3] + 0.001:
                union(i, j)
    groups = defaultdict(list)
    for i, part in enumerate(parts):
        groups[find(i)].append(part)
    out = []
    for members in groups.values():
        labels = sorted(m[1] for m in members if m[0] == "pad")
        out.append({"pads": labels, "items": len(members)})
    out.sort(key=lambda g: (-len(g["pads"]), -g["items"]))
    return out


# --- the reference's route laid over our board ------------------------------------------------------------------------
def overlay(fixed: planr.Fixed, links: list, layer_ids: dict, net: str, clearance_r: float, step: float = 0.05) -> dict:
    """Walk the reference's own route for this net over our board's copper. Returns the share of it that is clear,
    the nets of ours in the way with how much of the route each one takes, and the blocked spans."""
    total = 0.0
    blocked = 0.0
    culprits: Counter = Counter()
    spans = []
    for (a, b, layer, length, points) in links:
        L = layer_ids[layer]
        run = None
        for (px, py), (qx, qy) in zip(points, points[1:]):
            d = math.hypot(qx - px, qy - py)
            n = max(1, int(math.ceil(d / step)))
            for k in range(n):  # midpoints: n samples of d/n each, so the walk measures the route's own length
                x, y = px + (qx - px) * (k + 0.5) / n, py + (qy - py) * (k + 0.5) / n
                total += d / n
                hits = fixed.hits(L, x, y, clearance_r, skip=net)
                if hits:
                    blocked += d / n
                    for (other, kind) in set(hits):
                        culprits[(bus_design.short_name(other) if "/" in other or other else other, kind)] += 1
                    if run is None:
                        run = {"layer": layer, "x0": x, "y0": y, "x1": x, "y1": y, "mm": 0.0, "who": Counter()}
                    run["x1"], run["y1"] = x, y
                    run["mm"] += d / n
                    for (other, kind) in set(hits):
                        run["who"][bus_design.short_name(other) if other else "(no net)"] += 1
                elif run is not None:
                    spans.append(run)
                    run = None
        if run is not None:
            spans.append(run)
            run = None
    spans.sort(key=lambda s: -s["mm"])
    return {"total_mm": total, "blocked_mm": blocked, "culprits": culprits, "spans": spans}


def describe_vias(vias, packages) -> Counter:
    where: Counter = Counter()
    for v in vias:
        x, y = (v["x"], v["y"]) if isinstance(v, dict) else (v[0], v[1])
        place = "outside"
        for pkg in packages:
            w = pkg.where(x, y)
            if w:
                place = f"{w} of {pkg.reference}"
                break
        where[place] += 1
    return where


def summary(ref_board, cand, ref, packages) -> None:
    """The two boards side by side at bus level: layers, via placement, package entries, copper by place. This is
    where the structural difference shows, before any single net's route is looked at."""
    a = bus_design.measure_board(ref_board, ref)
    b = bus_design.measure_board(cand, ref)

    def row(label, left, right):
        print(f"   {label:<34} reference {left:<44} ours {right}")

    def counts(d, keys=None):
        items = sorted(d.items(), key=lambda kv: -kv[1] if isinstance(kv[1], (int, float)) else 0)
        return ", ".join(f"{k} {v:.0f}" if isinstance(v, float) else f"{k} {v}" for k, v in items[:6]) or "none"

    print("\n== the two boards at bus level")
    ours_st = bus_design.structure(cand, ref)
    ref_st = bus_design.structure(ref_board, ref)
    for line in bus_design.structure_lines(ours_st, ref_st):
        print(f"   {line}")
    for name, style in bus_design.escape_style(ref_board, ref).items():
        mine = bus_design.escape_style(cand, ref).get(name, {})
        print(f"   {name} escape style: reference {style['places']}, ours {mine.get('places', {})}")
    row("nets using each layer", counts(a["layers"]["nets_using"]), counts(b["layers"]["nets_using"]))
    row("vias per net", counts(a["vias_per_net"]), counts(b["vias_per_net"]))
    places_a: Counter = Counter()
    places_b: Counter = Counter()
    for nets, acc in ((a["nets"], places_a), (b["nets"], places_b)):
        for n in nets.values():
            for place, k in (n.get("via_places") or {}).items():
                acc[place] += k
    row("where the vias sit", counts(places_a), counts(places_b))
    for pkg in packages:
        r = pkg.reference
        if r not in a["packages"] or r not in b["packages"]:
            continue
        pa, pb = a["packages"][r], b["packages"][r]
        row(f"{r}: copper per layer (mm)",
            counts({k: sum(v.values()) for k, v in _by_layer(pa).items()}),
            counts({k: sum(v.values()) for k, v in _by_layer(pb).items()}))
        row(f"{r}: nets through hollow/array/margin",
            counts(pa.get("nets", {})), counts(pb.get("nets", {})))
        row(f"{r}: entries per side", counts(pa.get("entries", {})), counts(pb.get("entries", {})))


def _by_layer(pkg: dict) -> dict:
    """copper_mm is place -> layer -> mm; invert it to layer -> place -> mm."""
    out: dict = defaultdict(dict)
    for place, layers in (pkg.get("copper_mm") or {}).items():
        for layer, mm in layers.items():
            out[layer][place] = mm
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("key")
    ap.add_argument("nets", nargs="*", help="short names (DQ5) or full net names; empty with --failed")
    ap.add_argument("--candidate", default=None, help="our routed board (default build/bench/<key>-bus.kicad_pcb)")
    ap.add_argument("--failed", action="store_true", help="every bus net our board leaves in more than one piece")
    ap.add_argument("--spans", type=int, default=6, help="blocked spans printed per net")
    ap.add_argument("--summary", action="store_true", help="the two boards side by side at bus level, no per-net detail")
    args = ap.parse_args(argv)

    ref = refs.REFERENCES[args.key]
    c = constraints.measure(ref)
    ref_board = kb.load_board(refs.board_path(ref))
    cand_path = Path(args.candidate or f"build/bench/{args.key}-bus.kicad_pcb")
    if not cand_path.is_file():
        sys.exit(f"no candidate board at {cand_path}")
    cand = kb.load_board(cand_path)
    print(f"== {args.key}: reference {refs.board_path(ref).name} against {cand_path}")

    bus = sorted(kb.nets_matching(ref_board, ref.bus_net_pattern))
    plan = bus_design.reference_plan(ref_board, bus, ref.bus_parts[0])
    layer_ids = {name: lid for lid, name in kb.copper_layers(cand)}
    bus_layers = [layer_ids[n] for n in c.layers if n in layer_ids]
    packages = []
    for r in ref.bus_parts:
        fp = kb.footprint(ref_board, r)
        lat = Lattice(fp)
        packages.append(bus_design.Package(r, kb.package_info(fp), lat if lat.rows >= 4 and lat.cols >= 4 else None))
    boxes = [p.info.bbox_mm for p in packages]
    m = 6.0
    region = (min(b[0] for b in boxes) - m, min(b[1] for b in boxes) - m,
              max(b[2] for b in boxes) + m, max(b[3] for b in boxes) + m)
    fixed = planr.Fixed(cand, region, bus_layers)
    clearance_r = c.min_track_mm / 2 + c.clearance_mm

    if args.summary:
        summary(ref_board, cand, ref, packages)
        if not args.nets and not args.failed:
            return

    by_short = {bus_design.short_name(n): n for n in bus}
    wanted = [by_short.get(n, n) for n in args.nets]
    cand_items = {n: net_items(cand, n) for n in bus}
    cand_parts = {n: components(cand_items[n]) for n in bus}
    if args.failed or not wanted:
        broken = [n for n in bus if len(cand_parts[n]) > 1]
        print(f"   our board leaves {len(broken)} of {len(bus)} bus nets in more than one piece: "
              + ", ".join(bus_design.short_name(n) for n in broken))
        wanted = wanted or broken
    for name in wanted:
        if name not in plan:
            print(f"\n== {name}: not a bus net of this reference")
            continue
        short = bus_design.short_name(name)
        d = plan[name]
        ref_items = net_items(ref_board, name)
        print(f"\n== {short} ({name})")
        print(f"   reference: {ref_items['length_mm']:.1f} mm, {len(d['vias'])} vias "
              f"({', '.join(f'{k} {v}' for k, v in describe_vias(d['vias'], packages).items()) or 'none'}), "
              f"layers " + ", ".join(f"{k} {v:.1f}" for k, v in ref_items["per_layer"].most_common()))
        for (a, b, layer, length, points) in sorted(d["links"], key=lambda t: -t[3]):
            print(f"      run {a} -> {b} on {layer}, {length:.1f} mm")
        ci = cand_items[name]
        parts = cand_parts[name]
        print(f"   ours: {ci['length_mm']:.1f} mm, {len(ci['vias'])} vias "
              f"({', '.join(f'{k} {v}' for k, v in describe_vias(ci['vias'], packages).items()) or 'none'}), "
              f"layers " + ", ".join(f"{k} {v:.1f}" for k, v in ci["per_layer"].most_common()))
        print(f"      {len(parts)} piece(s) of copper: "
              + "; ".join(f"[{', '.join(g['pads']) or 'no pad'}] {g['items']} items" for g in parts))
        ov = overlay(fixed, d["links"], layer_ids, name, clearance_r)
        clear = 100.0 * (1 - ov["blocked_mm"] / ov["total_mm"]) if ov["total_mm"] else 0.0
        print(f"   the reference's own route over our board: {clear:.0f} % of {ov['total_mm']:.1f} mm is clear; "
              f"{ov['blocked_mm']:.1f} mm is taken by our copper")
        who: Counter = Counter()
        for (other, kind), n in ov["culprits"].items():
            who[f"{other} ({kind})"] += n
        if who:
            print("      taken by: " + ", ".join(f"{k} x{v}" for k, v in who.most_common(8)))
        for s in ov["spans"][:args.spans]:
            print(f"      blocked {s['mm']:.2f} mm on {s['layer']} from ({s['x0']:.2f}, {s['y0']:.2f}) to "
                  f"({s['x1']:.2f}, {s['y1']:.2f}): " + ", ".join(k for k, _ in s["who"].most_common(4)))
        # what our board has where the reference put its vias
        for (x, y, dia, drill) in d["vias"]:
            hits: Counter = Counter()
            for L in bus_layers:
                for (other, kind) in fixed.hits(L, x, y, dia / 2 + c.hole_to_copper_mm, skip=name):
                    hits[f"{bus_design.short_name(other) if other else '(no net)'} {kind}"] += 1
            print(f"      the reference's via at ({x:.2f}, {y:.2f}): "
                  + ("ours has " + ", ".join(f"{k}" for k, _ in hits.most_common(5)) if hits else "free on our board"))


if __name__ == "__main__":
    main()
