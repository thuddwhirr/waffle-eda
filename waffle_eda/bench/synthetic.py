"""Synthetic BGA-pair boards with known feasibility, for unit tests of the fan-out and the bus router (plan.md, M1).

A case is two ball-grid packages on a board of a given layer count, a bus of nets between the balls of one side of
each package, a few power and ground balls, and the fab rules. The board is written with pcbnew so that every later
stage reads it exactly as it reads a real board. There is no answer copper: a case is scored on connectivity, DRC and
the rules alone. ``order`` states how the bus balls correspond: ``"straight"`` (row by row, crossing-free by
construction), ``"reversed"`` (every net crosses every other) or ``"random"``.
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass, asdict
from pathlib import Path

import pcbnew

from waffle_eda.kicad import board as kb

ROW_LETTERS = [c for c in string.ascii_uppercase if c not in "IOQSXZ"]  # JEDEC ball row letters


@dataclass(frozen=True)
class BgaPairCase:
    name: str
    rows: int
    cols: int
    pitch_mm: float = 0.8
    ball_mm: float = 0.4
    layers: int = 4
    bus_cols: int = 2  # columns on the facing side of each package that carry the bus
    gap_mm: float = 5.0  # clear space between the two packages' outer ball rows
    margin_mm: float = 4.0  # board edge beyond the balls
    order: str = "straight"
    power_balls: int = 4  # centre balls assigned to GND and VCC alternately, on each package
    clearance_mm: float = 0.1
    track_mm: float = 0.1
    via_mm: float = 0.45
    via_drill_mm: float = 0.2
    seed: int = 0

    @property
    def bus_nets(self) -> int:
        return self.rows * self.bus_cols

    @property
    def expected_feasible(self) -> bool | None:
        """What is known about routability; None until a router or a proof settles it (M2, M3)."""
        return None


CASES: dict[str, BgaPairCase] = {
    "pair-6x6-straight": BgaPairCase("pair-6x6-straight", rows=6, cols=6, layers=4, bus_cols=2),
    "pair-6x6-reversed": BgaPairCase("pair-6x6-reversed", rows=6, cols=6, layers=4, bus_cols=2, order="reversed"),
    "pair-9x16-straight": BgaPairCase("pair-9x16-straight", rows=9, cols=16, layers=6, bus_cols=3, power_balls=8),
    "pair-20x20-bank": BgaPairCase("pair-20x20-bank", rows=20, cols=20, layers=8, bus_cols=3, power_balls=24, gap_mm=3.0),
}


def _set_rules(board: pcbnew.BOARD, case: BgaPairCase) -> None:
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(case.layers)
    ds.m_MinClearance = kb.nm(case.clearance_mm)
    ds.m_TrackMinWidth = kb.nm(case.track_mm)
    ds.m_ViasMinSize = kb.nm(case.via_mm)
    ds.m_MinThroughDrill = kb.nm(case.via_drill_mm)
    try:
        default = ds.m_NetSettings.GetDefaultNetclass()
    except AttributeError:
        default = ds.m_NetSettings.m_DefaultNetClass
    default.SetClearance(kb.nm(case.clearance_mm))
    default.SetTrackWidth(kb.nm(case.track_mm))
    default.SetViaDiameter(kb.nm(case.via_mm))
    default.SetViaDrill(kb.nm(case.via_drill_mm))


def _add_bga(board: pcbnew.BOARD, ref: str, case: BgaPairCase, x_mm: float, y_mm: float) -> pcbnew.FOOTPRINT:
    fp = pcbnew.FOOTPRINT(board)
    fp.SetReference(ref)
    fp.SetValue(f"BGA-{case.rows * case.cols}")
    fp.SetFPID(pcbnew.LIB_ID("synthetic", f"BGA-{case.rows}x{case.cols}_P{case.pitch_mm}mm"))
    fp.SetAttributes(pcbnew.FP_SMD)
    board.Add(fp)
    fp.SetPosition(pcbnew.VECTOR2I(kb.nm(x_mm), kb.nm(y_mm)))
    w = (case.cols - 1) * case.pitch_mm
    h = (case.rows - 1) * case.pitch_mm
    for r in range(case.rows):
        for c in range(case.cols):
            pad = pcbnew.PAD(fp)
            pad.SetNumber(f"{ROW_LETTERS[r]}{c + 1}")
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetSize(pcbnew.VECTOR2I(kb.nm(case.ball_mm), kb.nm(case.ball_mm)))
            pad.SetLayerSet(pcbnew.PAD.SMDMask())
            px = x_mm - w / 2 + c * case.pitch_mm
            py = y_mm - h / 2 + r * case.pitch_mm
            pad.SetPosition(pcbnew.VECTOR2I(kb.nm(px), kb.nm(py)))
            fp.Add(pad)
    # courtyard: the ball array plus half a pitch
    cx0, cy0 = x_mm - w / 2 - case.pitch_mm / 2, y_mm - h / 2 - case.pitch_mm / 2
    cx1, cy1 = x_mm + w / 2 + case.pitch_mm / 2, y_mm + h / 2 + case.pitch_mm / 2
    for (ax, ay), (bx, by) in (((cx0, cy0), (cx1, cy0)), ((cx1, cy0), (cx1, cy1)), ((cx1, cy1), (cx0, cy1)), ((cx0, cy1), (cx0, cy0))):
        seg = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(kb.nm(ax), kb.nm(ay)))
        seg.SetEnd(pcbnew.VECTOR2I(kb.nm(bx), kb.nm(by)))
        seg.SetLayer(pcbnew.F_CrtYd)
        seg.SetWidth(kb.nm(0.05))
        fp.Add(seg)
    return fp


def _outline(board: pcbnew.BOARD, x0: float, y0: float, x1: float, y1: float) -> None:
    for (ax, ay), (bx, by) in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        seg = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(kb.nm(ax), kb.nm(ay)))
        seg.SetEnd(pcbnew.VECTOR2I(kb.nm(bx), kb.nm(by)))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(kb.nm(0.1))
        board.Add(seg)


def _pads_by_number(fp: pcbnew.FOOTPRINT) -> dict[str, pcbnew.PAD]:
    return {p.GetNumber(): p for p in fp.Pads()}


def make_bga_pair(case: BgaPairCase, out_path: Path) -> dict:
    """Write the case as a board file; return a manifest (nets per pad) for the tests."""
    board = pcbnew.BOARD()
    _set_rules(board, case)
    w = (case.cols - 1) * case.pitch_mm
    h = (case.rows - 1) * case.pitch_mm
    x1 = 20.0
    y = 20.0
    x2 = x1 + w + case.gap_mm + case.pitch_mm  # gap between the outer ball rows
    u1 = _add_bga(board, "U1", case, x1, y)
    u2 = _add_bga(board, "U2", case, x2, y)
    _outline(board, x1 - w / 2 - case.margin_mm, y - h / 2 - case.margin_mm, x2 + w / 2 + case.margin_mm, y + h / 2 + case.margin_mm)

    p1, p2 = _pads_by_number(u1), _pads_by_number(u2)
    # Bus balls: U1's east-most columns face U2's west-most columns.
    u1_balls = [f"{ROW_LETTERS[r]}{c + 1}" for c in range(case.cols - case.bus_cols, case.cols) for r in range(case.rows)]
    u2_balls = [f"{ROW_LETTERS[r]}{c + 1}" for c in range(case.bus_cols) for r in range(case.rows)]
    if case.order == "reversed":
        u2_balls = u2_balls[::-1]
    elif case.order == "random":
        random.Random(case.seed).shuffle(u2_balls)
    elif case.order != "straight":
        raise ValueError(case.order)
    manifest = {"case": asdict(case), "bus": {}, "power": {}}
    for i, (a, b) in enumerate(zip(u1_balls, u2_balls)):
        net = pcbnew.NETINFO_ITEM(board, f"BUS{i:02d}")
        board.Add(net)
        p1[a].SetNet(net)
        p2[b].SetNet(net)
        manifest["bus"][net.GetNetname()] = {"U1": a, "U2": b}
    # Power balls: the centre of each package, GND and VCC alternately.
    gnd = pcbnew.NETINFO_ITEM(board, "GND")
    vcc = pcbnew.NETINFO_ITEM(board, "VCC")
    board.Add(gnd)
    board.Add(vcc)
    centre_r, centre_c = case.rows // 2, case.cols // 2
    k = 0
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            if k >= case.power_balls:
                break
            r, c = centre_r + dr, centre_c + dc
            if not (0 <= r < case.rows and 0 <= c < case.cols):
                continue
            number = f"{ROW_LETTERS[r]}{c + 1}"
            if p1[number].GetNetname() or p2[number].GetNetname():
                continue
            net = gnd if k % 2 == 0 else vcc
            p1[number].SetNet(net)
            p2[number].SetNet(net)
            manifest["power"][number] = net.GetNetname()
            k += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kb.save_board(board, out_path)
    return manifest
