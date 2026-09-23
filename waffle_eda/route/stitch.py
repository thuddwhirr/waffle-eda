"""Stitching vias: a pad a pour did not reach gets a via into the other layer's pour (plan.md, milestone A).

A pour reaches a pad only where the fill can put a spoke. After routing, a ground pad boxed in by tracks on its
own layer has no spoke and no via, and the DRC reports it unconnected (three of nine ground pads on
`tinkerforge-temperature`, 2026-09-23). A stitching via next to it, into the other layer's pour, is how the
reference connects such a pad. The via site is searched outward from the pad, its own axis first and then
every direction around it, and accepted when the via and the straight track to it clear every other net's
copper under the exact collision test every router here uses (`route.obstacles`), with the hole rule applied
to the via's own hole and to the holes it approaches.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pcbnew

from waffle_eda.kicad import board as kb
from waffle_eda.route.obstacles import Obstacles


@dataclass(frozen=True)
class ViaRules:
    track_mm: float
    clearance_mm: float
    hole_clearance_mm: float
    via_mm: float
    drill_mm: float

    @classmethod
    def from_board_rules(cls, rules) -> "ViaRules":
        """From `bench.rebuild.BoardRules` (or anything with the same fields)."""
        return cls(track_mm=rules.min_track_mm, clearance_mm=rules.clearance_mm,
                   hole_clearance_mm=rules.hole_to_copper_mm, via_mm=rules.min_via_mm, drill_mm=rules.min_drill_mm)


LENGTH_STEP_MM = 0.05
DIRECTIONS_AROUND = 24  # every 15 degrees around the pad, the pad's own axis first


def _track(board, layer: int, a, b, net, width_mm: float) -> pcbnew.PCB_TRACK:
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(kb.nm(a[0]), kb.nm(a[1])))
    t.SetEnd(pcbnew.VECTOR2I(kb.nm(b[0]), kb.nm(b[1])))
    t.SetWidth(kb.nm(width_mm))
    t.SetLayer(layer)
    t.SetNet(net)
    return t


def _via(board, at, net, rules: ViaRules) -> pcbnew.PCB_VIA:
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(kb.nm(at[0]), kb.nm(at[1])))
    v.SetDrill(kb.nm(rules.drill_mm))
    kb.set_via_diameter(v, rules.via_mm)
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    layers = [lid for lid, _ in kb.copper_layers(board)]
    v.SetLayerPair(layers[0], layers[-1])
    v.SetNet(net)
    return v


def pad_axis(pad, fp) -> tuple[float, float]:
    """The unit vector along the pad's long side, pointing away from the footprint's centre: the direction a
    stub leaves in. A square pad has no long side, so it leaves straight away from the centre."""
    size = pad.GetSize(pad.GetLayer()) if hasattr(pad, "GetSize") else pad.GetSize()
    sx, sy = kb.mm(size.x), kb.mm(size.y)
    angle = math.radians(pad.GetOrientationDegrees())
    long_axis = (math.cos(angle), -math.sin(angle)) if sx >= sy else (math.sin(angle), math.cos(angle))
    c, p = fp.GetPosition(), pad.GetPosition()
    away = (kb.mm(p.x - c.x), kb.mm(p.y - c.y))
    n = math.hypot(*away)
    if abs(sx - sy) < 1e-3:
        return (away[0] / n, away[1] / n) if n > 1e-6 else (0.0, -1.0)
    dot = away[0] * long_axis[0] + away[1] * long_axis[1]
    return long_axis if dot >= 0 else (-long_axis[0], -long_axis[1])


def _pad_half_extent(pad, direction) -> float:
    """Half the pad's size along ``direction``."""
    size = pad.GetSize(pad.GetLayer()) if hasattr(pad, "GetSize") else pad.GetSize()
    sx, sy = kb.mm(size.x), kb.mm(size.y)
    angle = math.radians(pad.GetOrientationDegrees())
    ax = (math.cos(angle), -math.sin(angle))
    along = abs(direction[0] * ax[0] + direction[1] * ax[1])
    across = math.sqrt(max(0.0, 1 - along * along))
    return (sx / 2) * along + (sy / 2) * across


