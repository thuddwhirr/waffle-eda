#!/usr/bin/env python3
"""Remove router copper that violates clearance: every track/via named in an error-level clearance,
hole-clearance or shorting violation is deleted (its net becomes unrouted there and shows in route-report.md).
Usage: python3 hw/tools/drc_cleanup.py"""
import os, json, subprocess, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(HW, "waffle.kicad_pcb"); rpt = os.path.join(HW, "..", "build", "drc_cleanup.json")
for it in range(4):
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "--format", "json", "--output", rpt, BOARD], capture_output=True)
    d = json.load(open(rpt)); bad = set()
    for v in d.get("violations", []):
        if v.get("type") in ("clearance", "hole_clearance", "shorting_items", "copper_edge_clearance", "items_not_allowed", "hole_to_hole", "holes_co_located"):
            for item in v.get("items", []):
                if item.get("description", "").startswith(("Track", "Via")): bad.add(item["uuid"])
    if not bad: print(f"pass {it}: no track/via clearance violations left"); break
    b = pcbnew.LoadBoard(BOARD); n = 0
    for t in list(b.GetTracks()):
        if t.m_Uuid.AsString() in bad: b.Remove(t); n += 1
    pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b); print(f"pass {it}: removed {n} tracks/vias")
