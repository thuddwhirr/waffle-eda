#!/usr/bin/env python3
"""Export build/waffle.dsn for Freerouting with routing-friendly rules:
- the BGA rule area is dropped (KiCad exports every rule area as a keepout, which walls off the FPGA),
- every net class is narrowed to 0.10 mm track / 0.125 mm clearance (the router under-delivers clearance by ~0.02 mm; the board rule is 0.10 mm = PCBWay 4 mil) so tracks can escape the 0.8 mm BGA
  (widen.py restores the impedance widths outside the BGA afterwards),
- 0.45/0.20 mm vias everywhere,
- GND1/GND2 marked as power layers; PWR stays routable outside the 1V1/1V35/5V islands (keepouts), so 4 signal layers.
Freerouting settings (~/.freerouting or /tmp/freerouting/freerouting.json): router.max_threads = cores-1, fanout.enabled = true.
Usage: python3 hw/tools/export_dsn.py [build/waffle.dsn]"""
import os, sys, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HW, "..", "build", "waffle.dsn")
b = pcbnew.LoadBoard(os.path.join(HW, "waffle.kicad_pcb"))
mm = pcbnew.FromMM
POWER_REROUTE = os.environ.get("POWER_REROUTE")        # "1": route only the high-current nets, wide, everything else fixed
ROUTE_ONLY = os.environ.get("ROUTE_ONLY")              # regex: only nets matching stay in the network section (staged routing, D57)
FIX_NETS = os.environ.get("FIX_NETS")                  # regex: existing wires of matching nets are exported as fixed (already routed, keep)
WIDE = ["1V1_SW", "1V35_SW", "3V3_SW", "BUCK5_SW", "VIN", "VBUS_IN", "5V_USB1", "5V_USB2", "5V_USB3", "5V_HDMI"]
for name, nc in b.GetAllNetClasses().items():          # (must run before any board edit: the SWIG wrapper loses m_NetSettings afterwards)
    nc.SetTrackWidth(mm(0.5) if (POWER_REROUTE and name == "POWER") else mm(0.10))
    nc.SetClearance(mm(0.125))        # the router lands ~0.02 mm short of its clearance on 45-degree geometry; 0.125 keeps the result above the 0.10 mm fab minimum
    if os.environ.get("HS_CLR") and (str(name).startswith("DDR3") or str(name) in ("DIFF100", "USB90", "CLOCK")):
        nc.SetClearance(mm(float(os.environ["HS_CLR"])))   # staged routing: give the high-speed classes crosstalk spacing while the board is still empty
    nc.SetViaDiameter(mm(0.45)); nc.SetViaDrill(mm(0.20))
    nc.SetDiffPairWidth(mm(0.125)); nc.SetDiffPairGap(mm(0.15))
islands = []
for z in b.Zones():
    if z.GetLayer() == pcbnew.In3_Cu and z.GetNetname() != "3V3" and not z.GetIsRuleArea():
        bb = z.GetBoundingBox(); islands.append(tuple(pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())))
for z in list(b.Zones()):
    if z.GetIsRuleArea(): b.Remove(z)
if POWER_REROUTE:
    for t in list(b.GetTracks()):
        if t.GetNetname() in WIDE: b.Remove(t)
ok = pcbnew.ExportSpecctraDSN(b, out)
# plane layers as "power" so the router only drops vias into them instead of cutting the GND planes / power islands
import re
txt = open(out).read()
# D59: PWR is a plane layer too. Routing on it (99 nets, 3.3 m of track on the stage-2 board) had cut the 3V3 fill into
# 47 pieces; PWR_ROUTE=1 restores the old behaviour (PWR routable outside the islands) for comparison runs.
PLANE_LAYERS = ("GND1", "GND2", "GND3") if os.environ.get("PWR_ROUTE") else ("GND1", "GND2", "GND3", "PWR")
for L in PLANE_LAYERS:
    txt = re.sub(r"\(layer %s\n(\s*)\(type signal\)" % L, r"(layer %s\n\1(type power)" % L, txt)
# PWR stays a signal layer (4th routing layer) but the 1V1/1V35/5V islands are keepouts there, so only the 3V3 fill gets cut
keep = []
for (x0, y0, x1, y1) in islands:
    pts = " ".join(f"{int(x*1000)} {int(-y*1000)}" for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)))
    keep.append(f"    (keepout \"\" (polygon PWR 0  {pts}))")
# pre-routed escapes (bga_escape.py) must stay: mark every exported wire as fixed
# pre-route wires stay "(type route)": Freerouting 1.9 does not route nets that contain fix- or protect-typed wires (it dropped them from its SES as well)
i = txt.index("    (keepout")
txt = txt[:i] + "\n".join(keep) + "\n" + txt[i:]
if POWER_REROUTE:
    txt = txt.replace("(type route)", "(type fix)")     # everything else is done: fix it so the router only touches the wide nets
if ROUTE_ONLY:
    # Freerouting 1.9 treats every pre-existing wire as fixed as soon as any wire is typed "fix" and then routes only
    # nets without copper, so staging cannot use "fix". Instead the non-selected nets keep their name and wires (they
    # remain obstacles) but lose their pins, so there is nothing left for the router to connect on them.
    rx = re.compile(ROUTE_ONLY)
    txt = re.sub(r"\(net (\S+)\n(\s*)\(pins [^)]*\)\n", lambda m: m.group(0) if rx.match(m.group(1)) else f"(net {m.group(1)}\n{m.group(2)}(pins)\n", txt)
if FIX_NETS:
    rx = re.compile(FIX_NETS)
    txt = re.sub(r"(\((?:wire|via)[^\n]*\(net (\S+)\)[^\n]*)\(type route\)", lambda m: m.group(1) + ("(type fix)" if rx.match(m.group(2)) else "(type route)"), txt)
open(out, "w").write(txt)
print(f"PWR-layer keepouts for power islands: {len(keep)}")
print(f"ExportSpecctraDSN -> {ok}; keepouts in DSN: {txt.count('(keepout')}; classes: {txt.count('(class ')}")
