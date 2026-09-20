"""Why a reference board needs more than a fab's standard tier: the part, or the layout? (D16, D42)

    python3 scripts/fab_attribution.py butterstick logicbone ulx3s orangecrab-r0.2.1

For each board it reports what the bus demands of a fabricator and, for each demand, where on the board that
demand is actually made: inside a package's ball array, where the pitch leaves no choice, or out in open board,
where the designer had room and chose not to use it. The same question asked of several boards that carry the
same package answers it outright: if one board needs a finer process than another for the same part, the part is
not what is asking for it.

The standard-tier limits are PCBWay's published quick-order numbers as read on 2026-09-18 (D16), and stand here
only as a yardstick every board is held against equally; the vendor landscape is a separate question.
"""
import argparse
import math
import sys
from collections import Counter, defaultdict

import _path  # noqa: F401
from waffle_eda.bench import bus_design as bd, references as refs
from waffle_eda.kicad import board as kb

# PCBWay's standard quick-order tier (D16), as the yardstick
STANDARD = {"track_mm": 0.1, "clearance_mm": 0.1, "drill_mm": 0.2, "ring_mm": 0.15}


def where_of(packages, x, y) -> str:
    """The name of the place a point sits in: a package's array, its hollow, its margin, or open board."""
    for pkg in packages:
        w = pkg.where(x, y)
        if w == "array":
            return f"in {pkg.reference}'s ball array"
        if w == "hollow":
            return f"in {pkg.reference}'s hollow"
        if w == "margin":
            return f"in {pkg.reference}'s margin"
    return "in open board"


def _cells(segments, size):
    grid = defaultdict(list)
    for k, seg in enumerate(segments):
        ax, ay, bx, by = seg[:4]
        for i in range(int(min(ax, bx) / size) - 1, int(max(ax, bx) / size) + 2):
            for j in range(int(min(ay, by) / size) - 1, int(max(ay, by) / size) + 2):
                grid[(i, j)].append(k)
    return grid


def _seg_seg(p, q):
    """Distance between two segments and the midpoint of the closest approach."""
    (ax, ay, bx, by), (cx, cy, dx, dy) = p, q

    def point_seg(px, py, x0, y0, x1, y1):
        vx, vy = x1 - x0, y1 - y0
        L = vx * vx + vy * vy
        t = 0.0 if L < 1e-18 else max(0.0, min(1.0, ((px - x0) * vx + (py - y0) * vy) / L))
        qx, qy = x0 + t * vx, y0 + t * vy
        return math.hypot(px - qx, py - qy), qx, qy

    best = None
    for (px, py, x0, y0, x1, y1) in ((ax, ay, cx, cy, dx, dy), (bx, by, cx, cy, dx, dy),
                                     (cx, cy, ax, ay, bx, by), (dx, dy, ax, ay, bx, by)):
        d, qx, qy = point_seg(px, py, x0, y0, x1, y1)
        if best is None or d < best[0]:
            best = (d, (px + qx) / 2, (py + qy) / 2)
    return best


