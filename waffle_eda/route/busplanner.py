"""The planner of M3a (decisions D37, D38): it decides a bus plan, and `busplan.check` says whether the plan can
be built. Nothing here searches for copper; that is M3b's work inside the plan this produces.

**The mesh.** One graph per copper layer, laid on a grid whose lines are not evenly spaced: every package
contributes its own half-pitch lines, so a ball centre, a corner between four balls and a channel between two of
them are all nodes of the mesh, and the rest of the region is filled in at `step_mm`. Deformed like this the grid
is still a grid -- x is increasing along i and y along j -- which is the point of it:

    two orthogonal paths through disjoint sets of nodes of a monotone grid cannot cross.

So the planner does not check for crossings and then repair them. It routes every net on node-disjoint paths and
crossing-freeness follows, on every layer at once, whatever the geometry. That is what makes the plan cheap enough
to gate in seconds: the expensive property is true by construction.

**Vias.** A layer change happens at a *column*: one net at a time, on every layer, as a through via is. A column
inside a package's ball array is only offered where that package's measured escape style puts its vias (D32), so
on a board that dog-bones a net leaves its ball on the top layer and turns down at a corner, and on a board that
uses via-in-pad it turns down in the ball itself -- neither is assumed, both are read off the reference.

**Layers.** A copper layer is a routing layer of this board if the board routes on it: the count of distinct
non-bus nets it carries separates the signal layers from the planes on every class C reference (orangecrab 95/55/39
against 10/1/1, logicbone 260/113/57/42 against 19/1/0/0, butterstick 232/127/57/52 against 13/8/0/0), and the
layers it picks are the ones each reference's own bus uses. Zone coverage does not separate them -- LogicBone pours
ground on its signal layers too.

**Contention.** Negotiated congestion (PathFinder): every net is routed against the others' current claims, a node
that two nets want gets dearer in every later round, and the rounds stop when no node is claimed twice. Until then
a plan is not node-disjoint and may cross; after it, it cannot.
"""
from __future__ import annotations

import heapq
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pcbnew

from waffle_eda.bench import bus_design
from waffle_eda.kicad import board as kb
from waffle_eda.route.busplan import BusPlan, Leg, Site, _site_of, styles_of, terminals


@dataclass
class PlanCosts:
    step_mm: float = 0.4  # the filler grid between the packages' own lines
    margin_mm: float = 0.10  # copper to the centre of a run: the plan's clearance, not M3b's DRC
    via_mm: float = 3.0  # what a layer change costs, in millimetres of run
    plane_mm: float = 0.0  # extra cost per mm on a layer a power or ground pour covers
    room_mm: float = 2.0  # what crossing the meander room another net holds costs
    present: float = 1.0  # the weight of this round's claims
    present_growth: float = 1.7  # how much dearer a contested node gets each round
    history: float = 1.0  # what a node that has ever been contested keeps costing
    rounds: int = 24
    min_nets_for_signal_layer: int = 20  # below this a layer is a plane, not a routing layer
    meander_depth: int = 3  # how far to either side of a run the plan will look for meander room
    budget_s: float = 900.0


# --- the board, as the planner sees it --------------------------------------------------------------------------
def signal_layers(board, ref, min_nets: int = 20) -> list:
    """The copper layers this board routes on, most used first: a layer carrying fewer than ``min_nets`` distinct
    nets other than the bus is a plane, and the bus does not cut it. Measured, never assumed from the layer's
    name -- `In2.Cu` says nothing and `Sig1.Cu` is only a hint."""
    bus = set(kb.nets_matching(board, ref.bus_net_pattern))
    nets: dict = defaultdict(set)
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA" or t.GetNetname() in bus:
            continue
        nets[t.GetLayer()].add(t.GetNetname())
    out = [(L, name, len(nets[L])) for L, name in kb.copper_layers(board)]
    keep = [(L, name, n) for (L, name, n) in out if n >= min_nets]
    if not keep:  # a board with nothing routed on it yet: every copper layer is a candidate
        keep = out
    return [(L, name, n) for (L, name, n) in sorted(keep, key=lambda r: -r[2])]


