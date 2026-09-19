"""The bus planner (decisions D26 step 4, D28): decides, before any detailed search, which layer each run takes and
which coarse route, under explicit channel capacities, with the length a net still needs reserved as capacity along
its route. The detailed router then works inside these guides.

Cells: a grid of square cells (half a pitch) per layer over the routing region. The capacity of the boundary between
two neighbouring cells on a layer is the number of tracks that can cross it clear of the fixed copper on that layer
(pads, vias, tracks of other nets), counted by sampling the boundary and adding up its free runs. A run (a net's
single-layer link between two terminals) takes one unit of capacity on every boundary it crosses, plus the units its
length deficit asks for (a serpentine of pitch p adding d mm of length needs about d*p of area beside the run).
Routing is negotiated congestion on the cell graph, with the layer chosen by the search: a run is searched on every
layer it may take and the cheapest wins, so a run comes out on one layer.

A terminal's own pad or via fills its cell and blocks the cell's boundaries; a net's own copper is no obstacle to
it, so around a run's terminals the capacities are recomputed for that run with its net's copper left out (the
termination resistors' pads on ButterStick sit against the memory's balls, and only their own net gets through).

The length room is optional capacity: a run whose net is short of its group asks for extra tracks beside it, takes
them on every boundary that has them to spare, and pays a little for every boundary that has not (so that it prefers
the wide channels, as the references make their length in the margins and hollows, without refusing a narrow pass).
What it could take is added up as the length it affords (``Run.reserved_mm``): the plan's own measure of whether the
tuner will find the room.
"""
from __future__ import annotations

import heapq
import math
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pcbnew

from waffle_eda.kicad import board as kb


