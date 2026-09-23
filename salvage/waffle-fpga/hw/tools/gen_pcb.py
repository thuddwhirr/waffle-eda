#!/usr/bin/env python3
"""
Create hw/waffle.kicad_pcb from the exported schematic netlist:
footprints with nets, 6-layer stack-up, board outline + mounting holes,
BGA rule area, and a first functional floorplan (block areas per sheet).
Placement is a starting point for interactive layout, not a final layout.

    python3 hw/tools/build.py        # (schematic, netlist)
    python3 hw/tools/gen_pcb.py      # board
"""
import os, sys, math, json, re
from collections import defaultdict
import pcbnew
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from impedance import PCBWAY_8L, geometry8
GEO = geometry8(PCBWAY_8L)          # D55: 8-layer build
W50, W100, G100, W90, W50S, W100S, G100S = GEO["SE50_L1"][0], GEO["DIFF100_L1"][0], GEO["DIFF100_L1"][1], GEO["DIFF90_L1"][0], GEO["SE50_L3"][0], GEO["DIFF100_L3"][0], GEO["DIFF100_L3"][1]
HERE = os.path.dirname(os.path.abspath(__file__)); HW = os.path.dirname(HERE); ROOT = os.path.dirname(HW)
sys.path.insert(0, HERE)
from sexp import loads, findall, find
import importlib.util
spec = importlib.util.spec_from_file_location("design", os.path.join(HW, "design.py")); design = importlib.util.module_from_spec(spec); spec.loader.exec_module(design)
D = design.D

FP_STOCK = "/usr/share/kicad/footprints"
FP_LOCAL = {"waffle": os.path.join(HW, "lib", "waffle.pretty")}
BOARD_W, BOARD_H = 100.0, 160.0          # mm, Eurocard 3U (D56); front edge = y = BOARD_H (case front end panel), back edge = y = 0
mm = pcbnew.FromMM
V = pcbnew.VECTOR2I_MM

# ---------------------------------------------------------------------------
# functional floorplan: anchor positions (mm) and rotations for the big parts,
# block rectangles for each sheet's passives. Package orientation per D3:
# FPGA rotated 180 deg (A1 at front-right).
# ---------------------------------------------------------------------------
ANCHORS = {
    # D56 floorplan, Eurocard 100 x 160 mm (x across, y along; y = 0 is the back end panel, y = 160 the front).
    # FPGA centre, DRAM on its left (banks 2/3), STM32 in front of it at the left facing bank 1 (FMC), USB hub between the
    # STM32 and the left-edge USB ports, PHY between STM32 and FPGA; power entry + eFuse back-left, buck row back-centre,
    # FT2232 behind the DRAM near the uplink port, config flash by the config bank (FPGA back-right), HDMI back-right with
    # its companion, ESP32 in front of the FPGA (bank 0), codec front-left by the jacks, LED row and buttons at the front.
    "U1": (50, 80, 180), "U2": (26, 82, 0),
    "U4": (24, 112, 0), "BT1": (24, 114, 0, "back"), "Y2": (20, 130, 0), "U5": (44, 104, 180), "Y5": (50, 100, 0), "U6": (18, 72, 180), "Y4": (18, 79, 0),
    "U16": (26, 16, 0), "U17": (26, 26, 0), "U7": (32, 42, 90), "Y6": (32, 52, 0), "U22": (26, 66, 0), "J16": (6, 98, 90), "J17": (6, 122, 90),
    "U18": (40, 16, 0), "L1": (50, 16, 0), "U19": (60, 16, 0), "L2": (66, 16, 0), "U20": (40, 26, 0), "L3": (46, 26, 0), "U21": (54, 26, 0), "L4": (60, 26, 0),
    "U3": (66, 58, 0), "SW1": (76, 58, 0), "Y1": (68, 66, 0), "U15": (80, 16, 0), "U8": (60, 118, 180), "J18": (80, 100, 0),
    "U9": (12, 134, 0), "U10": (40, 132, 180), "Y3": (40, 138, 0), "U14": (60, 138, 0),
    **{f"LED{n}": (x, 146, 0) for n, x in zip((3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2), range(46, 90, 4))},
}
# edge connectors: (edge, position along edge)   edge in front/back/left/right
EDGE_ROT = {"J15": 90, "J16": 90, "J17": 90, "J9": 180, "J10": 180,            # jacks: plug opening is the narrow neck at -y in the footprint
            "SW2": 180, "SW3": 180, "SW4": 180, "SW5": 180, "SW6": 180}        # angled tactiles: actuator is at -y in the footprint
