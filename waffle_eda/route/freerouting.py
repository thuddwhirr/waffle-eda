"""Stage 5's baseline router for class A: Freerouting, driven headless through KiCad's Specctra export and import.

The plan (D55) has each stage use the cheapest existing tool that passes the class, and for stage 5 of class A
that is Freerouting. This module is the wrapper: it takes a problem board (placement, pads, outline, keepouts,
no copper) and the rules the class A gate measures off the reference (`bench/rebuild.BoardRules`), exports a
DSN, runs the jar under a virtual display, imports the session file and hands the routed board back. The gate
then refills the zones and scores it exactly as before.

What the wrapper has to know, each found by running it (`docs/decisions.md` D56):

* **The version is 2.4.1 and it needs Java 25.** The container's Java is 21; `scripts/fetch_tools.py` puts a JDK
  and the jar under `build/tools/`, and :func:`java` prefers that JDK over the one on the path.
* **`pcbnew.ExportSpecctraDSN` returns False, and writes nothing, when two footprints share a reference.** The
  C++ wrapper swallows the exception. Logos, fiducials and a second `VAL` do that on five of the six class A
  references, so :func:`unique_references` renames the duplicates before the export and restores them after the
  import. The session file names components, so the same board object (with the same renames) has to receive
  the import.
* **The DSN carries the board's net-class values, not the measured rules.** The smoke test routed with the
  file's 0.15 mm clearance against a measured 0.197 and failed 25 times. :func:`apply_rules` writes the
  measured rules into the board's net classes before the export, with a margin, because Freerouting lands a
  little short of its clearance on 45-degree geometry (the old project measured about 0.02 mm).
* **Hole-to-copper is not a Specctra rule.** A hole's copper ring plus the clearance around it has to reach the
  measured hole clearance, so the rule section of the DSN gets typed clearances for vias (and for plated pins
  where the board has them) equal to the measured hole clearance less the smallest ring on the board.
* **Freerouting writes `logs/freerouting.log` into the working directory** on every run; the jar runs with the
  work directory as its cwd so nothing lands in the repository.
* **Two Freerouting runs at once can leave an empty session file.** Twice, with other instances routing other
  boards on the same machine, a run finished its passes, logged "Saving", and wrote 0 bytes (2026-09-24); no
  run alone has ever done that, and memory was not short. Run one board at a time; the gate does.

Salvaged mechanics (`salvage/waffle-fpga/hw/tools/export_dsn.py`, `staged_route.sh`) that class A does not
need yet and that are not implemented here: plane layers typed `power` (class B), rule areas dropped from the
export (class B+), and staged routing through `(pins)` removal (class C).
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pcbnew

from waffle_eda.kicad import board as kb

VERSION = "2.4.1"
JAVA_MAJOR = 25  # the minimum Java that runs the jar: 2.4.1 is compiled for class file version 69

# Measured on `tinkerforge-temperature` (D57): asked for the measured clearance itself (0.1972 mm, 0.003 under
# the SOT-563's pad gap) the router's exact insertion check rejects every connection at that part; asked for
# 0.190 it connects the whole board. So every clearance is handed over as the rule less this slack, and
# :func:`repair_clearances` takes the slack back afterwards under KiCad's own DRC (D60: the smoke board then
# passes, 6 of 6 and 0 violations, 15 moves). ``slack_all=False`` hands the slack to wire-to-SMD-pad clearances
# only and everything else exactly, which connected 4 of 6 there and is kept for measurement.
CLEARANCE_SLACK_MM = 0.0072
# The router writes via drills in whole micrometres (248.9 became 248), so the drill is rounded up to one.
DRILL_STEP_MM = 0.001
# The default via cost of 50 stops the router placing any via of its own on a 15 x 25 mm board (D57: 0 vias,
# every pass alternating between two top-layer solutions); at 1 it uses vias as the reference does (13 to the
# reference's 15). It goes into the settings file as `router.scoring.via_costs`; an `(autoroute_settings ...)`
# block in the DSN carried it too, but placed before the structure's rule block it made the loader drop every
# pin of `olimex-rp2040-pico-pc`, and after it the cost was not read.
VIA_COSTS = 1
FANOUT = False  # the fanout stage necks its stubs to 75 % of the width, below the rule, and is fragile (D57)
OPTIMIZER_PASSES = 0  # the optimiser reworks copper for length and via count, which the gate does not score; it took
# 11 of the esp32c3's 12 minutes and, drawing on Java's random generator, gave a different board each run (D65)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def tools_dir() -> Path:
    return repo_root() / "build" / "tools"


def jar_path() -> Path:
    return Path(os.environ.get("WAFFLE_FREEROUTING_JAR", tools_dir() / f"freerouting-{VERSION}.jar"))


def java_path() -> Path | None:
    """The `java` to run the jar with: `WAFFLE_JAVA`, else the fetched JDK, else the one on the path."""
    env = os.environ.get("WAFFLE_JAVA")
    if env:
        return Path(env)
    fetched = tools_dir() / "jdk" / "bin" / "java"
    if fetched.is_file():
        return fetched
    found = shutil.which("java")
    return Path(found) if found else None


def java_major(java: Path) -> int | None:
    """The major version `java -version` reports, or None when it does not run."""
    try:
        out = subprocess.run([str(java), "-version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r'version "(\d+)', out.stderr + out.stdout)
    return int(m.group(1)) if m else None


def available() -> str | None:
    """None when the wrapper can run, else the reason it cannot (the message the gate and check_env print)."""
    if not jar_path().is_file():
        return f"Freerouting jar not found at {jar_path()} (python3 scripts/fetch_tools.py)"
    java = java_path()
    if java is None:
        return "no java (python3 scripts/fetch_tools.py)"
    major = java_major(java)
    if major is None or major < JAVA_MAJOR:
        return f"java {major} at {java}; Freerouting {VERSION} needs {JAVA_MAJOR} (python3 scripts/fetch_tools.py)"
    if not shutil.which("xvfb-run"):
        return "xvfb-run not found"
    return None


# --- the board before export ------------------------------------------------------------------------------------
def unique_references(board) -> dict[str, str]:
    """Rename every footprint that shares a reference with an earlier one, returning uuid -> original name.

    `pcbnew.ExportSpecctraDSN` throws on a duplicate reference (a logo, a fiducial, a second `VAL`) and its
    Python wrapper turns the throw into a bare `False`. Found by bisection on `tinkerforge-temperature`: the
    export succeeds with every footprint removed and fails with any one of them removed, because the board has
    two duplicate pairs.
    """
    seen: Counter = Counter()
    renamed: dict[str, str] = {}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        seen[ref] += 1
        if seen[ref] > 1:
            renamed[fp.m_Uuid.AsString()] = ref
            fp.SetReference(f"{ref}~{seen[ref]}")
    return renamed


def restore_references(board, renamed: dict[str, str]) -> None:
    for fp in board.GetFootprints():
        original = renamed.get(fp.m_Uuid.AsString())
        if original is not None:
            fp.SetReference(original)


def smallest_ring_mm(board) -> tuple[float | None, float | None]:
    """The smallest copper ring around a hole, for vias and for plated pads: (via ring, pin ring), in mm.

    A via's ring comes from the rules, so the via ring here is only what the board already carries (None on a
    stripped board). A pad whose copper is smaller than its hole (a castellation, a slot) has a ring of zero.
    """
    via_rings = [(kb.via_diameter_mm(v) - kb.via_drill_mm(v)) / 2 for v in kb.vias(board)]
    pin_rings = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetAttribute() != pcbnew.PAD_ATTRIB_PTH or not pad.GetNetname():
                continue
            drill = pad.GetDrillSize()
            best = None
            for layer in pad.GetLayerSet().CuStack():
                size = pad.GetSize(layer)
                ring = (min(size.x, size.y) - max(drill.x, drill.y)) / 2
                best = ring if best is None else min(best, ring)
            pin_rings.append(max(0.0, kb.mm(best if best is not None else 0)))
    return (min(via_rings) if via_rings else None, min(pin_rings) if pin_rings else None)


@dataclass(frozen=True)
class DsnRules:
    """What the DSN's rule section says, in mm: the values the router is asked to meet."""
    width_mm: float
    clearance_mm: float
    via_diameter_mm: float
    via_drill_mm: float
    via_clearance_mm: float | None  # typed clearance for vias, from the hole-to-copper rule
    pin_clearance_mm: float | None  # typed clearance for plated pins, likewise
    smd_clearance_mm: float | None = None  # typed clearance wire to SMD pad: the rule less the slack


def dsn_rules(rules, pin_ring_mm: float | None, slack_all: bool = True) -> DsnRules:
    """Map the gate's measured rules (`bench/rebuild.BoardRules`) to what the router is asked for."""
    import math
    exact = round(rules.clearance_mm, 4)
    slack = round(rules.clearance_mm - CLEARANCE_SLACK_MM, 4)
    clearance = slack if slack_all else exact
    drill = math.ceil(rules.min_drill_mm / DRILL_STEP_MM - 1e-9) * DRILL_STEP_MM
    via_ring = (rules.min_via_mm - drill) / 2
    via_clr = round(rules.hole_to_copper_mm - via_ring, 4)
    pin_clr = round(rules.hole_to_copper_mm - pin_ring_mm, 4) if pin_ring_mm is not None else None
    return DsnRules(width_mm=rules.min_track_mm, clearance_mm=clearance,
                    via_diameter_mm=rules.min_via_mm, via_drill_mm=round(drill, 4),
                    via_clearance_mm=via_clr if via_clr > clearance else None,
                    pin_clearance_mm=pin_clr if pin_clr is not None and pin_clr > clearance else None,
                    smd_clearance_mm=None if slack_all else slack)


def apply_rules(board, d: DsnRules) -> None:
    """Write the rules into every net class so the export carries them. Must run before any other edit of the
    board: the SWIG wrapper loses the net settings after one (old project, `export_dsn.py`)."""
    for _name, nc in board.GetAllNetClasses().items():
        nc.SetTrackWidth(kb.nm(d.width_mm))
        nc.SetClearance(kb.nm(d.clearance_mm))
        nc.SetViaDiameter(kb.nm(d.via_diameter_mm))
        nc.SetViaDrill(kb.nm(d.via_drill_mm))


# Specctra clearance types Freerouting reads: a pair of item kinds. The typed rule applies to that pair only.
VIA_TYPES = ("via_via", "wire_via", "smd_via", "pin_via")
PIN_TYPES = ("pin_pin", "wire_pin", "smd_pin")
SMD_TYPES = ("wire_smd", "smd_wire")


