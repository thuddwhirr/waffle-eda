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

A terminal's own via fills its cell and blocks the cell's boundaries; the run has to leave the cell anyway, so the
boundaries of a run's terminal cells are reserved for it and other runs pay for crossing them.

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
        self.circles: dict[int, dict] = {L: defaultdict(list) for L in layer_ids}  # layer -> cell -> [(x, y, r)]
        self.segments: dict[int, dict] = {L: defaultdict(list) for L in layer_ids}  # layer -> cell -> [(ax, ay, bx, by, hw)]
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
                # a round pad by its radius, anything else by its bounding circle (conservative for rectangles)
                r = max(sx, sy) / 2 if pad.GetShape() in round_shapes else math.hypot(sx, sy) / 2
                for L in pad.GetLayerSet().CuStack():
                    if L in layers:
                        self._add_circle(L, x, y, r)
        for item in board.GetTracks():
            if item.GetNetname() in skip_nets:
                continue
            if item.GetClass() == "PCB_VIA":
                p = item.GetPosition()
                x, y = kb.mm(p.x), kb.mm(p.y)
                if x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1:
                    r = kb.via_diameter_mm(item) / 2
                    for L in layer_ids:
                        self._add_circle(L, x, y, r)
            else:
                L = item.GetLayer()
                if L not in layers:
                    continue
                a, b = item.GetStart(), item.GetEnd()
                ax, ay, bx, by = kb.mm(a.x), kb.mm(a.y), kb.mm(b.x), kb.mm(b.y)
                if max(ax, bx) < x0 - 1 or min(ax, bx) > x1 + 1 or max(ay, by) < y0 - 1 or min(ay, by) > y1 + 1:
                    continue
                self._add_segment(L, ax, ay, bx, by, kb.mm(item.GetWidth()) / 2)
        for (L, points, hw) in extra or []:
            if L in layers:
                for (ax, ay), (bx, by) in zip(points, points[1:]):
                    self._add_segment(L, ax, ay, bx, by, hw)

    def _key(self, x, y):
        return (int(math.floor(x / self.cell)), int(math.floor(y / self.cell)))

    def _add_circle(self, L, x, y, r):
        self.count += 1
        k = self._key(x, y)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                self.circles[L][(k[0] + dx, k[1] + dy)].append((x, y, r))

    def _add_segment(self, L, ax, ay, bx, by, hw):
        self.count += 1
        kx0, ky0 = self._key(min(ax, bx) - hw, min(ay, by) - hw)
        kx1, ky1 = self._key(max(ax, bx) + hw, max(ay, by) + hw)
        for i in range(kx0 - 1, kx1 + 2):
            for j in range(ky0 - 1, ky1 + 2):
                self.segments[L][(i, j)].append((ax, ay, bx, by, hw))

    def blocked(self, L, x, y, r) -> bool:
        """Is a track centre at (x, y) with half-width-plus-clearance r too close to fixed copper on layer L?"""
        k = self._key(x, y)
        for (cx, cy, cr) in self.circles[L].get(k, ()):
            if math.hypot(x - cx, y - cy) < cr + r:
                return True
        for (ax, ay, bx, by, hw) in self.segments[L].get(k, ()):
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
            if math.hypot(x - (ax + t * dx), y - (ay + t * dy)) < hw + r:
                return True
        return False


# --- the cell grid and its capacities ---------------------------------------------------------------------------------
class Cells:
    def __init__(self, region, layer_ids: list[int], fixed: Fixed, track_mm: float, clearance_mm: float,
                 cell_mm: float = 0.4, sample_mm: float = 0.05):
        self.x0, self.y0, x1, y1 = region
        self.c = cell_mm
        self.nx = int(math.ceil((x1 - self.x0) / cell_mm))
        self.ny = int(math.ceil((y1 - self.y0) / cell_mm))
        self.layers = layer_ids
        self.pitch = track_mm + clearance_mm
        r = track_mm / 2 + clearance_mm
        n = max(2, int(round(cell_mm / sample_mm)))
        offsets = (-cell_mm / 4, 0.0, cell_mm / 4)
        # cap_h[L][(i, j)]: boundary between (i, j) and (i + 1, j); cap_v[L][(i, j)]: between (i, j) and (i, j + 1)
        self.cap_h: dict = {}
        self.cap_v: dict = {}
        for L in layer_ids:
            ch, cv = {}, {}
            for i in range(self.nx):
                for j in range(self.ny):
                    bx = self.x0 + (i + 1) * cell_mm
                    by = self.y0 + j * cell_mm
                    if i + 1 < self.nx:  # the narrowest of three cuts: on the boundary and a quarter cell either side
                        ch[(i, j)] = min(self._tracks([not fixed.blocked(L, bx + o, by + (k + 0.5) * sample_mm, r)
                                                       for k in range(n)], sample_mm) for o in offsets)
                    bx = self.x0 + i * cell_mm
                    by = self.y0 + (j + 1) * cell_mm
                    if j + 1 < self.ny:
                        cv[(i, j)] = min(self._tracks([not fixed.blocked(L, bx + (k + 0.5) * sample_mm, by + o, r)
                                                       for k in range(n)], sample_mm) for o in offsets)
            self.cap_h[L], self.cap_v[L] = ch, cv

    def _tracks(self, free, sample_mm) -> int:
        total, run = 0, 0
        for f in free + [False]:
            if f:
                run += 1
            elif run:
                total += int(math.floor(run * sample_mm / self.pitch)) + 1
                run = 0
        return total

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
    seed: int = 1


