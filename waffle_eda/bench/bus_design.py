"""How a reference board routes its bus, read from the board: per net (length, layers, vias and where they sit,
where the route enters each package, the path from the controller to each memory pad, meanders and where they
lie), per signal group (the length matching the designer achieved), and per package (how the array, the hollow
middle and the margins are used). Nothing here is assumed; the numbers are what the router has to reproduce."""
from __future__ import annotations

import heapq
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pcbnew

from waffle_eda.bench import references as refs
from waffle_eda.kicad import board as kb
from waffle_eda.route.lattice import Lattice

MEANDER_WINDOW_MM = 1.5  # path length over which a serpentine makes little headway
MEANDER_HEADWAY = 0.5  # a window whose ends are closer than this fraction of its length is meander


# --- signal groups ------------------------------------------------------------------------------------------------
def short_name(net: str) -> str:
    s = net.split("/")[-1]
    s = s.replace("~{", "").replace("}", "")
    return re.sub(r"^DDR\d?_", "", s)


def classify(net: str) -> tuple[str, str, str | None]:
    """(group, role, pair) for a bus net: the group whose lengths are matched together, the net's role in it
    (data, strobe, mask, clock, command, other) and the differential pair it belongs to, if any."""
    s = short_name(net)
    m = re.fullmatch(r"DQ(\d+)", s)
    if m:
        return f"lane {int(m.group(1)) // 8}", "data", None
    m = re.fullmatch(r"([LU])DQS[_]?([PN])", s) or re.fullmatch(r"DQS(\d)([+-])", s)
    if m:
        lane = {"L": 0, "U": 1}.get(m.group(1), None)
        lane = int(m.group(1)) if lane is None else lane
        return f"lane {lane}", "strobe", f"DQS{lane}"
    m = re.fullmatch(r"([LU])DM", s) or re.fullmatch(r"DM(\d)", s)
    if m:
        lane = {"L": 0, "U": 1}.get(m.group(1), None)
        lane = int(m.group(1)) if lane is None else lane
        return f"lane {lane}", "mask", None
    m = re.fullmatch(r"CK(\d*)[_]?([PN+-])", s)
    if m:
        return "address/command", "clock", f"CK{m.group(1)}"
    if re.fullmatch(r"(A\d+|BA\d+|RAS|CAS|WE|CS\d*|CKE\d*|ODT\d*)", s):
        return "address/command", "command", None
    if re.fullmatch(r"(RST|RESET)", s):
        return "reset", "other", None
    return "other", "other", None


# --- geometry helpers ---------------------------------------------------------------------------------------------
def _key(x: float, y: float) -> tuple[int, int]:
    return (int(round(x * 1000)), int(round(y * 1000)))  # micrometres


@dataclass
class Package:
    reference: str
    info: kb.PackageInfo
    lattice: Lattice | None  # None for a resistor or a network

    def hollow_cells(self) -> set[tuple[int, int]]:
        """Grid cells inside the array's index range with no ball: the empty middle of a memory package."""
        lat = self.lattice
        if lat is None:
            return set()
        return {(i, j) for i in range(lat.cols) for j in range(lat.rows) if (i, j) not in lat.by_index}

    def where(self, x: float, y: float) -> str:
        """array (within half a pitch of a ball), hollow (inside the array's box, no ball near), margin (inside the
        footprint's box, outside the array's box) or nothing."""
        lat = self.lattice
        if lat is not None and lat.inside_array(x, y, 0.5):
            fi, fj = (x - lat.x0) / lat.pitch, (y - lat.y0) / lat.pitch
            i, j = round(fi), round(fj)
            if (i, j) in lat.by_index and abs(fi - i) <= 0.5 and abs(fj - j) <= 0.5:
                return "array"
            return "hollow"
        if self.info.in_footprint_mm(x, y):
            return "margin"
        return ""


def _side_of(bbox, x, y) -> str:
    x0, y0, x1, y1 = bbox
    d = {"W": abs(x - x0), "E": abs(x - x1), "N": abs(y - y0), "S": abs(y - y1)}
    return min(d, key=d.get)


