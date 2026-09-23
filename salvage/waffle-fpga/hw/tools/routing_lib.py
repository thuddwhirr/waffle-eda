"""Shared geometry helpers for the scripted routing steps: obstacle index, clearance tests, via/track creation and a
small BFS grid router. Used by finish_links.py (power_widen.py carries its own copy with rip support)."""
import math, pcbnew
from collections import deque
mm = pcbnew.FromMM
CLR = mm(0.125); VIA_R = mm(0.45) / 2; DRILL = mm(0.20)
CU = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.In5_Cu, pcbnew.In6_Cu, pcbnew.B_Cu]

class Router:
    def __init__(self, b):
        self.b = b
        self.plane = {}
        for z in b.Zones():
            if not z.GetIsRuleArea(): self.plane.setdefault(z.GetNetname(), []).append(z)
        self.obstacles = []
        for f in b.GetFootprints():
            for p in f.Pads(): self.obstacles.append((p.GetNetname(), p.GetBoundingBox(), p))
        for t in b.GetTracks(): self.obstacles.append((t.GetNetname(), t.GetBoundingBox(), t))
        self.keepouts = [z for z in b.Zones() if z.GetIsRuleArea() and (z.GetDoNotAllowVias() or z.GetDoNotAllowTracks())]
        for f in b.GetFootprints():
            for z in f.Zones():
                if z.GetIsRuleArea() and (z.GetDoNotAllowVias() or z.GetDoNotAllowTracks()): self.keepouts.append(z)
        self.holes = [(t.GetPosition(), t.GetDrillValue()) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
        for f in b.GetFootprints():
            for p in f.Pads():
                if p.GetDrillSize().x > 0: self.holes.append((p.GetPosition(), max(p.GetDrillSize().x, p.GetDrillSize().y)))
        e = b.GetBoardEdgesBoundingBox(); self.edge = (e.GetLeft() + mm(1), e.GetTop() + mm(1), e.GetRight() - mm(1), e.GetBottom() - mm(1))
    @staticmethod
    def layer_of(p): return pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
    def collides(self, net, shape, bbox, layer, skip=()):
        for onet, obb, item in self.obstacles:
            if onet == net or item in skip or not obb.Intersects(bbox): continue
            if item.Type() == pcbnew.PCB_PAD_T:
                if layer is None:
                    if any(item.IsOnLayer(L) and item.GetEffectiveShape(L).Collide(shape, int(CLR)) for L in CU): return True
                elif item.IsOnLayer(layer) and item.GetEffectiveShape(layer).Collide(shape, int(CLR)): return True
            elif item.Type() == pcbnew.PCB_VIA_T or layer is None or item.IsOnLayer(layer):
                if item.GetEffectiveShape().Collide(shape, int(CLR)): return True
        return False
    def seg_clear(self, net, a, c, w, layer, skip=()):
        s = pcbnew.SHAPE_SEGMENT(a, c, int(w)); bb = pcbnew.BOX2I(); bb.Merge(a); bb.Merge(c); bb.Inflate(int(w + CLR))
        return not self.collides(net, s, bb, layer, skip)
    def via_clear(self, net, v):
        if not (self.edge[0] < v.x < self.edge[2] and self.edge[1] < v.y < self.edge[3]): return False
        if any(k.Outline().Contains(v) for k in self.keepouts): return False
        for hp, hd in self.holes:
            if math.hypot(hp.x - v.x, hp.y - v.y) < DRILL / 2 + hd / 2 + mm(0.30): return False
        s = pcbnew.SHAPE_CIRCLE(v, int(VIA_R)); bb = pcbnew.BOX2I(pcbnew.VECTOR2I(v.x - int(VIA_R + CLR), v.y - int(VIA_R + CLR)), pcbnew.VECTOR2I(int(2 * (VIA_R + CLR)), int(2 * (VIA_R + CLR))))
        return not self.collides(net, s, bb, None)
    def add_track(self, net, a, c, w, layer):
        t = pcbnew.PCB_TRACK(self.b); t.SetStart(a); t.SetEnd(c); t.SetWidth(int(w)); t.SetLayer(layer); t.SetNet(net); self.b.Add(t)
        self.obstacles.append((net.GetNetname(), t.GetBoundingBox(), t)); return t
    def add_via(self, net, v):
        via = pcbnew.PCB_VIA(self.b); via.SetPosition(v); via.SetDrill(DRILL); via.SetWidth(int(2 * VIA_R)); via.SetViaType(pcbnew.VIATYPE_THROUGH)
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); via.SetNet(net); self.b.Add(via)
        self.obstacles.append((net.GetNetname(), via.GetBoundingBox(), via)); self.holes.append((v, DRILL)); return via
    def via_near(self, net, pad, w_stub):
        pos = pad.GetPosition(); layer = self.layer_of(pad); half = max(pad.GetSize().x, pad.GetSize().y) / 2
        for dist in (half + VIA_R + mm(0.2), half + VIA_R + mm(0.7), half + VIA_R + mm(1.3), half + VIA_R + mm(2.0)):
            for k in range(16):
                a_ = k * 2 * math.pi / 16
                v = pcbnew.VECTOR2I(int(pos.x + dist * math.cos(a_)), int(pos.y + dist * math.sin(a_)))
                if self.via_clear(net, v) and self.seg_clear(net, pos, v, w_stub, layer, skip=(pad,)): return v
        return None
    def grid_route(self, net, a, c, w, layer, skip=(), step=mm(0.25), margin=mm(8), avoid_islands=False, max_cells=60000):
        x0, y0 = min(a.x, c.x) - int(margin), min(a.y, c.y) - int(margin); x1, y1 = max(a.x, c.x) + int(margin), max(a.y, c.y) + int(margin)
        nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
        if nx * ny > max_cells: return None
        win = pcbnew.BOX2I(pcbnew.VECTOR2I(int(x0), int(y0)), pcbnew.VECTOR2I(int(x1 - x0), int(y1 - y0)))
        near = [(onet, obb, item) for onet, obb, item in self.obstacles if onet != net and item not in skip and obb.Intersects(win)]
        islands = [z for zn, zs in self.plane.items() if zn != net and zn != "3V3" for z in zs] if avoid_islands else []
        r = int(w / 2)
        def usable(gx, gy):
            pt = pcbnew.VECTOR2I(int(x0 + gx * step), int(y0 + gy * step))
            if not (self.edge[0] < pt.x < self.edge[2] and self.edge[1] < pt.y < self.edge[3]): return False
            if islands and any(z.Outline().Contains(pt) for z in islands): return False
            sh = pcbnew.SHAPE_CIRCLE(pt, r)
            for onet, obb, item in near:
                if item.Type() == pcbnew.PCB_PAD_T:
                    if item.IsOnLayer(layer) and item.GetEffectiveShape(layer).Collide(sh, int(CLR)): return False
                elif item.Type() == pcbnew.PCB_VIA_T or item.IsOnLayer(layer):
                    if item.GetEffectiveShape().Collide(sh, int(CLR)): return False
            return True
        ga, gc = (round((a.x - x0) / step), round((a.y - y0) / step)), (round((c.x - x0) / step), round((c.y - y0) / step))
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
        path.reverse(); pts = [path[0]]
        for i in range(1, len(path) - 1):
            d1 = (path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]); d2 = (path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
            if d1 != d2: pts.append(path[i])
        pts.append(path[-1])
        return [a] + [pcbnew.VECTOR2I(int(x0 + g[0] * step), int(y0 + g[1] * step)) for g in pts[1:-1]] + [c]
    def lay(self, net, pts, w, layer):
        return [self.add_track(net, pts[i], pts[i + 1], w, layer) for i in range(len(pts) - 1)]