def typed_clearances(dsn_text: str, d: DsnRules) -> str:
    """Add the hole-to-copper clearances as typed rules inside the structure's `(rule ...)` block.

    KiCad writes the DSN in micrometres (`(resolution um 10)`), one rule block in `(structure ...)` of the form
    `(rule (width W) (clearance C) (clearance c (type smd_smd)))`; the typed lines go after the default one.
    """
    lines = []
    if d.via_clearance_mm is not None:
        lines += [f"      (clearance {d.via_clearance_mm * 1000:.2f} (type {t}))" for t in VIA_TYPES]
    if d.pin_clearance_mm is not None:
        lines += [f"      (clearance {d.pin_clearance_mm * 1000:.2f} (type {t}))" for t in PIN_TYPES]
    if d.smd_clearance_mm is not None:
        lines += [f"      (clearance {d.smd_clearance_mm * 1000:.2f} (type {t}))" for t in SMD_TYPES]
    if not lines:
        return dsn_text
    m = re.search(r"\(structure\n(?:.*\n)*?(\s*\(rule\n\s*\(width [^\n]*\n\s*\(clearance [^\n]*\n)", dsn_text)
    if not m:
        raise ValueError("no (rule (width ..) (clearance ..)) block in the structure section of the DSN")
    end = m.end(1)
    return dsn_text[:end] + "\n".join(lines) + "\n" + dsn_text[end:]


# --- rules the export does not carry: per-pad clearance overrides (D59) ---------------------------------------
# KiCad's Specctra export carries the net-class clearance only. A pad with its own clearance (a mounting hole at
# 1.85 mm, a fiducial at 1.016 mm on `olimex-esp32c3-devkit`) is routed past at the ordinary clearance, and the
# gate's DRC then fails every track that came near. So every such pad goes into the DSN as a keepout circle
# around the pad grown by the override less the clearance, on each copper layer the pad is on: the router keeps
# its clearance from a keepout edge (measured on `olimex-esp32c3-devkit`: 0 hole violations at either growth,
# 8 fewer clearance violations at the smaller one).
@dataclass(frozen=True)
class PadKeepout:
    reference: str
    pad: str
    x_mm: float
    y_mm: float
    radius_mm: float  # the pad's own half extent, before growing
    grow_mm: float  # the override less the clearance the router keeps anyway
    layers: tuple  # copper layer names


def _local_clearance_mm(item) -> float:
    value = item.GetLocalClearance()
    if value is None:
        return 0.0
    if hasattr(value, "value"):  # KiCad 9 returns an optional
        return kb.mm(value.value()) if value.has_value() else 0.0
    return kb.mm(value)


def pad_keepouts(board, clearance_mm: float, hole_clearance_mm: float = 0.0) -> list[PadKeepout]:
    """Every pad whose own clearance override exceeds the clearance the router is asked for."""
    names = {lid: name for lid, name in kb.copper_layers(board)}
    out = []
    for fp in board.GetFootprints():
        fp_clr = _local_clearance_mm(fp)
        for pad in fp.Pads():
            override = max(fp_clr, _local_clearance_mm(pad))
            drill = pad.GetDrillSize()
            if not pad.GetNetname() and max(drill.x, drill.y) > 0:
                # a hole with no net (a mounting hole): the router keeps its clearance from the keepout KiCad
                # exports for it, not the hole rule; open-book's pour and a track came 0.06 mm too close
                override = max(override, hole_clearance_mm)
            if override <= clearance_mm:
                continue
            layers = tuple(names[l] for l in pad.GetLayerSet().CuStack() if l in names)
            if not layers:
                continue
            size = pad.GetSize(pad.GetLayerSet().CuStack()[0])
            drill = pad.GetDrillSize()
            radius = max(kb.mm(size.x), kb.mm(size.y), kb.mm(drill.x), kb.mm(drill.y)) / 2
            pos = pad.GetPosition()
            out.append(PadKeepout(reference=fp.GetReference(), pad=pad.GetNumber(), x_mm=kb.mm(pos.x),
                                  y_mm=kb.mm(pos.y), radius_mm=radius, grow_mm=round(override - clearance_mm, 4),
                                  layers=layers))
    return out


def keepouts_dsn(dsn_text: str, keepouts: list[PadKeepout], layers: list[str] | None = None) -> str:
    """Add the keepouts to the structure section, where KiCad puts its own (after the boundary, before the
    via). Coordinates are micrometres with y negated, as KiCad writes them."""
    lines = []
    for k in keepouts:
        for layer in (layers or k.layers):
            if layers and layer not in k.layers:
                continue
            name = f'"{layer}"' if any(c in layer for c in " ()") or not layer.isascii() else layer
            lines.append(f'    (keepout "" (circle {name} {2 * (k.radius_mm + k.grow_mm) * 1000:.2f} '
                         f'{k.x_mm * 1000:.2f} {-k.y_mm * 1000:.2f}))')
    if not lines:
        return dsn_text
    start = dsn_text.index("(structure")
    i = dsn_text.find("    (via ", start)
    if i < 0:
        i = dsn_text.index("    (rule\n", start)
    return dsn_text[:i] + "\n".join(lines) + "\n" + dsn_text[i:]


# --- rule areas the export gets wrong -------------------------------------------------------------------------
def pour_only_rule_areas(board) -> list:
    """The rule areas that forbid the copper pour and nothing the router lays (no tracks, no vias)."""
    return [z for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowCopperPour()
            and not z.GetDoNotAllowTracks() and not z.GetDoNotAllowVias()]


def lift_pour_only_rule_areas(board) -> list[dict]:
    """Take the pour-only rule areas off the board for the export and return what lays them back.

    KiCad's Specctra export writes a rule area that forbids only the pour as a plain ``(keepout ...)``, the same
    as one forbidding tracks and vias (tracks alone give ``wire_keepout``, vias alone ``via_keepout``). The
    router then treats it as ground it may not enter: `olimex-rp2040-pico-pc` draws no-pour areas over both pad
    rows of its TSSOP-14 and the router could not start a search from any of its 14 pins (13 of the board's 14
    open connections). The pour never reaches the router, so the areas are its business only after the import.
    """
    facts = []
    for zone in pour_only_rule_areas(board):
        poly = zone.Outline()
        outlines = []
        for i in range(poly.OutlineCount()):
            ring = poly.Outline(i)
            pts = [(ring.CPoint(k).x, ring.CPoint(k).y) for k in range(ring.PointCount())]
            holes = []
            for h in range(poly.HoleCount(i)):
                hole = poly.Hole(i, h)
                holes.append([(hole.CPoint(k).x, hole.CPoint(k).y) for k in range(hole.PointCount())])
            outlines.append((pts, holes))
        facts.append({"name": zone.GetZoneName(), "layers": list(zone.GetLayerSet().Seq()), "outlines": outlines,
                      "pads": zone.GetDoNotAllowPads(), "footprints": zone.GetDoNotAllowFootprints()})
        board.Delete(zone)
    return facts


def lay_rule_areas(board, facts: list[dict]) -> list:
    """Lay back the rule areas :func:`lift_pour_only_rule_areas` took off, as new zones (board.py: a zone is
    replaced, never reshaped)."""
    made = []
    for f in facts:
        zone = pcbnew.ZONE(board)
        zone.SetIsRuleArea(True)
        zone.SetDoNotAllowCopperPour(True)
        zone.SetDoNotAllowTracks(False)
        zone.SetDoNotAllowVias(False)
        zone.SetDoNotAllowPads(f["pads"])
        zone.SetDoNotAllowFootprints(f["footprints"])
        zone.SetZoneName(f["name"])
        layers = pcbnew.LSET()
        for lid in f["layers"]:
            layers.AddLayer(lid)
        zone.SetLayerSet(layers)
        poly = zone.Outline()
        for pts, holes in f["outlines"]:
            i = poly.NewOutline()
            for x, y in pts:
                poly.Append(x, y, i)
            for hole in holes:
                h = poly.NewHole(i)
                for x, y in hole:
                    poly.Append(x, y, i, h)
        board.Add(zone)
        made.append(zone)
    return made


# --- what the router leaves behind (D66) ---------------------------------------------------------------------
def prune_dangling(board) -> dict:
    """Remove duplicate track segments and, repeatedly, every segment with an end on nothing of its net (no
    pad containing it, no via at it, no other segment ending or passing there). Freerouting leaves such spurs
    and counts them among its own violations; KiCad's DRC reports them only as warnings, and one of
    open-book's ended 0.1 mm from the board edge."""
    removed = {"duplicates": 0, "dangling": 0}
    seen: set[tuple] = set()
    doomed = []
    for t in kb.track_segments(board):
        s, e = t.GetStart(), t.GetEnd()
        key = (t.GetNetCode(), t.GetLayer(), t.GetWidth()) + tuple(sorted(((s.x, s.y), (e.x, e.y))))
        if key in seen:
            doomed.append(t)
        else:
            seen.add(key)
    for t in doomed:  # deleted after the scan: a deleted item's proxy must not be touched again
        board.Delete(t)
        removed["duplicates"] += 1
    pads = [p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetCode()]
    while True:
        tracks = kb.track_segments(board)
        vias = kb.vias(board)
        victim = None
        for t in tracks:
            net, layer = t.GetNetCode(), t.GetLayer()
            for end in (t.GetStart(), t.GetEnd()):
                attached = any(p.GetNetCode() == net and p.IsOnLayer(layer) and p.HitTest(end) for p in pads) \
                    or any(v.GetNetCode() == net and v.GetPosition() == end for v in vias) \
                    or any(o.GetNetCode() == net and o.GetLayer() == layer and o.m_Uuid.AsString() != t.m_Uuid.AsString()
                           and (o.GetStart() == end or o.GetEnd() == end or o.HitTest(end)) for o in tracks)
                if not attached:
                    victim = t
                    break
            if victim is not None:
                break
        if victim is None:
            return removed
        board.Delete(victim)  # then the lists are rebuilt: nothing holds the deleted proxy
        removed["dangling"] += 1


# --- necked traces (D59, kind 2) -------------------------------------------------------------------------------
def widen_tracks(board, width_mm: float) -> int:
    """Set every track narrower than the rule back to it; returns how many. Freerouting narrows a trace where it
    enters a pad (40 width violations on `open-book-c1`, all by 0.03 mm or more) and its `automatic_neckdown`
    setting does not stop it. Whether the widened copper clears its neighbours is the gate's DRC's to say."""
    target = kb.nm(width_mm)
    widened = 0
    for track in kb.track_segments(board) + kb.track_arcs(board):
        if track.GetWidth() < target:
            track.SetWidth(target)
            widened += 1
    return widened


