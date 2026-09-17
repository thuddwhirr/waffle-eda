#!/usr/bin/env python3
"""Connect every plane-net pad (GND, 1V35, 1V1, 3V3, ...) that has no path to its plane, without touching anything else.
For each open pad, in this order:
  1. a 0.1 mm stub on the pad's layer to a neighbouring item of the same net that already reaches the plane
     (an adjacent ball, a via, a stitching via) within 1.5 mm;
  2. a new 0.45/0.2 via next to the pad, at the board rules (0.1 mm copper clearance, 0.2 mm hole clearance), that lands
     inside the net's filled zone copper, plus the stub to it.
"Open" is decided by this script's own connectivity (union-find over the net's copper; an item reaches the plane when it
is a via or pad inside the net's zone fill), not by the DRC file, so it can be re-run after hand edits.
Usage: python3 hw/tools/fix_open_pads.py [board.kicad_pcb] [--nets GND,1V35] [--dry-run]     (default hw/waffle.kicad_pcb, in place)"""
import os, sys, math, pcbnew
mm, tomm = pcbnew.FromMM, pcbnew.ToMM
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
BOARD = args[0] if args else os.path.join(HW, "waffle.kicad_pcb")
ONLY = None
for i, a in enumerate(sys.argv):
    if a == "--nets": ONLY = set(sys.argv[i + 1].split(","))
DRY = "--dry-run" in sys.argv
VIA_D, DRILL, CLR, HOLE_CLR, W = mm(0.45), mm(0.20), mm(0.10), mm(0.20), mm(0.10)
SHARE_R, VIA_R_MAX, STEP = mm(1.5), mm(3.5), mm(0.1)

b = pcbnew.LoadBoard(BOARD)
zones = [z for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname()]
pcbnew.ZONE_FILLER(b).Fill(b.Zones())                          # a freshly generated board has no fills; the plane test needs them
fills = {}                                                    # net -> [(layer, filled polyset)]
for z in zones:
    for L in z.GetLayerSet().Seq():
        fills.setdefault(z.GetNetname(), []).append((L, pcbnew.SHAPE_POLY_SET(z.GetFilledPolysList(L))))   # own copy: the wrapper's reference can dangle (segfault in PointInside)
plane_nets = set(fills) if ONLY is None else {n for n in fills if n in ONLY}
def in_fill(net, pt):
    """inside a connected piece of the net's fill on some layer"""
    return any(gp.Contains(pt) for L, gp in good_fills.get(net, []))

# ---- connectivity per plane net (own union-find: the SWIG connectivity wrapper is unreliable across calls)
pads = [(f, p) for f in b.GetFootprints() for p in f.Pads()]
ref_of = {p.m_Uuid.AsString(): f.GetReference() for f, p in pads}
def pname(p): return f"{ref_of[p.m_Uuid.AsString()]}.{p.GetNumber()}[{p.GetNetname()}]"
items = {}                                                    # net -> list of (kind, obj)
for f, p in pads:
    if p.GetNetname() in plane_nets: items.setdefault(p.GetNetname(), []).append(("pad", p))
for t in b.GetTracks():
    if t.GetNetname() in plane_nets: items[t.GetNetname()].append(("via" if t.Type() == pcbnew.PCB_VIA_T else "trk", t))
def touches(a, c):
    """do two same-net items touch: endpoint coincidence, endpoint inside a pad, via/pad centre on a track"""
    ka, oa = a; kc, oc = c
    if ka == "trk" and kc == "trk":
        return any(pa == pc for pa in (oa.GetStart(), oa.GetEnd()) for pc in (oc.GetStart(), oc.GetEnd())) or oa.GetEffectiveShape().Collide(oc.GetEffectiveShape(), 0)
    if ka == "trk" or kc == "trk":
        trk, other, ko = (oa, oc, kc) if ka == "trk" else (oc, oa, ka)
        shape = other.GetEffectiveShape(trk.GetLayer()) if ko == "pad" else other.GetEffectiveShape()
        if ko == "pad" and not other.IsOnLayer(trk.GetLayer()): return False
        return trk.GetEffectiveShape().Collide(shape, 0)
    sa = oa.GetEffectiveShape(pcbnew.F_Cu if ka == "pad" and oa.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu) if ka == "pad" else oa.GetEffectiveShape()
    sc = oc.GetEffectiveShape(pcbnew.F_Cu if kc == "pad" and oc.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu) if kc == "pad" else oc.GetEffectiveShape()
    if ka == "pad" and kc == "pad" and not any(oa.IsOnLayer(L) and oc.IsOnLayer(L) for L in (pcbnew.F_Cu, pcbnew.B_Cu)): return False
    return sa.Collide(sc, 0)
