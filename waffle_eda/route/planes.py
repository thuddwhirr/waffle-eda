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
board's rules; a pad that can hold the via gets it in the pad (a package's thermal pad). A pad with no
straight site gets an L-shaped one where there is room (D91: six of upduino's ten such pads): the stub leaves
the pad along one of its axes to a corner and turns straight to the via, the nearest site within `REACH_MM`
over every direction. A pad with no room at all gets no feed and stays the router's.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

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
    corner: tuple[float, float] | None = None  # an L-shaped stub turns here (D91); None for a straight one
    inside: bool = False  # the via inside the pad's copper but off its centre (D99): no stub either

    @property
    def in_pad(self) -> bool:
        return self.via == self.start or self.inside

    @property
    def legs(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        """The stub's segments, from the pad's centre to the via."""
        if self.in_pad:
            return []
        if self.corner is None:
            return [(self.start, self.via)]
        return [(self.start, self.corner), (self.corner, self.via)]

    @property
    def length_mm(self) -> float:
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in self.legs)


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
    name: str = ""  # "REF-N" for a pad; empty for a track, a via or a fill

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


def _rects(board, copper: bool = False) -> list[_Rect]:
    """Every pad as a rectangle; with ``copper``, every track segment (a rectangle bounding its round ends)
    and via (a square) too, for a search on a routed board."""
    rects = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if not pad.GetLayerSet().CuStack():
                continue
            centre, axis, half_len, half_wid = _geometry(pad)
            drill = pad.GetDrillSize()
            hole_r = max(kb.mm(drill.x), kb.mm(drill.y)) / 2
            rects.append(_Rect(pad.GetNetCode(), centre, axis, half_len, half_wid, hole_r,
                               math.hypot(half_len, half_wid), _local_clearance_mm(pad),
                               f"{fp.GetReference()}-{pad.GetNumber()}"))
    if copper:
        for t in kb.track_segments(board):
            (ax, ay), (bx, by) = (kb.mm(t.GetStart().x), kb.mm(t.GetStart().y)), (kb.mm(t.GetEnd().x), kb.mm(t.GetEnd().y))
            length, half_w = math.hypot(bx - ax, by - ay), kb.mm(t.GetWidth()) / 2
            axis = ((bx - ax) / length, (by - ay) / length) if length > 0 else (1.0, 0.0)
            rects.append(_Rect(t.GetNetCode(), ((ax + bx) / 2, (ay + by) / 2), axis, length / 2 + half_w, half_w, 0.0,
                               length / 2 + half_w, 0.0))
        for v in kb.vias(board):
            r = kb.via_diameter_mm(v) / 2
            rects.append(_Rect(v.GetNetCode(), (kb.mm(v.GetPosition().x), kb.mm(v.GetPosition().y)), (1.0, 0.0), r, r,
                               kb.via_drill_mm(v) / 2, r * math.sqrt(2), 0.0))
    return rects


class _Search:
    """The clearance tests for one board's rules; the feeds already placed count as obstacles."""

    def __init__(self, board, rules, width_mm: float, via_mm: float, drill_mm: float, copper: bool = False):
        self.rects = _rects(board, copper)
        # A filled zone of another net is not an obstacle: the refill clears the pour around a via or a track
        # of another net (the routed board's vias through both planes score 0 electrical violations). Taking
        # the fills as copper (2026-09-25 to D98) left a via no site anywhere on a board with a plane of another
        # net, since a via always passes through it: the stitching found no room and the after form 38 sites.
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

    # A feed may touch any copper of its own net, another pad of it included: 41 of upduino's 82 feed vias sit
    # over a neighbouring same-net pad, which the router counts as a violation with via-in-pad off (D85) and
    # which is legal to KiCad. A rule keeping a feed's copper to its own pad fed 56 pads for 88 and measured
    # worse at four passes (D88: 63 of 86 for 67, GND and +3V3 in pieces, the failed insertions 46 for 38).

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

    def stub_clear(self, net: int, a: tuple[float, float], b: tuple[float, float], rects: list[_Rect],
                   layer: int | None = None) -> bool:
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


IN_PAD_MARGIN_MM = 0.05  # a via in a pad keeps its ring this far inside the pad's copper (D93)
INSIDE_STEP_MM = 0.2  # the grid a via searches inside a pad whose centre is taken (D99)


def plane_feeds(board, rules, nets: set[str], width_mm: float | None = None, via_mm: float | None = None,
                drill_mm: float | None = None, pads: set[str] | None = None, copper: bool = False,
                via_in_pad: bool = False, skip: set[str] | None = None) -> list[Feed]:
    """The feeds for every SMD pad of ``nets`` that has room for one (only the pads named "REF-N" in ``pads``
    when given). Nothing is added to the board; :func:`lay_feeds` does that. Width and via default to the
    board's smallest. With ``copper`` the board's tracks and vias are obstacles too (a routed board). With
    ``via_in_pad`` (D93: the fab fills and caps its vias) the via goes in any pad it fits, ring and margin
    inside the copper; without, only in a thermal pad, as the references do. Pads named in ``skip`` get no
    feed (the pins left to their layer's pour, D95)."""
    width_mm = width_mm or rules.min_track_mm
    via_mm = via_mm or rules.min_via_mm
    drill_mm = drill_mm or rules.min_drill_mm
    search = _Search(board, rules, width_mm, via_mm, drill_mm, copper)
    r = search.via_r
    feeds: list[Feed] = []
    for fp in board.GetFootprints():
        fx, fy = kb.mm(fp.GetPosition().x), kb.mm(fp.GetPosition().y)
        for pad in fp.Pads():
            if pad.GetNetname() not in nets or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            if pads is not None and f"{fp.GetReference()}-{pad.GetNumber()}" not in pads:
                continue
            if skip and f"{fp.GetReference()}-{pad.GetNumber()}" in skip:
                continue
            stack = pad.GetLayerSet().CuStack()
            if not stack:
                continue
            net = pad.GetNetCode()
            name = f"{fp.GetReference()}-{pad.GetNumber()}"
            centre, (ux, uy), half_len, half_wid = _geometry(pad)
            rects = search.near(centre)
            feed = None
            # a via in the pad where the pad is a package's thermal pad, two vias wide at least (the references
            # put none in a passive's pad), or, with via_in_pad, wherever the ring fits inside the copper (D93)
            fits = (half_len >= via_mm and half_wid >= via_mm) or (
                via_in_pad and half_len >= via_mm / 2 + IN_PAD_MARGIN_MM and half_wid >= via_mm / 2 + IN_PAD_MARGIN_MM)
            if fits and search.via_clear(net, centre, rects):
                feed = Feed(pad.GetNetname(), stack[0], name, centre, centre, width_mm, via_mm, drill_mm)
            elif fits and copper:  # the centre taken on a routed board (another net's track under the pad on
                # another layer meets a through via): the nearest clear point inside the copper, ring and
                # margin inside (D99: U2-49's site under 335 tracks on In1)
                inset_l, inset_w = half_len - (via_mm / 2 + IN_PAD_MARGIN_MM), half_wid - (via_mm / 2 + IN_PAD_MARGIN_MM)
                kl, kw = int(inset_l / INSIDE_STEP_MM), int(inset_w / INSIDE_STEP_MM)
                points = sorted(((a * a + b * b, a, b) for a in (i * INSIDE_STEP_MM for i in range(-kl, kl + 1))
                                 for b in (j * INSIDE_STEP_MM for j in range(-kw, kw + 1))))
                for _d, a, b in points:
                    q = (round(centre[0] + ux * a - uy * b, 4), round(centre[1] + uy * a + ux * b, 4))
                    if search.via_clear(net, q, rects):
                        feed = Feed(pad.GetNetname(), stack[0], name, centre, q, width_mm, via_mm, drill_mm, inside=True)
                        break
            if feed is None:
                radial = (centre[0] - fx, centre[1] - fy)
                directions = [(ux, uy, half_len), (-ux, -uy, half_len), (-uy, ux, half_wid), (uy, -ux, half_wid)]
                directions.sort(key=lambda d: -(d[0] * radial[0] + d[1] * radial[1]))
                for dx, dy, extent in directions:
                    # the clearance away from its own pad: the router holds a via to the clearance from a pad
                    # of its own net while via-in-pad is off, which KiCad's export leaves it (its Via.isObstacle;
                    # 2 violations per feed on upduino when the via touched the pad); the stub bridges the gap
                    d = extent + r + search.clear
                    while d <= REACH_MM and feed is None:
                        p = (centre[0] + dx * d, centre[1] + dy * d)
                        edge = (centre[0] + dx * extent, centre[1] + dy * extent)
                        if search.via_clear(net, p, rects) and search.stub_clear(net, edge, p, rects, stack[0]):
                            feed = Feed(pad.GetNetname(), stack[0], name, centre, (round(p[0], 4), round(p[1], 4)),
                                        width_mm, via_mm, drill_mm)
                        d += STEP_MM
                    if feed is not None:
                        break
            if feed is None:  # no straight site: an L-shaped one, the nearest over every direction (D91)
                own = _Rect(net, centre, (ux, uy), half_len, half_wid, 0.0, math.hypot(half_len, half_wid), 0.0, name)
                site = _l_site(search, net, own, rects, stack[0])
                if site is not None:
                    corner, p = site
                    feed = Feed(pad.GetNetname(), stack[0], name, centre, (round(p[0], 4), round(p[1], 4)),
                                width_mm, via_mm, drill_mm, corner=(round(corner[0], 4), round(corner[1], 4)))
            if feed is not None:
                feeds.append(feed)
                search.placed.append((net, feed.via))
    return feeds


def _l_site(search: _Search, net: int, own: _Rect, rects: list[_Rect], layer: int):
    """The nearest via site within the reach that an L-shaped stub reaches from the pad ``own``: out of the pad
    along one of its axes to the via's projection on that axis (the corner), then straight to the via. Sites
    are tried nearest first, at every 10 degrees and every `STEP_MM`; the via keeps the router's clearance
    from its own pad (a via touching a same-net pad is a violation to it, D85). Returns (corner, via) or None."""
    r = search.via_r
    ux, uy = own.axis
    axes = ((ux, uy, own.half_len), (-ux, -uy, own.half_len), (-uy, ux, own.half_wid), (uy, -ux, own.half_wid))
    start = min(own.half_len, own.half_wid) + r + search.clear
    d = math.ceil(start / STEP_MM) * STEP_MM
    while d <= REACH_MM:
        for k in range(36):
            a = math.radians(k * 10)
            p = (own.centre[0] + math.cos(a) * d, own.centre[1] + math.sin(a) * d)
            if own.distance(p) < r + search.clear or not search.via_clear(net, p, rects):
                continue
            for dx, dy, ext in axes:
                edge = (own.centre[0] + dx * ext, own.centre[1] + dy * ext)
                along = (p[0] - edge[0]) * dx + (p[1] - edge[1]) * dy
                if along < r:  # the via must sit beyond the pad's edge on this axis
                    continue
                corner = (edge[0] + dx * along, edge[1] + dy * along)
                if (search.stub_clear(net, edge, corner, rects, layer)
                        and search.stub_clear(net, corner, p, rects, layer)):
                    return corner, p
        d += STEP_MM
    return None


def _via_at(board, feed: Feed):
    pos = pcbnew.VECTOR2I(kb.nm(feed.via[0]), kb.nm(feed.via[1]))
    for v in kb.vias(board):
        if v.GetPosition() == pos and v.GetNetname() == feed.net:
            return v
    return None


def _stub_at(board, feed: Feed, leg: tuple[tuple[float, float], tuple[float, float]]):
    a = (kb.nm(leg[0][0]), kb.nm(leg[0][1]))
    b = (kb.nm(leg[1][0]), kb.nm(leg[1][1]))
    for t in kb.track_segments(board):
        s, e = t.GetStart(), t.GetEnd()
        if t.GetLayer() == feed.layer and t.GetNetname() == feed.net and {(s.x, s.y), (e.x, e.y)} == {a, b}:
            return t
    return None


def lay_feeds(board, feeds: list[Feed], in_pad: bool = True, stubs: bool = True) -> list:
    """Add the feeds to the board (a stub and a via each, the via alone in a pad); a feed already there is
    left alone, so the same list re-lays what a session import dropped. Returns the items added. With
    ``in_pad`` false the vias in pads are skipped: the router must not see them (a via in a same-net pad is a
    violation to it while via-in-pad is off), and nothing routes through a pad anyway. With ``stubs`` false
    only the vias are laid (the "vias" form of D91: the router sees the vias, the stubs come after)."""
    nets = board.GetNetsByName()
    made = []
    for feed in feeds:
        if feed.in_pad and not in_pad:
            continue
        net = nets[feed.net]
        for leg in (feed.legs if stubs else []):
            if _stub_at(board, feed, leg) is not None:
                continue
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(kb.nm(leg[0][0]), kb.nm(leg[0][1])))
            track.SetEnd(pcbnew.VECTOR2I(kb.nm(leg[1][0]), kb.nm(leg[1][1])))
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