class Mesh:
    """The monotone grid: x lines, y lines, and for every node what blocks it on each layer."""

    def __init__(self, board, ref, layers: list, costs: PlanCosts, region=None):
        self.costs = costs
        self.layers = [L for (L, _name, _n) in layers]
        self.layer_name = {L: name for (L, name, _n) in layers}
        self.index_of_layer = {L: k for k, L in enumerate(self.layers)}
        self.packages = bus_design.packages_of(board, ref)
        self.bus = set(kb.nets_matching(board, ref.bus_net_pattern))
        self.region = region or self._region(board, ref)
        self.X, self.Y = self._lines()
        self.nx, self.ny = len(self.X), len(self.Y)
        self.nl = len(self.layers)
        self.n = self.nl * self.nx * self.ny
        self.blocked = bytearray(self.n)  # copper of another net on that layer
        self.owner: dict = {}  # node -> the one net that may use it (its own pad)
        self._lay_copper(board)

    # --- geometry ------------------------------------------------------------------------------------------
    def _region(self, board, ref):
        xs, ys = [], []
        for p in self.packages:
            x0, y0, x1, y1 = p.info.bbox_mm
            xs += [x0, x1]
            ys += [y0, y1]
        shapes, _names, _balls = terminals(board, ref)
        for pads in shapes.values():
            for (_label, x, y, hx, hy) in pads:
                xs += [x - hx, x + hx]
                ys += [y - hy, y + hy]
        m = 2.0
        bx0, by0, bx1, by1 = kb.outline_bbox_mm(board)
        return (max(min(xs) - m, bx0), max(min(ys) - m, by0), min(max(xs) + m, bx1), min(max(ys) + m, by1))

    def _lines(self):
        """The packages' own half-pitch lines, plus filler where they leave a gap. A line is kept only if it is
        clear of the ones already kept, so the mesh never has two lines a micrometre apart."""
        x0, y0, x1, y1 = self.region
        exact_x, exact_y = set(), set()
        for p in self.packages:
            lat = p.lattice
            if lat is None:
                continue
            for k in range(-2, 2 * lat.cols + 2):
                exact_x.add(round(lat.X(k / 2), 4))
            for k in range(-2, 2 * lat.rows + 2):
                exact_y.add(round(lat.Y(k / 2), 4))
        step = self.costs.step_mm

        def build(exact, lo, hi):
            lines = sorted(v for v in exact if lo - step <= v <= hi + step)
            filler = [lo + k * step for k in range(int((hi - lo) / step) + 2)]
            out = []
            for v in sorted(lines + filler, key=lambda v: (v, v not in exact)):
                if lo - 1e-9 <= v <= hi + 1e-9 and (not out or v - out[-1] >= step * 0.55 or v in exact and v - out[-1] > 1e-6):
                    if out and v - out[-1] < 1e-6:
                        continue
                    out.append(round(v, 4))
            return out

        return build(exact_x, x0, x1), build(exact_y, y0, y1)

    def near_x(self, x: float) -> int:
        return min(range(self.nx), key=lambda i: abs(self.X[i] - x))

    def near_y(self, y: float) -> int:
        return min(range(self.ny), key=lambda j: abs(self.Y[j] - y))

    def nid(self, li: int, i: int, j: int) -> int:
        return (li * self.nx + i) * self.ny + j

    def unpack(self, nid: int):
        j = nid % self.ny
        rest = nid // self.ny
        return rest // self.nx, rest % self.nx, j  # layer index, i, j

    def xy(self, nid: int):
        li, i, j = self.unpack(nid)
        return self.X[i], self.Y[j]

    # --- what the board already puts there -----------------------------------------------------------------
    def _mark(self, layer_ids, x0, y0, x1, y1, net):
        """Every node of these layers inside the box is taken, by ``net`` if it is a bus net's own pad (only that
        net may use it) or by nobody at all."""
        lo_i, hi_i = self._span(self.X, x0, x1)
        lo_j, hi_j = self._span(self.Y, y0, y1)
        if lo_i > hi_i or lo_j > hi_j:
            return
        for L in layer_ids:
            li = self.index_of_layer.get(L)
            if li is None:
                continue
            for i in range(lo_i, hi_i + 1):
                for j in range(lo_j, hi_j + 1):
                    nid = self.nid(li, i, j)
                    if net in self.bus:
                        if self.owner.get(nid, net) != net:
                            self.blocked[nid] = 1  # two bus nets' pads over one node: neither may have it
                        self.owner[nid] = net
                    else:
                        self.blocked[nid] = 1

    @staticmethod
    def _span(lines, lo, hi):
        import bisect
        return bisect.bisect_left(lines, lo), bisect.bisect_right(lines, hi) - 1

    def _lay_copper(self, board):
        """Pads and the copper of every net but the bus, which is the copper M3b will replace."""
        m = self.costs.margin_mm
        x0, y0, x1, y1 = self.region
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                p, size = pad.GetPosition(), pad.GetSize()
                x, y = kb.mm(p.x), kb.mm(p.y)
                if not (x0 - 2 <= x <= x1 + 2 and y0 - 2 <= y <= y1 + 2):
                    continue
                sx, sy = kb.mm(size.x), kb.mm(size.y)
                if pad.GetOrientation().AsDegrees() % 180 not in (0.0,):
                    sx = sy = math.hypot(sx, sy)
                hx, hy = sx / 2 + m, sy / 2 + m
                self._mark(list(pad.GetLayerSet().CuStack()), x - hx, y - hy, x + hx, y + hy, pad.GetNetname())
        for item in board.GetTracks():
            net = item.GetNetname()
            if net in self.bus:
                continue  # the bus's own copper is what the plan replaces
            if item.GetClass() == "PCB_VIA":
                p = item.GetPosition()
                x, y = kb.mm(p.x), kb.mm(p.y)
                r = kb.via_diameter_mm(item) / 2 + m
                self._mark(self.layers, x - r, y - r, x + r, y + r, net)
            else:
                L = item.GetLayer()
                if L not in self.index_of_layer:
                    continue
                a, b = item.GetStart(), item.GetEnd()
                ax, ay, bx, by = kb.mm(a.x), kb.mm(a.y), kb.mm(b.x), kb.mm(b.y)
                r = kb.mm(item.GetWidth()) / 2 + m
                steps = max(1, int(math.hypot(bx - ax, by - ay) / self.costs.step_mm))
                for k in range(steps + 1):
                    t = k / steps
                    cx, cy = ax + t * (bx - ax), ay + t * (by - ay)
                    self._mark([L], cx - r, cy - r, cx + r, cy + r, net)


