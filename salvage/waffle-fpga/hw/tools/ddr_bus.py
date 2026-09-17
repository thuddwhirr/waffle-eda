#!/usr/bin/env python3
"""DDR3 bus router (D59), the pattern of the reference layouts: layer changes only at the dog-bone vias under the two
BGAs, re-ordering of the lines on the ball lattice under the packages, straight lines across the corridor.

Input: a board whose power balls and non-DDR3 signals are escaped (bga_escape.py with SKIP_NETS=DDR3_) and whose plane
vias are placed. Each DDR3 ball gets a dog-bone via at a free diagonal site; from there its line runs on ONE inner layer
along the row and column lines of the ball grid (between the via rows, one track per grid node and layer) to the comb
line outside the package on an "exit row", and then straight to the other chip's exit row on the same layer.

Stage A (z3) chooses layer and exit rows per net: one net per (side, exit row, layer); on each layer the exit rows
keep the same order at both chips (no crossing in the corridor); DQS pairs share a layer and sit on adjacent rows;
small jogs preferred. Stage B routes each net's lattice path on that layer with real copper as obstacles; a net that
finds no path adds a nogood to stage A and the pair is solved again (a few rounds).
Usage: python3 hw/tools/ddr_bus.py [board]   (edits the board in place; DDR_BUS_DEBUG=1 prints per-net results)"""
import os, sys, math, json, heapq, collections, itertools, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); ROOT = os.path.dirname(HW)
BOARD = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else os.path.join(HW, "waffle.kicad_pcb")
mm, tomm = pcbnew.FromMM, pcbnew.ToMM
DEBUG = os.environ.get("DDR_BUS_DEBUG")
LAYERS = [pcbnew.In2_Cu, pcbnew.In5_Cu, pcbnew.B_Cu]
W_BGA, W_IN, W_OUT = mm(0.10), mm(0.13), mm(0.21)               # under the BGA / inner-layer corridor / outer-layer corridor
CLR_BGA, GAP_COR = mm(0.10), mm(0.15)                            # fab minimum under the BGA; reference-layout spacing in the corridor
VIA_D, DRILL = mm(0.45), mm(0.20)
OUT = {"U2": 2, "U1": 4}                                       # comb line, in pitches beyond the last ball column (the FPGA side gets the room for jogs)
JOG = int(os.environ.get("DDR_JOG", "6"))                        # max exit-row offset from the ball row
PAIRS = {"DDR3_DQS_P0": "DDR3_DQS_N0", "DDR3_DQS_P1": "DDR3_DQS_N1", "DDR3_CLK_P": "DDR3_CLK_N"}
CHIPS = {"U2": +1, "U1": -1}                                     # exit direction along x

b = pcbnew.LoadBoard(BOARD); netmap = b.GetNetsByName()
tracks = [t for t in b.GetTracks()]
obstacles = [(t.GetNetname(), t.GetBoundingBox(), t) for t in tracks]
for f in b.GetFootprints():
    for p in f.Pads(): obstacles.append((p.GetNetname(), p.GetBoundingBox(), p))
def collides(net, shape, bbox, layer, clr):
    """other-net copper on `layer` (None = any layer) within clr of shape"""
    for onet, obb, item in obstacles:
        if onet == net or not obb.Intersects(bbox): continue
        if item.Type() == pcbnew.PCB_PAD_T:
            Ls = [pcbnew.F_Cu, pcbnew.B_Cu] if layer is None else [layer]
            if any(item.IsOnLayer(L) and item.GetEffectiveShape(L).Collide(shape, int(clr)) for L in Ls): return True
        elif item.Type() == pcbnew.PCB_VIA_T or layer is None or item.GetLayer() == layer:
            if item.GetEffectiveShape().Collide(shape, int(clr)): return True
    return False
def seg_ok(net, a, c, w, layer, clr):
    s = pcbnew.SHAPE_SEGMENT(a, c, int(w)); bb = pcbnew.BOX2I(); bb.Merge(a); bb.Merge(c); bb.Inflate(int(w + clr)); return not collides(net, s, bb, layer, clr)
def via_ok(net, v, clr):
    r = VIA_D / 2 + clr; bb = pcbnew.BOX2I(pcbnew.VECTOR2I(v.x - int(r), v.y - int(r)), pcbnew.VECTOR2I(int(2 * r), int(2 * r)))
    return not collides(net, pcbnew.SHAPE_CIRCLE(v, int(VIA_D / 2)), bb, None, clr)
