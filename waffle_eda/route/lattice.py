"""A ball-grid package as a lattice: grid indices, rings, sides, and the coordinate helpers every escape uses.

Conventions: column index ``i`` grows with x (east), row index ``j`` grows with y (south, KiCad's y points down).
Ring 1 is the outermost row or column. Fractional indices address gaps: ``(i + 0.5, j + 0.5)`` is the diagonal gap
between four balls, ``i + 0.5`` at integer ``j`` the channel between two balls of a row. A *side* is the package
edge a ball leaves toward; ``across`` is the index along that edge, ``along`` the distance from the edge inward
(0 at the edge row, negative outside the package).
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass

from waffle_eda.kicad import board as kb

SIDES = ("N", "S", "W", "E")


@dataclass(frozen=True)
class Ball:
    number: str
    i: int
    j: int
    x_mm: float
    y_mm: float
    net: str
    ring: int
    pad_mm: float


class Lattice:
    def __init__(self, footprint):
        self.reference = footprint.GetReference()
        raw = []
        for pad in footprint.Pads():
            pos = pad.GetPosition()
            raw.append((kb.mm(pos.x), kb.mm(pos.y), pad.GetNumber(), pad.GetNetname(), kb.mm(pad.GetSize().x), pad))
        # the grid: the dominant step between pad columns and rows; pads off that grid (fiducials, extra pads at
        # the package edge) do not belong to the lattice and stay obstacles only
        xs = sorted(set(round(x, 3) for x, *_ in raw))
        ys = sorted(set(round(y, 3) for _, y, *_ in raw))
        steps = Counter(round(b - a, 3) for a, b in zip(xs, xs[1:])) + Counter(round(b - a, 3) for a, b in zip(ys, ys[1:]))
        self.pitch = steps.most_common(1)[0][0]
        modal_size = Counter(round(size, 3) for *_, size, _ in raw).most_common(1)[0][0]
        grid = [r for r in raw if abs(r[4] - modal_size) < 0.02]
        self.x0 = min(x for x, *_ in grid)
        self.y0 = min(y for _, y, *_ in grid)
        on_grid = []
        self.off_grid = []
        for r in raw:
            fi, fj = (r[0] - self.x0) / self.pitch, (r[1] - self.y0) / self.pitch
            if abs(fi - round(fi)) < 0.1 and abs(fj - round(fj)) < 0.1 and round(fi) >= 0 and round(fj) >= 0:
                on_grid.append(r)
            else:
                self.off_grid.append(r[2])
        self.cols = max(round((x - self.x0) / self.pitch) for x, *_ in on_grid) + 1
        self.rows = max(round((y - self.y0) / self.pitch) for _, y, *_ in on_grid) + 1
        self.balls: dict[str, Ball] = {}
        self.by_index: dict[tuple[int, int], Ball] = {}
        self.pads = {}
        for x, y, number, net, size, pad in on_grid:
            i = round((x - self.x0) / self.pitch)
            j = round((y - self.y0) / self.pitch)
            ring = 1 + min(i, j, self.cols - 1 - i, self.rows - 1 - j)
            ball = Ball(number, i, j, x, y, net, ring, size)
            self.balls[number] = ball
            self.by_index[(i, j)] = ball
            self.pads[number] = pad
        self.pad_mm = statistics.median(b.pad_mm for b in self.balls.values())

    # --- coordinates -------------------------------------------------------------------------------------------
    def X(self, i: float) -> float:
        return self.x0 + i * self.pitch

    def Y(self, j: float) -> float:
        return self.y0 + j * self.pitch

    def array_bbox_mm(self, margin_pitches: float = 0.5) -> tuple[float, float, float, float]:
        m = margin_pitches * self.pitch
        return (self.x0 - m, self.y0 - m, self.X(self.cols - 1) + m, self.Y(self.rows - 1) + m)

    def inside_array(self, x: float, y: float, margin_pitches: float = 0.5) -> bool:
        x0, y0, x1, y1 = self.array_bbox_mm(margin_pitches)
        return x0 <= x <= x1 and y0 <= y <= y1

    # --- sides ---------------------------------------------------------------------------------------------------
    def distances(self, ball: Ball) -> dict[str, int]:
        return {"N": ball.j, "S": self.rows - 1 - ball.j, "W": ball.i, "E": self.cols - 1 - ball.i}

    def nearest_side(self, ball: Ball) -> str:
        d = self.distances(ball)
        return min(SIDES, key=lambda s: d[s])

    def side_coords(self, ball: Ball, side: str) -> tuple[float, int]:
        """(across, along) of a ball seen from ``side``."""
        d = self.distances(ball)
        across = ball.i if side in "NS" else ball.j
        return across, d[side]

    def edge_len(self, side: str) -> int:
        return self.cols if side in "NS" else self.rows

    def pt(self, side: str, across: float, along: float) -> tuple[float, float]:
        """Board position (mm) of lattice coordinates seen from ``side``; ``along`` negative is outside the package."""
        if side == "N":
            return (self.X(across), self.Y(along))
        if side == "S":
            return (self.X(across), self.Y(self.rows - 1 - along))
        if side == "W":
            return (self.X(along), self.Y(across))
        return (self.X(self.cols - 1 - along), self.Y(across))

    def key(self, side: str, across: float, along: float) -> tuple[float, float]:
        """Canonical (i, j) lattice key of a position seen from ``side``, for bookkeeping of used sites and lines."""
        if side == "N":
            return (across, along)
        if side == "S":
            return (across, self.rows - 1 - along)
        if side == "W":
            return (along, across)
        return (self.cols - 1 - along, across)

    def facing_side(self, other_x_mm: float, other_y_mm: float) -> str:
        """The side of this package that faces a point (another package's centre)."""
        cx = (self.x0 + self.X(self.cols - 1)) / 2
        cy = (self.y0 + self.Y(self.rows - 1)) / 2
        dx, dy = other_x_mm - cx, other_y_mm - cy
        if abs(dx) >= abs(dy):
            return "E" if dx > 0 else "W"
        return "S" if dy > 0 else "N"
