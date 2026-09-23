"""Escape routing on the package lattice with negotiated congestion.

The package region is a quarter-pitch grid on every routable layer. On the top layer inside the array a path may
only use the half-pitch nodes (pad centres, the channels between two pads, the diagonal gaps between four): at a
fine pitch the channel has no slack, so a track there is centred or nowhere. On the inner layers, and on the top
layer outside the array, every quarter-pitch node is a place a track may run, straight or diagonal: that is what
lets a track thread between via rows that are too close for a track on the half-pitch line between them, as the
0.5 mm-pitch references do. A via sits on a half-pitch node inside the array (a gap, a channel, an empty ball
position, the pad itself when the style allows) or anywhere outside it.

Every step and via is checked against the board's existing copper with KiCad's own collision test; that is a hard
constraint. Conflicts between the balls' own escapes are resolved by negotiation (PathFinder): every ball routes with
a cost for each other ball a step or via would come too close to, the cost of a contested place rises each
iteration, and the iterations stop when nothing is contested. What "too close" means comes from the rules and the
pitch: offsets on a grid of an eighth of the pitch whose distance is under track + clearance (two tracks), via radius
+ clearance + half a track (a via and a track), via + clearance (two vias); a step is sampled along its length so
diagonals count too. The cost counts other balls, not samples, so a long overlap costs what a short one does. When
the conflicts stop shrinking, the balls the contested ones are too close to are ripped up as well, then their
partners, so that a pair stuck on one gap can make a settled third ball give way; the contested balls choose first.
The final pass commits the paths in the negotiated order under the exact collision test against the copper already
committed (the occupancy model blocks nothing there), and a stranded ball has its neighbours ripped up and re-placed
around it in a growing radius. A ball with no path is reported with the copper that blocked it, never left to a
router.
"""
from __future__ import annotations

import heapq
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass

import pcbnew

from waffle_eda.kicad import board as kb
from waffle_eda.route.lattice import Lattice, Ball
from waffle_eda.route.obstacles import Obstacles
from waffle_eda.route.fanout import FanoutRules, FanoutResult

import os

TRACE = bool(os.environ.get("ESCAPE_TRACE"))
STRAIGHT = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))
OUTWARD = {"E": (2, 2), "W": (-2, 2), "S": (2, 2), "N": (2, -2)}  # a ball's own outward gap, in quarter steps


@dataclass
class Costs:
    via: float = 3.0  # pitches of track a via is worth
    other_side: float = 4.0  # penalty for leaving on a side other than the exit side
    diagonal: float = 0.05  # small preference for straight runs
    tie: float = 0.02  # per step toward the higher grid index: a consistent side for channel choices
    foreign_site: float = 1.0  # extra cost of a via that is not at the ball's own outward gap
    top_depth: float = 0.75  # top-layer steps inside the array cost (1 + top_depth * (ring - top_rings)) times more
    iterations: int = 60  # negotiation rounds
    present: float = 0.6  # sharing penalty per other user, times the iteration number
    history: float = 0.4  # added to a contested node's history each round it stays contested
    max_vias: int = 2
    stall_rounds: int = 4  # rounds without fewer conflicts before the contested balls' neighbours are ripped up too
    max_radius: int = 4  # in balls, the widest rip-up around a contested ball
    repair_tries: int = 3  # orders tried per radius when a stranded ball's neighbours are ripped up in the final pass
    seed: int = 1


