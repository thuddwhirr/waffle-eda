"""The bus plan of M3a (decisions D37, D38): what is decided before any detailed search, and the check that says
whether it can be built.

A plan is a list of legs. A leg is one net's run between two terminals on one layer: from a pad or a via site to
another, with a coarse route as cells and the room reserved beside it for the length the net still needs. Every
layer change happens at a via site, and a via site belongs to a package's escape style (D32): it is the ball
itself where the package uses in-pad vias, a corner between four balls where it dog-bones, or a cell of the
package's hollow or its margin. The plan also fixes the order in which each bundle crosses each package's
boundary, which is what D28 and D29 found the negotiation cannot decide for itself.

The gate is `check`. It answers five questions, all of them in seconds, because a plan is a much smaller artifact
than a route:

1. is every net planned, its legs joining its pads into one piece?
2. do two legs of one layer cross? (the references cross nowhere, D32)
3. is every via site legal for its package's style, and used by one net only?
4. has every net the room its length deficit needs?
5. are the bus packages' escapes part of the plan, rather than taken from M2 (D36)?

A reference board's own routing can be read back as a plan (`from_reference`), which is the answer key: it must
pass this gate, and if it does not, the gate is wrong before the planner is.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict

from waffle_eda.bench import bus_design
from waffle_eda.kicad import board as kb


@dataclass(frozen=True)
class Site:
    """Where a leg ends: a pad of a package, or a via at a place the package's style allows. Two legs meet where
    they name the same terminal, so the label is the identity, not the coordinates: a track that ends inside a
    via's pad is at that via, and comparing positions to three decimals would miss it."""
    kind: str  # "pad" or "via"
    x: float
    y: float
    package: str = ""  # the package it belongs to, "" outside every one
    label: str = ""  # "REF.pad" for a pad, "via@x,y" for a via
    place: str = ""  # for a via: on the ball / on a corner / in the channel / in the hollow / in the margin

    def key(self) -> str:
        return self.label or f"{self.kind}@{self.x:.3f},{self.y:.3f}"


@dataclass
class Leg:
    net: str
    a: Site
    b: Site
    layer: str  # layer name, so a plan is readable and board-independent
    route: list = field(default_factory=list)  # the coarse route as a polyline, (x, y) in mm
    units: int = 1  # tracks the leg asks for: itself plus the room for its meanders
    reserved_mm: float = 0.0  # the length that room affords
    length_mm: float = 0.0  # the coarse route's own length


@dataclass
class BusPlan:
    board: str  # the reference key, for the record
    legs: list = field(default_factory=list)
    order: dict = field(default_factory=dict)  # "group|package" -> nets in the order they cross the boundary
    deficit_mm: dict = field(default_factory=dict)  # net -> the length it is short of its group
    provenance: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1, default=str)

    @staticmethod
    def from_json(text: str) -> "BusPlan":
        d = json.loads(text)
        legs = [Leg(net=l["net"], a=Site(**l["a"]), b=Site(**l["b"]), layer=l["layer"],
                    route=[tuple(c) for c in l["route"]], units=l["units"], reserved_mm=l["reserved_mm"],
                    length_mm=l["length_mm"]) for l in d["legs"]]
        return BusPlan(board=d["board"], legs=legs, order=d["order"], deficit_mm=d["deficit_mm"],
                       provenance=d.get("provenance", {}))

    def nets(self) -> set:
        return {leg.net for leg in self.legs}


# --- reading a board back as a plan (the answer key) ------------------------------------------------------------------
def _intersection(p, q):
    """Where two segments cross, or None. Touching at an endpoint does not count as crossing."""
    (ax, ay), (bx, by) = p
    (cx, cy), (dx, dy) = q
    r = (bx - ax, by - ay)
    s2 = (dx - cx, dy - cy)
    denom = r[0] * s2[1] - r[1] * s2[0]
    if abs(denom) < 1e-12:
        return None  # parallel, including two runs side by side
    t = ((cx - ax) * s2[1] - (cy - ay) * s2[0]) / denom
    u = ((cx - ax) * r[1] - (cy - ay) * r[0]) / denom
    if 1e-9 < t < 1 - 1e-9 and 1e-9 < u < 1 - 1e-9:
        return (ax + t * r[0], ay + t * r[1])
    return None


