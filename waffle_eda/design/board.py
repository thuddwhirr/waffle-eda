"""The board of stage 5 from the netlist, the footprints and the specification, with its placement.

Placement is a free variable (definition.md, section 4) and there is no existing headless tool for it in KiCad,
so this is the smallest placer that serves class A: parts go down one at a time, most pins first, each at the
grid position and rotation that keeps its courtyard clear of the others and inside the outline and makes the
half-perimeter wirelength of its nets shortest. A locked interface position (the header on its edge, pin 1 to
the north) is placed first and never moved; a part with a stated region is confined to it. The placer is
deterministic (D25) and takes an ``attempt`` number so the closure loop of stage 5 can ask for a different
placement after a failed route: each attempt rotates the order of the free parts.
"""
from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pcbnew

from waffle_eda.kicad import board as kb
from waffle_eda.route import pours as pours_mod
from waffle_eda.sch import schematic

FOOTPRINT_DIR = Path("/usr/share/kicad/footprints")
GRID_MM = 0.5
COURTYARD_GAP_MM = 0.25
ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class Spec:
    fab: str
    layers: int
    width_mm: float
    height_mm: float
    track_mm: float
    clearance_mm: float
    via_mm: float
    via_drill_mm: float
    hole_to_copper_mm: float
    edge_clearance_mm: float
    pours: list
    raw: dict

    @classmethod
    def read(cls, path: Path) -> "Spec":
        d = tomllib.loads(path.read_text())
        b, r = d["board"], d["rules"]
        return cls(fab=b["fab"], layers=int(b["layers"]), width_mm=float(b["outline_mm"]["width"]),
                   height_mm=float(b["outline_mm"]["height"]), track_mm=float(r["track_mm"]),
                   clearance_mm=float(r["clearance_mm"]), via_mm=float(r["via_mm"]), via_drill_mm=float(r["via_drill_mm"]),
                   hole_to_copper_mm=float(r["hole_to_copper_mm"]), edge_clearance_mm=float(r["edge_clearance_mm"]),
                   pours=d.get("pours", []), raw=d)

    def board_rules(self, name: str):
        """The specification as `bench.rebuild.BoardRules`, which stage 5 and its DRC run under."""
        from waffle_eda.bench import rebuild
        return rebuild.BoardRules(reference=name, board_mtime=0.0, clearance_mm=self.clearance_mm,
                                  hole_to_copper_mm=self.hole_to_copper_mm, edge_clearance_mm=self.edge_clearance_mm,
                                  min_track_mm=self.track_mm, min_via_mm=self.via_mm, min_drill_mm=self.via_drill_mm,
                                  min_annular_mm=round((self.via_mm - self.via_drill_mm) / 2, 4),
                                  layers=("F.Cu", "B.Cu") if self.layers == 2 else tuple(f"L{i}" for i in range(self.layers)),
                                  nets=0)

    def pour_spec(self) -> list:
        outline = ((0.0, 0.0), (self.width_mm, 0.0), (self.width_mm, self.height_mm), (0.0, self.height_mm))
        out = []
        for p in self.pours:
            for layer in p["layers"]:
                out.append(pours_mod.Pour(net=p["net"], layer=layer, outline_mm=outline,
                                          clearance_mm=float(p.get("clearance_mm", self.clearance_mm)),
                                          min_width_mm=float(p.get("min_width_mm", self.track_mm)),
                                          thermal_gap_mm=float(p.get("thermal_gap_mm", self.clearance_mm)),
                                          thermal_spoke_mm=float(p.get("thermal_spoke_mm", self.track_mm)),
                                          pad_connection=pcbnew.ZONE_CONNECTION_THERMAL, priority=0))
        return out


def read_interfaces(connectivity: Path) -> dict:
    """The locked interface positions and stated regions of the design document's machine-readable part."""
    return tomllib.loads(connectivity.read_text()).get("interfaces", {})


def load_footprint(lib_id: str) -> pcbnew.FOOTPRINT:
    lib, name = lib_id.split(":", 1)
    fp = pcbnew.FootprintLoad(str(FOOTPRINT_DIR / f"{lib}.pretty"), name)
    if fp is None:
        raise FileNotFoundError(f"footprint {lib_id} not found under {FOOTPRINT_DIR}")
    return fp


