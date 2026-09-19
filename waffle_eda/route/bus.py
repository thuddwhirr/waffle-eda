"""The bus router (plan.md, M3): connects every island of every bus net after the fan-out, on the layers the
constraints allow, with layer changes only inside the packages, under KiCad's own collision test, by negotiated
congestion (the scheme of ``escape.py``).

The graph is a union of node sets: inside each package's zone (its pad array plus ``out_pitches``), the package's
own quarter-pitch lattice, so that a track between two dog-bone vias sits exactly where it fits; elsewhere a grid at
the finest quarter pitch, anchored on the first package. Nodes are joined to every node within one and a half steps,
which stitches the sets together at the zone boundaries. On the top layer inside a pad array only the half-pitch
nodes are used (a channel at a fine pitch has no slack); a via may sit only inside a package's footprint, on a
half-pitch node inside its pad array or anywhere else in the footprint. A net's terminals are its copper islands:
the pads with the escapes the fan-out gave them, and the termination pads; the router grows one tree per net from
the first island to every other, from any covered node to any covered node, so a shared net joins its two DRAM
islands wherever that is shortest, through the arrays if need be. Nothing is routed on the assumption that a
human finishes it: a net with no path is reported with what blocked it.
"""
from __future__ import annotations

import heapq
import math
import os
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace

import pcbnew

from waffle_eda.bench import bus_design
from waffle_eda.kicad import board as kb
from waffle_eda.route.lattice import Lattice
from waffle_eda.route.obstacles import Obstacles

TRACE = bool(os.environ.get("BUS_TRACE"))


@dataclass(frozen=True)
class BusRules:
    track_mm: float
    clearance_mm: float
    via_mm: float
    via_drill_mm: float
    layers: tuple[str, ...]  # copper layers the bus may use, by name (the top layer included when allowed)
    hole_clearance_mm: float = 0.0
    out_pitches: float = 1.5  # the zone around a package's pad array that uses the package's own lattice
    margin_mm: float = 6.0  # routing region beyond the packages' footprints
    spacing_mm: float = 0.0  # extra room the negotiation keeps between bus nets outside the pad arrays, for tuning
    in_pad_packages: tuple[str, ...] = ()  # packages whose balls take a via in the pad (filled and capped)
    # D32, measured from the references: inside a package's pad array every via of the reference sits at one of a
    # few offsets from its ball (on it, for an in-pad package; on a diagonal corner, for a dog-bone one), the same
    # few for every ball, so the vias form a regular field with predictable channels between them. This maps a
    # package to the offsets its vias may take, in pitches, from the ball whose cell they are in; an empty tuple
    # forbids a via between the balls altogether, and a package not named here is unrestricted.
    ball_via_offsets: dict = field(default_factory=dict)
    # D32: the references run transit on the top layer too (122 mm on ButterStick, 170 on LogicBone), so this is
    # off by default. Set it to limit a net's top-layer copper to within that distance of one of its own pads.
    top_escape_mm: float = math.inf


@dataclass
class Costs:
    via_mm: float = 1.5  # a via costs this much track
    other_layer_mm: float = 0.0
    iterations: int = 60
    present: float = 0.6
    history: float = 0.4
    max_vias: int = 2
    # D32: the references keep a net's layer changes few (ButterStick at most 3 per net, LogicBone 4) and Lattice's
    # own checklist caps a DDR data net at 3 (D30). 0 leaves the budget to ``max_vias`` per leg, which is what the
    # synthetic cases use; a positive number is the whole net's budget, the copper it already carries included.
    max_vias_per_net: int = 0
    corridor_mm: float = 3.0  # a net's search stays within its islands' bounding box grown by this much
    pop_budget: int = 150000  # states a single search may settle before it is called off (runs are bounded)
    repair_partners: int = 6  # nets ripped up around a stranded net in the final pass
    detour_min_mm: float = 3.0  # a net shorter than its window by more than this is re-routed through a detour
    detour_candidates: int = 12  # detour points tried per net
    waypoint_deficit_mm: float = math.inf  # a net this far below its window gets a waypoint before the negotiation
    repair_radius_mm: tuple = (1.5, 3.0)  # a stranded net's neighbourhood is re-packed within these radii
    repair_rounds: int = 2  # passes over the stranded nets (a re-packing can free what another needs)
    repair_negotiation: int = 12  # rounds of the local negotiation around a stranded net
    reroute_all: bool = False  # every round re-routes every net, not only the contested ones
    stall_rounds: int = 4
    max_radius_hops: int = 4
    max_radius_mm: float = 4.0  # the widest rip-up around a stuck pair's paths, in the fallback by distance
    seed: int = 1


@dataclass
class BusResult:
    routed: dict = field(default_factory=dict)  # net -> summary
    failed: dict = field(default_factory=dict)  # net -> diagnosis
    counts: Counter = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return len(self.routed) + len(self.failed)

    def summary(self) -> str:
        return f"{len(self.routed)}/{self.total} nets routed; " + ", ".join(f"{k} {v}" for k, v in sorted(self.counts.items()))


