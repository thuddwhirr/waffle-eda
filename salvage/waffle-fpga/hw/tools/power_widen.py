#!/usr/bin/env python3
"""Power nets after the autorouter: replace the router's 0.10 mm tracks on the short high-current nets with direct
wide tracks (straight or one bend) where the path is clear, and give the inductor / regulator output pads that
sit on a plane net several vias instead of the single 0.2 mm stub from plane_vias.py.
Usage: python3 hw/tools/power_widen.py   (edits hw/waffle.kicad_pcb in place; re-run after every SES import)"""
import os, math, itertools, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.environ.get("PW_BOARD", os.path.join(HW, "waffle.kicad_pcb"))
mm = pcbnew.FromMM
CLR = mm(0.125); VIA_R = mm(0.45) / 2; DRILL = mm(0.20)
CU = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.In5_Cu, pcbnew.In6_Cu, pcbnew.B_Cu]
WIDE_NETS = ["1V1_SW", "1V35_SW", "3V3_SW", "BUCK5_SW", "VIN", "VBUS_IN", "5V_USB1", "5V_USB2", "5V_USB3", "5V_HDMI"]
MULTI_VIA_REFS = ("L1", "L2", "L3", "L4", "U17", "U18", "U19", "U20", "U21", "U25", "U26", "U27")   # pads of these on plane nets get 3 vias