def pieces(board, net: str) -> list[set[str]]:
    """The net's pads grouped by what KiCad's connectivity joins (pads, tracks, vias and filled zones), read
    one hop at a time as `kicad.board.open_nets` does: one group is a connected net. Pads are "REF-N"."""
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    names: dict[str, str] = {}
    items = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() == net:
                names[pad.m_Uuid.AsString()] = f"{fp.GetReference()}-{pad.GetNumber()}"
                items.append(pad)
    items += [t for t in board.GetTracks() if t.GetNetname() == net]
    items += [z for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname() == net]
    for x in items:
        xid = x.m_Uuid.AsString()
        find(xid)
        for y in list(conn.GetConnectedPads(x)) + list(conn.GetConnectedTracks(x)):
            rx, ry = find(xid), find(y.m_Uuid.AsString())
            if rx != ry:
                parent[rx] = ry
    groups: dict[str, set[str]] = {}
    for uid, name in names.items():
        groups.setdefault(find(uid), set()).add(name)
    return sorted(groups.values(), key=lambda g: (-len(g), sorted(g)))


def stitch(board, rules, nets: set[str]) -> list[Feed]:
    """On a routed board with its zones filled: a feed for one pad of every piece of a plane net beyond the
    largest, so a refill joins it to the plane (the class B stitching, D85). Returns what it laid."""
    laid: list[Feed] = []
    for net in sorted(nets):
        groups = pieces(board, net)
        for group in groups[1:]:
            found = plane_feeds(board, rules, {net}, pads=group, copper=True)
            if found:
                lay_feeds(board, found[:1])
                laid.append(found[0])
    return laid