def new_board(spec: Spec, bom: list[dict], netlist: dict[str, set[tuple[str, str]]]) -> pcbnew.BOARD:
    """An unplaced board: the outline, the rules in the design settings and the default net class, every
    footprint of the BOM with its pads on the netlist's nets."""
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(spec.layers)
    ds = board.GetDesignSettings()
    ds.m_HoleClearance = kb.nm(spec.hole_to_copper_mm)
    ds.m_CopperEdgeClearance = kb.nm(spec.edge_clearance_mm)
    ds.m_MinClearance = kb.nm(spec.clearance_mm)
    ds.m_TrackMinWidth = kb.nm(spec.track_mm)
    ds.m_ViasMinSize = kb.nm(spec.via_mm)
    ds.m_MinThroughDrill = kb.nm(spec.via_drill_mm)
    for _name, nc in board.GetAllNetClasses().items():
        nc.SetTrackWidth(kb.nm(spec.track_mm))
        nc.SetClearance(kb.nm(spec.clearance_mm))
        nc.SetViaDiameter(kb.nm(spec.via_mm))
        nc.SetViaDrill(kb.nm(spec.via_drill_mm))
    outline = pcbnew.PCB_SHAPE(board)
    outline.SetShape(pcbnew.SHAPE_T_RECT)
    outline.SetStart(pcbnew.VECTOR2I(0, 0))
    outline.SetEnd(pcbnew.VECTOR2I(kb.nm(spec.width_mm), kb.nm(spec.height_mm)))
    outline.SetLayer(pcbnew.Edge_Cuts)
    outline.SetWidth(kb.nm(0.1))
    board.Add(outline)
    nets = {}
    for name in sorted(netlist):
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net
    pin_net = {rp: name for name, pins in netlist.items() for rp in pins}
    for row in bom:
        fp = load_footprint(row["footprint"])
        fp.SetReference(row["reference"])
        fp.SetValue(row["value"])
        for pad in fp.Pads():
            net = pin_net.get((row["reference"], pad.GetNumber()))
            if net:
                pad.SetNet(nets[net])
        board.Add(fp)
    return board


# --- placement --------------------------------------------------------------------------------------------------
def _box(fp) -> tuple[float, float, float, float]:
    bb = fp.GetBoundingBox(False, False)
    return (kb.mm(bb.GetLeft()), kb.mm(bb.GetTop()), kb.mm(bb.GetRight()), kb.mm(bb.GetBottom()))


def _overlaps(a, b, gap: float) -> bool:
    return not (a[2] + gap <= b[0] or b[2] + gap <= a[0] or a[3] + gap <= b[1] or b[3] + gap <= a[1])


def _inside(box, spec: Spec) -> bool:
    e = spec.edge_clearance_mm
    return box[0] >= e and box[1] >= e and box[2] <= spec.width_mm - e and box[3] <= spec.height_mm - e


def _region_ok(box, region: str | None, spec: Spec) -> bool:
    if not region:
        return True
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    return {"east": cx >= spec.width_mm / 2, "west": cx <= spec.width_mm / 2,
            "north": cy <= spec.height_mm / 2, "south": cy >= spec.height_mm / 2}.get(region, True)


def _place_locked(fp, interface: dict, spec: Spec) -> None:
    """A part on its locked edge. The header's pins run from pin 1 in the footprint's +y direction, so pin 1
    north is rotation 0 on the west edge."""
    edge = interface["edge"]
    pads = list(fp.Pads())
    fp.SetOrientationDegrees(0)
    fp.SetPosition(pcbnew.VECTOR2I(0, 0))
    box = _box(fp)
    ys = [kb.mm(p.GetPosition().y) for p in pads]
    span = max(ys) - min(ys)
    e = spec.edge_clearance_mm + 0.2
    if edge == "west":
        x = e - box[0]
        y = (spec.height_mm - span) / 2 - min(ys)
    elif edge == "east":
        x = spec.width_mm - e - box[2]
        y = (spec.height_mm - span) / 2 - min(ys)
    else:
        raise ValueError(f"locked edge {edge!r} is not placed by this placer")
    fp.SetPosition(pcbnew.VECTOR2I(kb.nm(x), kb.nm(y)))