def main():
    b = pcbnew.LoadBoard(BOARD)
    zones = [z for z in b.Zones() if not z.GetIsRuleArea()]
    plane = {}
    for z in zones: plane.setdefault(z.GetNetname(), []).append(z)
    obstacles = []
    for f in b.GetFootprints():
        for p in f.Pads(): obstacles.append((p.GetNetname(), p.GetBoundingBox(), p))
    for t in b.GetTracks(): obstacles.append((t.GetNetname(), t.GetBoundingBox(), t))
    keepouts = [z for z in b.Zones() if z.GetIsRuleArea() and (z.GetDoNotAllowVias() or z.GetDoNotAllowTracks())]
    for f in b.GetFootprints():
        for z in f.Zones():
            if z.GetIsRuleArea() and (z.GetDoNotAllowVias() or z.GetDoNotAllowTracks()): keepouts.append(z)
    def holes():
        h = [(t.GetPosition(), t.GetDrillValue()) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
        for f in b.GetFootprints():
            for p in f.Pads():
                if p.GetDrillSize().x > 0: h.append((p.GetPosition(), max(p.GetDrillSize().x, p.GetDrillSize().y)))
        return h
    PROTECT = ("DDR3_", "HDMI_", "USB", "HUB_", "ULPI_", "CLK", "I2S", "SD1_", "SD2_", "ESP_SDIO", "FMC_", "JTAG", "FLASH_")
    def rippable(onet, item):
        return item.Type() != pcbnew.PCB_PAD_T and onet not in plane and onet not in WIDE_NETS and not onet.startswith(PROTECT)
    def seg_blockers(net, a, c, w, layer, skip=()):
        """other-net items in the way of a segment; None if a pad or protected copper blocks it"""
        s_ = pcbnew.SHAPE_SEGMENT(a, c, int(w)); bb = pcbnew.BOX2I(); bb.Merge(a); bb.Merge(c); bb.Inflate(int(w + CLR)); out = []
        for onet, obb, item in obstacles:
            if onet == net or item in skip or not obb.Intersects(bb): continue
            hit = False
            if item.Type() == pcbnew.PCB_PAD_T:
                hit = item.IsOnLayer(layer) and item.GetEffectiveShape(layer).Collide(s_, int(CLR))
            elif item.Type() == pcbnew.PCB_VIA_T or item.IsOnLayer(layer):
                hit = item.GetEffectiveShape().Collide(s_, int(CLR))
            if hit:
                if not rippable(onet, item): return None
                out.append(item)
        return out
    ripped = {}
    def rip(items):
        for it in items:
            if it.GetNetname() not in ripped: ripped[it.GetNetname()] = 0
            ripped[it.GetNetname()] += 1; b.Remove(it)
        obstacles[:] = [o for o in obstacles if o[2] not in items]
    def seg_clear(net, a, c, w, layer, skip=()):
        s = pcbnew.SHAPE_SEGMENT(a, c, int(w)); bb = pcbnew.BOX2I(); bb.Merge(a); bb.Merge(c); bb.Inflate(int(w + CLR))
        for onet, obb, item in obstacles:
            if onet == net or item in skip or not obb.Intersects(bb): continue
            if item.Type() == pcbnew.PCB_PAD_T:
                if item.IsOnLayer(layer) and item.GetEffectiveShape(layer).Collide(s, int(CLR)): return False
            elif item.Type() == pcbnew.PCB_VIA_T or item.IsOnLayer(layer):
                if item.GetEffectiveShape().Collide(s, int(CLR)): return False
        return True
    def via_clear(net, v, hs):
        s = pcbnew.SHAPE_CIRCLE(v, int(VIA_R)); bb = pcbnew.BOX2I(pcbnew.VECTOR2I(v.x - int(VIA_R + CLR), v.y - int(VIA_R + CLR)), pcbnew.VECTOR2I(int(2 * (VIA_R + CLR)), int(2 * (VIA_R + CLR))))
        if any(k.Outline().Contains(v) for k in keepouts): return False
        for hp, hd in hs:
            if math.hypot(hp.x - v.x, hp.y - v.y) < DRILL / 2 + hd / 2 + mm(0.30): return False
        for onet, obb, item in obstacles:
            if onet == net or not obb.Intersects(bb): continue
            if item.Type() == pcbnew.PCB_PAD_T:
                if any(item.IsOnLayer(L) and item.GetEffectiveShape(L).Collide(s, int(CLR)) for L in CU): return False
            elif item.GetEffectiveShape().Collide(s, int(CLR)): return False
        return True
    def add_track(net, a, c, w, layer):
        t = pcbnew.PCB_TRACK(b); t.SetStart(a); t.SetEnd(c); t.SetWidth(int(w)); t.SetLayer(layer); t.SetNet(net); b.Add(t); obstacles.append((net.GetNetname(), t.GetBoundingBox(), t)); return t
    def add_via(net, v):
        via = pcbnew.PCB_VIA(b); via.SetPosition(v); via.SetDrill(DRILL); via.SetWidth(int(2 * VIA_R)); via.SetViaType(pcbnew.VIATYPE_THROUGH)
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); via.SetNet(net); b.Add(via); obstacles.append((net.GetNetname(), via.GetBoundingBox(), via)); return via
    def grid_route(net, a, c, w, layer, skip=(), step=mm(0.25), margin=mm(8), avoid_islands=False, allow_rip=False):
        """BFS on a square grid inside the window around a..c; a cell is usable if a track of width w through it
        keeps CLR from every other-net item on `layer` (vias count on all layers). Returns a list of points or None."""
        x0, y0 = min(a.x, c.x) - int(margin), min(a.y, c.y) - int(margin); x1, y1 = max(a.x, c.x) + int(margin), max(a.y, c.y) + int(margin)
        nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
        if nx * ny > 40000: return None
        near = [(onet, obb, item) for onet, obb, item in obstacles if onet != net and item not in skip and obb.Intersects(pcbnew.BOX2I(pcbnew.VECTOR2I(int(x0), int(y0)), pcbnew.VECTOR2I(int(x1 - x0), int(y1 - y0))))]
        islands = [z for zn, zs in plane.items() if zn != net and zn != "3V3" for z in zs] if avoid_islands else []
        r = int(w / 2); rips = {}
        def usable(gx, gy):
            pt = pcbnew.VECTOR2I(int(x0 + gx * step), int(y0 + gy * step)); sh = pcbnew.SHAPE_CIRCLE(pt, r)
            if islands and any(z.Outline().Contains(pt) for z in islands): return False
            hits = []
            for onet, obb, item in near:
                hit = False
                if item.Type() == pcbnew.PCB_PAD_T:
                    hit = item.IsOnLayer(layer) and item.GetEffectiveShape(layer).Collide(sh, int(CLR))
                elif item.Type() == pcbnew.PCB_VIA_T or item.IsOnLayer(layer):
                    hit = item.GetEffectiveShape().Collide(sh, int(CLR))
                if hit:
                    if allow_rip and rippable(onet, item): hits.append(item)
                    else: return False
            if hits: rips[(gx, gy)] = hits
            return True
        ga, gc = (round((a.x - x0) / step), round((a.y - y0) / step)), (round((c.x - x0) / step), round((c.y - y0) / step))
        from collections import deque
        prev = {ga: None}; dq = deque([ga]); cache = {}
        while dq:
            cur = dq.popleft()
            if cur == gc: break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nb = (cur[0] + dx, cur[1] + dy)
                if nb in prev or not (0 <= nb[0] < nx and 0 <= nb[1] < ny): continue
                if nb not in cache: cache[nb] = usable(*nb) or nb == gc
                if not cache[nb]: continue
                prev[nb] = cur; dq.append(nb)
        if gc not in prev: return None
        path = []; cur = gc
        while cur is not None: path.append(cur); cur = prev[cur]
        path.reverse()
        if allow_rip:
            victims = {id(it): it for g in path for it in rips.get(g, [])}
            if victims: rip(list(victims.values()))
        # straighten: keep only direction changes
        pts = [path[0]]
        for i in range(1, len(path) - 1):
            d1 = (path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]); d2 = (path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
            if d1 != d2: pts.append(path[i])
        pts.append(path[-1])
        out = [a] + [pcbnew.VECTOR2I(int(x0 + g[0] * step), int(y0 + g[1] * step)) for g in pts[1:-1]] + [c]
        return out
    def lay_path(net, pts, w, layer):
        return [add_track(net, pts[i], pts[i + 1], w, layer) for i in range(len(pts) - 1)]
    report = []; thin_links = []
    # 1. short high-current nets: direct wide tracks
    for name in WIDE_NETS:
        pads = [p for f in b.GetFootprints() for p in f.Pads() if p.GetNetname() == name]
        if len(pads) < 2: continue
        old = [t for t in b.GetTracks() if t.GetNetname() == name]
        layer_of = lambda p: pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
        # MST over pads (Manhattan), only pairs on a common layer
        edges = sorted((abs(p.GetPosition().x - q.GetPosition().x) + abs(p.GetPosition().y - q.GetPosition().y), i, j)
                       for (i, p), (j, q) in itertools.combinations(enumerate(pads), 2))
        parent = list(range(len(pads)))
        def find(i):
            while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
            return i
        plan = []
        for d, i, j in edges:
            if find(i) != find(j):
                parent[find(i)] = find(j); plan.append((pads[i], pads[j]))
        # remove the router's copper for this net, then try wide connections; restore if any connection fails
        removed = [(t.Type(), t.GetStart() if t.Type() != pcbnew.PCB_VIA_T else t.GetPosition(), t.GetEnd() if t.Type() != pcbnew.PCB_VIA_T else None, t.GetWidth(), t.GetLayer()) for t in old]
        for t in old: b.Remove(t)
        obstacles[:] = [o for o in obstacles if o[2] not in old]
        net = pads[0].GetNet(); made = []; ok_all = True
        hs = holes()
        def inner_ok(a, c, w, layer):
            """wide segment on an inner layer; on the PWR layer it must stay out of the other nets' islands"""
            if not seg_clear(name, a, c, w, layer): return False
            if layer == pcbnew.In3_Cu:
                for zn, zs in plane.items():
                    if zn == name or zn == "3V3": continue
                    for z in zs:
                        for pt in (a, c, pcbnew.VECTOR2I((a.x + c.x) // 2, (a.y + c.y) // 2)):
                            if z.Outline().Contains(pt): return False
            return True
        def via_near(pad, w_stub):
            pos = pad.GetPosition(); layer = layer_of(pad); half = max(pad.GetSize().x, pad.GetSize().y) / 2
            for dist in (half + VIA_R + mm(0.2), half + VIA_R + mm(0.7), half + VIA_R + mm(1.3), half + VIA_R + mm(2.0)):
                for k in range(16):
                    a_ = k * 2 * math.pi / 16
                    v = pcbnew.VECTOR2I(int(pos.x + dist * math.cos(a_)), int(pos.y + dist * math.sin(a_)))
                    if via_clear(name, v, hs) and seg_clear(name, pos, v, w_stub, layer, skip=(pad,)): return v
            return None
        for p, q in plan:
            a, c = p.GetPosition(), q.GetPosition()
            layer = layer_of(p) if layer_of(p) == layer_of(q) else None
            done = False
            if layer is not None:
                for w in (mm(0.6), mm(0.4), mm(0.3)):
                    pts = grid_route(name, a, c, w, layer, skip=(p, q))
                    if pts: made += lay_path(net, pts, w, layer); done = True; break
            if not done:
                va = via_near(p, mm(0.4)); vb = via_near(q, mm(0.4)) if va is not None else None
                if va is not None and vb is not None:
                    for L in (pcbnew.In2_Cu, pcbnew.In5_Cu, pcbnew.In3_Cu):
                        for w in (mm(0.6), mm(0.4), mm(0.3)):
                            pts = grid_route(name, va, vb, w, L, avoid_islands=(L == pcbnew.In3_Cu))
                            if pts:
                                made.append(add_track(net, a, va, mm(0.4), layer_of(p))); made.append(add_via(net, va)); hs.append((va, DRILL))
                                made.append(add_track(net, c, vb, mm(0.4), layer_of(q))); made.append(add_via(net, vb)); hs.append((vb, DRILL))
                                made += lay_path(net, pts, w, L); done = True; break
                        if done: break
            if not done and layer is not None:
                for w in (mm(0.5), mm(0.35)):
                    pts = grid_route(name, a, c, w, layer, skip=(p, q), allow_rip=True)
                    if pts: made += lay_path(net, pts, w, layer); done = True; break
            if not done and layer is not None:
                # last resort for this link: keep connectivity with a thin track (DRC will flag it as narrow)
                for w in (mm(0.2), mm(0.15), mm(0.1)):
                    pts = grid_route(name, a, c, w, layer, skip=(p, q), allow_rip=True)
                    if pts: made += lay_path(net, pts, w, layer); done = True; thin_links.append(name); break
            if name in os.environ.get("PW_DEBUG", "").split(","):
                print(f"    link {p.GetParentAsString()}.{p.GetNumber()} -> {q.GetParentAsString()}.{q.GetNumber()} layer={layer} done={done} thin={name in thin_links}")
            if not done: ok_all = False          # keep trying the other links of this net
        if not ok_all:
            # keep the wide links that worked (they parallel the router's copper on the same net) and put the
            # router's copper back so the failed links stay connected; DRC flags what is still thin
            for kind, s0, e0, w0, l0 in removed:
                if kind == pcbnew.PCB_VIA_T:
                    v = pcbnew.PCB_VIA(b); v.SetPosition(s0); v.SetDrill(DRILL); v.SetWidth(int(2 * VIA_R)); v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(net); b.Add(v); obstacles.append((name, v.GetBoundingBox(), v))
                else:
                    t = pcbnew.PCB_TRACK(b); t.SetStart(s0); t.SetEnd(e0); t.SetWidth(w0); t.SetLayer(l0); t.SetNet(net); b.Add(t); obstacles.append((name, t.GetBoundingBox(), t))
            report.append(f"{name}: {len(made)} wide segments added, router's copper kept for the links without a wide path ({len(plan)} links)")
        else:
            report.append(f"{name}: {len(made)} segments replace {len(old)} router items" + (f" ({thin_links.count(name)} links only fit as thin tracks)" if name in thin_links else ""))
    # 2. multiple vias for high-current pads on plane nets
    hs = holes(); added = 0
    for f in b.GetFootprints():
        if f.GetReference() not in MULTI_VIA_REFS: continue
        for p in f.Pads():
            n = p.GetNetname()
            if n not in plane: continue
            layer = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
            pos = p.GetPosition(); half = max(p.GetSize().x, p.GetSize().y) / 2
            got = 0
            for dist in (half + VIA_R + mm(0.2), half + VIA_R + mm(0.9)):
                for k in range(16):
                    if got >= 3: break
                    a = k * 2 * math.pi / 16
                    v = pcbnew.VECTOR2I(int(pos.x + dist * math.cos(a)), int(pos.y + dist * math.sin(a)))
                    if not any(z.Outline().Contains(v) for z in plane[n]): continue
                    if not via_clear(n, v, hs) or not seg_clear(n, pos, v, mm(0.5), layer, skip=(p,)): continue
                    add_via(p.GetNet(), v); add_track(p.GetNet(), pos, v, mm(0.5), layer); hs.append((v, DRILL)); got += 1; added += 1
            if got: report.append(f"{f.GetReference()} pad {p.GetNumber()} ({n}): {got} vias")
    # 3. re-route the links of the nets that were ripped (thin, direct / L / inner with vias), best effort
    rerouted = 0; left = []
    for rn in list(ripped):
        pads = [p for f in b.GetFootprints() for p in f.Pads() if p.GetNetname() == rn]
        b.BuildConnectivity(); c = b.GetConnectivity()
        # connect each pad with no copper to the nearest pad of the net that has copper (or any other pad)
        dry = [p for p in pads if len(c.GetConnectedTracks(p)) == 0]
        for p in dry:
            others = sorted((q for q in pads if q is not p), key=lambda q: abs(q.GetPosition().x - p.GetPosition().x) + abs(q.GetPosition().y - p.GetPosition().y))
            ok = False
            for q in others[:3]:
                a, c_ = p.GetPosition(), q.GetPosition(); lp = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu; lq = pcbnew.F_Cu if q.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
                if lp == lq:
                    pts = grid_route(rn, a, c_, mm(0.15), lp, skip=(p, q))
                    if pts: lay_path(p.GetNet(), pts, mm(0.15), lp); ok = True; break
            if ok: rerouted += 1
            else: left.append(rn)
    report.append(f"ripped {sum(ripped.values())} items on {len(ripped)} low-current nets to make room; re-routed {rerouted} of their pads directly; left for the router: {sorted(set(left))}")
    pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b)
    print("\n".join(report)); print(f"multi-via additions: {added}")

if __name__ == "__main__":
    main()