# --- where a via may go -----------------------------------------------------------------------------------------
def via_columns(mesh: Mesh, styles: dict, shapes: dict) -> bytearray:
    """One byte per (i, j): may a net change layer here? Inside a package's ball array only where that package's
    measured style puts its vias, and inside a bus pad only when that pad is a ball whose package uses via-in-pad.

    The second rule matters because the mesh carries every package's lines, so a line of one package can cut
    through another's ball: a node inside a ball's copper is an in-pad via wherever it sits in that copper, and on
    a board that dog-bones it is not a site at all."""
    ok = bytearray(b"\x01" * (mesh.nx * mesh.ny))
    arrays = [p for p in mesh.packages if p.lattice is not None]
    for i, x in enumerate(mesh.X):
        for j, y in enumerate(mesh.Y):
            for pkg in arrays:
                cells = bus_design.ball_cells(pkg.lattice, x, y)
                if not cells:
                    continue
                offsets = {(di, dj) for (_, _, _, di, dj) in cells}
                if (0.0, 0.0) in offsets:
                    place = "on the ball"
                elif all(abs(di) == 0.5 and abs(dj) == 0.5 for di, dj in offsets):
                    place = "on a corner"
                else:
                    place = "in the channel"
                if place not in styles.get(pkg.reference, {}).get("places", {}):
                    ok[i * mesh.ny + j] = 0
                break
    centres = {}
    for pkg in arrays:
        if "on the ball" in styles.get(pkg.reference, {}).get("places", {}):
            for ball in pkg.lattice.balls.values():
                centres[(mesh.near_x(ball.x_mm), mesh.near_y(ball.y_mm))] = True
    for pads in shapes.values():
        for (_label, x, y, hx, hy) in pads:
            lo_i, hi_i = mesh._span(mesh.X, x - hx - 1e-3, x + hx + 1e-3)
            lo_j, hi_j = mesh._span(mesh.Y, y - hy - 1e-3, y + hy + 1e-3)
            for i in range(lo_i, hi_i + 1):
                for j in range(lo_j, hi_j + 1):
                    if not centres.get((i, j)):
                        ok[i * mesh.ny + j] = 0
    return ok


