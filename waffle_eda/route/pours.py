"""Supply nets on a two-layer board are pours, not tracks (plan.md, milestone A).

A pour is part of the specification stage 5 receives, not something the router invents: which nets are
poured, on which layers, over which outline, with what relief. For a reference board that specification is the
board's own zones (D17: the constraints of a reference stand for what stages 1 to 4 would have produced), read
by :func:`pour_spec` with the teardrops left out (KiCad 9 stores a teardrop as a zone; `olimex-esp32c3-devkit`
has 154 of them next to its two real pours). For a synthetic design it comes from `spec.toml`.

:func:`add_pours` recreates the pours on a bare board before routing, so that the router sees them as planes
and routes the other nets through them, and the ground pads it never has to reach are connected by the fill.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import pcbnew

from waffle_eda.kicad import board as kb


@dataclass(frozen=True)
class Pour:
    net: str
    layer: str
    outline_mm: tuple[tuple[float, float], ...]  # one outline, no holes: a pour is a region, not a fill
    clearance_mm: float
    min_width_mm: float
    thermal_gap_mm: float
    thermal_spoke_mm: float
    pad_connection: int  # pcbnew.ZONE_CONNECTION_*
    priority: int


def _outline_mm(zone) -> tuple[tuple[float, float], ...]:
    chain = zone.Outline().Outline(0)
    return tuple((kb.mm(chain.CPoint(i).x), kb.mm(chain.CPoint(i).y)) for i in range(chain.PointCount()))


def pour_spec(board) -> list[Pour]:
    """Every copper zone of ``board`` that is a pour: not a rule area, not a teardrop. One entry per layer the
    zone covers, sorted so the specification does not depend on item order (D25)."""
    pours = []
    for z in board.Zones():
        if z.GetIsRuleArea() or z.IsTeardropArea() or not z.GetNetname():
            continue
        for layer in z.GetLayerSet().CuStack():
            pours.append(Pour(net=z.GetNetname(), layer=board.GetLayerName(layer), outline_mm=_outline_mm(z),
                              clearance_mm=round(kb.mm(z.GetLocalClearance()), 4),
                              min_width_mm=round(kb.mm(z.GetMinThickness()), 4),
                              thermal_gap_mm=round(kb.mm(z.GetThermalReliefGap()), 4),
                              thermal_spoke_mm=round(kb.mm(z.GetThermalReliefSpokeWidth()), 4),
                              pad_connection=int(z.GetPadConnection()), priority=int(z.GetAssignedPriority())))
    return sorted(pours, key=lambda p: (p.net, p.layer, p.outline_mm))


def pours_to_json(pours: list[Pour]) -> list[dict]:
    return [asdict(p) for p in pours]


def pours_from_json(data: list[dict]) -> list[Pour]:
    return [Pour(**{**d, "outline_mm": tuple(tuple(pt) for pt in d["outline_mm"])}) for d in data]


def add_pours(board, pours: list[Pour], clearance_floor_mm: float = 0.0, min_width_floor_mm: float = 0.0) -> list:
    """Create the pours on ``board`` (unfilled; refill before any check). A pour's clearance and minimum width
    are raised to the floors, which the caller sets from the measured rules, so a pour never violates a rule
    the board demonstrates elsewhere."""
    layer_ids = {name: lid for lid, name in kb.copper_layers(board)}
    zones = []
    for p in pours:
        if p.layer not in layer_ids:
            raise ValueError(f"pour of {p.net} on unknown layer {p.layer}")
        net = board.FindNet(p.net)
        if net is None:
            raise ValueError(f"pour of unknown net {p.net}")
        z = pcbnew.ZONE(board)
        z.SetLayer(layer_ids[p.layer])
        z.SetNetCode(net.GetNetCode())
        outline = z.Outline()
        outline.NewOutline()
        for x, y in p.outline_mm:
            outline.Append(kb.nm(x), kb.nm(y))
        z.SetLocalClearance(kb.nm(max(p.clearance_mm, clearance_floor_mm)))
        z.SetMinThickness(kb.nm(max(p.min_width_mm, min_width_floor_mm)))
        z.SetThermalReliefGap(kb.nm(max(p.thermal_gap_mm, clearance_floor_mm)))
        z.SetThermalReliefSpokeWidth(kb.nm(max(p.thermal_spoke_mm, min_width_floor_mm)))
        z.SetPadConnection(p.pad_connection)
        z.SetAssignedPriority(p.priority)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        board.Add(z)
        zones.append(z)
    return zones
