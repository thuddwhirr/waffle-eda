"""Feeds from a plane net's SMD pads to its plane: a via beside each pad with a stub to it, or a via in a pad
big enough, laid before the router runs and fixed, so the plane connects the net and the router routes only
what is left (the pads with no room for a via), as the references do (D85).

Measured first on `upduino-v3.01` (D84, D85): with no plane in the DSN the router routes GND and +3V3 as
tracks (73 and 37 of its 270 items), walls four GND pins in by its third pass, and the pours laid afterwards
come out in two pieces each; with the reference's plane handed over on a `power` layer it must put a via
beside every pad itself and fails where the pads are dense (28 GND pads untouched, one GND via); its own
fanout stage vias every SMD pin of the board (218 of 307) and routes worse still. The references put a via
within 1.5 mm of most plane pads (median 0.9 to 1.2 mm) and reach the rest through the outer pours.

A feed is found by sliding a via outward from the pad along the pad's own axes, the direction away from the
footprint's centre first, until the via and its stub clear every other net's pad copper and hole by the
board's rules; a pad that can hold the via gets it in the pad (a package's thermal pad). A pad with no room
within `REACH_MM` gets no feed and stays the router's.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pcbnew

from waffle_eda.kicad import board as kb

STEP_MM = 0.05  # the via slides outward in these steps
REACH_MM = 1.5  # how far from the pad centre a via may sit: the references' feeds end within it
MARGIN_MM = 0.01  # over every rule, so the repair has nothing to settle at a feed


@dataclass(frozen=True)
class Feed:
    net: str
    layer: int  # the pad's copper layer, where the stub runs
    pad: str  # "REF-N"
    start: tuple[float, float]  # the pad's centre, mm
    via: tuple[float, float]  # the via's centre, mm; the pad's centre for a via in the pad
    width_mm: float
    via_mm: float
    drill_mm: float

    @property
    def in_pad(self) -> bool:
        return self.via == self.start

    @property
    def length_mm(self) -> float:
        return math.hypot(self.via[0] - self.start[0], self.via[1] - self.start[1])


@dataclass(frozen=True)
class _Rect:
    """A pad as an oriented rectangle (exact for rectangular pads, a bound for round and oval ones)."""
    net: int
    centre: tuple[float, float]
    axis: tuple[float, float]
    half_len: float
    half_wid: float
    hole_r: float  # 0 for an SMD pad
    reach: float  # the rectangle's circumradius, to skip far pads quickly
    local: float  # the pad's own clearance, mm (a fiducial's 0.375 on upduino), 0 without one

    def distance(self, p: tuple[float, float]) -> float:
        """From a point to the rectangle's copper (0 inside)."""
        dx, dy = p[0] - self.centre[0], p[1] - self.centre[1]
        ux, uy = self.axis
        along, across = abs(dx * ux + dy * uy), abs(-dx * uy + dy * ux)
        return math.hypot(max(along - self.half_len, 0.0), max(across - self.half_wid, 0.0))

    def hole_distance(self, p: tuple[float, float]) -> float:
        """From a point to the hole's edge (infinite without a hole)."""
        if self.hole_r <= 0:
            return math.inf
        return math.hypot(p[0] - self.centre[0], p[1] - self.centre[1]) - self.hole_r