def add_track(net, a, c, w, layer):
    t = pcbnew.PCB_TRACK(b); t.SetStart(a); t.SetEnd(c); t.SetWidth(int(w)); t.SetLayer(layer); t.SetNet(net); b.Add(t); obstacles.append((net.GetNetname(), t.GetBoundingBox(), t)); return t
def add_via(net, v):
    via = pcbnew.PCB_VIA(b); via.SetPosition(v); via.SetDrill(int(DRILL)); via.SetWidth(int(VIA_D)); via.SetViaType(pcbnew.VIATYPE_THROUGH)
    via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); via.SetNet(net); b.Add(via); obstacles.append((net.GetNetname(), via.GetBoundingBox(), via)); return via

class Chip:
    def __init__(self, ref, dirx):
        self.ref, self.dirx = ref, dirx
        fp = b.FindFootprintByReference(ref); pads = list(fp.Pads())
        xs = sorted({p.GetPosition().x for p in pads}); ys = sorted({p.GetPosition().y for p in pads})
        self.pitch = min(b2 - a for a, b2 in zip(xs, xs[1:])); self.x0, self.y0 = xs[0], ys[0]
        self.n = round((xs[-1] - xs[0]) / self.pitch) + 1; self.m = round((ys[-1] - ys[0]) / self.pitch) + 1
        self.balls = {}
        for p in pads:
            if p.GetNetname().startswith("DDR3_"): self.balls[p.GetNetname()] = (round((p.GetPosition().x - self.x0) / self.pitch), round((p.GetPosition().y - self.y0) / self.pitch), p)
        self.ring = {n: (self.n - 1 - i if dirx > 0 else i) + 1 for n, (i, j, _) in self.balls.items()}
        out = OUT[ref]; self.comb_i = self.n - 1 + out if dirx > 0 else -out
        self.cols = range(-out, self.n + out)                      # column lines, incl. the free space on both sides
        self.rows = range(-1, self.m + 1)
        self.used_nodes = {L: set() for L in LAYERS}; self.used_sites = set()
        self.node_free = {}; self.edge_free = {}; self.last_shared = []   # caches against the existing copper
    def P(self, i, j): return pcbnew.VECTOR2I(int(self.x0 + i * self.pitch), int(self.y0 + j * self.pitch))
    def free_node(self, net, L, i, j):
        k = (L, i, j)
        if k not in self.node_free:
            p = self.P(i, j); s = pcbnew.SHAPE_CIRCLE(p, int(W_BGA / 2)); bb = pcbnew.BOX2I(pcbnew.VECTOR2I(p.x - int(W_BGA), p.y - int(W_BGA)), pcbnew.VECTOR2I(int(2 * W_BGA), int(2 * W_BGA)))
            self.node_free[k] = not collides(net, s, bb, L, CLR_BGA)
        return self.node_free[k] and (i, j) not in self.used_nodes[L]
    def exit_ok(self, net, L, r):
        """the comb node of row r and the row edges from the last ball column out to it are free on layer L"""
        edge_i = self.n - 1 if self.dirx > 0 else 0
        i = edge_i
        while i != self.comb_i:
            nxt = i + self.dirx
            if not self.free_node(net, L, nxt, r) or not self.free_edge(net, L, (i, r), (nxt, r)): return False
            i = nxt
        return True
    def free_edge(self, net, L, a, c):
        k = (L, min(a, c), max(a, c))
        if k not in self.edge_free: self.edge_free[k] = seg_ok(net, self.P(*a), self.P(*c), W_BGA, L, CLR_BGA)   # existing copper only; DDR3 paths are handled by the negotiation
        return self.edge_free[k]
    def route(self, net, L, exit_row, draw):
        """lattice path from a free diagonal site of the ball to the comb node (comb_i, exit_row) on layer L"""
        i, j, pad = self.balls[net]; netobj = pad.GetNet()
        sites = [(i + 0.5 * self.dirx, j + 0.5), (i + 0.5 * self.dirx, j - 0.5), (i - 0.5 * self.dirx, j + 0.5), (i - 0.5 * self.dirx, j - 0.5)]
        target = (self.comb_i, exit_row)
        best = None
        for si, sj in sites:
            if (si, sj) in self.used_sites: continue
            v = self.P(si, sj)
            if not via_ok(net, v, CLR_BGA) or not seg_ok(net, pad.GetPosition(), v, W_BGA, pcbnew.F_Cu, CLR_BGA): continue
            starts = [(int(si + dx), int(sj + dy)) for dx in (-0.5, 0.5) for dy in (-0.5, 0.5)]
            starts = [s for s in starts if s[0] in self.cols and s[1] in self.rows and self.free_node(net, L, *s) and seg_ok(net, v, self.P(*s), W_BGA, L, CLR_BGA)]
            if not starts: continue
            path = self.dijkstra(net, L, starts, target)
            if path and (best is None or len(path) < len(best[1])): best = ((si, sj), path)
        if not best: return None
        (si, sj), path = best
        if draw:
            v = self.P(si, sj); add_via(netobj, v); add_track(netobj, pad.GetPosition(), v, W_BGA, pcbnew.F_Cu); add_track(netobj, v, self.P(*path[0]), W_BGA, L)
            pts = [path[0]]
            for k in range(1, len(path) - 1):                      # merge collinear runs
                if (path[k][0] - pts[-1][0]) * (path[k + 1][1] - path[k][1]) != (path[k][1] - pts[-1][1]) * (path[k + 1][0] - path[k][0]): pts.append(path[k])
            pts.append(path[-1])
            for a, c in zip(pts, pts[1:]): add_track(netobj, self.P(*a), self.P(*c), W_BGA, L)
        self.used_sites.add((si, sj))
        for nd in path: self.used_nodes[L].add(nd)
        return path
    def negotiate(self, L, jobs, iters=int(os.environ.get("DDR_ITERS", "150"))):
        """PathFinder-style: route every (net, exit_row) of `jobs` on layer L at once; nodes and via sites shared by
        several nets get more expensive each iteration until no sharing remains. Returns {net: (site, path)} or None."""
        starts_of = {}
        for net, exit_row in jobs:
            i, j, pad = self.balls[net]; opts = []
            for si, sj in [(i + 0.5 * self.dirx, j + 0.5), (i + 0.5 * self.dirx, j - 0.5), (i - 0.5 * self.dirx, j + 0.5), (i - 0.5 * self.dirx, j - 0.5)]:
                if (si, sj) in self.used_sites: continue
                v = self.P(si, sj)
                if not via_ok(net, v, CLR_BGA) or not seg_ok(net, pad.GetPosition(), v, W_BGA, pcbnew.F_Cu, CLR_BGA): continue
                nodes = [(int(si + dx), int(sj + dy)) for dx in (-0.5, 0.5) for dy in (-0.5, 0.5)]
                nodes = [q for q in nodes if q[0] in self.cols and q[1] in self.rows and self.free_node(net, L, *q) and seg_ok(net, v, self.P(*q), W_BGA, L, CLR_BGA)]
                if nodes: opts.append(((si, sj), nodes))
            starts_of[net] = opts
        if any(not starts_of[net] for net, _ in jobs):
            if DEBUG: print(f"      {self.ref} {b.GetLayerName(L)}: no free via site for {[net for net, _ in jobs if not starts_of[net]]}", flush=True)
            return None
        hist = collections.Counter(); routes = {}; pfac = 0.5
        for it in range(iters):
            pfac = min(pfac * 1.3, 1e6)                              # PathFinder: the present-sharing penalty grows every iteration
            occ = collections.Counter()
            for net, (site, path) in routes.items():
                occ[("site", site)] += 1
                for q in path: occ[q] += 1
            shared = [k for k, c in occ.items() if c > 1]
            if DEBUG and it % 10 == 0: print(f"      {self.ref} {b.GetLayerName(L)} it {it}: {len(routes)}/{len(jobs)} routed, {len(shared)} shared", flush=True)
            if routes and not shared and len(routes) == len(jobs): return routes
            if it == iters - 1:
                sh = set(shared); self.last_shared = sorted({net for net, (site, path) in routes.items() if ("site", site) in sh or any(q in sh for q in path)})
                if DEBUG: print(f"      {self.ref} {b.GetLayerName(L)}: not converged, {len(shared)} shared nodes among {self.last_shared}", flush=True)
            for k in shared: hist[k] += 1
            for net, exit_row in jobs:
                cur = routes.get(net)
                def cost(k, cur_uses):
                    o = occ[k] - (1 if cur_uses else 0)
                    return (1 + hist[k]) * (1 + pfac * o)
                best = None
                for site, nodes in starts_of[net]:
                    c0 = cost(("site", site), cur and cur[0] == site) - 1
                    path = self.dijkstra(net, L, nodes, (self.comb_i, exit_row), lambda q: cost(q, cur and q in cur[1]), c0)
                    if path and (best is None or path[0] < best[0]): best = (path[0], site, path[1])
                if best is None:
                    if DEBUG: print(f"      {self.ref} {b.GetLayerName(L)}: {net} has no path to exit row {exit_row} (sites {[s_ for s_, _ in starts_of[net]]})", flush=True)
                    return None
                if cur: 
                    occ[("site", cur[0])] -= 1
                    for q in cur[1]: occ[q] -= 1
                routes[net] = (best[1], best[2]); occ[("site", best[1])] += 1
                for q in best[2]: occ[q] += 1
        return None
    def dijkstra(self, net, L, starts, target, node_cost=None, c0=0):
        nc = node_cost or (lambda q: 1)
        dist = {s: c0 + nc(s) for s in starts}; prev = {}; pq = [(dist[s], s) for s in starts]; seen = set()
        while pq:
            d, u = heapq.heappop(pq)
            if u in seen: continue
            seen.add(u)
            if u == target:
                path = [u]
                while path[-1] in prev: path.append(prev[path[-1]])
                return (d, path[::-1]) if node_cost else path[::-1]
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                w = (u[0] + di, u[1] + dj)
                if w[0] not in self.cols or w[1] not in self.rows or w in seen: continue
                if not self.free_node(net, L, *w) or not self.free_edge(net, L, u, w): continue
                if w[0] * self.dirx > self.comb_i * self.dirx: continue
                cost = d + nc(w) + (0 if di * self.dirx > 0 else 0.5)      # prefer moving outward
                if cost < dist.get(w, float('inf')): dist[w] = cost; prev[w] = u; heapq.heappush(pq, (cost, w))
        return None