# --- fixed copper, as circles and segments per layer -----------------------------------------------------------------
class Fixed:
    def __init__(self, board, region, layer_ids: list[int], skip_nets: set[str] = frozenset(), cell: float = 0.5,
                 extra: list | None = None):
        """``extra``: (layer id, polyline, half-width) items the board does not carry yet but the plan keeps, such as
        the escapes a reference decided."""
        self.cell = cell
        self.circles: dict[int, dict] = {L: defaultdict(list) for L in layer_ids}  # layer -> cell -> [(x, y, r, net)]
        self.rects: dict[int, dict] = {L: defaultdict(list) for L in layer_ids}  # layer -> cell -> [(x, y, hx, hy, net)]
        self.segments: dict[int, dict] = {L: defaultdict(list) for L in layer_ids}  # layer -> cell -> [(ax, ay, bx, by, hw, net)]
        self.count = 0
        x0, y0, x1, y1 = region
        layers = set(layer_ids)
        round_shapes = (pcbnew.PAD_SHAPE_CIRCLE, pcbnew.PAD_SHAPE_OVAL)
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                p = pad.GetPosition()
                x, y = kb.mm(p.x), kb.mm(p.y)
                if not (x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1) or pad.GetNetname() in skip_nets:
                    continue
                size = pad.GetSize()
                sx, sy = kb.mm(size.x), kb.mm(size.y)
                net = pad.GetNetname()
                shape = pad.GetShape()
                angle = pad.GetOrientation().AsDegrees() % 180
                for L in pad.GetLayerSet().CuStack():
                    if L not in layers:
                        continue
                    if shape in round_shapes:  # a round pad by its radius
                        self._add_circle(L, x, y, max(sx, sy) / 2, net)
                    elif abs(angle) < 1e-6 or abs(angle - 90) < 1e-6:  # a rectangle along the axes as it is
                        hx, hy = (sx / 2, sy / 2) if abs(angle) < 1e-6 else (sy / 2, sx / 2)
                        self._add_rect(L, x, y, hx, hy, net)
                    else:  # anything else by its bounding circle
                        self._add_circle(L, x, y, math.hypot(sx, sy) / 2, net)
        for item in board.GetTracks():
            net = item.GetNetname()
            if net in skip_nets:
                continue
            if item.GetClass() == "PCB_VIA":
                p = item.GetPosition()
                x, y = kb.mm(p.x), kb.mm(p.y)
                if x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1:
                    r = kb.via_diameter_mm(item) / 2
                    for L in layer_ids:
                        self._add_circle(L, x, y, r, net)
            else:
                L = item.GetLayer()
                if L not in layers:
                    continue
                a, b = item.GetStart(), item.GetEnd()
                ax, ay, bx, by = kb.mm(a.x), kb.mm(a.y), kb.mm(b.x), kb.mm(b.y)
                if max(ax, bx) < x0 - 1 or min(ax, bx) > x1 + 1 or max(ay, by) < y0 - 1 or min(ay, by) > y1 + 1:
                    continue
                self._add_segment(L, ax, ay, bx, by, kb.mm(item.GetWidth()) / 2, net)
        for (L, points, hw, net) in extra or []:
            if L in layers:
                for (ax, ay), (bx, by) in zip(points, points[1:]):
                    self._add_segment(L, ax, ay, bx, by, hw, net)

    def _key(self, x, y):
        return (int(math.floor(x / self.cell)), int(math.floor(y / self.cell)))

    def _add_circle(self, L, x, y, r, net):
        self.count += 1
        k = self._key(x, y)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                self.circles[L][(k[0] + dx, k[1] + dy)].append((x, y, r, net))

    def _add_rect(self, L, x, y, hx, hy, net):
        self.count += 1
        kx0, ky0 = self._key(x - hx, y - hy)
        kx1, ky1 = self._key(x + hx, y + hy)
        for i in range(kx0 - 1, kx1 + 2):
            for j in range(ky0 - 1, ky1 + 2):
                self.rects[L][(i, j)].append((x, y, hx, hy, net))

    def _add_segment(self, L, ax, ay, bx, by, hw, net):
        self.count += 1
        kx0, ky0 = self._key(min(ax, bx) - hw, min(ay, by) - hw)
        kx1, ky1 = self._key(max(ax, bx) + hw, max(ay, by) + hw)
        for i in range(kx0 - 1, kx1 + 2):
            for j in range(ky0 - 1, ky1 + 2):
                self.segments[L][(i, j)].append((ax, ay, bx, by, hw, net))

    def blocked(self, L, x, y, r, skip: str | None = None) -> bool:
        """Is a track centre at (x, y) with half-width-plus-clearance r too close to fixed copper on layer L? The
        copper of net ``skip`` does not count (a net's own terminals)."""
        k = self._key(x, y)
        for (cx, cy, cr, net) in self.circles[L].get(k, ()):
            if net != skip and math.hypot(x - cx, y - cy) < cr + r:
                return True
        for (cx, cy, hx, hy, net) in self.rects[L].get(k, ()):
            if net != skip and math.hypot(max(abs(x - cx) - hx, 0.0), max(abs(y - cy) - hy, 0.0)) < r:
                return True
        for (ax, ay, bx, by, hw, net) in self.segments[L].get(k, ()):
            if net == skip:
                continue
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
            if math.hypot(x - (ax + t * dx), y - (ay + t * dy)) < hw + r:
                return True
        return False