# --- the measurement ----------------------------------------------------------------------------------------------
@dataclass
class NetDesign:
    net: str
    group: str
    role: str
    pair: str | None
    length_mm: float = 0.0
    per_layer_mm: dict = field(default_factory=dict)
    vias: int = 0
    via_places: Counter = field(default_factory=Counter)  # in pad / array of X / hollow of X / margin of X / outside
    entries: dict = field(default_factory=dict)  # package -> list of (side, layer, across index)
    paths: dict = field(default_factory=dict)  # "REF.pad" -> {"length_mm", "layers", "vias"}
    meander_mm: float = 0.0
    meander_places: Counter = field(default_factory=Counter)
    copper_places: Counter = field(default_factory=Counter)  # mm of copper by place
    unreached: list = field(default_factory=list)


def measure_bus_design(key: str) -> dict:
    ref = refs.REFERENCES[key]
    return measure_board(kb.load_board(refs.board_path(ref)), ref)


def measure_board(board, ref) -> dict:
    """The bus design of any board that carries the reference's bus nets and packages (the reference itself, or a
    candidate routed on its stripped problem board)."""
    key = ref.key
    bus = sorted(kb.nets_matching(board, ref.bus_net_pattern))
    bus_set = set(bus)
    # packages: the bus parts (BGAs) and every other footprint carrying a bus pad (terminations)
    packages: dict[str, Package] = {}
    for fp in board.GetFootprints():
        r = fp.GetReference()
        if r in ref.bus_parts or any(p.GetNetname() in bus_set for p in fp.Pads()):
            lat = Lattice(fp) if r in ref.bus_parts else None
            packages[r] = Package(r, kb.package_info(fp), lat)
    controller = ref.bus_parts[0]

    def place(x, y) -> str:
        for r, pk in packages.items():
            w = pk.where(x, y)
            if w:
                return f"{w} of {r}"
        return "outside"

    # pads of the bus nets: (net, ref, number, x, y, radius)
    pads = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() in bus_set:
                p = pad.GetPosition()
                size = pad.GetSize()
                pads.append((pad.GetNetname(), fp.GetReference(), pad.GetNumber(), kb.mm(p.x), kb.mm(p.y),
                             max(kb.mm(size.x), kb.mm(size.y)) / 2))
    pads_by_net = defaultdict(list)
    for entry in pads:
        pads_by_net[entry[0]].append(entry)

    # the copper as a graph per net: nodes at track ends (a via joins layers at its position by sharing the key)
    tracks_by_net = defaultdict(list)
    vias_by_net = defaultdict(list)
    for item in board.GetTracks():
        name = item.GetNetname()
        if name not in bus_set:
            continue
        if item.GetClass() == "PCB_VIA":
            p = item.GetPosition()
            vias_by_net[name].append((kb.mm(p.x), kb.mm(p.y), kb.via_diameter_mm(item) / 2))
        else:
            a, b = item.GetStart(), item.GetEnd()
            tracks_by_net[name].append((kb.mm(a.x), kb.mm(a.y), kb.mm(b.x), kb.mm(b.y), kb.mm(item.GetLength()),
                                        board.GetLayerName(item.GetLayer())))

    nets: dict[str, NetDesign] = {}
    for name in bus:
        group, role, pair = classify(name)
        nd = NetDesign(name, group, role, pair)
        tracks = tracks_by_net[name]
        nd.length_mm = sum(t[4] for t in tracks)
        per_layer: Counter = Counter()
        for t in tracks:
            per_layer[t[5]] += t[4]
            nd.copper_places[place((t[0] + t[2]) / 2, (t[1] + t[3]) / 2)] += t[4]
        nd.per_layer_mm = {k: round(v, 2) for k, v in per_layer.most_common()}
        nd.vias = len(vias_by_net[name])
        for (x, y, _vr) in vias_by_net[name]:
            in_pad = any(math.hypot(x - px, y - py) <= pr + 1e-3 for _, _, _, px, py, pr in pads_by_net[name])
            nd.via_places["in pad" if in_pad else place(x, y)] += 1
        # entries: track segments crossing a package's array box (half a pitch outside the outer balls)
        for r, pk in packages.items():
            if pk.lattice is None:
                continue
            bb = pk.lattice.array_bbox_mm(0.5)
            found = []
            for (ax, ay, bx, by, L, layer) in tracks:
                ina = bb[0] <= ax <= bb[2] and bb[1] <= ay <= bb[3]
                inb = bb[0] <= bx <= bb[2] and bb[1] <= by <= bb[3]
                if ina != inb:
                    ox, oy = (bx, by) if ina else (ax, ay)  # the outer end
                    side = _side_of(bb, ox, oy)
                    lat = pk.lattice
                    across = (oy - lat.y0) / lat.pitch if side in "WE" else (ox - lat.x0) / lat.pitch
                    found.append((side, layer, round(across, 1)))
            if found:
                nd.entries[r] = sorted(set(found))
        # paths from the controller's pad to every other pad of the net
        adj: dict = defaultdict(list)
        for (ax, ay, bx, by, L, layer) in tracks:
            ka, kb_ = _key(ax, ay), _key(bx, by)
            adj[ka].append((kb_, L, layer, (ax, ay, bx, by)))
            adj[kb_].append((ka, L, layer, (bx, by, ax, ay)))
        # a via joins every track end within its barrel (a track may stop short of the via's centre by microns)
        for (vx, vy, vr) in vias_by_net[name]:
            vk = _key(vx, vy)
            for node in list(adj):
                if node != vk and math.hypot(node[0] / 1000 - vx, node[1] / 1000 - vy) <= vr + 1e-3:
                    adj[node].append((vk, 0.0, "via", (node[0] / 1000, node[1] / 1000, vx, vy)))
                    adj[vk].append((node, 0.0, "via", (vx, vy, node[0] / 1000, node[1] / 1000)))
        # pad centres join every track end within the pad
        pad_key = {}
        for (_, r, num, px, py, pr) in pads_by_net[name]:
            pk_ = _key(px, py)
            pad_key[(r, num)] = pk_
            for node in list(adj):
                if node != pk_ and math.hypot(node[0] / 1000 - px, node[1] / 1000 - py) <= pr + 1e-3:
                    adj[node].append((pk_, 0.0, "pad", (node[0] / 1000, node[1] / 1000, px, py)))
                    adj[pk_].append((node, 0.0, "pad", (px, py, node[0] / 1000, node[1] / 1000)))
        sources = [pad_key[(r, num)] for (_, r, num, *_rest) in pads_by_net[name] if r == controller]
        if not sources:
            nd.unreached = [f"{r}.{num}" for (_, r, num, *_rest) in pads_by_net[name]]
            nets[name] = nd
            continue
        dist = {s: 0.0 for s in sources}
        prev = {s: None for s in sources}
        heap = [(0.0, i, s) for i, s in enumerate(sources)]
        counter = len(sources)
        while heap:
            d, _, u = heapq.heappop(heap)
            if d > dist.get(u, math.inf):
                continue
            for v, L, layer, seg in adj[u]:
                nd_ = d + L
                if nd_ < dist.get(v, math.inf):
                    dist[v] = nd_
                    prev[v] = (u, layer, seg, L)
                    counter += 1
                    heapq.heappush(heap, (nd_, counter, v))
        meander_edges: set = set()
        for (_, r, num, px, py, pr) in pads_by_net[name]:
            if r == controller:
                continue
            target = pad_key[(r, num)]
            if target not in dist:
                nd.unreached.append(f"{r}.{num}")
                continue
            # the polyline back to the controller, as (x, y, layer-of-the-segment-that-led-here, length)
            poly = []
            node = target
            while prev.get(node) is not None:
                u, layer, seg, L = prev[node]
                poly.append((seg[0], seg[1], seg[2], seg[3], layer, L))
                node = u
            poly.reverse()
            layers = [p[4] for p in poly if p[4] not in ("pad", "via")]
            seq = [layers[0]] if layers else []
            for L_ in layers[1:]:
                if L_ != seq[-1]:
                    seq.append(L_)
            nd.paths[f"{r}.{num}"] = {"length_mm": round(dist[target], 2), "layers": seq,
                                       "vias": max(0, len(seq) - 1)}
            # meanders: windows of the path that make little headway
            pts = [(p[0], p[1]) for p in poly] + ([(poly[-1][2], poly[-1][3])] if poly else [])
            cum = [0.0]
            for p in poly:
                cum.append(cum[-1] + p[5])
            for i, p in enumerate(poly):
                if p[4] in ("pad", "via") or p[5] == 0:
                    continue
                mid = (cum[i] + cum[i + 1]) / 2
                s0, s1 = mid - MEANDER_WINDOW_MM / 2, mid + MEANDER_WINDOW_MM / 2
                if s0 < 0 or s1 > cum[-1]:
                    continue

                def at(s):
                    j = max(0, min(len(poly) - 1, next((k for k in range(len(poly)) if cum[k + 1] >= s), len(poly) - 1)))
                    q = poly[j]
                    f = (s - cum[j]) / q[5] if q[5] else 0.0
                    return q[0] + (q[2] - q[0]) * f, q[1] + (q[3] - q[1]) * f

                (x0, y0), (x1, y1) = at(s0), at(s1)
                if math.hypot(x1 - x0, y1 - y0) < MEANDER_HEADWAY * MEANDER_WINDOW_MM:
                    meander_edges.add((p[0], p[1], p[2], p[3], p[4], p[5]))
        for (ax, ay, bx, by, layer, L) in meander_edges:
            nd.meander_mm += L
            nd.meander_places[place((ax + bx) / 2, (ay + by) / 2)] += L
        nd.meander_mm = round(nd.meander_mm, 2)
        nets[name] = nd

    # --- groups: the matching the designer achieved -------------------------------------------------------------
    groups: dict = {}
    by_group = defaultdict(list)
    for nd in nets.values():
        by_group[nd.group].append(nd)
    for g, members in by_group.items():
        ref_net = None
        for nd in members:
            if (g.startswith("lane") and nd.role == "strobe" and short_name(nd.net).endswith(("P", "+"))) or \
               (g == "address/command" and nd.role == "clock" and short_name(nd.net).endswith(("P", "+"))
                and "0" in short_name(nd.net) or (g == "address/command" and nd.role == "clock" and ref_net is None
                                                  and short_name(nd.net).endswith(("P", "+")))):
                ref_net = nd
        lengths = {short_name(nd.net): nd.length_mm for nd in members}
        # the path to each memory pad, keyed by the memory package: the matching that matters at the pin
        per_dest: dict = defaultdict(dict)
        for nd in members:
            for dest, info in nd.paths.items():
                per_dest[dest.split(".")[0]][short_name(nd.net)] = info["length_mm"]
        entry = {"nets": len(members), "reference": short_name(ref_net.net) if ref_net else None,
                 "total_length_mm": {"min": round(min(lengths.values()), 2), "max": round(max(lengths.values()), 2),
                                     "spread": round(max(lengths.values()) - min(lengths.values()), 2)}}
        if ref_net:
            deltas = {n: round(L - ref_net.length_mm, 2) for n, L in lengths.items()}
            entry["delta_to_reference_mm"] = {"max_abs": round(max(abs(d) for d in deltas.values()), 2),
                                              "per_net": dict(sorted(deltas.items(), key=lambda kv: kv[1]))}
        entry["to_each_memory_mm"] = {}
        for dest, L in per_dest.items():
            vals = list(L.values())
            d = {"nets": len(vals), "min": round(min(vals), 2), "max": round(max(vals), 2),
                 "spread": round(max(vals) - min(vals), 2)}
            if ref_net and short_name(ref_net.net) in L:
                r0 = L[short_name(ref_net.net)]
                d["max_abs_delta_to_reference"] = round(max(abs(v - r0) for v in vals), 2)
            entry["to_each_memory_mm"][dest] = d
        pairs = defaultdict(list)
        for nd in members:
            if nd.pair:
                pairs[nd.pair].append(nd.length_mm)
        entry["pair_mismatch_mm"] = {p: round(abs(v[0] - v[1]), 3) for p, v in pairs.items() if len(v) == 2}
        groups[g] = entry

    # --- packages: array, hollow and margins ---------------------------------------------------------------------
    pkgs: dict = {}
    for r, pk in packages.items():
        lat = pk.lattice
        if lat is None:
            continue
        hollow = pk.hollow_cells()
        use: dict = defaultdict(Counter)
        nets_in: dict = defaultdict(set)
        for nd in nets.values():
            for (ax, ay, bx, by, L, layer) in tracks_by_net[nd.net]:
                w = pk.where((ax + bx) / 2, (ay + by) / 2)
                if w:
                    use[w][layer] += L
                    nets_in[w].add(short_name(nd.net))
        bus_balls = sum(1 for b in lat.balls.values() if b.net in bus_set)
        pkgs[r] = {"pitch_mm": lat.pitch, "rows": lat.rows, "cols": lat.cols, "balls": len(lat.balls),
                   "bus_balls": bus_balls, "hollow_cells": len(hollow),
                   "hollow_cols": sorted({i for i, _ in hollow}) if hollow else [],
                   "copper_mm": {w: {L: round(v, 1) for L, v in c.most_common()} for w, c in use.items()},
                   "nets": {w: len(s) for w, s in nets_in.items()},
                   "entries": Counter(side for nd in nets.values() for side, _, _ in nd.entries.get(r, ())),
                   "entry_layers": Counter(layer for nd in nets.values() for _, layer, _ in nd.entries.get(r, ()))}

    layer_nets = Counter()
    for nd in nets.values():
        for L, v in nd.per_layer_mm.items():
            if v >= 1.0:
                layer_nets[L] += 1
    via_hist = Counter(nd.vias for nd in nets.values())
    return {"reference": key, "controller": controller, "bus_parts": list(ref.bus_parts),
            "terminations": sorted(r for r in packages if r not in ref.bus_parts),
            "nets": {short_name(n): {"group": nd.group, "role": nd.role, "length_mm": round(nd.length_mm, 2),
                                     "per_layer_mm": nd.per_layer_mm, "vias": nd.vias,
                                     "via_places": dict(nd.via_places), "entries": nd.entries, "paths": nd.paths,
                                     "meander_mm": nd.meander_mm, "meander_places": {k: round(v, 2) for k, v in nd.meander_places.items()},
                                     "copper_places": {k: round(v, 2) for k, v in nd.copper_places.most_common()},
                                     "unreached": nd.unreached}
                     for n, nd in nets.items()},
            "groups": groups, "packages": pkgs,
            "layers": {"nets_using": dict(layer_nets.most_common())},
            "vias_per_net": dict(sorted(via_hist.items()))}