def terminals(board, ref) -> tuple:
    """The terminals of every bus net on this board, as a property of the board rather than of any one plan: a map
    from each pad's label to the name of the terminal it belongs to, and per package the terminals its bus balls
    belong to. A plan and the gate that checks it must agree on this or a net whose ball shares copper with a
    resistor pad looks like two pieces to one of them."""
    bus = set(kb.nets_matching(board, ref.bus_net_pattern))
    shapes: dict = defaultdict(list)
    ball_of: dict = defaultdict(set)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() in bus:
                p, size = pad.GetPosition(), pad.GetSize()
                label = f"{fp.GetReference()}.{pad.GetNumber()}"
                shapes[pad.GetNetname()].append((label, kb.mm(p.x), kb.mm(p.y), kb.mm(size.x) / 2, kb.mm(size.y) / 2))
                if fp.GetReference() in ref.bus_parts:
                    ball_of[fp.GetReference()].add((pad.GetNetname(), label))
    names: dict = {}
    for net, pads in shapes.items():
        names[net] = _terminal_names(pads, tuple(ref.bus_parts))
    balls: dict = {part: {names[net][label] for (net, label) in items} for part, items in ball_of.items()}
    return shapes, names, balls


# D32: both references put their bus vias on a ball or on a corner between four balls and never in the channel
# between two neighbouring balls, which is the narrowest gap and the one those balls' own neighbours escape
# through. A package whose board has not escaped it yet has no style to measure, and this is the rule it gets.
CROSS_BOARD_STYLE = {"places": {"on the ball": 0, "on a corner": 0}, "vias": 0,
                     "offsets": ((0.0, 0.0), (0.5, 0.5), (0.5, -0.5), (-0.5, 0.5), (-0.5, -0.5))}


def styles_of(board, ref) -> dict:
    """Each bus package's escape style: the one the board's own vias show where there are any (D32), and the
    cross-board rule where there are none. The planner and the gate ask this same question, so a plan can never
    be built to one rule and judged by another."""
    out = {}
    measured = bus_design.escape_style(board, ref)
    for pkg in bus_design.packages_of(board, ref):
        if pkg.lattice is None:
            continue
        style = measured.get(pkg.reference)
        out[pkg.reference] = style if style and style["vias"] else dict(CROSS_BOARD_STYLE)
    return out


def _terminal_names(pads: list, bus_parts: tuple) -> dict:
    """One name for each terminal of a net. Two pads whose copper overlaps are one terminal: on ButterStick each
    clock ball sits 0.13 to 0.20 mm from its termination resistor's pad, closer than their copper is wide, so the
    two are the same node and a plan that treats them as separate ends says the net falls into two pieces. Where a
    bus package's ball is one of them, it gives the terminal its name."""
    parent = {label: label for (label, *_rest) in pads}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, (la, xa, ya, hxa, hya) in enumerate(pads):
        for (lb, xb, yb, hxb, hyb) in pads[i + 1:]:
            if abs(xa - xb) <= hxa + hxb + 1e-6 and abs(ya - yb) <= hya + hyb + 1e-6:
                ra, rb = find(la), find(lb)
                if ra != rb:
                    parent[ra] = rb
    groups: dict = defaultdict(list)
    for (label, *_rest) in pads:
        groups[find(label)].append(label)
    names = {}
    for members in groups.values():
        on_bus = sorted(m for m in members if m.split(".")[0] in bus_parts)
        chosen = on_bus[0] if on_bus else sorted(members)[0]
        for m in members:
            names[m] = chosen
    return names


def _site_of(label: str, x: float, y: float, packages, pads: list = (), names: dict | None = None) -> Site:
    """The terminal a leg ends on, by the label the reference plan gave it: a pad, or a via whose place comes from
    the package whose area holds it. A via inside one of the net's own pads is that ball's terminal and takes its
    label, because the layer change happens in the pad: keeping them apart would make every in-pad net look as
    though it fell into two pieces."""
    names = names or {}
    if label.startswith("j@"):  # a junction in the net's own copper, where a run branches
        return Site("junction", x, y, label=label)
    if not label.startswith("via@"):
        name = names.get(label, label)
        return Site("pad", x, y, package=name.split(".")[0], label=name)
    for (plabel, px, py, phx, phy) in pads:
        if abs(x - px) <= phx + 1e-3 and abs(y - py) <= phy + 1e-3:
            name = names.get(plabel, plabel)
            return Site("via", x, y, package=name.split(".")[0], label=name, place="on the ball")
    for pkg in packages:
        where = pkg.where(x, y)
        if not where:
            continue
        place = where
        if where == "array" and pkg.lattice is not None:
            cells = bus_design.ball_cells(pkg.lattice, x, y)
            offsets = {(di, dj) for (_, _, _, di, dj) in cells}
            if (0.0, 0.0) in offsets:
                place = "on the ball"
            elif all(abs(di) == 0.5 and abs(dj) == 0.5 for di, dj in offsets):
                place = "on a corner"
            else:
                place = "in the channel"
        elif where == "hollow":
            place = "in the hollow"
        elif where == "margin":
            place = "in the margin"
        return Site("via", x, y, package=pkg.reference, label=label, place=place)
    return Site("via", x, y, label=label, place="outside the packages")


