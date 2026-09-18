"""BGA fan-out: an escape for every ball of the given nets, placed only where it clears the copper already there.

The standard 0.8 mm-pitch fan-out, as measured on the references (docs/decisions.md D13):

* every ball owns its outward diagonal gap; power and ground balls take theirs first and unconditionally, a dog-bone
  via being their whole connection (a power ball without a via is an error);
* ring 1 signals leave on the top layer straight out; ring 2 signals use the top-layer channel between two ring-1
  pads where no via sits in it; inner rings dog-bone to their site and run out on an inner layer along a ball column
  line, one track per (layer, side, line); ring 3 may fall back to a free top-layer channel;
* with ``style = "in-pad"`` the via sits in the pad (ButterStick) and inner-layer tracks run along the half lines
  between the via rows instead.

Nothing is placed on the assumption that a router will finish it; every escape ends ``out_pitches`` beyond the
outer row, where the bus router picks it up.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import pcbnew

from waffle_eda.kicad import board as kb
from waffle_eda.route.lattice import Lattice, Ball
from waffle_eda.route.obstacles import Obstacles


@dataclass(frozen=True)
class FanoutRules:
    track_mm: float
    clearance_mm: float
    via_mm: float
    via_drill_mm: float
    inner_layers: tuple[str, ...]  # copper layers, by name, that escapes may use besides F.Cu
    style: str = "dogbone"  # or "in-pad"
    top_rings: int = 2  # rings that may leave on the top layer without a via (1 or 2)
    out_pitches: float = 1.5  # where escapes end, in pitches beyond the outer row
    stub_mm: float | None = None  # width of the pad-to-via stub; default the track width
    hole_clearance_mm: float = 0.0  # a hole's wall to copper of another net (0: not enforced)


@dataclass
class FanoutResult:
    package: str
    escaped: dict[str, str] = field(default_factory=dict)  # ball number -> how
    failed: dict[str, str] = field(default_factory=dict)  # ball number -> why
    counts: Counter = field(default_factory=Counter)
    diagnostics: dict[str, list[str]] = field(default_factory=dict)  # ball number -> failed attempts

    @property
    def total(self) -> int:
        return len(self.escaped) + len(self.failed)

    def summary(self) -> str:
        return (f"{self.package}: {len(self.escaped)}/{self.total} escaped; "
                + ", ".join(f"{k} {v}" for k, v in sorted(self.counts.items())))


class _Placer:
    """Builds one escape as pending items and commits it only if every item clears the existing copper."""

    def __init__(self, board, lat: Lattice, rules: FanoutRules, obstacles: Obstacles, layer_ids: dict[str, int]):
        self.board, self.lat, self.rules, self.obs, self.layer_ids = board, lat, rules, obstacles, layer_ids
        self.pending: list = []
        self.used_sites: set = set()  # canonical (i, j) keys of gaps holding a via
        self.used_lines: set = set()  # (layer, side, line)
        self.used_channels: set = set()  # (side, channel) top-layer channels
        self.stub_w = rules.stub_mm or rules.track_mm
        # Sites already holding vias (other nets' copper on a real board).
        for item in obstacles.vias():
            if True:
                p = item.GetPosition()
                fi, fj = (kb.mm(p.x) - lat.x0) / lat.pitch, (kb.mm(p.y) - lat.y0) / lat.pitch
                if -3 <= fi <= lat.cols + 2 and -3 <= fj <= lat.rows + 2:
                    self.used_sites.add((round(fi * 2) / 2, round(fj * 2) / 2))

    def track(self, net, layer: int, a: tuple[float, float], b: tuple[float, float], width_mm: float | None = None):
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(pcbnew.VECTOR2I(kb.nm(a[0]), kb.nm(a[1])))
        t.SetEnd(pcbnew.VECTOR2I(kb.nm(b[0]), kb.nm(b[1])))
        t.SetWidth(kb.nm(width_mm or self.rules.track_mm))
        t.SetLayer(layer)
        t.SetNet(net)
        self.pending.append(t)

    def via(self, net, p: tuple[float, float]):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(pcbnew.VECTOR2I(kb.nm(p[0]), kb.nm(p[1])))
        v.SetDrill(kb.nm(self.rules.via_drill_mm))
        kb.set_via_diameter(v, self.rules.via_mm)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(net)
        self.pending.append(v)

    def commit(self, skip: set | None = None) -> bool:
        self.last_failure = None
        for item in self.pending:
            hit = self.obs.clear(item, self.rules.clearance_mm, skip)
            if hit is not None:
                kind = hit.GetClass()
                where = self.board.GetLayerName(item.GetLayer()) if item.GetClass() != "PCB_VIA" else "via"
                self.last_failure = f"{where} {item.GetClass()} hits {kind} of net {hit.GetNetname()!r}"
                break
        ok = self.last_failure is None
        if ok:
            for item in self.pending:
                self.board.Add(item)
                self.obs.add(item)
        self.pending.clear()
        return ok

    def site_free(self, side, across_half, along_half) -> bool:
        if not (-0.5 <= across_half <= self.lat.edge_len(side) - 0.5):
            return False
        return self.lat.key(side, across_half, along_half) not in self.used_sites

    def channel_free(self, side, channel, from_along_half) -> bool:
        """A top-layer channel stub from ``from_along_half`` outward passes every diagonal site down to -0.5."""
        if not (-0.5 <= channel <= self.lat.edge_len(side) - 0.5) or (side, channel) in self.used_channels:
            return False
        a = from_along_half
        while a >= -0.5:
            if self.lat.key(side, channel, a) in self.used_sites:
                return False
            a -= 1
        return True


def fanout(board: pcbnew.BOARD, package_ref: str, nets: set[str], rules: FanoutRules,
           exit_side: str | None = None, power_nets: set[str] = frozenset()) -> FanoutResult:
    """Escape every ball of ``nets`` (signals, leaving toward ``exit_side`` or their nearest edge) and of
    ``power_nets`` (dog-bone via at the nearest edge) on package ``package_ref``."""
    fp = kb.footprint(board, package_ref)
    if fp is None:
        raise KeyError(package_ref)
    lat = Lattice(fp)
    layer_ids = {name: lid for lid, name in kb.copper_layers(board)}
    inner = [layer_ids[n] for n in rules.inner_layers if n in layer_ids]
    region = lat.array_bbox_mm(rules.out_pitches + 2)
    obs = Obstacles(board, region)
    pl = _Placer(board, lat, rules, obs, layer_ids)
    F = pcbnew.F_Cu
    OUT = -rules.out_pitches
    result = FanoutResult(package_ref)

    def candidate_sides(ball: Ball) -> list[str]:
        """Sides by distance from the ball; the exit side goes first when it is within two rows of the nearest."""
        d = lat.distances(ball)
        sides = sorted(d, key=lambda s: (d[s], s != exit_side))
        if exit_side and d[exit_side] <= d[sides[0]] + 2:
            sides.remove(exit_side)
            sides.insert(0, exit_side)
        return sides

    def order(ball: Ball):
        is_power = ball.net in power_nets
        depth = min(lat.distances(ball).values())
        return (0 if is_power else 1, -depth, ball.i, ball.j)

    def dogbone(net, side, across, along, ah, along_half):
        """pad-to-via stub on F.Cu and the via at the diagonal site."""
        pl.track(net, F, lat.pt(side, across, along), lat.pt(side, ah, along_half), pl.stub_w)
        pl.via(net, lat.pt(side, ah, along_half))

    def escape_signal(ball: Ball, side: str) -> str | None:
        attempts = result.diagnostics.setdefault(ball.number, [])
        real_commit = pl.commit

        def logged_commit(skip=None):
            ok = real_commit(skip)
            if not ok:
                attempts.append(f"{side}: {pl.last_failure}")
            return ok

        pl.commit = logged_commit
        try:
            return _escape_signal(ball, side)
        finally:
            pl.commit = real_commit

    def _escape_signal(ball: Ball, side: str) -> str | None:
        net = pl.lat.pads[ball.number].GetNet()
        across, along = lat.side_coords(ball, side)
        ring = along + 1
        pad = lat.pads[ball.number]
        if ring == 1 and rules.top_rings >= 1:
            pl.track(net, F, lat.pt(side, across, 0), lat.pt(side, across, OUT))
            if pl.commit():
                return "ring1 F.Cu"
        if ring == 2 and rules.top_rings >= 2:
            for ch in (across + 0.5, across - 0.5):
                if pl.channel_free(side, ch, 0.5):
                    pl.track(net, F, lat.pt(side, across, 1), lat.pt(side, ch, 0.5))
                    pl.track(net, F, lat.pt(side, ch, 0.5), lat.pt(side, ch, OUT))
                    if pl.commit():
                        pl.used_channels.add((side, ch))
                        return "ring2 F.Cu channel"
        if rules.style == "in-pad":
            # via in the pad; inner-layer run along a half line between the via rows, reached by a diagonal and,
            # for a line further out, a jog along the half row between the via rows
            site = lat.key(side, across, along)
            if site in pl.used_sites:
                return None
            for k in (0.5, 1.5, 2.5, 3.5):
                for sgn in (+1, -1):
                    line = across + sgn * k
                    if not (-0.5 <= line <= lat.edge_len(side) - 0.5):
                        continue
                    for layer in inner:
                        if (layer, side, line) in pl.used_lines:
                            continue
                        first = across + sgn * 0.5
                        pl.via(net, lat.pt(side, across, along))
                        pl.track(net, layer, lat.pt(side, across, along), lat.pt(side, first, along - 0.5))
                        if k > 0.5:
                            pl.track(net, layer, lat.pt(side, first, along - 0.5), lat.pt(side, line, along - 0.5))
                        pl.track(net, layer, lat.pt(side, line, along - 0.5), lat.pt(side, line, OUT))
                        if pl.commit():
                            pl.used_sites.add(site)
                            pl.used_lines.add((layer, side, line))
                            return f"ring{ring} via-in-pad {board.GetLayerName(layer)}"
            return None
        # dog-bone: via at a diagonal site (outward first, inward as a fallback); inner-layer run along a ball column
        # line between the via columns, reached by a diagonal onto the row beside the via and, for a line further out,
        # a jog along that row (rows and columns are free of vias on inner layers; the half lines hold them)
        for along_half, row in ((along - 0.5, along - 1), (along + 0.5, along)):
            for ah in (across + 0.5, across - 0.5):
                if not pl.site_free(side, ah, along_half):
                    continue
                for k in (0.5, 1.5, 2.5, 3.5):
                    for sgn in (+1, -1):
                        line = ah + sgn * k
                        if not (-1 <= line <= lat.edge_len(side)):
                            continue
                        for layer in inner:
                            if (layer, side, line) in pl.used_lines:
                                continue
                            first = ah + sgn * 0.5
                            dogbone(net, side, across, along, ah, along_half)
                            pl.track(net, layer, lat.pt(side, ah, along_half), lat.pt(side, first, row))
                            if k > 0.5:
                                pl.track(net, layer, lat.pt(side, first, row), lat.pt(side, line, row))
                            pl.track(net, layer, lat.pt(side, line, row), lat.pt(side, line, OUT))
                            if pl.commit():
                                pl.used_sites.add(lat.key(side, ah, along_half))
                                pl.used_lines.add((layer, side, line))
                                return f"ring{ring} dog-bone {board.GetLayerName(layer)}"
        if ring == 3 and rules.top_rings >= 2:
            for ch in (across + 0.5, across - 0.5):
                if pl.channel_free(side, ch, 1.5):
                    pl.track(net, F, lat.pt(side, across, along), lat.pt(side, ch, along - 0.5))
                    pl.track(net, F, lat.pt(side, ch, along - 0.5), lat.pt(side, ch, OUT))
                    if pl.commit():
                        pl.used_channels.add((side, ch))
                        return "ring3 F.Cu channel"
        return None

    for ball in sorted(lat.balls.values(), key=order):
        if ball.net in power_nets:
            net = lat.pads[ball.number].GetNet()
            side = lat.nearest_side(ball)
            across, along = lat.side_coords(ball, side)
            placed = False
            for ah, alh in ((across + 0.5, along - 0.5), (across - 0.5, along - 0.5),
                            (across + 0.5, along + 0.5), (across - 0.5, along + 0.5)):
                if not pl.site_free(side, ah, alh):
                    continue
                if rules.style == "in-pad":
                    pl.via(net, lat.pt(side, across, along))
                    site = lat.key(side, across, along)
                else:
                    dogbone(net, side, across, along, ah, alh)
                    site = lat.key(side, ah, alh)
                if pl.commit():
                    pl.used_sites.add(site)
                    result.escaped[ball.number] = "power dog-bone" if rules.style != "in-pad" else "power via-in-pad"
                    result.counts[result.escaped[ball.number]] += 1
                    placed = True
                    break
            if not placed:
                result.failed[ball.number] = "power ball without via"
                result.counts["FAILED power"] += 1
            continue
        if ball.net not in nets:
            continue
        sides = candidate_sides(ball)
        how = None
        for side in sides:
            how = escape_signal(ball, side)
            if how:
                how += f" {side}"
                break
        if how:
            result.escaped[ball.number] = how
            result.counts[how] += 1
        else:
            attempts = result.diagnostics.get(ball.number, [])
            hits = Counter(a.split(" hits ")[-1] for a in attempts if " hits " in a)
            result.failed[ball.number] = (f"ring {ball.ring}: {len(attempts)} attempts; "
                                          + (", ".join(f"{k} x{v}" for k, v in hits.most_common(3)) or "no free site or line"))
            result.counts[f"FAILED ring{ball.ring}"] += 1
        result.diagnostics.pop(ball.number, None) if how else None
    return result


def escape_gate(board: pcbnew.BOARD, package_ref: str, nets: set[str], power_nets: set[str] = frozenset()) -> dict:
    """Independent check: from each ball of ``nets``, does the net's copper reach outside the array (signals) or a
    via (power)? Walks the net's tracks and vias by touching endpoints, starting at the pad centre."""
    fp = kb.footprint(board, package_ref)
    lat = Lattice(fp)
    tol = kb.nm(0.01)  # endpoints coincide to a lattice point; 10 um covers file rounding
    by_net: dict[str, list] = {}
    for t in board.GetTracks():
        n = t.GetNetname()
        if n in nets or n in power_nets:
            by_net.setdefault(n, []).append(t)
    escaped, missing = {}, {}
    for ball in lat.balls.values():
        if ball.net not in nets and ball.net not in power_nets:
            continue
        start = pcbnew.VECTOR2I(kb.nm(ball.x_mm), kb.nm(ball.y_mm))
        frontier = [start]
        seen_pts = {(start.x, start.y)}
        seen_items = set()
        reached_via = False
        reached_out = False
        while frontier and not reached_out:
            p = frontier.pop()
            for item in by_net.get(ball.net, []):
                if id(item) in seen_items:
                    continue
                if item.GetClass() == "PCB_VIA":
                    q = item.GetPosition()
                    if abs(q.x - p.x) <= tol and abs(q.y - p.y) <= tol:
                        seen_items.add(id(item))
                        reached_via = True
                    continue
                s, e = item.GetStart(), item.GetEnd()
                hit = None
                if abs(s.x - p.x) <= tol and abs(s.y - p.y) <= tol:
                    hit = e
                elif abs(e.x - p.x) <= tol and abs(e.y - p.y) <= tol:
                    hit = s
                if hit is None:
                    continue
                seen_items.add(id(item))
                if not lat.inside_array(kb.mm(hit.x), kb.mm(hit.y), 0.5):
                    reached_out = True
                    break
                if (hit.x, hit.y) not in seen_pts:
                    seen_pts.add((hit.x, hit.y))
                    frontier.append(hit)
        ok = reached_via if ball.net in power_nets else reached_out
        (escaped if ok else missing)[ball.number] = ball.net
    return {"package": package_ref, "escaped": len(escaped), "missing": missing, "total": len(escaped) + len(missing)}
