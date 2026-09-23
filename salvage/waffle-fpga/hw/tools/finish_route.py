#!/usr/bin/env python3
"""Post-autoroute pipeline: import build/waffle.ses, fill zones, restore stack-up/project rules, plane vias for what the
router left dry, wide power nets, widen impedance tracks outside the BGAs, DRC, route report, renders. Usage: python3 hw/tools/finish_route.py [build/waffle.ses]"""
import os, sys, subprocess
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); ROOT = os.path.dirname(HW); T = os.path.join(HW, "tools")
ses = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "waffle.ses")
def run(*a): print("$", " ".join(a)); subprocess.run(list(a), check=False)
run("python3", os.path.join(T, "import_ses.py"), ses)
import pcbnew
board = os.path.join(HW, "waffle.kicad_pcb")
b = pcbnew.LoadBoard(board); pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(board, b); print("zones filled")
sys.path.insert(0, T); from gen_pcb import inject_stackup, write_project; inject_stackup(board); write_project()
run("python3", os.path.join(T, "plane_vias.py"))      # vias for plane pads the router still left dry
run("python3", os.path.join(T, "power_widen.py"))     # wide switch nodes / input rails, multi-via inductor outputs
run("python3", os.path.join(T, "drc_cleanup.py"))      # drop router copper that violates clearance
run("python3", os.path.join(T, "widen.py"))
run("kicad-cli", "pcb", "drc", "--severity-all", "--format", "report", "--output", os.path.join(ROOT, "build", "drc.rpt"), board)
run("python3", os.path.join(T, "route_report.py"))
run("kicad-cli", "pcb", "render", "--side", "top", "--zoom", "1", "--width", "2000", "--height", "1700", "--output", os.path.join(HW, "waffle-board-top.png"), board)
run("kicad-cli", "pcb", "render", "--side", "bottom", "--zoom", "1", "--width", "2000", "--height", "1700", "--output", os.path.join(HW, "waffle-board-bottom.png"), board)