# --- the negotiation --------------------------------------------------------------------------------------------
class Router:
    """Node-disjoint paths on the mesh, reached by negotiated congestion."""

    def __init__(self, mesh: Mesh, columns: bytearray, costs: PlanCosts, plane: set):
        self.mesh = mesh
        self.columns = columns
        self.costs = costs
        self.plane = plane  # layer indices carrying a power or ground pour
        self.use: dict = defaultdict(set)  # node -> the nets whose run passes through it
        self.column_use: dict = defaultdict(set)  # (i, j) -> the nets with a via there
        self.want: dict = {}  # node -> the one net holding it as meander room beside its run
        self.halo: dict = defaultdict(set)  # net -> the nodes it holds that way
        self.history: dict = defaultdict(float)
        self.present = costs.present

    def node_cost(self, nid: int, net: str) -> float:
        m = self.mesh
        li, i, j = m.unpack(nid)
        others = len(self.use[nid] - {net}) + len(self.column_use[(i, j)] - {net})
        room = self.want.get(nid)
        return (self.present * others + self.costs.room_mm * (room is not None and room != net)
                + self.history[nid])

    def route_net(self, net: str, targets: list, seeds: set) -> list | None:
        """Grow the net's tree to every target in turn, nearest first, each by an A* over the mesh. Returns the
        edges of the tree, or None if a target cannot be reached."""
        tree = set(seeds)
        edges = []
        left = [t for t in targets if not (set(t) & tree)]
        while left:
            best = None
            for k, target in enumerate(left):
                path = self._search(net, tree, set(target))
                if path and (best is None or path[0] < best[0]):
                    best = (path[0], k, path[1])
            if best is None:
                return None
            _cost, k, path = best
            for a, b in zip(path, path[1:]):
                edges.append((a, b))
            tree.update(path)
            left.pop(k)
            left = [t for t in left if not (set(t) & tree)]
        return edges

    def _search(self, net: str, sources: set, targets: set):
        m = self.mesh
        via = self.costs.via_mm
        step = self.costs.step_mm
        tx = [m.X[m.unpack(t)[1]] for t in targets]
        ty = [m.Y[m.unpack(t)[2]] for t in targets]

        def h(nid):
            x, y = m.xy(nid)
            return min(abs(x - a) + abs(y - b) for a, b in zip(tx, ty))

        dist: dict = {}
        prev: dict = {}
        heap = []
        for s in sources:
            if m.blocked[s] and s not in targets:
                continue
            dist[s] = 0.0
            heapq.heappush(heap, (h(s), 0.0, s))
        while heap:
            _f, d, nid = heapq.heappop(heap)
            if d > dist.get(nid, math.inf) + 1e-9:
                continue
            if nid in targets:
                path = [nid]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                return d, path[::-1]
            li, i, j = m.unpack(nid)
            x, y = m.X[i], m.Y[j]
            factor = 1.0 + (self.costs.plane_mm if li in self.plane else 0.0)
            for (di, dj) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = i + di, j + dj
                if not (0 <= a < m.nx and 0 <= b < m.ny):
                    continue
                nxt = m.nid(li, a, b)
                if (m.blocked[nxt] or m.owner.get(nxt, net) != net) and nxt not in targets:
                    continue
                w = (abs(m.X[a] - x) + abs(m.Y[b] - y)) * factor + self.node_cost(nxt, net)
                nd = d + w
                if nd < dist.get(nxt, math.inf) - 1e-9:
                    dist[nxt] = nd
                    prev[nxt] = nid
                    heapq.heappush(heap, (nd + h(nxt), nd, nxt))
            if not self.columns[i * m.ny + j]:
                continue
            for lk in range(m.nl):
                if lk == li:
                    continue
                nxt = m.nid(lk, i, j)
                if (m.blocked[nxt] or m.owner.get(nxt, net) != net) and nxt not in targets:
                    continue
                nd = d + via + self.node_cost(nxt, net) + step * 1e-3 * abs(lk - li)
                if nd < dist.get(nxt, math.inf) - 1e-9:
                    dist[nxt] = nd
                    prev[nxt] = nid
                    heapq.heappush(heap, (nd + h(nxt), nd, nxt))
        return None

    def claim(self, net: str, edges: list, halo: int = 0):
        m = self.mesh
        for (a, b) in edges:
            for nid in (a, b):
                self.use[nid].add(net)
            la, ia, ja = m.unpack(a)
            lb, _ib, _jb = m.unpack(b)
            if la != lb:
                self.column_use[(ia, ja)].add(net)
        for nid in self.beside(net, edges, halo):
            self.want[nid] = net
            self.halo[net].add(nid)

    def beside(self, net: str, edges: list, depth: int) -> list:
        """The free nodes within ``depth`` of a run, across it: the room a serpentine would use. A node another
        net's run passes through, or that another net already holds, is not room."""
        m = self.mesh
        out = []
        for (a, b) in edges:
            la, ia, ja = m.unpack(a)
            lb, ib, jb = m.unpack(b)
            if la != lb:
                continue
            across = ((0, 1), (0, -1)) if ib != ia else ((1, 0), (-1, 0))
            for (di, dj) in across:
                for d in range(1, depth + 1):
                    i, j = ia + di * d, ja + dj * d
                    if not (0 <= i < m.nx and 0 <= j < m.ny):
                        break
                    nid = m.nid(la, i, j)
                    if m.blocked[nid] or m.owner.get(nid, net) != net or (self.use[nid] - {net}):
                        break
                    if self.want.get(nid, net) != net:
                        break
                    out.append(nid)
        return out

    def release(self, net: str, edges: list):
        m = self.mesh
        for (a, b) in edges:
            for nid in (a, b):
                self.use[nid].discard(net)
            la, ia, ja = m.unpack(a)
            if la != m.unpack(b)[0]:
                self.column_use[(ia, ja)].discard(net)
        for nid in self.halo.pop(net, ()):
            if self.want.get(nid) == net:
                del self.want[nid]

    def conflicts(self) -> list:
        out = [nid for nid, nets in self.use.items() if len(nets) > 1]
        out += [self.mesh.nid(0, i, j) for (i, j), nets in self.column_use.items() if len(nets) > 1]
        return out

    def where(self, nid: int) -> str:
        x, y = self.mesh.xy(nid)
        return f"({x:.2f}, {y:.2f})"

    def contested_nets(self) -> set:
        out = set()
        for nets in self.use.values():
            if len(nets) > 1:
                out |= nets
        for nets in self.column_use.values():
            if len(nets) > 1:
                out |= nets
        return out