def report(d: dict) -> str:
    out = [f"== {d['reference']}: controller {d['controller']}, memories {d['bus_parts'][1:]}, "
           f"terminations {d['terminations']}"]
    out.append(f"   nets per layer (>= 1 mm on it): {d['layers']['nets_using']}; vias per net: {d['vias_per_net']}")
    for g, e in d["groups"].items():
        t = e["total_length_mm"]
        line = (f"   group {g}: {e['nets']} nets, total length {t['min']}..{t['max']} mm (spread {t['spread']}), "
                f"reference {e['reference']}")
        if "delta_to_reference_mm" in e:
            line += f", max |delta| {e['delta_to_reference_mm']['max_abs']} mm"
        out.append(line)
        for dest, m in e["to_each_memory_mm"].items():
            out.append(f"      to {dest}: {m['nets']} nets, {m['min']}..{m['max']} mm (spread {m['spread']})"
                       + (f", max |delta| to reference {m['max_abs_delta_to_reference']}" if "max_abs_delta_to_reference" in m else ""))
        if e["pair_mismatch_mm"]:
            out.append(f"      pairs: {e['pair_mismatch_mm']}")
    for r, p in d["packages"].items():
        out.append(f"   {r}: {p['cols']}x{p['rows']} at {p['pitch_mm']} mm, {p['balls']} balls ({p['bus_balls']} bus), "
                   f"hollow {p['hollow_cells']} cells (cols {p['hollow_cols']})")
        for w, c in p["copper_mm"].items():
            out.append(f"      copper in {w}: {c} ({p['nets'].get(w, 0)} nets)")
        out.append(f"      entries by side {dict(p['entries'])}, by layer {dict(p['entry_layers'])}")
    meander_total = sum(n["meander_mm"] for n in d["nets"].values())
    places: Counter = Counter()
    for n in d["nets"].values():
        for k, v in n["meander_places"].items():
            places[k] += v
    out.append(f"   meanders: {meander_total:.1f} mm in {sum(1 for n in d['nets'].values() if n['meander_mm'] > 0)} nets; "
               f"where: {', '.join(f'{k} {v:.1f}' for k, v in places.most_common())}")
    via_places: Counter = Counter()
    for n in d["nets"].values():
        via_places.update(n["via_places"])
    out.append(f"   vias: {dict(via_places.most_common())}")
    out.append("   per net: name group length vias layers[mm] meander[mm] paths")
    for name, n in sorted(d["nets"].items(), key=lambda kv: (kv[1]["group"], kv[0])):
        paths = ", ".join(f"{k} {v['length_mm']} {'/'.join(v['layers'])}" for k, v in n["paths"].items())
        out.append(f"      {name:<8} {n['group']:<16} {n['length_mm']:6.2f} {n['vias']} {n['per_layer_mm']} "
                   f"meander {n['meander_mm']} {n['meander_places']} | {paths}"
                   + (f" | UNREACHED {n['unreached']}" if n["unreached"] else ""))
    return "\n".join(out)


