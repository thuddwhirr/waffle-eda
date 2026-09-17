#!/usr/bin/env python3
"""Scripted finish for the links the autorouter left: for every pad with no copper, route to the nearest pad of its
net that has copper (or any other pad): same-layer grid route at 0.10 mm, else an inner-layer run between two vias.
Usage: python3 hw/tools/finish_links.py   (edits hw/waffle.kicad_pcb in place; run drc_cleanup afterwards)"""
import os, sys, pcbnew
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routing_lib import Router, mm
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); BOARD = os.path.join(HW, "waffle.kicad_pcb")
b = pcbnew.LoadBoard(BOARD); b.BuildConnectivity(); c = b.GetConnectivity()
R = Router(b)
zl = {}
for z in b.Zones():
    if not z.GetIsRuleArea(): zl.setdefault(z.GetNetname(), set()).add(z.GetLayer())
pads_by_net = {}
for f in b.GetFootprints():
    for p in f.Pads():
        if p.GetNetCode(): pads_by_net.setdefault(p.GetNetname(), []).append(p)
def has_copper(p): return len(c.GetConnectedTracks(p)) > 0 or (p.GetNetname() in zl and any(p.IsOnLayer(L) for L in zl[p.GetNetname()]))
done = failed = 0; fails = []
for net, pads in sorted(pads_by_net.items()):
    if len(pads) < 2: continue
    dry = [p for p in pads if not has_copper(p)]
    for p in dry:
        targets = sorted((q for q in pads if q is not p), key=lambda q: (not has_copper(q), abs(q.GetPosition().x - p.GetPosition().x) + abs(q.GetPosition().y - p.GetPosition().y)))
        ok = False
        for q in targets[:3]:
            a, d = p.GetPosition(), q.GetPosition(); lp, lq = R.layer_of(p), R.layer_of(q); netobj = p.GetNet()
            if lp == lq:
                pts = R.grid_route(net, a, d, mm(0.10), lp, skip=(p, q))
                if pts: R.lay(netobj, pts, mm(0.10), lp); ok = True; break
            va = R.via_near(net, p, mm(0.10)); vb = R.via_near(net, q, mm(0.10)) if va is not None else None
            if va is None or vb is None: continue
            for L in (pcbnew.In2_Cu, pcbnew.In5_Cu, pcbnew.B_Cu, pcbnew.F_Cu, pcbnew.In3_Cu):
                pts = R.grid_route(net, va, vb, mm(0.10), L, avoid_islands=(L == pcbnew.In3_Cu))
                if pts:
                    R.add_track(netobj, a, va, mm(0.10), lp); R.add_via(netobj, va); R.add_track(netobj, d, vb, mm(0.10), lq); R.add_via(netobj, vb); R.lay(netobj, pts, mm(0.10), L); ok = True; break
            if ok: break
        if ok: done += 1
        else: failed += 1; fails.append(f"{net}@{p.GetParentAsString()}")
    if (done + failed) % 25 == 0 and (done + failed): print(f"  progress: {done} routed, {failed} failed", flush=True)
pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b)
print(f"finish_links: {done} pads connected, {failed} still open"); print("open:", ", ".join(fails[:60]))
