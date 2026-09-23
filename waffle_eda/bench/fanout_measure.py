"""Measure how a reference board escapes the bus balls of its packages: the evidence for the fan-out rules (M2).

For every bus net and each package it lands on: the ball's ring (1 = outermost row or column), the nearest via of the
net relative to the ball in pitch units and its class (in-pad, diagonal gap, channel between two balls, farther out,
or none), the layers the net's copper uses inside the package, and the side of the package where the net leaves.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from waffle_eda.bench import references as refs
from waffle_eda.kicad import board as kb


def lattice(fp) -> dict:
    """Pad centres, pitch and grid indices of a BGA footprint."""
    pads = {}
    for p in fp.Pads():
        pos = p.GetPosition()
        pads[p.GetNumber()] = (kb.mm(pos.x), kb.mm(pos.y), p.GetNetname(), kb.mm(p.GetSize().x))
    xs = sorted(set(round(x, 3) for x, _, _, _ in pads.values()))
    ys = sorted(set(round(y, 3) for _, y, _, _ in pads.values()))
    pitch = statistics.median([b - a for a, b in zip(xs, xs[1:])] + [b - a for a, b in zip(ys, ys[1:])])
    x0, y0 = xs[0], ys[0]
    ncols = round((xs[-1] - x0) / pitch) + 1
    nrows = round((ys[-1] - y0) / pitch) + 1
    grid = {}
    for number, (x, y, net, size) in pads.items():
        c = round((x - x0) / pitch)
        r = round((y - y0) / pitch)
        ring = 1 + min(r, c, nrows - 1 - r, ncols - 1 - c)
        grid[number] = {"x": x, "y": y, "net": net, "col": c, "row": r, "ring": ring, "pad_mm": size}
    return {"pitch": round(pitch, 3), "rows": nrows, "cols": ncols, "x0": x0, "y0": y0,
            "x1": xs[-1], "y1": ys[-1], "pads": grid}


def classify_offset(dx: float, dy: float) -> str:
    ax, ay = abs(dx), abs(dy)
    if ax < 0.25 and ay < 0.25:
        return "in-pad"
    if 0.25 <= ax <= 0.75 and 0.25 <= ay <= 0.75:
        return "diagonal"
    if (ax < 0.25 and 0.25 <= ay <= 0.75) or (ay < 0.25 and 0.25 <= ax <= 0.75):
        return "channel"
    if ax <= 1.75 and ay <= 1.75:
        return "near"
    return "far"


def measure_fanout(ref: refs.Reference) -> dict:
    board = kb.load_board(refs.board_path(ref))
    bus_nets = kb.nets_matching(board, ref.bus_net_pattern)
    bus = set(bus_nets)
    vias_by_net: dict[str, list] = defaultdict(list)
    tracks_by_net: dict[str, list] = defaultdict(list)
    for item in board.GetTracks():
        name = item.GetNetname()
        if name not in bus:
            continue
        cls = item.GetClass()
        if cls == "PCB_VIA":
            p = item.GetPosition()
            vias_by_net[name].append((kb.mm(p.x), kb.mm(p.y), kb.via_diameter_mm(item), kb.via_drill_mm(item)))
        elif cls in ("PCB_TRACK", "PCB_ARC"):
            s, e = item.GetStart(), item.GetEnd()
            tracks_by_net[name].append((kb.mm(s.x), kb.mm(s.y), kb.mm(e.x), kb.mm(e.y),
                                        board.GetLayerName(item.GetLayer()), kb.mm(item.GetWidth())))
    out = {"reference": ref.key, "packages": {}}
    for part in ref.bus_parts:
        fp = kb.footprint(board, part)
        lat = lattice(fp)
        pitch = lat["pitch"]
        bx0, by0, bx1, by1 = lat["x0"] - pitch / 2, lat["y0"] - pitch / 2, lat["x1"] + pitch / 2, lat["y1"] + pitch / 2
        balls = []
        for number, pad in lat["pads"].items():
            if pad["net"] not in bus:
                continue
            net = pad["net"]
            nearest = None
            for (vx, vy, vd, vdrill) in vias_by_net.get(net, []):
                dx, dy = (vx - pad["x"]) / pitch, (vy - pad["y"]) / pitch
                d = (dx * dx + dy * dy) ** 0.5
                if nearest is None or d < nearest["dist"]:
                    nearest = {"dx": round(dx, 2), "dy": round(dy, 2), "dist": round(d, 2), "dia": vd, "drill": vdrill}
            via_class = classify_offset(nearest["dx"], nearest["dy"]) if nearest else "none"
            layers_inside = Counter()
            widths_inside = Counter()
            exits = Counter()
            for (sx, sy, ex, ey, layer, w) in tracks_by_net.get(net, []):
                inside = lambda x, y: bx0 <= x <= bx1 and by0 <= y <= by1
                if inside(sx, sy) or inside(ex, ey):
                    layers_inside[layer] += 1
                    widths_inside[w] += 1
                for (x, y) in ((sx, sy), (ex, ey)):
                    # an endpoint just outside the ball array: which side did the net leave on
                    if not inside(x, y) and (bx0 - pitch) <= x <= (bx1 + pitch) and (by0 - pitch) <= y <= (by1 + pitch):
                        side = "W" if x < bx0 else "E" if x > bx1 else "N" if y < by0 else "S"
                        exits[side] += 1
            balls.append({
                "ball": number, "net": net, "ring": pad["ring"], "row": pad["row"], "col": pad["col"],
                "via": nearest, "via_class": via_class,
                "layers_inside": dict(layers_inside), "widths_inside": dict(widths_inside),
                "exit_side": exits.most_common(1)[0][0] if exits else None,
            })
        by_ring: dict[int, Counter] = defaultdict(Counter)
        layers_by_ring: dict[int, Counter] = defaultdict(Counter)
        exit_sides = Counter()
        offsets = Counter()
        for b in balls:
            by_ring[b["ring"]][b["via_class"]] += 1
            for layer in b["layers_inside"]:
                layers_by_ring[b["ring"]][layer] += 1
            if b["exit_side"]:
                exit_sides[b["exit_side"]] += 1
            if b["via"]:
                offsets[(abs(b["via"]["dx"]), abs(b["via"]["dy"]))] += 1
        out["packages"][part] = {
            "pitch_mm": pitch, "rows": lat["rows"], "cols": lat["cols"],
            "pad_mm": statistics.median(p["pad_mm"] for p in lat["pads"].values()),
            "bus_balls": len(balls),
            "via_class_by_ring": {r: dict(c) for r, c in sorted(by_ring.items())},
            "layers_by_ring": {r: dict(c.most_common()) for r, c in sorted(layers_by_ring.items())},
            "exit_sides": dict(exit_sides.most_common()),
            "via_offsets_pitch": [[list(k), v] for k, v in offsets.most_common(8)],
            "via_sizes": dict(Counter((b["via"]["dia"], b["via"]["drill"]) for b in balls if b["via"]).most_common(3)).__repr__(),
            "balls": balls,
        }
    return out


def summary(data: dict) -> str:
    lines = [f"== {data['reference']}"]
    for part, p in data["packages"].items():
        lines.append(f"  {part}: {p['rows']}x{p['cols']} balls, pitch {p['pitch_mm']} mm, pad {p['pad_mm']} mm, bus balls {p['bus_balls']}, exit sides {p['exit_sides']}, via sizes {p['via_sizes']}")
        for ring, cls in p["via_class_by_ring"].items():
            lines.append(f"     ring {ring}: vias {cls}  layers {p['layers_by_ring'].get(ring, {})}")
        lines.append(f"     via offsets (|dx|,|dy|) in pitches: {p['via_offsets_pitch']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    keys = sys.argv[1:] or [k for k, r in refs.REFERENCES.items() if r.has_bus and refs.is_fetched(r)]
    for key in keys:
        data = measure_fanout(refs.REFERENCES[key])
        out = refs.repo_root() / "build" / f"fanout-{key}.json"
        out.write_text(json.dumps(data, indent=1))
        print(summary(data))