# --- the plan ---------------------------------------------------------------------------------------------------
def _tree_legs(mesh: Mesh, net: str, edges: list, label_at: dict, packages, pads, names) -> list:
    """Cut the net's tree into legs: a leg runs on one layer from one site to the next, and a site is a terminal,
    a via or a junction where the tree branches."""
    adj: dict = defaultdict(set)
    for (a, b) in edges:
        adj[a].add(b)
        adj[b].add(a)
    vias = set()
    for (a, b) in edges:
        if mesh.unpack(a)[0] != mesh.unpack(b)[0]:
            vias.add(a)
            vias.add(b)
    stops = {n for n in adj if n in label_at or n in vias or len(adj[n]) != 2}
    legs = []
    seen = set()
    for start in sorted(stops):
        for first in sorted(adj[start]):
            if (start, first) in seen:
                continue
            walk = [start, first]
            seen.add((start, first))
            seen.add((first, start))
            while walk[-1] not in stops:
                nxt = [k for k in adj[walk[-1]] if k != walk[-2]]
                if not nxt:
                    break
                seen.add((walk[-1], nxt[0]))
                seen.add((nxt[0], walk[-1]))
                walk.append(nxt[0])
            if mesh.unpack(walk[0])[0] != mesh.unpack(walk[1])[0]:
                continue  # the via itself, which is a site rather than a leg
            layer = mesh.layers[mesh.unpack(walk[0])[0]]
            route = _simplify([mesh.xy(n) for n in walk])
            ends = []
            for n in (walk[0], walk[-1]):
                x, y = mesh.xy(n)
                label = label_at.get(n) or (f"via@{x:.3f},{y:.3f}" if n in vias else f"j@{x:.3f},{y:.3f}")
                ends.append(_site_of(label, x, y, packages, pads, names))
            legs.append(Leg(net=net, a=ends[0], b=ends[1], layer=mesh.layer_name[layer], route=route,
                            length_mm=round(_length(route), 3)))
    return legs


def _simplify(points: list) -> list:
    out = [points[0]]
    for p in points[1:]:
        if len(out) >= 2:
            (ax, ay), (bx, by) = out[-2], out[-1]
            if abs((bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)) < 1e-9:
                out[-1] = p
                continue
        out.append(p)
    return out


def _length(points: list) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def _order_of(plan: BusPlan, board, ref) -> dict:
    """The order each bundle crosses each package's boundary, measured on our own plan the way
    `bus_design.entry_order` measures the reference's: walk the array's box clockwise and read the nets off."""
    out: dict = {}
    pkgs = [p for p in bus_design.packages_of(board, ref) if p.lattice is not None]
    by_net: dict = defaultdict(list)
    for leg in plan.legs:
        by_net[leg.net].append(leg)
    for pkg in pkgs:
        lat = pkg.lattice
        x0, y0, x1, y1 = lat.array_bbox_mm(0.5)
        for net, legs in by_net.items():
            group = bus_design.classify(net)[0]
            best = None
            for leg in legs:
                for (ax, ay), (bx, by) in zip(leg.route, leg.route[1:]):
                    inside_a = x0 <= ax <= x1 and y0 <= ay <= y1
                    inside_b = x0 <= bx <= x1 and y0 <= by <= y1
                    if inside_a == inside_b:
                        continue
                    mx, my = (ax + bx) / 2, (ay + by) / 2
                    side = min({"W": abs(mx - x0), "E": abs(mx - x1), "N": abs(my - y0), "S": abs(my - y1)}.items(),
                               key=lambda kv: kv[1])[0]
                    across = (mx - x0) / lat.pitch if side in "NS" else (my - y0) / lat.pitch
                    pos = bus_design._perimeter(side, across, lat)
                    if best is None or pos < best:
                        best = pos
            if best is not None:
                out.setdefault(f"{group}|{pkg.reference}", []).append((best, bus_design.short_name(net)))
    return {k: [n for _p, n in sorted(v)] for k, v in out.items() if len(v) > 1}