def place(board: pcbnew.BOARD, spec: Spec, interfaces: dict, attempt: int = 0) -> dict:
    """Place every footprint; returns the placement (reference -> x, y, rotation) for the report."""
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    placed_boxes: dict[str, tuple] = {}
    for ref, interface in interfaces.items():
        if ref in fps and interface.get("edge"):
            _place_locked(fps[ref], interface, spec)
            placed_boxes[ref] = _box(fps[ref])
    free = sorted((r for r in fps if r not in placed_boxes),
                  key=lambda r: (-len([p for p in fps[r].Pads() if p.GetNetname()]), r))
    if free and attempt:
        k = attempt % len(free)
        free = free[k:] + free[:k]
    pad_xy: dict[str, list[tuple[float, float]]] = {}  # net -> placed pad positions

    def note_pads(fp):
        for pad in fp.Pads():
            if pad.GetNetname():
                p = pad.GetPosition()
                pad_xy.setdefault(pad.GetNetname(), []).append((kb.mm(p.x), kb.mm(p.y)))

    for ref in placed_boxes:
        note_pads(fps[ref])
    nx = int(spec.width_mm / GRID_MM)
    ny = int(spec.height_mm / GRID_MM)
    for ref in free:
        fp = fps[ref]
        region = interfaces.get(ref, {}).get("region")
        best = None
        for rot in ROTATIONS:
            fp.SetOrientationDegrees(rot)
            fp.SetPosition(pcbnew.VECTOR2I(0, 0))
            box0 = _box(fp)
            pads0 = [(pad.GetNetname(), kb.mm(pad.GetPosition().x), kb.mm(pad.GetPosition().y)) for pad in fp.Pads()]
            for ix in range(nx + 1):
                for iy in range(ny + 1):
                    x, y = ix * GRID_MM, iy * GRID_MM
                    box = (box0[0] + x, box0[1] + y, box0[2] + x, box0[3] + y)
                    if not _inside(box, spec) or not _region_ok(box, region, spec):
                        continue
                    if any(_overlaps(box, other, COURTYARD_GAP_MM) for other in placed_boxes.values()):
                        continue
                    cost = 0.0
                    for net, px, py in pads0:
                        if net and net in pad_xy:
                            xs = [px + x] + [q[0] for q in pad_xy[net]]
                            ys = [py + y] + [q[1] for q in pad_xy[net]]
                            cost += (max(xs) - min(xs)) + (max(ys) - min(ys))
                    cost += 0.05 * math.hypot(x - spec.width_mm / 2, y - spec.height_mm / 2)
                    if best is None or cost < best[0] - 1e-9:
                        best = (cost, x, y, rot)
        if best is None:
            raise RuntimeError(f"{ref}: no position inside the outline clears the placed parts")
        _cost, x, y, rot = best
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(pcbnew.VECTOR2I(kb.nm(x), kb.nm(y)))
        placed_boxes[ref] = _box(fp)
        note_pads(fp)
    return {ref: {"x_mm": round(kb.mm(fp.GetPosition().x), 3), "y_mm": round(kb.mm(fp.GetPosition().y), 3),
                  "rotation": float(fp.GetOrientationDegrees())} for ref, fp in sorted(fps.items())}


def build(design_dir: Path, name: str, attempt: int = 0) -> tuple[pcbnew.BOARD, Spec, dict]:
    """The placed, unrouted board of a design directory, from its spec, BOM and exported netlist."""
    spec = Spec.read(design_dir / "spec.toml")
    bom = schematic.read_bom(design_dir / "bom.csv")
    netlist = schematic.parse_netlist((design_dir / "reports" / "netlist.net").read_text())
    board = new_board(spec, bom, netlist)
    placement = place(board, spec, read_interfaces(design_dir / "connectivity.toml"), attempt=attempt)
    return board, spec, placement