def reaches_plane(kind, o):
    """the item touches its net's zone fill on some layer (thermal spokes count: they overlap the pad)"""
    if kind == "trk": return False
    for L, poly in fills.get(o.GetNetname(), []):
        if kind == "pad" and not o.IsOnLayer(L): continue
        shape = o.GetEffectiveShape(L) if kind == "pad" else o.GetEffectiveShape()
        if poly.Collide(shape, 0): return True
    return False
open_pads, anchors, good_fills = [], {}, {}                   # anchors: net -> [(kind, obj)] items that reach the plane
for net, its in items.items():
    n = len(its); parent = list(range(n))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    bbs = [o.GetBoundingBox() for k, o in its]
    for i in range(n):
        for j in range(i + 1, n):
            if bbs[i].Intersects(bbs[j]) and touches(its[i], its[j]): parent[find(i)] = find(j)
    good = {find(i) for i, (k, o) in enumerate(its) if reaches_plane(k, o)}
    # a net distributed by tracks rather than a plane (5V_SYS) has its regulator in the largest cluster: that one counts
    from collections import Counter
    good.add(Counter(find(i) for i in range(n)).most_common(1)[0][0])
    anchors[net] = [(k, o) for i, (k, o) in enumerate(its) if find(i) in good]
    # fill pieces (an island can be in several pieces) that a connected via or pad touches: only those may take a new via
    for L, poly in fills.get(net, []):
        gp = pcbnew.SHAPE_POLY_SET()                         # the connected pieces, holes included, as one polyset
        for i in range(poly.OutlineCount()):
            piece = poly.Outline(i); hit = False
            for k, o in anchors[net]:
                if k == "trk" or not (k == "via" or o.IsOnLayer(L)): continue
                q = o.GetPosition()
                if piece.PointInside(q) or (k == "pad" and piece.Distance(q) <= max(o.GetSize().x, o.GetSize().y) / 2 + mm(0.3)): hit = True; break
            if not hit: continue
            gp.AddOutline(piece)
            for j in range(poly.HoleCount(i)): gp.AddHole(poly.Hole(i, j))
        good_fills.setdefault(net, []).append((L, gp))
    for i, (k, o) in enumerate(its):
        if k == "pad" and find(i) not in good: open_pads.append(o)
print(f"{len(open_pads)} open plane-net pads: " + ", ".join(pname(p) for p in open_pads))

# ---- obstacles (all copper of other nets) and clearance checks at the board rules
obstacles = [(p.GetNetname(), p.GetBoundingBox(), "pad", p) for f, p in pads] + [(t.GetNetname(), t.GetBoundingBox(), "via" if t.Type() == pcbnew.PCB_VIA_T else "trk", t) for t in b.GetTracks()]
holes = [(t.GetPosition(), t.GetDrillValue()) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T] + [(p.GetPosition(), max(p.GetDrillSize().x, p.GetDrillSize().y)) for f, p in pads if p.GetDrillSize().x > 0]
CU = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.In5_Cu, pcbnew.In6_Cu, pcbnew.B_Cu]
edge = b.GetBoardEdgesBoundingBox()
def clear_on(net, shape, bbox, layers, clr=CLR):
    for onet, obb, kind, o in obstacles:
        if onet == net or not obb.Intersects(bbox): continue
        if kind == "pad":
            if any(o.IsOnLayer(L) and o.GetEffectiveShape(L).Collide(shape, int(clr)) for L in layers): return False
        elif kind == "via" or o.GetLayer() in layers:
            if o.GetEffectiveShape().Collide(shape, int(clr)): return False
    return True
DEBUG = os.environ.get("DEBUG_PAD")
keepouts = [z for z in b.Zones() if z.GetIsRuleArea() and (z.GetDoNotAllowVias() or z.GetDoNotAllowTracks())]
for f_ in b.GetFootprints():
    keepouts += [z for z in f_.Zones() if z.GetIsRuleArea() and (z.GetDoNotAllowVias() or z.GetDoNotAllowTracks())]
def via_why(net, v):
    """None if a via may go at v, else the reason"""
    if not (edge.GetLeft() + mm(1) < v.x < edge.GetRight() - mm(1) and edge.GetTop() + mm(1) < v.y < edge.GetBottom() - mm(1)): return "edge"
    if any(k.Outline().Contains(v) for k in keepouts): return "keepout"
    if not in_fill(net, v): return "no connected fill"
    for hp, hd in holes:
        if math.hypot(hp.x - v.x, hp.y - v.y) < DRILL / 2 + hd / 2 + HOLE_CLR: return "hole"
    r = VIA_D / 2 + CLR
    box = pcbnew.BOX2I(pcbnew.VECTOR2I(v.x - int(r), v.y - int(r)), pcbnew.VECTOR2I(int(2 * r), int(2 * r)))
    if not clear_on(net, pcbnew.SHAPE_CIRCLE(v, int(VIA_D / 2)), box, CU): return "copper"
    hbox = pcbnew.BOX2I(pcbnew.VECTOR2I(v.x - int(DRILL / 2 + HOLE_CLR), v.y - int(DRILL / 2 + HOLE_CLR)), pcbnew.VECTOR2I(int(DRILL + 2 * HOLE_CLR), int(DRILL + 2 * HOLE_CLR)))
    return None if clear_on(net, pcbnew.SHAPE_CIRCLE(v, int(DRILL / 2)), hbox, CU, HOLE_CLR) else "hole-copper"