# --- clearances a few micrometres short (D59, kind 1) -----------------------------------------------------------
# The router keeps every round shape as an octagon and passes its own check with copper up to 0.011 mm closer
# than KiCad measures. The repair is KiCad's ruler applied afterwards: run the gate's DRC, and for every
# clearance violation that involves a track, move that track away from the other item by the shortfall plus a
# hair, carrying the tracks that share its ends with it, then check again. A track end inside a pad or a via
# stays connected after a move of a few micrometres; the DRC says whether the move made a new violation.
ROUTER_EDGE_MM = 0.30  # what the router keeps from the board edge; the DRC and the repair hold the measured rule (D68)
NUDGE_EXTRA_MM = 0.0005
REPAIR_ROUNDS = 12
TRACE: list | None = None  # a list here receives the repair's decisions, for the order test's diagnosis
DRAG_FLOOR = True  # set per strategy by repair_clearances; see _move_checked
CARRY_MM = 0.6  # a connected segment shorter than this is carried whole with a move, not pivoted on its far end


@dataclass(frozen=True)
class Violation:
    type: str
    rule_mm: float
    actual_mm: float
    items: tuple  # (uuid, description, (x_mm, y_mm)) per item

    @property
    def short_mm(self) -> float:
        return round(self.rule_mm - self.actual_mm, 4)


_RULE_ACTUAL = re.compile(r"(?:clearance|width) ([\d.]+) mm; actual ([\d.]+) mm")


def drc_violations(board, rules, work_dir: Path) -> list[Violation]:
    """The electrical violations KiCad's DRC reports for ``board`` under the gate's rules, with the items'
    identities and positions. The board is saved to ``work_dir`` for the run."""
    from waffle_eda.bench import harness, rebuild
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / "board.kicad_pcb"
    kb.save_board(board, path)
    (work_dir / "board.kicad_dru").write_text(rules.rules_text())
    report = harness.run_drc(path, work_dir / "drc.json")
    out = []
    for v in report.get("violations", []):
        if v.get("type") not in harness.ELECTRICAL_TYPES:
            continue
        m = _RULE_ACTUAL.search(v.get("description", ""))
        rule, actual = (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)
        items = tuple((i.get("uuid", ""), i.get("description", ""), (i.get("pos", {}).get("x", 0.0), i.get("pos", {}).get("y", 0.0)))
                      for i in v.get("items", []))
        out.append(Violation(type=v["type"], rule_mm=rule, actual_mm=actual, items=items))
    return out


def _room(board, obstacles, track, ux: float, uy: float, rules, limit_mm: float = 0.05,
          allowed: frozenset | None = None) -> float:
    """How far ``track`` can move along the unit vector (ux, uy) before colliding, by bisection of trial moves."""
    lo, hi = 0.0, limit_mm
    if _move_checked(board, obstacles, track, ux * hi, uy * hi, rules, keep=False, allowed=allowed):
        return hi
    for _ in range(8):
        mid = (lo + hi) / 2
        if _move_checked(board, obstacles, track, ux * mid, uy * mid, rules, keep=False, allowed=allowed):
            lo = mid
        else:
            hi = mid
    return lo


def index_violations(board, obstacles, rules) -> list[Violation]:
    """Every pair of our copper (a track or via) and other-net copper closer than the rules, from the exact
    collision index, in geometric order. KiCad's DRC report dropped a real violation in 1 run of 8 on one
    board (D63), so the repair does not steer by it; the gate's DRC still judges the result."""
    out = []
    seen: set[tuple] = set()
    ours = kb.track_segments(board) + kb.vias(board)
    for item in ours:
        is_via = item.GetClass() == "PCB_VIA"
        layer = pcbnew.F_Cu if is_via else item.GetLayer()
        for oid, other in _hits(obstacles, item, rules).items():
            pair = tuple(sorted((item.m_Uuid.AsString(), oid)))
            if pair in seen:
                continue
            seen.add(pair)
            other_layer = layer if not is_via else (other.GetLayer() if other.GetClass() == "PCB_TRACK" else pcbnew.F_Cu)
            if other.GetClass() == "PCB_SHAPE" and other.GetLayer() == pcbnew.Edge_Cuts:
                vtype, rule = "copper_edge_clearance", rules.edge_clearance_mm
                gap = _gap_mm(item, other, other_layer, limit_mm=rule + 0.05) + kb.mm(other.GetWidth()) / 2
                short = round(rule - gap, 4)
            else:
                gap = _gap_mm(item, other, other_layer)
                rule, vtype = rules.clearance_mm, "clearance"
                short = round(rule - gap, 4)
                if short <= 0:  # copper clears; the index answered for a hole, if either has one
                    if not _has_hole(other) and not _has_hole(item):
                        continue  # a gap within rounding of the rule (crkbd's KEY3 stub: 0.18896 under 0.189)
                    vtype, rule = "hole_clearance", rules.hole_to_copper_mm
                    short = round(rule - gap - _ring_mm(other, item), 4)
            if short <= 0:
                continue
            out.append(Violation(type=vtype, rule_mm=rule, actual_mm=round(rule - short, 4),
                                 items=(_item_ref(item), _item_ref(other, near=item))))
    return sorted(out, key=_violation_key)


def _has_hole(item) -> bool:
    if item.GetClass() == "PCB_VIA":
        return True
    return item.GetClass() == "PAD" and item.GetDrillSize().x > 0


def _ring_mm(a, b) -> float:
    """The copper ring around whichever of the two has a hole (a via or a plated pad), else 0."""
    for item in (a, b):
        if item.GetClass() == "PCB_VIA":
            return kb.via_diameter_mm(item) / 2 - kb.via_drill_mm(item) / 2
        if item.GetClass() == "PAD" and item.GetDrillSize().x > 0:
            layers = item.GetLayerSet().CuStack()
            size = item.GetSize(layers[0] if layers else pcbnew.F_Cu)
            return max(0.0, (min(kb.mm(size.x), kb.mm(size.y)) - max(kb.mm(item.GetDrillSize().x), kb.mm(item.GetDrillSize().y))) / 2)
    return 0.0


def _item_ref(item, near=None) -> tuple:
    """(uuid, description, position) as the DRC report would give them, for an item of the board. For a board
    edge the position is the point of it nearest ``near``, so a push away from it is perpendicular to it."""
    cls = item.GetClass()
    if cls == "PCB_SHAPE":
        s, e = item.GetStart(), item.GetEnd()
        px, py = kb.mm(s.x), kb.mm(s.y)
        if near is not None:
            n = near.GetPosition() if near.GetClass() == "PCB_VIA" else near.GetStart()
            ax, ay, bx, by = kb.mm(s.x), kb.mm(s.y), kb.mm(e.x), kb.mm(e.y)
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            t = 0.0 if length2 < 1e-12 else max(0.0, min(1.0, ((kb.mm(n.x) - ax) * dx + (kb.mm(n.y) - ay) * dy) / length2))
            px, py = ax + t * dx, ay + t * dy
        return (item.m_Uuid.AsString(), f"{item.GetShapeStr()} on {item.GetLayerName()}", (px, py))
    if cls == "PCB_TRACK":
        p = item.GetStart()
        return (item.m_Uuid.AsString(), f"Track [{item.GetNetname()}] on {item.GetLayerName()}, length {kb.mm(item.GetLength()):.4f} mm", (kb.mm(p.x), kb.mm(p.y)))
    p = item.GetPosition()
    if cls == "PCB_VIA":
        return (item.m_Uuid.AsString(), f"Via [{item.GetNetname()}]", (kb.mm(p.x), kb.mm(p.y)))
    if cls == "PAD":
        parent = item.GetParentFootprint()
        ref = parent.GetReference() if parent else "?"
        return (item.m_Uuid.AsString(), f"Pad {item.GetNumber()} [{item.GetNetname()}] of {ref}", (kb.mm(p.x), kb.mm(p.y)))
    return (item.m_Uuid.AsString(), cls, (kb.mm(p.x), kb.mm(p.y)))


def _hits(obstacles, item, rules) -> dict:
    """The other-net copper ``item`` collides with under the rules, by uuid."""
    return {o.m_Uuid.AsString(): o for o in obstacles._collisions(item, rules.clearance_mm, rules.hole_to_copper_mm)}


def _hit_ids(obstacles, item, rules) -> set[str]:
    return set(_hits(obstacles, item, rules))


def _gap_mm(a, b, layer: int, limit_mm: float = 0.25) -> float:
    """The copper-to-copper distance between two items on ``layer``, by bisection of the clearance at which
    KiCad's shapes collide (the shapes answer collide-or-not, never a distance); ``limit_mm`` when they are
    further apart than that. An edge line is measured to its stroke; the caller adds half its width, since
    KiCad measures to the outline itself (rp2040's LED1 track read 0.25 short at 0.539 from the edge)."""
    def shape(item):
        return item.GetEffectiveShape(layer) if item.GetClass() == "PAD" else item.GetEffectiveShape()
    sa, sb = shape(a), shape(b)
    lo, hi = 0.0, limit_mm
    if not sa.Collide(sb, kb.nm(hi)):
        return hi
    for _ in range(12):  # 0.25 mm to 0.06 um; an edge rule of 0.5 to 0.12 um
        mid = (lo + hi) / 2
        if sa.Collide(sb, kb.nm(mid)):
            hi = mid
        else:
            lo = mid
    return lo


def _with_ends(board, item) -> list:
    """``item`` and the tracks of its net that a move of it carries: those whose ends sit on it (a via's
    position, or a track's ends), and, when such a neighbour is shorter than ``CARRY_MM``, the tracks on its
    far end too, since that neighbour moves whole (see :func:`_move`). The esp32c3's USB_DN sat 0.014 mm off
    the centre of a 0.02 mm corridor and could not move: its short 45-degree neighbour, pivoted on its far
    end, swung into the next pad's corner."""
    is_via = item.GetClass() == "PCB_VIA"
    net = item.GetNetCode()
    own = item.m_Uuid.AsString()
    if is_via:
        ends = [pcbnew.VECTOR2I(item.GetPosition())]
    else:
        ends = [pcbnew.VECTOR2I(item.GetStart()), pcbnew.VECTOR2I(item.GetEnd())]
    segments = [o for o in kb.track_segments(board) if o.GetNetCode() == net and o.m_Uuid.AsString() != own]
    moved = [item]
    seen = {own}
    far_ends = []
    for o in segments:
        if o.GetStart() in ends or o.GetEnd() in ends:
            moved.append(o)
            seen.add(o.m_Uuid.AsString())
            if o.GetLength() < kb.nm(CARRY_MM):  # carried whole: its far end moves too
                far_ends.append(pcbnew.VECTOR2I(o.GetEnd() if o.GetStart() in ends else o.GetStart()))
    for o in segments:  # the tracks on a carried neighbour's far end follow with that end
        if o.m_Uuid.AsString() not in seen and (o.GetStart() in far_ends or o.GetEnd() in far_ends):
            moved.append(o)
            seen.add(o.m_Uuid.AsString())
    return moved


FREE_FLOOR_MM = 0.01  # with dragged ends free (D64) a kept collision may still never close to a short