# --- the reference's plan: its vias and its single-layer runs between terminals ------------------------------------
def reference_plan(board, bus_nets, controller: str | None = None) -> dict:
    """For each net: its vias (x, y, diameter, drill) and its links, the maximal single-layer runs between terminals
    (a pad or a via), as (label_a, label_b, layer, length_mm, points). This is what the reference decided: where
    the layer changes are and which layer each run takes; the path between two terminals is what a router finds,
    and the reference's own polyline (``points``) can bound where it looks."""
    bus_set = set(bus_nets)
    pads = defaultdict(list)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() in bus_set:
                p = pad.GetPosition()
                size = pad.GetSize()
                pads[pad.GetNetname()].append((kb.mm(p.x), kb.mm(p.y), max(kb.mm(size.x), kb.mm(size.y)) / 2,
                                              fp.GetReference() + "." + pad.GetNumber(),
                                              frozenset(board.GetLayerName(L) for L in pad.GetLayerSet().CuStack())))
    tracks = defaultdict(list)
    vias = defaultdict(list)
    for item in board.GetTracks():
        name = item.GetNetname()
        if name not in bus_set:
            continue
        if item.GetClass() == "PCB_VIA":
            p = item.GetPosition()
            vias[name].append((kb.mm(p.x), kb.mm(p.y), kb.via_diameter_mm(item), kb.via_drill_mm(item)))
        else:
            a, b = item.GetStart(), item.GetEnd()
            tracks[name].append((kb.mm(a.x), kb.mm(a.y), kb.mm(b.x), kb.mm(b.y), kb.mm(item.GetLength()),
                                 board.GetLayerName(item.GetLayer())))
    out = {}
    for name in bus_nets:
        # terminals: pads (on their own layers) and vias (on every layer); a track end within a terminal's radius on
        # a layer the terminal reaches belongs to it; a track passing under a pad on an inner layer does not stop
        terminals = [(x, y, r, label, layers) for (x, y, r, label, layers) in pads[name]]
        terminals += [(x, y, d / 2, f"via@{x:.3f},{y:.3f}", None) for (x, y, d, _) in vias[name]]

        def terminal_of(x, y, layer):
            for (tx, ty, tr, label, layers) in terminals:
                if (layers is None or layer in layers) and math.hypot(x - tx, y - ty) <= tr + 1e-3:
                    return label
            return None

        # per layer, the tracks form chains between terminals; walk each chain from a terminal end
        by_layer = defaultdict(list)
        for t in tracks[name]:
            by_layer[t[5]].append(t)
        links = []
        for layer, ts in by_layer.items():
            adj = defaultdict(list)
            for idx, (ax, ay, bx, by, L, _) in enumerate(ts):
                adj[_key(ax, ay)].append((idx, _key(bx, by)))
                adj[_key(bx, by)].append((idx, _key(ax, ay)))
            used = set()
            # start from track ends that lie on a terminal
            starts = [(k, terminal_of(k[0] / 1000, k[1] / 1000, layer)) for k in adj]
            starts = [(k, lab) for k, lab in starts if lab]
            for k0, lab0 in starts:
                for idx, nxt in adj[k0]:
                    if idx in used:
                        continue
                    used.add(idx)
                    length = ts[idx][4]
                    cur, prev_idx = nxt, idx
                    points = [(k0[0] / 1000, k0[1] / 1000), (cur[0] / 1000, cur[1] / 1000)]
                    lab = terminal_of(cur[0] / 1000, cur[1] / 1000, layer)
                    while lab is None:
                        cands = [(i2, n2) for i2, n2 in adj[cur] if i2 != prev_idx and i2 not in used]
                        if not cands:
                            break
                        i2, n2 = cands[0]
                        used.add(i2)
                        length += ts[i2][4]
                        prev_idx, cur = i2, n2
                        points.append((cur[0] / 1000, cur[1] / 1000))
                        lab = terminal_of(cur[0] / 1000, cur[1] / 1000, layer)
                    if lab is None or lab == lab0:  # a stub inside a terminal, or copper that ends nowhere
                        continue
                    links.append((lab0, lab, layer, round(length, 3), points))
        out[name] = {"vias": vias[name], "links": links, "pads": [(lab, x, y) for (x, y, _, lab, _) in pads[name]]}
    return out