# --- the cell grid and its capacities ---------------------------------------------------------------------------------
class Cells:
    def __init__(self, region, layer_ids: list[int], fixed: Fixed, track_mm: float, clearance_mm: float,
                 cell_mm: float = 0.4, sample_mm: float = 0.05, grid_mm: float = 0.0):
        """``grid_mm``: the detailed router's node spacing; tracks are counted at that pitch when it is coarser than
        the rules' pitch, so that the plan promises no more than the detailed grid can hold."""
        self.x0, self.y0, x1, y1 = region
        self.c = cell_mm
        self.nx = int(math.ceil((x1 - self.x0) / cell_mm))
        self.ny = int(math.ceil((y1 - self.y0) / cell_mm))
        self.layers = layer_ids
        self.pitch = max(track_mm + clearance_mm, grid_mm)
        self.fixed = fixed
        self.r = track_mm / 2 + clearance_mm
        self.sample = sample_mm
        self.n = max(2, int(round(cell_mm / sample_mm)))
        self.offsets = (-cell_mm / 4, 0.0, cell_mm / 4)
        # cap_h[L][(i, j)]: boundary between (i, j) and (i + 1, j); cap_v[L][(i, j)]: between (i, j) and (i, j + 1)
        self.cap_h: dict = {}
        self.cap_v: dict = {}
        for L in layer_ids:
            ch, cv = {}, {}
            for i in range(self.nx):
                for j in range(self.ny):
                    if i + 1 < self.nx:
                        ch[(i, j)] = self._cut(L, "h", i, j)
                    if j + 1 < self.ny:
                        cv[(i, j)] = self._cut(L, "v", i, j)
            self.cap_h[L], self.cap_v[L] = ch, cv

    def _cut(self, L, kind, i, j, skip=None) -> int:
        """The tracks that cross a boundary: the narrowest of three cuts, on the boundary and a quarter cell either
        side, each sampled along its length and its free runs added up."""
        n, sm, r = self.n, self.sample, self.r
        if kind == "h":
            bx, by = self.x0 + (i + 1) * self.c, self.y0 + j * self.c
            return min(self._tracks([not self.fixed.blocked(L, bx + o, by + (k + 0.5) * sm, r, skip) for k in range(n)])
                       for o in self.offsets)
        bx, by = self.x0 + i * self.c, self.y0 + (j + 1) * self.c
        return min(self._tracks([not self.fixed.blocked(L, bx + (k + 0.5) * sm, by + o, r, skip) for k in range(n)])
                   for o in self.offsets)

    def _tracks(self, free) -> int:
        total, run = 0, 0
        for f in free + [False]:
            if f:
                run += 1
            elif run:
                total += int(math.floor(run * self.sample / self.pitch)) + 1
                run = 0
        return total

    def capacity_near(self, L, x, y, radius_mm: float, skip: str) -> dict:
        """The capacities of the boundaries within ``radius_mm`` of (x, y) with the copper of net ``skip`` left out:
        what a run of that net sees around its own terminal."""
        i0, j0 = self.cell_of(x, y)
        span = int(math.ceil(radius_mm / self.c))
        out = {}
        for i in range(i0 - span, i0 + span + 1):
            for j in range(j0 - span, j0 + span + 1):
                if not (0 <= i < self.nx and 0 <= j < self.ny):
                    continue
                cx, cy = self.centre(i, j)
                if math.hypot(cx - x, cy - y) > radius_mm:
                    continue
                if i + 1 < self.nx:
                    out[("h", i, j)] = self._cut(L, "h", i, j, skip)
                if j + 1 < self.ny:
                    out[("v", i, j)] = self._cut(L, "v", i, j, skip)
        return out

    def cell_of(self, x, y) -> tuple[int, int]:
        return (min(self.nx - 1, max(0, int((x - self.x0) / self.c))), min(self.ny - 1, max(0, int((y - self.y0) / self.c))))

    def centre(self, i, j) -> tuple[float, float]:
        return (self.x0 + (i + 0.5) * self.c, self.y0 + (j + 0.5) * self.c)

    def boundary(self, a, b):
        """The capacity key of the boundary between neighbouring cells a and b: ('h'|'v', i, j)."""
        (i, j), (k, l) = a, b
        if j == l:
            return ("h", min(i, k), j)
        return ("v", i, min(j, l))

    def boundaries_of(self, cell) -> list:
        i, j = cell
        out = []
        for nxt in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= nxt[0] < self.nx and 0 <= nxt[1] < self.ny:
                out.append(self.boundary(cell, nxt))
        return out

    def capacity(self, L, key) -> int:
        kind, i, j = key
        return (self.cap_h if kind == "h" else self.cap_v)[L].get((i, j), 0)

    def octilinear_mm(self, path: list, every: int = 4) -> float:
        """The length of the cell path as the detailed route will run it: octilinear between points a few cells
        apart (a staircase of cells becomes a diagonal)."""
        if len(path) < 2:
            return 0.0
        pts = path[::every] + ([path[-1]] if (len(path) - 1) % every else [])
        total = 0.0
        for (i, j), (k, l) in zip(pts, pts[1:]):
            dx, dy = abs(k - i) * self.c, abs(l - j) * self.c
            total += max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)
        return total

    def total_capacity(self, L) -> int:
        return sum(self.cap_h[L].values()) + sum(self.cap_v[L].values())


