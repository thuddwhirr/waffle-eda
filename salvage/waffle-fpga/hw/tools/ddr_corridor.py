#!/usr/bin/env python3
"""Deterministic corridor router for the DDR3 group (D57).

The BGA escapes leave the DRAM eastwards and the FPGA westwards as combs of stub ends facing each other across an
empty corridor (gen_pcb CORRIDORS). Every DDR3 net with one free stub end on each side is routed as a Z: along its row
from the DRAM stub end to a column x, vertically along that column to the FPGA row, then along that row to the FPGA
stub end — a layer change (via) at the column corner where the two stubs are on different layers. Columns are 0.3 mm
apart (0.1 mm track, 0.2 mm gap = 3W for the DDR3 group), corners are chamfered, every segment and via is checked
against the real board copper with routing_lib. Differential pairs are routed consecutively in adjacent columns.
Nets that find no Z are listed in build/ddr_leftover.txt for the router stage. Usage: python3 hw/tools/ddr_corridor.py
"""
import os, re, sys, math, collections, pcbnew
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routing_lib import Router, mm, CLR, VIA_R
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); ROOT = os.path.dirname(HW)
BOARD = os.path.join(HW, "waffle.kicad_pcb")
W = mm(0.10); GAP = mm(0.20); WCHK = W + 2 * (GAP - CLR)          # check width that yields a 0.2 mm gap
VCHK = 2 * VIA_R + 2 * (GAP - CLR)                                  # same for vias (as a zero-length segment)
PITCH = mm(0.30); CHAMFER = mm(0.40)
PAIRS = {"DDR3_DQS_P0": "DDR3_DQS_N0", "DDR3_DQS_P1": "DDR3_DQS_N1", "DDR3_CLK_P": "DDR3_CLK_N"}
SPLIT_X = mm(35)                                                    # DRAM side < 35 mm < FPGA side

def free_ends(b):
    cnt = collections.Counter(); anch = set()
    for t in b.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T: anch.add((t.GetNetname(), t.GetPosition().x, t.GetPosition().y)); continue
        for q in (t.GetStart(), t.GetEnd()): cnt[(t.GetNetname(), q.x, q.y, t.GetLayer())] += 1
    for f in b.GetFootprints():
        for p in f.Pads(): anch.add((p.GetNetname(), p.GetPosition().x, p.GetPosition().y))
    ends = collections.defaultdict(list)
    for (n, x, y, l), k in cnt.items():
        if k == 1 and (n, x, y) not in anch: ends[n].append((x, y, l))
    return ends