def measure(key: str) -> dict:
    ref = refs.REFERENCES[key]
    board = kb.load_board(refs.board_path(ref))
    bus = set(kb.nets_matching(board, ref.bus_net_pattern))
    packages = bd.packages_of(board, ref)
    lat = {p.reference: p.lattice for p in packages if p.lattice is not None}

    segments, vias = [], []
    for t in board.GetTracks():
        if t.GetNetname() not in bus:
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            vias.append((round(kb.via_diameter_mm(t), 3), round(kb.via_drill_mm(t), 3),
                         kb.mm(p.x), kb.mm(p.y)))
            continue
        a, b = t.GetStart(), t.GetEnd()
        segments.append((kb.mm(a.x), kb.mm(a.y), kb.mm(b.x), kb.mm(b.y), t.GetLayer(), t.GetNetname(),
                         round(kb.mm(t.GetWidth()), 3)))

    # where the thinnest tracks are
    thinnest = min(seg[6] for seg in segments)
    thin_where = Counter(where_of(packages, (seg[0] + seg[2]) / 2, (seg[1] + seg[3]) / 2)
                         for seg in segments if seg[6] <= thinnest + 1e-6)

    # where the bus runs closest to itself, edge to edge, by a spatial hash so this stays a measurement and not
    # an afternoon: only segments sharing a cell of the grid are ever compared
    grid = _cells(segments, 1.0)
    edge_gap = None
    tight = Counter()
    seen = set()
    for bucket in grid.values():
        for n, i in enumerate(bucket):
            for j in bucket[n + 1:]:
                key2 = (i, j) if i < j else (j, i)
                if key2 in seen:
                    continue
                seen.add(key2)
                if segments[i][4] != segments[j][4] or segments[i][5] == segments[j][5]:
                    continue
                d, mx, my = _seg_seg(segments[i][:4], segments[j][:4])
                g = d - segments[i][6] / 2 - segments[j][6] / 2
                if edge_gap is None or g < edge_gap[0]:
                    edge_gap = (g, mx, my)
                if g < STANDARD["clearance_mm"] - 1e-6:
                    tight[where_of(packages, mx, my)] += 1

    ring = {}
    for (dia, drill, x, y) in vias:
        ring.setdefault((dia, drill), Counter())[where_of(packages, x, y)] += 1

    fp = kb.footprint(board, ref.bus_parts[0])
    info = kb.package_info(fp)
    lat0 = lat.get(ref.bus_parts[0])
    style = bd.escape_style(board, ref)
    return {
        "key": key,
        "controller": ref.bus_parts[0],
        "pitch_mm": lat0.pitch if lat0 else None,
        "balls": len(lat0.balls) if lat0 else None,
        "pad_mm": round(lat0.pad_mm, 3) if lat0 else None,
        "style": style.get(ref.bus_parts[0], {}).get("places", {}),
        "thinnest_track_mm": thinnest,
        "thin_where": dict(thin_where.most_common()),
        "closest_edge_mm": round(edge_gap[0], 4) if edge_gap else None,
        "closest_where": where_of(packages, edge_gap[1], edge_gap[2]) if edge_gap else None,
        "tight_where": dict(tight.most_common()),
        "vias": {f"{d}/{k}": dict(c.most_common()) for (d, k), c in sorted(ring.items())},
        "layers": board.GetCopperLayerCount(),
    }


def corner_room(pitch: float, pad: float) -> float:
    """How much copper-free radius the diagonal gap between four balls offers: the room a dog-bone via has."""
    return pitch * math.sqrt(2) / 2 - pad / 2


def report(rows: list) -> None:
    print()
    print("What each board's bus asks of a fabricator, and where it asks it")
    print()
    for r in rows:
        print(f"== {r['key']}: {r['controller']}, {r['balls']} balls at {r['pitch_mm']} mm, "
              f"{r['pad_mm']} mm pads, {r['layers']} layers, escape {r['style']}")
        flag = "  (finer than the standard tier)" if r["thinnest_track_mm"] < STANDARD["track_mm"] - 1e-6 else ""
        print(f"   thinnest track {r['thinnest_track_mm']} mm{flag}: " +
              ", ".join(f"{v} of them {k}" for k, v in r["thin_where"].items()))
        flag = "  (closer than the standard tier)" if (r["closest_edge_mm"] or 9) < STANDARD["clearance_mm"] - 1e-6 else ""
        print(f"   closest the bus comes to itself {r['closest_edge_mm']} mm{flag}, {r['closest_where']}")
        if r["tight_where"]:
            print("   every place it is closer than the standard tier allows: " +
                  ", ".join(f"{v} {k}" for k, v in r["tight_where"].items()))
        for size, places in r["vias"].items():
            dia, drill = (float(v) for v in size.split("/"))
            ring = (dia - drill) / 2
            flag = "  (thinner ring than the standard tier)" if ring < STANDARD["ring_mm"] - 1e-6 else ""
            print(f"   via {size} mm, ring {ring:.3f} mm{flag}: " +
                  ", ".join(f"{v} {k}" for k, v in places.items()))
        room = corner_room(r["pitch_mm"], r["pad_mm"])
        biggest = 2 * (room - 0.1)  # a via that clears the four balls by the standard tier's own 0.1 mm
        print(f"   the diagonal gap between four of its balls leaves {room:.3f} mm to the nearest pad edge, so a "
              f"dog-bone via up to {biggest:.2f} mm across fits there with 0.1 mm to spare")
        print()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("keys", nargs="+")
    args = ap.parse_args(argv)
    rows = []
    for key in args.keys:
        ref = refs.REFERENCES[key]
        if not refs.is_fetched(ref):
            print(f"{key} is not fetched", file=sys.stderr)
            continue
        rows.append(measure(key))
    report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
