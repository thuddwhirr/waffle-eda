#!/usr/bin/env python3
"""Repair the 3V3 distribution of an existing (possibly hand-edited) board without touching any track (D58).

The 3V3 rail has no plane of its own: it is the lowest-priority fill on PWR (In3), which the power islands and the
signal tracks routed on PWR cut into pieces. On the stage-2 board it was 47 pieces and the regulator's piece did not
reach the FPGA. This script only edits zones:
  1. the 1V35_feed / 1V1_feed islands become 4 mm strips straight down from their regulator to their consumer island
     (they were the bounding rectangles of the regulator-to-consumer diagonal, i.e. 19 x 60 mm walls);
  2. the 3V3 fill and the power islands get the board's minimum clearance (0.1 mm) and a 0.15 mm minimum width, so
     they pass between 0.8 mm-pitch via rows (the 1V1 core cluster inside the FPGA was cut off its feed otherwise);
  3. a 3V3 pour is added on B.Cu (lowest priority, 0.15 mm minimum width, 0.2 mm clearance): the back copper that no track uses
     becomes a second, differently-sliced 3V3 sheet, and every 3V3 via ties the two sheets together.
Then all zones are refilled and the number of 3V3 fill pieces is reported.
Usage: python3 hw/tools/fix_pwr_fill.py [board.kicad_pcb] [--no-bcu]      (default board: hw/waffle.kicad_pcb, edited in place)
BCU_CLR=0.1 sets the B.Cu pour clearance (default 0.2 mm, which keeps the pour a little further from the B.Cu signal tracks; 0.1 connects nothing more)."""
import os, sys, pcbnew
mm, FM = pcbnew.ToMM, pcbnew.FromMM
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
BOARD = args[0] if args else os.path.join(HW, "waffle.kicad_pcb")
b = pcbnew.LoadBoard(BOARD); netmap = b.GetNetsByName(); PWR = b.GetLayerID("In3.Cu")
zones = {z.GetZoneName(): z for z in b.Zones()}

def set_outline(z, pts):
    """replace the zone by a fresh one with the new outline: reshaping an existing zone's outline in place leaves the
    filler with stale obstacle data and its fill then covers vias in the added area"""
    n = pcbnew.ZONE(b); n.SetLayer(z.GetFirstLayer()); n.SetNet(z.GetNet()); n.SetZoneName(z.GetZoneName()); n.SetAssignedPriority(z.GetAssignedPriority())
    n.SetPadConnection(z.GetPadConnection()); n.SetMinThickness(z.GetMinThickness()); n.SetLocalClearance(z.GetLocalClearance())
    n.Outline().NewOutline()
    for x, y in pts: n.Outline().Append(FM(x), FM(y))
    b.Remove(z); b.Add(n); zones[n.GetZoneName()] = n; return n
def rect(x0, y0, x1, y1): return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
def centre(ref):
    f = b.FindFootprintByReference(ref); return mm(f.GetPosition().x), mm(f.GetPosition().y)
def top_of(zname): return mm(zones[zname].GetBoundingBox().GetTop())

# 1. feeds: a 4 mm strip from the regulator's centre straight down, 2 mm into the consumer island (islands overlap
#    at distinct priorities, which KiCad accepts for same-net zones)
#    The last 6 mm above each consumer island is a wider block (the decoupling capacitors and plane vias of that rail sit
#    there), so the rail's vias placed against the old rectangles still land in their copper.
for feed, reg, island, x0, x1 in (("1V35_feed", "U20", "1V35_ddr", 18.5, 41.0), ("1V1_feed", "U21", "1V1_core", 42.0, 62.0)):
    if feed in zones and island in zones and b.FindFootprintByReference(reg):
        rx, ry = centre(reg); top = top_of(island)
        set_outline(zones[feed], ((rx - 2, ry - 2), (rx + 2, ry - 2), (rx + 2, top - 6), (x1, top - 6), (x1, top + 2), (x0, top + 2), (x0, top - 6), (rx - 2, top - 6)))
        print(f"{feed}: strip x {rx - 2:.1f}..{rx + 2:.1f} from y {ry - 2:.1f}, block x {x0}..{x1} at y {top - 6:.1f}..{top + 2:.1f}")
# 1b. the 1V35 island reaches 8 mm below the DRAM: its decoupling capacitors (C52, C55, C56, C60, C62) sit there
if "1V35_ddr" in zones:
    z = zones["1V35_ddr"]; bb = z.GetBoundingBox(); x0, y0, x1, y1 = (mm(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
    if y1 < 98.0: set_outline(z, rect(x0, y0, x1, 98.0)); print(f"1V35_ddr: bottom edge {y1:.1f} -> 98.0")
# 2. the 3V3 fill and the islands at the board's minimum clearance and a width that passes between 0.8 mm via rows
#    (at 0.125 / 0.2 the rings of VCCIO and GND dog-bone vias inside the FPGA cut the 1V1 core cluster off its feed;
#    the GND planes go from 80 to 86 % copper under the FPGA and from 8 to 5 pieces)
for name in ("3V3_fill", "1V1_core", "1V1_feed", "1V35_ddr", "1V35_feed", "GND_GND1", "GND_GND2", "GND_GND3"):
    if name in zones: zones[name].SetLocalClearance(FM(0.1)); zones[name].SetMinThickness(FM(0.15))
# 3. a B.Cu 3V3 pour (added once)
if "--no-bcu" not in sys.argv and "3V3_back" not in zones and "3V3" in netmap:
    bb = b.GetBoardEdgesBoundingBox()
    z = pcbnew.ZONE(b); z.SetLayer(pcbnew.B_Cu); z.SetNet(netmap["3V3"]); z.SetZoneName("3V3_back"); z.SetAssignedPriority(0)
    z.Outline().NewOutline()
    for x, y in rect(mm(bb.GetLeft()) + 0.5, mm(bb.GetTop()) + 0.5, mm(bb.GetRight()) - 0.5, mm(bb.GetBottom()) - 0.5): z.Outline().Append(FM(x), FM(y))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL); z.SetThermalReliefGap(FM(0.25)); z.SetThermalReliefSpokeWidth(FM(0.3))
    z.SetLocalClearance(FM(float(os.environ.get("BCU_CLR", "0.2")))); z.SetMinThickness(FM(0.15)); b.Add(z); zones["3V3_back"] = z
    print("added 3V3_back pour on B.Cu")
pcbnew.ZONE_FILLER(b).Fill(b.Zones())

def pieces(z, layer):
    p = z.GetFilledPolysList(layer); return p, p.OutlineCount()
for name, layer in (("3V3_fill", PWR), ("3V3_back", pcbnew.B_Cu), ("1V1_core", PWR), ("1V35_ddr", PWR)):
    if name not in zones: continue
    NET = zones[name].GetNetname()
    polys, n = pieces(zones[name], layer)
    vias = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == NET]
    def which(x, y):
        pt = pcbnew.VECTOR2I(FM(x), FM(y))
        for i in range(n):
            if polys.Outline(i).PointInside(pt): return i
    biggest = max(range(n), key=lambda i: abs(polys.Outline(i).Area()))
    inbig = sum(1 for t in vias if which(mm(t.GetPosition().x), mm(t.GetPosition().y)) == biggest)
    print(f"{name}: {n} pieces; the largest holds {inbig} of {len(vias)} {NET} vias")
pcbnew.SaveBoard(BOARD, b); print("saved", BOARD)