def _kept_ok(m, layer, before_hits: dict, after_hits: dict, gaps: dict, rules) -> bool:
    """A moved item may keep only the collisions it had, and none of them closer than the router itself was
    allowed (the rule less the slack) or than it was before, whichever is less; free (D64), only never within
    FREE_FLOOR_MM of a short. crkbd's KEY5 was swung 0.28 mm into KEY10 by an end move that kept the pair's
    0.006 mm violation and deepened it to an overlap (D70)."""
    mid = m.m_Uuid.AsString()
    if not set(after_hits) <= set(before_hits):
        return False
    floor = rules.clearance_mm - CLEARANCE_SLACK_MM - NUDGE_EXTRA_MM if DRAG_FLOOR else FREE_FLOOR_MM
    return not any(_gap_mm(m, o, layer) < min(gaps.get((mid, oid), floor), floor) - 0.0002 for oid, o in after_hits.items())


def _move_checked(board, obstacles, item, dx_mm: float, dy_mm: float, rules, keep: bool = True,
                  allowed: frozenset | None = None) -> bool:
    """Move a track (and the ends it shares) or a via (and the track ends on it) and keep the move only if it
    makes no new collision under the exact collision index. The item may keep colliding only with ``allowed``:
    the copper it is moving away from, whose collision shrinks (with no ``allowed``, anything it collided with
    before). A dragged end may keep the collisions it had (D62)."""
    moved = _with_ends(board, item)
    own = item.m_Uuid.AsString()
    before = {m.m_Uuid.AsString(): _hits(obstacles, m, rules) for m in moved}
    layer_of = {m.m_Uuid.AsString(): (m.GetLayer() if m.GetClass() != "PCB_VIA" else pcbnew.F_Cu) for m in moved}
    gaps = {(mid, oid): _gap_mm(next(m for m in moved if m.m_Uuid.AsString() == mid), o, layer_of[mid])
            for mid, hits in before.items() for oid, o in hits.items()}
    for m in moved:
        obstacles.remove(m)
    _move(board, item, moved, kb.nm(dx_mm), kb.nm(dy_mm))
    clean = True
    for m in moved:
        mid = m.m_Uuid.AsString()
        after = _hits(obstacles, m, rules)
        if mid == own and allowed is not None:  # the caller vouches: it moves away from these
            if not set(after) <= allowed:
                clean = False
                break
            continue
        # a dragged end (or an item pushed with nothing vouched for) keeps only what it had, and none of it
        # closer than the rule allows (_kept_ok): the repair never leaves copper worse than the router's own
        # output. Measured through the DRC report this floor stalled open-book at two pairs; the report drops
        # violations (D63), and under the index the measurement is repeated (scripts/repair_only.py).
        if not _kept_ok(m, layer_of[mid], before[mid], after, gaps, rules):
            clean = False
            break
    if not clean or not keep:
        _move(board, item, moved, -kb.nm(dx_mm), -kb.nm(dy_mm))
    for m in moved:
        obstacles.add(m)
    return clean


def _push_chain(board, obstacles, item, ux: float, uy: float, step: float, rules, movable: dict,
                allowed: frozenset | None, depth: int = 4) -> bool:
    """Move ``item`` by ``step`` along (ux, uy); if what stops it is ours (in ``movable``), push that first,
    up to ``depth`` items deep. A row of packed tracks can only spread from its free edge inward."""
    if _move_checked(board, obstacles, item, ux * step, uy * step, rules, allowed=allowed):
        return True
    if depth == 0:
        return False
    blocker = _blocker(board, obstacles, item, ux, uy, step, rules)
    if blocker is None:
        return False
    other = movable.get(blocker.m_Uuid.AsString())
    if other is None:
        return False
    if not _push_chain(board, obstacles, other, ux, uy, step, rules, movable, None, depth - 1):
        return False
    return _move_checked(board, obstacles, item, ux * step, uy * step, rules, allowed=allowed)


def _blocker(board, obstacles, item, ux: float, uy: float, distance_mm: float, rules):
    """The nearest other-net copper ``item`` newly meets when moved ``distance_mm`` along (ux, uy), or None.
    Nearest by gap, ties by position: the index yields hits in board order, which follows the order items
    came in, and the order test caught the chain push choosing differently for the same geometry (D25)."""
    moved = _with_ends(board, item)
    before = {m.m_Uuid.AsString(): _hit_ids(obstacles, m, rules) for m in moved}
    for m in moved:
        obstacles.remove(m)
    _move(board, item, moved, kb.nm(ux * distance_mm), kb.nm(uy * distance_mm))
    best = None
    for m in moved:
        layer = m.GetLayer() if m.GetClass() != "PCB_VIA" else pcbnew.F_Cu
        for o in obstacles._collisions(m, rules.clearance_mm, rules.hole_to_copper_mm):
            if o.m_Uuid.AsString() in before[m.m_Uuid.AsString()]:
                continue
            key = (round(_gap_mm(m, o, layer), 4), _item_key(o))
            if best is None or key < best[0]:
                best = (key, o)
    _move(board, item, moved, -kb.nm(ux * distance_mm), -kb.nm(uy * distance_mm))
    for m in moved:
        obstacles.add(m)
    return None if best is None else best[1]


def _item_key(item) -> tuple:
    """A geometric sort key for any board item (D25)."""
    if item.GetClass() == "PCB_TRACK":
        return (0,) + _track_key(item)
    p = item.GetPosition()
    return (1, p.x, p.y)


def _move_end_checked(board, obstacles, track, end_index: int, dx_mm: float, dy_mm: float, rules,
                      allowed: frozenset | None = None) -> bool:
    """Move one end of ``track`` (with what sits on that end: short neighbours carried whole, long ones by
    their shared end), keeping the other end where it is, if the moved copper makes no new collision. The
    move for a violation near one end of a long track, where translating the whole track drags its far end
    into something (open-book's 13 mm BTN_LOCK diagonal turning too early at an edge pad)."""
    end = pcbnew.VECTOR2I(track.GetStart() if end_index == 0 else track.GetEnd())
    net, layer = track.GetNetCode(), track.GetLayer()
    own = track.m_Uuid.AsString()
    neighbours = [o for o in kb.track_segments(board) if o.GetNetCode() == net and o.GetLayer() == layer
                  and o.m_Uuid.AsString() != own and (o.GetStart() == end or o.GetEnd() == end)]
    moved = [track] + neighbours
    far_ends = [pcbnew.VECTOR2I(o.GetEnd() if o.GetStart() == end else o.GetStart())
                for o in neighbours if o.GetLength() < kb.nm(CARRY_MM)]
    moved += [o for o in kb.track_segments(board) if o.GetNetCode() == net and o.m_Uuid.AsString() not in {m.m_Uuid.AsString() for m in moved}
              and (o.GetStart() in far_ends or o.GetEnd() in far_ends)]
    before = {m.m_Uuid.AsString(): _hits(obstacles, m, rules) for m in moved}
    gaps = {(m.m_Uuid.AsString(), oid): _gap_mm(m, o, layer) for m in moved for oid, o in before[m.m_Uuid.AsString()].items()}
    for m in moved:
        obstacles.remove(m)
    dx, dy = kb.nm(dx_mm), kb.nm(dy_mm)

    def shift(item, points):
        if item.GetStart() in points:
            item.SetStart(pcbnew.VECTOR2I(item.GetStart().x + dx, item.GetStart().y + dy))
        if item.GetEnd() in points:
            item.SetEnd(pcbnew.VECTOR2I(item.GetEnd().x + dx, item.GetEnd().y + dy))

    def apply(sign):
        nonlocal dx, dy
        dx, dy = sign * abs(dx) * (1 if dx_mm >= 0 else -1), sign * abs(dy) * (1 if dy_mm >= 0 else -1)
        anchors = [end]
        if end_index == 0:
            track.SetStart(pcbnew.VECTOR2I(track.GetStart().x + dx, track.GetStart().y + dy))
        else:
            track.SetEnd(pcbnew.VECTOR2I(track.GetEnd().x + dx, track.GetEnd().y + dy))
        for o in neighbours:
            if o.GetLength() < kb.nm(CARRY_MM):
                anchors.append(pcbnew.VECTOR2I(o.GetEnd() if o.GetStart() == end else o.GetStart()))
                o.SetStart(pcbnew.VECTOR2I(o.GetStart().x + dx, o.GetStart().y + dy))
                o.SetEnd(pcbnew.VECTOR2I(o.GetEnd().x + dx, o.GetEnd().y + dy))
            else:
                shift(o, [end])
        for o in moved:
            if o is track or o in neighbours:
                continue
            shift(o, anchors[1:])
        end.x, end.y = end.x + dx, end.y + dy

    apply(1)
    clean = True
    for m in moved:
        after = _hits(obstacles, m, rules)
        if m is track and allowed is not None:
            clean = set(after) <= allowed
        else:
            clean = _kept_ok(m, layer, before[m.m_Uuid.AsString()], after, gaps, rules)
        if not clean:
            break
    if not clean:
        apply(-1)
    for m in moved:
        obstacles.add(m)
    return clean


def _retract_into_pad(board, obstacles, track, by_mm: float, rules) -> bool:
    """Pull whichever end of ``track`` lies inside a pad of its net back along the track by ``by_mm``, if the
    new end still lies inside that pad (connected by overlap) and the track makes no new collision."""
    import math
    s, e = track.GetStart(), track.GetEnd()
    length = math.hypot(kb.mm(e.x - s.x), kb.mm(e.y - s.y))
    if length <= by_mm + 0.05:
        return False
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() != track.GetNetCode() or not pad.IsOnLayer(track.GetLayer()):
                continue
            for end, other_end, setter in ((s, e, track.SetStart), (e, s, track.SetEnd)):
                if not pad.HitTest(end):
                    continue
                ux, uy = kb.mm(other_end.x - end.x) / length, kb.mm(other_end.y - end.y) / length
                new_end = pcbnew.VECTOR2I(end.x + kb.nm(ux * by_mm), end.y + kb.nm(uy * by_mm))
                if not pad.HitTest(new_end):
                    continue
                before = _hit_ids(obstacles, track, rules)
                obstacles.remove(track)
                setter(new_end)
                ok = _hit_ids(obstacles, track, rules) <= before
                if not ok:
                    setter(end)
                obstacles.add(track)
                return ok
    return False