def group_windows(board, ref) -> dict:
    """How closely each group has to match: the spread the board itself achieves. That is the criterion M3b is
    judged by -- plan.md asks for "lengths matched as the reference matches them", and D27 measured what that is
    per group -- so it is also the target a plan has to reserve room against. A board with no bus routed yet has
    no spread to measure and its groups match exactly."""
    d = bus_design.measure_board(board, ref)
    per: dict = defaultdict(list)
    for _n, nd in d["nets"].items():
        if nd["length_mm"] > 0:
            per[nd["group"]].append(nd["length_mm"])
    return {g: round(max(v) - min(v), 3) for g, v in per.items() if len(v) > 1}


def negotiate(router: Router, targets: dict, bus: list, costs: PlanCosts, halo: dict, t0: float, say) -> tuple:
    """Negotiated congestion to node-disjoint paths, which is what makes the plan crossing-free. ``halo`` is the
    room each net holds beside its run for its meanders."""
    order = sorted(bus, key=lambda n: (-halo.get(n, 0), -_extent(targets.get(n, []))))
    trees: dict = {}
    failed: list = []
    best = None
    rnd = 0
    for rnd in range(costs.rounds):
        # Round one lays every net down; after that only the nets in a conflict are ripped up and re-routed
        # against the others' standing claims. Re-routing all of them every round does not settle: a net moves
        # off a contested node and another moves straight on to it, and the two trade places for ever.
        todo = order if rnd == 0 else [n for n in order if n in router.contested_nets() or n in failed]
        for net in todo:
            t = targets.get(net)
            if not t:
                continue
            if net in trees:
                router.release(net, trees.pop(net))
            if net in failed:
                failed.remove(net)
            edges = router.route_net(net, t[1:], set(t[0]))
            if edges is None:
                failed.append(net)
                continue
            trees[net] = edges
            router.claim(net, edges, halo.get(net, 0))
        bad = router.conflicts()
        say(f"   round {rnd + 1}: {len(trees)} of {len(bus)} nets routed, {len(todo)} re-routed, "
            f"{len(bad)} contested nodes, {time.time() - t0:.0f}s")
        if best is None or (len(failed), len(bad)) < best[0]:
            best = ((len(failed), len(bad)), dict(trees))
        if not bad and not failed:
            break
        for nid in bad:
            router.history[nid] += costs.history
        router.present *= costs.present_growth
        if time.time() - t0 > costs.budget_s:
            say(f"   the budget of {costs.budget_s:.0f}s is spent after round {rnd + 1}")
            break
    if best[0] != (0, 0):  # the best round, not the last: a later round can be worse than one already seen
        for net in set(trees) - set(best[1]):
            router.release(net, trees[net])
        for net, edges in best[1].items():
            if net not in trees:
                router.claim(net, edges, halo.get(net, 0))
        contested = sorted({router.where(nid) for nid in router.conflicts()})
        say(f"   {best[0][0]} net(s) unrouted and {len(contested)} node(s) still contested: "
            + ", ".join(contested[:6]))
    return best[1], rnd + 1


