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
    def __init__(self, board: pcbnew.BOARD, region_mm: tuple[float, float, float, float] | None = None):
        self.board = board
        self.cells: dict[tuple[int, int], list] = defaultdict(list)
        self.count = 0
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

    def clear(self, item, clearance_mm: float, skip=None) -> object | None:
        """The first other-net obstacle ``item`` collides with at ``clearance_mm``, or None when it clears all."""
        clr = kb.nm(clearance_mm)
        net = item.GetNetname()
        is_via = item.GetClass() == "PCB_VIA"
        layer = None if is_via else item.GetLayer()
        bb = item.GetBoundingBox()  # returned by value: inflating it does not touch the item
        bb.Inflate(clr)
        shape = item.GetEffectiveShape()
        seen = set()
        for cell in self._cells(bb):
            for onet, obb, other, kind in self.cells.get(cell, ()):
                if id(other) in seen or not obb.Intersects(bb):
                    continue
                if onet == net and kind != "shape":
                    continue
                seen.add(id(other))
                if kind == "pad":
                    if is_via:
                        for L in other.GetLayerSet().CuStack():
                            if other.GetEffectiveShape(L).Collide(shape, clr):
                                return other
                    elif other.IsOnLayer(layer) and other.GetEffectiveShape(layer).Collide(shape, clr):
                        return other
                elif kind == "shape":
                    if is_via or other.GetLayer() == layer:
                        try:
                            if other.GetEffectiveShape(other.GetLayer()).Collide(shape, clr):
                                return other
                        except Exception:  # text and unusual shapes: the bounding box already intersects
                            return other
                elif kind == "via" or is_via or other.IsOnLayer(layer):
                    if other.GetEffectiveShape().Collide(shape, clr):
                        return other
        return None
