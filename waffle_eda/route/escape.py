"""Escape routing on the package lattice with negotiated congestion.

The package region is a half-pitch lattice on every routable layer. A ball's escape is a path from its pad on the
top layer to the region boundary (signals) or to a via (power and ground), through steps between neighbouring
lattice points, straight or diagonal, with a via at a diagonal gap between four balls (or in the pad, when the
style allows). Every step and via is checked against the board's existing copper with KiCad's own collision test;
that is a hard constraint. Conflicts between the balls' own escapes are resolved by negotiation (PathFinder):
every ball routes with a cost on lattice resources other balls use, the cost of an over-used resource rises each
iteration, and the iterations stop when nothing is shared. A final pass commits the paths with hard occupancy.
A ball with no path is reported with the copper that blocked it, never left to a router.
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

STRAIGHT = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))


@dataclass
class Costs:
    via: float = 3.0  # pitches of track a via is worth
    other_side: float = 4.0  # penalty for leaving on a side other than the exit side
    diagonal: float = 0.05  # small preference for straight runs
    tie: float = 0.02  # per half-step toward the higher lattice index: a consistent side for channel choices
    foreign_site: float = 1.0  # extra cost of a via at a diagonal gap that is not the ball's own outward gap
    top_depth: float = 0.75  # top-layer steps inside the array cost (1 + top_depth * (ring - top_rings)) times more
    iterations: int = 60  # negotiation rounds
    present: float = 0.6  # sharing penalty per other user, times the iteration number
    history: float = 0.4  # added to an over-used resource's history each round it stays over-used
    max_vias: int = 2
    final_order: str = "shortest"  # final hard pass: "deepest" balls first (fewest alternatives) or "shortest" path
    assign_sites: bool = False  # fix one diagonal gap per ball by matching before routing (else a cost preference)
    seed: int = 1


class LatticeGraph:
    """Static part: geometry, existing copper (hard), caches."""

    def __init__(self, board, lat: Lattice, rules: FanoutRules, layers: list[int], margin_pitches: float,
                 obstacles: Obstacles):
        self.board, self.lat, self.rules, self.layers, self.obs = board, lat, rules, layers, obstacles
        m = int(math.ceil(margin_pitches * 2))
        self.hx0, self.hx1 = -m, 2 * (lat.cols - 1) + m
        self.hy0, self.hy1 = -m, 2 * (lat.rows - 1) + m
        self.pad_net = {(2 * b.i, 2 * b.j): b.net for b in lat.balls.values()}
        self.top = pcbnew.F_Cu
        self.edge_cache: dict = {}
        self.via_cache: dict = {}
        half = lat.pitch / 2
        # at small pitches a via at one node does not clear a track at the next node, and parallel diagonals in
        # adjacent cells (half / sqrt 2 apart) do not clear each other: then they occupy those neighbours too
        self.via_blocks_neighbours = half - rules.via_mm / 2 - rules.track_mm / 2 < rules.clearance_mm
        self.diag_blocks_parallel = half / math.sqrt(2) - rules.track_mm < rules.clearance_mm
        self.existing_vias: set = set()
        for item in obstacles.vias():
            p = item.GetPosition()
            fx, fy = (kb.mm(p.x) - lat.x0) / lat.pitch * 2, (kb.mm(p.y) - lat.y0) / lat.pitch * 2
            node = (round(fx), round(fy))
            if abs(fx - node[0]) < 0.1 and abs(fy - node[1]) < 0.1 and self.in_graph(*node):
                self.existing_vias.add(node)

    def mm(self, hx: int, hy: int) -> tuple[float, float]:
        return (self.lat.X(hx / 2), self.lat.Y(hy / 2))

    def in_graph(self, hx: int, hy: int) -> bool:
        return self.hx0 <= hx <= self.hx1 and self.hy0 <= hy <= self.hy1

    def outside_array(self, hx: int, hy: int) -> bool:
        return hx < -1 or hy < -1 or hx > 2 * (self.lat.cols - 1) + 1 or hy > 2 * (self.lat.rows - 1) + 1

    def on_boundary(self, hx: int, hy: int) -> bool:
        return hx in (self.hx0, self.hx1) or hy in (self.hy0, self.hy1)

    def boundary_side(self, hx: int, hy: int) -> str:
        dist = {"W": hx - self.hx0, "E": self.hx1 - hx, "N": hy - self.hy0, "S": self.hy1 - hy}
        return min(dist, key=dist.get)

    def _track(self, layer, a, b, net):
        t = pcbnew.PCB_TRACK(self.board)
        ax, ay = self.mm(*a)
        bx, by = self.mm(*b)
        t.SetStart(pcbnew.VECTOR2I(kb.nm(ax), kb.nm(ay)))
        t.SetEnd(pcbnew.VECTOR2I(kb.nm(bx), kb.nm(by)))
        t.SetWidth(kb.nm(self.rules.track_mm))
        t.SetLayer(layer)
        t.SetNet(net)
        return t

    def _via(self, node, net):
        v = pcbnew.PCB_VIA(self.board)
        x, y = self.mm(*node)
        v.SetPosition(pcbnew.VECTOR2I(kb.nm(x), kb.nm(y)))
        v.SetDrill(kb.nm(self.rules.via_drill_mm))
        kb.set_via_diameter(v, self.rules.via_mm)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(net)
        return v

    def segment_clear(self, layer, a, b, net) -> bool:
        key = (net.GetNetname(), layer, a, b) if a <= b else (net.GetNetname(), layer, b, a)
        hit = self.edge_cache.get(key)
        if hit is None:
            hit = self.obs.clear(self._track(layer, a, b, net), self.rules.clearance_mm) is None
            self.edge_cache[key] = hit
        return hit

    def segment_blocker(self, layer, a, b, net) -> str:
        hit = self.obs.clear(self._track(layer, a, b, net), self.rules.clearance_mm)
        return f"{self.board.GetLayerName(layer)}: {hit.GetClass()} of {hit.GetNetname()!r}" if hit is not None else "?"

    def via_clear(self, node, net) -> bool:
        key = (net.GetNetname(), node)
        hit = self.via_cache.get(key)
        if hit is None:
            hit = self.obs.clear(self._via(node, net), self.rules.clearance_mm) is None
            self.via_cache[key] = hit
        return hit

    def via_site(self, node, own_pad) -> bool:
        hx, hy = node
        if hx % 2 and hy % 2:
            return True
        return self.rules.style == "in-pad" and node == own_pad


# --- resources: what an escape occupies, for negotiation and for the hard final pass ---------------------------------
def _cell_of(a, b):
    (ax, ay), (bx, by) = a, b
    return (min(ax, bx), min(ay, by))


def _via_resources(g: LatticeGraph, node):
    hx, hy = node
    res = [("v", node)] + [("n", L, node) for L in g.layers]
    # the four cells whose diagonals would pass 0.35 pitch from the via
    res += [("c", (hx - 1, hy)), ("c", (hx, hy - 1)), ("c", (hx, hy)), ("c", (hx - 1, hy - 1))]
    if g.via_blocks_neighbours:
        for dx, dy in STRAIGHT:
            res += [("n", L, (hx + dx, hy + dy)) for L in g.layers]
    return res


def _diag_resources(g: LatticeGraph, a, b, layer=None):
    cell = _cell_of(a, b)
    res = [("c", cell)]
    if g.diag_blocks_parallel:
        res += [("c", (cell[0] + 1, cell[1])), ("c", (cell[0] - 1, cell[1])),
                ("c", (cell[0], cell[1] + 1)), ("c", (cell[0], cell[1] - 1))]
        if layer is not None:  # the diagonal passes half / sqrt 2 from its two corner nodes: no track there either
            (ax, ay), (bx, by) = a, b
            res += [("n", layer, (ax, by)), ("n", layer, (bx, ay))]
    return res


def _path_resources(g: LatticeGraph, layer_nodes, vias) -> list:
    """The lattice resources a path occupies, each once."""
    res = []
    prev = None
    for layer, node in layer_nodes:
        res.append(("n", layer, node))
        if prev is not None and prev[0] == layer and prev[1][0] != node[0] and prev[1][1] != node[1]:
            res.extend(_diag_resources(g, prev[1], node, layer))
        prev = (layer, node)
    for node in vias:
        res.extend(_via_resources(g, node))
    return list(dict.fromkeys(res))


def _assign_sites(g: LatticeGraph, balls: list[Ball], nets_of: dict, exit_side: str | None,
                  power_nets: set[str]) -> dict[str, tuple[int, int]]:
    """One diagonal gap per ball, distinct, by maximum bipartite matching (Kuhn's augmenting paths), trying each
    ball's own outward gap first and the deepest balls first. Balls left without a gap may use any free one."""
    if g.rules.style == "in-pad":
        return {}
    out = {"E": (1, 1), "W": (-1, 1), "S": (1, 1), "N": (1, -1)}.get(exit_side or "", (1, 1))
    candidates: dict[str, list] = {}
    for b in balls:
        node = (2 * b.i, 2 * b.j)
        own = (node[0] + out[0], node[1] + out[1])
        sites = [own] + [(node[0] + dx, node[1] + dy) for dx, dy in DIAGONAL if (node[0] + dx, node[1] + dy) != own]
        candidates[b.number] = [site for site in sites if g.in_graph(*site) and site not in g.existing_vias
                                and g.via_clear(site, nets_of[b.number])]
    order = sorted(balls, key=lambda b: (0 if b.net in power_nets else 1, -min(g.lat.distances(b).values()), b.i, b.j))
    match: dict[tuple[int, int], str] = {}  # site -> ball

    def try_ball(number: str, seen: set) -> bool:
        for site in candidates[number]:
            if site in seen:
                continue
            seen.add(site)
            if site not in match or try_ball(match[site], seen):
                match[site] = number
                return True
        return False

    for b in order:
        try_ball(b.number, set())
    return {number: site for site, number in match.items()}


class _Context:
    """Costs and blocks on resources for one search: negotiation (soft) or the final pass (hard)."""

    def __init__(self, usage: Counter, history: dict, present: float, hard: bool):
        self.usage, self.history, self.present, self.hard = usage, history, present, hard
        self.blocked: Counter = Counter()  # hard mode: resources that turned a step away, for diagnostics

    def cost(self, res) -> float | None:
        """None when blocked (hard mode and used), else the extra cost."""
        u = self.usage.get(res, 0)
        if self.hard and u:
            self.blocked[res] += 1
            return None
        return self.history.get(res, 0.0) + self.present * u


def _search(g: LatticeGraph, ball: Ball, net, exit_side, costs: Costs, power: bool, ctx: _Context,
            assigned: tuple[int, int] | None = None):
    start_node = (2 * ball.i, 2 * ball.j)
    out = {"E": (1, 1), "W": (-1, 1), "S": (1, 1), "N": (1, -1)}.get(exit_side or "", (1, 1))
    own_site = assigned or (start_node[0] + out[0], start_node[1] + out[1])
    start = (g.top, start_node, 0)
    dist = {start: 0.0}
    prev = {start: None}
    heap = [(0.0, 0, start)]
    counter = 1
    blockers: Counter = Counter()
    goal = None
    while heap:
        d, _, cur = heapq.heappop(heap)
        if d > dist.get(cur, math.inf):
            continue
        layer, node, nvias = cur
        if power and nvias >= 1:
            goal = cur
            break
        if not power and g.on_boundary(*node):
            goal = cur
            break
        hx, hy = node
        for dx, dy in STRAIGHT + DIAGONAL:
            nxt = (hx + dx, hy + dy)
            if not g.in_graph(*nxt) or nxt in g.existing_vias:
                continue
            if layer == g.top and nxt in g.pad_net and nxt != start_node:
                continue
            diagonal = dx != 0 and dy != 0
            extra = ctx.cost(("n", layer, nxt))
            if extra is None:
                continue
            if diagonal:
                c_extra = 0.0
                for res in _diag_resources(g, node, nxt, layer):
                    c = ctx.cost(res)
                    if c is None:
                        c_extra = None
                        break
                    c_extra += c
                if c_extra is None:
                    continue
                extra += c_extra
                corners = ((hx + dx, hy), (hx, hy + dy))
                if any(c in g.existing_vias for c in corners):
                    continue
            if not g.segment_clear(layer, node, nxt, net):
                blockers[g.segment_blocker(layer, node, nxt, net)] += 1
                continue
            step = (0.5 * math.sqrt(2) + costs.diagonal) if diagonal else 0.5
            if dx > 0 or dy > 0:
                step += costs.tie
            if layer == g.top and not g.outside_array(*nxt):
                step *= 1 + costs.top_depth * max(0, ball.ring - g.rules.top_rings)
            if not power and g.on_boundary(*nxt) and exit_side and g.boundary_side(*nxt) != exit_side:
                step += costs.other_side
            nd = d + step + extra
            state = (layer, nxt, nvias)
            if nd < dist.get(state, math.inf):
                dist[state] = nd
                prev[state] = cur
                counter += 1
                heapq.heappush(heap, (nd, counter, state))
        site_ok = (node == assigned) if assigned else g.via_site(node, start_node)
        if g.rules.style == "in-pad" and node == start_node:
            site_ok = True
        if nvias < costs.max_vias and site_ok and node not in g.existing_vias and g.via_clear(node, net):
            extra = 0.0
            for res in _via_resources(g, node):
                c = ctx.cost(res)
                if c is None:
                    extra = None
                    break
                extra += c
            if extra is None:
                continue
            via_cost = costs.via + (0.0 if node in (own_site, start_node) else costs.foreign_site) + extra
            for other in g.layers:
                if other == layer:
                    continue
                state = (other, node, nvias + 1)
                nd = d + via_cost
                if nd < dist.get(state, math.inf):
                    dist[state] = nd
                    prev[state] = cur
                    counter += 1
                    heapq.heappush(heap, (nd, counter, state))
    if goal is None:
        return None, blockers
    path = []
    cur = goal
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    layer_nodes = [(layer, node) for layer, node, _ in path]
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
                if (bx - ax, by - ay) == (cx - bx, cy - by):
                    pts[-1] = nodes[k]
                    continue
            pts.append(nodes[k])
        for a, b in zip(pts, pts[1:]):
            t = g._track(layer, a, b, net)
            g.board.Add(t)
            g.obs.add(t)
            added.append(t)
    for node in vias:
        v = g._via(node, net)
        g.board.Add(v)
        g.obs.add(v)
        added.append(v)
    return added


def escape_package(board: pcbnew.BOARD, package_ref: str, nets: set[str], rules: FanoutRules,
                   exit_side: str | None = None, power_nets: set[str] = frozenset(),
                   costs: Costs | None = None) -> FanoutResult:
    costs = costs or Costs()
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
    assigned = _assign_sites(g, balls, nets_of, exit_side, power_nets) if costs.assign_sites else {}

    # --- negotiation: soft sharing, rising penalties ---------------------------------------------------------
    usage: Counter = Counter()
    history: dict = defaultdict(float)
    paths: dict = {}
    last_blockers: dict = {}
    iterations_run = 0
    rng = random.Random(costs.seed)
    for it in range(costs.iterations):
        iterations_run = it + 1
        ctx = _Context(usage, history, costs.present * it, hard=False)
        # rip up and re-route only the balls in conflict (or without a path); the rest keep their paths
        todo = [b for b in balls if b.number not in paths or any(usage[r] > 1 for r in paths[b.number][2])]
        if it > 0:
            rng.shuffle(todo)
        for ball in todo:
            if ball.number in paths:
                for res in paths[ball.number][2]:
                    usage[res] -= 1
                del paths[ball.number]
            first, second = _search(g, ball, nets_of[ball.number], exit_side, costs, ball.net in power_nets, ctx,
                                    assigned.get(ball.number))
            if first is None:
                last_blockers[ball.number] = second
                continue
            res = _path_resources(g, first, second)
            paths[ball.number] = (first, second, res)
            for r in res:
                usage[r] += 1
        over = [r for r, c in usage.items() if c > 1]
        if not over:
            break
        for r in over:
            history[r] += costs.history * (usage[r] - 1)

    # --- final pass: hard occupancy, in the negotiated order (balls with a path first, shortest first) --------
    result = FanoutResult(package_ref)
    result.counts["iterations"] = iterations_run
    result.counts["sites assigned"] = len(assigned)
    usage = Counter()
    ctx = _Context(usage, history, 0.0, hard=True)
    if costs.final_order == "deepest":
        order = sorted(balls, key=lambda b: (0 if b.net in power_nets else 1, -min(lat.distances(b).values()),
                                             b.number not in paths, b.i, b.j))
    else:
        order = sorted(balls, key=lambda b: (b.number not in paths, 0 if b.net in power_nets else 1,
                                             len(paths[b.number][0]) if b.number in paths else 0, b.i, b.j))
    committed: dict = {}  # ball number -> (layer_nodes, vias, resources, items)

    def place(ball: Ball):
        net = nets_of[ball.number]
        power = ball.net in power_nets
        first, second = _search(g, ball, net, exit_side, costs, power, ctx, assigned.get(ball.number))
        if first is None:
            return second
        res = _path_resources(g, first, second)
        for r in res:
            usage[r] += 1
        items = _commit(g, net, first, second)
        committed[ball.number] = (first, second, res, items)
        return None

    def unplace(number: str):
        first, second, res, items = committed.pop(number)
        for r in res:
            usage[r] -= 1
        for item in items:
            g.obs.remove(item)
            board.Delete(item)

    blockers: dict = {}
    for ball in order:
        why = place(ball)
        if why is not None:
            blockers[ball.number] = why

    # --- repair: for each stranded ball, rip up the escapes of its neighbours and route it first ------------------
    by_number = {b.number: b for b in balls}
    for number in list(blockers):
        f = by_number[number]
        near = [n for n in committed if abs(by_number[n].i - f.i) <= 2 and abs(by_number[n].j - f.j) <= 2
                and by_number[n].net not in power_nets]
        saved = {n: committed[n] for n in near}
        for n in near:
            unplace(n)
        trial_failed = []
        why = place(f)
        if why is not None:
            trial_failed.append(number)
        for n in near:
            if place(by_number[n]) is not None:
                trial_failed.append(n)
        if len(trial_failed) < 1 + 0:  # the stranded ball and every neighbour placed: keep
            blockers.pop(number, None)
            continue
        if len(trial_failed) < 1:
            blockers.pop(number, None)
        # not an improvement: restore the previous state
        for n in [x for x in near if x in committed]:
            unplace(n)
        if number in committed:
            unplace(number)
        for n, (first, second, res, items) in saved.items():
            for r in res:
                usage[r] += 1
            committed[n] = (first, second, res, _commit(g, nets_of[n], first, second))

    for ball in balls:
        power = ball.net in power_nets
        if ball.number in committed:
            first, second, _, _ = committed[ball.number]
            end_layer = board.GetLayerName(first[-1][0])
            side = g.boundary_side(*first[-1][1]) if not power else "-"
            how = "power via" if power else f"ring{ball.ring} {len(second)} via {end_layer} {side}"
            result.escaped[ball.number] = how
            result.counts[how] += 1
        else:
            why = blockers.get(ball.number, Counter())
            top = ", ".join(f"{k} x{v}" for k, v in why.most_common(3)) or "no free lattice path"
            result.failed[ball.number] = f"ring {ball.ring}: {top}"
            result.counts[f"FAILED ring{ball.ring}"] += 1
    return result
