"""A board from the netlist and the specification: the footprints from KiCad's libraries, the nets from the
netlist `kicad-cli` exported at stage 3, the outline and the design rules from `spec.toml`. No copper: the
board this writes is what stage 5's placer and router receive, which is also what the class A gate hands the
router for a reference (`bench/rebuild.strip_all`)."""
from __future__ import annotations

import math
from pathlib import Path

import pcbnew

from waffle_eda.design import stage3_schematic as s3
from waffle_eda.kicad import board as kb, libs


def new_board(spec: dict) -> pcbnew.BOARD:
    board = pcbnew.BOARD()
    rules = spec["rules"]
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(int(spec["board"]["layers"]))
    ds.m_MinClearance = kb.nm(rules["clearance"])
    ds.m_HoleClearance = kb.nm(rules["hole_clearance"])
    ds.m_CopperEdgeClearance = kb.nm(rules["edge_clearance"])
    ds.m_TrackMinWidth = kb.nm(rules["track_width"])
    ds.m_ViasMinSize = kb.nm(rules["via_diameter"])
    ds.m_MinThroughDrill = kb.nm(rules["via_drill"])
    ds.m_ViasMinAnnularWidth = kb.nm(rules["annular_ring"])
    try:
        default = ds.m_NetSettings.GetDefaultNetclass()
    except AttributeError:
        default = ds.m_NetSettings.m_DefaultNetClass
    default.SetClearance(kb.nm(rules["clearance"]))
    default.SetTrackWidth(kb.nm(rules["track_width"]))
    default.SetViaDiameter(kb.nm(rules["via_diameter"]))
    default.SetViaDrill(kb.nm(rules["via_drill"]))
    return board


def outline_rect(spec: dict) -> tuple[float, float, float, float]:
    ox, oy = spec["outline"]["origin_mm"]
    return ox, oy, ox + spec["outline"]["width_mm"], oy + spec["outline"]["height_mm"]


def draw_outline(board: pcbnew.BOARD, spec: dict) -> None:
    """A rectangle with rounded corners on Edge.Cuts, as the class A references draw theirs."""
    for item in [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]:
        board.Delete(item)
    x0, y0, x1, y1 = outline_rect(spec)
    r = float(spec["outline"].get("corner_radius_mm", 0.0))
    width = kb.nm(0.1)

    def seg(ax, ay, bx, by):
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I(kb.nm(ax), kb.nm(ay)))
        s.SetEnd(pcbnew.VECTOR2I(kb.nm(bx), kb.nm(by)))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(width)
        board.Add(s)

    def arc(cx, cy, a0, a1):
        """A quarter arc about (cx, cy) from angle a0 to a1 (degrees, y down)."""
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
        p = lambda a: pcbnew.VECTOR2I(kb.nm(cx + r * math.cos(math.radians(a))), kb.nm(cy + r * math.sin(math.radians(a))))
        s.SetArcGeometry(p(a0), p((a0 + a1) / 2), p(a1))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(width)
        board.Add(s)

    if r <= 0:
        seg(x0, y0, x1, y0), seg(x1, y0, x1, y1), seg(x1, y1, x0, y1), seg(x0, y1, x0, y0)
        return
    seg(x0 + r, y0, x1 - r, y0)
    seg(x1, y0 + r, x1, y1 - r)
    seg(x1 - r, y1, x0 + r, y1)
    seg(x0, y1 - r, x0, y0 + r)
    arc(x1 - r, y0 + r, 270, 360)
    arc(x1 - r, y1 - r, 0, 90)
    arc(x0 + r, y1 - r, 90, 180)
    arc(x0 + r, y0 + r, 180, 270)


def add_parts(board: pcbnew.BOARD, netlist: Path) -> dict[str, pcbnew.FOOTPRINT]:
    """Every component of the netlist as its library footprint, with its pads on the netlist's nets."""
    comps = s3.netlist_components(netlist)
    fps: dict[str, pcbnew.FOOTPRINT] = {}
    for ref, comp in sorted(comps.items()):
        fp = libs.load_footprint(comp["footprint"])
        lib, name = libs.split_id(comp["footprint"])
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(comp["value"])
        board.Add(fp)
        fps[ref] = fp
    for name, pins in sorted(s3.read_netlist(netlist).items()):
        if name.startswith("unconnected-") and len(pins) <= 1:
            continue
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        for ref, pin in pins:
            for pad in fps[ref].Pads():
                if pad.GetNumber() == pin:
                    pad.SetNet(net)
    return fps


def build(spec: dict, netlist: Path) -> tuple[pcbnew.BOARD, dict[str, pcbnew.FOOTPRINT]]:
    board = new_board(spec)
    draw_outline(board, spec)
    fps = add_parts(board, netlist)
    return board, fps