def _move(board, item, moved, dx_nm: int, dy_nm: int) -> None:
    """Translate ``item``; carry every neighbour in ``moved`` shorter than ``CARRY_MM`` whole; for the rest
    move only the end that sits on a moved point."""
    if item.GetClass() == "PCB_VIA":
        points = [pcbnew.VECTOR2I(item.GetPosition())]
        item.SetPosition(pcbnew.VECTOR2I(points[0].x + dx_nm, points[0].y + dy_nm))
    else:
        points = [pcbnew.VECTOR2I(item.GetStart()), pcbnew.VECTOR2I(item.GetEnd())]
        item.SetStart(pcbnew.VECTOR2I(points[0].x + dx_nm, points[0].y + dy_nm))
        item.SetEnd(pcbnew.VECTOR2I(points[1].x + dx_nm, points[1].y + dy_nm))
    others = [o for o in moved if o.m_Uuid.AsString() != item.m_Uuid.AsString()]
    anchors = list(points)
    carried = set()
    for o in others:
        if (o.GetStart() in points or o.GetEnd() in points) and o.GetLength() < kb.nm(CARRY_MM):
            anchors.append(pcbnew.VECTOR2I(o.GetEnd() if o.GetStart() in points else o.GetStart()))
            o.SetStart(pcbnew.VECTOR2I(o.GetStart().x + dx_nm, o.GetStart().y + dy_nm))
            o.SetEnd(pcbnew.VECTOR2I(o.GetEnd().x + dx_nm, o.GetEnd().y + dy_nm))
            carried.add(o.m_Uuid.AsString())
    for o in others:
        if o.m_Uuid.AsString() in carried:
            continue
        if o.GetStart() in anchors:
            o.SetStart(pcbnew.VECTOR2I(o.GetStart().x + dx_nm, o.GetStart().y + dy_nm))
        if o.GetEnd() in anchors:
            o.SetEnd(pcbnew.VECTOR2I(o.GetEnd().x + dx_nm, o.GetEnd().y + dy_nm))


def _move_track(board, track, dx_nm: int, dy_nm: int) -> None:
    """Translate a track and the ends of every track of its net and layer that shares one of its ends."""
    ends = (track.GetStart(), track.GetEnd())
    net, layer = track.GetNetCode(), track.GetLayer()
    for other in kb.track_segments(board):
        if other.GetNetCode() != net or other.GetLayer() != layer:
            continue
        if other.m_Uuid.AsString() == track.m_Uuid.AsString():
            continue
        for end in ends:
            if other.GetStart() == end:
                other.SetStart(pcbnew.VECTOR2I(end.x + dx_nm, end.y + dy_nm))
            if other.GetEnd() == end:
                other.SetEnd(pcbnew.VECTOR2I(end.x + dx_nm, end.y + dy_nm))
    track.SetStart(pcbnew.VECTOR2I(ends[0].x + dx_nm, ends[0].y + dy_nm))
    track.SetEnd(pcbnew.VECTOR2I(ends[1].x + dx_nm, ends[1].y + dy_nm))


def _normal(track) -> tuple[float, float]:
    """A unit normal of the track (one of its two sides; the sign is fixed per track for a round)."""
    import math
    s, e = track.GetStart(), track.GetEnd()
    ax, ay = kb.mm(e.x - s.x), kb.mm(e.y - s.y)
    length = math.hypot(ax, ay)
    return (0.0, 0.0) if length < 1e-9 else (-ay / length, ax / length)


def _away(track, other_pos_mm: tuple[float, float]) -> tuple[float, float]:
    """Unit vector perpendicular to ``track`` pointing away from ``other_pos_mm``."""
    import math
    s, e = track.GetStart(), track.GetEnd()
    ax, ay = kb.mm(e.x - s.x), kb.mm(e.y - s.y)
    length = math.hypot(ax, ay)
    if length < 1e-9:
        return (0.0, 0.0)
    nx, ny = -ay / length, ax / length
    mx, my = (kb.mm(s.x) + kb.mm(e.x)) / 2, (kb.mm(s.y) + kb.mm(e.y)) / 2
    if (other_pos_mm[0] - mx) * nx + (other_pos_mm[1] - my) * ny > 0:
        nx, ny = -nx, -ny
    return (nx, ny)


def _snapshot(board) -> dict:
    return {**{t.m_Uuid.AsString(): (pcbnew.VECTOR2I(t.GetStart()), pcbnew.VECTOR2I(t.GetEnd())) for t in kb.track_segments(board)},
            **{v.m_Uuid.AsString(): (pcbnew.VECTOR2I(v.GetPosition()),) for v in kb.vias(board)}}


def _restore(board, snap: dict) -> None:
    for t in kb.track_segments(board):
        s, e = snap[t.m_Uuid.AsString()]
        t.SetStart(s)
        t.SetEnd(e)
    for v in kb.vias(board):
        v.SetPosition(snap[v.m_Uuid.AsString()][0])


STRATEGIES = (True, False)  # dragged ends floored at the router's clearance, then free (D64)


def repair_clearances(board, rules, work_dir: Path, rounds: int = REPAIR_ROUNDS) -> dict:
    """Repair under each strategy in turn from the same imported copper, and keep the first that leaves the
    index clean, else the one whose deepest violation is shallowest and, at a tie, the fewer. With dragged
    ends floored the esp32c3 passes and open-book keeps 5 violations; free, the reverse (D64): one rule serves
    neither, two in sequence serve both, and each is deterministic. The depth comes first because on crkbd the
    free strategy left fewer violations (51 against the floor's) but four of them were shorts and most were
    deeper than anything the router had left (D70: 833 at import, none over 0.011 mm)."""
    global DRAG_FLOOR
    start = _snapshot(board)
    best = None
    for floor in STRATEGIES:
        _restore(board, start)
        DRAG_FLOOR = floor
        report = _repair_rounds(board, rules, work_dir, rounds)
        report["strategy"] = "floor" if floor else "free"
        if best is None or (report["worst_mm"], report["remaining"]) < (best[0]["worst_mm"], best[0]["remaining"]):
            best = (report, _snapshot(board))
        if report["remaining"] == 0:
            break
    _restore(board, best[1])
    DRAG_FLOOR = True
    return best[0]


def _repair_rounds(board, rules, work_dir: Path, rounds: int) -> dict:
    """Move tracks a few micrometres away from what they violate, until the exact collision index is clean.

    A track is moved once per round, by the largest shortfall on its open side plus a hair, or, when it is
    pressed from both sides, by half the difference of the two shortfalls, so it settles between its
    neighbours; the outcome does not depend on the order KiCad lists the violations (D25). The smoke board's
    three parallel SOT-563 exits oscillated under one move per violation, and overshot under a summed push."""
    from waffle_eda.route.obstacles import Obstacles
    work_dir.mkdir(parents=True, exist_ok=True)
    design_rules(board, rules)  # the index reads the edge clearance from the design settings
    report = {"rounds": 0, "moved": 0, "remaining": 0, "unfixable": 0}
    for round_no in range(1, rounds + 1):
        report["rounds"] = round_no
        tracks = {t.m_Uuid.AsString(): t for t in kb.track_segments(board)}
        obstacles = Obstacles(board)  # at the rule alone: the DRC rounds hold the per-pad overrides
        violations = index_violations(board, obstacles, rules)  # clearance, hole and edge alike
        report["remaining"] = len(violations)
        if not violations:
            report["worst_mm"] = 0.0
            return report
        via_ids = {v.m_Uuid.AsString() for v in kb.vias(board)}
        # per track: the shortfalls on each side of it, along its own normal
        sides: dict[str, list[float]] = {}
        partners: dict[str, list[set]] = {}  # per track and side: the copper it is pushed away from
        normals: dict[str, tuple[float, float]] = {}
        unfixable = 0
        for v in violations:
            ours = [(u, d, p) for u, d, p in v.items if u in tracks]
            if not ours or v.short_mm <= 0:
                if not any(u in via_ids for u, _d, _p in v.items):
                    unfixable += 1
                continue
            for uuid, _d, _p in ours:  # every track in the violation is pushed by the other item
                other = next(((u, d, p) for u, d, p in v.items if u != uuid), None)
                if other is None:
                    unfixable += 1
                    continue
                track = tracks[uuid]
                if uuid not in normals:
                    normals[uuid] = _normal(track)
                nx, ny = normals[uuid]
                ax, ay = _away(track, other[2])
                side = 0 if ax * nx + ay * ny > 0 else 1  # which side of the track the push points to
                entry = sides.setdefault(uuid, [0.0, 0.0])
                entry[side] = max(entry[side], v.short_mm)
                partners.setdefault(uuid, [set(), set()])[side].add(other[0])
        moved_now = 0
        if TRACE is not None:
            TRACE.append(("round", round_no, sorted((_track_key(tracks[u])[1:3], tuple(sides[u])) for u in sides)))
        stuck: list[str] = []
        balanced: set[str] = set()  # pressed equally from both sides: moved only by a neighbour's push
        for uuid, (plus, minus) in sorted(sides.items(), key=lambda kv: _track_key(tracks[kv[0]])):
            nx, ny = normals[uuid]
            if plus > 0 and minus > 0:  # pressed from both sides: settle in the middle, no extra
                step = (plus - minus) / 2
            else:
                step = plus + NUDGE_EXTRA_MM if plus > 0 else -(minus + NUDGE_EXTRA_MM)
            if abs(step) < 1e-6:
                balanced.add(uuid)
                continue
            track = tracks[uuid]
            short = abs(step) - NUDGE_EXTRA_MM if not (plus > 0 and minus > 0) else abs(step)
            sign = 1 if step > 0 else -1
            both = plus > 0 and minus > 0
            allowed = frozenset(partners[uuid][0] | partners[uuid][1]) if both else frozenset(partners[uuid][0 if sign > 0 else 1])
            room = _room(board, obstacles, track, nx * sign, ny * sign, rules, allowed=allowed)  # free travel
            if room < short - 1e-6:  # boxed in: no translation clears both sides
                stuck.append(uuid)
                continue
            move = min(abs(step), (short + room) / 2)  # the middle of the corridor, or the step if there is room
            if _move_checked(board, obstacles, track, nx * sign * move, ny * sign * move, rules, allowed=allowed):
                moved_now += 1
            else:
                stuck.append(uuid)
        # a track boxed in: the item it violates, then whatever blocks its way on the far side, is pushed
        # instead, where that is ours (a via or a track), and what blocks that in turn, a few items deep
        if TRACE is not None:
            TRACE.append(("stuck", [_track_key(tracks[u])[1:3] for u in stuck], "balanced", sorted(_track_key(tracks[u])[1:3] for u in balanced)))
        vias = {v.m_Uuid.AsString(): v for v in kb.vias(board)}
        movable = {**tracks, **vias}
        for uuid in stuck:
            track = tracks[uuid]
            plus, minus = sides[uuid]
            nx, ny = normals[uuid]
            sign = 1 if plus >= minus else -1
            short = max(plus, minus)
            pushed = False
            for v in violations:  # the violating item, pushed away from the track
                ids = [u for u, _d, _p in v.items]
                if uuid not in ids:
                    continue
                other = next((movable.get(u) for u in ids if u != uuid), None)
                if other is None or (other.m_Uuid.AsString() in sides and other.m_Uuid.AsString() not in balanced):
                    continue
                step = v.short_mm + 2 * NUDGE_EXTRA_MM
                if _push_chain(board, obstacles, other, -nx * sign, -ny * sign, step, rules, movable, frozenset({uuid})):
                    moved_now += 1
                    pushed = True
            if pushed:
                continue
            blocker = _blocker(board, obstacles, track, nx * sign, ny * sign, short + NUDGE_EXTRA_MM, rules)
            if blocker is not None:
                uid = blocker.m_Uuid.AsString()
                other = movable.get(uid)
                if other is not None and (uid not in sides or uid in balanced):
                    step = short + 2 * NUDGE_EXTRA_MM
                    if _push_chain(board, obstacles, other, nx * sign, ny * sign, step, rules, movable, None):
                        moved_now += 1
                        continue
            # last: move only the end of the track nearer the violation, the other end staying put
            allowed = frozenset(partners[uuid][0 if sign > 0 else 1])
            for v in violations:
                ids = [u for u, _d, _p in v.items]
                if uuid not in ids:
                    continue
                pos = next(p for u, _d, p in v.items if u != uuid)
                s0, e0 = track.GetStart(), track.GetEnd()
                d_start = (kb.mm(s0.x) - pos[0]) ** 2 + (kb.mm(s0.y) - pos[1]) ** 2
                d_end = (kb.mm(e0.x) - pos[0]) ** 2 + (kb.mm(e0.y) - pos[1]) ** 2
                step = (short + NUDGE_EXTRA_MM) * 2  # an end move gains half its size at the far side of the segment
                if _move_end_checked(board, obstacles, track, 0 if d_start <= d_end else 1, nx * sign * step, ny * sign * step, rules, allowed=allowed):
                    moved_now += 1
                    break
        # a via against copper it cannot wait for (fixed copper, or a track that did not move this round): the
        # via moves away, straight or along whichever axis still gains the distance, since a via boxed on the
        # straight line is often free along an axis (the esp32c3's +5V vias either side of a diagonal USB_DP)
        # a track pressed from both sides only settles between them; when the corridor is too narrow it stays
        # short on both, so it counts as waiting, and the via pressing it gives way (rp2040's +5V track between
        # U1's pad and a +BATT via, 0.011 mm narrow, settled 0.0002 mm a round for twelve rounds)
        moved_ids = set(u for u in sides if u not in balanced and u not in stuck and not (sides[u][0] > 0 and sides[u][1] > 0))
        for v in violations:
            ours_v = [(u, p) for u, _d, p in v.items if u in vias]
            if not ours_v or v.short_mm <= 0:
                continue
            if any(u in moved_ids for u, _d, _p in v.items if u in tracks):
                continue
            for uuid, _p in ours_v:  # two vias of ours: whichever can give way (rp2040's SPI0_CSn1 against
                other = next(((u, p) for u, _d, p in v.items if u != uuid), None)  # MICRO_SD1's, boxed itself)
                if other is None:
                    continue
                via = vias[uuid]
                at = via.GetPosition()
                dx, dy = kb.mm(at.x) - other[1][0], kb.mm(at.y) - other[1][1]
                if other[0] in tracks:  # away from a track is along its normal, whichever side the via is on
                    nx, ny = _normal(tracks[other[0]])
                    sx, sy = _away(tracks[other[0]], (kb.mm(at.x), kb.mm(at.y)))
                    dx, dy = -sx, -sy
                length = (dx * dx + dy * dy) ** 0.5
                if length < 1e-9:
                    continue
                ux, uy = dx / length, dy / length
                candidates = [(ux, uy, 1.0)]
                for ax, ay in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
                    gain = ax * ux + ay * uy  # distance gained per unit moved along the axis
                    if gain > 0.3:
                        candidates.append((ax, ay, gain))
                done = False
                for cx, cy, gain in candidates:
                    step = (v.short_mm + NUDGE_EXTRA_MM) / gain
                    if _move_checked(board, obstacles, via, cx * step, cy * step, rules, allowed=frozenset({other[0]})):
                        moved_now += 1
                        done = True
                        break
                if done:
                    break
        # a track ending at a pad on the board edge: its end cap is what the edge rule sees; the end is pulled
        # back along the track into the pad's copper (open-book's BTN_LOCK at a castellated pad)
        for v in violations:
            if v.type != "copper_edge_clearance":
                continue
            ours_t = [u for u, _d, _p in v.items if u in tracks]
            if not ours_t:
                continue
            if _retract_into_pad(board, obstacles, tracks[ours_t[0]], v.short_mm + NUDGE_EXTRA_MM, rules):
                moved_now += 1
        report["moved"] += moved_now
        report["unfixable"] = unfixable
        if moved_now == 0:
            break
    left = index_violations(board, Obstacles(board), rules)
    report["remaining"] = len(left)
    report["worst_mm"] = max((v.short_mm for v in left), default=0.0)
    return report


