#!/usr/bin/env python3
"""Rip the routing of the named nets back to their pre-route state (BGA escapes / plane vias) so the router can redo them:
the nets' copper is removed from hw/waffle.kicad_pcb and replaced by their copper from a pre-route board file.
Usage: python3 hw/tools/rip_nets.py build/preroute.kicad_pcb NET [NET ...]   (or --regex REGEX)"""
import os, re, sys, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); BOARD = os.path.join(HW, "waffle.kicad_pcb")
pre = sys.argv[1]
if sys.argv[2] == "--regex":
    rx = re.compile(sys.argv[3]); wanted = lambda n: bool(rx.match(n))
else:
    nets = set(sys.argv[2:]); wanted = lambda n: n in nets
pb = pcbnew.LoadBoard(pre); items = []
for t in pb.GetTracks():
    n = t.GetNetname()
    if not wanted(n): continue
    if t.Type() == pcbnew.PCB_VIA_T: items.append(("via", n, (t.GetPosition().x, t.GetPosition().y), t.GetDrillValue(), t.GetWidth(pcbnew.F_Cu), None))
    else: items.append(("trk", n, (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y), t.GetWidth(), t.GetLayer()))
del pb
b = pcbnew.LoadBoard(BOARD); netmap = b.GetNetsByName(); removed = 0; ripped = set()
for t in list(b.GetTracks()):
    if wanted(t.GetNetname()): ripped.add(t.GetNetname()); b.Remove(t); removed += 1
for kind, n, a, c, w, layer in items:
    if kind == "via":
        v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(*a)); v.SetDrill(c); v.SetWidth(w); v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(netmap[n]); b.Add(v)
    else:
        s = pcbnew.PCB_TRACK(b); s.SetStart(pcbnew.VECTOR2I(*a)); s.SetEnd(pcbnew.VECTOR2I(*c)); s.SetWidth(w); s.SetLayer(layer); s.SetNet(netmap[n]); b.Add(s)
pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b)
print(f"ripped {len(ripped)} nets ({removed} items), restored {len(items)} pre-route items")