# --- crossings ---------------------------------------------------------------------------------------------------------
def _cyclic_position(stretch: list, t: int, cell, d0, d_last) -> float:
    """Where a cell attached to the ``t``-th cell of a shared stretch sits on the walk around the stretch: behind its
    start 0, along its left side 1 to 2, ahead of its end 3, back along its right side 4 to 5."""
    n = len(stretch) - 1
    sx, sy = stretch[t]
    if t == 0 and cell == (sx - d0[0], sy - d0[1]):
        return 0.0
    if t == n and cell == (sx + d_last[0], sy + d_last[1]):
        return 3.0
    d = (stretch[t + 1][0] - sx, stretch[t + 1][1] - sy) if t < n else d_last
    cross = d[0] * (cell[1] - sy) - d[1] * (cell[0] - sx)
    frac = t / n if n else 0.0
    return 1.0 + frac if cross > 0 else 5.0 - frac


def path_crossings(P: list, Q: list) -> list:
    """The stretches of cells two 4-connected paths share on which they cross: each is a list of cells. Two paths
    on one layer can only cross through a shared cell; sharing cells side by side is no crossing. A stretch that
    holds an end of either path is not a crossing (a terminal on the other's route is a matter of capacity)."""
    where = {c: idx for idx, c in enumerate(Q)}
    out = []
    k = 0
    while k < len(P):
        if P[k] not in where:
            k += 1
            continue
        m = k
        while m + 1 < len(P) and P[m + 1] in where and abs(where[P[m + 1]] - where[P[m]]) == 1:
            m += 1
        stretch = P[k:m + 1]
        qi, qj = where[P[k]], where[P[m]]
        if k > 0 and m < len(P) - 1 and min(qi, qj) > 0 and max(qi, qj) < len(Q) - 1:
            p_in, p_out = P[k - 1], P[m + 1]
            q_in = Q[qi - 1] if qj >= qi else Q[qi + 1]  # Q oriented along P
            q_out = Q[qj + 1] if qj >= qi else Q[qj - 1]
            d_last = (p_out[0] - stretch[-1][0], p_out[1] - stretch[-1][1]) if len(stretch) == 1 else \
                (stretch[-1][0] - stretch[-2][0], stretch[-1][1] - stretch[-2][1])
            d0 = (stretch[1][0] - stretch[0][0], stretch[1][1] - stretch[0][1]) if len(stretch) > 1 else d_last
            marks = sorted([(_cyclic_position(stretch, 0, p_in, d0, d_last), "P"),
                            (_cyclic_position(stretch, len(stretch) - 1, p_out, d0, d_last), "P"),
                            (_cyclic_position(stretch, 0, q_in, d0, d_last), "Q"),
                            (_cyclic_position(stretch, len(stretch) - 1, q_out, d0, d_last), "Q")])
            if marks[0][1] != marks[1][1] and marks[1][1] != marks[2][1]:  # P, Q, P, Q around the stretch
                out.append(stretch)
        k = m + 1
    return out


