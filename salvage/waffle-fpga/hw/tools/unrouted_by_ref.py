#!/usr/bin/env python3
"""Count remaining airwires per footprint and per net from a KiCad DRC JSON run on the given board.
Usage: python3 hw/tools/unrouted_by_ref.py [board.kicad_pcb]"""
import os, sys, json, subprocess, re, collections
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
board = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HW, "waffle.kicad_pcb")
rpt = os.path.join(HW, "..", "build", "drc_unrouted.json")
subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "--format", "json", "--output", rpt, board], capture_output=True)
d = json.load(open(rpt))
by_ref = collections.Counter(); by_net = collections.Counter(); n = 0
for u in d.get("unconnected_items", []):
    n += 1
    for it in u.get("items", []):
        m = re.match(r"Pad \S+ \[(.*?)\] of (\S+)", it.get("description", ""))
        if m: by_ref[m.group(2)] += 1; by_net[m.group(1)] += 1
        else:
            m2 = re.search(r"\[(.*?)\]", it.get("description", ""))
            if m2: by_net[m2.group(1)] += 1
print(f"airwires: {n}")
print("by footprint:", ", ".join(f"{r}:{c}" for r, c in by_ref.most_common(15)))
print("by net (top):", ", ".join(f"{r}:{c}" for r, c in by_net.most_common(15)))