EDGE = {
    # back end panel: USB-C power | USB-C uplink | HDMI
    "J1": ("back", 14), "J2": ("back", 26), "J6": ("back", 80),
    # front end panel: USB-C host | audio jacks | PWR RST BTN0 BTN1 BTN2
    "J3": ("front", 13.5), "J9": ("front", 25), "J10": ("front", 36.5), "SW2": ("front", 47.5), "SW3": ("front", 57.2), "SW4": ("front", 66.9), "SW5": ("front", 76.6), "SW6": ("front", 86.3),
    # left side: two microSD, stacked dual USB-A
    "J7": ("left", 20), "J8": ("left", 36), "J4": ("left", 54),
    # right side: PMOD A-D and the 2x20 header (all FPGA GPIO on the bank 6/7 side)
    "J11": ("right", 22), "J12": ("right", 40), "J13": ("right", 58), "J14": ("right", 76), "J15": ("right", 110),
}
# extra outward shift (mm) for edge parts whose drawn overhang is not the mating face: the angled tactiles are placed with the
# switch body flush with the board edge so the whole actuator protrudes (fab drawing tip = actuator tip)
CORRIDORS = [(30.5, 72.0, 41.4, 92.0)]      # DRAM (U2 at x 26) -> FPGA (U1 west edge x 41.5) DDR3 corridor, mm
EDGE_PUSH = {"SW2": 3.0, "SW3": 3.0, "SW4": 3.0, "SW5": 3.0, "SW6": 3.0}
# passives block areas per sheet: (x0, y0, x1, y1)
BLOCKS = {
    "power": (34, 8, 70, 40), "fpga_pwr": (36, 60, 66, 100), "fpga_io": (36, 60, 66, 100), "config": (20, 30, 84, 70), "ddr3": (10, 60, 36, 100),
    "stm32": (4, 95, 50, 130), "usb": (4, 40, 40, 80), "clocks_audio": (4, 120, 60, 150), "expansion": (60, 90, 96, 150),
}

def load_fp(lib_id):
    lib, name = lib_id.split(":", 1)
    path = FP_LOCAL.get(lib, os.path.join(FP_STOCK, lib + ".pretty"))
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise KeyError(f"footprint {lib_id} not found in {path}")
    return fp

def read_netlist(path):
    doc = loads(open(path).read())
    comps = {}
    for c in findall(find(doc, "components"), "comp"):
        comps[find(c, "ref")[1]] = dict(value=find(c, "value")[1], footprint=find(c, "footprint")[1] if find(c, "footprint") else "")
    nets = {}
    for n in findall(find(doc, "nets"), "net"):
        nets[find(n, "name")[1]] = [(find(x, "ref")[1], find(x, "pin")[1]) for x in findall(n, "node")]
    return comps, nets

def fp_bbox_mm(fp):
    bb = fp.GetBoundingBox(False, False)
    return (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))

def place_edge(fp, edge, along, keep_rot=False):
    """Place an edge connector with its body overhang facing the board edge."""
    if not keep_rot:
        fp.SetOrientationDegrees(0)
    fp.SetPosition(V(0, 0))
    # direction from pad centroid to bbox centre = where the body/mating face is
    pads = [p.GetPosition() for p in fp.Pads()]
    cx = sum(p.x for p in pads) / len(pads); cy = sum(p.y for p in pads) / len(pads)
    x0, y0, x1, y1 = fp_bbox_mm(fp); bx, by = (x0 + x1) / 2 * 1e6, (y0 + y1) / 2 * 1e6
    vx, vy = bx - cx, by - cy
    face = "down" if abs(vy) >= abs(vx) and vy > 0 else "up" if abs(vy) >= abs(vx) else "right" if vx > 0 else "left"
    want = {"front": "down", "back": "up", "left": "left", "right": "right"}[edge]
    if os.environ.get("EDGE_DEBUG"): print(f"  {fp.GetReference():4} {edge:5} face={face:5} pads=({pcbnew.ToMM(int(cx)):.1f},{pcbnew.ToMM(int(cy)):.1f}) bbox=({x0:.1f},{y0:.1f},{x1:.1f},{y1:.1f})")
    order = ["up", "right", "down", "left"]                     # clockwise in screen coords (y down)
    def face_of(fp):
        pads = [p.GetPosition() for p in fp.Pads()]
        cx = sum(p.x for p in pads) / len(pads); cy = sum(p.y for p in pads) / len(pads)
        x0, y0, x1, y1 = fp_bbox_mm(fp); vx, vy = (x0 + x1) / 2 * 1e6 - cx, (y0 + y1) / 2 * 1e6 - cy
        return "down" if abs(vy) >= abs(vx) and vy > 0 else "up" if abs(vy) >= abs(vx) else "right" if vx > 0 else "left"
    if not keep_rot:
        # try the four orientations and keep the one whose body faces the edge (sign convention independent)
        for ang in (0, 90, 180, 270):
            fp.SetOrientationDegrees(ang); fp.SetPosition(V(0, 0))
            if face_of(fp) == want: break
    fp.SetPosition(V(0, 0))
    x0, y0, x1, y1 = fp_bbox_mm(fp); cxm, cym = (x0 + x1) / 2, (y0 + y1) / 2
    if edge == "front":   pos = (along - cxm, BOARD_H - y1 + 0.2)
    elif edge == "back":  pos = (along - cxm, -y0 - 0.2)
    elif edge == "left":  pos = (-x0 - 0.2, along - cym)
    else:                 pos = (BOARD_W - x1 + 0.2, along - cym)
    push = EDGE_PUSH.get(fp.GetReference(), 0.0)
    pos = {"front": (pos[0], pos[1] + push), "back": (pos[0], pos[1] - push), "left": (pos[0] - push, pos[1]), "right": (pos[0] + push, pos[1])}[edge]
    fp.SetPosition(V(*pos))