def finish(board, out: Path, rules, nets: set[str]) -> dict:
    """A routed board's finishing, the gate's own: saved to ``out``, its zones filled in a child process
    (`kicad/refill.py`, D14), every plane net stitched (one feed for every piece beyond the largest) and filled
    again when a feed was added. Returns the fill's report and the feeds the stitching laid."""
    from waffle_eda.kicad import refill
    kb.save_board(board, out)
    fill = refill.refill_file(out)
    stitched: list[Feed] = []
    if nets:
        routed = kb.load_board(out)
        stitched = stitch(routed, rules, nets)
        if stitched:
            kb.save_board(routed, out)
            fill = refill.refill_file(out)
    return {"fill": fill, "stitched": stitched}


def plane_pads(board, nets: set[str]) -> set[str]:
    """Every pad of ``nets`` ("REF-N"), plated or not."""
    return {f"{fp.GetReference()}-{pad.GetNumber()}" for fp in board.GetFootprints() for pad in fp.Pads()
            if pad.GetNetname() in nets and pad.GetLayerSet().CuStack()}


def unfed_pads(board, feeds: list[Feed], nets: set[str], pth_nets: set[str] = frozenset()) -> set[str]:
    """The SMD pads of ``nets`` that no feed reaches, and the plated pads of ``pth_nets`` (plane nets whose
    pour comes after the import, so nothing of theirs is in the DSN for a plated pin to reach)."""
    fed = {f.pad for f in feeds}
    out = set()
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            name = f"{fp.GetReference()}-{pad.GetNumber()}"
            if pad.GetNetname() not in nets or not pad.GetLayerSet().CuStack() or name in fed:
                continue
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD or pad.GetNetname() in pth_nets:
                out.add(name)
    return out


