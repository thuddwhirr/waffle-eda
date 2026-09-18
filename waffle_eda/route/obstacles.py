"""An index of the copper a new item must clear: pads, tracks, vias and graphic copper, with KiCad's own shape
collision. Items are bucketed on a coarse grid so a clearance query touches only the cells an inflated bounding box
covers; a BGA region on a real board holds thousands of items and the escape router makes tens of thousands of queries.
"""
from __future__ import annotations

from collections import defaultdict

import pcbnew

from waffle_eda.kicad import board as kb

CELL_NM = 1_000_000  # 1 mm buckets


class Obstacles:
    def __init__(self, board: pcbnew.BOARD, region_mm: tuple[float, float, float, float] | None = None,
                 items=None):
        """The board's copper inside ``region_mm``; with ``items`` (possibly empty) only those items."""
        self.board = board
        self.cells: dict[tuple[int, int], list] = defaultdict(list)
        self.count = 0
        if items is not None:
            for item in items:
                self.add(item)
            return
        window = None
        if region_mm:
            x0, y0, x1, y1 = region_mm
            window = pcbnew.BOX2I(pcbnew.VECTOR2I(kb.nm(x0), kb.nm(y0)), pcbnew.VECTOR2I(kb.nm(x1 - x0), kb.nm(y1 - y0)))
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                bb = pad.GetBoundingBox()
                if window is None or window.Intersects(bb):
                    self._insert(pad.GetNetname(), bb, pad, "pad")
        for t in board.GetTracks():
            bb = t.GetBoundingBox()
            if window is None or window.Intersects(bb):
                self._insert(t.GetNetname(), bb, t, "via" if t.GetClass() == "PCB_VIA" else "track")
        # graphic copper: logos, text and shapes drawn on a copper layer carry no net and block that layer
        copper = set(board.GetEnabledLayers().CuStack())
        drawings = list(board.GetDrawings())
        for fp in board.GetFootprints():
            drawings.extend(fp.GraphicalItems())
        for d in drawings:
            if d.GetLayer() not in copper:
                continue
            bb = d.GetBoundingBox()
            if window is None or window.Intersects(bb):
                self._insert("", bb, d, "shape")

    @staticmethod
    def _cells(bb: pcbnew.BOX2I):
        cx0, cy0 = bb.GetLeft() // CELL_NM, bb.GetTop() // CELL_NM
        cx1, cy1 = bb.GetRight() // CELL_NM, bb.GetBottom() // CELL_NM
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                yield (cx, cy)

    def _insert(self, net: str, bb: pcbnew.BOX2I, item, kind: str) -> None:
        entry = (net, bb, item, kind)
        for cell in self._cells(bb):
            self.cells[cell].append(entry)
        self.count += 1

    def add(self, item) -> None:
        kind = "via" if item.GetClass() == "PCB_VIA" else "pad" if item.GetClass() == "PAD" else "track"
        self._insert(item.GetNetname(), item.GetBoundingBox(), item, kind)

    def remove(self, item) -> None:
        for cell in self._cells(item.GetBoundingBox()):
            self.cells[cell] = [e for e in self.cells[cell] if e[2] is not item]

    def vias(self):
        seen = set()
        for entries in self.cells.values():
            for net, bb, item, kind in entries:
                if kind == "via" and id(item) not in seen:
                    seen.add(id(item))
                    yield item

    @staticmethod
    def _hole_shape(other, kind):
        """The drilled hole of a via or a through-hole pad as a shape, or None."""
        if kind == "via":
            return pcbnew.SHAPE_CIRCLE(other.GetPosition(), other.GetDrillValue() // 2)
        if kind == "pad" and other.GetDrillSize().x > 0:
            try:
                return other.GetEffectiveHoleShape()
            except Exception:
                return pcbnew.SHAPE_CIRCLE(other.GetPosition(), other.GetDrillSize().x // 2)
        return None

    def clear(self, item, clearance_mm: float, skip=None, hole_clearance_mm: float = 0.0) -> object | None:
        """The first other-net obstacle ``item`` collides with at ``clearance_mm`` (copper to copper) or at
        ``hole_clearance_mm`` (a hole's wall to copper), or None when it clears all."""
        for other in self._collisions(item, clearance_mm, hole_clearance_mm):
            return other
        return None

    def hits(self, item, clearance_mm: float, hole_clearance_mm: float = 0.0) -> frozenset:
        """Every obstacle ``item`` collides with, of any net, as (class, net name) pairs. Same-net copper is
        included, so a caller can share one geometric answer between nets: the item is clear for net N when every
        hit is of net N."""
        return frozenset((other.GetClass(), other.GetNetname()) for other in self._collisions(item, clearance_mm, hole_clearance_mm, any_net=True))

    def _collisions(self, item, clearance_mm: float, hole_clearance_mm: float = 0.0, any_net: bool = False):
        clr = kb.nm(clearance_mm)
        hole_clr = kb.nm(hole_clearance_mm) if hole_clearance_mm else 0
        net = item.GetNetname()
        is_via = item.GetClass() == "PCB_VIA"
        layer = None if is_via else item.GetLayer()
        bb = item.GetBoundingBox()  # returned by value: inflating it does not touch the item
        bb.Inflate(max(clr, hole_clr))
        shape = item.GetEffectiveShape()
        own_hole = pcbnew.SHAPE_CIRCLE(item.GetPosition(), item.GetDrillValue() // 2) if (is_via and hole_clr) else None
        seen = set()
        for cell in self._cells(bb):
            for onet, obb, other, kind in self.cells.get(cell, ()):
                if id(other) in seen or not obb.Intersects(bb):
                    continue
                if onet == net and kind != "shape" and not any_net:
                    continue
                seen.add(id(other))
                if other is item:
                    continue
                if self._collides(other, kind, shape, clr, layer, is_via, own_hole, hole_clr):
                    yield other

    def _collides(self, other, kind, shape, clr, layer, is_via, own_hole, hole_clr) -> bool:
        if kind == "pad":
            if is_via:
                for L in other.GetLayerSet().CuStack():
                    if other.GetEffectiveShape(L).Collide(shape, clr):
                        return True
            elif other.IsOnLayer(layer) and other.GetEffectiveShape(layer).Collide(shape, clr):
                return True
        elif kind == "shape":
            if is_via or other.GetLayer() == layer:
                try:
                    if other.GetEffectiveShape(other.GetLayer()).Collide(shape, clr):
                        return True
                except Exception:  # text and unusual shapes: the bounding box already intersects
                    return True
        elif kind == "via" or is_via or other.IsOnLayer(layer):
            if other.GetEffectiveShape().Collide(shape, clr):
                return True
        if hole_clr and kind in ("via", "pad"):
            # the other item's hole against our copper
            hole = self._hole_shape(other, kind)
            # our item's shape is the receiver: a Python-built SHAPE_CIRCLE only accepts a SEG (board.py)
            if hole is not None and shape.Collide(hole, hole_clr):
                return True
        if own_hole is not None and kind in ("pad", "track", "via", "shape"):
            # our via's hole against the other item's copper, on any layer it has
            if kind == "pad":
                for L in other.GetLayerSet().CuStack():
                    if other.GetEffectiveShape(L).Collide(own_hole, hole_clr):
                        return True
            else:
                try:
                    other_shape = other.GetEffectiveShape() if kind != "shape" else other.GetEffectiveShape(other.GetLayer())
                    if other_shape.Collide(own_hole, hole_clr):
                        return True
                except Exception:
                    pass
        return False