def _track_key(track) -> tuple:
    """A geometric sort key: the session import gives every item a fresh uuid, so an order by uuid is an order
    by chance, and the repair's result changed between two runs of one board that way (D25)."""
    s, e = track.GetStart(), track.GetEnd()
    return (track.GetLayer(), min(s.x, e.x), min(s.y, e.y), max(s.x, e.x), max(s.y, e.y))


def _violation_key(v: Violation) -> tuple:
    """Type, the items' positions and descriptions (net, layer, length), and the shortfall: the report gives
    both items of a clearance violation the same position, so positions alone tie and fall back to report
    order (D25)."""
    return (v.type, tuple(sorted((p, d) for _u, d, p in v.items)), v.short_mm)


def _ours(board, v: Violation) -> bool:
    """Whether a violation involves copper the router laid (a track or via); a pair of fixed items is the
    placement's, as `bench.rebuild.board_facts` grades it, and no move can change it."""
    return any(d.startswith(("Track", "Via", "Arc")) for _u, d, _p in v.items)


# --- pads with the same number (D61) ------------------------------------------------------------------------
# KiCad exports the pieces of a pad with the same number as `REF-N`, `REF-N@1`, ... Where the pieces' copper
# overlaps (the fingers of `open-book-c1`'s buttons touch their round pad) KiCad's connectivity already joins
# them; Freerouting sees separate pins, cannot get between the interleaved fingers of the other net, and
# leaves 14 GND connections open. Where they do not overlap (the two `EP` pads of the smoke board's connector,
# 11.6 mm apart) KiCad wants copper between them, and so must the router. So only the overlapping pieces
# leave the net's pin list; they stay in the image as obstacles.
_PINS = re.compile(r"\(pins ([^)]*)\)")


def _pin_names(fp) -> list[str]:
    """The pin names KiCad's exporter gives a footprint's pads, in pad order: N, then N@1, N@2 for repeats."""
    seen: Counter = Counter()
    names = []
    for pad in fp.Pads():
        n = pad.GetNumber()
        names.append(n if seen[n] == 0 else f"{n}@{seen[n]}")
        seen[n] += 1
    return names


def _touch(a, b) -> bool:
    """Whether two pads' copper overlaps on a shared layer (board.py: the effective shape is the receiver)."""
    shared = [l for l in a.GetLayerSet().CuStack() if b.IsOnLayer(l)]
    if not shared:
        return False
    return bool(a.GetEffectiveShape(shared[0]).Collide(b.GetEffectiveShape(shared[0]), 0))


def joined_pins(board) -> set[str]:
    """Pin names (`REF-N@k`) of pad pieces joined by copper to another piece of the same number: one pin per
    connected group of pieces stays, the rest leave the router's pin lists."""
    out: set[str] = set()
    for fp in board.GetFootprints():
        pads = list(fp.Pads())
        names = _pin_names(fp)
        groups: dict[str, list[int]] = {}
        for i, pad in enumerate(pads):
            groups.setdefault(pad.GetNumber(), []).append(i)
        for idx in groups.values():
            if len(idx) < 2:
                continue
            parent = {i: i for i in idx}

            def find(i):
                while parent[i] != i:
                    i = parent[i]
                return i

            for a in idx:
                for b in idx:
                    if a < b and _touch(pads[a], pads[b]):
                        parent[find(b)] = find(a)
            comps: dict[int, list[int]] = {}
            for i in idx:
                comps.setdefault(find(i), []).append(i)
            for members in comps.values():  # the largest piece stays the pin: a plane reaches a round pad, not
                if len(members) < 2:  # a 0.2 mm finger walled in by the other net's fingers
                    continue
                keep = max(members, key=lambda i: _area(pads[i]))
                for i in members:
                    if i != keep:
                        out.add(f"{fp.GetReference()}-{names[i]}")
    return out


def _area(pad) -> float:
    layers = pad.GetLayerSet().CuStack()
    size = pad.GetSize(layers[0] if layers else pcbnew.F_Cu)
    return kb.mm(size.x) * kb.mm(size.y)


def drop_pins(dsn_text: str, names: set[str]) -> str:
    """Remove the named pins from every net's pin list in the network section."""
    start = dsn_text.find("(network")
    if start < 0 or not names:
        return dsn_text

    def strip(m: re.Match) -> str:
        kept = [pin for pin in m.group(1).split() if pin.replace('"', "") not in names]
        return "(pins " + " ".join(kept) + ")"

    return dsn_text[:start] + _PINS.sub(strip, dsn_text[start:])


# --- supply nets as pours (plan, milestone A) -------------------------------------------------------------------
def design_rules(board, rules) -> None:
    """Write the measured rules into the board's design settings, which is what the zone filler keeps: filled
    under KiCad's defaults the pours came within 0.25 mm of holes against a measured 0.4964 (13 hole-clearance
    violations on the smoke board, 8 on open-book)."""
    ds = board.GetDesignSettings()
    ds.m_MinClearance = kb.nm(rules.clearance_mm)
    ds.m_HoleClearance = kb.nm(rules.hole_to_copper_mm)
    ds.m_CopperEdgeClearance = kb.nm(rules.edge_clearance_mm)
    ds.m_TrackMinWidth = kb.nm(rules.min_track_mm)


def hole_rule_areas(board, rules) -> list:
    """A rule area forbidding copper pour around every hole whose copper ring is smaller than the hole rule:
    the filler keeps the zone clearance from a pad's copper, and a non-plated hole has none (open-book's pour
    came 0.1 mm too close to its four mounting holes on both layers). The circle is the hole plus the rule."""
    import math
    made = []
    enabled = [lid for lid, _n in kb.copper_layers(board)]  # a pad's layer set names all 32 copper ids
    sides = 64
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            drill = pad.GetDrillSize()
            hole = max(kb.mm(drill.x), kb.mm(drill.y))
            if hole <= 0:
                continue
            layers = [l for l in pad.GetLayerSet().CuStack() if l in enabled]
            size = pad.GetSize(layers[0]) if layers else drill
            ring = (min(kb.mm(size.x), kb.mm(size.y)) - hole) / 2
            if ring >= rules.hole_to_copper_mm:
                continue
            # circumscribed: the polygon's flat sides stay outside the circle of hole plus rule
            radius = (hole / 2 + rules.hole_to_copper_mm) / math.cos(math.pi / sides)
            pos = pad.GetPosition()
            for layer in (layers or enabled):
                zone = pcbnew.ZONE(board)
                zone.SetIsRuleArea(True)
                zone.SetDoNotAllowCopperPour(True)
                zone.SetDoNotAllowTracks(False)
                zone.SetDoNotAllowVias(False)
                zone.SetLayer(layer)
                outline = zone.Outline()
                outline.NewOutline()
                for k in range(sides):
                    a = 2 * math.pi * k / sides
                    outline.Append(pos.x + kb.nm(radius * math.cos(a)), pos.y + kb.nm(radius * math.sin(a)))
                board.Add(zone)
                made.append(zone)
    return made


