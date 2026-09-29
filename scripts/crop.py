#!/usr/bin/env python3
"""Micro-boards cut out of a real board round a failure (D147): the failure alone, in seconds instead of the
board's hour.

    python3 scripts/crop.py cut <board.kicad_pcb> <x> <y> <half> <out.kicad_pcb> [--edge]
    python3 scripts/crop.py route <key> <x> <y> <half> [a|b]

`cut` keeps every footprint, track, via, zone and drawing whose bounding box meets the square of side 2 x half
round (x, y), in mm, and draws the outline round what it kept, 0.5 mm out (with --edge it keeps the board's own
outline where it meets the square instead, for a failure at the edge): a footprint half in the square comes whole. `route` cuts the gate's stripped board of <key> the same way and routes it with Freerouting under the class's
configuration (b when not named), the nets with two or more pads left in it; the work goes to
build/fr/<key>-crop/. A crop the router cannot finish locates a real blocker at that spot (a translation fault, a
missing constraint, a pad it cannot reach); a crop it finishes proves less, the congestion round it being gone.
"""
import sys
import time

import pcbnew

import _path  # noqa: F401
from waffle_eda.kicad import board as kb


def cut(board, x: float, y: float, half: float, keep_edge: bool = False) -> pcbnew.BOARD:
    """Cut ``board`` in place down to what meets the square round (x, y); returns it. ``keep_edge`` keeps the
    board's own outline where it meets the square instead of drawing one, for a failure at the edge."""
    window = pcbnew.BOX2I(pcbnew.VECTOR2I(kb.nm(x - half), kb.nm(y - half)),
                          pcbnew.VECTOR2I(kb.nm(2 * half), kb.nm(2 * half)))
    kept = pcbnew.BOX2I(window.GetPosition(), window.GetSize())
    for fp in list(board.GetFootprints()):
        bb = fp.GetBoundingBox(False)
        if window.Intersects(bb):
            kept.Merge(bb)
        else:
            board.Delete(fp)
    for t in list(board.GetTracks()):
        if window.Intersects(t.GetBoundingBox()):
            kept.Merge(t.GetBoundingBox())
        else:
            board.Delete(t)
    for z in list(board.Zones()):
        if not window.Intersects(z.GetBoundingBox()):
            board.Delete(z)
    for d in list(board.GetDrawings()):
        if (d.GetLayer() == pcbnew.Edge_Cuts and not keep_edge) or not window.Intersects(d.GetBoundingBox()):
            board.Delete(d)
    if keep_edge:
        return board
    kept.Inflate(kb.nm(0.5))
    edge = pcbnew.PCB_SHAPE(board)
    edge.SetShape(pcbnew.SHAPE_T_RECT)
    edge.SetStart(kept.GetPosition())
    edge.SetEnd(kept.GetEnd())
    edge.SetLayer(pcbnew.Edge_Cuts)
    edge.SetWidth(kb.nm(0.05))
    board.Add(edge)
    return board


def route(key: str, x: float, y: float, half: float, klass: str = "b") -> int:
    import gate
    from waffle_eda.bench import rebuild, references as refs
    from waffle_eda.route import freerouting as fr
    ref = refs.REFERENCES[key]
    cfg = gate.configuration(gate.CLASS_B if klass == "b" else gate.CLASS_A)
    bare, info = rebuild.strip_all(ref)
    rules = rebuild.measure_rules(ref)
    board = cut(kb.load_board(bare), x, y, half)
    planes, pours = gate.plane_split(board, info["pours"], cfg["planes"])
    outer = {kb.copper_layers(board)[0][1], kb.copper_layers(board)[-1][1]}
    plane_nets = {p["net"] for p in info["pours"] if p["layer"] not in outer} if cfg["feeds"] else None
    extra = {}
    if "plane_type" in cfg:
        extra = {"plane_type": cfg["plane_type"], "jar_name": cfg["jar"], "via_costs": cfg["via_costs"],
                 "plane_via_costs": cfg["plane_via_costs"], "ripup_costs": cfg["ripup_costs"],
                 "via_bands": cfg["via_bands"], "slack_mm": cfg["slack_mm"], "ring_per_axis": cfg["ring_per_axis"],
                 "via_at_smd": cfg["via_at_smd"],
                 "layer_trace_costs": {p["layer"]: cfg["layer_costs"] for p in planes} if planes else None}
    before = kb.open_nets(board)
    work = refs.repo_root() / "build" / "fr" / f"{key}-crop"
    t0 = time.time()
    result = fr.route_board(board, rules, work, pours=pours, planes=planes, feeds=plane_nets, stubs=cfg["stubs"],
                            gui=False, feeds_mode=cfg["feeds_mode"], via_in_pad=cfg["via_in_pad"],
                            pour_pins_rule=cfg["pour_pins"], timeout_s=cfg.get("timeout_s", 1200.0), **extra)
    out = work / "routed.kicad_pcb"
    kb.save_board(board, out)
    from waffle_eda.kicad import refill
    refill.refill_file(out)
    left = kb.open_nets(kb.load_board(out))
    print(f"{key} cropped round ({x}, {y}) +-{half} mm: {len(before)} nets to route, {len(left)} left open after "
          f"{time.time() - t0:.0f} s; {result.summary()}")
    for net, pieces in sorted(left.items()):
        print(f"  open {net}: {pieces} pieces")
    return 0 if not left else 1


def main(argv: list[str]) -> int:
    if len(argv) >= 6 and argv[0] == "cut":
        board = cut(kb.load_board(argv[1]), float(argv[2]), float(argv[3]), float(argv[4]), keep_edge="--edge" in argv)
        kb.save_board(board, argv[5])
        print(f"{argv[5]}: {len(list(board.GetFootprints()))} footprints, {len(list(board.GetTracks()))} tracks and "
              f"vias, {len(list(board.Zones()))} zones")
        return 0
    if len(argv) >= 5 and argv[0] == "route":
        return route(argv[1], float(argv[2]), float(argv[3]), float(argv[4]), argv[5] if len(argv) > 5 else "b")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    sys.exit(main(sys.argv[1:]))