# --- runs and the negotiated global routing --------------------------------------------------------------------------
@dataclass
class Run:
    net: str
    a: tuple[float, float]
    b: tuple[float, float]
    layers: tuple[int, ...]
    units: int = 1  # capacity asked for on every boundary crossed: one track plus the length room wanted
    layer: int | None = None
    cells: list = field(default_factory=list)  # the route as cells on ``layer``
    length_mm: float = 0.0
    taken: dict = field(default_factory=dict)  # boundary key -> extra tracks the route could reserve there
    reserved_mm: float = 0.0  # the length the reserved room affords
    deficit_mm: float = 0.0  # the length the net is short of its group
    tag: object = None  # the caller's handle (which link of which net)
    group: object = None  # runs of one bundle (a lane between two packages) prefer to share a layer
    local: dict = field(default_factory=dict)  # (layer, key) -> capacity around the run's terminals without its own copper
    crossed: list = field(default_factory=list)  # the runs this one crossed last round (their current routes count)

    def guide(self, cells: Cells, half_mm: float | None = None) -> tuple[list, float]:
        """The route as a polyline of cell centres with a half-width: the band the detailed search stays in."""
        points = [cells.centre(*c) for c in self.cells] or [self.a, self.b]
        if half_mm is None:
            half_mm = cells.c * (0.5 + 0.5 * self.units) + 0.1
        return points, half_mm


@dataclass
class PlanCosts:
    iterations: int = 40
    present: float = 0.5
    history: float = 0.3
    layer_bias: dict = field(default_factory=dict)  # layer id -> extra cost per cell (e.g. to keep off the top)
    meander_factor: float = 2.0  # room reserved for a length deficit d along a run of length l: d * factor / l tracks
    affinity_mm: float = 8.0  # a run pays this much (times the share of its bundle elsewhere) for leaving its bundle's layer
    cramped_mm: float = 0.2  # a run pays this much per boundary and per extra track it wanted there but cannot have
    crossing: float = 1.0  # a crossing counts as this much overflow on every boundary of the shared cells
    corridor_mm: float = 6.0  # a run stays within its terminals' bounding box grown by this much: no long detours
    turn_mm: float = 0.4  # a turn costs this much: runs side by side in a channel stay side by side instead of braiding
    seed: int = 1