def add_pours(board, pours: list[dict], rules, ring_mm: float | None = None) -> list:
    """Lay the recorded pours (`bench.rebuild.pour_facts`) as zones after the import, over the routed tracks.

    Laid before the export they become `(plane ...)` entries the router trusts: it left the SOT-563's middle GND
    pad to the plane, which KiCad's fill cannot reach past the neighbouring pads (D62). Routed as tracks first,
    GND is connected whatever the fill reaches, and the pour adds its copper on top; the gate says what that
    costs. The zone clearance is the larger of the reference's and the hole rule less the smallest ring on the
    board, since the fill keeps its clearance from a via's pad, not its hole (13 violations at 0.475 mm against
    0.4964). Returns the zones, unfilled; the gate fills them."""
    names = {name: lid for lid, name in kb.copper_layers(board)}
    nets = board.GetNetsByName()
    design_rules(board, rules)
    made = []
    for pour in pours:
        layer = names.get(pour["layer"])
        if layer is None or pour["net"] not in nets or len(pour["outline_mm"]) < 3:
            continue
        zone = pcbnew.ZONE(board)
        zone.SetNet(nets[pour["net"]])
        zone.SetLayer(layer)
        outline = zone.Outline()
        outline.NewOutline()
        for x, y in pour["outline_mm"]:
            outline.Append(kb.nm(x), kb.nm(y))
        clearance = max(pour["clearance_mm"], rules.clearance_mm)
        if ring_mm is not None:
            clearance = max(clearance, rules.hole_to_copper_mm - ring_mm)
        zone.SetLocalClearance(kb.nm(round(clearance, 4)))
        zone.SetMinThickness(kb.nm(max(pour["min_thickness_mm"], rules.min_track_mm)))
        try:
            zone.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL if pour["pad_connection"] == 1
                                  else pcbnew.ZONE_CONNECTION_FULL)
        except AttributeError:  # binding variants
            pass
        board.Add(zone)
        made.append(zone)
    return made


# --- escape stubs for fine-pitch rows (D51/D52) --------------------------------------------------------------
# A trace leaving a pad in a fine-pitch row must stay within a corridor: the neighbour pad's edge, less the
# clearance, less half the width. On the SOT-563 of `tinkerforge-temperature` the pads are 0.200 mm apart and
# the measured clearance is 0.1972, so the corridor is 0.003 mm wide. Measured (D56): Freerouting routes the
# board completely at a clearance of 0.190 and attaches nothing to that part at 0.1972, so it needs about
# 0.01 mm of slack that the reference's tightest spot does not have. The reference shows the exit that works:
# each end pad of the row turns away from the row at once, the middle pad goes straight and turns only past
# the row. The wrapper lays those exits itself, full width and exactly on the pad axis, as fixed wires: a
# straight leg along the pad's long axis away from the package, longer for pads nearer the row's centre, then a
# 45-degree leg towards the nearer end of the row, so every stub ends in free space. The router continues from
# the ends. Fixed wires do not come back in the session file, so the stubs are re-laid after the import.
STUB_SLACK_MM = 0.02  # a corridor narrower than this needs a stub
STUB_EXTRA_MM = 0.05  # how far past the last constraining neighbour a straight leg reaches
STUB_STEP_MM = 0.10  # extra straight length per pad towards the row's centre, so each turn clears the outer one
STUB_LEG_MM = 0.40  # the 45-degree leg


def _unit(deg: float) -> tuple[float, float]:
    """The pad's local x axis in board coordinates (KiCad's y points down, angles are counter-clockwise)."""
    import math
    r = math.radians(deg)
    return (math.cos(r), -math.sin(r))


def _pad_geometry(pad) -> tuple[tuple[float, float], tuple[float, float], float, float]:
    """(centre, long-axis unit vector, half length along it, half width across it), in mm."""
    pos = pad.GetPosition()
    layer = pad.GetLayerSet().CuStack()[0] if pad.GetLayerSet().CuStack() else pcbnew.F_Cu
    size = pad.GetSize(layer)
    sx, sy = kb.mm(size.x), kb.mm(size.y)
    ux, uy = _unit(float(pad.GetOrientationDegrees()))
    if sy > sx:  # long axis is the pad's local y
        ux, uy = -uy, ux
        sx, sy = sy, sx
    return (kb.mm(pos.x), kb.mm(pos.y)), (ux, uy), sx / 2, sy / 2


def _extent(axis: tuple[float, float], half_len: float, half_wid: float, direction: tuple[float, float]) -> float:
    """Half extent of a rectangle (long axis ``axis``) projected onto ``direction``."""
    ax, ay = axis
    dx, dy = direction
    return abs(ax * dx + ay * dy) * half_len + abs(-ay * dx + ax * dy) * half_wid


@dataclass(frozen=True)
class Stub:
    net: str
    layer: int
    width_mm: float
    points: tuple  # ((x, y), ...) in mm, from the pad centre outwards

    def length_mm(self) -> float:
        import math
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(self.points, self.points[1:]))


def escape_stubs(board, width_mm: float, clearance_mm: float, nets: set[str] | None = None) -> list[Stub]:
    """The exit stubs for every pad whose row leaves no corridor for the router (see above). Nothing is added to
    the board; :func:`lay_stubs` does that. Only pads of ``nets`` (default: nets on two or more pads) get one."""
    from waffle_eda.bench import rebuild
    nets = rebuild.routable_nets(board) if nets is None else nets
    reach = width_mm / 2 + clearance_mm
    stubs: list[Stub] = []
    for fp in board.GetFootprints():
        pads = [p for p in fp.Pads() if p.GetLayerSet().CuStack()]
        cx, cy = kb.mm(fp.GetPosition().x), kb.mm(fp.GetPosition().y)
        geo = {}
        for pad in pads:
            (px, py), (ux, uy), half_len, half_wid = _pad_geometry(pad)
            if (px - cx) * ux + (py - cy) * uy < 0:  # the exit points away from the package centre
                ux, uy = -ux, -uy
            geo[pad.GetNumber()] = ((px, py), (ux, uy), half_len, half_wid)
        # tight neighbours per pad, by side (+1 or -1 across the exit axis): the walls of its corridor
        walls: dict[str, dict[int, tuple[str, float]]] = {}  # pad -> side -> (neighbour, straight length needed)
        for pad in pads:
            num = pad.GetNumber()
            (px, py), (ux, uy), half_len, half_wid = geo[num]
            n = (-uy, ux)
            for other in pads:
                if other.GetNumber() == num:
                    continue
                (qx, qy), q_axis, q_half_len, q_half_wid = geo[other.GetNumber()]
                dx, dy = qx - px, qy - py
                along, side = dx * ux + dy * uy, dx * n[0] + dy * n[1]
                across = _extent(q_axis, q_half_len, q_half_wid, n)
                ahead = _extent(q_axis, q_half_len, q_half_wid, (ux, uy))
                slack = abs(side) - across - reach
                if slack < STUB_SLACK_MM and -ahead <= along <= half_len + ahead + reach:
                    need = along + ahead + reach + STUB_EXTRA_MM
                    sign = 1 if side > 0 else -1
                    prev = walls.setdefault(num, {}).get(sign)
                    if prev is None or need > prev[1]:
                        walls[num][sign] = (other.GetNumber(), need)

        def depth(num: str, sign: int) -> int:
            """How many tight pads sit beyond ``num`` on ``sign``'s side before the row ends."""
            seen, k = {num}, 0
            while sign in walls.get(num, {}):
                num = walls[num][sign][0]
                if num in seen:
                    break
                seen.add(num)
                k += 1
            return k

        for pad in pads:
            num = pad.GetNumber()
            if pad.GetNetname() not in nets or num not in walls:
                continue
            (px, py), (ux, uy), half_len, half_wid = geo[num]
            n = (-uy, ux)
            left, right = depth(num, -1), depth(num, 1)
            k = min(left, right)
            straight = max(v[1] for v in walls[num].values())
            straight = max(straight, half_len + reach + STUB_EXTRA_MM) + k * STUB_STEP_MM
            points = [(px, py), (px + ux * straight, py + uy * straight)]
            if left != right:  # turn towards the nearer end of the row; the middle pad of an odd row goes straight
                sign = -1 if left < right else 1
                if k == 0 and sign not in walls[num]:
                    pass
                d = 0.7071067811865476
                lx, ly = (ux + sign * n[0]) * d, (uy + sign * n[1]) * d
                x1, y1 = points[-1]
                points.append((x1 + lx * STUB_LEG_MM, y1 + ly * STUB_LEG_MM))
            else:
                x1, y1 = points[-1]
                points[-1] = (x1 + ux * STUB_STEP_MM, y1 + uy * STUB_STEP_MM)
            stubs.append(Stub(net=pad.GetNetname(), layer=pad.GetLayerSet().CuStack()[0], width_mm=width_mm,
                              points=tuple(points)))
    return stubs


def lay_stubs(board, stubs: list[Stub]) -> list:
    """Add the stubs to the board as tracks; returns the tracks."""
    nets = board.GetNetsByName()
    made = []
    for stub in stubs:
        for (ax, ay), (bx, by) in zip(stub.points, stub.points[1:]):
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(kb.nm(ax), kb.nm(ay)))
            track.SetEnd(pcbnew.VECTOR2I(kb.nm(bx), kb.nm(by)))
            track.SetWidth(kb.nm(stub.width_mm))
            track.SetLayer(stub.layer)
            track.SetNet(nets[stub.net])
            board.Add(track)
            made.append(track)
    return made


def fix_wires(dsn_text: str) -> str:
    """Type every exported wire as fixed: on a problem board the only wires at export time are the stubs."""
    return dsn_text.replace("(type route)", "(type fix)")


# Freerouting's `job_timeout` does not stop its auto-routing stage: only the fanout and optimiser stages read
# it (its scheduler thread checks isFanoutTimedOut and the optimiser's isTimedOut; crkbd routed on past a
# 14-minute job timeout to the 20-minute process cap, 2026-09-24). A run that must finish gets a pass budget.


