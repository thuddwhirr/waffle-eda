#!/usr/bin/env python3
"""DDR3 bus plan (D59): one layer per net, no layer change between the two chips.

Between the DRAM (exits east) and the FPGA (DDR3 balls exit west) every net is a straight line on one layer. An inner
escape (dog-bone at the ball's own outward site, then a line on In2/In5/B.Cu) may run on the ball's own row line or the
next one (the two lines beside the site); a ring-1/2 ball may instead leave on F.Cu (ring 1 on its row, ring 2 in a
channel beside it) and then needs one via in the band beside the comb to reach the line's layer, at most one such via
per row and side. This script picks, for every net, the layer, the line row at each chip and the F.Cu use so that no
(side, row, layer) slot is used twice, no two nets of a layer cross, and the halves of a differential pair share a
layer. Backtracking over ~50 nets. Output: build/ddr_layers.json, read by bga_escape.py (forced escapes) and
ddr_lines.py (the straight lines and band vias).
Usage: python3 hw/tools/ddr_plan.py [board.kicad_pcb]   (any board with the parts placed; escapes are not needed)"""
import os, sys, json, itertools, collections, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); ROOT = os.path.dirname(HW)
BOARD = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HW, "waffle.kicad_pcb")
PAIRS = {"DDR3_DQS_P0": "DDR3_DQS_N0", "DDR3_DQS_P1": "DDR3_DQS_N1", "DDR3_CLK_P": "DDR3_CLK_N"}
INNER = ["In2.Cu", "In5.Cu", "B.Cu"]
b = pcbnew.LoadBoard(BOARD); mm = pcbnew.ToMM
def balls(ref):
    fp = b.FindFootprintByReference(ref); out = {}
    for p in fp.Pads():
        if p.GetNetname().startswith("DDR3_"): out[p.GetNetname()] = (mm(p.GetPosition().x), mm(p.GetPosition().y))
    xs = [mm(p.GetPosition().x) for p in fp.Pads()]; return out, min(xs), max(xs)
U1, x1min, _ = balls("U1"); U2, _, x2max = balls("U2")
nets = sorted(n for n in U1 if n in U2)
ring = {n: (round((U1[n][0] - x1min) / 0.8) + 1, round((x2max - U2[n][0]) / 0.8) + 1) for n in nets}   # (at U1 from west, at U2 from east)
row = {n: (round(U1[n][1], 2), round(U2[n][1], 2)) for n in nets}
crossing = {n: set() for n in nets}
for a, c in itertools.combinations(nets, 2):
    if (U2[a][1] - U2[c][1]) * (U1[a][1] - U1[c][1]) < 0: crossing[a].add(c); crossing[c].add(a)
partner = dict(PAIRS); partner.update({v: k for k, v in PAIRS.items()})

# every ball owns the diagonal gap site on its outward side, half a pitch toward the next row (row + 0.4); a dog-bone
# there feeds the line on the ball's own row or the next one. The site half a pitch toward the previous row belongs to
# the ball above; it is free only if that ball leaves on F.Cu (ring 1/2 signal) or is absent. Power balls and non-DDR3
# inner-ring signals always take their own site (they are placed first by bga_escape.py).
def all_balls(ref):
    fp = b.FindFootprintByReference(ref); out = []
    for p in fp.Pads():
        if p.GetNetname() and not p.GetNetname().startswith("unconnected"): out.append((p.GetNetname(), mm(p.GetPosition().x), mm(p.GetPosition().y)))
    return out
plane_nets = {z.GetNetname() for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname()}
blocked = set()                                                     # (side, along_half, y_half) taken by a non-DDR3 signal ball
power = []                                                          # (side, ref, pad, r, y): power balls may use their outward or inward site
pad_of = {}
for side, ref, xedge in (("U1", "U1", x1min), ("U2", "U2", x2max)):
    fp = b.FindFootprintByReference(ref)
    for pd in fp.Pads():
        net = pd.GetNetname()
        if not net or net.startswith("unconnected") or net.startswith("DDR3_"): continue
        x, y = mm(pd.GetPosition().x), mm(pd.GetPosition().y)
        r = round((x - xedge) / 0.8) + 1 if side == "U1" else round((xedge - x) / 0.8) + 1
        if net in plane_nets: power.append((side, ref, pd.GetNumber(), r, round(y, 2)))
        elif r >= 3: blocked.add((side, r - 1.5, round(y + 0.4, 2)))
def site(side, r, y_half): return (side, r - 1.5, round(y_half, 2))
def options(n):
    """(layer, u1, u2); uN = ("I", line_row, site_y) for an inner escape or ("F", stub_row, chan) for F.Cu"""
    y1, y2 = row[n]; r1, r2 = ring[n]
    def inner(y, r, side):
        out = []
        for d, sy in ((0, 0.4), (0.8, 0.4), (0, -0.4), (-0.8, -0.4)):    # own row / next row from the own site; own row / previous row from the site above
            if site(side, r, y + sy) in blocked: continue
            out.append(("I", round(y + d, 2), round(y + sy, 2)))
        return out
    e1 = inner(y1, r1, "U1"); e2 = inner(y2, r2, "U2")
    def fcu(y, r, side):
        if r == 1: return [("F", y, 0)]
        if r in (2, 3): return [("F", y, c) for c in (1, -1) if not any(site(side, k, y + 0.4 * c) in blocked for k in range(1, r + 1))]
        return []
    f1 = fcu(y1, r1, "U1"); f2 = fcu(y2, r2, "U2")
    out = []
    for L in INNER:
        for a in e1:
            for c in e2: out.append((L, a, c))
    for a in f1:
        for c in f2: out.append(("F.Cu", a, c))
    return out