def main():
    import shutil; shutil.copy(BOARD, os.path.join(ROOT, "build", "precor.kicad_pcb"))     # pre-corridor copy for re-runs
    b = pcbnew.LoadBoard(BOARD); R = Router(b); netmap = b.GetNetsByName()
    region = pcbnew.BOX2I(pcbnew.VECTOR2I(mm(26), mm(64)), pcbnew.VECTOR2I(mm(22), mm(36)))   # x 26..48, y 64..100
    R.obstacles = [o for o in R.obstacles if o[1].Intersects(region)]
    R.holes = [h for h in R.holes if region.Contains(h[0])]
    ends = free_ends(b)
    nets = {}
    for n, e in ends.items():
        if not n.startswith("DDR3_"): continue
        d = [q for q in e if q[0] < SPLIT_X]; f = [q for q in e if q[0] > SPLIT_X]
        if len(d) == 1 and len(f) == 1: nets[n] = (d[0], f[0])
    if not nets: print("no DDR3 nets with a stub end on each side"); return
    XL = max(d[0] for d, f in nets.values()) + mm(0.45); XR = min(f[0] for d, f in nets.values()) - mm(0.45)
    ncol = int((XR - XL) / PITCH) + 1
    columns = [XL + i * PITCH for i in range(ncol)]
    mid = ncol // 2
    col_order = sorted(range(ncol), key=lambda i: abs(i - mid))
    print(f"{len(nets)} DDR3 nets, corridor x {pcbnew.ToMM(XL):.1f}..{pcbnew.ToMM(XR):.1f} mm, {ncol} columns")
    def span(n): return abs(nets[n][0][1] - nets[n][1][1])
    placed = {}                                                    # net -> (column index, vertical layer)
    V = pcbnew.VECTOR2I
    def clear_path(n, segs, vias):
        return all(R.seg_clear(n, a, c, WCHK, L) for a, c, L in segs) and all(R.via_clear(n, v) and R.seg_clear(n, v, v, VCHK, None) for v in vias)
    VIA_OFFS = [mm(v) for v in (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)]    # via distance from a stub end along its row
    def build(n, ci, Lv, xv1, xv2):
        """segments and vias of the Z for net n: vertical on layer Lv at column ci; layer changes at xv1 (DRAM row) / xv2
        (FPGA row) where the stub layer differs from Lv, so the corridor middle stays via-free"""
        (xd, yd, Ld), (xf, yf, Lf) = nets[n]; xc = columns[ci]
        segs = []; vias = []
        dy = yf - yd; s = 1 if dy > 0 else -1
        ch = CHAMFER if abs(dy) > 2 * CHAMFER + mm(0.1) else 0
        x1 = xd
        if Ld != Lv:
            if xv1 is None or xv1 >= xc - ch - mm(0.1): return None
            segs.append((V(xd, yd), V(xv1, yd), Ld)); vias.append(V(xv1, yd)); x1 = xv1
        if ch: segs.append((V(x1, yd), V(xc - ch, yd), Lv)); segs.append((V(xc - ch, yd), V(xc, yd + s * ch), Lv)); y1 = yd + s * ch
        else: segs.append((V(x1, yd), V(xc, yd), Lv)); y1 = yd
        x2 = xf
        if Lf != Lv:
            if xv2 is None or xv2 <= xc + ch + mm(0.1): return None
            segs.append((V(xv2, yf), V(xf, yf), Lf)); vias.append(V(xv2, yf)); x2 = xv2
        if ch: segs.append((V(xc, yf - s * ch), V(xc + ch, yf), Lv)); segs.append((V(xc + ch, yf), V(x2, yf), Lv)); y2 = yf - s * ch
        else: segs.append((V(xc, yf), V(x2, yf), Lv)); y2 = yf
        if abs(y2 - y1) > mm(0.01): segs.append((V(xc, y1), V(xc, y2), Lv))
        return segs, vias
    def via_spot(n, x0, y, L, direction):
        """first clear via position along row y from stub end x0 (direction +1 east / -1 west), with the stub-layer lead"""
        for off in VIA_OFFS:
            v = V(x0 + direction * off, y)
            if R.via_clear(n, v) and R.seg_clear(n, v, v, VCHK, None) and R.seg_clear(n, V(x0, y), v, WCHK, L): return v.x
        return None
    # --- straight-line mode (D57): after ddr_swap.py the DRAM and FPGA orders agree inside every group, so a straight
    # segment per net never crosses another of its group; nets of different groups that would cross go on different
    # layers. A net whose two stubs sit on different layers gets its via in the band beside the comb (via_spot) and the
    # straight run on the other stub's layer. Nets are laid top to bottom by DRAM row; each candidate is checked
    # against the real copper (0.2 mm gap), so a crossing on one layer simply fails over to the next layer. ---------
    LAYERS = [pcbnew.In2_Cu, pcbnew.In5_Cu, pcbnew.B_Cu, pcbnew.F_Cu]
    DEBUG = os.environ.get("CORRIDOR_DEBUG", "")
    def blocker(n, a, c, w, L):
        """first obstacle a segment collides with (for CORRIDOR_DEBUG)"""
        sh = pcbnew.SHAPE_SEGMENT(a, c, int(w)); bb = pcbnew.BOX2I(); bb.Merge(a); bb.Merge(c); bb.Inflate(int(w + CLR))
        for onet, obb, item in R.obstacles:
            if onet == n or not obb.Intersects(bb): continue
            if item.Type() == pcbnew.PCB_PAD_T:
                if (L is None and any(item.IsOnLayer(x) and item.GetEffectiveShape(x).Collide(sh, int(CLR)) for x in [pcbnew.F_Cu, pcbnew.B_Cu])) or (L is not None and item.IsOnLayer(L) and item.GetEffectiveShape(L).Collide(sh, int(CLR))): return f"pad {onet}"
            elif (item.Type() == pcbnew.PCB_VIA_T or L is None or item.IsOnLayer(L)) and item.GetEffectiveShape().Collide(sh, int(CLR)):
                return f"{'via' if item.Type() == pcbnew.PCB_VIA_T else 'trk ' + b.GetLayerName(item.GetLayer())} {onet} @({pcbnew.ToMM(item.GetPosition().x):.1f},{pcbnew.ToMM(item.GetPosition().y):.1f})"
        return None
    XS1 = max(d[0] for d, f in nets.values()) + mm(0.4); XS2 = min(f[0] for d, f in nets.values()) - mm(0.4)
    T_VIA = (0.5, 0.35, 0.65, 0.2, 0.8, 0.12, 0.88, 0.28, 0.72, 0.42, 0.58)     # via position along the diagonal, as a fraction
    # one layer per group (D57, as in the reference layouts): the lanes overlap in y at the FPGA because the two DQS
    # groups interleave there, so lane 0 and lane 1 must not share a layer; inside a group the lines never cross
    GROUP_LAYER = {}
    for i in range(8): GROUP_LAYER[f"DDR3_DQ{i}"] = pcbnew.In2_Cu; GROUP_LAYER[f"DDR3_DQ{i + 8}"] = pcbnew.In5_Cu
    for n_ in ("DDR3_DM0", "DDR3_DQS_P0", "DDR3_DQS_N0"): GROUP_LAYER[n_] = pcbnew.In2_Cu
    for n_ in ("DDR3_DM1", "DDR3_DQS_P1", "DDR3_DQS_N1"): GROUP_LAYER[n_] = pcbnew.In5_Cu
    T1 = (0.08, 0.16, 0.24, 0.32); T2 = (0.92, 0.84, 0.76, 0.68)                 # via positions near the ends, staggered
    BAND = [mm(v) for v in (0.5, 1.4, 2.3, 0.95, 1.85, 2.75)]           # via offsets from a stub end along its row (0.85 mm apart: 0.45 via + 0.2 gap)
    def try_line(n, L):
        """D59: the straight diagonal on the group layer L runs between two points in the via bands beside the combs; a
        stub on another layer gets its via on its own row inside the band (never on the diagonal, where the neighbouring
        lines leave no room), the band vias of different nets stagger along the rows. The corridor middle stays via-free."""
        (xd, yd, Ld), (xf, yf, Lf) = nets[n]
        dbg = DEBUG and re.match(DEBUG, n)
        starts = [(V(xd, yd), [], [])] if Ld == L else [(V(xd + o, yd), [(V(xd, yd), V(xd + o, yd), Ld)], [V(xd + o, yd)]) for o in BAND]
        ends = [(V(xf, yf), [], [])] if Lf == L else [(V(xf - o, yf), [(V(xf - o, yf), V(xf, yf), Lf)], [V(xf - o, yf)]) for o in BAND]
        first_fail = None
        for a, sa, va in starts:
            for c_, sc, vc in ends:
                if c_.x - a.x < mm(1.0): continue
                segs = sa + [(a, c_, L)] + sc; vias = va + vc
                if clear_path(n, segs, vias):
                    net = netmap[n]
                    for p, q, L_ in segs: R.add_track(net, p, q, W, L_)
                    for v in vias: R.add_via(net, v)
                    placed[n] = (None, L); return True
                if first_fail is None: first_fail = (segs, vias)
        if dbg and first_fail:
            for p, q, L_ in first_fail[0]:
                k = blocker(n, p, q, WCHK, L_)
                if k: print(f"  {n}: segment on {b.GetLayerName(L_)} ({pcbnew.ToMM(p.x):.1f},{pcbnew.ToMM(p.y):.1f})-({pcbnew.ToMM(q.x):.1f},{pcbnew.ToMM(q.y):.1f}) blocked by {k}")
            for v in first_fail[1]:
                if not (R.via_clear(n, v) and R.seg_clear(n, v, v, VCHK, None)): print(f"  {n}: via at ({pcbnew.ToMM(v.x):.1f},{pcbnew.ToMM(v.y):.1f}) blocked by {blocker(n, v, v, VCHK, None)}")
        return False
    leftover = []
    order = sorted(nets, key=lambda n: nets[n][0][1])
    done = set()
    for n in order:
        if n in done: continue
        partner = PAIRS.get(n) or next((k for k, v in PAIRS.items() if v == n), None)
        unit = [n] + ([partner] if partner in nets and partner not in done else [])
        for m in unit:
            done.add(m)
            if not try_line(m, GROUP_LAYER.get(m, pcbnew.B_Cu)): leftover.append(m)
    for n in leftover[:]:                                     # second chance on the spare layer, then the other layers
        if any(try_line(n, L) for L in (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In2_Cu, pcbnew.In5_Cu) if L != GROUP_LAYER.get(n, pcbnew.B_Cu)): leftover.remove(n)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b)
    byL = collections.Counter(b.GetLayerName(Lv) for _, Lv in placed.values())
    print(f"routed {len(placed)} of {len(nets)} nets ({dict(byL)} vertical layers); leftover: {leftover}")
    open(os.path.join(ROOT, "build", "ddr_leftover.txt"), "w").write("\n".join(leftover))

if __name__ == "__main__":
    main()