TARGET_REACH_MM = 3.0  # how far from a pad no feed reaches its net's feeds are fixed as vias for the router


def targets_for_unfed(board, feeds: list[Feed], nets: set[str], reach_mm: float = TARGET_REACH_MM,
                      per_pad: int = 2, pth_nets: set[str] = frozenset()) -> list[Feed]:
    """For every SMD pad of ``nets`` that no feed reaches (D91: on upduino, nine pads boxed in by other nets'
    pads touching theirs), the nearest ``per_pad`` feeds of its net within ``reach_mm``: the reserved form
    hands these to the router as fixed vias, and the pad stays in its network to be routed to one."""
    centres = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            centres[f"{fp.GetReference()}-{pad.GetNumber()}"] = (pad.GetNetname(), (kb.mm(pad.GetPosition().x), kb.mm(pad.GetPosition().y)))
    chosen: dict[str, Feed] = {}
    for name in sorted(unfed_pads(board, feeds, nets, pth_nets)):
        net, (px, py) = centres[name]
        near = sorted((math.hypot(f.via[0] - px, f.via[1] - py), f.pad, f) for f in feeds if f.net == net and not f.in_pad)
        for dist, _pad, f in near[:per_pad]:
            if dist <= reach_mm:
                chosen[f.pad] = f
    return [chosen[k] for k in sorted(chosen)]