def via_site(board, obs: Obstacles, pad, direction, rules: ViaRules, max_length_mm: float = 3.0,
             min_length_mm: float | None = None):
    """The nearest point along ``direction`` from the pad's centre where a via and the straight track to it
    clear every other net under ``rules``, or None. The via never overlaps the pad it serves."""
    net = pad.GetNet()
    p = pad.GetPosition()
    origin = (kb.mm(p.x), kb.mm(p.y))
    layer = pad.GetLayer() if not pad.GetDrillSizeX() else pcbnew.F_Cu
    start = min_length_mm if min_length_mm is not None else \
        _pad_half_extent(pad, direction) + rules.via_mm / 2 + rules.clearance_mm
    length = math.ceil(start / LENGTH_STEP_MM) * LENGTH_STEP_MM
    while length <= max_length_mm + 1e-9:
        at = (origin[0] + direction[0] * length, origin[1] + direction[1] * length)
        via = _via(board, at, net, rules)
        if obs.clear(via, rules.clearance_mm, hole_clearance_mm=rules.hole_clearance_mm) is None:
            track = _track(board, layer, origin, at, net, rules.track_mm)
            if obs.clear(track, rules.clearance_mm, hole_clearance_mm=rules.hole_clearance_mm) is None:
                return at
        length += LENGTH_STEP_MM
    return None


def lay_stub(board, obs: Obstacles, pad, at, rules: ViaRules) -> tuple:
    """Add the track from the pad's centre to ``at`` and the via there; both join the obstacle index."""
    net = pad.GetNet()
    p = pad.GetPosition()
    layer = pad.GetLayer() if not pad.GetDrillSizeX() else pcbnew.F_Cu
    track = _track(board, layer, (kb.mm(p.x), kb.mm(p.y)), at, net, rules.track_mm)
    via = _via(board, at, net, rules)
    board.Add(track)
    board.Add(via)
    obs.add(track)
    obs.add(via)
    return track, via


# --- stitching vias after the fill ---------------------------------------------------------------------------
def stitch_pad(board, obs: Obstacles, pad, fp, rules: ViaRules) -> tuple | None:
    """A via into the other layer's pour next to a pad the fill did not reach: the pad's own axis first, then
    every direction around it. Returns the site or None."""
    axis = pad_axis(pad, fp)
    base = math.atan2(axis[1], axis[0])
    for k in range(DIRECTIONS_AROUND):
        angle = base + (k // 2 + 1) * (2 * math.pi / DIRECTIONS_AROUND) * (1 if k % 2 else -1) if k else base
        direction = (math.cos(angle), math.sin(angle))
        at = via_site(board, obs, pad, direction, rules, max_length_mm=2.0)
        if at is not None:
            lay_stub(board, obs, pad, at, rules)
            return at
    return None


def stitch_poured_pads(board, obs: Obstacles, poured: set[str], rules: ViaRules) -> dict:
    """Before routing: a via next to every surface pad of a poured net, so the pour on the other layer reaches
    it whatever the router lays around it afterwards (the reference puts fifteen such vias on the smoke-test
    board; a pad left to the fill was walled in by tracks on three of nine, 2026-09-23). Through-hole pads
    reach both pours by themselves. Fixed order (D25). Returns what was placed and what found no site."""
    placed, missed = [], []
    pads = sorted(((fp.GetReference(), pad.GetNumber(), fp, pad) for fp in board.GetFootprints() for pad in fp.Pads()
                   if pad.GetNetname() in poured and not pad.GetDrillSizeX()), key=lambda r: (r[0], r[1]))
    for ref, number, fp, pad in pads:
        at = stitch_pad(board, obs, pad, fp, rules)
        (placed if at else missed).append(f"{ref}.{number}")
    return {"stitched": placed, "no_site": missed}
