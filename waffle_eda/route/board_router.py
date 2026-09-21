"""The general router of M4: every net of a whole board, from placement, with no bus behind it.

Where the bus routers work on a package's lattice (`route.escape`) or a bus grid between two packages
(`route.bus`), this one has no package to anchor on: a class A board is a microcontroller, some passives and
headers, and the nets run wherever there is room. So the graph is a uniform grid over the whole routing region on
every copper layer, plus a node at each pad centre, with a via edge joining the layers at each grid position.

**Feasibility is exact, never a proxy.** An edge is usable when the track it would become clears the board's
copper under the measured rules, asked of `route.obstacles`, which is KiCad's own shape collision. The grid
decides where a track may run; it never decides whether one fits.

**A net is grown as a tree.** The first pad seeds it; each further pad is reached by an A* from every node the
tree already occupies, so a later pad joins wherever the net is nearest rather than at its first pad. Copper is
added to the board and to the obstacle index as it is laid, so a net routed later sees every net routed before it
exactly, and a net's own copper is something it may touch rather than something it must clear.

**Order matters and is not negotiated yet.** Nets are routed shortest-first by the span of their pads. A net that
cannot be routed is reported with the pad it could not reach; it is never left half-connected in silence. Rip-up
and negotiation, which both existing routers need, are not here: on the boards of the M4 ladder this is measured
rather than assumed, and the gate says which boards it is not enough for.
"""
from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field

import pcbnew

from waffle_eda.kicad import board as kb
from waffle_eda.route.obstacles import Obstacles

DIAGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


@dataclass
class RouteResult:
    """What the router did, per net, so a failure names the pad it could not reach."""

    routed: list = field(default_factory=list)
    failed: dict = field(default_factory=dict)  # net -> why
    tracks: int = 0
    vias: int = 0
    seconds: float = 0.0
    nodes: int = 0

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        return (f"{len(self.routed)} nets routed, {len(self.failed)} failed; "
                f"{self.tracks} tracks, {self.vias} vias, {self.nodes} grid nodes, {self.seconds:.1f}s")


class _Grid:
    """A uniform lattice on every copper layer, with the pads of the nets to route as extra nodes."""

    def __init__(self, board, rules, region, step_mm: float):
        self.board = board
        self.rules = rules
        self.step = step_mm
        self.layers = [lid for lid, _name in kb.copper_layers(board)]
        x0, y0, x1, y1 = region
        self.x0, self.y0 = x0, y0
        self.nx = max(2, int((x1 - x0) / step_mm) + 1)
        self.ny = max(2, int((y1 - y0) / step_mm) + 1)
        self.pad_xy: dict[int, tuple[float, float]] = {}  # node id -> position, for pad nodes
        self.pad_layer: dict[int, int] = {}
        self._next_pad_id = -1

    # node ids: grid nodes are non-negative, pad nodes negative
    def gid(self, layer_index: int, ix: int, iy: int) -> int:
        return (layer_index * self.ny + iy) * self.nx + ix

    def ungid(self, node: int) -> tuple[int, int, int]:
        ix = node % self.nx
        rest = node // self.nx
        return rest // self.ny, rest % self.ny, ix  # layer index, iy, ix

    def xy(self, node: int) -> tuple[float, float]:
        if node < 0:
            return self.pad_xy[node]
        li, iy, ix = self.ungid(node)
        return self.x0 + ix * self.step, self.y0 + iy * self.step

    def layer_of(self, node: int) -> int:
        if node < 0:
            return self.pad_layer[node]
        li, _iy, _ix = self.ungid(node)
        return self.layers[li]

    def add_pad_node(self, x: float, y: float, layer: int) -> int:
        node = self._next_pad_id
        self._next_pad_id -= 1
        self.pad_xy[node] = (x, y)
        self.pad_layer[node] = layer
        return node


class RoutingTooLarge(RuntimeError):
    """The board needs a finer grid than this router can hold without the global stage."""


