#!/usr/bin/env python3
"""DDR3 length matching by meander insertion (run after stage-1 routing, before the rest is routed):
- each byte lane: DQ/DM matched to the lane's DQS average within TOL_DQ,
- DQS and CK pairs: N matched to P (and vice versa) within TOL_PAIR,
- address/command/control: matched to the CK average within TOL_AC (only lengthened, never shortened).
A meander replaces part of the longest straight segment of the net with a serpentine of amplitude A; every added
segment is clearance-checked against all other copper on that layer. Usage: python3 hw/tools/ddr3_tune.py"""
import os, sys, re, math, pcbnew
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routing_lib import Router, mm
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); BOARD = os.path.join(HW, "waffle.kicad_pcb")
TOL_DQ, TOL_PAIR, TOL_AC = mm(0.5), mm(0.3), mm(2.0)

b = pcbnew.LoadBoard(BOARD); R = Router(b)
def segs(net): return [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetname() == net]
def length(net): return sum(t.GetLength() for t in segs(net))
names = [str(n) for n in b.GetNetsByName().keys()]

def meander(net, delta):
    """add ~delta of length to net; returns the added length or 0"""
    cands = sorted(segs(net), key=lambda t: -t.GetLength())
    for t in cands[:4]:
        a, c = t.GetStart(), t.GetEnd(); L = t.GetLength(); w = t.GetWidth(); layer = t.GetLayer()
        if L < mm(3): continue
        ux, uy = (c.x - a.x) / L, (c.y - a.y) / L; nx, ny = -uy, ux
        # amplitude / bump-count combinations, closest added length first (a bump adds 2A), so a 0.6 mm shortfall gets a
        # single 0.3 mm bump instead of a 1.6 mm one
        combos = []
        for A in (mm(0.3), mm(0.4), mm(0.5), mm(0.6), mm(0.8), mm(1.2), mm(1.8), mm(2.5)):
            n = max(1, int(math.ceil(delta / (2 * A))))
            combos.append((abs(2 * A * n - delta), A, n))
        for _, A, n in sorted(combos):
            pitch = max(w * 3, mm(0.6))                    # width of one bump leg (3W spacing between legs)
            per_bump = 2 * A
            span = n * 2 * pitch
            if span > L - mm(2): continue
            for sign in (1, -1):
                # build the polyline: start 1 mm into the segment
                s0 = mm(1) + (L - mm(2) - span) / 2
                pts = [a, pcbnew.VECTOR2I(int(a.x + ux * s0), int(a.y + uy * s0))]
                x = s0; out = False
                for i in range(n):
                    p0 = pts[-1]
                    p1 = pcbnew.VECTOR2I(int(p0.x + sign * nx * A), int(p0.y + sign * ny * A))
                    p2 = pcbnew.VECTOR2I(int(p1.x + ux * pitch), int(p1.y + uy * pitch))
                    p3 = pcbnew.VECTOR2I(int(p2.x - sign * nx * A), int(p2.y - sign * ny * A))
                    p4 = pcbnew.VECTOR2I(int(p3.x + ux * pitch), int(p3.y + uy * pitch))
                    pts += [p1, p2, p3, p4]
                pts.append(c)
                ok = all(R.seg_clear(net, pts[i], pts[i + 1], w, layer, skip=(t,)) for i in range(len(pts) - 1))
                if not ok: continue
                if os.environ.get("TUNE_DEBUG"): print("  meander on", net, "seg", pcbnew.ToMM(L), "A", pcbnew.ToMM(A), "n", n, flush=True)
                net_obj = t.GetNet(); uid = t.m_Uuid.AsString()
                R.obstacles = [o for o in R.obstacles if o[2].m_Uuid.AsString() != uid]
                b.Remove(t)
                R.lay(net_obj, pts, w, layer)
                return per_bump * n
    return 0

report = []
def match(net, target, tol, label):
    if os.environ.get("TUNE_DEBUG"): print("match", label, net, flush=True)
    L = length(net)
    if L == 0: report.append(f"{label} {net}: unrouted, skipped"); return
    if L < target - tol:
        got = meander(net, target - L)
        report.append(f"{label} {net}: {pcbnew.ToMM(L):.2f} -> +{pcbnew.ToMM(got):.2f} mm (target {pcbnew.ToMM(target):.2f}){'' if got else '  NO ROOM'}")
    elif L > target + tol:
        report.append(f"{label} {net}: {pcbnew.ToMM(L):.2f} mm is {pcbnew.ToMM(L - target):.2f} over the target -> reroute shorter by hand")
# 1. pairs (DQS0/1, CK): lengthen the shorter half
for base in ("DDR3_DQS_P0/DDR3_DQS_N0", "DDR3_DQS_P1/DDR3_DQS_N1", "DDR3_CLK_P/DDR3_CLK_N"):
    p, n = base.split("/"); lp, ln = length(p), length(n)
    if lp and ln:
        if lp < ln - TOL_PAIR: match(p, ln, TOL_PAIR, "pair")
        elif ln < lp - TOL_PAIR: match(n, lp, TOL_PAIR, "pair")
# 2. byte lanes: DQ/DM to the DQS average (nets longer than that are reported for a manual reroute)
for lane in (0, 1):
    dq = [f"DDR3_DQ{k}" for k in range(8 * lane, 8 * lane + 8)] + [f"DDR3_DM{lane}"]
    dqs = (f"DDR3_DQS_P{lane}", f"DDR3_DQS_N{lane}")
    ref = (length(dqs[0]) + length(dqs[1])) / 2
    for x in dq: match(x, ref, TOL_DQ, f"lane{lane}")
# 3. address/command to CK
ck = (length("DDR3_CLK_P") + length("DDR3_CLK_N")) / 2
ac = [n for n in names if re.match(r"DDR3_(A\d+|BA\d|RAS_N|CAS_N|WE_N|CS_N|CKE|ODT|RESET_N)$", n)]
for x in ac: match(x, ck, TOL_AC, "addr")
pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b)
print("\n".join(report) if report else "nothing to tune")