# --- the graph ---------------------------------------------------------------------------------------------------
class BusGraph:
    def __init__(self, board, packages: list[Lattice], rules: BusRules, layer_ids: list[int], top: int,
                 region_mm: tuple[float, float, float, float], footprints: dict):
        self.board, self.packages, self.rules, self.layers, self.top = board, packages, rules, layer_ids, top
        self.region = region_mm
        self.step = min(p.pitch for p in packages) / 4
        self.u = self.step / 2  # occupancy unit
        self.footprints = footprints  # package reference -> PackageInfo (footprint bbox for the via rule)
        self.xy: list[tuple[float, float]] = []
        self.index: dict[tuple[int, int], int] = {}  # quantised (x, y) -> node id
        self.zone: list[int] = []  # package index or -1
        self.half: list[bool] = []  # a half-pitch node of its zone's lattice (or a global node)
        self.in_array: list[bool] = []  # inside a pad array (pads plus half a pitch)
        self.pad_net: dict[int, str] = {}
        self.via_site: list[bool] = []
        self._build_nodes()
        self._build_adjacency()
        tw, clr, vr = rules.track_mm, rules.clearance_mm, rules.via_mm / 2
        self.t_near = self._offsets(tw + clr)
        self.t_spaced = self._offsets(tw + clr + rules.spacing_mm)  # between bus nets outside the pad arrays
        self.v_for_t = self._offsets(vr + clr + tw / 2)
        self.v_for_v = self._offsets(2 * vr + clr)
        self.arrays = [(lat.x0 - lat.pitch / 2, lat.y0 - lat.pitch / 2, lat.X(lat.cols - 1) + lat.pitch / 2,
                        lat.Y(lat.rows - 1) + lat.pitch / 2) for lat in packages]
        self.edge_cache: dict = {}
        self.via_cache: dict = {}
        self._top_cache: dict = {}
        self.sample_cache: dict = {}
        self.committed = Obstacles(board, items=[])

    # nodes ------------------------------------------------------------------------------------------------------
    def _key(self, x: float, y: float) -> tuple[int, int]:
        return (int(round(x / 0.001)), int(round(y / 0.001)))  # 1 um

    def in_any_array(self, x: float, y: float) -> bool:
        """Within half a pitch of a pad of a package: where the fan-out lives and spacing cannot be kept."""
        for lat in self.packages:
            fi, fj = (x - lat.x0) / lat.pitch, (y - lat.y0) / lat.pitch
            i, j = round(fi), round(fj)
            if abs(fi - i) <= 0.5 + 1e-9 and abs(fj - j) <= 0.5 + 1e-9 and (i, j) in lat.by_index:
                return True
        return False

    def _add(self, x, y, zone, half, in_array, via_site) -> int:
        k = self._key(x, y)
        if k in self.index:
            i = self.index[k]
            if in_array and not self.in_array[i]:  # a node of one lattice inside another package's array
                self.in_array[i] = True
                self.half[i] = self.half[i] and half
                self.via_site[i] = self.via_site[i] and via_site
            return i
        i = len(self.xy)
        self.index[k] = i
        self.xy.append((x, y))
        self.zone.append(zone)
        self.half.append(half)
        self.in_array.append(in_array)
        self.via_site.append(via_site)
        return i

    def _in_footprint(self, x, y) -> bool:
        return any(fp.in_footprint_mm(x, y) for fp in self.footprints.values())

    def _build_nodes(self):
        rx0, ry0, rx1, ry1 = self.region
        zones = []
        for pi, lat in enumerate(self.packages):
            m = self.rules.out_pitches * lat.pitch
            zones.append((lat.x0 - m, lat.y0 - m, lat.X(lat.cols - 1) + m, lat.Y(lat.rows - 1) + m))
            q = lat.pitch / 4
            i0, i1 = -int(round(m / q)), (lat.cols - 1) * 4 + int(round(m / q))
            j0, j1 = -int(round(m / q)), (lat.rows - 1) * 4 + int(round(m / q))
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    x, y = lat.x0 + i * q, lat.y0 + j * q
                    if not (rx0 <= x <= rx1 and ry0 <= y <= ry1):
                        continue
                    half = i % 2 == 0 and j % 2 == 0
                    in_array = -2 <= i <= (lat.cols - 1) * 4 + 2 and -2 <= j <= (lat.rows - 1) * 4 + 2
                    on_pad = i % 4 == 0 and j % 4 == 0 and (i // 4, j // 4) in lat.by_index
                    in_pad = on_pad and lat.reference in self.rules.in_pad_packages
                    via = self._in_footprint(x, y) and (not in_array or (half and (not on_pad or in_pad)))
                    node = self._add(x, y, pi, half, in_array, via)
                    if on_pad:
                        self.pad_net[node] = lat.by_index[(i // 4, j // 4)].net
        # D32: inside a package's array a via may only take the offsets from its ball that the package's escape
        # style uses, so the via field stays regular and the channels between the balls stay where the other nets
        # expect them
        for lat in self.packages:
            allowed = self.rules.ball_via_offsets.get(lat.reference)
            if allowed is None:
                continue
            allowed = {(round(di, 2), round(dj, 2)) for di, dj in allowed}
            for node, (x, y) in enumerate(self.xy):
                if not self.via_site[node]:
                    continue
                # a node on the corner between four balls lies in all four cells: the style has to allow the offset
                # from every one of them, or the via would be in a channel one of those balls needs
                for (_, _, _, di, dj) in bus_design.ball_cells(lat, x, y):
                    if (round(di, 2), round(dj, 2)) not in allowed:
                        self.via_site[node] = False
                        break
        self.zones = zones
        g = self.step
        lat0 = self.packages[0]
        nx0 = int(math.floor((rx0 - lat0.x0) / g))
        nx1 = int(math.ceil((rx1 - lat0.x0) / g))
        ny0 = int(math.floor((ry0 - lat0.y0) / g))
        ny1 = int(math.ceil((ry1 - lat0.y0) / g))
        for i in range(nx0, nx1 + 1):
            for j in range(ny0, ny1 + 1):
                x, y = lat0.x0 + i * g, lat0.y0 + j * g
                if not (rx0 <= x <= rx1 and ry0 <= y <= ry1):
                    continue
                if any(zx0 <= x <= zx1 and zy0 <= y <= zy1 for zx0, zy0, zx1, zy1 in zones):
                    continue
                self._add(x, y, -1, True, False, self._in_footprint(x, y))

    def _build_adjacency(self):
        cell = self.step
        buckets: dict = defaultdict(list)
        for i, (x, y) in enumerate(self.xy):
            buckets[(int(math.floor(x / cell)), int(math.floor(y / cell)))].append(i)
        self.adj: list[list[tuple[int, float]]] = [[] for _ in self.xy]
        r = 1.45 * self.step
        r2 = r * r
        for i, (x, y) in enumerate(self.xy):
            cx, cy = int(math.floor(x / cell)), int(math.floor(y / cell))
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    for j in buckets.get((cx + dx, cy + dy), ()):
                        if j == i:
                            continue
                        ox, oy = self.xy[j]
                        d2 = (ox - x) ** 2 + (oy - y) ** 2
                        if d2 <= r2:
                            self.adj[i].append((j, math.sqrt(d2)))
        self.buckets = buckets
        # the top layer inside a pad array moves between half-pitch nodes (two steps): from a pad to a gap or a
        # channel and on along the channels, as the escape router does; plus the one-step moves that leave the array
        self.adj_top: dict[int, list] = {}
        r2t = (1.45 * 2 * self.step) ** 2
        for i, (x, y) in enumerate(self.xy):
            if not self.in_array[i] or not self.half[i]:
                continue
            out = [(j, d) for j, d in self.adj[i] if not self.in_array[j]]
            cx, cy = int(math.floor(x / cell)), int(math.floor(y / cell))
            for dx in (-3, -2, -1, 0, 1, 2, 3):
                for dy in (-3, -2, -1, 0, 1, 2, 3):
                    for j in buckets.get((cx + dx, cy + dy), ()):
                        if j == i or not self.half[j] or not self.in_array[j] or self.zone[j] != self.zone[i]:
                            continue
                        ox, oy = self.xy[j]
                        d2 = (ox - x) ** 2 + (oy - y) ** 2
                        if d2 <= r2t and d2 > 1e-9:
                            out.append((j, math.sqrt(d2)))
            self.adj_top[i] = out

    def nodes_near(self, x: float, y: float, radius: float):
        cell = self.step
        cx, cy = int(math.floor(x / cell)), int(math.floor(y / cell))
        n = int(math.ceil(radius / cell)) + 1
        r2 = radius * radius
        for dx in range(-n, n + 1):
            for dy in range(-n, n + 1):
                for j in self.buckets.get((cx + dx, cy + dy), ()):
                    ox, oy = self.xy[j]
                    if (ox - x) ** 2 + (oy - y) ** 2 <= r2:
                        yield j

    def _offsets(self, dist_mm: float) -> tuple:
        r = int(dist_mm / self.u) + 1
        return tuple((dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                     if math.hypot(dx, dy) * self.u < dist_mm - 1e-9)

    def top_allowance(self, net_name: str) -> set | None:
        """The nodes where this net may put top-layer copper under ``rules.top_escape_mm``: those within that
        distance of one of its own pads, which is the escape and nothing else (D31). None when the rule is off."""
        if self.rules.top_escape_mm == math.inf:
            return None
        cached = self._top_cache.get(net_name)
        if cached is None:
            cached = set()
            for fp in self.board.GetFootprints():
                for pad in fp.Pads():
                    if pad.GetNetname() == net_name:
                        p = pad.GetPosition()
                        cached.update(self.nodes_near(kb.mm(p.x), kb.mm(p.y), self.rules.top_escape_mm))
            self._top_cache[net_name] = cached
        return cached

    def top_ok(self, node: int, net_name: str = "") -> bool:
        """Where a top-layer track may run: anywhere outside the pad arrays; inside, the half-pitch nodes that are
        not another net's pad (the net's own pad is where its route starts or ends). Under ``top_escape_mm`` the
        net must also stay within reach of its own pads, so the top layer carries escapes and not transit."""
        if self.in_array[node] and not (self.half[node] and self.pad_net.get(node, net_name) == net_name):
            return False
        allowed = self.top_allowance(net_name)
        return allowed is None or node in allowed

    # geometry -----------------------------------------------------------------------------------------------------
    def _track(self, layer, a: int, b: int, net):
        t = pcbnew.PCB_TRACK(self.board)
        ax, ay = self.xy[a]
        bx, by = self.xy[b]
        t.SetStart(pcbnew.VECTOR2I(kb.nm(ax), kb.nm(ay)))
        t.SetEnd(pcbnew.VECTOR2I(kb.nm(bx), kb.nm(by)))
        t.SetWidth(kb.nm(self.rules.track_mm))
        t.SetLayer(layer)
        t.SetNet(net)
        return t

    def _via(self, node: int, net):
        v = pcbnew.PCB_VIA(self.board)
        x, y = self.xy[node]
        v.SetPosition(pcbnew.VECTOR2I(kb.nm(x), kb.nm(y)))
        v.SetDrill(kb.nm(self.rules.via_drill_mm))
        kb.set_via_diameter(v, self.rules.via_mm)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(net)
        return v

    def _edge_hits(self, layer, a, b, net, obs: Obstacles) -> frozenset:
        key = (layer, a, b) if a <= b else (layer, b, a)
        hits = self.edge_cache.get(key)
        if hits is None:
            hits = obs.hits(self._track(layer, a, b, net), self.rules.clearance_mm,
                            hole_clearance_mm=self.rules.hole_clearance_mm)
            self.edge_cache[key] = hits
        return hits

    def segment_clear(self, layer, a, b, net, obs: Obstacles, committed: bool = True) -> bool:
        name = net.GetNetname()
        if not all(n == name for _, n in self._edge_hits(layer, a, b, net, obs)):
            return False
        if committed and self.committed.count:
            return self.committed.clear(self._track(layer, a, b, net), self.rules.clearance_mm,
                                        hole_clearance_mm=self.rules.hole_clearance_mm) is None
        return True

    def segment_blocker(self, layer, a, b, net, obs: Obstacles) -> str:
        name = net.GetNetname()
        hits = [f"{cls} of {n!r}" for cls, n in sorted(self._edge_hits(layer, a, b, net, obs)) if n != name]
        if not hits and self.committed.count:
            other = self.committed.clear(self._track(layer, a, b, net), self.rules.clearance_mm,
                                         hole_clearance_mm=self.rules.hole_clearance_mm)
            if other is not None:
                hits = [f"our {other.GetClass()} of {other.GetNetname()!r}"]
        return f"{self.board.GetLayerName(layer)}: {hits[0]}" if hits else "?"

    def via_clear(self, node, net, obs: Obstacles, committed: bool = True) -> bool:
        hits = self.via_cache.get(node)
        if hits is None:
            hits = obs.hits(self._via(node, net), self.rules.clearance_mm,
                            hole_clearance_mm=self.rules.hole_clearance_mm)
            self.via_cache[node] = hits
        name = net.GetNetname()
        if not all(n == name for _, n in hits):
            return False
        if committed and self.committed.count:
            return self.committed.clear(self._via(node, net), self.rules.clearance_mm,
                                        hole_clearance_mm=self.rules.hole_clearance_mm) is None
        return True

    def path_clear(self, path, vias, net, obs: Obstacles) -> bool:
        """A whole path against the fixed and the committed copper (exact)."""
        prev = None
        for layer, node in path:
            if prev is not None and prev[0] == layer and not self.segment_clear(layer, prev[1], node, net, obs):
                return False
            prev = (layer, node)
        return all(self.via_clear(node, net, obs) for node in vias)

    # occupancy sampling -------------------------------------------------------------------------------------------
    def qkey(self, x: float, y: float) -> tuple[int, int]:
        return (int(round(x / self.u)), int(round(y / self.u)))

    def samples(self, a: int, b: int) -> tuple:
        """Points every occupancy unit along the edge a -> b, the start excluded (cached per edge)."""
        key = (a, b)
        out = self.sample_cache.get(key)
        if out is None:
            ax, ay = self.xy[a]
            bx, by = self.xy[b]
            n = max(1, int(round(math.hypot(bx - ax, by - ay) / self.u)))
            out = tuple(self.qkey(ax + (bx - ax) * k / n, ay + (by - ay) * k / n) for k in range(1, n + 1))
            self.sample_cache[key] = out
        return out


class Occupancy:
    """Which nets are too close to each point of the occupancy grid, kept incrementally: adding a path spreads its
    samples over the neighbourhood that another track (``tn``) or another via (``tv``) may not enter, and its vias
    over the neighbourhoods for tracks (``vn``) and vias (``vv``). A query is then one lookup per sample. Track
    samples outside the pad arrays spread by the spaced neighbourhood so that tuning has room (BusRules.spacing_mm)."""

    def __init__(self, g: BusGraph):
        self.g = g
        self.tn: dict = defaultdict(Counter)  # (layer, x, y) -> nets whose tracks are too close for a track here
        self.tv: dict = defaultdict(Counter)  # (layer, x, y) -> nets whose tracks are too close for a via here
        self.vn: dict = defaultdict(Counter)  # (x, y) -> nets whose vias are too close for a track here
        self.vv: dict = defaultdict(Counter)  # (x, y) -> nets whose vias are too close for a via here

    def path_samples(self, path) -> set:
        out = set()
        prev = None
        for layer, node in path:
            x, y = self.g.xy[node]
            out.add((layer,) + self.g.qkey(x, y))
            if prev is not None and prev[0] == layer:
                for k in self.g.samples(prev[1], node):
                    out.add((layer,) + k)
            prev = (layer, node)
        return out

    def _spread(self, counter_map, key, offsets, name, sign):
        layer, x, y = key if len(key) == 3 else (None,) + key
        for dx, dy in offsets:
            k = (layer, x + dx, y + dy) if layer is not None else (x + dx, y + dy)
            c = counter_map[k]
            c[name] += sign
            if c[name] <= 0:
                del c[name]
                if not c:
                    del counter_map[k]

    def add(self, path, vias, name: str, sign: int = 1):
        g = self.g
        for key in self.path_samples(path):
            layer, x, y = key
            spaced = g.t_spaced is not g.t_near and not g.in_any_array(x * g.u, y * g.u)
            self._spread(self.tn, key, g.t_spaced if spaced else g.t_near, name, sign)
            self._spread(self.tv, key, g.v_for_t, name, sign)
        for node in set(vias):
            k = g.qkey(*g.xy[node])
            self._spread(self.vn, k, g.v_for_t, name, sign)
            self._spread(self.vv, k, g.v_for_v, name, sign)

    def near_sample(self, layer, x, y) -> set:
        out: set = set()
        c = self.tn.get((layer, x, y))
        if c:
            out |= c.keys()
        c = self.vn.get((x, y))
        if c:
            out |= c.keys()
        return out

    def near_step(self, layer, a, b) -> set:
        out: set = set()
        tn, vn = self.tn, self.vn
        for x, y in self.g.samples(a, b):
            c = tn.get((layer, x, y))
            if c:
                out |= c.keys()
            c = vn.get((x, y))
            if c:
                out |= c.keys()
        return out

    def near_via(self, node) -> set:
        g = self.g
        k = g.qkey(*g.xy[node])
        out: set = set()
        c = self.vv.get(k)
        if c:
            out |= c.keys()
        for layer in g.layers:
            c = self.tv.get((layer,) + k)
            if c:
                out |= c.keys()
        return out

    def conflicts(self, path, vias, name: str) -> list:
        out = [("t",) + key for key in self.path_samples(path) if self.near_sample(*key) - {name}]
        out += [("v", node) for node in set(vias) if self.near_via(node) - {name}]
        return out


class Context:
    """Costs on the occupancy for one search. In the final pass (``hard``) the exact collision test against the
    committed copper decides; the occupancy blocks only when a spacing between bus nets is asked for, because the
    occupancy is an approximation (a sample every eighth of a pitch) and would refuse paths the geometry allows."""

    def __init__(self, occ: Occupancy, history: dict, present: float, hard: bool = False):
        self.occ, self.history, self.present, self.hard = occ, history, present, hard
        self.covers_committed = hard and occ.g.rules.spacing_mm >= occ.g.u + 1e-9
        self.quiet = not history and present == 0.0 and not self.covers_committed  # nothing to look up

    def step_cost(self, layer, a, b) -> float | None:
        """None when the step is too close to another bus net under the spacing (final pass only)."""
        if self.quiet:
            return 0.0
        if self.hard:
            if self.covers_committed and self.occ.near_step(layer, a, b):
                return None
            n = 0
        else:
            n = len(self.occ.near_step(layer, a, b)) if self.present else 0
        h = self.history
        hist = 0.0
        if h:
            for k in self.occ.g.samples(a, b):
                v = h.get(("t", layer) + k)
                if v is not None and v > hist:
                    hist = v
        return hist + self.present * n

    def via_cost(self, node) -> float | None:
        if self.quiet:
            return 0.0
        if self.hard:
            if self.covers_committed and self.occ.near_via(node):
                return None
            n = 0
        else:
            n = len(self.occ.near_via(node)) if self.present else 0
        return self.history.get(("v", node), 0.0) + self.present * n


# --- islands: the copper a net already has, as covered nodes per layer ---------------------------------------------
def _islands(board, net_name: str, g: BusGraph, layer_ids: set[int]) -> list[dict]:
    """Connected groups of the net's pads, tracks and vias, each with the set of (layer, node) it covers."""
    items = []  # (kind, item)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() == net_name:
                items.append(("pad", pad))
    for t in board.GetTracks():
        if t.GetNetname() == net_name:
            items.append(("via" if t.GetClass() == "PCB_VIA" else "track", t))
    n = len(items)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    def ends(kind, item):
        if kind == "track":
            a, b = item.GetStart(), item.GetEnd()
            return [(kb.mm(a.x), kb.mm(a.y)), (kb.mm(b.x), kb.mm(b.y))]
        p = item.GetPosition()
        return [(kb.mm(p.x), kb.mm(p.y))]

    def radius(kind, item):
        if kind == "track":
            return kb.mm(item.GetWidth()) / 2
        if kind == "via":
            return kb.via_diameter_mm(item) / 2
        return max(kb.mm(item.GetSize().x), kb.mm(item.GetSize().y)) / 2

    def layers_of(kind, item):
        if kind == "track":
            return {item.GetLayer()}
        if kind == "via":
            return set(layer_ids)
        return {L for L in item.GetLayerSet().CuStack()} & set(layer_ids)

    pts = [ends(k, it) for k, it in items]
    for i in range(n):
        ki, iti = items[i]
        for j in range(i + 1, n):
            kj, itj = items[j]
            if ki == "track" and kj == "track" and iti.GetLayer() != itj.GetLayer():
                continue
            if ki == "pad" and kj == "pad":
                continue
            tol = 0.001 + (radius(ki, iti) if ki != "track" else 0) + (radius(kj, itj) if kj != "track" else 0)
            if ki == "track" and kj == "track":
                tol = 0.001
            if any(math.hypot(p[0] - q[0], p[1] - q[1]) <= tol for p in pts[i] for q in pts[j]):
                union(i, j)
    groups: dict = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    out = []
    for members in groups.values():
        covered: set = set()
        kinds = Counter()
        for i in members:
            kind, item = items[i]
            kinds[kind] += 1
            r = radius(kind, item) + 1e-6
            lays = layers_of(kind, item)
            if kind == "track":
                (ax, ay), (bx, by) = pts[i]
                steps = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / (g.step / 2))))
                for k in range(steps + 1):
                    x, y = ax + (bx - ax) * k / steps, ay + (by - ay) * k / steps
                    for node in g.nodes_near(x, y, r):
                        for L in lays:
                            covered.add((L, node))
            else:
                x, y = pts[i][0]
                for node in g.nodes_near(x, y, r):
                    for L in lays:
                        covered.add((L, node))
        out.append({"members": members, "covered": covered, "kinds": dict(kinds),
                    "pads": [items[i][1] for i in members if items[i][0] == "pad"]})
    # the order of the board's tracks depends on the order they were added in, which a set of net names upstream
    # can vary from one process to the next; the islands are ordered by their geometry so that the tree, and with
    # it the negotiation, is the same in every run
    out.sort(key=lambda isl: (-len(isl["covered"]), min(p for m in isl["members"] for p in pts[m])))
    return out


# --- the search ------------------------------------------------------------------------------------------------------
def _search(g: BusGraph, net, sources: set, targets: set, costs: Costs, ctx: Context, obs: Obstacles,
            corridor: tuple[float, float, float, float] | None = None, avoid: frozenset = frozenset(),
            same_layer: bool = False, allowed: set | None = None):
    """Multi-source A* from any (layer, node) in ``sources`` to any in ``targets``, inside ``corridor`` (mm).
    ``avoid`` holds (layer, node) pairs the path may not enter (a detour's first leg, so the second cannot retrace
    it and count the same copper twice)."""
    xs = [g.xy[n][0] for _, n in targets]
    ys = [g.xy[n][1] for _, n in targets]
    tx0, tx1, ty0, ty1 = min(xs), max(xs), min(ys), max(ys)
    if corridor is None:
        corridor = g.region
    cx0, cy0, cx1, cy1 = corridor
    xy = g.xy
    net_name = net.GetNetname()

    def h(node):
        x, y = g.xy[node]
        dx = tx0 - x if x < tx0 else (x - tx1 if x > tx1 else 0.0)
        dy = ty0 - y if y < ty0 else (y - ty1 if y > ty1 else 0.0)
        return math.hypot(dx, dy)

    dist = {}
    prev = {}
    heap = []
    counter = 0
    _dbg = os.environ.get("BUS_DEBUG_SEARCH") == net_name.split("/")[-1]
    if _dbg:
        print(f"SEARCH {net_name} sources {sorted(sources)[:8]} targets {sorted(targets)[:8]} corridor {corridor}", flush=True)
        print(f"SEARCH src-order {list(sources)[:12]}", flush=True)
    for layer, node in sources:
        state = (layer, node, 0)
        dist[state] = 0.0
        prev[state] = None
        heapq.heappush(heap, (h(node), counter, state))
        counter += 1
    blockers: Counter = Counter()
    goal = None
    target_nodes = defaultdict(set)
    for layer, node in targets:
        target_nodes[node].add(layer)
    pops = 0
    while heap:
        f, _, cur = heapq.heappop(heap)
        d = dist[cur]
        if f > d + h(cur[1]) + 1e-9:
            continue
        pops += 1
        if _dbg and pops <= 40:
            print(f"SEARCH pop {pops} {cur} f={f:.4f} d={d:.4f}", flush=True)
        if pops > costs.pop_budget:
            blockers[f"search budget of {costs.pop_budget} states spent"] += 1
            return None, blockers
        layer, node, nvias = cur
        if layer in target_nodes.get(node, ()):
            goal = cur
            break
        on_top = layer == g.top
        edges = g.adj_top.get(node, g.adj[node]) if on_top else g.adj[node]
        if on_top and node in g.adj_top:
            # a half-pitch node inside an array may also step straight onto a target on a quarter-pitch node next to
            # it: a via sitting off the half-pitch lattice (the references' hollow vias do) is reached that way
            extra = [(nxt, ln) for nxt, ln in g.adj[node] if layer in target_nodes.get(nxt, ())]
            if extra:
                edges = list(edges) + extra
        for nxt, length in edges:
            nx, ny = xy[nxt]
            if nx < cx0 or nx > cx1 or ny < cy0 or ny > cy1:
                continue
            if allowed is not None and nxt not in allowed:
                continue
            if on_top and not g.top_ok(nxt, net_name) and layer not in target_nodes.get(nxt, ()):
                continue  # a target node (the island's own copper) may always be entered
            if avoid and (layer, nxt) in avoid:
                continue
            # the fixed copper first (cached per edge), then the other bus nets (occupancy); with spacing kept by
            # the occupancy (sampled every u, a slack of u/2 a side) a step it admits is already clear of the
            # committed bus copper whenever the spacing exceeds that slack
            if not g.segment_clear(layer, node, nxt, net, obs, committed=not ctx.covers_committed):
                blockers[g.segment_blocker(layer, node, nxt, net, obs)] += 1
                continue
            extra = ctx.step_cost(layer, node, nxt)
            if extra is None:
                blockers["spacing to another bus net"] += 1
                continue
            nd = d + length + extra
            state = (layer, nxt, nvias)
            if nd < dist.get(state, math.inf):
                dist[state] = nd
                prev[state] = cur
                counter += 1
                heapq.heappush(heap, (nd + h(nxt), counter, state))
        if (not same_layer and nvias < costs.max_vias and g.via_site[node]
                and g.pad_net.get(node, net_name) == net_name and g.via_clear(node, net, obs)):
            extra = ctx.via_cost(node)
            if extra is None:
                continue
            vc = costs.via_mm + extra
            for other in g.layers:
                if other == layer or (avoid and (other, node) in avoid):
                    continue
                state = (other, node, nvias + 1)
                nd = d + vc
                if nd < dist.get(state, math.inf):
                    dist[state] = nd
                    prev[state] = cur
                    counter += 1
                    heapq.heappush(heap, (nd + h(node), counter, state))
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


def _corridor(g: BusGraph, islands: list[dict], margin_mm: float) -> tuple[float, float, float, float]:
    xs = [g.xy[n][0] for isl in islands for _, n in isl["covered"]]
    ys = [g.xy[n][1] for isl in islands for _, n in isl["covered"]]
    return (min(xs) - margin_mm, min(ys) - margin_mm, max(xs) + margin_mm, max(ys) + margin_mm)


def _route_net(g: BusGraph, net, islands: list[dict], costs: Costs, ctx: Context, obs: Obstacles,
               waypoint: int | None = None, vias_used: int = 0):
    """Grow a tree over the islands: connect the largest island to the nearest other, repeat; with ``waypoint``
    the tree first goes from the largest island to that node (a detour that adds length). ``vias_used`` is what
    the net's own copper already spends of ``costs.max_vias_per_net``. Returns (list of (layer_nodes, vias)
    segments, None) or (None, diagnosis)."""
    if len(islands) < 2:
        return [], None
    budget = costs.max_vias_per_net - vias_used if costs.max_vias_per_net else None

    def leg_costs(spent: int) -> Costs:
        """The via budget left for one leg: the lesser of the per-leg limit and what the net has left."""
        if budget is None:
            return costs
        left = max(0, budget - spent)
        return costs if left >= costs.max_vias else replace(costs, max_vias=left)
    corridor = _corridor(g, islands, costs.corridor_mm)
    order = sorted(range(len(islands)), key=lambda i: -len(islands[i]["covered"]))
    connected: set = set(islands[order[0]]["covered"])
    done = {order[0]}
    segments = []
    def centre(nodes):
        xs = [g.xy[n][0] for _, n in nodes]
        ys = [g.xy[n][1] for _, n in nodes]
        return (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else (0.0, 0.0)

    if waypoint is not None:
        # the detour leaves from whichever island can reach the waypoint (largest first: a DRAM pad walled in by
        # the other nets' copper often cannot, while the FPGA's fan-out can), then continues from the waypoint only,
        # never retracing the first leg, to the island nearest the waypoint: otherwise the detour would be a stub
        # (or the same copper twice) rather than a longer route
        wx, wy = g.xy[waypoint]
        cx0, cy0, cx1, cy1 = corridor
        corridor = (min(cx0, wx - costs.corridor_mm), min(cy0, wy - costs.corridor_mm),
                    max(cx1, wx + costs.corridor_mm), max(cy1, wy + costs.corridor_mm))
        targets = {(L, waypoint) for L in g.layers}
        last = {"why": "no path to the detour point", "blockers": Counter()}
        for start in order:
            if not islands[start]["covered"]:
                continue
            sources = set(islands[start]["covered"])
            # the legs stay inside the corridor: a waypoint it cannot reach is a poor one, and exhausting the whole
            # region (packed with the board's other copper) costs the full search budget each time
            path, vias = _search(g, net, sources, targets, leg_costs(0), ctx, obs, corridor)
            if path is None:
                last = {"why": "no path to the detour point", "blockers": vias}
                continue
            remaining = [i for i in range(len(islands)) if i != start and islands[i]["covered"]]
            if not remaining:
                return None, {"why": "an island covers no routable node", "blockers": Counter()}
            nearest = min(remaining, key=lambda i: math.hypot(centre(islands[i]["covered"])[0] - wx,
                                                              centre(islands[i]["covered"])[1] - wy))
            avoid = frozenset(path[:-1]) | frozenset(sources)
            path2, vias2 = _search(g, net, {path[-1]}, islands[nearest]["covered"], leg_costs(len(vias)), ctx, obs,
                                   corridor, avoid=avoid)
            if path2 is None:
                last = {"why": "no path from the detour point onwards", "blockers": vias2}
                continue
            done = {start, nearest}
            connected = sources | set(path) | set(path2) | set(islands[nearest]["covered"])
            segments = [(path, vias), (path2, vias2)]
            break
        else:
            return None, last

    while len(done) < len(islands):
        if not connected:
            return None, {"why": "an island covers no routable node", "blockers": Counter()}
        cx, cy = centre(connected)
        remaining = [i for i in range(len(islands)) if i not in done and islands[i]["covered"]]
        if not remaining:
            return None, {"why": "an island covers no routable node", "blockers": Counter()}
        nearest = min(remaining, key=lambda i: math.hypot(centre(islands[i]["covered"])[0] - cx,
                                                          centre(islands[i]["covered"])[1] - cy))
        targets = islands[nearest]["covered"]
        path, second = _search(g, net, connected, targets, leg_costs(sum(len(v) for _, v in segments)), ctx, obs,
                               corridor)
        if path is None:  # the corridor is a speed-up, not a rule: the whole region gets a try before failing
            path, second = _search(g, net, connected, targets, leg_costs(sum(len(v) for _, v in segments)), ctx,
                                   obs, None)
        if path is None:
            pads = [pcbnew.Cast_to_FOOTPRINT(p.GetParent()).GetReference() + "." + p.GetNumber()
                    for p in islands[nearest]["pads"]]
            return None, {"why": f"no path from the connected copper to the island of {pads or 'copper'} "
                                 f"({len(islands) - len(done)} island(s) left)", "blockers": second}
        done.add(nearest)
        connected |= islands[nearest]["covered"]
        connected |= set(path)
        segments.append((path, second))
    return segments, None


def _route_net_planned(g: BusGraph, net, islands: list[dict], plan: list, costs: Costs, ctx: Context,
                       obs: Obstacles):
    """Route the links of a plan: each is (x_a, y_a, x_b, y_b, layer_id), a run on one layer between two terminals
    of the net (a pad or a via the board already carries), as a reference board decided it. The terminals' nodes
    come from the net's islands (the copper it already has); the path between them is what is searched for."""
    covered: set = set()
    for isl in islands:
        covered |= isl["covered"]
    segments = []
    for link in plan:
        (ax, ay, bx, by, layer) = link[:5]
        band = link[5] if len(link) > 5 else None  # (polyline, half-width): the reference's own route, widened
        r = g.step * 1.5
        sources = {(layer, n) for n in g.nodes_near(ax, ay, r) if (layer, n) in covered}
        targets = {(layer, n) for n in g.nodes_near(bx, by, r) if (layer, n) in covered}
        if not sources or not targets:
            which = f"({ax:.2f}, {ay:.2f})" if not sources else f"({bx:.2f}, {by:.2f})"
            return None, {"why": f"no node of the net's copper on {g.board.GetLayerName(layer)} at {which}",
                          "blockers": Counter()}
        m = costs.corridor_mm
        corridor = (min(ax, bx) - m, min(ay, by) - m, max(ax, bx) + m, max(ay, by) + m)
        allowed = None
        if band is not None:
            points, half = band
            allowed = {n for _, n in sources} | {n for _, n in targets}
            for (px, py), (qx, qy) in zip(points, points[1:]):
                steps = max(1, int(math.ceil(math.hypot(qx - px, qy - py) / (g.step / 2))))
                for k in range(steps + 1):
                    allowed.update(g.nodes_near(px + (qx - px) * k / steps, py + (qy - py) * k / steps, half))
            xs = [x for x, _ in points]
            ys = [y for _, y in points]
            corridor = (min(xs) - half - 0.2, min(ys) - half - 0.2, max(xs) + half + 0.2, max(ys) + half + 0.2)
        path, second = _search(g, net, sources, targets, costs, ctx, obs, corridor, same_layer=True, allowed=allowed)
        if path is None and allowed is not None:  # the band was too narrow for the grid: the plain corridor
            corridor = (min(ax, bx) - m, min(ay, by) - m, max(ax, bx) + m, max(ay, by) + m)
            path, second = _search(g, net, sources, targets, costs, ctx, obs, corridor, same_layer=True)
        if path is None:
            path, second = _search(g, net, sources, targets, costs, ctx, obs, None, same_layer=True)
        if path is None:
            return None, {"why": f"no path on {g.board.GetLayerName(layer)} from ({ax:.2f}, {ay:.2f}) to "
                                 f"({bx:.2f}, {by:.2f})", "blockers": second}
        segments.append((path, second))
    return segments, None


def _commit(g: BusGraph, net, path, vias) -> list:
    added = []
    runs: list[tuple[int, list]] = []
    for layer, node in path:
        if runs and runs[-1][0] == layer:
            runs[-1][1].append(node)
        else:
            runs.append((layer, [node]))
    for layer, nodes in runs:
        pts = [nodes[0]]
        for k in range(1, len(nodes)):
            if len(pts) >= 2:
                (ax, ay), (bx, by) = g.xy[pts[-2]], g.xy[pts[-1]]
                cx, cy = g.xy[nodes[k]]
                d1, d2 = (bx - ax, by - ay), (cx - bx, cy - by)
                cross = d1[0] * d2[1] - d1[1] * d2[0]
                dot = d1[0] * d2[0] + d1[1] * d2[1]
                if abs(cross) < 1e-9 and dot > 0:
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


def _path_mm(g: BusGraph, segs: list) -> float:
    """Track length of routed segments (the vias add nothing)."""
    total = 0.0
    for path, _ in segs:
        for (la, a), (lb, b) in zip(path, path[1:]):
            if la == lb:
                total += math.hypot(g.xy[b][0] - g.xy[a][0], g.xy[b][1] - g.xy[a][1])
    return total


def _detour_candidates(g: BusGraph, board, rules: BusRules, islands: list[dict], deficit: float) -> list:
    """Waypoints for a detour of about ``deficit`` mm, as (estimate, node) sorted by the estimate: the node nearest
    each square millimetre's centre (the grid's phase is the first package's, so no node need sit on a whole
    millimetre) outside the pad arrays (the empty middle of a DRAM and the free board area both serve) and inside
    the board outline, whose straight-line added length lies between half the deficit and the deficit plus 4 mm.
    The estimate spans the tree's start island (the largest, as _route_net grows it) and the island farthest from
    it: the net's real span, not its two biggest pads (on ButterStick the two DRAM pads of a net sit 0.2 mm apart
    on opposite sides of the board)."""
    edges = board.GetBoardEdgesBoundingBox()
    inset = rules.track_mm / 2 + kb.mm(board.GetDesignSettings().m_CopperEdgeClearance)
    ex0, ey0 = kb.mm(edges.GetLeft()) + inset, kb.mm(edges.GetTop()) + inset
    ex1, ey1 = kb.mm(edges.GetRight()) - inset, kb.mm(edges.GetBottom()) - inset
    cents = []
    for i in sorted(islands, key=lambda i: -len(i["covered"])):
        xs = [g.xy[n][0] for _, n in i["covered"]]
        ys = [g.xy[n][1] for _, n in i["covered"]]
        cents.append((sum(xs) / len(xs), sum(ys) / len(ys)))
    if len(cents) < 2:
        return []
    (ax, ay) = cents[0]
    (bx, by) = max(cents[1:], key=lambda c: math.hypot(c[0] - ax, c[1] - ay))
    direct = math.hypot(bx - ax, by - ay)
    cells: dict = {}
    for w, (x, y) in enumerate(g.xy):
        if g.in_array[w] or not (ex0 <= x <= ex1 and ey0 <= y <= ey1):
            continue
        cell = (math.floor(x), math.floor(y))
        off = abs(x - cell[0] - 0.5) + abs(y - cell[1] - 0.5)
        if cell not in cells or off < cells[cell][0]:
            cells[cell] = (off, w)
    out = []
    for _, w in cells.values():
        x, y = g.xy[w]
        est = math.hypot(x - ax, y - ay) + math.hypot(bx - x, by - y) - direct
        if deficit * 0.5 <= est <= deficit + 4.0:
            out.append((est, w))
    out.sort()
    return out


def _detour(cands: list, deficit: float, lo: float, hi: float, cur: float, attempt, max_tries: int,
            prior: float = 1.6, budget_s: float = 90.0):
    """Try waypoints until the routed length lands in [lo, hi]. ``attempt(node)`` routes the net through the
    waypoint and returns (length, segments) or None. A routed detour runs longer than its straight-line estimate
    (it winds around the packages and the other nets), by a ratio learnt from each success: the next waypoint is
    the one whose estimate, at that ratio, adds the deficit. Returns the best (length, segments, waypoint) at or
    below ``hi``, or None."""
    cands = list(cands)
    ratio = prior
    best = None
    tries = successes = 0
    want = min(max(deficit / ratio, deficit * 0.5), deficit + 4.0)
    spread = (deficit * 0.5 + 4.0) / 6  # after an unreachable waypoint the next is looked for further out
    t0 = time.time()
    while cands and tries < max_tries and time.time() - t0 < budget_s:
        i = min(range(len(cands)), key=lambda k: abs(cands[k][0] - want))
        est, w = cands.pop(i)
        tries += 1
        got = attempt(w)
        if got is None:
            want = est + spread if est + spread <= deficit + 4.0 else deficit * 0.5
            continue
        new_len, segs = got
        if lo - 1e-3 <= new_len <= hi + 1e-3:
            return new_len, segs, w
        successes += 1
        if new_len <= hi + 1e-3 and new_len > cur + 1.0 and (best is None or new_len > best[0]):
            best = (new_len, segs, w)
        ratio = max(0.5, (new_len - cur) / max(est, 1e-6))
        want = min(max(deficit / ratio, deficit * 0.5), deficit + 4.0)
        if successes >= 4:
            break
    return best


def route_bus(board, packages: list[str], nets: set[str], rules: BusRules, costs: Costs | None = None,
              length_windows: dict | None = None, plans: dict | None = None) -> BusResult:
    """``length_windows`` maps a net to (min_mm, max_mm): a routed net shorter than its window by more than
    ``costs.detour_min_mm`` is re-routed through a detour point in free board area that adds about the missing
    length (the serpentine tuner adds the rest afterwards)."""
    costs = costs or Costs()
    lats = [Lattice(kb.footprint(board, r)) for r in packages]
    fps = {r: kb.package_info(kb.footprint(board, r)) for r in packages}
    layer_ids = {name: lid for lid, name in kb.copper_layers(board)}
    layers = [layer_ids[n] for n in rules.layers if n in layer_ids]
    top = pcbnew.F_Cu
    boxes = [fp.bbox_mm for fp in fps.values()]
    m = rules.margin_mm
    region = (min(b[0] for b in boxes) - m, min(b[1] for b in boxes) - m, max(b[2] for b in boxes) + m, max(b[3] for b in boxes) + m)
    g = BusGraph(board, lats, rules, layers, top, region, fps)
    obs = Obstacles(board, region)
    if TRACE:
        print(f"      bus graph: {len(g.xy)} nodes, {sum(len(a) for a in g.adj)} edges, {obs.count} obstacles", flush=True)
    net_objs = {}
    for name in nets:
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetname() == name:
                    net_objs[name] = pad.GetNet()
                    break
            if name in net_objs:
                break
    islands = {name: _islands(board, name, g, set(layers)) for name in nets}
    names = sorted(nets, key=lambda n: (-len(islands[n]), n))
    # a plan (a reference's structure: vias the board already carries, single-layer runs between terminals) replaces
    # the tree for the nets that have one
    link_plans: dict = {}
    for name, links in (plans or {}).items():
        link_plans[name] = [(link[0], link[1], link[2], link[3], layer_ids[link[4]] if isinstance(link[4], str) else link[4])
                            + tuple(link[5:]) for link in links]

    vias_on_board: Counter = Counter()
    if costs.max_vias_per_net:
        for item in board.GetTracks():
            if item.GetClass() == "PCB_VIA" and item.GetNetname() in nets:
                vias_on_board[item.GetNetname()] += 1

    def route_one(name, ctx_, waypoint=None):
        if name in link_plans:
            return _route_net_planned(g, net_objs[name], islands[name], link_plans[name], costs, ctx_, obs)
        return _route_net(g, net_objs[name], islands[name], costs, ctx_, obs, waypoint=waypoint,
                          vias_used=vias_on_board[name])

    # --- negotiation -----------------------------------------------------------------------------------------------
    occ = Occupancy(g)
    history: dict = defaultdict(float)
    paths: dict = {}  # net -> list of (path, vias)
    waypoints: dict = {}  # net -> node its route passes through, so that it comes out long enough
    base_mm: dict = {}
    if length_windows:
        from waffle_eda.route.length import net_length_mm
        base_mm = {name: net_length_mm(board, name) for name in names}  # the fan-out's own copper
    contested: dict = {}
    diagnoses: dict = {}
    rng = random.Random(costs.seed)
    best, since_better, forced = len(names) + 1, 0, set()
    for it in range(costs.iterations):
        t_it = time.time()
        ctx = Context(occ, history, costs.present * it)
        todo = [n for n in names if n not in paths or contested.get(n) or costs.reroute_all]
        extra = [n for n in names if n in forced and n not in todo]
        if it > 0:
            rng.shuffle(todo)
            rng.shuffle(extra)
        todo += extra
        for name in todo:
            if name in paths:
                for path, vias in paths.pop(name):
                    occ.add(path, vias, name, -1)
            segs, diag = route_one(name, ctx, waypoint=waypoints.get(name))
            if segs is None and name in waypoints:  # the detour is a wish, the connection a must
                segs, diag = route_one(name, ctx)
            if segs is None:
                diagnoses[name] = diag
                continue
            paths[name] = segs
            for path, vias in segs:
                occ.add(path, vias, name, 1)
        if it == 0 and length_windows and costs.waypoint_deficit_mm < math.inf:
            # a net whose first, uncontested route falls short of its window by more than the tuner can add is
            # given a waypoint now, so that the negotiation places the long route rather than a short one the
            # other nets then wall in (on ButterStick the reference's bus lives inside the DRAM area, meandered;
            # there is no free board area to detour through afterwards)
            t_w = time.time()
            ctx0 = Context(occ, history, 0.0)
            for name in names:
                if name not in paths:
                    continue
                lo, hi = length_windows.get(name, (0.0, math.inf))
                cur = base_mm[name] + _path_mm(g, paths[name])
                if lo - cur < costs.waypoint_deficit_mm:
                    continue  # the tuner's serpentines and a detour in the final pass can add this much

                def attempt(w, name=name):
                    segs, _ = route_one(name, ctx0, waypoint=w)
                    return None if segs is None else (base_mm[name] + _path_mm(g, segs), segs)

                cands = _detour_candidates(g, board, rules, islands[name], lo - cur)
                # aim at the lower half of the window: the negotiation lengthens routes, the tuner only adds
                got = _detour(cands, lo - cur, lo, (lo + hi) / 2, cur, attempt, costs.detour_candidates)
                if got is None:
                    continue
                waypoints[name] = got[2]
                for path, vias in paths.pop(name):
                    occ.add(path, vias, name, -1)
                paths[name] = got[1]
                for path, vias in got[1]:
                    occ.add(path, vias, name, 1)
            if TRACE:
                print(f"      waypoints for {len(waypoints)} nets short of their window, {time.time() - t_w:.1f}s",
                      flush=True)
        contested = {}
        for name, segs in paths.items():
            c = []
            for path, vias in segs:
                c += occ.conflicts(path, vias, name)
            if c:
                contested[name] = c
        if TRACE:
            print(f"      it {it}: {len(paths)}/{len(names)} routed, {len(contested)} contested, "
                  f"{len(todo)} re-routed, {time.time() - t_it:.1f}s", flush=True)
            if os.environ.get("BUS_DEBUG_ROUNDS"):
                print(f"         todo {[n.split('/')[-1] for n in todo]}", flush=True)
                print(f"         contested {sorted(n.split('/')[-1] for n in contested)}", flush=True)
                print(f"         lengths {[round(_path_mm(g, paths[n]), 2) for n in names if n in paths]}", flush=True)
                import hashlib
                for n in names:
                    if n in paths:
                        d = hashlib.sha1(repr([(path, vias) for path, vias in paths[n]]).encode()).hexdigest()[:8]
                        print(f"         path {n.split('/')[-1]} {d}", flush=True)
            if contested and (it % 10 == 9 or it == costs.iterations - 1):
                # who is in conflict with whom: the partners of each contested net
                for name in sorted(contested)[:12]:
                    partners: Counter = Counter()
                    for key in contested[name]:
                        near = occ.near_sample(key[1], key[2], key[3]) if key[0] == "t" else occ.near_via(key[1])
                        for other in near - {name}:
                            partners[other] += 1
                    short = ", ".join(f"{o.split('/')[-1]} x{c}" for o, c in partners.most_common(4))
                    where: Counter = Counter()
                    xs, ys = [], []
                    for key in contested[name]:
                        if key[0] == "t":
                            where[f"track {board.GetLayerName(key[1])}"] += 1
                            xs.append(key[2] * g.u)
                            ys.append(key[3] * g.u)
                        else:
                            where["via"] += 1
                            xs.append(g.xy[key[1]][0])
                            ys.append(g.xy[key[1]][1])
                    spot = f"x {min(xs):.1f}..{max(xs):.1f} y {min(ys):.1f}..{max(ys):.1f}" if xs else ""
                    print(f"         {name.split('/')[-1]}: conflicts with {short}; "
                          f"{dict(where)} at {spot}", flush=True)
            for name in names:
                if name not in paths and name in diagnoses:
                    d = diagnoses[name]
                    top = ", ".join(f"{k} x{v}" for k, v in d["blockers"].most_common(3))
                    print(f"         unrouted {name}: {d['why']}; {top or 'nothing recorded'}", flush=True)
        if not contested:
            break
        for keys in contested.values():
            for k in keys:
                history[k] += costs.history
        if len(contested) < best:
            best, since_better, forced = len(contested), 0, set()
        else:
            since_better += 1
            if since_better >= costs.stall_rounds:
                hops = 1 + (since_better - costs.stall_rounds) // costs.stall_rounds
                forced = set(contested)
                for _ in range(min(hops, costs.max_radius_hops)):
                    grown = set(forced)
                    for name in forced:
                        for path, vias in paths.get(name, []):
                            for key in occ.path_samples(path):
                                grown |= occ.near_sample(*key)
                            for node in vias:
                                grown |= occ.near_via(node)
                    forced = grown
                forced -= set(contested)
                # a pair stuck on one spot has no partners but each other: then every net whose path passes within
                # a growing distance of the contested paths is ripped up too, so that the third net in the way
                # gives way (the escape router's radius fallback)
                if not forced or hops > costs.max_radius_hops:
                    radius = min(0.5 * 2 ** max(0, hops - 1), costs.max_radius_mm)
                    boxes = []
                    for name in contested:
                        for path, _ in paths.get(name, []):
                            xs = [g.xy[n][0] for _, n in path]
                            ys = [g.xy[n][1] for _, n in path]
                            boxes.append((min(xs) - radius, min(ys) - radius, max(xs) + radius, max(ys) + radius))
                    for other, segs in paths.items():
                        if other in contested or other in forced:
                            continue
                        if any(bx0 <= g.xy[n][0] <= bx1 and by0 <= g.xy[n][1] <= by1
                               for bx0, by0, bx1, by1 in boxes for path, _ in segs for _, n in path):
                            forced.add(other)
                    if TRACE:
                        print(f"      stalled {since_better} rounds: ripping up {len(forced)} nets within "
                              f"{radius} mm of the contested paths", flush=True)

    # --- final pass: the negotiated paths are kept where nothing contests them and the exact collision test
    # against the copper committed so far agrees; only the contested or unrouted nets are searched again, with the
    # spacing between bus nets kept by the occupancy ---------------------------------------------------------------
    result = BusResult()
    result.counts["iterations"] = it + 1
    occ = Occupancy(g)
    ctx = Context(occ, history, 0.0, hard=True)
    committed: dict = {}

    def commit_segments(name, segs):
        items = []
        for path, vias in segs:
            items += _commit(g, net_objs[name], path, vias)
            occ.add(path, vias, name, 1)
        committed[name] = (segs, items)

    def place(name):
        segs, diag = route_one(name, ctx, waypoint=waypoints.get(name))
        if segs is None and name in waypoints:
            segs, diag = route_one(name, ctx)
        if segs is None:
            return diag
        commit_segments(name, segs)
        return None

    def unplace(name):
        segs, items = committed.pop(name)
        for path, vias in segs:
            occ.add(path, vias, name, -1)
        for item in items:
            g.committed.remove(item)
            board.Delete(item)

    kept = 0
    leftovers = []
    for name in names:
        if name in paths and not contested.get(name):
            segs = paths[name]
            if all(g.path_clear(path, vias, net_objs[name], obs) for path, vias in segs):
                commit_segments(name, segs)
                kept += 1
            else:
                leftovers.append(name)
    result.counts["negotiated kept"] = kept
    depth = {}
    for name in names:
        rings = [b.ring for isl in islands[name] for pad in isl["pads"] for lat in lats
                 for b in [lat.balls.get(pad.GetNumber())] if b is not None and lat.reference ==
                 pcbnew.Cast_to_FOOTPRINT(pad.GetParent()).GetReference()]
        depth[name] = max(rings) if rings else 0
    order = sorted([n for n in names if n not in committed],
                   key=lambda n: (n not in paths, -depth[n], sum(len(p) for p, _ in paths.get(n, [])), n))
    failed: dict = {}
    for name in order:
        diag = place(name)
        if diag is not None:
            failed[name] = diag
    # repair: rip up the nets whose copper blocks a failed net (the most blocking first, a bounded number) and
    # route it first, then re-place them; when one of them cannot be placed again, everything ripped up is put
    # back as it was
    def repair_with(name, saved) -> bool:
        """Rip up ``saved`` and negotiate them together with ``name`` against everything else, committed and
        fixed; commit the result when every one of them is routed and uncontested, otherwise put everything back
        as it was. A greedy re-placement is not enough: the stranded net fits once its neighbours are ripped up,
        but re-placing them one by one strands one of them instead."""
        saved = [n for n in saved if n in committed]
        if not saved:
            return False
        saved_segs = {n: committed[n][0] for n in saved}
        for n in saved:
            unplace(n)
        subset = [name] + sorted(saved, key=lambda n: (-depth[n], n))
        occ2 = Occupancy(g)
        hist2: dict = defaultdict(float)
        paths2: dict = {}
        contested2: dict = {}
        rng2 = random.Random(costs.seed)
        for it2 in range(costs.repair_negotiation):
            ctx2 = Context(occ2, hist2, costs.present * (it2 + 1))
            todo = [n for n in subset if n not in paths2 or contested2.get(n)]
            if it2 > 0:
                rng2.shuffle(todo)
            for n in todo:
                for path, vias in paths2.pop(n, []):
                    occ2.add(path, vias, n, -1)
                segs, _ = route_one(n, ctx2, waypoint=waypoints.get(n))
                if segs is None and n in waypoints:
                    segs, _ = route_one(n, ctx2)
                if segs is None:
                    continue
                paths2[n] = segs
                for path, vias in segs:
                    occ2.add(path, vias, n, 1)
            contested2 = {}
            for n, segs in paths2.items():
                c = [k for path, vias in segs for k in occ2.conflicts(path, vias, n)]
                if c:
                    contested2[n] = c
            if len(paths2) == len(subset) and not contested2:
                break
            for keys in contested2.values():
                for k in keys:
                    hist2[k] += costs.history
        ok = len(paths2) == len(subset) and not contested2
        placed = []
        if ok:
            for n in subset:  # exact geometry decides, one by one; a net the samples misjudged is searched again
                segs = paths2[n]
                if not all(g.path_clear(path, vias, net_objs[n], obs) for path, vias in segs):
                    if place(n) is not None:
                        ok = False
                        break
                else:
                    commit_segments(n, segs)
                placed.append(n)
        if ok:
            return True
        for n in placed:
            if n in committed:
                unplace(n)
        for n in saved:
            commit_segments(n, saved_segs[n])
        return False

    for _round in range(costs.repair_rounds):
        for name in list(failed):
            partners: Counter = Counter()
            for key, count in failed[name]["blockers"].items():
                if ": our " in key:
                    partners[key.split(" of '", 1)[1].rstrip("'")] += count
            if not partners:  # blocked by spacing: the nets whose copper lies in this net's corridor
                cx0, cy0, cx1, cy1 = _corridor(g, islands[name], 0.5)
                for other, (segs, _) in committed.items():
                    inside = sum(1 for path, _ in segs for _, n in path if cx0 <= g.xy[n][0] <= cx1 and cy0 <= g.xy[n][1] <= cy1)
                    if inside:
                        partners[other] += inside
            if repair_with(name, [n for n, _ in partners.most_common(costs.repair_partners)]):
                failed.pop(name)
                continue
            # the named blockers are only the first wall: re-pack the whole neighbourhood of the stranded net's pads,
            # within a growing radius, the stranded net first
            points = [g.xy[n] for isl in islands[name] for _, n in isl["covered"]]
            for radius in costs.repair_radius_mm:
                near = []
                for other, (segs, _) in committed.items():
                    if other == name:
                        continue
                    d = min((math.hypot(g.xy[n][0] - px, g.xy[n][1] - py) for path, _ in segs for _, n in path
                             for px, py in points), default=math.inf)
                    if d <= radius:
                        near.append((d, other))
                saved = [o for _, o in sorted(near)[:30]]
                if TRACE:
                    print(f"      repair {name.split('/')[-1]}: re-packing {len(saved)} nets within {radius} mm", flush=True)
                if repair_with(name, saved):
                    failed.pop(name)
                    break
    # --- detours: nets far below their length window get a waypoint in free board area ----------------------------
    if length_windows:
        from waffle_eda.route.length import net_length_mm

        for name in names:
            if name not in committed:
                continue
            lo, hi = length_windows.get(name, (0.0, math.inf))
            cur = net_length_mm(board, name)
            if cur > hi + 1e-3 and name in waypoints:  # the negotiation grew the detour past the window
                saved_segs = committed[name][0]
                unplace(name)
                segs, _ = route_one(name, ctx)
                if segs is not None:
                    commit_segments(name, segs)
                    cur = net_length_mm(board, name)
                if segs is None or cur > hi + 1e-3:
                    if segs is not None:
                        unplace(name)
                    commit_segments(name, saved_segs)
                    continue
                result.counts["shortened"] += 1
            if lo - cur <= costs.detour_min_mm:
                continue
            saved_segs = committed[name][0]
            unplace(name)

            def attempt(w, name=name):
                segs, _ = route_one(name, ctx, waypoint=w)
                if segs is None:
                    return None
                commit_segments(name, segs)
                new_len = net_length_mm(board, name)
                unplace(name)
                return new_len, segs

            cands = _detour_candidates(g, board, rules, islands[name], lo - cur)
            best = _detour(cands, lo - cur, lo, hi, cur, attempt, costs.detour_candidates)
            if best is None:
                commit_segments(name, saved_segs)
            else:
                commit_segments(name, best[1])
                result.counts["detours"] += 1

    for name in names:
        if name in committed:
            segs, items = committed[name]
            nvias = sum(len(v) for _, v in segs)
            lays = {board.GetLayerName(L) for path, _ in segs for L, _ in path}
            result.routed[name] = f"{len(segs)} link(s), {nvias} via(s), {sorted(lays)}"
            result.counts[f"links {len(segs)}"] += 1
            result.counts[f"vias {nvias}"] += 1
        else:
            d = failed.get(name) or diagnoses.get(name) or {"why": "no path", "blockers": Counter()}
            top3 = ", ".join(f"{k} x{v}" for k, v in d["blockers"].most_common(3))
            result.failed[name] = f"{d['why']}; blocked by {top3 or 'nothing recorded'}"
            result.counts["FAILED"] += 1
    return result