# PCBWay 6-layer 1.6 mm structure #1 (see impedance.py); thicknesses after lamination
STACKUP = f"""	(stackup
		(layer "F.SilkS" (type "Top Silk Screen"))
		(layer "F.Paste" (type "Top Solder Paste"))
		(layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))
		(layer "F.Cu" (type "copper") (thickness {PCBWAY_8L['L1']}))
		(layer "dielectric 1" (type "prepreg") (thickness {PCBWAY_8L['pp12']}) (material "FR4 2116") (epsilon_r {PCBWAY_8L['dk12']}) (loss_tangent 0.02))
		(layer "In1.Cu" (type "copper") (thickness {PCBWAY_8L['inner_cu']}))
		(layer "dielectric 2" (type "core") (thickness {PCBWAY_8L['core23']}) (material "FR4") (epsilon_r {PCBWAY_8L['dk23']}) (loss_tangent 0.02))
		(layer "In2.Cu" (type "copper") (thickness {PCBWAY_8L['inner_cu']}))
		(layer "dielectric 3" (type "prepreg") (thickness {PCBWAY_8L['pp34']}) (material "FR4 7628") (epsilon_r {PCBWAY_8L['dk34']}) (loss_tangent 0.02))
		(layer "In3.Cu" (type "copper") (thickness {PCBWAY_8L['inner_cu']}))
		(layer "dielectric 4" (type "core") (thickness {PCBWAY_8L['core45']}) (material "FR4") (epsilon_r {PCBWAY_8L['dk45']}) (loss_tangent 0.02))
		(layer "In4.Cu" (type "copper") (thickness {PCBWAY_8L['inner_cu']}))
		(layer "dielectric 5" (type "prepreg") (thickness {PCBWAY_8L['pp56']}) (material "FR4 7628") (epsilon_r {PCBWAY_8L['dk56']}) (loss_tangent 0.02))
		(layer "In5.Cu" (type "copper") (thickness {PCBWAY_8L['inner_cu']}))
		(layer "dielectric 6" (type "core") (thickness {PCBWAY_8L['core67']}) (material "FR4") (epsilon_r {PCBWAY_8L['dk67']}) (loss_tangent 0.02))
		(layer "In6.Cu" (type "copper") (thickness {PCBWAY_8L['inner_cu']}))
		(layer "dielectric 7" (type "prepreg") (thickness {PCBWAY_8L['pp78']}) (material "FR4 2116") (epsilon_r {PCBWAY_8L['dk78']}) (loss_tangent 0.02))
		(layer "B.Cu" (type "copper") (thickness {PCBWAY_8L['L8']}))
		(layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01))
		(layer "B.Paste" (type "Bottom Solder Paste"))
		(layer "B.SilkS" (type "Bottom Silk Screen"))
		(copper_finish "ENIG")
		(dielectric_constraints no)
	)
"""

def inject_stackup(path):
    txt = open(path).read()
    if "(stackup" in txt:
        return
    i = txt.index("(setup")
    j = txt.index("\n", i) + 1
    open(path, "w").write(txt[:j] + STACKUP + txt[j:])