class Planner:
    def __init__(self, cells: Cells, costs: PlanCosts | None = None):
        self.cells = cells
        self.costs = costs or PlanCosts()
        self.usage: dict = defaultdict(int)  # (layer, key) -> tracks in use (the runs themselves)
        self.extra: dict = defaultdict(int)  # (layer, key) -> tracks reserved as length room
        self.history: dict = defaultdict(float)
        self.local_max: dict = {}  # (layer, key) -> the widest any run's own view of the boundary is
        self.bundles: dict = defaultdict(list)  # group -> runs

    def cap(self, L, key, run: Run | None = None) -> int:
        """The boundary's capacity as ``run`` sees it (its own copper left out around its terminals); without a run,
        the widest view any run has of it, for the shared accounting."""
        if run is not None:
            return run.local.get((L, key), self.cells.capacity(L, key))
        return max(self.cells.capacity(L, key), self.local_max.get((L, key), 0))

    def _search(self, run: Run, present: float):
        cells = self.cells
        ca, cb = cells.cell_of(*run.a), cells.cell_of(*run.b)
        tx, ty = cells.centre(*cb)
        span = int(math.ceil(self.costs.corridor_mm / cells.c))
        i0, i1 = min(ca[0], cb[0]) - span, max(ca[0], cb[0]) + span
        j0, j1 = min(ca[1], cb[1]) - span, max(ca[1], cb[1]) + span
        best = None
        mates = [r for r in self.bundles.get(run.group, ()) if r is not run and r.layer is not None] if run.group is not None else []
        turn = self.costs.turn_mm
        for L in run.layers:
            bias = self.costs.layer_bias.get(L, 0.0)
            apart = self.costs.affinity_mm * (1 - sum(1 for r in mates if r.layer == L) / len(mates)) if mates else 0.0
            # the cells of the runs this one crossed, where they are now: entering one costs like an overflow
            crossed = {c for r in run.crossed if r.layer == L for c in r.cells}
            start = (ca, None)  # (cell, direction of the step that reached it)
            dist = {start: 0.0}
            prev = {}
            heap = [(0.0, 0, start)]
            counter = 0
            found = None
            while heap:
                f, _, cur = heapq.heappop(heap)
                d = dist[cur]
                (i, j), came = cur
                if (i, j) == cb:
                    found = (d, cur)
                    break
                if d > dist.get(cur, math.inf):
                    continue
                for step in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nxt = (i + step[0], j + step[1])
                    if not (0 <= nxt[0] < cells.nx and 0 <= nxt[1] < cells.ny):
                        continue
                    if not (i0 <= nxt[0] <= i1 and j0 <= nxt[1] <= j1):
                        continue
                    key = cells.boundary((i, j), nxt)
                    cap = run.local.get((L, key), self.cells.capacity(L, key))
                    if cap <= 0:
                        continue
                    use = self.usage.get((L, key), 0) + self.extra.get((L, key), 0)
                    over = max(0, use + 1 - cap)
                    if nxt in crossed:
                        over += self.costs.crossing
                    unmet = max(0, run.units - 1 - max(0, cap - use - 1))
                    cost = cells.c + bias + present * over + self.history.get((L, key), 0.0) + self.costs.cramped_mm * unmet
                    if came is not None and step != came:
                        cost += turn
                    state = (nxt, step)
                    nd = d + cost
                    if nd < dist.get(state, math.inf):
                        dist[state] = nd
                        prev[state] = cur
                        counter += 1
                        cx, cy = cells.centre(*nxt)
                        heapq.heappush(heap, (nd + abs(cx - tx) + abs(cy - ty), counter, state))
            if found is not None and (best is None or found[0] + apart < best[0]):
                path = [found[1]]
                while path[-1] != start:
                    path.append(prev[path[-1]])
                best = (found[0] + apart, L, [c for c, _ in reversed(path)])
        return best

    def _apply(self, run: Run, sign: int):
        for a, b in zip(run.cells, run.cells[1:]):
            self.usage[(run.layer, self.cells.boundary(a, b))] += sign

    def _take_room(self, runs: list[Run]):
        """The length room, run by run: on each boundary of its route a run takes the extra tracks it wants where
        the capacity has them to spare after every run's own track and the room taken before it."""
        self.extra = defaultdict(int)
        for run in runs:
            run.taken = {}
            if not run.cells or run.units <= 1:
                run.reserved_mm = 0.0
                continue
            for a, b in zip(run.cells, run.cells[1:]):
                key = self.cells.boundary(a, b)
                spare = self.cap(run.layer, key) - self.usage.get((run.layer, key), 0) - self.extra.get((run.layer, key), 0)
                take = max(0, min(run.units - 1, spare))
                if take:
                    run.taken[key] = take
                    self.extra[(run.layer, key)] += take
            run.reserved_mm = sum(run.taken.values()) * self.cells.c / self.costs.meander_factor

    def _local_capacities(self, runs: list[Run], radius_mm: float = 1.0):
        self.local_max = defaultdict(int)
        for run in runs:
            if not run.local:
                for L in run.layers:
                    for (x, y) in (run.a, run.b):
                        for key, cap in self.cells.capacity_near(L, x, y, radius_mm, run.net).items():
                            run.local[(L, key)] = max(run.local.get((L, key), 0), cap)
            for k2, cap in run.local.items():
                self.local_max[k2] = max(self.local_max[k2], cap)

    def overflow(self) -> dict:
        return {k2: u - self.cap(k2[0], k2[1]) for k2, u in self.usage.items() if u > self.cap(k2[0], k2[1])}

    def crossings(self, runs: list[Run]) -> list:
        """(run index, run index, layer, shared stretch) for every crossing between two routed runs on one layer."""
        by_cell: dict = defaultdict(set)
        for k, run in enumerate(runs):
            for c in run.cells:
                by_cell[(run.layer, c)].add(k)
        pairs = set()
        for members in by_cell.values():
            if len(members) > 1:
                members = sorted(members)
                for i, a in enumerate(members):
                    for b in members[i + 1:]:
                        pairs.add((a, b))
        out = []
        for a, b in sorted(pairs):
            for stretch in path_crossings(runs[a].cells, runs[b].cells):
                out.append((a, b, runs[a].layer, stretch))
        return out

    def route(self, runs: list[Run], trace=None) -> dict:
        """Negotiate all runs; returns {"overflow": boundaries still over capacity, "contested": runs on them,
        "unrouted": runs without a path, "rounds": n}."""
        rng = random.Random(self.costs.seed)
        self.usage = defaultdict(int)
        self.extra = defaultdict(int)
        self.history = defaultdict(float)
        for run in runs:
            run.cells, run.layer, run.length_mm, run.taken, run.reserved_mm = [], None, 0.0, {}, 0.0
        self._local_capacities(runs)
        self.bundles = defaultdict(list)
        for run in runs:
            if run.group is not None:
                self.bundles[run.group].append(run)
        order = list(range(len(runs)))
        contested: set = set(order)
        rounds = 0
        t0 = time.time()
        for it in range(self.costs.iterations):
            rounds = it + 1
            present = self.costs.present * (it + 1)
            todo = [k for k in order if k in contested] if it else list(order)
            if it:
                rng.shuffle(todo)
            for k in todo:
                run = runs[k]
                if run.cells:
                    self._apply(run, -1)
                    run.cells = []
                best = self._search(run, present)
                if best is None:
                    continue
                _, run.layer, run.cells = best
                run.length_mm = self.cells.octilinear_mm(run.cells)
                self._apply(run, +1)
            self._take_room(runs)
            over_keys = self.overflow()
            contested = set()
            for k, run in enumerate(runs):
                if any((run.layer, self.cells.boundary(a, b)) in over_keys for a, b in zip(run.cells, run.cells[1:])):
                    contested.add(k)
            for k2, over in over_keys.items():
                self.history[k2] += self.costs.history * over
            # crossings: both runs are contested, each remembers the other's cells, the shared cells' boundaries
            # gain history so that one of them leaves (to another route or another layer)
            crossed = self.crossings(runs)
            for run in runs:
                run.crossed = []
            for a, b, L, stretch in crossed:
                contested.update((a, b))
                if runs[b] not in runs[a].crossed:
                    runs[a].crossed.append(runs[b])
                if runs[a] not in runs[b].crossed:
                    runs[b].crossed.append(runs[a])
                for c in stretch:
                    for key in self.cells.boundaries_of(c):
                        self.history[(L, key)] += self.costs.history * self.costs.crossing
            if trace and (it % 5 == 0 or not contested or it == self.costs.iterations - 1):
                trace(f"      plan it {it}: {sum(1 for r in runs if r.cells)}/{len(runs)} routed, "
                      f"{len(contested)} runs contested: {len(over_keys)} boundaries over capacity, {len(crossed)} crossings, "
                      f"{time.time() - t0:.1f}s")
            if not contested:
                break
        over_keys = self.overflow()
        crossed = self.crossings(runs)
        spots = []
        for (L, key), over in sorted(over_keys.items(), key=lambda kv: -kv[1])[:8]:
            kind, i, j = key
            x, y = self.cells.centre(i, j)
            spots.append((L, round(x + (self.cells.c / 2 if kind == "h" else 0), 1),
                          round(y + (self.cells.c / 2 if kind == "v" else 0), 1), over, self.cap(L, key)))
        return {"overflow": len(over_keys), "contested": len(contested), "contested_runs": sorted(contested),
                "unrouted": sum(1 for r in runs if not r.cells), "rounds": rounds, "spots": spots,
                "crossings": [(a, b, L, self.cells.centre(*stretch[0])) for a, b, L, stretch in crossed]}