def from_reference(board, ref) -> BusPlan:
    """Read a reference board's own routing back as a plan. This is the answer key of M3a."""
    bus = sorted(kb.nets_matching(board, ref.bus_net_pattern))
    ref_plan = bus_design.reference_plan(board, bus, ref.bus_parts[0])
    packages = bus_design.packages_of(board, ref)
    pad_shape, terminal_names, _balls = terminals(board, ref)
    legs = []
    for net, d in ref_plan.items():
        where = {label: (x, y) for (label, x, y) in d["pads"]}
        for (x, y, _dia, _drill) in d["vias"]:
            where[f"via@{x:.3f},{y:.3f}"] = (x, y)
        for (a, b, layer, length, points) in d["links"]:
            if len(points) < 2:
                continue
            for label, pt in ((a, points[0]), (b, points[-1])):
                where.setdefault(label, tuple(pt))  # a junction is named by where it sits
            pads = pad_shape[net]
            names = terminal_names.get(net, {})
            legs.append(Leg(net=net, a=_site_of(a, *where[a], packages, pads, names),
                            b=_site_of(b, *where[b], packages, pads, names), layer=layer,
                            route=[tuple(pt) for pt in points], length_mm=round(length, 3)))
    order = {}
    for group, v in bus_design.entry_order(board, ref).items():
        for pkg, nets in v["order"].items():
            order[f"{group}|{pkg}"] = nets
    return BusPlan(board=ref.key, legs=legs, order=order,
                   provenance={"source": "the reference's own routing"})


# --- the gate ---------------------------------------------------------------------------------------------------------
@dataclass
class Finding:
    kind: str
    detail: str