chips = {ref: Chip(ref, d) for ref, d in CHIPS.items()}
nets = sorted(n for n in chips["U2"].balls if n in chips["U1"].balls)
if os.environ.get("DDR_BUS_DIAG"):
    for ref, ch in chips.items():
        for L in LAYERS:
            free_n = sum(1 for i in ch.cols for j in ch.rows if ch.free_node("DDR3_A0", L, i, j)); tot_n = len(ch.cols) * len(ch.rows)
            free_e = sum(1 for i in ch.cols for j in ch.rows if (i + 1) in ch.cols and ch.free_edge("DDR3_A0", L, (i, j), (i + 1, j)))
            free_v = sum(1 for i in ch.cols for j in ch.rows if (j + 1) in ch.rows and ch.free_edge("DDR3_A0", L, (i, j), (i, j + 1)))
            print(f"  {ref} {b.GetLayerName(L)}: nodes free {free_n}/{tot_n}, row edges free {free_e}, column edges free {free_v}")
        if ref == "U2":
            for L in LAYERS:
                blocked_nodes = [(i, j) for i in ch.cols for j in ch.rows if i >= 5 and not ch.free_node("DDR3_A0", L, i, j)]
                blocked_row_edges = [(i, j) for i in ch.cols for j in ch.rows if i >= 5 and (i + 1) in ch.cols and not ch.free_edge("DDR3_A0", L, (i, j), (i + 1, j))]
                print(f"  U2 {b.GetLayerName(L)} east block: blocked nodes {blocked_nodes}; blocked row edges {blocked_row_edges}")
        # what blocks: list other-net items on inner layers inside the chip's bbox
        bb = b.FindFootprintByReference(ref).GetBoundingBox(); bb.Inflate(pcbnew.FromMM(2))
        items = collections.Counter((b.GetLayerName(t.GetLayer()), t.GetNetname()[:12]) for t in tracks if t.Type() != pcbnew.PCB_VIA_T and t.GetLayer() in LAYERS and bb.Intersects(t.GetBoundingBox()))
        print("  tracks on the inner layers near", ref, ":", items.most_common(8))
    sys.exit(0)