class BoardRouter:
    """Routes every net of a board under `bench.rebuild.BoardRules`."""

    MAX_NODES = 400_000

    def __init__(self, board, rules, fixed_nets: set[str] | None = None, step_mm: float | None = None,
                 say=lambda _m: None):
        self.board = board
        self.rules = rules
        self.say = say
        self.fixed = set(fixed_nets or ())
        self.track_mm = rules.min_track_mm
        self.clearance_mm = rules.clearance_mm
        self.hole_clearance_mm = rules.hole_to_copper_mm
        self.via_mm = rules.min_via_mm
        self.via_drill_mm = rules.min_drill_mm
        # The step has to resolve the finest pad row on the board, not just fit a track. Derived from the track
        # it lands on 0.4969 mm against `tinkerforge-temperature`'s 0.498 mm pad pitch (D51): a point beside a
        # pad then snaps to a lattice line up to half a step away, which is sideways into the neighbouring pad,
        # and such a pad ends with no reachable node at all.
        self.pad_pitch = self._finest_pad_pitch()
        self.step = step_mm or min(max(self.track_mm + self.clearance_mm, 0.1), max(self.pad_pitch / 3, 0.05))
        region = self._region()
        self.grid = _Grid(board, rules, region, self.step)
        # A grid fine enough for the pads is too big for a large board, which is what stage B of
        # `docs/router-spec.md` exists to fix: restricting the detailed search to a coarse guide. Until it
        # exists, say so and stop rather than filling memory and appearing to work.
        nodes = self.grid.nx * self.grid.ny * len(self.grid.layers)
        if nodes > self.MAX_NODES:
            raise RoutingTooLarge(
                f"{nodes:,} grid nodes at a {self.step:.4f} mm step (the finest pad pitch is "
                f"{self.pad_pitch:.3f} mm) exceeds the {self.MAX_NODES:,} this router can hold. A board this "
                f"size needs the global stage of docs/router-spec.md section 6, which is not built.")
        self.obs = Obstacles(board, local_clearance=True)
        self.net_by_name = {n.GetNetname(): n for n in board.GetNetsByName().values()}
        self._placed: set[str] = set()
        # grid node -> the pad nodes of the net being routed that sit beside it. Without this the graph is
        # one-way: a pad has edges out to the grid and the grid has none back, so every target pad is
        # unreachable and every net fails with no copper laid at all.
        self._pad_near: dict[int, list[int]] = {}
        self._free_adj: dict[int, list[int]] = {}   # off-lattice node -> what it connects to

    def _finest_pad_pitch(self) -> float:
        """The smallest centre-to-centre spacing between two pads of one footprint that do not overlap.

        Overlapping pads are one pad electrically and are not a row: `olimex-rp2040-pico-pc` has a USB shield
        pad lying across a signal pad 0.025 mm away, and `libresolar-mppt-2420` draws a MOSFET drain as a large
        and a small pad 0.150 mm apart. Counting those as a pitch drove the grid step to its floor and asked for
        2.1 and 5.4 million nodes on boards whose real pad rows are far coarser.
        """
        finest = math.inf
        for fp in self.board.GetFootprints():
            pads = [(kb.mm(p.GetPosition().x), kb.mm(p.GetPosition().y), p.GetBoundingBox()) for p in fp.Pads()]
            for i, (ax, ay, abb) in enumerate(pads):
                for bx, by, bbb in pads[i + 1:]:
                    if abb.Intersects(bbb):
                        continue  # one pad drawn as two shapes, not two pads in a row
                    d = math.dist((ax, ay), (bx, by))
                    if 1e-6 < d < finest:
                        finest = d
        return finest if finest < math.inf else 1.0

    def _region(self) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = kb.outline_bbox_mm(self.board)
        inset = self.rules.edge_clearance_mm + self.track_mm / 2 + 1e-6
        return x0 + inset, y0 + inset, x1 - inset, y1 - inset

    # --- geometry -----------------------------------------------------------------------------------------
    def _track(self, layer: int, a: tuple[float, float], b: tuple[float, float], net) -> pcbnew.PCB_TRACK:
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(pcbnew.VECTOR2I(kb.nm(a[0]), kb.nm(a[1])))
        t.SetEnd(pcbnew.VECTOR2I(kb.nm(b[0]), kb.nm(b[1])))
        t.SetWidth(kb.nm(self.track_mm))
        t.SetLayer(layer)
        t.SetNet(net)
        return t

    def _via(self, at: tuple[float, float], net) -> pcbnew.PCB_VIA:
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(pcbnew.VECTOR2I(kb.nm(at[0]), kb.nm(at[1])))
        v.SetDrill(kb.nm(self.via_drill_mm))
        kb.set_via_diameter(v, self.via_mm)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(self.grid.layers[0], self.grid.layers[-1])
        v.SetNet(net)
        return v

    def _clear(self, item, net_name: str) -> bool:
        """Whether ``item`` clears every other net's copper. Same-net copper is not an obstacle: that is how a
        net's own tree is joined."""
        return self.obs.clear(item, self.clearance_mm, hole_clearance_mm=self.hole_clearance_mm) is None

    STUB_LENGTHS = (0.3, 0.4, 0.5, 0.7, 1.0, 1.4, 2.0)
    STUB_DIRECTIONS = ((0, -1), (0, 1), (1, 0), (-1, 0),
                       (0.7071, 0.7071), (0.7071, -0.7071), (-0.7071, 0.7071), (-0.7071, -0.7071))

    def _stubs(self, x: float, y: float, layer: int, net_name: str, net) -> list[tuple[float, float]]:
        """Points a straight track can reach from (x, y), one per direction, shortest that clears.

        This is the escape, and it has to end where the geometry allows rather than on a lattice line. Measured
        on `tinkerforge-temperature` (D51): a stub leaves the middle pad of its SOT-563 cleanly at 0.4 mm north
        or south, while **no lattice node is reachable from that pad at all**, at either step tried, because the
        nearest node to the clear direction sits sideways of it and the track to it runs into the neighbouring
        pad. A pad row at 0.498 mm pitch is finer than any grid this router can afford over a whole board.
        """
        out = []
        for ux, uy in self.STUB_DIRECTIONS:
            for length in self.STUB_LENGTHS:
                end = (x + ux * length, y + uy * length)
                if self._clear(self._track(layer, (x, y), end, net), net_name):
                    out.append(end)
                    break
        return out

    def _node_at(self, x: float, y: float, layer_index: int) -> int | None:
        grid = self.grid
        ix = int(round((x - grid.x0) / grid.step))
        iy = int(round((y - grid.y0) / grid.step))
        if 0 <= ix < grid.nx and 0 <= iy < grid.ny:
            return grid.gid(layer_index, ix, iy)
        return None

    def _lattice_near(self, x: float, y: float, layer: int, net_name: str, net, reach: float = 2.0,
                      keep: int = 12) -> list[int]:
        """The grid nodes (x, y) can reach by one straight track, nearest first.

        A fine-pitch pad has no usable node in the cell around it. A track of this board's own width needs
        0.694 mm to pass between two pads of `tinkerforge-temperature`, whose TSSOP-8 leaves 0.245 mm and whose
        SOT-563 leaves 0.198 mm (D51), so such a pad must reach out of its own pad row before it is on the grid
        at all. Walking outward in eight directions finds that, and leaving it as edges of the same search means
        the route picks its escape rather than having one picked for it in advance, which is D36's lesson.
        """
        grid = self.grid
        if layer not in grid.layers:
            return []
        li = grid.layers.index(layer)
        span = max(1, int(reach / grid.step))
        ix = int(round((x - grid.x0) / grid.step))
        iy = int(round((y - grid.y0) / grid.step))
        candidates = []
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                jx, jy = ix + dx, iy + dy
                if not (0 <= jx < grid.nx and 0 <= jy < grid.ny) or (dx == 0 and dy == 0):
                    continue
                node = grid.gid(li, jx, jy)
                candidates.append((math.dist((x, y), grid.xy(node)), node))
        candidates.sort()
        out: list[int] = []
        for _d, node in candidates:
            if self._clear(self._track(layer, (x, y), grid.xy(node), net), net_name):
                out.append(node)
                if len(out) >= keep:
                    break
        return out

    # --- search -------------------------------------------------------------------------------------------
    def _neighbours(self, node: int, net_name: str, net):
        """(neighbour, cost, item) for each edge out of ``node`` that clears the board."""
        grid = self.grid
        here = grid.xy(node)
        layer = grid.layer_of(node)
        out = []
        if node < 0:  # a pad or an escape point: its edges were found when the net's pads were built
            for other in self._free_adj.get(node, ()):
                there = grid.xy(other)
                item = self._track(layer, here, there, net)
                if self._clear(item, net_name):
                    out.append((other, math.dist(here, there), item))
            return out
        li, iy, ix = grid.ungid(node)
        for dx, dy in DIAGONAL:
            jx, jy = ix + dx, iy + dy
            if not (0 <= jx < grid.nx and 0 <= jy < grid.ny):
                continue
            other = grid.gid(li, jx, jy)
            there = grid.xy(other)
            item = self._track(layer, here, there, net)
            if self._clear(item, net_name):
                out.append((other, math.dist(here, there), item))
        if len(grid.layers) > 1:  # a via joins every layer at this position
            via = self._via(here, net)
            if self._clear(via, net_name):
                for lj in range(len(grid.layers)):
                    if lj == li:
                        continue
                    out.append((grid.gid(lj, ix, iy), self.step * 2.0, via))
        for pad_node in self._pad_near.get(node, ()):  # the way back into a pad, which the graph needs to exist
            if grid.layer_of(pad_node) != layer:
                continue
            there = grid.xy(pad_node)
            item = self._track(layer, here, there, net)
            if self._clear(item, net_name):
                out.append((pad_node, math.dist(here, there), item))
        return out

    def _search(self, sources: set[int], targets: set[int], net_name: str, net, budget: int):
        """A* from every node of ``sources`` to the nearest of ``targets``; returns (path, items) or None."""
        grid = self.grid
        goals = [grid.xy(t) for t in targets]

        def h(node: int) -> float:
            x, y = grid.xy(node)
            return min(math.dist((x, y), g) for g in goals)

        dist = {s: 0.0 for s in sources}
        prev: dict[int, tuple[int, object]] = {}
        heap = [(h(s), 0.0, i, s) for i, s in enumerate(sources)]
        heapq.heapify(heap)
        counter = len(sources)
        seen = set()
        while heap:
            _f, d, _c, node = heapq.heappop(heap)
            if node in seen:
                continue
            seen.add(node)
            if len(seen) > budget:
                return None
            if node in targets:
                path, items = [node], []
                while node in prev:
                    node, item = prev[node]
                    path.append(node)
                    items.append(item)
                return list(reversed(path)), items
            for other, cost, item in self._neighbours(node, net_name, net):
                nd = d + cost
                if nd < dist.get(other, math.inf):
                    dist[other] = nd
                    prev[other] = (node, item)
                    counter += 1
                    heapq.heappush(heap, (nd + h(other), nd, counter, other))
        return None

    # --- routing ------------------------------------------------------------------------------------------
    def _pad_nodes(self, net_name: str) -> list[list[int]]:
        """One list of nodes per pad of the net: the pad centre on each copper layer the pad reaches."""
        out = []
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetname() != net_name:
                    continue
                p = pad.GetPosition()
                x, y = kb.mm(p.x), kb.mm(p.y)
                layers = [L for L in pad.GetLayerSet().CuStack() if L in self.grid.layers]
                if not layers:
                    continue
                nodes = [self.grid.add_pad_node(x, y, L) for L in layers]
                net = self.net_by_name.get(net_name)
                for node, layer in zip(nodes, layers):
                    self._wire_free_node(node, x, y, layer, net_name, net, stubs=True)
                out.append(nodes)
        return out

    def _wire_free_node(self, node: int, x: float, y: float, layer: int, net_name: str, net,
                        stubs: bool) -> None:
        """Give an off-lattice node its edges: the lattice nodes it can reach, and, for a pad, an escape stub
        in each direction that clears, each stub's end being a free node wired the same way."""
        adj = list(self._lattice_near(x, y, layer, net_name, net))
        for lattice_node in adj:
            self._pad_near.setdefault(lattice_node, []).append(node)
        if stubs:
            for ex, ey in self._stubs(x, y, layer, net_name, net):
                end = self.grid.add_pad_node(ex, ey, layer)
                adj.append(end)
                self._free_adj.setdefault(end, []).append(node)
                self._wire_free_node(end, ex, ey, layer, net_name, net, stubs=False)
        self._free_adj.setdefault(node, []).extend(adj)

    def route_net(self, net_name: str, budget: int = 60000) -> str | None:
        """Grow one net's tree over its pads. Returns None on success, or why it failed."""
        net = self.net_by_name.get(net_name)
        if net is None:
            return "no such net on the board"
        self._pad_near, self._free_adj = {}, {}  # this net's pads only: another net's pad is copper, not a stop
        pads = self._pad_nodes(net_name)
        if len(pads) < 2:
            return None
        tree = set(pads[0])
        laid = []
        for pad in pads[1:]:
            found = self._search(tree, set(pad), net_name, net, budget)
            if found is None:
                self._unplace(laid)
                x, y = self.grid.xy(pad[0])
                return (f"no route to the pad at ({x:.2f}, {y:.2f}) mm after "
                        f"{len(pads) - 1} pad(s) of {len(pads)}; its copper was taken back off")
            path, items = found
            for item in items:
                self._place(item)
                laid.append(item)
            tree |= set(path)
        return None

    def _unplace(self, items) -> None:
        """Take a failed net's copper back off the board. A half-routed net is not a partial success, and
        leaving its copper there blocks every net routed after it (`definition.md` section 3)."""
        for item in items:
            uid = item.m_Uuid.AsString()
            if uid not in self._placed:
                continue
            self._placed.discard(uid)
            self.obs.remove(item)
            self.board.Delete(item)  # not Remove(): the proxy would own a C++ object with no destructor

    def _place(self, item) -> None:
        """Add a track or via to the board and to the obstacle index, once. A via edge is shared by every layer
        pair it joins, so the same object can come back in more than one path."""
        uid = item.m_Uuid.AsString()
        if uid in self._placed:
            return
        self._placed.add(uid)
        self.board.Add(item)
        self.obs.add(item)

    def route(self, nets: list[str]) -> RouteResult:
        t0 = time.time()
        result = RouteResult(nodes=self.grid.nx * self.grid.ny * len(self.grid.layers))
        order = sorted(nets, key=self._span)
        for name in order:
            if name in self.fixed:
                continue
            why = self.route_net(name)
            if why:
                result.failed[name] = why
                self.say(f"   {name}: FAILED, {why}")
            else:
                result.routed.append(name)
                self.say(f"   {name}: routed")
        result.tracks = len(kb.track_segments(self.board))
        result.vias = len(kb.vias(self.board))
        result.seconds = round(time.time() - t0, 1)
        return result

    def _span(self, net_name: str) -> float:
        """The diagonal of a net's pad box: the shortest nets are routed first, which leaves the long ones the
        room they need rather than the scraps."""
        xs, ys = [], []
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetname() == net_name:
                    p = pad.GetPosition()
                    xs.append(kb.mm(p.x))
                    ys.append(kb.mm(p.y))
        if len(xs) < 2:
            return 0.0
        return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def route_board(board, rules, fixed_nets: set[str] | None = None, nets: list[str] | None = None,
                say=lambda _m: None) -> RouteResult:
    """Route every net of ``board`` under ``rules``, leaving the copper of ``fixed_nets`` untouched.

    The board is modified in place; the result says what was routed and, for anything that was not, the pad it
    could not reach.
    """
    from waffle_eda.bench import rebuild

    if nets is None:
        nets = sorted(rebuild.routable_nets(board))
    router = BoardRouter(board, rules, fixed_nets=fixed_nets, say=say)
    return router.route(nets)
