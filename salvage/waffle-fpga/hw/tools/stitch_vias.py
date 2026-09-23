#!/usr/bin/env python3
"""Return-path stitching: for every via on a high-speed net (DDR3, TMDS, USB, clocks) add a GND via within ~1 mm if
none is there yet, and add a GND stitching grid (8 mm pitch) wherever the board is free. Uses routing_lib's
clearance checks. Usage: python3 hw/tools/stitch_vias.py"""
import os, sys, math, pcbnew
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routing_lib import Router, mm, DRILL
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); BOARD = os.path.join(HW, "waffle.kicad_pcb")
HS = ("DDR3_", "HDMI_D", "HDMI_CLK", "USB_UP_D", "HUB_UP_D", "HUB_DN", "USB1_D", "USB2_D", "USB3_D", "J1_D", "CLK27", "CLK_SI5351", "ULPI_CLK", "I2S_MCLK")
b = pcbnew.LoadBoard(BOARD); R = Router(b); gnd = b.GetNetsByName()["GND"]
gnd_vias = [t.GetPosition() for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == "GND"]
def has_gnd_near(p, r): return any(math.hypot(g.x - p.x, g.y - p.y) < r for g in gnd_vias)
added = 0; missing = 0
for t in list(b.GetTracks()):
    if t.Type() != pcbnew.PCB_VIA_T or not t.GetNetname().startswith(HS): continue
    p = t.GetPosition()
    if has_gnd_near(p, mm(1.5)): continue
    ok = False
    for dist in (mm(0.85), mm(1.1), mm(1.4)):
        for k in range(12):
            a = k * 2 * math.pi / 12
            v = pcbnew.VECTOR2I(int(p.x + dist * math.cos(a)), int(p.y + dist * math.sin(a)))
            if R.via_clear("GND", v): R.add_via(gnd, v); gnd_vias.append(v); added += 1; ok = True; break
        if ok: break
    if not ok: missing += 1
# stitching grid
grid = 0
e = b.GetBoardEdgesBoundingBox()
y = e.GetTop() + mm(6)
while y < e.GetBottom() - mm(6):
    x = e.GetLeft() + mm(6)
    while x < e.GetRight() - mm(6):
        v = pcbnew.VECTOR2I(int(x), int(y))
        if not has_gnd_near(v, mm(4)) and R.via_clear("GND", v): R.add_via(gnd, v); gnd_vias.append(v); grid += 1
        x += mm(8)
    y += mm(8)
pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b)
print(f"stitch_vias: {added} return-path GND vias next to high-speed layer changes ({missing} had no room), {grid} grid stitching vias")