# --- the judgement of D27: matched as the reference matches -------------------------------------------------------
def judge(candidate: dict, reference: dict, pair_mm: float = 0.2) -> dict:
    """Each data lane within the reference's own lane spread on total length, each differential pair within
    ``pair_mm``, the address/command group within the reference's spread at each memory's pins. Returns
    {"passed": bool, "lines": [...], "failures": [...]}."""
    lines, failures = [], []
    for g, r in reference["groups"].items():
        c = candidate["groups"].get(g)
        if c is None:
            failures.append(f"{g}: absent"); continue
        if g.startswith("lane"):
            ok = c["total_length_mm"]["spread"] <= r["total_length_mm"]["spread"] + 1e-3
            lines.append(f"{g}: spread {c['total_length_mm']['spread']} mm (reference {r['total_length_mm']['spread']}) "
                         f"{'ok' if ok else 'FAIL'}; nets {c['nets']} of {r['nets']}")
            if not ok or c["nets"] != r["nets"]:
                failures.append(f"{g}: spread {c['total_length_mm']['spread']} > {r['total_length_mm']['spread']} mm"
                                if not ok else f"{g}: {c['nets']} nets, reference {r['nets']}")
        elif g == "address/command":
            for dest, rm in r["to_each_memory_mm"].items():
                if not dest.startswith(tuple(reference["bus_parts"])):
                    continue  # terminations are single nets
                cm = c["to_each_memory_mm"].get(dest)
                if cm is None:
                    failures.append(f"{g} at {dest}: no paths"); continue
                ok = cm["spread"] <= rm["spread"] + 1e-3 and cm["nets"] == rm["nets"]
                lines.append(f"{g} at {dest}: spread {cm['spread']} mm over {cm['nets']} nets (reference "
                             f"{rm['spread']} over {rm['nets']}) {'ok' if ok else 'FAIL'}")
                if not ok:
                    failures.append(f"{g} at {dest}: spread {cm['spread']} > {rm['spread']} mm or {cm['nets']} nets of {rm['nets']}")
        for pair, mis in r["pair_mismatch_mm"].items():
            cm = c["pair_mismatch_mm"].get(pair)
            ok = cm is not None and cm <= pair_mm + 1e-3
            lines.append(f"pair {pair}: mismatch {cm} mm (limit {pair_mm}) {'ok' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"pair {pair}: mismatch {cm} > {pair_mm} mm")
    unreached = [n for n, d in candidate["nets"].items() if d["unreached"]]
    if unreached:
        failures.append(f"{len(unreached)} nets with pads not reached: {unreached[:8]}")
    return {"passed": not failures, "lines": lines, "failures": failures}