def write_project():
    """Net classes + board rules go into the .kicad_pro (KiCad rewrites this file on every
    kicad-cli run, so the generator re-applies them each time)."""
    pro_path = os.path.join(HW, "waffle.kicad_pro")
    pro = json.load(open(pro_path)) if os.path.exists(pro_path) else {"meta": {"filename": "waffle.kicad_pro", "version": 3}}
    base = {"bus_width": 12, "clearance": 0.10, "diff_pair_gap": 0.15, "diff_pair_via_gap": 0.25, "diff_pair_width": 0.15, "line_style": 0,
            "microvia_diameter": 0.3, "microvia_drill": 0.1, "name": "Default", "pcb_color": "rgba(0, 0, 0, 0.000)", "priority": 2147483647,
            "schematic_color": "rgba(0, 0, 0, 0.000)", "track_width": 0.15, "via_diameter": 0.5, "via_drill": 0.25, "wire_width": 6}
    def cls(name, prio, **kw):
        c = dict(base); c.update(name=name, priority=prio); c.update(kw); return c
    classes = [cls("Default", 2147483647),
               cls("POWER", 0, clearance=0.10, track_width=0.5, via_diameter=0.6, via_drill=0.3),
               cls("DIFF100", 1, track_width=W100, diff_pair_width=W100, diff_pair_gap=G100, via_diameter=0.45, via_drill=0.2),
               cls("USB90", 2, track_width=W90, diff_pair_width=W90, diff_pair_gap=G100, via_diameter=0.45, via_drill=0.2),
               cls("DDR3_DQ0", 3, track_width=W50, diff_pair_width=W100, diff_pair_gap=G100, via_diameter=0.45, via_drill=0.2),
               cls("DDR3_DQ1", 4, track_width=W50, diff_pair_width=W100, diff_pair_gap=G100, via_diameter=0.45, via_drill=0.2),
               cls("DDR3_AC", 5, track_width=W50S, diff_pair_width=W100S, diff_pair_gap=G100S, via_diameter=0.45, via_drill=0.2),
               cls("CLOCK", 6, clearance=0.10, track_width=W50, via_diameter=0.45, via_drill=0.2)]
    patterns = [("POWER", "GND"), ("POWER", "VIN"), ("POWER", "VBUS_IN"), ("POWER", "5V_SYS"), ("POWER", "3V3"), ("POWER", "3V3_STBY"), ("POWER", "3V3A"),
                ("POWER", "1V35"), ("POWER", "1V1"), ("POWER", "2V5"), ("POWER", "VTT"), ("POWER", "5V_USB*"), ("POWER", "5V_HDMI"), ("POWER", "*_SW"),
                ("DIFF100", "HDMI_D*"), ("DIFF100", "HDMI_CLK_*"), ("DIFF100", "DDR3_DQS_*"),
                ("USB90", "USB_UP_D*"), ("USB90", "HUB_*_D?"), ("USB90", "USB?_D?"), ("USB90", "J1_D?"),
                ("DDR3_DQ0", "DDR3_DQ?"), ("DDR3_DQ0", "DDR3_DM0"), ("DDR3_DQ1", "DDR3_DQ??"), ("DDR3_DQ1", "DDR3_DM1"),
                ("DDR3_AC", "DDR3_A*"), ("DDR3_AC", "DDR3_BA*"), ("DDR3_AC", "DDR3_RAS_N"), ("DDR3_AC", "DDR3_CAS_N"), ("DDR3_AC", "DDR3_WE_N"),
                ("DDR3_AC", "DDR3_CS_N"), ("DDR3_AC", "DDR3_CKE"), ("DDR3_AC", "DDR3_ODT"), ("DDR3_AC", "DDR3_RESET_N"), ("DDR3_AC", "DDR3_CLK_*"),
                ("CLOCK", "CLK27*"), ("CLOCK", "CLK_SI5351"), ("CLOCK", "I2S_MCLK"), ("CLOCK", "ULPI_CLK"), ("CLOCK", "SD?_CLK"), ("CLOCK", "ESP_SDIO_CLK"), ("CLOCK", "FLASH_SCK")]
    pro["net_settings"] = {"classes": classes, "meta": {"version": 4}, "net_colors": None, "netclass_assignments": None,
                           "netclass_patterns": [{"netclass": c, "pattern": p} for c, p in patterns]}
    ds = pro.setdefault("board", {}).setdefault("design_settings", {})
    rules = ds.setdefault("rules", {})
    rules.update({"min_clearance": 0.10, "min_connection": 0.0, "min_copper_edge_clearance": 0.3, "min_hole_clearance": 0.20, "min_hole_to_hole": 0.25,
                  "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1, "min_resolved_spokes": 2, "min_silk_clearance": 0.0, "min_text_height": 0.8,
                  "min_text_thickness": 0.08, "min_through_hole_diameter": 0.2, "min_track_width": 0.1, "min_via_annular_width": 0.1, "min_via_diameter": 0.45,
                  "solder_mask_to_copper_clearance": 0.0, "use_height_for_length_calcs": True})
    ds.setdefault("rule_severities", {})["unconnected_items"] = "warning"
    ds["track_widths"] = [0.0, 0.125, 0.15, W100, W90, W50, 0.25, 0.5]; ds["via_dimensions"] = [{"diameter": 0.0, "drill": 0.0}, {"diameter": 0.45, "drill": 0.2}, {"diameter": 0.5, "drill": 0.25}, {"diameter": 0.6, "drill": 0.3}]
    ds["diff_pair_dimensions"] = [{"gap": 0.0, "via_gap": 0.0, "width": 0.0}, {"gap": G100, "via_gap": 0.25, "width": W100}, {"gap": G100, "via_gap": 0.25, "width": W90}, {"gap": G100S, "via_gap": 0.25, "width": W100S}]
    json.dump(pro, open(pro_path, "w"), indent=2)

