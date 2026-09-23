#!/usr/bin/env python3
"""Import a Freerouting session file (build/waffle.ses) into hw/waffle.kicad_pcb.
Usage: python3 hw/tools/import_ses.py [build/waffle.ses] [board.kicad_pcb]   (default board: hw/waffle.kicad_pcb)"""
import os, sys, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HW, "tools"))
from gen_pcb import inject_stackup, write_project
ses = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HW, "..", "build", "waffle.ses")
board = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HW, "waffle.kicad_pcb")
b = pcbnew.LoadBoard(board)
before = sum(1 for t in b.GetTracks())
ok = pcbnew.ImportSpecctraSES(b, ses)
after = sum(1 for t in b.GetTracks())
pcbnew.SaveBoard(board, b)
if len(sys.argv) <= 2: inject_stackup(board); write_project()
print(f"ImportSpecctraSES -> {ok}; tracks+vias {before} -> {after}")