def reserve_lengths(runs: list[Run], fixed_mm: dict, groups: list, factor: float) -> dict:
    """Set each run's units from its net's length deficit: for every group (members, window_mm) the net's planned
    length (its fixed copper plus its runs) is compared with the group's longest member; a net short of the window
    by d over a planned length l reserves d * factor / l extra tracks along all its runs. Returns net -> deficit."""
    planned: dict = defaultdict(float)
    for name, mm in fixed_mm.items():
        planned[name] += mm
    for run in runs:
        planned[run.net] += run.length_mm
    deficit: dict = defaultdict(float)
    for members, window in groups:
        members = [m for m in members if m in planned]
        if len(members) < 2:
            continue
        longest = max(planned[m] for m in members)
        for m in members:
            deficit[m] = max(deficit[m], longest - window - planned[m], 0.0)
    for run in runs:
        d = deficit.get(run.net, 0.0)
        run.deficit_mm = d
        run.units = 1 + (int(math.ceil(d * factor / planned[run.net])) if d > 0 and planned[run.net] > 0 else 0)
    return dict(deficit)


def plan_runs(board, region, layer_ids: list[int], track_mm: float, clearance_mm: float, runs: list[Run],
              groups: list | None = None, fixed_mm: dict | None = None, costs: PlanCosts | None = None,
              trace=None, cell_mm: float = 0.4, extra: list | None = None, grid_mm: float = 0.0) -> dict:
    """Plan ``runs`` on the board's fixed copper: a first pass at one unit each, then, when ``groups`` ask for
    matched lengths, a second pass with the length deficits reserved as extra units. Returns the statistics."""
    costs = costs or PlanCosts()
    t0 = time.time()
    fixed = Fixed(board, region, layer_ids, extra=extra)
    cells = Cells(region, layer_ids, fixed, track_mm, clearance_mm, cell_mm=cell_mm, grid_mm=grid_mm)
    stats = {"cells": (cells.nx, cells.ny), "fixed": fixed.count, "build_s": round(time.time() - t0, 1),
             "capacity": {L: cells.total_capacity(L) for L in layer_ids}, "cells_obj": cells}
    if trace:
        trace(f"      plan: {cells.nx}x{cells.ny} cells of {cell_mm} mm on {len(layer_ids)} layers, {fixed.count} fixed items, "
              f"tracks at {cells.pitch:.3f} mm, capacity per layer {[cells.total_capacity(L) for L in layer_ids]}, {stats['build_s']}s")
    planner = Planner(cells, costs)
    stats["pass1"] = planner.route(runs, trace)
    stats["pass1"]["lengths"] = [r.length_mm for r in runs]
    if groups:
        stats["deficit"] = reserve_lengths(runs, fixed_mm or {}, groups, costs.meander_factor)
        stats["units"] = Counter(r.units for r in runs)
        if trace:
            short = sorted(stats["deficit"].items(), key=lambda kv: -kv[1])[:6]
            trace(f"      plan: length reserved for {sum(1 for d in stats['deficit'].values() if d > 0)} nets, units "
                  f"{dict(sorted(stats['units'].items()))}, largest deficits "
                  + ", ".join(f"{n.split('/')[-1]} {d:.1f}" for n, d in short))
        planner = Planner(cells, costs)
        stats["pass2"] = planner.route(runs, trace)
        room: dict = defaultdict(float)
        for r in runs:
            room[r.net] += r.reserved_mm
        stats["room"] = {n: (stats["deficit"][n], room[n]) for n in stats["deficit"] if stats["deficit"][n] > 0}
        if trace:
            short = [(n, d, got) for n, (d, got) in stats["room"].items() if got < d]
            trace(f"      plan: length room for {sum(1 for n, (d, got) in stats['room'].items() if got >= d)} of "
                  f"{len(stats['room'])} nets that need it; short of room: "
                  + (", ".join(f"{n.split('/')[-1]} {got:.1f} of {d:.1f}" for n, d, got in sorted(short, key=lambda t: t[2] - t[1])[:10]) or "none"))
    stats["planner"] = planner
    return stats
