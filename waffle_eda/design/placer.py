"""Placement for a class A board: the interface parts at their locked edges, parts with no net in the free
corners, and the rest by simulated annealing on wire length with courtyards kept apart (the simplest placer
that serves the closure loop of milestone A, `docs/plan.md`).

What it holds to, and why: an interface's position is a locked constraint (definition.md section 4); a
decoupling capacitor sits next to the supply pin it serves (`docs/lessons/layout-practices.md`, item 7), so a
two-pin part between two power nets is pulled to the pin of the largest part on its supply net; courtyards
never overlap and stay inside the outline by the edge clearance. The run is seeded and deterministic (D25):
the closure loop retries with the next seed.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import pcbnew

from waffle_eda.kicad import board as kb

ROTATIONS = (0, 90, 180, 270)
KEEP_APART_MM = 1.5  # between two parts' boxes: room for a track, and for a 1 mm silkscreen reference
EDGE_PART_MARGIN_MM = 0.5  # a part on an edge sits this far inside the edge clearance
DECOUPLING_WEIGHT = 3.0  # wire-length units per mm between a decoupling capacitor and the pin it serves
ITERATIONS_PER_PART = 4000


@dataclass
class Part:
    ref: str
    fp: pcbnew.FOOTPRINT
    boxes: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)  # rot -> (l, t, r, b) offsets
    pads: dict[int, list[tuple[str, float, float]]] = field(default_factory=dict)  # rot -> [(net, dx, dy)]
    x: float = 0.0
    y: float = 0.0
    rot: int = 0
    fixed: bool = False

    @property
    def nets(self) -> set[str]:
        return {n for n, _x, _y in self.pads[0] if n}

    def box(self, x=None, y=None, rot=None) -> tuple[float, float, float, float]:
        x, y, rot = (self.x if x is None else x), (self.y if y is None else y), (self.rot if rot is None else rot)
        l, t, r, b = self.boxes[rot]
        return x + l, y + t, x + r, y + b


def measure(fp: pcbnew.FOOTPRINT) -> tuple[dict, dict]:
    """The footprint's box and pad offsets at each rotation, read back from pcbnew so no rotation convention
    is assumed (the footprint is left at rotation 0 and the origin)."""
    boxes, pads = {}, {}
    fp.SetPosition(pcbnew.VECTOR2I(0, 0))
    for rot in ROTATIONS:
        fp.SetOrientationDegrees(rot)
        bb = fp.GetBoundingBox(False, False)
        boxes[rot] = (kb.mm(bb.GetLeft()), kb.mm(bb.GetTop()), kb.mm(bb.GetRight()), kb.mm(bb.GetBottom()))
        pads[rot] = [(p.GetNetname(), kb.mm(p.GetPosition().x), kb.mm(p.GetPosition().y)) for p in fp.Pads()]
    fp.SetOrientationDegrees(0)
    return boxes, pads


def _overlap(a, b, gap: float) -> bool:
    return not (a[2] + gap <= b[0] or b[2] + gap <= a[0] or a[3] + gap <= b[1] or b[3] + gap <= a[1])


def _inside(box, inner, tol: float = 0.001) -> bool:
    return box[0] >= inner[0] - tol and box[1] >= inner[1] - tol and box[2] <= inner[2] + tol and box[3] <= inner[3] + tol


class Placer:
    def __init__(self, board: pcbnew.BOARD, fps: dict[str, pcbnew.FOOTPRINT], outline: tuple[float, float, float, float],
                 edge_clearance_mm: float, fixed_edges: dict[str, tuple[str, str]], seed: int = 0):
        """``fixed_edges``: reference -> (edge, along), the interfaces' locked positions."""
        self.rng = random.Random(seed)
        self.outline = outline
        self.inner = (outline[0] + edge_clearance_mm, outline[1] + edge_clearance_mm,
                      outline[2] - edge_clearance_mm, outline[3] - edge_clearance_mm)
        self.parts: dict[str, Part] = {}
        for ref, fp in fps.items():
            boxes, pads = measure(fp)
            self.parts[ref] = Part(ref, fp, boxes, pads)
        self.fixed_edges = fixed_edges
        self.nets: dict[str, list[tuple[str, int]]] = {}  # net -> [(ref, pad index)]
        for p in self.parts.values():
            for i, (net, _x, _y) in enumerate(p.pads[0]):
                if net:
                    self.nets.setdefault(net, []).append((p.ref, i))
        self.decoupling = self._decoupling_pairs()

    # --- what serves what -----------------------------------------------------------------------------------
    def _decoupling_pairs(self) -> list[tuple[str, int, str, int]]:
        """(capacitor, its pad, part, that part's pad) for every two-pin part between two nets that both reach a
        power pin of a larger part: it is a decoupling capacitor, and it belongs at that part's supply pin."""
        pairs = []
        for cap in self.parts.values():
            if len(cap.pads[0]) != 2 or not str(cap.fp.GetFPID().GetLibNickname()).lower().startswith("capacitor"):
                continue
            nets = [n for n, _x, _y in cap.pads[0]]
            if len(set(nets)) != 2:
                continue
            served = [p for p in self.parts.values() if p.ref != cap.ref and len(p.pads[0]) > 2 and set(nets) <= p.nets]
            if not served:
                continue
            ic = max(served, key=lambda p: len(p.pads[0]))
            gnd_like = min(nets, key=lambda n: (("gnd" not in n.lower()), n))  # the other net is the supply
            supply = next(n for n in nets if n != gnd_like) if len(set(nets)) == 2 else nets[0]
            cap_pad = next(i for i, (n, _x, _y) in enumerate(cap.pads[0]) if n == supply)
            ic_pad = next(i for i, (n, _x, _y) in enumerate(ic.pads[0]) if n == supply)
            pairs.append((cap.ref, cap_pad, ic.ref, ic_pad))
        return pairs

    # --- placement of the fixed parts ------------------------------------------------------------------------
    def place_fixed(self) -> None:
        x0, y0, x1, y1 = self.outline
        m = (self.inner[0] - x0) + EDGE_PART_MARGIN_MM
        for ref, (edge, along) in self.fixed_edges.items():
            p = self.parts[ref]
            # the part's long axis lies along the edge: rotation 0 or 90, whichever makes it so
            l, t, r, b = p.boxes[0]
            tall = (b - t) >= (r - l)
            rot = 0 if (tall == (edge in ("left", "right"))) else 90
            l, t, r, b = p.boxes[rot]
            if edge == "left":
                x, y = x0 + m - l, (y0 + y1) / 2 - (t + b) / 2
            elif edge == "right":
                x, y = x1 - m - r, (y0 + y1) / 2 - (t + b) / 2
            elif edge == "top":
                x, y = (x0 + x1) / 2 - (l + r) / 2, y0 + m - t
            else:
                x, y = (x0 + x1) / 2 - (l + r) / 2, y1 - m - b
            if along != "centred":  # "<n> mm from <end>"
                n, end = float(along.split()[0]), along.split()[-1]
                if end == "left":
                    x = x0 + n - l
                elif end == "right":
                    x = x1 - n - r
                elif end == "top":
                    y = y0 + n - t
                else:
                    y = y1 - n - b
            p.x, p.y, p.rot, p.fixed = round(x, 1), round(y, 1), rot, True

    def corner_parts(self) -> list[Part]:
        return [p for p in self.parts.values() if not p.nets and p.ref not in self.fixed_edges]

    def place_corners(self) -> list[str]:
        """Parts with no net (mounting holes) in the free corners, the farthest apart first; returns the
        references that found no corner. Every part already placed is an obstacle."""
        x0, y0, x1, y1 = self.inner
        corners = [(x1, y0), (x0, y1), (x1, y1), (x0, y0)]
        loose = self.corner_parts()
        for p in loose:
            p.fixed = False
        placed = [p for p in self.parts.values() if p.fixed or (p.nets and p.x)]
        left = []
        for p in loose:
            l, t, r, b = p.boxes[0]
            for cx, cy in corners:  # snapped to 0.05 mm towards the inside, so rounding never crosses the edge
                x = math.floor((cx - r) * 20) / 20 if cx == x1 else math.ceil((cx - l) * 20) / 20
                y = math.floor((cy - b) * 20) / 20 if cy == y1 else math.ceil((cy - t) * 20) / 20
                box = p.box(x, y, 0)
                if _inside(box, self.inner) and not any(_overlap(box, q.box(), KEEP_APART_MM) for q in placed):
                    p.x, p.y, p.rot, p.fixed = x, y, 0, True
                    placed.append(p)
                    corners.remove((cx, cy))
                    break
            else:
                left.append(p.ref)
        return left

    def set_outline(self, outline: tuple[float, float, float, float]) -> None:
        m = self.inner[0] - self.outline[0]
        self.outline = outline
        self.inner = (outline[0] + m, outline[1] + m, outline[2] - m, outline[3] - m)

    def compact(self) -> bool:  # noqa: C901
        self.compaction = ""
        """Pull the outline in to the placed parts plus the edge margin, keeping the edges that carry a fixed
        part where they are, and re-seat the corner parts. A smaller board is the cheaper one, and the wire
        length the annealer minimises leaves the room where no part needs it. Reverts and returns False when
        the parts do not fit the smaller outline."""
        free = [p for p in self.parts.values() if not p.fixed]
        edge_parts = [self.parts[r] for r in self.fixed_edges]
        if not free:
            return False
        boxes = [p.box() for p in free + edge_parts]
        l, t, r, b = min(x[0] for x in boxes), min(x[1] for x in boxes), max(x[2] for x in boxes), max(x[3] for x in boxes)
        m = (self.inner[0] - self.outline[0]) + EDGE_PART_MARGIN_MM
        used = {e for e, _a in self.fixed_edges.values()}
        x0, y0, x1, y1 = self.outline
        old_outline, old = self.outline, {p.ref: (p.x, p.y, p.rot, p.fixed) for p in self.parts.values()}
        corner_w = max((p.boxes[0][2] - p.boxes[0][0] for p in self.corner_parts()), default=0.0)
        corner_h = max((p.boxes[0][3] - p.boxes[0][1] for p in self.corner_parts()), default=0.0)
        for extra in (0.0, 1.0, 2.0, 3.0):  # widen the pulled-in edges until the corner parts find a corner
            nx0 = x0 if "left" in used else l - m
            ny0 = y0 if "top" in used else t - m
            nx1 = x1 if "right" in used else r + m + (corner_w + KEEP_APART_MM if self.corner_parts() else 0.0) + extra
            ny1 = y1 if "bottom" in used else b + m + extra
            nx1, ny1 = min(nx1, x1), min(ny1, y1)
            if self.corner_parts() and (ny1 - ny0) < 2 * (corner_h + m) and "bottom" not in used:
                ny1 = min(y1, ny0 + 2 * (corner_h + m))
            new = (round(nx0, 1), round(ny0, 1), round(nx1 * 2) / 2, round(ny1 * 2) / 2)
            if new[2] - new[0] >= x1 - x0 - 1e-9 and new[3] - new[1] >= y1 - y0 - 1e-9:
                self.set_outline(old_outline)
                self.compaction = f"nothing to pull in: the parts span {round(r - l, 1)} x {round(b - t, 1)} mm plus margins"
                return False
            self.set_outline(new)
            # the edge parts re-seat on the new edges; the free parts follow the first of them
            before = {p.ref: (p.x, p.y) for p in edge_parts}
            self.place_fixed()
            if edge_parts:
                dx, dy = edge_parts[0].x - before[edge_parts[0].ref][0], edge_parts[0].y - before[edge_parts[0].ref][1]
                for p in free:
                    p.x, p.y = round(p.x + dx, 1), round(p.y + dy, 1)
            unseated = self.place_corners()
            if unseated:
                self.compaction = f"no corner for {unseated} at {new}"
                continue
            invalid = [p.ref for p in self.parts.values() if not self._valid(p, p.x, p.y, p.rot)]
            if not invalid:
                self.compaction = f"pulled in from {old_outline} to {new}"
                return True
            self.compaction = f"{invalid} do not fit {new}"
        self.set_outline(old_outline)
        for p in self.parts.values():
            p.x, p.y, p.rot, p.fixed = old[p.ref]
        return False

    def place_reference_texts(self) -> list[str]:
        """Each reference designator just outside its part's box, on the first of eight places (the four sides,
        then the four corners) where it covers no other part's box, no other text and stays inside the
        outline: silkscreen over a pad is clipped by the solder mask, and two references over each other read
        as neither. A reference with no free place is hidden from the silkscreen (the fab layer keeps its own
        for assembly); their references are returned."""
        placed_boxes = [p.box() for p in self.parts.values()]
        texts: list[tuple[float, float, float, float]] = []
        hidden = []
        gap = 0.25
        for p in self.parts.values():
            ref = p.fp.Reference()
            l, t, r, b = p.box()
            bb = ref.GetBoundingBox()
            w, h = kb.mm(bb.GetWidth()) + 0.1, kb.mm(bb.GetHeight()) + 0.1
            cx0, cy0 = (l + r) / 2, (t + b) / 2
            candidates = [(cx0, t - gap - h / 2), (cx0, b + gap + h / 2), (l - gap - w / 2, cy0), (r + gap + w / 2, cy0),
                          (l - gap - w / 2, t - gap - h / 2), (r + gap + w / 2, t - gap - h / 2),
                          (l - gap - w / 2, b + gap + h / 2), (r + gap + w / 2, b + gap + h / 2)]
            for cx, cy in candidates:
                box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
                if not _inside(box, self.inner):
                    continue
                if any(_overlap(box, q, 0.0) for q in placed_boxes) or any(_overlap(box, q, 0.0) for q in texts):
                    continue
                ref.SetPosition(pcbnew.VECTOR2I(kb.nm(cx), kb.nm(cy)))
                ref.SetTextAngleDegrees(0)
                ref.SetVisible(True)
                texts.append(box)
                break
            else:
                ref.SetVisible(False)
                hidden.append(p.ref)
        return hidden

    # --- the annealer ---------------------------------------------------------------------------------------
    def _pad_xy(self, ref: str, i: int) -> tuple[float, float]:
        p = self.parts[ref]
        _n, dx, dy = p.pads[p.rot][i]
        return p.x + dx, p.y + dy

    def cost(self) -> float:
        total = 0.0
        for net, pins in self.nets.items():
            xs, ys = zip(*(self._pad_xy(r, i) for r, i in pins))
            total += (max(xs) - min(xs)) + (max(ys) - min(ys))
        for cap, ci, ic, ii in self.decoupling:
            (ax, ay), (bx, by) = self._pad_xy(cap, ci), self._pad_xy(ic, ii)
            total += DECOUPLING_WEIGHT * math.hypot(ax - bx, ay - by)
        return total

    def _valid(self, p: Part, x: float, y: float, rot: int) -> bool:
        box = p.box(x, y, rot)
        if not _inside(box, self.inner):
            return False
        return not any(_overlap(box, q.box(), KEEP_APART_MM) for q in self.parts.values() if q.ref != p.ref)

    def _random_valid(self, p: Part, tries: int = 2000) -> bool:
        x0, y0, x1, y1 = self.inner
        for _ in range(tries):
            rot = self.rng.choice(ROTATIONS)
            l, t, r, b = p.boxes[rot]
            x = self.rng.uniform(x0 - l, x1 - r)
            y = self.rng.uniform(y0 - t, y1 - b)
            if self._valid(p, x, y, rot):
                p.x, p.y, p.rot = x, y, rot
                return True
        return False

    def pack(self, free: list[Part]) -> list[str]:
        """A first placement that fits whenever the room exists: the free parts in rows across the free area,
        tallest first, each at the first spot along the row where it is valid. Returns what did not fit."""
        x0, y0, x1, y1 = self.inner
        left = []
        order = sorted(free, key=lambda p: -(p.boxes[0][3] - p.boxes[0][1]))
        for p in order:
            l, t, r, b = p.boxes[0]
            done = False
            y = y0 - t
            while y + b <= y1 + 1e-9 and not done:
                x = x0 - l
                while x + r <= x1 + 1e-9:
                    if self._valid(p, round(x, 1), round(y, 1), 0):
                        p.x, p.y, p.rot = round(x, 1), round(y, 1), 0
                        done = True
                        break
                    x += 0.5
                y += 0.5
            if not done:
                left.append(p.ref)
        return left

    def anneal(self) -> float:
        free = [p for p in self.parts.values() if not p.fixed]
        unplaced = self.pack(free)
        if unplaced:
            raise RuntimeError(f"no room for {unplaced} inside the outline {self.inner}")
        if not free:
            return self.cost()
        current = self.cost()
        best, best_state = current, {p.ref: (p.x, p.y, p.rot) for p in free}
        n = ITERATIONS_PER_PART * len(free)
        t0 = max(current / max(len(self.nets), 1), 1.0)
        t_end = t0 / 500
        span = max(self.inner[2] - self.inner[0], self.inner[3] - self.inner[1])
        for k in range(n):
            t = t0 * (t_end / t0) ** (k / n)
            p = self.rng.choice(free)
            old = (p.x, p.y, p.rot)
            move = self.rng.random()
            if move < 0.15:
                rot = self.rng.choice([r for r in ROTATIONS if r != p.rot])
                x, y = p.x, p.y
            elif move < 0.25 and len(free) > 1:
                q = self.rng.choice([q for q in free if q is not p])
                qold = (q.x, q.y, q.rot)
                p.x, p.y, q.x, q.y = q.x, q.y, p.x, p.y
                if not (self._valid(p, p.x, p.y, p.rot) and self._valid(q, q.x, q.y, q.rot)):
                    p.x, p.y, p.rot = old
                    q.x, q.y, q.rot = qold
                    continue
                new = self.cost()
                if new <= current or self.rng.random() < math.exp((current - new) / t):
                    current = new
                else:
                    p.x, p.y, p.rot = old
                    q.x, q.y, q.rot = qold
                if current < best:
                    best, best_state = current, {r.ref: (r.x, r.y, r.rot) for r in free}
                continue
            else:
                scale = span * (0.05 + 0.5 * (t / t0))
                x, y, rot = p.x + self.rng.gauss(0, scale), p.y + self.rng.gauss(0, scale), p.rot
            x, y = round(x, 1), round(y, 1)  # every position on a 0.1 mm grid, so no rounding afterwards can
            if not self._valid(p, x, y, rot):  # close a gap the keep-apart rule was checked on
                continue
            p.x, p.y, p.rot = x, y, rot
            new = self.cost()
            if new <= current or self.rng.random() < math.exp((current - new) / t):
                current = new
                if current < best:
                    best, best_state = current, {r.ref: (r.x, r.y, r.rot) for r in free}
            else:
                p.x, p.y, p.rot = old
        for p in free:
            p.x, p.y, p.rot = best_state[p.ref]
        return best

    def apply(self) -> None:
        for p in self.parts.values():
            p.fp.SetPosition(pcbnew.VECTOR2I(kb.nm(p.x), kb.nm(p.y)))
            p.fp.SetOrientationDegrees(p.rot)

    def overlaps(self) -> list[tuple[str, str]]:
        ps = list(self.parts.values())
        return [(a.ref, b.ref) for i, a in enumerate(ps) for b in ps[i + 1:] if _overlap(a.box(), b.box(), 0.0)]

    def run(self) -> dict:
        self.place_fixed()
        unseated = self.place_corners()
        if unseated:
            raise RuntimeError(f"no corner for {unseated} inside the outline {self.inner}")
        cost = self.anneal()
        compacted = self.compact()
        self.apply()
        hidden = self.place_reference_texts()
        return {"cost": round(cost, 2), "overlaps": self.overlaps(), "compacted": compacted,
                "compaction": self.compaction, "outline": self.outline, "references_hidden": hidden,
                "positions": {p.ref: (p.x, p.y, p.rot) for p in self.parts.values()},
                "decoupling": [(c, ic) for c, _i, ic, _j in self.decoupling]}
