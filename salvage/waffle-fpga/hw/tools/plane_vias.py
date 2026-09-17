#!/usr/bin/env python3
"""Drop a via (0.45/0.20) next to every plane-net pad that has no copper yet, connected with a short track,
checking the candidate against all other-net copper at the board clearance. Then refill zones.
Usage: python3 hw/tools/plane_vias.py   (edits hw/waffle.kicad_pcb in place)"""
import os, math, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(HW, "waffle.kicad_pcb")
mm = pcbnew.FromMM
VIA_R = mm(0.45) / 2; DRILL = mm(0.20); CLR = mm(0.125)
CU = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.In5_Cu, pcbnew.In6_Cu, pcbnew.B_Cu]

def main():
    b = pcbnew.LoadBoard(BOARD); b.BuildConnectivity(); c = b.GetConnectivity()
    zones = [z for z in b.Zones() if not z.GetIsRuleArea()]
    plane_nets = {}
    for z in zones: plane_nets.setdefault(z.GetNetname(), []).append(z)
    # obstacle list: (net, bbox, shape_or_item, kind)
    obstacles = []
    for f in b.GetFootprints():
        for p in f.Pads(): obstacles.append((p.GetNetname(), p.GetBoundingBox(), p))
    for t in b.GetTracks(): obstacles.append((t.GetNetname(), t.GetBoundingBox(), t))
    # the free ends of the BGA escape stubs must stay reachable: a via in front of a stub end blocks the router (D57),
    # so every dangling signal-net track end gets a virtual 1.5 mm extension (0.25 mm clearance) as an obstacle
    ends = {}
    for t in b.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T: continue
        for q in (t.GetStart(), t.GetEnd()): ends[(t.GetNetname(), q.x, q.y)] = ends.get((t.GetNetname(), q.x, q.y), 0) + 1
    anchored = {(t.GetNetname(), t.GetPosition().x, t.GetPosition().y) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T}
    for f in b.GetFootprints():
        for p in f.Pads(): anchored.add((p.GetNetname(), p.GetPosition().x, p.GetPosition().y))
    plane_names = {z.GetNetname() for z in zones}
    n_ext = 0
    for t in b.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T or t.GetNetname() in plane_names: continue
        for e, s0 in ((t.GetEnd(), t.GetStart()), (t.GetStart(), t.GetEnd())):
            key = (t.GetNetname(), e.x, e.y)
            if ends[key] != 1 or key in anchored: continue
            L = math.hypot(e.x - s0.x, e.y - s0.y)
            if L == 0: continue
            far = pcbnew.VECTOR2I(int(e.x + (e.x - s0.x) / L * mm(1.5)), int(e.y + (e.y - s0.y) / L * mm(1.5)))
            x = pcbnew.PCB_TRACK(b); x.SetStart(e); x.SetEnd(far); x.SetWidth(int(t.GetWidth() + 2 * (mm(0.25) - CLR))); x.SetLayer(t.GetLayer())
            obstacles.append((t.GetNetname(), x.GetBoundingBox(), x)); n_ext += 1
    print(f"{n_ext} stub-end extensions protected")
    edge = b.GetBoardEdgesBoundingBox()
    keepouts = [z for z in b.Zones() if z.GetIsRuleArea() and (z.GetDoNotAllowVias() or z.GetDoNotAllowTracks())]
    for f in b.GetFootprints():
        for z in f.Zones():
            if z.GetIsRuleArea() and (z.GetDoNotAllowVias() or z.GetDoNotAllowTracks()): keepouts.append(z)
    holes = [(t.GetPosition(), t.GetDrillValue()) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetDrillSize().x > 0: holes.append((p.GetPosition(), max(p.GetDrillSize().x, p.GetDrillSize().y)))
    HOLE_GAP = mm(0.30)
    def hole_ok(v):
        for hp, hd in holes:
            if math.hypot(hp.x - v.x, hp.y - v.y) < DRILL / 2 + hd / 2 + HOLE_GAP: return False
        return True
    def clear(net, shape, bbox, extra=CLR):
        for onet, obb, item in obstacles:
            if onet == net: continue
            if not obb.Intersects(bbox): continue
            if item.Type() == pcbnew.PCB_PAD_T:
                for L in CU:
                    if item.IsOnLayer(L) and item.GetEffectiveShape(L).Collide(shape, int(extra)): return False
            else:
                if item.GetEffectiveShape().Collide(shape, int(extra)): return False
        return True
    def inside_zone(net, pt):
        for z in plane_nets.get(net, []):
            if z.Outline().Contains(pt): return True
        return False
    todo = []
    for f in b.GetFootprints():
        for p in f.Pads():
            n = p.GetNetname()
            if n in plane_nets and len(c.GetConnectedTracks(p)) == 0 and not any(p.IsOnLayer(z.GetLayer()) for z in plane_nets[n]):
                todo.append(p)
    print(f"{len(todo)} plane-net pads without copper")
    placed = failed = 0
    for p in todo:
        n = p.GetNetname(); pos = p.GetPosition(); sz = p.GetSize(); half = max(sz.x, sz.y) / 2
        layer = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
        done = False
        for dist, W, ndir in [(half + VIA_R + d, w, 16) for w in (mm(0.20), mm(0.10)) for d in (mm(0.15), mm(0.45), mm(0.8), mm(1.2), mm(1.7), mm(2.3), mm(3.0), mm(3.8))]:   # the long reaches clear the protected stub-end zone in front of a BGA comb:
            for k in range(ndir):
                a = k * 2 * math.pi / ndir
                v = pcbnew.VECTOR2I(int(pos.x + dist * math.cos(a)), int(pos.y + dist * math.sin(a)))
                if not (edge.GetLeft() + mm(1) < v.x < edge.GetRight() - mm(1) and edge.GetTop() + mm(1) < v.y < edge.GetBottom() - mm(1)): continue
                if not inside_zone(n, v) or not hole_ok(v): continue
                if any(k.Outline().Contains(v) for k in keepouts): continue
                vs = pcbnew.SHAPE_CIRCLE(v, int(VIA_R)); vb = pcbnew.BOX2I(pcbnew.VECTOR2I(v.x - int(VIA_R + CLR), v.y - int(VIA_R + CLR)), pcbnew.VECTOR2I(int(2 * (VIA_R + CLR)), int(2 * (VIA_R + CLR))))
                ts = pcbnew.SHAPE_SEGMENT(pos, v, int(W)); tb = pcbnew.BOX2I(); tb.Merge(pos); tb.Merge(v); tb.Inflate(int(W + CLR))
                if not clear(n, vs, vb): continue
                # the track is only on `layer`: check against items on that layer
                ok = True
                for onet, obb, item in obstacles:
                    if onet == n or not obb.Intersects(tb): continue
                    if item.Type() == pcbnew.PCB_PAD_T:
                        if item.IsOnLayer(layer) and item.GetEffectiveShape(layer).Collide(ts, int(CLR)): ok = False; break
                    elif item.Type() == pcbnew.PCB_VIA_T or item.IsOnLayer(layer):
                        if item.GetEffectiveShape().Collide(ts, int(CLR)): ok = False; break
                if not ok: continue
                via = pcbnew.PCB_VIA(b); via.SetPosition(v); via.SetDrill(DRILL); via.SetWidth(int(2 * VIA_R)); via.SetViaType(pcbnew.VIATYPE_THROUGH)
                via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); via.SetNet(p.GetNet()); b.Add(via)
                t = pcbnew.PCB_TRACK(b); t.SetStart(pos); t.SetEnd(v); t.SetWidth(int(W)); t.SetLayer(layer); t.SetNet(p.GetNet()); b.Add(t)
                obstacles.append((n, via.GetBoundingBox(), via)); obstacles.append((n, t.GetBoundingBox(), t)); holes.append((v, DRILL))
                placed += 1; done = True; break
            if done: break
        if not done: failed += 1
    pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b)
    print(f"placed {placed} plane vias, {failed} pads found no clear spot")

if __name__ == "__main__":
    main()