def _pieces(legs: list, pads: list) -> int:
    """How many pieces the net's planned copper falls into: its pads and legs joined where they share a site."""
    parts = [({p}, set()) for p in pads]  # (site keys, nothing)
    for leg in legs:
        parts.append(({leg.a.key(), leg.b.key()}, set()))
    parent = list(range(len(parts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            if parts[i][0] & parts[j][0]:
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    return len({find(i) for i in range(len(parts))})


def check(plan: BusPlan, board, ref, styles: dict | None = None) -> list:
    """The M3a gate. Returns the findings; an empty list is a pass."""
    out: list = []
    bus = sorted(kb.nets_matching(board, ref.bus_net_pattern))
    packages = {p.reference: p for p in bus_design.packages_of(board, ref)}
    styles = styles or styles_of(board, ref)

    # 1. every net planned, and its pads joined into one piece
    by_net: dict = defaultdict(list)
    for leg in plan.legs:
        by_net[leg.net].append(leg)
    shapes, names, bus_pads = terminals(board, ref)
    pads_of: dict = defaultdict(set)
    for net, pads in shapes.items():
        for (label, *_rest) in pads:
            pads_of[net].add(names[net].get(label, label))
    for net in bus:
        if not by_net.get(net):
            out.append(Finding("unplanned", f"{bus_design.short_name(net)} has no legs"))
            continue
        n = _pieces(by_net[net], sorted(pads_of[net]))
        if n > 1:
            out.append(Finding("in pieces", f"{bus_design.short_name(net)} falls into {n} pieces"))

    # 2. no two legs of one layer crossing. Exactly, on the routes themselves: two runs side by side share the
    # same neighbourhood for millimetres and a meander weaves within it, so anything coarser reports crossings the
    # copper does not have.
    by_layer: dict = defaultdict(list)
    for leg in plan.legs:
        if len(leg.route) > 1:
            by_layer[leg.layer].append(leg)
    for layer, legs in sorted(by_layer.items()):
        boxes = []
        for leg in legs:
            xs = [x for x, _ in leg.route]
            ys = [y for _, y in leg.route]
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
        for i in range(len(legs)):
            for j in range(i + 1, len(legs)):
                if legs[i].a.key() in (legs[j].a.key(), legs[j].b.key()) or \
                   legs[i].b.key() in (legs[j].a.key(), legs[j].b.key()):
                    continue  # two legs that meet at a terminal touch there by design
                ax0, ay0, ax1, ay1 = boxes[i]
                bx0, by0, bx1, by1 = boxes[j]
                if ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0:
                    continue
                hit = None
                for p in zip(legs[i].route, legs[i].route[1:]):
                    for q in zip(legs[j].route, legs[j].route[1:]):
                        hit = _intersection(p, q)
                        if hit:
                            break
                    if hit:
                        break
                if hit:
                    out.append(Finding("crossing", f"{bus_design.short_name(legs[i].net)} crosses "
                                                   f"{bus_design.short_name(legs[j].net)} on {layer} at "
                                                   f"({hit[0]:.1f}, {hit[1]:.1f})"))

    # 2b. a leg's route has to run between its own terminals, or the crossings and the lengths are of something
    # else entirely
    for leg in plan.legs:
        if len(leg.route) < 2:
            continue
        for site, end in ((leg.a, leg.route[0]), (leg.b, leg.route[-1])):
            if math.hypot(site.x - end[0], site.y - end[1]) > 0.5:
                out.append(Finding("route adrift", f"{bus_design.short_name(leg.net)}'s leg on {leg.layer} ends at "
                                                   f"({end[0]:.2f}, {end[1]:.2f}), {math.hypot(site.x - end[0], site.y - end[1]):.2f} mm "
                                                   f"from its terminal {site.key()}"))

    # 3. via sites legal for the package's style, and one net to a site
    held: dict = {}
    for leg in plan.legs:
        for site in (leg.a, leg.b):
            if site.kind != "via":
                continue
            other = held.setdefault(site.key(), leg.net)
            if other != leg.net:
                out.append(Finding("site shared", f"the via at ({site.x:.2f}, {site.y:.2f}) is used by both "
                                                  f"{bus_design.short_name(other)} and "
                                                  f"{bus_design.short_name(leg.net)}"))
            # a via inside a package's array is judged against that package's own escape style, not against an
            # absolute: OrangeCrab puts three of its own vias in a ball channel, so a gate that forbids it outright
            # fails the board it is meant to certify. A board with no reference of its own gets the cross-board
            # style instead (ball or corner), which `bus_bench` calls BUS_STYLE=diagonal.
            want = {"on the ball": (0.0, 0.0), "on a corner": (0.5, 0.5), "in the channel": (0.5, 0.0)}.get(site.place)
            if site.package and want is not None:
                allowed = {(round(abs(a), 2), round(abs(b), 2)) for a, b in styles.get(site.package, {}).get("offsets", ())}
                if want not in allowed:
                    out.append(Finding("site off style",
                                       f"{bus_design.short_name(leg.net)} puts a via {site.place} of "
                                       f"{site.package} at ({site.x:.2f}, {site.y:.2f}), which its style "
                                       f"({', '.join(sorted(styles.get(site.package, {}).get('places', {}))) or 'no via in the array'}) "
                                       f"does not use"))

    # 4. the room each net's length deficit needs
    room: dict = defaultdict(float)
    for leg in plan.legs:
        room[leg.net] += leg.reserved_mm
    for net, deficit in (plan.deficit_mm or {}).items():
        if deficit > room[net] + 1e-6:
            out.append(Finding("no room", f"{bus_design.short_name(net)} needs {deficit:.1f} mm of meander and the "
                                          f"plan reserves room for {room[net]:.1f} mm"))

    # 5. the escapes of the bus packages belong to the plan
    for part in ref.bus_parts:
        if part not in bus_pads:
            continue
        # a ball is reached whether its leg ends on the bare pad or on the via in that pad
        reached = {site.label for leg in plan.legs for site in (leg.a, leg.b) if site.package == part}
        missing = sorted(bus_pads[part] - reached)
        if missing:
            out.append(Finding("escape missing", f"{len(missing)} ball(s) of {part} have no leg leaving them: "
                                                 + ", ".join(missing[:6])))
    return _dedupe(out)


def _dedupe(findings: list) -> list:
    """One finding per fact: a via is the end of two legs and would otherwise be reported twice."""
    seen = set()
    out = []
    for f in findings:
        k = (f.kind, f.detail)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def report(findings: list) -> str:
    if not findings:
        return "the plan passes: every net planned in one piece, no crossings, every via site legal and its own, " \
               "room for every deficit, every ball escaped"
    counts = Counter(f.kind for f in findings)
    lines = [f"{len(findings)} finding(s): " + ", ".join(f"{k} {v}" for k, v in counts.most_common())]
    lines += [f"   {f.kind}: {f.detail}" for f in findings[:20]]
    if len(findings) > 20:
        lines.append(f"   ... and {len(findings) - 20} more")
    return "\n".join(lines)