print(f"{len(nets)} DDR3 nets; U2 {chips['U2'].n}x{chips['U2'].m}, U1 {chips['U1'].n}x{chips['U1'].m}", flush=True)

def plan(nogoods, fixed):
    import z3
    o = z3.Solver(); L_of = {}; R = {}; X = {}                    # plain SAT: the optimiser timed out on this model; small jogs come from JOG
    for n in nets:
        L_of[n] = {L: z3.Bool(f"L_{n}_{b.GetLayerName(L)}") for L in LAYERS}
        o.add(z3.PbEq([(v, 1) for v in L_of[n].values()], 1))
        for ref, ch in chips.items():
            j = ch.balls[n][1]; rows = [r for r in ch.rows if abs(r - j) <= (1 if (ref == "U2" and ch.ring[n] <= 3) else JOG)]
            X[(n, ref)] = {r: z3.Bool(f"X_{n}_{ref}_{r}") for r in rows}
            o.add(z3.PbEq([(v, 1) for v in X[(n, ref)].values()], 1))
            R[(n, ref)] = z3.Int(f"R_{n}_{ref}")
            for r, v in X[(n, ref)].items():
                o.add(z3.Implies(v, R[(n, ref)] == r))
                for L in LAYERS:
                    if not ch.exit_ok(n, L, r): o.add(z3.Not(z3.And(v, L_of[n][L])))   # comb row cut by existing copper on that layer
    caps = [int(v) for v in os.environ.get("DDR_LAYER_CAPS", "17,17,17").split(",")]   # In2, In5, B.Cu: row lines past the ball columns carry one net each
    for L, cap in zip(LAYERS, caps): o.add(z3.PbLe([(L_of[n][L], 1) for n in nets], cap))
    for ref in chips:                                              # one net per (side, exit row, layer)
        users = collections.defaultdict(list)
        for n in nets:
            for r, xv in X[(n, ref)].items():
                for L, lv in L_of[n].items(): users[(r, L)].append(z3.And(xv, lv))
        for k, us in users.items():
            if len(us) > 1: o.add(z3.PbLe([(u, 1) for u in us], 1))
    for a, c in itertools.combinations(nets, 2):                   # same layer -> same order at both combs
        for L in LAYERS:
            same = z3.And(L_of[a][L], L_of[c][L])
            o.add(z3.Implies(same, (R[(a, "U2")] < R[(c, "U2")]) == (R[(a, "U1")] < R[(c, "U1")])))
            # on a planar lattice two nets of the same ring cannot swap their row order (neither can cross the other's row
            # before it starts); nets of different rings can, the deeper one jogging before the shallower one's column
            for ref, ch in chips.items():
                if ch.ring[a] == ch.ring[c] and ch.balls[a][1] != ch.balls[c][1]:
                    o.add(z3.Implies(same, (R[(a, ref)] < R[(c, ref)]) == (ch.balls[a][1] < ch.balls[c][1])))
    sel = os.environ.get("DDR_PAIRS")                              # e.g. DDR_PAIRS=DDR3_DQS_P0,DDR3_CLK_P restricts the pair rules to those
    for a, c in ([] if os.environ.get("DDR_NO_PAIRS") else [(a, c) for a, c in PAIRS.items() if not sel or a in sel.split(",")]):
        if a in L_of and c in L_of:
            if a != "DDR3_CLK_P":                                   # CK: balls in the same ring at both chips in opposite order, so
                for L in LAYERS: o.add(L_of[a][L] == L_of[c][L])   # the halves cannot share a layer without crossing (practice 18)
            for ref in chips:
                adj = z3.Or(R[(a, ref)] - R[(c, ref)] == 1, R[(c, ref)] - R[(a, ref)] == 1)
                if a != "DDR3_CLK_P" and os.environ.get("DDR_PAIR_ADJ", "1") == "1": o.add(adj)   # DQS halves on adjacent rows; the CK halves may sit apart (D59, practice 18)
    for n, ref, r, L in nogoods:
        if r in X[(n, ref)]: o.add(z3.Not(z3.And(X[(n, ref)][r], L_of[n][L])))
    for n, (L, rows) in fixed.items():                            # converged layers stay as they are
        o.add(L_of[n][L])
        for ref, r in rows.items(): o.add(X[(n, ref)][r])
    o.set("timeout", int(os.environ.get("DDR_Z3_MS", "300000")))
    r = o.check()
    if r != z3.sat: print(f"   stage A {r} with JOG {JOG}, pairs {not os.environ.get('DDR_NO_PAIRS')}"); return None
    m = o.model(); out = {}
    for n in nets:
        L = next(L for L, v in L_of[n].items() if z3.is_true(m.eval(v, model_completion=True)))
        out[n] = (L, {ref: next(r for r, v in X[(n, ref)].items() if z3.is_true(m.eval(v, model_completion=True))) for ref in chips})
    return out