def _unit(deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    return (math.cos(r), -math.sin(r))  # KiCad's y points down, angles are counter-clockwise


def _geometry(pad) -> tuple[tuple[float, float], tuple[float, float], float, float]:
    """(centre, long-axis unit vector, half length along it, half width across it), mm."""
    pos = pad.GetPosition()
    stack = pad.GetLayerSet().CuStack()
    size = pad.GetSize(stack[0] if stack else pcbnew.F_Cu)
    sx, sy = kb.mm(size.x), kb.mm(size.y)
    ux, uy = _unit(float(pad.GetOrientationDegrees()))
    if sy > sx:
        ux, uy = -uy, ux
        sx, sy = sy, sx
    return (kb.mm(pos.x), kb.mm(pos.y)), (ux, uy), sx / 2, sy / 2


def _local_clearance_mm(pad) -> float:
    value = pad.GetLocalClearance()
    if value is None:
        return 0.0
    if hasattr(value, "value"):  # KiCad 9 returns an optional
        return kb.mm(value.value()) if value.has_value() else 0.0
    return kb.mm(value)


def _rects(board) -> list[_Rect]:
    rects = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if not pad.GetLayerSet().CuStack():
                continue
            centre, axis, half_len, half_wid = _geometry(pad)
            drill = pad.GetDrillSize()
            hole_r = max(kb.mm(drill.x), kb.mm(drill.y)) / 2
            rects.append(_Rect(pad.GetNetCode(), centre, axis, half_len, half_wid, hole_r,
                               math.hypot(half_len, half_wid), _local_clearance_mm(pad)))
    return rects


class _Search:
    """The clearance tests for one board's rules; the feeds already placed count as obstacles."""

    def __init__(self, board, rules, width_mm: float, via_mm: float, drill_mm: float):
        self.rects = _rects(board)
        self.clear = rules.clearance_mm + MARGIN_MM
        self.hole = rules.hole_to_copper_mm + MARGIN_MM
        self.edge = rules.edge_clearance_mm + MARGIN_MM
        self.bbox = kb.outline_bbox_mm(board)
        self.width = width_mm
        self.via_r = via_mm / 2
        self.drill_r = drill_mm / 2
        self.placed: list[tuple[int, tuple[float, float]]] = []  # (net, via centre)

    def near(self, centre: tuple[float, float]) -> list[_Rect]:
        limit = REACH_MM + self.via_r + max(self.clear, self.hole) + 0.1
        return [r for r in self.rects
                if math.hypot(r.centre[0] - centre[0], r.centre[1] - centre[1]) <= limit + r.reach + r.local]

    def copper(self, o: _Rect) -> float:
        """The clearance copper must keep from this pad: the rule, or the pad's own if larger."""
        return max(self.clear, o.local + MARGIN_MM)

    def via_clear(self, net: int, p: tuple[float, float], rects: list[_Rect]) -> bool:
        x0, y0, x1, y1 = self.bbox
        r = self.via_r
        if not (x0 + self.edge + r <= p[0] <= x1 - self.edge - r and y0 + self.edge + r <= p[1] <= y1 - self.edge - r):
            return False
        for o in rects:
            if o.net == net:
                continue
            if o.distance(p) < r + self.copper(o) or o.distance(p) < self.drill_r + self.hole:
                return False
            if o.hole_distance(p) < r + self.hole:
                return False
        for o_net, q in self.placed:
            d = math.hypot(q[0] - p[0], q[1] - p[1])
            if o_net == net:
                if d < 2 * r:  # no via on top of another
                    return False
            elif d < 2 * r + self.clear or d < r + self.drill_r + self.hole:
                return False
        return True

    def stub_clear(self, net: int, a: tuple[float, float], b: tuple[float, float], rects: list[_Rect]) -> bool:
        """The stub's copper from ``a`` to ``b`` (the parts outside the pad and the via) against other nets."""
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length <= 0:
            return True
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        n = max(1, int(length / STEP_MM))
        half = self.width / 2
        for k in range(n + 1):
            p = (a[0] + ux * length * k / n, a[1] + uy * length * k / n)
            for o in rects:
                if o.net == net:
                    continue
                if o.distance(p) < half + self.copper(o) or o.hole_distance(p) < half + self.hole:
                    return False
            for o_net, q in self.placed:
                if o_net != net and math.hypot(q[0] - p[0], q[1] - p[1]) < half + self.via_r + self.clear:
                    return False
        return True


def plane_feeds(board, rules, nets: set[str], width_mm: float | None = None, via_mm: float | None = None,
                drill_mm: float | None = None) -> list[Feed]:
    """The feeds for every SMD pad of ``nets`` that has room for one. Nothing is added to the board;
    :func:`lay_feeds` does that. Width and via default to the board's smallest."""
    width_mm = width_mm or rules.min_track_mm
    via_mm = via_mm or rules.min_via_mm
    drill_mm = drill_mm or rules.min_drill_mm
    search = _Search(board, rules, width_mm, via_mm, drill_mm)
    r = search.via_r
    feeds: list[Feed] = []
    for fp in board.GetFootprints():
        fx, fy = kb.mm(fp.GetPosition().x), kb.mm(fp.GetPosition().y)
        for pad in fp.Pads():
            if pad.GetNetname() not in nets or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            stack = pad.GetLayerSet().CuStack()
            if not stack:
                continue
            net = pad.GetNetCode()
            centre, (ux, uy), half_len, half_wid = _geometry(pad)
            rects = search.near(centre)
            feed = None
            # a via in the pad only where the pad is a package's thermal pad, two vias wide at least: the
            # references put none in a passive's pad
            if half_len >= via_mm and half_wid >= via_mm and search.via_clear(net, centre, rects):
                feed = Feed(pad.GetNetname(), stack[0], f"{fp.GetReference()}-{pad.GetNumber()}", centre, centre,
                            width_mm, via_mm, drill_mm)
            else:
                radial = (centre[0] - fx, centre[1] - fy)
                directions = [(ux, uy, half_len), (-ux, -uy, half_len), (-uy, ux, half_wid), (uy, -ux, half_wid)]
                directions.sort(key=lambda d: -(d[0] * radial[0] + d[1] * radial[1]))
                for dx, dy, extent in directions:
                    d = max(extent + r - STEP_MM, 0.0)
                    while d <= REACH_MM and feed is None:
                        p = (centre[0] + dx * d, centre[1] + dy * d)
                        edge = (centre[0] + dx * extent, centre[1] + dy * extent)
                        if search.via_clear(net, p, rects) and search.stub_clear(net, edge, p, rects):
                            feed = Feed(pad.GetNetname(), stack[0], f"{fp.GetReference()}-{pad.GetNumber()}",
                                        centre, (round(p[0], 4), round(p[1], 4)), width_mm, via_mm, drill_mm)
                        d += STEP_MM
                    if feed is not None:
                        break
            if feed is not None:
                feeds.append(feed)
                search.placed.append((net, feed.via))
    return feeds


def _via_at(board, feed: Feed):
    pos = pcbnew.VECTOR2I(kb.nm(feed.via[0]), kb.nm(feed.via[1]))
    for v in kb.vias(board):
        if v.GetPosition() == pos and v.GetNetname() == feed.net:
            return v
    return None


def _stub_at(board, feed: Feed):
    a = (kb.nm(feed.start[0]), kb.nm(feed.start[1]))
    b = (kb.nm(feed.via[0]), kb.nm(feed.via[1]))
    for t in kb.track_segments(board):
        s, e = t.GetStart(), t.GetEnd()
        if t.GetLayer() == feed.layer and t.GetNetname() == feed.net and {(s.x, s.y), (e.x, e.y)} == {a, b}:
            return t
    return None


def lay_feeds(board, feeds: list[Feed]) -> list:
    """Add the feeds to the board (a stub and a via each, the via alone in a pad); a feed already there is
    left alone, so the same list re-lays what a session import dropped. Returns the items added."""
    nets = board.GetNetsByName()
    made = []
    for feed in feeds:
        net = nets[feed.net]
        if not feed.in_pad and _stub_at(board, feed) is None:
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(kb.nm(feed.start[0]), kb.nm(feed.start[1])))
            track.SetEnd(pcbnew.VECTOR2I(kb.nm(feed.via[0]), kb.nm(feed.via[1])))
            track.SetWidth(kb.nm(feed.width_mm))
            track.SetLayer(feed.layer)
            track.SetNet(net)
            board.Add(track)
            made.append(track)
        if _via_at(board, feed) is None:
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(kb.nm(feed.via[0]), kb.nm(feed.via[1])))
            via.SetViaType(pcbnew.VIATYPE_THROUGH)
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            via.SetDrill(kb.nm(feed.drill_mm))
            kb.set_via_diameter(via, feed.via_mm)
            via.SetNet(net)
            board.Add(via)
            made.append(via)
    return made