class Planner:
    def __init__(self, cells: Cells, costs: PlanCosts | None = None):
        self.cells = cells
        self.costs = costs or PlanCosts()
        self.usage: dict = defaultdict(int)  # (layer, key) -> tracks in use (the runs themselves)
        self.extra: dict = defaultdict(int)  # (layer, key) -> tracks reserved as length room
        self.history: dict = defaultdict(float)
        self.reserved: dict = {}  # (layer, key) -> units the runs whose terminals sit beside the boundary need
        self.bundles: dict = defaultdict(list)  # group -> runs

    def cap(self, L, key) -> int:
        return max(self.cells.capacity(L, key), self.reserved.get((L, key), 0))

    def _search(self, run: Run, present: float):
        cells = self.cells
        ca, cb = cells.cell_of(*run.a), cells.cell_of(*run.b)
        tx, ty = cells.centre(*cb)
        best = None
        mates = [r for r in self.bundles.get(run.group, ()) if r is not run and r.layer is not None] if run.group is not None else []
        for L in run.layers:
            bias = self.costs.layer_bias.get(L, 0.0)
            apart = self.costs.affinity_mm * (1 - sum(1 for r in mates if r.layer == L) / len(mates)) if mates else 0.0
            dist = {ca: 0.0}
            prev = {}
            heap = [(0.0, 0, ca)]
            counter = 0
            found = None
            while heap:
                f, _, cur = heapq.heappop(heap)
                d = dist[cur]
                if cur == cb:
                    found = d
                    break
                i, j = cur
                for nxt in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                    if not (0 <= nxt[0] < cells.nx and 0 <= nxt[1] < cells.ny):
                        continue
                    key = cells.boundary(cur, nxt)
                    cap = self.cap(L, key)
                    if cap <= 0:
                        continue
                    use = self.usage.get((L, key), 0) + self.extra.get((L, key), 0)
                    over = max(0, use + 1 - cap)
                    unmet = max(0, run.units - 1 - max(0, cap - use - 1))
                    cost = cells.c + bias + present * over + self.history.get((L, key), 0.0) + self.costs.cramped_mm * unmet
                    nd = d + cost
                    if nd < dist.get(nxt, math.inf):
                        dist[nxt] = nd
                        prev[nxt] = cur
                        counter += 1
                        cx, cy = cells.centre(*nxt)
                        heapq.heappush(heap, (nd + abs(cx - tx) + abs(cy - ty), counter, nxt))
            if found is not None and (best is None or found + apart < best[0]):
                path = [cb]
                while path[-1] != ca:
                    path.append(prev[path[-1]])
                path.reverse()
                best = (found + apart, L, path)
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

    def _reserve_terminals(self, runs: list[Run]):
        self.reserved = defaultdict(int)
        for run in runs:
            for cell in {self.cells.cell_of(*run.a), self.cells.cell_of(*run.b)}:
                for key in self.cells.boundaries_of(cell):
                    for L in run.layers:
                        self.reserved[(L, key)] += 1

    def overflow(self) -> dict:
        return {k2: u - self.cap(k2[0], k2[1]) for k2, u in self.usage.items() if u > self.cap(k2[0], k2[1])}

    def route(self, runs: list[Run], trace=None) -> dict:
        """Negotiate all runs; returns {"overflow": boundaries still over capacity, "contested": runs on them,
        "unrouted": runs without a path, "rounds": n}."""
        rng = random.Random(self.costs.seed)
        self.usage = defaultdict(int)
        self.extra = defaultdict(int)
        self.history = defaultdict(float)
        for run in runs:
            run.cells, run.layer, run.length_mm, run.taken, run.reserved_mm = [], None, 0.0, {}, 0.0
        self._reserve_terminals(runs)
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
            if trace and (it % 5 == 0 or not contested or it == self.costs.iterations - 1):
                trace(f"      plan it {it}: {sum(1 for r in runs if r.cells)}/{len(runs)} routed, "
                      f"{len(contested)} runs over capacity on {len(over_keys)} boundaries, {time.time() - t0:.1f}s")
            if not contested:
                break
        over_keys = self.overflow()
        spots = []
        for (L, key), over in sorted(over_keys.items(), key=lambda kv: -kv[1])[:8]:
            kind, i, j = key
            x, y = self.cells.centre(i, j)
            spots.append((L, round(x + (self.cells.c / 2 if kind == "h" else 0), 1),
                          round(y + (self.cells.c / 2 if kind == "v" else 0), 1), over, self.cap(L, key)))
        return {"overflow": len(over_keys), "contested": len(contested), "contested_runs": sorted(contested),
                "unrouted": sum(1 for r in runs if not r.cells), "rounds": rounds, "spots": spots}


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
              trace=None, cell_mm: float = 0.4, extra: list | None = None) -> dict:
    """Plan ``runs`` on the board's fixed copper: a first pass at one unit each, then, when ``groups`` ask for
    matched lengths, a second pass with the length deficits reserved as extra units. Returns the statistics."""
    costs = costs or PlanCosts()
    t0 = time.time()
    fixed = Fixed(board, region, layer_ids, extra=extra)
    cells = Cells(region, layer_ids, fixed, track_mm, clearance_mm, cell_mm=cell_mm)
    stats = {"cells": (cells.nx, cells.ny), "fixed": fixed.count, "build_s": round(time.time() - t0, 1),
             "capacity": {L: cells.total_capacity(L) for L in layer_ids}, "cells_obj": cells}
    if trace:
        trace(f"      plan: {cells.nx}x{cells.ny} cells of {cell_mm} mm on {len(layer_ids)} layers, {fixed.count} fixed items, "
              f"capacity per layer {[cells.total_capacity(L) for L in layer_ids]}, {stats['build_s']}s")
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