nogoods = []; result = None; final_routes = None; fixed = {}; kept_routes = {}
for rnd in range(int(os.environ.get("DDR_ROUNDS", "12"))):
    p = plan(nogoods, fixed)
    if p is None: print("stage A: no plan"); break
    if os.environ.get("DDR_PLAN_ONLY"): print("plan only:", collections.Counter(b.GetLayerName(p[n][0]) for n in nets)); sys.exit(0)
    for ch in chips.values(): ch.used_nodes = {L: set() for L in LAYERS}; ch.used_sites = set()
    for (n, ref), (site, path) in kept_routes.items(): chips[ref].used_sites.add(site)      # vias are through-all: a site serves one net whatever its layer
    routes = dict(kept_routes); failed_layers = set(); new_nogoods = []
    for L in LAYERS:
        if all(n in fixed for n in nets if p[n][0] == L): continue   # this layer is frozen and already routed
        ok = True; layer_routes = {}
        for ref, ch in chips.items():
            jobs = [(n, p[n][1][ref]) for n in nets if p[n][0] == L]
            r = ch.negotiate(L, jobs)
            if r is None:
                ok = False; failed_layers.add(L)
                for n in (ch.last_shared or [n for n, _ in jobs])[:2]: new_nogoods.append((n, ref, p[n][1][ref], L))
                break
            for n, (site, path) in r.items(): layer_routes[(n, ref)] = (site, path)
        if ok:
            routes.update(layer_routes); kept_routes.update(layer_routes)
            for (n, ref), (site, path) in layer_routes.items(): chips[ref].used_sites.add(site)
            for n in nets:
                if p[n][0] == L: fixed[n] = p[n]
    perL = collections.Counter(b.GetLayerName(p[n][0]) for n in nets)
    print(f"round {rnd + 1}: plan {dict(perL)}, frozen nets {len(fixed)}, failed layers {[b.GetLayerName(L) for L in failed_layers]}" + (f", nogoods +{len(new_nogoods)}" if new_nogoods else ""), flush=True)
    if not failed_layers: result = p; final_routes = routes; break
    nogoods += new_nogoods