class LatticeGraph:
    """Static part: geometry, existing copper (hard), the neighbourhoods that decide what is too close, caches."""

    def __init__(self, board, lat: Lattice, rules: FanoutRules, layers: list[int], margin_pitches: float,
                 obstacles: Obstacles):
        self.board, self.lat, self.rules, self.layers, self.obs = board, lat, rules, layers, obstacles
        self.q = lat.pitch / 4  # mm per quarter step
        m = int(math.ceil(margin_pitches * 4))
        self.qx0, self.qx1 = -m, 4 * (lat.cols - 1) + m
        self.qy0, self.qy1 = -m, 4 * (lat.rows - 1) + m
        self.ax0, self.ax1 = -2, 4 * (lat.cols - 1) + 2  # the array: the pads and half a pitch around them
        self.ay0, self.ay1 = -2, 4 * (lat.rows - 1) + 2
        self.pad_net = {(4 * b.i, 4 * b.j): b.net for b in lat.balls.values()}
        self.top = pcbnew.F_Cu
        tw, clr, vr = rules.track_mm, rules.clearance_mm, rules.via_mm / 2
        # occupancy lives on a grid twice as fine (an eighth of the pitch) so that a step is sampled along its
        # length, diagonals included; the offsets below are in that unit
        self.u = self.q / 2
        self.t_near = self._offsets(tw + clr)  # another track's centreline may not be this close to a track sample
        self.v_for_t = self._offsets(vr + clr + tw / 2)  # a via centre this close to a track sample collides
        self.v_for_v = self._offsets(2 * vr + clr)  # via centres this close collide
        self.edge_cache: dict = {}  # (layer, a, b) -> hits against the fixed copper, shared between nets
        self.via_cache: dict = {}  # node -> hits against the fixed copper
        self.committed = Obstacles(board, items=[])  # the copper this run has committed, checked live

    def _offsets(self, dist_mm: float) -> tuple:
        r = int(dist_mm / self.u) + 1
        return tuple((dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                     if math.hypot(dx, dy) * self.u < dist_mm - 1e-9)

    @staticmethod
    def samples(a, b):
        """The eighth-pitch grid points along the step a -> b (quarter-pitch nodes), the start excluded."""
        ax, ay, bx, by = 2 * a[0], 2 * a[1], 2 * b[0], 2 * b[1]
        n = max(abs(bx - ax), abs(by - ay))
        sx, sy = (bx - ax) // n, (by - ay) // n
        return [(ax + k * sx, ay + k * sy) for k in range(1, n + 1)]

    # --- geometry ------------------------------------------------------------------------------------------------
    def mm(self, q) -> tuple[float, float]:
        return (self.lat.X(q[0] / 4), self.lat.Y(q[1] / 4))

    def in_graph(self, q) -> bool:
        return self.qx0 <= q[0] <= self.qx1 and self.qy0 <= q[1] <= self.qy1

    def in_array(self, q) -> bool:
        return self.ax0 <= q[0] <= self.ax1 and self.ay0 <= q[1] <= self.ay1

    def on_boundary(self, q) -> bool:
        return q[0] in (self.qx0, self.qx1) or q[1] in (self.qy0, self.qy1)

    def boundary_side(self, q) -> str:
        dist = {"W": q[0] - self.qx0, "E": self.qx1 - q[0], "N": q[1] - self.qy0, "S": self.qy1 - q[1]}
        return min(dist, key=dist.get)

    def side_distance(self, q, side: str) -> float:
        """Pitches from ``q`` to the graph boundary on ``side``."""
        d = {"W": q[0] - self.qx0, "E": self.qx1 - q[0], "N": q[1] - self.qy0, "S": self.qy1 - q[1]}[side]
        return d / 4

    def top_ok(self, q, start) -> bool:
        """Where a top-layer track may run: any node outside the array; inside only the half-pitch nodes that are
        not another ball's pad."""
        if not self.in_array(q):
            return True
        if q[0] % 2 or q[1] % 2:
            return False
        return q == start or q not in self.pad_net

    def via_ok(self, q, start) -> bool:
        """Where a via may go: a half-pitch node that is not another ball's pad (a gap, a channel, an empty ball
        position: the collision test decides whether it fits), any node outside the array, the pad itself when the
        style allows."""
        if q == start:
            return self.rules.style == "in-pad"
        if not self.in_array(q):
            return True
        if q[0] % 2 or q[1] % 2:
            return False
        return q not in self.pad_net

    def _track(self, layer, a, b, net):
        t = pcbnew.PCB_TRACK(self.board)
        ax, ay = self.mm(a)
        bx, by = self.mm(b)
        t.SetStart(pcbnew.VECTOR2I(kb.nm(ax), kb.nm(ay)))
        t.SetEnd(pcbnew.VECTOR2I(kb.nm(bx), kb.nm(by)))
        t.SetWidth(kb.nm(self.rules.track_mm))
        t.SetLayer(layer)
        t.SetNet(net)
        return t

    def _via(self, node, net):
        v = pcbnew.PCB_VIA(self.board)
        x, y = self.mm(node)
        v.SetPosition(pcbnew.VECTOR2I(kb.nm(x), kb.nm(y)))
        v.SetDrill(kb.nm(self.rules.via_drill_mm))
        kb.set_via_diameter(v, self.rules.via_mm)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(net)
        return v

    def _edge_hits(self, layer, a, b, net) -> frozenset:
        key = (layer, a, b) if a <= b else (layer, b, a)
        hits = self.edge_cache.get(key)
        if hits is None:
            hits = self.obs.hits(self._track(layer, a, b, net), self.rules.clearance_mm,
                                 hole_clearance_mm=self.rules.hole_clearance_mm)
            self.edge_cache[key] = hits
        return hits

    def segment_clear(self, layer, a, b, net, committed: bool = True) -> bool:
        """Clear of the fixed copper (cached) and, with ``committed``, of the copper this run has committed."""
        name = net.GetNetname()
        if not all(n == name for _, n in self._edge_hits(layer, a, b, net)):
            return False
        if committed and self.committed.count:
            return self.committed.clear(self._track(layer, a, b, net), self.rules.clearance_mm,
                                        hole_clearance_mm=self.rules.hole_clearance_mm) is None
        return True

    def segment_blocker(self, layer, a, b, net) -> str:
        name = net.GetNetname()
        hits = [f"{cls} of {n!r}" for cls, n in sorted(self._edge_hits(layer, a, b, net)) if n != name]
        if not hits and self.committed.count:
            other = self.committed.clear(self._track(layer, a, b, net), self.rules.clearance_mm,
                                         hole_clearance_mm=self.rules.hole_clearance_mm)
            if other is not None:
                hits = [f"our {other.GetClass()} of {other.GetNetname()!r}"]
        return f"{self.board.GetLayerName(layer)}: {hits[0]}" if hits else "?"

    def via_clear(self, node, net, committed: bool = True) -> bool:
        hits = self.via_cache.get(node)
        if hits is None:
            hits = self.obs.hits(self._via(node, net), self.rules.clearance_mm,
                                 hole_clearance_mm=self.rules.hole_clearance_mm)
            self.via_cache[node] = hits
        name = net.GetNetname()
        if not all(n == name for _, n in hits):
            return False
        if committed and self.committed.count:
            return self.committed.clear(self._via(node, net), self.rules.clearance_mm,
                                        hole_clearance_mm=self.rules.hole_clearance_mm) is None
        return True

    def path_clear(self, layer_nodes, vias, net) -> bool:
        """A whole path against the fixed and the committed copper."""
        prev = None
        for layer, q in layer_nodes:
            if prev is not None and prev[0] == layer and not self.segment_clear(layer, prev[1], q, net):
                return False
            prev = (layer, q)
        return all(self.via_clear(q, net) for q in vias)


# --- occupancy: what an escape occupies, for negotiation (soft) and for the final pass (hard) ---------------------------
class _Occupancy:
    """Which paths have a track sample or a via centre at each point of the eighth-pitch grid, and the
    neighbourhood queries that say which other paths a new step or via would be too close to. Conflicts are
    counted per path, not per sample, so that a long overlap costs what a short one does: one other ball."""

    def __init__(self, g: LatticeGraph):
        self.g = g
        self.tracks: dict = defaultdict(set)  # (layer, x, y) on the eighth grid -> paths with a track sample there
        self.vias: dict = defaultdict(set)  # (x, y) on the eighth grid -> paths with a via centre there

    @staticmethod
    def track_samples(layer_nodes) -> set:
        out = set()
        prev = None
        for layer, q in layer_nodes:
            if prev is None or prev[0] != layer:
                out.add((layer, 2 * q[0], 2 * q[1]))
            else:
                for x, y in LatticeGraph.samples(prev[1], q):
                    out.add((layer, x, y))
            prev = (layer, q)
        return out

    def add(self, layer_nodes, vias, number: str, sign: int = 1) -> None:
        for key in self.track_samples(layer_nodes):
            if sign > 0:
                self.tracks[key].add(number)
            else:
                self.tracks[key].discard(number)
        for (x, y) in set(vias):
            if sign > 0:
                self.vias[(2 * x, 2 * y)].add(number)
            else:
                self.vias[(2 * x, 2 * y)].discard(number)

    def near_sample(self, layer, x, y) -> set:
        """Paths a track sample at (layer, x, y) would be too close to."""
        g = self.g
        out: set = set()
        t = self.tracks
        for dx, dy in g.t_near:
            s = t.get((layer, x + dx, y + dy))
            if s:
                out |= s
        v = self.vias
        for dx, dy in g.v_for_t:
            s = v.get((x + dx, y + dy))
            if s:
                out |= s
        return out

    def near_step(self, layer, a, b) -> set:
        """Paths the step a -> b (quarter nodes) would be too close to, over its samples."""
        out: set = set()
        for x, y in LatticeGraph.samples(a, b):
            out |= self.near_sample(layer, x, y)
        return out

    def near_via(self, q) -> set:
        """Paths a via centred at the quarter node q would be too close to."""
        g, x, y = self.g, 2 * q[0], 2 * q[1]
        out: set = set()
        v = self.vias
        for dx, dy in g.v_for_v:
            s = v.get((x + dx, y + dy))
            if s:
                out |= s
        t = self.tracks
        for layer in g.layers:
            for dx, dy in g.v_for_t:
                s = t.get((layer, x + dx, y + dy))
                if s:
                    out |= s
        return out

    def conflicts(self, layer_nodes, vias, number: str) -> list:
        """The samples and vias of the placed path ``number`` that are too close to another path."""
        out = [("t", layer, x, y) for layer, x, y in self.track_samples(layer_nodes)
               if self.near_sample(layer, x, y) - {number}]
        out += [("v", q) for q in set(vias) if self.near_via(q) - {number}]
        return out


class _Context:
    """Costs and blocks on nodes for one search: negotiation (soft) or the final pass (hard)."""

    def __init__(self, occ: _Occupancy, history: dict, present: float, hard: bool):
        self.occ, self.history, self.present, self.hard = occ, history, present, hard
        self.blocked = 0  # hard mode: steps turned away by occupancy, for diagnostics

    def step_cost(self, layer, a, b) -> float | None:
        n = len(self.occ.near_step(layer, a, b))
        if self.hard and n:
            self.blocked += 1
            return None
        h = self.history
        return max(h.get(("t", layer, x, y), 0.0) for x, y in LatticeGraph.samples(a, b)) + self.present * n

    def via_cost(self, q) -> float | None:
        n = len(self.occ.near_via(q))
        if self.hard and n:
            self.blocked += 1
            return None
        return self.history.get(("v", q), 0.0) + self.present * n


def _search(g: LatticeGraph, ball: Ball, net, exit_side, costs: Costs, power: bool, ctx: _Context):
    """A* from the ball's pad to the graph boundary (signals) or to a via (power); returns (layer_nodes, vias) or
    (None, blockers)."""
    start_q = (4 * ball.i, 4 * ball.j)
    out = OUTWARD.get(exit_side or "", (2, 2))
    own_site = (start_q[0] + out[0], start_q[1] + out[1])
    depth = 1 + costs.top_depth * max(0, ball.ring - g.rules.top_rings)
    sides = ("N", "S", "W", "E")

    def h(q) -> float:
        if power:
            return 0.0
        best = math.inf
        for s in sides:
            d = g.side_distance(q, s) + (0.0 if (not exit_side or s == exit_side) else costs.other_side)
            if d < best:
                best = d
        return best

    start = (g.top, start_q, 0)
    dist = {start: 0.0}
    prev = {start: None}
    heap = [(h(start_q), 0, start)]
    counter = 1
    blockers: Counter = Counter()
    goal = None
    while heap:
        f, _, cur = heapq.heappop(heap)
        d = dist[cur]
        if f > d + h(cur[1]) + 1e-9:
            continue
        layer, q, nvias = cur
        if power and nvias >= 1:
            goal = cur
            break
        if not power and g.on_boundary(q):
            goal = cur
            break
        on_top = layer == g.top
        step = 2 if (on_top and g.in_array(q)) else 1
        for dx, dy in STRAIGHT + DIAGONAL:
            nxt = (q[0] + dx * step, q[1] + dy * step)
            if not g.in_graph(nxt):
                continue
            if on_top and not g.top_ok(nxt, start_q):
                continue
            extra = ctx.step_cost(layer, q, nxt)
            if extra is None:
                continue
            if not g.segment_clear(layer, q, nxt, net):
                blockers[g.segment_blocker(layer, q, nxt, net)] += 1
                continue
            diagonal = dx != 0 and dy != 0
            length = 0.25 * step * (math.sqrt(2) if diagonal else 1.0)
            cost = length + (costs.diagonal if diagonal else 0.0) + (costs.tie if (dx > 0 or dy > 0) else 0.0)
            if on_top and g.in_array(nxt):
                cost *= depth
            if not power and g.on_boundary(nxt) and exit_side and g.boundary_side(nxt) != exit_side:
                cost += costs.other_side
            nd = d + cost + extra
            state = (layer, nxt, nvias)
            if nd < dist.get(state, math.inf):
                dist[state] = nd
                prev[state] = cur
                counter += 1
                heapq.heappush(heap, (nd + h(nxt), counter, state))
        if nvias < costs.max_vias and g.via_ok(q, start_q) and g.via_clear(q, net):
            extra = ctx.via_cost(q)
            if extra is None:
                continue
            via_cost = costs.via + (0.0 if q in (own_site, start_q) else costs.foreign_site) + extra
            for other in g.layers:
                if other == layer:
                    continue
                state = (other, q, nvias + 1)
                nd = d + via_cost
                if nd < dist.get(state, math.inf):
                    dist[state] = nd
                    prev[state] = cur
                    counter += 1
                    heapq.heappush(heap, (nd + h(q), counter, state))
    if goal is None:
        return None, blockers
    path = []
    cur = goal
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    layer_nodes = [(layer, q) for layer, q, _ in path]
    vias = [path[i][1] for i in range(1, len(path)) if path[i][0] != path[i - 1][0]]
    return layer_nodes, vias


def _commit(g: LatticeGraph, net, layer_nodes, vias) -> list:
    """Write the path as merged straight tracks and vias into the board and the obstacle index."""
    added = []
    runs: list[tuple[int, list]] = []
    for layer, node in layer_nodes:
        if runs and runs[-1][0] == layer:
            runs[-1][1].append(node)
        else:
            runs.append((layer, [node]))
    for layer, nodes in runs:
        pts = [nodes[0]]
        for k in range(1, len(nodes)):
            if len(pts) >= 2:
                (ax, ay), (bx, by) = pts[-2], pts[-1]
                cx, cy = nodes[k]
                d1, d2 = (bx - ax, by - ay), (cx - bx, cy - by)
                if d1[0] * d2[1] == d1[1] * d2[0] and d1[0] * d2[0] + d1[1] * d2[1] > 0:  # same direction
                    pts[-1] = nodes[k]
                    continue
            pts.append(nodes[k])
        for a, b in zip(pts, pts[1:]):
            t = g._track(layer, a, b, net)
            g.board.Add(t)
            g.committed.add(t)
            added.append(t)
    for node in vias:
        v = g._via(node, net)
        g.board.Add(v)
        g.committed.add(v)
        added.append(v)
    return added


def escape_package(board: pcbnew.BOARD, package_ref: str, nets: set[str], rules: FanoutRules,
                   exit_side: str | None = None, power_nets: set[str] = frozenset(),
                   costs: Costs | None = None, exit_sides: dict[str, str] | None = None) -> FanoutResult:
    """``exit_side`` is the package side the escapes leave toward; ``exit_sides`` overrides it per net name (the
    bus router prefers each net to leave toward its partner on the other package)."""
    costs = costs or Costs()
    exit_sides = exit_sides or {}
    fp = kb.footprint(board, package_ref)
    if fp is None:
        raise KeyError(package_ref)
    lat = Lattice(fp)
    layer_ids = {name: lid for lid, name in kb.copper_layers(board)}
    layers = [pcbnew.F_Cu] + [layer_ids[n] for n in rules.inner_layers if n in layer_ids]
    obs = Obstacles(board, lat.array_bbox_mm(rules.out_pitches + 2))
    g = LatticeGraph(board, lat, rules, layers, rules.out_pitches, obs)
    balls = [b for b in lat.balls.values() if b.net in power_nets or b.net in nets]
    balls.sort(key=lambda b: (0 if b.net in power_nets else 1, min(lat.distances(b).values()), b.i, b.j))
    nets_of = {b.number: lat.pads[b.number].GetNet() for b in balls}

    # --- negotiation: soft sharing, rising penalties ---------------------------------------------------------
    occ = _Occupancy(g)
    history: dict = defaultdict(float)
    paths: dict = {}  # ball number -> (layer_nodes, vias)
    contested: dict = {}  # ball number -> conflict keys after the last round
    last_blockers: dict = {}
    iterations_run = 0
    rng = random.Random(costs.seed)
    by_number = {b.number: b for b in balls}
    best_contested, since_better = len(balls) + 1, 0
    forced: set = set()
    for it in range(costs.iterations):
        iterations_run = it + 1
        ctx = _Context(occ, history, costs.present * it, hard=False)
        # rip up and re-route only the balls in conflict (or without a path); the rest keep their paths. When the
        # conflicts stop shrinking, the settled neighbours of the contested balls are ripped up too, in a growing
        # radius: a pair stuck on one gap needs a third ball, which nothing contests, to give way (docs/decisions D20)
        todo = [b for b in balls if b.number not in paths or contested.get(b.number)]
        extra = [b for b in balls if b.number in forced and b not in todo]
        if it > 0:
            rng.shuffle(todo)
            rng.shuffle(extra)
        todo += extra  # the contested balls choose first; the neighbours ripped up for them adapt
        for ball in todo:
            if ball.number in paths:
                occ.add(*paths.pop(ball.number), ball.number, -1)
            first, second = _search(g, ball, nets_of[ball.number], exit_sides.get(ball.net, exit_side), costs,
                                    ball.net in power_nets, ctx)
            if first is None:
                last_blockers[ball.number] = second
                continue
            paths[ball.number] = (first, second)
            occ.add(first, second, ball.number, 1)
        contested = {n: c for n, (ln, vs) in paths.items() if (c := occ.conflicts(ln, vs, n))}
        if TRACE:
            print(f"      it {it}: {len(paths)}/{len(balls)} routed, {len(contested)} contested: "
                  f"{sorted(contested)[:12]}", flush=True)
        if not contested:
            break
        for keys in contested.values():
            for k in keys:
                history[k] += costs.history
        if len(contested) < best_contested:
            best_contested, since_better, forced = len(contested), 0, set()
        else:
            since_better += 1
            if since_better >= costs.stall_rounds:
                # the partners the contested balls are too close to, then the partners' partners, and so on;
                # past max_radius hops every ball within that many pitches of a contested one
                hops = 1 + (since_better - costs.stall_rounds) // costs.stall_rounds
                forced = set(contested)
                for _ in range(min(hops, costs.max_radius)):
                    grown = set(forced)
                    for n in forced:
                        ln, vs = paths[n]
                        for layer, x, y in _Occupancy.track_samples(ln):
                            grown |= occ.near_sample(layer, x, y)
                        for q in vs:
                            grown |= occ.near_via(q)
                    forced = grown
                if hops > costs.max_radius:
                    forced |= {o.number for o in balls for n in contested
                               if abs(o.i - by_number[n].i) <= costs.max_radius
                               and abs(o.j - by_number[n].j) <= costs.max_radius}
                forced -= set(contested)
                if TRACE:
                    print(f"      stalled {since_better} rounds: ripping up {len(forced)} partners at {hops} hops", flush=True)

    # --- final pass: exact collision against the committed copper decides; the negotiated history steers ---------
    # The occupancy model is an approximation for the negotiation; here the committed index answers exactly, so
    # nothing is blocked by the model and a path the geometry allows is never refused.
    result = FanoutResult(package_ref)
    result.counts["iterations"] = iterations_run
    occ = _Occupancy(g)
    ctx = _Context(occ, history, 0.0, hard=False)
    order = sorted(balls, key=lambda b: (b.number not in paths, 0 if b.net in power_nets else 1,
                                         len(paths[b.number][0]) if b.number in paths else 0, b.i, b.j))
    committed: dict = {}  # ball number -> (layer_nodes, vias, items)

    def place(ball: Ball):
        net = nets_of[ball.number]
        first, second = _search(g, ball, net, exit_sides.get(ball.net, exit_side), costs, ball.net in power_nets, ctx)
        if first is None:
            return second
        place_path(ball, first, second)
        return None

    def place_path(ball: Ball, first, second):
        occ.add(first, second, ball.number, 1)
        committed[ball.number] = (first, second, _commit(g, nets_of[ball.number], first, second))

    def unplace(number: str):
        first, second, items = committed.pop(number)
        occ.add(first, second, number, -1)
        for item in items:
            g.committed.remove(item)
            board.Delete(item)

    # negotiated paths that contest nothing are kept as they are, once the exact collision test against the copper
    # committed so far agrees; only the balls in conflict are re-routed
    clean = []
    for ball in balls:
        if ball.number in paths and not contested.get(ball.number):
            first, second = paths[ball.number]
            if g.path_clear(first, second, nets_of[ball.number]):
                place_path(ball, first, second)
                clean.append(ball)
    blockers: dict = {}
    for ball in order:
        if ball.number in committed:
            continue
        why = place(ball)
        if why is not None:
            blockers[ball.number] = why

    # --- repair: for each stranded ball, rip up the escapes of its neighbours, route it first and re-place them, in
    # a growing radius and a few orders, keeping the first configuration that places every ball ------------------
    def repair(number: str) -> bool:
        f = by_number[number]
        for radius in range(1, costs.max_radius + 1):
            near = [n for n in committed if abs(by_number[n].i - f.i) <= radius and abs(by_number[n].j - f.j) <= radius
                    and by_number[n].net not in power_nets]
            for attempt in range(costs.repair_tries):
                saved = {n: committed[n][:2] for n in near}
                for n in near:
                    unplace(n)
                order_ = list(near)
                if attempt:
                    rng.shuffle(order_)
                ok = place(f) is None and all(place(by_number[n]) is None for n in order_)
                if ok:
                    return True
                for n in [x for x in near if x in committed]:
                    unplace(n)
                if number in committed:
                    unplace(number)
                for n, (first, second) in saved.items():
                    place_path(by_number[n], first, second)
        return False

    for number in list(blockers):
        if repair(number):
            blockers.pop(number, None)
    result.counts["negotiated kept"] = len(clean)

    for ball in balls:
        power = ball.net in power_nets
        if ball.number in committed:
            first, second, _ = committed[ball.number]
            end_layer = board.GetLayerName(first[-1][0])
            side = g.boundary_side(first[-1][1]) if not power else "-"
            how = "power via" if power else f"ring{ball.ring} {len(second)} via {end_layer} {side}"
            result.escaped[ball.number] = how
            result.counts[how] += 1
        else:
            why = blockers.get(ball.number, Counter())
            top = ", ".join(f"{k} x{v}" for k, v in why.most_common(3)) or "no free lattice path"
            result.failed[ball.number] = f"ring {ball.ring}: {top}"
            result.counts[f"FAILED ring{ball.ring}"] += 1
    return result