def plan_bus(board, ref, costs: PlanCosts | None = None, trace=None) -> BusPlan:
    """Plan the bus of a board: the answer M3a has to produce, in the form `busplan.check` judges.

    Two passes. The first lays every net down at one track wide and says what each net's length deficit is; the
    second routes them again with the neediest first and each holding the room its meanders will need, which is
    the area assignment the plan owes M3b. Reserving nothing and hoping is what packs a bundle shoulder to
    shoulder and leaves a net short of its group with nowhere to make the length up."""
    costs = costs or PlanCosts()
    t0 = time.time()
    say = trace or (lambda _s: None)
    layers = signal_layers(board, ref, costs.min_nets_for_signal_layer)
    mesh = Mesh(board, ref, layers, costs)
    shapes, names, _balls = terminals(board, ref)
    styles = styles_of(board, ref)
    columns = via_columns(mesh, styles, shapes)
    plane = _plane_layers(board, mesh)
    windows = group_windows(board, ref)
    say(f"   mesh {mesh.nx}x{mesh.ny} nodes on {mesh.nl} layers "
        f"({', '.join(mesh.layer_name[L] for L in mesh.layers)}), "
        f"{sum(columns)} via columns of {mesh.nx * mesh.ny}, {time.time() - t0:.1f}s")
    say("   match to within " + ", ".join(f"{g} {w:.1f} mm" for g, w in sorted(windows.items())))

    bus = sorted(kb.nets_matching(board, ref.bus_net_pattern))
    targets, label_at, _pad_layers = _terminal_nodes(mesh, shapes, names)
    router = Router(mesh, columns, costs, plane)

    say("   pass 1: one track a net")
    trees, rounds = negotiate(router, targets, bus, costs, {}, t0, say)
    deficit = _deficits(mesh, trees, windows)
    halo = {}
    for net in trees:
        if bus_design.classify(net)[0] == "other":
            continue
        d = deficit.get(net, 0.0)
        l = max(_tree_length(mesh, trees[net]), 1e-6)
        # invert the serpentine: the amplitude in mesh steps that affords d over a run of l
        want = math.sqrt(max((d / l + 1) ** 2 - 1, 0.0)) / 2
        halo[net] = max(1, min(costs.meander_depth, math.ceil(want)))
    if halo:
        say(f"   pass 2: {len(halo)} net(s) short of their group by up to {max(deficit.values()):.1f} mm, "
            f"holding up to {max(halo.values())} track(s) of room each")
        router = Router(mesh, columns, costs, plane)
        trees, more = negotiate(router, targets, bus, costs, halo, t0, say)
        rounds += more

    plan = BusPlan(board=ref.key)
    for net, edges in sorted(trees.items()):
        plan.legs += _tree_legs(mesh, net, edges, label_at, mesh.packages, shapes.get(net, ()), names.get(net, {}))
    deficit = _reserve(mesh, router, plan, windows)
    short = _short(plan, deficit)
    if short:
        say(f"   {len(short)} net(s) still short of room: taking what is left beside their runs, neediest first")
        for net, _gap in sorted(short.items(), key=lambda kv: -kv[1]):
            for nid in router.beside(net, trees[net], costs.meander_depth * 3):
                router.want[nid] = net
                router.halo[net].add(nid)
        deficit = _reserve(mesh, router, plan, windows)
        short = _short(plan, deficit)
    if short:
        say(f"   {len(short)} net(s) have no room for their deficit: "
            + ", ".join(f"{bus_design.short_name(n)} {g:.1f} mm" for n, g in sorted(short.items())[:6]))
    plan.order = _order_of(plan, board, ref)
    plan.provenance = {
        "source": "the planner of M3a",
        "layers": [mesh.layer_name[L] for L in mesh.layers],
        "mesh": f"{mesh.nx}x{mesh.ny}x{mesh.nl}",
        "styles": {k: v["places"] for k, v in styles.items()},
        "match_window_mm": windows,
        "costs": dict(costs.__dict__),
        "rounds": rounds,
        "contested": sorted({router.where(nid) for nid in router.conflicts()}),
        "build_s": round(time.time() - t0, 1),
        "unrouted": sorted(set(bus) - set(trees)),
    }
    return plan


def _short(plan: BusPlan, deficit: dict) -> dict:
    """Net -> how much of its deficit the plan has found no room for."""
    room: dict = defaultdict(float)
    for leg in plan.legs:
        room[leg.net] += leg.reserved_mm
    return {net: round(d - room[net], 3) for net, d in deficit.items() if d > room[net] + 1e-6}


def _tree_length(mesh: Mesh, edges: list) -> float:
    total = 0.0
    for (a, b) in edges:
        la, ia, ja = mesh.unpack(a)
        lb, ib, jb = mesh.unpack(b)
        if la == lb:
            total += abs(mesh.X[ib] - mesh.X[ia]) + abs(mesh.Y[jb] - mesh.Y[ja])
    return total


def _deficits(mesh: Mesh, trees: dict, windows: dict) -> dict:
    """Each net's shortfall against the longest of its group, less the spread that group is allowed."""
    planned = {net: _tree_length(mesh, edges) for net, edges in trees.items()}
    groups: dict = defaultdict(list)
    for net in planned:
        groups[bus_design.classify(net)[0]].append(net)
    out = {}
    for group, members in groups.items():
        if group == "other" or len(members) < 2:
            continue
        longest = max(planned[m] for m in members)
        for m in members:
            d = longest - windows.get(group, 0.0) - planned[m]
            if d > 1e-6:
                out[m] = round(d, 3)
    return out


def _plane_layers(board, mesh: Mesh) -> set:
    """The layer indices a power or ground pour covers, which a run pays `plane_mm` a millimetre to cross."""
    out = set()
    x0, y0, x1, y1 = mesh.region
    for z in board.Zones():
        if not z.IsOnCopperLayer():
            continue
        bb = z.GetBoundingBox()
        if kb.mm(bb.GetLeft()) > x1 or kb.mm(bb.GetRight()) < x0 or kb.mm(bb.GetTop()) > y1 or kb.mm(bb.GetBottom()) < y0:
            continue
        for L in z.GetLayerSet().CuStack():
            if L in mesh.index_of_layer:
                out.add(mesh.index_of_layer[L])
    return out