def slots(n, opt):
    L, a, c = opt; out = []
    for side, e, r in (("U1", a, ring[n][0]), ("U2", c, ring[n][1])):
        if e[0] == "I": out += [(side, e[1], L), site(side, r, e[2])]
        else:
            out.append((side, round(e[1] + 0.4 * e[2], 2), "F"))
            if r >= 2: out += [site(side, k, e[1] + 0.4 * e[2]) for k in range(1, r + 1)]   # the channel passes every site out to the edge
    return out
def line_rows(opt):
    L, a, c = opt; return a[1], c[1]
def crosses(opt_a, opt_c):
    ya1, ya2 = line_rows(opt_a); yc1, yc2 = line_rows(opt_c)
    return (ya1 - yc1) * (ya2 - yc2) < 0 or (ya1 == yc1) or (ya2 == yc2)

assign = {}
NO_CROSS = bool(os.environ.get("PLAN_NO_CROSS")); NO_PAIR = bool(os.environ.get("PLAN_NO_PAIR"))
def solve():
    """z3: one Boolean per (net, option); every net picks one; slots unique; crossing nets on different layers; pairs share
    a layer; as few band vias as possible"""
    import z3
    opts = {n: options(n) for n in nets}
    X = {(n, i): z3.Bool(f"{n}#{i}") for n in nets for i in range(len(opts[n]))}
    o = z3.Optimize()
    for n in nets: o.add(z3.PbEq([(X[(n, i)], 1) for i in range(len(opts[n]))], 1))
    by_slot = collections.defaultdict(list)
    for n in nets:
        for i, opt in enumerate(opts[n]):
            for sl in slots(n, opt): by_slot[sl].append(X[(n, i)])
    P = {}
    for side, ref, pad, r, y in power:                                # outward site (r - 1.5) when P, inward (r - 0.5) when not P
        P[(ref, pad)] = z3.Bool(f"P_{ref}_{pad}")
        by_slot[site(side, r, y + 0.4)].append(P[(ref, pad)]); by_slot[(side, r - 0.5, round(y + 0.4, 2))].append(z3.Not(P[(ref, pad)]))
        o.add_soft(P[(ref, pad)], weight=1)                            # prefer the standard outward site
    for sl, xs in by_slot.items():
        if len(xs) > 1: o.add(z3.PbLe([(x, 1) for x in xs], 1))
    global power_inward; power_inward = []
    if not NO_CROSS:
        for a, c in itertools.combinations(nets, 2):
            for i, oa in enumerate(opts[a]):
                for j, oc in enumerate(opts[c]):
                    if oa[0] == oc[0] and crosses(oa, oc): o.add(z3.Not(z3.And(X[(a, i)], X[(c, j)])))
    # the DQS pairs share a layer; the CK pair may not (D59: the CK balls sit in opposite order at the two chips, so the
    # two halves would have to cross; each half runs straight on its own inner layer, length-matched, and the FPGA can
    # invert CK in the ODDR pattern if the pins are ever swapped). Prefer inner layers for CK so both halves are striplines.
    for n in ("DDR3_CLK_P", "DDR3_CLK_N"):
        if n in opts:
            for i, opt in enumerate(opts[n]):
                if opt[0] == "F.Cu": o.add_soft(z3.Not(X[(n, i)]), weight=5)
    if not NO_PAIR:
        for a, c in PAIRS.items():
            if a in opts and c in opts and a != "DDR3_CLK_P":
                for L in INNER + ["F.Cu"]:
                    o.add(z3.Or([X[(a, i)] for i, oa in enumerate(opts[a]) if oa[0] == L] + [z3.BoolVal(False)]) == z3.Or([X[(c, j)] for j, oc in enumerate(opts[c]) if oc[0] == L] + [z3.BoolVal(False)]))
    o.set("timeout", 300000)
    r = o.check()
    if r != z3.sat: return False
    m = o.model()
    for n in nets:
        for i in range(len(opts[n])):
            if z3.is_true(m.eval(X[(n, i)], model_completion=True)): assign[n] = opts[n][i]
    power_inward.extend([list(k) for k, v in P.items() if not z3.is_true(m.eval(v, model_completion=True))])
    return True
power_inward = []
ok = solve()
print(f"{len(nets)} nets; {'solved' if ok else 'NO solution'}")
if ok:
    byL = collections.Counter(v[0] for v in assign.values()); print("layers:", dict(byL))
    def side_out(e, y):
        if e[0] == "F": return {"esc": "F", "chan": e[2]}
        return {"esc": "I", "line_off": round((e[1] - y) / 0.8), "site": 1 if e[2] > y else -1}
    out = {"nets": {n: {"layer": assign[n][0], "U1": side_out(assign[n][1], row[n][0]), "U2": side_out(assign[n][2], row[n][1])} for n in nets},
           "power_inward": power_inward}
    print("power balls dog-boning inward:", len(power_inward))
    json.dump(out, open(os.path.join(ROOT, "build", "ddr_layers.json"), "w"), indent=1); print("wrote build/ddr_layers.json")