def main():
    comps, nets = read_netlist(os.path.join(ROOT, "build", "sch", "waffle.net"))
    b = pcbnew.BOARD()
    ds = b.GetDesignSettings()
    ds.SetCopperLayerCount(8)
    ds.m_MinClearance = mm(0.125); ds.m_TrackMinWidth = mm(0.125); ds.m_ViasMinSize = mm(0.45); ds.m_MinThroughDrill = mm(0.2)
    ds.m_ViasMinAnnularWidth = mm(0.1); ds.m_CopperEdgeClearance = mm(0.3); ds.m_SolderMaskMinWidth = mm(0.1); ds.m_HoleClearance = mm(0.25)
    ds.m_MinSilkTextHeight = mm(0.8)
    # layer names
    for lid, name in ((pcbnew.In1_Cu, "GND1"), (pcbnew.In2_Cu, "SIG2"), (pcbnew.In3_Cu, "PWR"), (pcbnew.In4_Cu, "GND2"), (pcbnew.In5_Cu, "SIG3"), (pcbnew.In6_Cu, "GND3")):
        b.SetLayerName(lid, name)
    # stack-up is written into the saved file as text (the stackup descriptor is not exposed by SWIG here)
    # nets
    netmap = {}
    for name in nets:
        ni = pcbnew.NETINFO_ITEM(b, name); b.Add(ni); netmap[name] = ni
    pad_net = {}
    for name, nodes in nets.items():
        for ref, pin in nodes: pad_net[(ref, pin)] = name
    # footprints
    missing = []
    fps = {}
    for ref, c in comps.items():
        if not c["footprint"]:
            missing.append(ref); continue
        try:
            fp = load_fp(c["footprint"])
        except Exception as e:
            missing.append(f"{ref}:{c['footprint']}"); continue
        fp.SetReference(ref); fp.SetValue(c["value"]); b.Add(fp); fps[ref] = fp
        if re.match(r"^(R|C|L|LED|FB|D)\d+$", ref):
            fp.Reference().SetLayer(pcbnew.F_Fab)
        for pad in fp.Pads():
            n = pad_net.get((ref, pad.GetNumber()))
            if n: pad.SetNet(netmap[n])
    # placement -------------------------------------------------------------
    sheet_of = {ref: list(p.unit_sheets.values())[0] for ref, p in D.parts.items()}
    CELL = 0.5
    occ = set()          # occupied grid cells (front side) ; back side tracked separately
    occ_b = set()
    def cells(x0, y0, x1, y1):
        for gx in range(int(math.floor(x0 / CELL)), int(math.ceil(x1 / CELL))):
            for gy in range(int(math.floor(y0 / CELL)), int(math.ceil(y1 / CELL))):
                yield (gx, gy)
    def mark(fp, back=False):
        x0, y0, x1, y1 = fp_bbox_mm(fp)
        (occ_b if back else occ).update(cells(x0 - 0.3, y0 - 0.3, x1 + 0.3, y1 + 0.3))
        if any(p.GetDrillSize().x > 0 for p in fp.Pads()):          # through-hole parts block the other side too
            (occ if back else occ_b).update(cells(x0 - 0.3, y0 - 0.3, x1 + 0.3, y1 + 0.3))
    def free(x0, y0, x1, y1, back=False):
        o = occ_b if back else occ
        return not any(c in o for c in cells(x0, y0, x1, y1))
    # keep-out margins along the edges for the edge connectors and mounting holes
    for (x, y) in ((4, 4), (BOARD_W - 4, 4), (4, BOARD_H - 4), (BOARD_W - 4, BOARD_H - 4)):
        occ.update(cells(x - 4, y - 4, x + 4, y + 4)); occ_b.update(cells(x - 4, y - 4, x + 4, y + 4))
    # routing corridors stay free of parts on both sides (D57): the DDR3 group runs straight from the DRAM's east edge to the
    # FPGA's west edge on the inner layers, and any part there (decoupling, its vias) forces the 92 nets round it
    for (x0, y0, x1, y1) in CORRIDORS:
        occ.update(cells(x0, y0, x1, y1)); occ_b.update(cells(x0, y0, x1, y1))
    # assembly fiducials: three per side, asymmetric, in edge gaps the connectors leave free (D57); marked so nothing lands on them
    for i, (x, y) in enumerate(((36, 6), (BOARD_W - 6, 144), (6, 140))):
        for side in ("F", "B"):
            f = pcbnew.FootprintLoad(os.path.join(FP_STOCK, "Fiducial.pretty"), "Fiducial_1mm_Mask3mm")
            f.SetReference(f"FID{i+1}{side}"); b.Add(f); f.SetPosition(V(x, y))
            if side == "B": f.Flip(V(x, y), False)
            mark(f, side == "B")
    placed_first = []; overflow = []; nudged = []
    # KiCad's Micron FBGA-96 footprint has 0.52 mm pads, which leaves no room for a 0.45 mm via between four balls
    # (diagonal gap 0.61 mm < 0.65 needed at 0.10 mm clearance); 0.40 mm pads (Micron TN-00-15 NSMD sizing) do.
    if "U2" in fps:
        for p in fps["U2"].Pads(): p.SetSize(pcbnew.VECTOR2I(mm(0.40), mm(0.40)))
    for ref, fp in fps.items():                      # 1. edge connectors are fixed
        if ref in EDGE:
            place_edge(fp, *EDGE[ref])
            if ref in EDGE_ROT:
                fp.SetOrientationDegrees(EDGE_ROT[ref]); place_edge(fp, *EDGE[ref], keep_rot=True)
            mark(fp); placed_first.append(ref)
    for ref in ANCHORS:                              # 2. anchored parts in ANCHORS order (big parts first), nudged to the nearest free spot
        fp = fps.get(ref)
        if fp is not None:
            a = ANCHORS[ref]; x, y, rot = a[0], a[1], a[2]; back = len(a) > 3 and a[3] == "back"
            if back: fp.Flip(V(0, 0), False)
            fp.SetOrientationDegrees(rot); fp.SetPosition(V(x, y))
            bx0, by0, bx1, by1 = fp_bbox_mm(fp)
            ok = free(bx0 - 0.3, by0 - 0.3, bx1 + 0.3, by1 + 0.3, back)
            if not ok:
                for r in range(1, 30):
                    for dx, dy in sorted({(i, j) for i in range(-r, r + 1) for j in range(-r, r + 1) if max(abs(i), abs(j)) == r}, key=lambda t: t[0] * t[0] + t[1] * t[1]):
                        fp.SetPosition(V(x + dx, y + dy)); bx0, by0, bx1, by1 = fp_bbox_mm(fp)
                        if bx0 > 3 and by0 > 3 and bx1 < BOARD_W - 3 and by1 < BOARD_H - 3 and free(bx0 - 0.3, by0 - 0.3, bx1 + 0.3, by1 + 0.3, back):
                            ok = True; nudged.append(f"{ref}({dx:+d},{dy:+d})"); break
                    if ok: break
                if not ok:
                    fp.SetPosition(V(x, y)); print(f"WARNING: no free spot near the anchor for {ref}; left at ({x}, {y})")
            mark(fp, back); placed_first.append(ref)
    if nudged: print("anchors nudged:", " ".join(nudged))
    # 3. everything else: attraction placement. Each part is pulled toward the pads of already-placed parts on its
    #    signal nets (plane nets excluded; buses with many pads use the nearest anchored part), and takes the first
    #    free spot on a spiral around that target; parts with no attractor go into their sheet's block.
    PLANE = {"GND", "3V3", "1V1", "1V35", "5V_SYS"}
    placed = set(placed_first)
    pad_index = defaultdict(list)                     # net -> [(x, y, ref)] of placed parts
    def index_pads(fp):
        for p in fp.Pads():
            n = p.GetNetname()
            if n and not n.startswith("unconnected") and n not in PLANE:
                pad_index[n].append((pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y), fp.GetReference()))
    for r in placed_first: index_pads(fps[r])
    def block_centre(sheet):
        x0, y0, x1, y1 = BLOCKS.get(sheet, BLOCKS["expansion"]); return ((x0 + x1) / 2, (y0 + y1) / 2)
    def target_of(fp, sheet):
        cx, cy = block_centre(sheet); pts = []
        for p in fp.Pads():
            n = p.GetNetname()
            if n in pad_index:
                x, y, _ = min(pad_index[n], key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2)   # nearest placed pad on that net
                pts.append((x, y))
        if not pts: return None
        return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
    rest = [r for r in fps if r not in placed]
    def supply_target(fp):
        """a decoupling part under the FPGA goes to the centroid of the FPGA balls on its own rail (D59: the raster scan had put
        the 1V35 capacitors of banks 2/3 at the east edge, 25 mm from the balls and the 1V35 island on the west)"""
        rails = {p.GetNetname() for p in fp.Pads() if p.GetNetname() in PLANE and p.GetNetname() != "GND"}
        pts = [(pcbnew.ToMM(q.GetPosition().x), pcbnew.ToMM(q.GetPosition().y)) for q in fps["U1"].Pads() if q.GetNetname() in rails]
        return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)) if pts else None
    def n_attractors(r):
        return sum(1 for p in fps[r].Pads() if p.GetNetname() in pad_index)
    def place_one(ref):
        fp = fps[ref]; sheet = sheet_of.get(ref, "expansion")
        back = sheet == "fpga_pwr"
        if back:
            fp.Flip(V(0, 0), False)
            fx, fy = pcbnew.ToMM(fps["U1"].GetPosition().x), pcbnew.ToMM(fps["U1"].GetPosition().y)   # the placed position, not the anchor (nudged; D59)
            x0, y0, x1, y1 = fx - 17, fy - 17, fx + 17, fy + 17
            occ_b.update(cells(fx - 9.8, fy - 9.8, fx + 9.8, fy + 9.8))
        else:
            x0, y0, x1, y1 = BLOCKS.get(sheet, BLOCKS["expansion"])
        fp.SetOrientationDegrees(0); fp.SetPosition(V(0, 0))
        bx0, by0, bx1, by1 = fp_bbox_mm(fp); w = bx1 - bx0 + 0.8; h = by1 - by0 + 0.8
        done = False
        tgt = supply_target(fp) if back else target_of(fp, sheet)
        if tgt is not None:
            tx, ty = tgt; rej_b = rej_o = 0
            for r_ in [i * 0.5 for i in range(0, 41)]:          # spiral, 0.5 mm steps, up to 20 mm
                n_ = max(8, int(2 * math.pi * r_ / 0.5)) if r_ > 0 else 1
                for k in range(n_):
                    a = 2 * math.pi * k / n_
                    xx, yy = tx + r_ * math.cos(a), ty + r_ * math.sin(a)
                    if xx - w / 2 < 6 or yy - h / 2 < 6 or xx + w / 2 > BOARD_W - 6 or yy + h / 2 > BOARD_H - 6: rej_b += 1; continue
                    if free(xx - w / 2, yy - h / 2, xx + w / 2, yy + h / 2, back):
                        fp.SetPosition(V(xx - (bx0 + bx1) / 2, yy - (by0 + by1) / 2)); mark(fp, back); done = True; break
                    rej_o += 1
                if done: break
            if ref in os.environ.get("PLACE_DEBUG", "").split(","):
                print(f"  SPIRAL {ref}: target=({tx:.1f},{ty:.1f}) size={w:.1f}x{h:.1f} found={done} r={r_} rejected bounds={rej_b} occupied={rej_o}")
        if not done:
            for yy in [y0 + h / 2 + i * 0.5 for i in range(int((y1 - y0) / 0.5))]:
                for xx in [x0 + w / 2 + i * 0.5 for i in range(int((x1 - x0) / 0.5))]:
                    if xx + w / 2 > x1 or yy + h / 2 > y1: continue
                    if free(xx - w / 2, yy - h / 2, xx + w / 2, yy + h / 2, back):
                        fp.SetPosition(V(xx - (bx0 + bx1) / 2, yy - (by0 + by1) / 2)); mark(fp, back); done = True; break
                if done: break
        if not done:
            for yy in [6 + h / 2 + i * 0.5 for i in range(int((BOARD_H - 12) / 0.5))]:
                for xx in [6 + w / 2 + i * 0.5 for i in range(int((BOARD_W - 12) / 0.5))]:
                    if xx + w / 2 > BOARD_W - 6 or yy + h / 2 > BOARD_H - 6: continue
                    if free(xx - w / 2, yy - h / 2, xx + w / 2, yy + h / 2, back):
                        fp.SetPosition(V(xx - (bx0 + bx1) / 2, yy - (by0 + by1) / 2)); mark(fp, back); done = True; break
                if done: break
            overflow.append(ref)
        if not done:
            print("WARNING: no room anywhere for", ref)
        else:
            placed.add(ref); index_pads(fp)
        if ref in os.environ.get("PLACE_DEBUG", "").split(","):
            print(f"  PLACE {ref}: target={tgt} -> ({pcbnew.ToMM(fp.GetPosition().x):.1f}, {pcbnew.ToMM(fp.GetPosition().y):.1f}) attractors={[p.GetNetname() for p in fp.Pads() if p.GetNetname() in pad_index]}")
    # rounds: place whatever has an attractor now (most-connected first); newly placed parts attract the next round
    # (inductor after its buck, divider after its regulator, ...). Leftovers with no attractor go to their block.
    remaining = list(rest)
    while remaining:
        ready = sorted([r for r in remaining if n_attractors(r) > 0], key=lambda r: -n_attractors(r))
        if not ready: break
        for r in ready:
            place_one(r); remaining.remove(r)
    for r in remaining: place_one(r)
    # outline + mounting holes
    for (sx, sy, ex, ey) in ((0, 0, BOARD_W, 0), (BOARD_W, 0, BOARD_W, BOARD_H), (BOARD_W, BOARD_H, 0, BOARD_H), (0, BOARD_H, 0, 0)):
        s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetStart(V(sx, sy)); s.SetEnd(V(ex, ey)); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1)); b.Add(s)
    for i, (x, y) in enumerate(((4, 4), (BOARD_W - 4, 4), (4, BOARD_H - 4), (BOARD_W - 4, BOARD_H - 4))):
        h = pcbnew.FootprintLoad(os.path.join(FP_STOCK, "MountingHole.pretty"), "MountingHole_3.2mm_M3")
        h.SetReference(f"H{i+1}"); h.SetPosition(V(x, y)); b.Add(h)

    # BGA rule area around the FPGA (tighter trace/space allowed inside, see waffle.kicad_dru)
    fx, fy, _ = ANCHORS["U1"]
    z = pcbnew.ZONE(b); z.SetIsRuleArea(True); z.SetZoneName("BGA"); z.SetLayerSet(pcbnew.LSET.AllCuMask(8))
    z.SetDoNotAllowCopperPour(False); z.SetDoNotAllowTracks(False); z.SetDoNotAllowVias(False)
    z.SetDoNotAllowFootprints(False); z.SetDoNotAllowPads(False)
    pts = [(fx - 11, fy - 11), (fx + 11, fy - 11), (fx + 11, fy + 11), (fx - 11, fy + 11)]
    z.Outline().NewOutline()
    for x, y in pts: z.Outline().Append(mm(x), mm(y))
    b.Add(z)
    # same for the DDR3 FBGA-96 (0.8 mm pitch as well)
    if "U2" in fps:
        dx0, dy0, dx1, dy1 = fp_bbox_mm(fps["U2"])
        z2 = pcbnew.ZONE(b); z2.SetIsRuleArea(True); z2.SetZoneName("BGA_DDR"); z2.SetLayerSet(pcbnew.LSET.AllCuMask(8))
        z2.SetDoNotAllowCopperPour(False); z2.SetDoNotAllowTracks(False); z2.SetDoNotAllowVias(False); z2.SetDoNotAllowFootprints(False); z2.SetDoNotAllowPads(False)
        z2.Outline().NewOutline()
        for x, y in ((dx0 - 1.5, dy0 - 1.5), (dx1 + 1.5, dy0 - 1.5), (dx1 + 1.5, dy1 + 1.5), (dx0 - 1.5, dy1 + 1.5)): z2.Outline().Append(mm(x), mm(y))
        b.Add(z2)
    # GND pours on the two ground layers
    for layer in (pcbnew.In1_Cu, pcbnew.In4_Cu, pcbnew.In6_Cu):
        zg = pcbnew.ZONE(b); zg.SetLayer(layer); zg.SetNet(netmap["GND"]); zg.SetZoneName(f"GND_{b.GetLayerName(layer)}")
        zg.Outline().NewOutline()
        for x, y in ((0.5, 0.5), (BOARD_W - 0.5, 0.5), (BOARD_W - 0.5, BOARD_H - 0.5), (0.5, BOARD_H - 0.5)): zg.Outline().Append(mm(x), mm(y))
        zg.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL); zg.SetThermalReliefGap(mm(0.3)); zg.SetThermalReliefSpokeWidth(mm(0.4)); zg.SetLocalClearance(mm(0.1)); zg.SetMinThickness(mm(0.15)); b.Add(zg)   # 0.1/0.15 passes between 0.8 mm via rows under the BGAs (D58)   # thermal spokes on through-hole GND pads (vias stay solid)
    # power islands on In3.Cu (PWR): consumer area + a corridor to the regulator; 3V3 fills the rest at lowest priority.
    def zone(net, pts, prio, name, layer=pcbnew.In3_Cu, clr=0.1, minw=0.15):   # 0.1/0.15 passes between 0.8 mm via rows (D58)
        z = pcbnew.ZONE(b); z.SetLayer(layer); z.SetNet(netmap[net]); z.SetZoneName(name); z.SetAssignedPriority(prio)
        z.Outline().NewOutline()
        for x, y in pts: z.Outline().Append(mm(x), mm(y))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL); z.SetMinThickness(mm(minw)); z.SetLocalClearance(mm(clr)); b.Add(z)
        return z
    def rect(x0, y0, x1, y1): return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    def feed(reg, island_top, bx0, bx1, w=4.0):
        """a w-wide strip straight down from the regulator's centre into a block (x bx0..bx1) over the 6 mm above the
        consumer island, where that rail's capacitors and plane vias sit (D58: the bounding rectangle of the
        regulator-to-consumer diagonal used before was a 19 x 60 mm wall that cut the 3V3 fill)"""
        rx, ry = centre(reg); t = island_top
        return ((rx - w / 2, ry - w / 2), (rx + w / 2, ry - w / 2), (rx + w / 2, t - 6), (bx1, t - 6), (bx1, t + 2), (bx0, t + 2), (bx0, t - 6), (rx - w / 2, t - 6))
    def centre(ref):
        f = fps[ref]; return (pcbnew.ToMM(f.GetPosition().x), pcbnew.ToMM(f.GetPosition().y))
    fx0, fy0, fx1, fy1 = fp_bbox_mm(fps["U1"]); dx0, dy0, dx1, dy1 = fp_bbox_mm(fps["U2"])
    # distinct priorities everywhere: KiCad flags same-net zones that overlap at equal priority
    if "1V1" in netmap and "U21" in fps:
        zone("1V1", rect(fx0 - 1, fy0 - 1, fx1 + 1, fy1 + 1), 6, "1V1_core")
        zone("1V1", feed("U21", fy0 - 1, fx0 - 0.5, fx1 + 0.5), 5, "1V1_feed")
    if "1V35" in netmap and "U20" in fps:
        zone("1V35", rect(dx0 - 2, min(dy0, fy0) - 2, fx0 - 1.5, max(dy1, fy1) + 8), 4, "1V35_ddr")   # +8: the DRAM decoupling row below the part sits on the island (D58)   # DRAM + the gap to the FPGA's left edge (banks 2/3 VCCIO balls hook in with short tracks/vias)
        zone("1V35", feed("U20", min(dy0, fy0) - 2, dx0 - 0.2, fx0 - 1.5), 3, "1V35_feed")
        # the FPGA's bank 2/3 VCCIO balls sit inside the 1V1 core island: a 1V35 patch above it takes their dog-bone vias
        # and the decoupling beside them (D59); it is fed by the router (short 1V35 tracks to the DRAM island) and by the
        # bank capacitors' vias
        vp = [(pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)) for p in fps["U1"].Pads() if p.GetNetname() == "1V35"]
        if vp:
            xs_, ys_ = [x for x, _ in vp], [y for _, y in vp]
            zone("1V35", rect(min(xs_) - 0.9, min(ys_) - 0.9, max(xs_) + 0.3, max(ys_) + 0.9), 7, "1V35_vccio")
    if "5V_SYS" in netmap:
        zone("5V_SYS", rect(12, 2.5, BOARD_W - 8, 12), 1, "5V_SYS_back")
    if "3V3" in netmap:
        # 3V3 has no layer of its own: the PWR fill is cut by the islands and by every signal track routed on PWR, so it runs
        # at the board's minimum clearance with a width that passes between 0.8 mm via rows, and a second 3V3 sheet on B.Cu
        # (thermal-relieved pads, lowest priority) is tied to it by every 3V3 via (D58; hw/tools/fix_pwr_fill.py applies the
        # same repair to an already-routed board)
        zone("3V3", rect(0.5, 0.5, BOARD_W - 0.5, BOARD_H - 0.5), 0, "3V3_fill")
        zb = zone("3V3", rect(0.5, 0.5, BOARD_W - 0.5, BOARD_H - 0.5), 0, "3V3_back", layer=pcbnew.B_Cu, clr=0.2, minw=0.15)
        zb.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL); zb.SetThermalReliefGap(mm(0.25)); zb.SetThermalReliefSpokeWidth(mm(0.3))
    out = os.path.join(HW, "waffle.kicad_pcb")
    pcbnew.SaveBoard(out, b)
    inject_stackup(out)
    write_project()
    print(f"wrote {out}: {len(fps)} footprints, {len(nets)} nets; missing footprints: {missing}; {len(overflow)} parts with no attractor and no room in their block: {overflow[:12]}")

if __name__ == "__main__":
    main()