def _terminal_nodes(mesh: Mesh, shapes: dict, names: dict):
    """Every net's terminals as mesh nodes: one group of nodes per terminal (the same copper on each of its pad's
    layers), the label the plan gives it, and the layers it is reachable on."""
    targets: dict = {}
    label_at: dict = {}
    pad_layers: dict = {}
    for net, pads in shapes.items():
        per: dict = defaultdict(list)
        for (label, x, y, _hx, _hy) in pads:
            per[names[net].get(label, label)].append((label, x, y))
        groups = []
        for term, members in sorted(per.items()):
            _label, x, y = members[0]
            i, j = mesh.near_x(x), mesh.near_y(y)
            nodes = []
            for li in range(mesh.nl):
                nid = mesh.nid(li, i, j)
                if mesh.owner.get(nid) == net and not mesh.blocked[nid]:
                    nodes.append(nid)
                    label_at[nid] = term
            if not nodes:  # the pad's own node is taken: fall back to the nearest node it owns on any layer
                nid = mesh.nid(0, i, j)
                nodes = [nid]
                label_at[nid] = term
            groups.append(tuple(nodes))
            pad_layers[term] = nodes
        if groups:
            targets[net] = groups
    return targets, label_at, pad_layers


def _extent(groups: list) -> float:
    if not groups:
        return 0.0
    return float(len(groups))


def _reserve(mesh: Mesh, router: Router, plan: BusPlan, windows: dict):
    """What each net needs and what the plan reserves for it.

    A serpentine of amplitude ``a`` at the tightest period the mesh allows -- one node out and one node back --
    turns a run of length ``l`` into ``l * sqrt(1 + 4a^2)`` where ``a`` is measured in mesh steps, so the length
    it affords is ``l * (sqrt(1 + 4a^2) - 1)``: about 1.2 times the run at one node of amplitude and 3.1 at two.
    The amplitude is what the net actually holds beside that run, averaged over it, not what happens to be free:
    room two nets could both use is room neither can rely on."""
    planned: dict = defaultdict(float)
    for leg in plan.legs:
        planned[leg.net] += leg.length_mm
    groups: dict = defaultdict(list)
    for net in planned:
        groups[bus_design.classify(net)[0]].append(net)
    deficit = {}
    for group, members in groups.items():
        if group == "other" or len(members) < 2:
            continue
        longest = max(planned[m] for m in members)
        for m in members:
            d = longest - windows.get(group, 0.0) - planned[m]
            if d > 1e-6:
                deficit[m] = round(d, 3)
    for leg in plan.legs:
        leg.reserved_mm = round(_afforded(mesh, router, leg), 3)
        # the tracks the leg asks for: itself, and the amplitude its room affords to either side of it
        ratio = leg.reserved_mm / max(leg.length_mm, 1e-6)
        leg.units = 1 + 2 * int(math.ceil(math.sqrt(max((ratio + 1) ** 2 - 1, 0.0)) / 2))
    plan.deficit_mm = deficit
    return deficit


def _afforded(mesh: Mesh, router: Router, leg: Leg) -> float:
    """The length the room this leg holds affords, by the serpentine above."""
    held = router.halo.get(leg.net, ())
    if not held or leg.length_mm <= 0:
        return 0.0
    li = mesh.index_of_layer[_layer_id(mesh, leg.layer)]
    corners = [(mesh.near_x(x), mesh.near_y(y)) for (x, y) in leg.route]
    walk = []
    for (i, j), (i2, j2) in zip(corners, corners[1:]):
        si, sj = (i2 > i) - (i2 < i), (j2 > j) - (j2 < j)
        a, b = i, j
        while (a, b) != (i2, j2):
            walk.append((a, b))
            a, b = a + si, b + sj
    walk.append(corners[-1])
    beside = 0
    for k, (a, b) in enumerate(walk):
        other = walk[k + 1] if k + 1 < len(walk) else walk[k - 1]
        di, dj = (0, 1) if other[0] != a else (1, 0)  # across the run
        for sign in (1, -1):
            for d in range(1, max(mesh.nx, mesh.ny)):
                u, v = a + di * d * sign, b + dj * d * sign
                if not (0 <= u < mesh.nx and 0 <= v < mesh.ny) or mesh.nid(li, u, v) not in held:
                    break
                beside += 1
    amplitude = beside / (2 * len(walk))
    return leg.length_mm * (math.sqrt(1 + 4 * amplitude ** 2) - 1)


def _layer_id(mesh: Mesh, name: str) -> int:
    for L, n in mesh.layer_name.items():
        if n == name:
            return L
    raise KeyError(name)
