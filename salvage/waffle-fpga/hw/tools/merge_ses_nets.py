#!/usr/bin/env python3
"""Merge the copper of selected nets from a Freerouting session into hw/waffle.kicad_pcb without touching the
rest: the session is imported into a scratch copy, the named nets' tracks/vias are removed from the real board and
copied over from the scratch copy. Usage: python3 hw/tools/merge_ses_nets.py build/power.ses NET [NET ...]"""
import os, sys, shutil, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); ROOT = os.path.dirname(HW)
BOARD = os.path.join(HW, "waffle.kicad_pcb"); SCRATCH = os.path.join(ROOT, "build", "merge_scratch.kicad_pcb")
ses = sys.argv[1]
import re
if len(sys.argv) > 2 and sys.argv[2] in ("--except", "--only"):   # regex modes
    rx = re.compile(sys.argv[3]); mode = sys.argv[2]; nets = None
else:
    nets = set(sys.argv[2:]); mode = None
def wanted(n):
    if nets is not None: return n in nets
    return (not rx.match(n)) if mode == "--except" else bool(rx.match(n))
shutil.copy(BOARD, SCRATCH); shutil.copy(BOARD.replace(".kicad_pcb", ".kicad_pro"), SCRATCH.replace(".kicad_pcb", ".kicad_pro"))
sb = pcbnew.LoadBoard(SCRATCH); pcbnew.ImportSpecctraSES(sb, ses); pcbnew.SaveBoard(SCRATCH, sb)
sb = pcbnew.LoadBoard(SCRATCH)      # reload: the wrapper is unusable right after the import
# extract the wanted copper as plain values before opening the second board (two live boards confuse the wrapper)
items = []
for t in sb.GetTracks():
    n = t.GetNetname()
    if not wanted(n): continue
    if t.Type() == pcbnew.PCB_VIA_T: items.append(("via", n, (t.GetPosition().x, t.GetPosition().y), t.GetDrillValue(), t.GetWidth(pcbnew.F_Cu), None))
    else: items.append(("trk", n, (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y), t.GetWidth(), t.GetLayer()))
del sb
b = pcbnew.LoadBoard(BOARD); netmap = b.GetNetsByName()
pads_by_net = {}
for f in b.GetFootprints():
    for p in f.Pads(): pads_by_net.setdefault(p.GetNetname(), []).append((p.m_Uuid.AsString(), p.GetBoundingBox(), p.GetDrillSize().x > 0, [L for L in (pcbnew.F_Cu, pcbnew.B_Cu) if p.IsOnLayer(L)]))
def clusters(board, names):
    """per net: number of connected groups its pads fall into (1 = fully connected); own union-find over exact
    endpoint coincidence, vias at endpoints and endpoints inside pad outlines (the SWIG connectivity wrapper cannot be
    queried twice in one process)"""
    out = {}
    for n in names:
        pads = pads_by_net.get(n, [])
        trks = [t for t in board.GetTracks() if t.GetNetname() == n]
        parent = {}
        def find(x):
            while parent.setdefault(x, x) != x: parent[x] = parent[parent[x]]; x = parent[x]
            return x
        def union(a, c): parent[find(a)] = find(c)
        pt_layers = {}                                             # (x, y) -> set of layers touched by tracks / "via"
        for i, t in enumerate(trks):
            if t.Type() == pcbnew.PCB_VIA_T:
                key = (t.GetPosition().x, t.GetPosition().y); pt_layers.setdefault(key, {}).setdefault("via", []).append(("t", i))
            else:
                for q in (t.GetStart(), t.GetEnd()): pt_layers.setdefault((q.x, q.y), {}).setdefault(t.GetLayer(), []).append(("t", i))
        for key, byL in pt_layers.items():
            allitems = [it for lst in byL.values() for it in lst]
            if "via" in byL:                                       # a via joins everything at that point
                for it in allitems[1:]: union(allitems[0], it)
            else:
                for L, lst in byL.items():
                    for it in lst[1:]: union(lst[0], it)
        for uid, bb, th, layers in pads:
            for key, byL in pt_layers.items():
                if bb.Contains(pcbnew.VECTOR2I(*key)):
                    for L, lst in byL.items():
                        if L == "via" or th or L in layers: union(("p", uid), lst[0])
        out[n] = len({find(("p", uid)) for uid, *_ in pads}) if pads else 0
    return out
new_nets = {n for _, n, *_ in items}
before = clusters(b, new_nets)
old_items = {}                                                  # keep the old copper per net in case the session is worse
for t in list(b.GetTracks()):
    n = t.GetNetname()
    if not wanted(n): continue
    if t.Type() == pcbnew.PCB_VIA_T: old_items.setdefault(n, []).append(("via", n, (t.GetPosition().x, t.GetPosition().y), t.GetDrillValue(), t.GetWidth(pcbnew.F_Cu), None))
    else: old_items.setdefault(n, []).append(("trk", n, (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y), t.GetWidth(), t.GetLayer()))
    b.Remove(t)
removed = sum(len(v) for v in old_items.values())
def add_items(its):
    for kind, n, a, c, w, layer in its:
        if kind == "via":
            v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(*a)); v.SetDrill(c); v.SetWidth(w); v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(netmap[n]); b.Add(v)
        else:
            s_ = pcbnew.PCB_TRACK(b); s_.SetStart(pcbnew.VECTOR2I(*a)); s_.SetEnd(pcbnew.VECTOR2I(*c)); s_.SetWidth(w); s_.SetLayer(layer); s_.SetNet(netmap[n]); b.Add(s_)
add_items(items); added = len(items)
after = clusters(b, new_nets)
worse = [n for n in new_nets if after[n] > before.get(n, after[n])]
# nets the session left out entirely keep their old copper too
missing = [n for n in old_items if n not in new_nets]
for n in worse + missing:
    for t in list(b.GetTracks()):
        if t.GetNetname() == n: b.Remove(t)
    add_items(old_items.get(n, []))
if worse or missing: print(f"kept the previous copper of {len(worse)} nets the session made worse and {len(missing)} nets it dropped: {sorted(worse + missing)}")
pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b)
print(f"merged {added} items (removed {removed} old items)")
