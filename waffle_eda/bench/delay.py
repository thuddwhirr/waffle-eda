"""Propagation delay per copper layer: the quantity the vendor rules are written in, which copper length is only
a proxy for (D45, D47, and `docs/research/ddr3-bus-routing.md` section 1).

A signal on an outer layer runs over solder mask and air on one side and dielectric on the other; a signal on an
inner layer runs with dielectric on both sides. The outer line therefore sees a lower effective permittivity and
travels faster -- about 5.6 against 7.1 ps/mm on FR-4 -- so two nets of equal copper length have different delay
when they use different layers, and a rule stated in millimetres is ambiguous until the layers are known.

TI is the only vendor that states the convention: "all length-matching is based on an equivalent stripline
length" (SPRABI1). That is the quantity :func:`equivalent_stripline_mm` returns, and it is what makes a delay
comparable to a tolerance published in mils.

**The model.** IPC-2141's effective permittivity, one formula family for both layer kinds so the two numbers are
derived the same way rather than quoted from two different rules of thumb:

    t_pd = sqrt(er_eff) / c,    er_eff = er (stripline), 0.475 er + 0.67 (surface microstrip)

At the er of 4.5 that ButterStick's own stackup records this gives 5.59 ps/mm on an outer layer, which is the
5.6 ps/mm figure the research note quotes; the same formula puts stripline at 7.08 ps/mm rather than the 6.7
ps/mm that note quotes, because 6.7 comes from a rule of thumb assuming er = 4.0. The formula is used for both,
and every report prints the ps/mm it used.

**Provenance.** The permittivity comes from the board's own stackup when the file records one (KiCad writes
`epsilon_r` per dielectric) and from :data:`DEFAULT_ER` when it does not, and :attr:`Stackup.source` says which.
Of the three class C references only ButterStick records a stackup. The stackup is read from the board file
rather than through `pcbnew`, whose `GetStackupDescriptor` returns an untyped SwigPyObject in KiCad 9 (see the
pitfalls in `waffle_eda/kicad/board.py`).

**The assumption this makes, stated so a reader can reject it.** Every outer copper layer is taken to be
microstrip and every inner one stripline. An inner layer is only truly stripline if a plane references it on both
sides; none of the class C references is routed otherwise on its bus layers, but a board that is would need the
plane structure read rather than assumed.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

C_MM_PER_PS = 0.299792458  # speed of light in vacuum

DEFAULT_ER = 4.5  # FR-4 at the value ButterStick's own stackup records; PCBWay's profile spans 4.45 to 4.74
OUTER_LAYERS = ("F.Cu", "B.Cu")


def er_effective(er: float, outer: bool) -> float:
    """IPC-2141 effective permittivity: the dielectric alone for stripline, reduced for a surface microstrip
    whose field runs partly in air."""
    return 0.475 * er + 0.67 if outer else er


def ps_per_mm(er: float, outer: bool) -> float:
    """Propagation delay per millimetre of copper on a layer of this kind."""
    return math.sqrt(er_effective(er, outer)) / C_MM_PER_PS


def is_outer(layer_name: str) -> bool:
    """Whether a layer is outer, from its name alone. Only for a layer the board did not declare: KiCad lets a
    board rename its copper layers (LogicBone calls its inner ones ``Sig2.Cu`` and ``Gnd3.Cu``), so a board's own
    layers are classified by identity in :func:`stackup_of` instead."""
    return layer_name in OUTER_LAYERS


@dataclass
class Stackup:
    """The per-layer propagation model of one board."""

    er: float
    source: str  # where the permittivity came from, printed with every result
    layers: dict = field(default_factory=dict)  # layer name -> ps/mm, for the layers the board actually has

    @property
    def stripline_ps_per_mm(self) -> float:
        return ps_per_mm(self.er, outer=False)

    @property
    def microstrip_ps_per_mm(self) -> float:
        return ps_per_mm(self.er, outer=True)

    def rate(self, layer_name: str) -> float:
        """ps/mm on a named copper layer. A layer the board did not declare still gets the right rate for its
        kind, so a candidate routed on a layer the reference never used is measured, not skipped."""
        if layer_name in self.layers:
            return self.layers[layer_name]
        return ps_per_mm(self.er, is_outer(layer_name))

    def delay_ps(self, per_layer_mm: dict) -> float:
        """The delay of a path given its copper length on each layer."""
        return sum(mm * self.rate(name) for name, mm in per_layer_mm.items())

    def equivalent_stripline_mm(self, per_layer_mm: dict) -> float:
        """The path's delay expressed as the stripline length that would take as long: TI's convention, and the
        quantity that can be compared with a tolerance published in mils."""
        return self.delay_ps(per_layer_mm) / self.stripline_ps_per_mm

    def describe(self) -> str:
        return (f"er {self.er:.2f} ({self.source}); microstrip {self.microstrip_ps_per_mm:.2f}, "
                f"stripline {self.stripline_ps_per_mm:.2f} ps/mm")


_EPSILON = re.compile(r"\(epsilon_r\s+([0-9.]+)\)")
_LAYER = re.compile(r'\(layer\s+"([^"]*)"')


def read_epsilon_r(path: str | Path) -> list[float]:
    """Every *dielectric* permittivity the board file's stackup records, in order. Empty when the file has no
    stackup, which is the common case: KiCad only writes one once the board's stackup has been edited.

    Only the layers named ``dielectric N`` count. KiCad also writes an ``epsilon_r`` for the solder mask on a
    board where one has been set, and a mask's permittivity averaged in with the laminate's would pull the whole
    model towards a number no signal ever travels through.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    start = text.find("(stackup")
    if start < 0:
        return []
    end = text.find("(pad_to_mask_clearance", start)
    block = text[start:end if end > start else start + 20000]
    starts = [(m.start(), m.group(1)) for m in _LAYER.finditer(block)]
    out = []
    for i, (at, name) in enumerate(starts):
        if not name.startswith("dielectric"):
            continue
        body = block[at:starts[i + 1][0] if i + 1 < len(starts) else len(block)]
        found = _EPSILON.search(body)
        if found:
            out.append(float(found.group(1)))
    return out


def stackup_of(board, path: str | Path | None = None) -> Stackup:
    """The propagation model of ``board``, from the board file's own stackup where it records one.

    Several dielectrics with different permittivities are averaged: a per-layer model would need to know which
    dielectric each signal layer is referenced to, which the file does not say.
    """
    # imported here, not at the top: everything else in this module is arithmetic on numbers a caller already
    # has, so the delay model stays usable and testable on an interpreter with no KiCad bindings
    from waffle_eda.kicad import board as kb

    path = path or board.GetFileName()
    ers = read_epsilon_r(path) if path else []
    if ers:
        er = sum(ers) / len(ers)
        source = (f"the board's stackup, {len(ers)} dielectric{'s' if len(ers) > 1 else ''}"
                  + ("" if len(set(ers)) == 1 else f", {min(ers):.2f} to {max(ers):.2f}, averaged"))
    else:
        er, source = DEFAULT_ER, "no stackup in the board file; FR-4 default"
    # outer by identity, not by name: ``CuStack`` runs front to back, so its two ends are the outer layers
    stack = kb.copper_layers(board)
    outer_ids = {stack[0][0], stack[-1][0]} if stack else set()
    layers = {name: ps_per_mm(er, layer_id in outer_ids) for layer_id, name in stack}
    return Stackup(er=er, source=source, layers=layers)
