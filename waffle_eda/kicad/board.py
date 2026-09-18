"""Thin helpers over KiCad 9's ``pcbnew`` Python API.

Every pitfall the last project paid for (docs/lessons/tooling-project-brief.md, section 7) is encoded here so that no
stage repeats it:

* Zone fills are not updated automatically. A freshly generated or freshly loaded legacy board has no usable fills;
  call :func:`refill_zones` before DRC or any connectivity check, or vias read as clearance errors.
* In KiCad 9 a via has a padstack, and ``PCB_VIA.GetWidth()`` without a layer asserts. Use :func:`via_diameter_mm`.
* ``GetFilledPolysList`` returns a reference that can dangle; copy the polygon set before the board changes.
* Connectivity queries are unreliable across calls; keep your own union-find when a stage needs connectivity.
* Reshaping a zone's outline in place leaves the filler with stale data; replace the zone by a new object.
* Footprint parents need casting; use ``m_Uuid.AsString()`` for identity.
* Remove an item with ``board.Delete(item)``, not ``board.Remove(item)``: after Remove the Python proxy owns a
  C++ object with no destructor and SWIG prints a memory-leak warning per item.
* Every iteration of ``board.GetTracks()`` or ``fp.Pads()`` yields new proxy objects for the same C++ items, so
  ``is`` and ``id()`` never identify an item across calls; compare ``m_Uuid.AsString()``. An index that keeps a
  proxy of an item the board has since deleted holds a dangling pointer, and the next collision test segfaults.
* A shape built in Python (``pcbnew.SHAPE_CIRCLE(...)``) exposes only the ``Collide(SEG, ...)`` overload; make the
  shape from ``GetEffectiveShape()`` (typed as the base ``SHAPE``) the receiver and pass the built shape as the
  argument, or the call raises a ``TypeError`` about ``SEG const &``.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pcbnew

NM_PER_MM = 1_000_000


def mm(nanometres: int | float) -> float:
    """KiCad internal units (nanometres) to millimetres."""
    return nanometres / NM_PER_MM


def nm(millimetres: float) -> int:
    """Millimetres to KiCad internal units (nanometres)."""
    return int(round(millimetres * NM_PER_MM))


def load_board(path: str | Path) -> pcbnew.BOARD:
    """Load a board file. Legacy (KiCad 5) files load with a best-effort zone conversion; refill before checks."""
    board = pcbnew.LoadBoard(str(path))
    if board is None:  # pcbnew returns None for a file it cannot parse rather than raising
        raise OSError(f"pcbnew could not load {path}")
    return board


def save_board(board: pcbnew.BOARD, path: str | Path) -> None:
    pcbnew.SaveBoard(str(path), board)


def file_format_version(board: pcbnew.BOARD) -> int | None:
    try:
        return int(board.GetFileFormatVersionAtLoad())
    except Exception:  # older bindings
        return None


def copper_layers(board: pcbnew.BOARD) -> list[tuple[int, str]]:
    """Enabled copper layers as (layer id, name), front to back."""
    return [(layer, board.GetLayerName(layer)) for layer in board.GetEnabledLayers().CuStack()]


def layer_name(board: pcbnew.BOARD, layer: int) -> str:
    return board.GetLayerName(layer)


def refill_zones(board: pcbnew.BOARD) -> None:
    """Recompute every zone fill. Required before DRC and before any connectivity question."""
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())


def outline_bbox_mm(board: pcbnew.BOARD) -> tuple[float, float, float, float]:
    bb = board.GetBoardEdgesBoundingBox()
    return (mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))


def outline_size_mm(board: pcbnew.BOARD) -> tuple[float, float]:
    x0, y0, x1, y1 = outline_bbox_mm(board)
    return (x1 - x0, y1 - y0)


def track_segments(board: pcbnew.BOARD) -> list[pcbnew.PCB_TRACK]:
    """Straight track segments only (no vias, no arcs)."""
    return [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]


def track_arcs(board: pcbnew.BOARD) -> list:
    return [t for t in board.GetTracks() if t.GetClass() == "PCB_ARC"]


def vias(board: pcbnew.BOARD) -> list[pcbnew.PCB_VIA]:
    return [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]


def via_diameter_mm(via: pcbnew.PCB_VIA, layer: int = pcbnew.F_Cu) -> float:
    """Via pad diameter on ``layer``. KiCad 9 asserts on ``GetWidth()`` with no layer, so always pass one."""
    return mm(via.GetWidth(layer))


def via_drill_mm(via: pcbnew.PCB_VIA) -> float:
    return mm(via.GetDrillValue())


def set_via_diameter(via: pcbnew.PCB_VIA, diameter_mm: float) -> None:
    """Set the via pad diameter on every layer, across the KiCad 9 binding variants."""
    try:
        via.SetWidth(nm(diameter_mm))
    except TypeError:
        for layer in via.GetLayerSet().Seq():
            via.SetWidth(layer, nm(diameter_mm))


def net_names(board: pcbnew.BOARD) -> list[str]:
    return [str(name) for name in board.GetNetsByName().keys()]


def nets_matching(board: pcbnew.BOARD, pattern: str | re.Pattern) -> list[str]:
    regex = re.compile(pattern) if isinstance(pattern, str) else pattern
    return sorted(name for name in net_names(board) if regex.search(name))


def footprint(board: pcbnew.BOARD, reference: str) -> pcbnew.FOOTPRINT | None:
    return board.FindFootprintByReference(reference)


@dataclass(frozen=True)
class PackageInfo:
    reference: str
    value: str
    pads: int
    x_mm: float
    y_mm: float
    rotation_deg: float
    back_side: bool
    pad_bbox_mm: tuple[float, float, float, float]  # bbox of pad centres: (x0, y0, x1, y1)
    bbox_mm: tuple[float, float, float, float]  # footprint bounding box without text (courtyard, pads, graphics)

    def in_footprint_mm(self, x: float, y: float) -> bool:
        """True when (x, y) lies inside the footprint's bounding box: the brief's "inside the BGA footprint"."""
        x0, y0, x1, y1 = self.bbox_mm
        return x0 <= x <= x1 and y0 <= y <= y1

    def in_pad_array_mm(self, x: float, y: float, margin_mm: float = 0.0) -> bool:
        """True when (x, y) lies within the pad-centre bbox grown by ``margin_mm`` (e.g. half a ball pitch)."""
        x0, y0, x1, y1 = self.pad_bbox_mm
        return (x0 - margin_mm) <= x <= (x1 + margin_mm) and (y0 - margin_mm) <= y <= (y1 + margin_mm)


def package_info(fp: pcbnew.FOOTPRINT) -> PackageInfo:
    xs, ys = [], []
    for pad in fp.Pads():
        p = pad.GetPosition()
        xs.append(mm(p.x))
        ys.append(mm(p.y))
    pos = fp.GetPosition()
    bb = fp.GetBoundingBox(False, False)  # no text, no invisible text
    return PackageInfo(
        reference=fp.GetReference(),
        value=fp.GetValue(),
        pads=len(xs),
        x_mm=mm(pos.x),
        y_mm=mm(pos.y),
        rotation_deg=float(fp.GetOrientationDegrees()),
        back_side=bool(fp.IsFlipped()),
        pad_bbox_mm=(min(xs), min(ys), max(xs), max(ys)) if xs else (mm(pos.x), mm(pos.y), mm(pos.x), mm(pos.y)),
        bbox_mm=(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())),
    )


@dataclass
class NetCopper:
    """Copper of one net: total routed length, segment and via counts, layers used, via positions."""
    net: str
    length_mm: float = 0.0
    segments: int = 0
    via_count: int = 0
    layers: tuple[str, ...] = ()
    via_positions_mm: tuple[tuple[float, float], ...] = ()
    track_widths_mm: tuple[tuple[float, int], ...] = ()


def net_copper(board: pcbnew.BOARD, nets: Iterable[str]) -> dict[str, NetCopper]:
    wanted = set(nets)
    result = {name: NetCopper(net=name) for name in wanted}
    layers: dict[str, set[str]] = {name: set() for name in wanted}
    via_pos: dict[str, list[tuple[float, float]]] = {name: [] for name in wanted}
    widths: dict[str, Counter] = {name: Counter() for name in wanted}
    for item in board.GetTracks():
        name = item.GetNetname()
        if name not in wanted:
            continue
        cls = item.GetClass()
        nc = result[name]
        if cls in ("PCB_TRACK", "PCB_ARC"):
            nc.length_mm += mm(item.GetLength())
            nc.segments += 1
            layers[name].add(board.GetLayerName(item.GetLayer()))
            widths[name][round(mm(item.GetWidth()), 3)] += 1
        elif cls == "PCB_VIA":
            nc.via_count += 1
            p = item.GetPosition()
            via_pos[name].append((mm(p.x), mm(p.y)))
    for name, nc in result.items():
        nc.layers = tuple(sorted(layers[name]))
        nc.via_positions_mm = tuple(via_pos[name])
        nc.track_widths_mm = tuple(sorted(widths[name].items()))
    return result


def track_width_histogram_mm(board: pcbnew.BOARD) -> list[tuple[float, int]]:
    counter = Counter(round(mm(t.GetWidth()), 3) for t in track_segments(board))
    return counter.most_common()


def via_size_histogram_mm(board: pcbnew.BOARD) -> list[tuple[float, float, int]]:
    counter = Counter((round(via_diameter_mm(v), 2), round(via_drill_mm(v), 2)) for v in vias(board))
    return [(d, drill, n) for (d, drill), n in counter.most_common()]
