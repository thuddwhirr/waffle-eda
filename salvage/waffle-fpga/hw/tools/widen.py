#!/usr/bin/env python3
"""After a Freerouting import (routed at 0.125 mm everywhere): set every track segment that lies outside the
BGA rule area back to its net class width, then run DRC and narrow again any segment that now violates
clearance; repeat until DRC has no clearance errors on tracks.
Usage: python3 hw/tools/widen.py"""
import os, json, subprocess, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(HW, "waffle.kicad_pcb"); BUILD = os.path.join(HW, "..", "build")
NARROW = pcbnew.FromMM(0.125)

def bga_rect(b):
    rects = []
    for z in b.Zones():
        if z.GetIsRuleArea() and z.GetZoneName().startswith("BGA"):
            bb = z.GetBoundingBox(); m = pcbnew.FromMM(0.5)
            rects.append((bb.GetLeft() - m, bb.GetTop() - m, bb.GetRight() + m, bb.GetBottom() + m))
    return rects

def inside(rects, p):
    return any(r[0] <= p.x <= r[2] and r[1] <= p.y <= r[3] for r in rects)

def drc_clearance_tracks():
    rpt = os.path.join(BUILD, "drc_widen.json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-error", "--format", "json", "--output", rpt, BOARD], capture_output=True)
    d = json.load(open(rpt)); bad = set()
    for v in d.get("violations", []):
        if v.get("type") in ("clearance", "copper_edge_clearance", "hole_clearance", "solder_mask_bridge"):
            for it in v.get("items", []):
                if it.get("description", "").startswith("Track"): bad.add(it["uuid"])
    return bad, len(d.get("violations", []))

def main():
    b = pcbnew.LoadBoard(BOARD)
    widths = {k: nc.GetTrackWidth() for k, nc in b.GetAllNetClasses().items()}   # before any edit (SWIG quirk)
    rect = bga_rect(b)
    tracks = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
    widened = 0
    for t in tracks:
        if inside(rect, t.GetStart()) or inside(rect, t.GetEnd()): continue
        w = widths.get(t.GetNetClassName(), NARROW)
        if w > t.GetWidth(): t.SetWidth(w); widened += 1
    pcbnew.SaveBoard(BOARD, b)
    print(f"widened {widened} of {len(tracks)} segments outside the BGA area")
    for it in range(6):
        bad, total = drc_clearance_tracks()
        print(f"  DRC pass {it}: {total} error-level violations, {len(bad)} track segments to narrow")
        if not bad: break
        b = pcbnew.LoadBoard(BOARD); n = 0
        for t in b.GetTracks():
            if t.Type() == pcbnew.PCB_TRACE_T and t.m_Uuid.AsString() in bad and t.GetWidth() > NARROW:
                t.SetWidth(NARROW); n += 1
        pcbnew.SaveBoard(BOARD, b); print(f"  narrowed {n}")
        if n == 0: break

if __name__ == "__main__":
    main()