def via_ok(net, v): return via_why(net, v) is None
def stub_ok(net, a, c, layer):
    seg = pcbnew.SHAPE_SEGMENT(a, c, int(W)); box = pcbnew.BOX2I(); box.Merge(a); box.Merge(c); box.Inflate(int(W + CLR))
    if any(k.GetDoNotAllowTracks() and k.Outline().Collide(seg, 0) for k in keepouts): return False
    return clear_on(net, seg, box, [layer])
def add_track(net_obj, a, c, layer):
    t = pcbnew.PCB_TRACK(b); t.SetStart(a); t.SetEnd(c); t.SetWidth(int(W)); t.SetLayer(layer); t.SetNet(net_obj); b.Add(t)
    obstacles.append((net_obj.GetNetname(), t.GetBoundingBox(), "trk", t)); return t
def add_via(net_obj, v):
    via = pcbnew.PCB_VIA(b); via.SetPosition(v); via.SetDrill(int(DRILL)); via.SetWidth(int(VIA_D)); via.SetViaType(pcbnew.VIATYPE_THROUGH)
    via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); via.SetNet(net_obj); b.Add(via)
    obstacles.append((net_obj.GetNetname(), via.GetBoundingBox(), "via", via)); holes.append((v, DRILL)); return via

placed, failed = [], []
queue = sorted(open_pads, key=lambda p: (p.GetNetname(), ref_of[p.m_Uuid.AsString()], p.GetNumber()))
for _pass in range(4):                                        # later passes can share the vias placed in earlier ones
  if not queue: break
  retry = []
  for p in queue:
      net = p.GetNetname(); pos = p.GetPosition(); layer = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
      name = pname(p); done = None
      # 1. share a neighbour that reaches the plane
      cands = []
      for k, o in anchors[net]:
          if k == "trk":
              if o.GetLayer() != layer: continue
              qs = [o.GetStart(), o.GetEnd()]
          else:
              if not (k == "via" or o.IsOnLayer(layer)): continue
              qs = [o.GetPosition()]
          for q in qs:
              d = math.hypot(q.x - pos.x, q.y - pos.y)
              if 0 < d <= SHARE_R: cands.append((d, k, o, q))
      for d, k, o, q in sorted(cands, key=lambda c: c[0]):
          if stub_ok(net, pos, q, layer):
              add_track(p.GetNet(), pos, q, layer); done = f"stub {tomm(d):.2f} mm to {k} at ({tomm(q.x):.1f},{tomm(q.y):.1f})"; break
      # 2. a new via
      if not done:
          half = max(p.GetSize().x, p.GetSize().y) / 2; rmin = half + VIA_D / 2 + CLR
          pts = []
          for step, reach in ((mm(0.4), VIA_R_MAX), (STEP, VIA_R_MAX)):   # the half-pitch grid of a BGA holds the natural dog-bone sites
              k = int(reach / step); grid = []
              for i in range(-k, k + 1):
                  for j in range(-k, k + 1):
                      v = pcbnew.VECTOR2I(int(pos.x + i * step), int(pos.y + j * step)); d = math.hypot(i * step, j * step)
                      if rmin <= d <= reach: grid.append((d, v))
              pts += sorted(grid, key=lambda c: c[0])
          if DEBUG and DEBUG in name:
              from collections import Counter
              why = Counter(); shown = 0
              for d, v in pts:
                  r = via_why(net, v) or ("stub" if not stub_ok(net, pos, v, layer) else "ok"); why[r] += 1
                  if r != "copper" and shown < 25: print(f"      cand ({tomm(v.x):.2f},{tomm(v.y):.2f}) {tomm(d):.2f} mm: {r}"); shown += 1
              print(f"      {name} candidate outcomes: {dict(why)}")
          for d, v in pts:
              if via_ok(net, v) and stub_ok(net, pos, v, layer):
                  add_via(p.GetNet(), v); add_track(p.GetNet(), pos, v, layer); done = f"via at ({tomm(v.x):.2f},{tomm(v.y):.2f}), {tomm(d):.2f} mm"; break
      if done: placed.append(name); anchors[net].append(("pad", p)); print(f"  {name}: {done}")
      else: retry.append(p)
  queue = retry
failed = [pname(p) for p in queue]
for p in queue: print(f"  {pname(p)}: no clear spot within {tomm(VIA_R_MAX)} mm")

print(f"connected {len(placed)}, failed {len(failed)}" + (f": {failed}" if failed else ""))
if not DRY:
    pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b); print("saved", BOARD)