def settings_json(work_dir: Path, threads: int, passes: int, fanout: bool = FANOUT,
                  edge_clearance_mm: float | None = None) -> Path:
    """Freerouting's settings file for this run, in the work directory: telemetry off, the log there, the fanout
    stage as configured. The file must carry a version and a profile id or the jar stops with an exception."""
    import json
    import uuid
    cfg = {"version": VERSION,
           "profile": {"id": str(uuid.uuid4()), "email": "", "allow_telemetry": False, "allow_contact": False},
           "gui": {"enabled": True, "input_directory": "", "dialog_confirmation_timeout": 5,
                   "show_routing_summary": False},
           "router": {"max_passes": passes, "max_threads": threads, "fanout": {"enabled": fanout},
                      "optimizer": {"max_threads": threads, "max_passes": OPTIMIZER_PASSES,
                                    "enabled": OPTIMIZER_PASSES > 0},
                      "scoring": {"via_costs": VIA_COSTS},
                      # the router's own default is 0.5 mm; open-book's rule is 0.5948 and its diagonal from a
                      # button pad cut the corner of a step in the edge at 0.25 mm (D66)
                      **({"copper_to_edge_clearance_um": round(edge_clearance_mm * 1000, 1)} if edge_clearance_mm else {})},
           "usage_and_diagnostic_data": {"disable_analytics": True, "track_window_changed": False,
                                         "track_button_clicked": False},
           "feature_flags": {"multi_threading": False},
           "logging": {"console": {"enabled": True, "level": "INFO"},
                       "file": {"enabled": True, "level": "INFO", "location": str(work_dir / "freerouting.log")}}}
    path = work_dir / "freerouting.json"
    path.write_text(json.dumps(cfg, indent=1))
    return path


def geometry_digest(board) -> str:
    """A short digest of the board's routed copper, independent of item order and uuids: two runs of one
    configuration must agree on it (D25), and a gate row carries it so a difference shows at a glance."""
    import hashlib
    rows = []
    for t in kb.track_segments(board) + kb.track_arcs(board):
        s, e = t.GetStart(), t.GetEnd()
        a, b = sorted(((s.x, s.y), (e.x, e.y)))
        rows.append(("t", t.GetLayer(), a, b, t.GetWidth(), t.GetNetname()))
    for v in kb.vias(board):
        p = v.GetPosition()
        rows.append(("v", p.x, p.y, v.GetDrillValue(), v.GetNetname()))
    return hashlib.sha1(repr(sorted(rows)).encode()).hexdigest()[:10]


# --- the run ----------------------------------------------------------------------------------------------------
@dataclass
class FreeroutingResult:
    """What the run did and what its log said, so a failure names the numbers and the files."""
    dsn: Path
    ses: Path
    log: Path
    rules: DsnRules
    renamed: int
    stubs: int = 0
    pours: int = 0
    widened: int = 0  # tracks the router necked below the rule, set back to it
    pruned: dict = field(default_factory=dict)  # duplicate and dangling segments removed
    repair: dict = field(default_factory=dict)  # what repair_clearances did
    digest: str = ""  # geometry_digest of the board handed back
    dsn_md5: str = ""  # of the DSN handed to the router: the same DSN must give the same session
    imported: str = ""  # geometry_digest of the router's output as imported, before the repair
    exported_layers: list = field(default_factory=list)
    passes: int = 0
    unrouted: int | None = None  # the router's own count at the end of its last stage
    violations: int | None = None  # the router's own count
    seconds: float = 0.0
    tracks: int = 0
    vias: int = 0
    exit_code: int | None = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.ses.is_file() and not self.timed_out and self.unrouted == 0

    def summary(self) -> str:
        state = "timed out" if self.timed_out else f"exit {self.exit_code}"
        return (f"freerouting {VERSION}: {state}, {self.passes} passes, router reports {self.unrouted} unrouted "
                f"and {self.violations} violations; imported {self.tracks} tracks, {self.vias} vias, "
                f"{self.widened} widened, pruned {self.pruned or 'none'}, repair {self.repair or 'none'}; dsn {self.dsn_md5} "
                f"imported {self.imported} "
                f"final {self.digest}; "
                f"{self.seconds:.0f}s")


_STAGE = re.compile(r"(Auto-routing|Optimization) stage completed:.*?final score: [\d.]+ \((\d+) unrouted and (\d+) violations\)")
_PASS = re.compile(r"Auto-routing pass #(\d+) ")


def parse_log(text: str) -> dict:
    """The router's own numbers from its log: passes run, and unrouted and violations after its last stage."""
    facts: dict = {"passes": 0, "unrouted": None, "violations": None}
    for m in _PASS.finditer(text):
        facts["passes"] = max(facts["passes"], int(m.group(1)))
    for m in _STAGE.finditer(text):
        facts["unrouted"], facts["violations"] = int(m.group(2)), int(m.group(3))
    return facts


def export_dsn(board, rules, out: Path, slack_all: bool = True) -> tuple[DsnRules, dict[str, str]]:
    """Write the DSN for ``board`` under ``rules``; the board is left with its references renamed (see
    :func:`unique_references`) so that the session can be imported into it, and the mapping is returned."""
    _via_ring, pin_ring = smallest_ring_mm(board)
    d = dsn_rules(rules, pin_ring, slack_all=slack_all)
    apply_rules(board, d)
    renamed = unique_references(board)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file():
        out.unlink()
    lifted = lift_pour_only_rule_areas(board)  # exported as full keepouts otherwise
    try:
        ok = pcbnew.ExportSpecctraDSN(board, str(out))
    finally:
        lay_rule_areas(board, lifted)
    if not ok or not out.is_file():
        raise RuntimeError(f"pcbnew.ExportSpecctraDSN returned {ok} and wrote {'a file' if out.is_file() else 'nothing'}"
                           f" (a duplicate reference is the known cause and was handled: {len(renamed)} renamed)")
    text = drop_pins(typed_clearances(out.read_text(), d), joined_pins(board))
    out.write_text(keepouts_dsn(text, pad_keepouts(board, d.clearance_mm, rules.hole_to_copper_mm)))
    return d, renamed


def run_jar(dsn: Path, ses: Path, log: Path, passes: int, threads: int, timeout_s: float,
            edge_clearance_mm: float | None = None) -> tuple[int | None, bool]:
    reason = available()
    if reason:
        raise RuntimeError(reason)
    settings_json(dsn.parent, threads, passes, edge_clearance_mm=edge_clearance_mm)
    cmd = ["xvfb-run", "-a", str(java_path()), "-jar", str(jar_path()), f"--user_data_path={dsn.parent}",
           "-de", str(dsn), "-do", str(ses), "-mp", str(passes), "-mt", str(threads)]
    if ses.is_file():
        ses.unlink()
    env = {k: v for k, v in os.environ.items() if k != "JAVA_TOOL_OPTIONS"}  # the proxy settings only add noise
    # the jar runs in its own process group: killing `xvfb-run` alone at the cap orphaned the JVM, which routed
    # on for twenty more minutes beside the next run (two crkbd runs at once, 2026-09-24; D57's empty session)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=dsn.parent,
                            env=env, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        log.write_text(out or "")
        return None, True
    log.write_text(out or "")  # the same text the settings file sends to freerouting.log
    return proc.returncode, False


def route_board(board, rules, work_dir: Path, passes: int = 30, threads: int = 1,
                timeout_s: float = 1200.0, stubs: bool = False, slack_all: bool = True,
                pours: list[dict] | None = None, say=lambda _m: None,
                router_edge_mm: float | None = None) -> FreeroutingResult:
    """Route every net of ``board`` under ``rules`` with Freerouting, in place. The board should carry no copper
    for the nets to route (the gate's problem board). ``work_dir`` receives the DSN, the session and the log."""
    t0 = time.time()
    work_dir = work_dir.resolve()  # the jar runs with the work directory as its cwd, so nothing relative survives
    work_dir.mkdir(parents=True, exist_ok=True)
    dsn, ses, log = work_dir / "board.dsn", work_dir / "board.ses", work_dir / "run.log"
    laid = escape_stubs(board, rules.min_track_mm, rules.clearance_mm) if stubs else []
    lay_stubs(board, laid)
    d, renamed = export_dsn(board, rules, dsn, slack_all=slack_all)
    if laid:
        dsn.write_text(fix_wires(dsn.read_text()))
    layers = re.findall(r"\(layer (\S+)\n\s*\(type", dsn.read_text())
    say(f"exported {dsn.name}: layers {layers}, {len(renamed)} references renamed, rules {d}")
    import hashlib
    dsn_md5 = hashlib.md5(dsn.read_bytes()).hexdigest()[:10]
    if router_edge_mm is None:  # the router's own margin closed rp2040's last corridor at the rule (D68)
        router_edge_mm = min(ROUTER_EDGE_MM, rules.edge_clearance_mm)
    code, timed_out = run_jar(dsn, ses, log, passes, threads, timeout_s, edge_clearance_mm=router_edge_mm)
    facts = parse_log(log.read_text())
    result = FreeroutingResult(dsn=dsn, ses=ses, log=log, rules=d, renamed=len(renamed), stubs=len(laid),
                               exported_layers=layers,
                               passes=facts["passes"], unrouted=facts["unrouted"], violations=facts["violations"],
                               exit_code=code, timed_out=timed_out, dsn_md5=dsn_md5)
    if ses.is_file():
        before = len(list(board.GetTracks()))
        if not pcbnew.ImportSpecctraSES(board, str(ses)):
            raise RuntimeError(f"pcbnew.ImportSpecctraSES returned False for {ses}")
        result.pruned = prune_dangling(board)
        result.widened = widen_tracks(board, d.width_mm)
        result.imported = geometry_digest(board)
        kb.save_board(board, work_dir / "imported.kicad_pcb")  # the router's output as imported: the repair
        say(f"saved {work_dir / 'imported.kicad_pcb'}")  # alone can be rerun on it (scripts/repair_only.py)
        result.repair = repair_clearances(board, rules, work_dir / "repair")
        say(f"repair: {result.repair}")
        via_ring, pin_ring = smallest_ring_mm(board)
        rings = [r for r in (via_ring, pin_ring) if r is not None]
        if pours:
            hole_rule_areas(board, rules)
        result.pours = len(add_pours(board, pours or [], rules, ring_mm=min(rings) if rings else None))
        say(f"pours: {result.pours}")
        result.tracks = len(kb.track_segments(board)) + len(kb.track_arcs(board))
        result.vias = len(kb.vias(board))
        say(f"imported {ses.name}: tracks+vias {before} -> {result.tracks + result.vias}")
        if laid:  # the session file does not carry fixed wires; the import dropped them with the rest
            lay_stubs(board, laid)
    restore_references(board, renamed)
    result.digest = geometry_digest(board)
    result.seconds = round(time.time() - t0, 1)
    return result