leftover = []
if result is None:
    # draw the layers that converged, leave the rest to the fallback (escapes + autorouter at the loosened spacing)
    if not fixed: print("no complete plan; nothing drawn"); sys.exit(1)
    result = {n: fixed[n] for n in fixed}; final_routes = {k: v for k, v in kept_routes.items() if k[0] in fixed}
    leftover = [n for n in nets if n not in fixed]; nets = [n for n in nets if n in fixed]
    print(f"partial: drawing {len(nets)} nets of the converged layers; leftover {len(leftover)}: {leftover}")
open(os.path.join(ROOT, "build", "ddr_leftover.txt"), "w").write("\n".join(leftover))
# draw the negotiated lattice paths, then the corridor lines
ends = {}
for (n, ref), (site, path) in final_routes.items():
    ch = chips[ref]; L = result[n][0]; i, j, pad = ch.balls[n]; netobj = pad.GetNet()
    v = ch.P(*site); add_via(netobj, v); add_track(netobj, pad.GetPosition(), v, W_BGA, pcbnew.F_Cu); add_track(netobj, v, ch.P(*path[0]), W_BGA, L)
    pts = [path[0]]
    for k in range(1, len(path) - 1):
        if (path[k][0] - pts[-1][0]) * (path[k + 1][1] - path[k][1]) != (path[k][1] - pts[-1][1]) * (path[k + 1][0] - path[k][0]): pts.append(path[k])
    pts.append(path[-1])
    for a, c in zip(pts, pts[1:]): add_track(netobj, ch.P(*a), ch.P(*c), W_BGA, L)
    ends[(n, ref)] = ch.P(*path[-1])
order = nets
drawn = 0; blocked = []
for n in order:
    L = result[n][0]
    if (n, "U2") not in ends or (n, "U1") not in ends: continue
    a, c = ends[(n, "U2")], ends[(n, "U1")]; w = W_OUT if L == pcbnew.B_Cu else W_IN
    if seg_ok(n, a, c, w, L, GAP_COR): add_track(netmap[n], a, c, w, L); drawn += 1
    else: blocked.append(n)
byL = collections.Counter(b.GetLayerName(result[n][0]) for n in nets)
print(f"corridor lines drawn {drawn} of {len(nets)} ({dict(byL)}); blocked: {blocked}")
pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b); print("saved", BOARD)
