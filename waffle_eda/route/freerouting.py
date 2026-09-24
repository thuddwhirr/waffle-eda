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

Salvaged mechanics (`salvage/waffle-fpga/hw/tools/export_dsn.py`, `staged_route.sh`) that class A does not
need yet and that are not implemented here: plane layers typed `power` (class B), rule areas dropped from the
export (class B+), and staged routing through `(pins)` removal (class C).
"""
from __future__ import annotations

import os
import re
import shutil
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
NUDGE_EXTRA_MM = 0.0005
REPAIR_ROUNDS = 8


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


def _room(board, obstacles, track, ux: float, uy: float, rules, limit_mm: float = 0.05) -> float:
    """How far ``track`` can move along the unit vector (ux, uy) before colliding, by bisection of trial moves."""
    lo, hi = 0.0, limit_mm
    if _move_checked(board, obstacles, track, ux * hi, uy * hi, rules, keep=False):
        return hi
    for _ in range(8):
        mid = (lo + hi) / 2
        if _move_checked(board, obstacles, track, ux * mid, uy * mid, rules, keep=False):
            lo = mid
        else:
            hi = mid
    return lo


def _hit_ids(obstacles, item, rules) -> set[str]:
    """The uuids of the other-net copper ``item`` collides with under the rules."""
    return {o.m_Uuid.AsString() for o in obstacles._collisions(item, rules.clearance_mm, rules.hole_to_copper_mm)}


def _with_ends(board, item) -> list:
    """``item`` and the tracks of its net whose ends sit on it (a via's position, or a track's ends)."""
    is_via = item.GetClass() == "PCB_VIA"
    net = item.GetNetCode()
    if is_via:
        ends = (pcbnew.VECTOR2I(item.GetPosition()),)
    else:
        ends = (pcbnew.VECTOR2I(item.GetStart()), pcbnew.VECTOR2I(item.GetEnd()))
    return [item] + [o for o in kb.track_segments(board) if o.GetNetCode() == net
                     and o.m_Uuid.AsString() != item.m_Uuid.AsString()
                     and (is_via or o.GetLayer() == item.GetLayer())
                     and (o.GetStart() in ends or o.GetEnd() in ends)]


def _move_checked(board, obstacles, item, dx_mm: float, dy_mm: float, rules, keep: bool = True) -> bool:
    """Move a track (and the ends it shares) or a via (and the track ends on it) and keep the move only if it
    makes no new collision under the exact collision index. A collision that exists before the move is what
    the move is there to resolve, and may persist until a later round finishes the job."""
    moved = _with_ends(board, item)
    before = {m.m_Uuid.AsString(): _hit_ids(obstacles, m, rules) for m in moved}
    for m in moved:
        obstacles.remove(m)
    _move(board, item, moved, kb.nm(dx_mm), kb.nm(dy_mm))
    clean = all(_hit_ids(obstacles, m, rules) <= before[m.m_Uuid.AsString()] for m in moved)
    if not clean or not keep:
        _move(board, item, moved, -kb.nm(dx_mm), -kb.nm(dy_mm))
    for m in moved:
        obstacles.add(m)
    return clean


def _blocker(board, obstacles, item, ux: float, uy: float, distance_mm: float, rules):
    """The first other-net copper ``item`` newly meets when moved ``distance_mm`` along (ux, uy), or None."""
    moved = _with_ends(board, item)
    before = {m.m_Uuid.AsString(): _hit_ids(obstacles, m, rules) for m in moved}
    for m in moved:
        obstacles.remove(m)
    _move(board, item, moved, kb.nm(ux * distance_mm), kb.nm(uy * distance_mm))
    hit = None
    for m in moved:
        new = [o for o in obstacles._collisions(m, rules.clearance_mm, rules.hole_to_copper_mm)
               if o.m_Uuid.AsString() not in before[m.m_Uuid.AsString()]]
        if new:
            hit = new[0]
            break
    _move(board, item, moved, -kb.nm(ux * distance_mm), -kb.nm(uy * distance_mm))
    for m in moved:
        obstacles.add(m)
    return hit


def _move(board, item, moved, dx_nm: int, dy_nm: int) -> None:
    """Translate ``item`` and the ends of ``moved`` that sit on it."""
    if item.GetClass() == "PCB_VIA":
        at = item.GetPosition()
        for o in moved:
            if o is item:
                continue
            if o.GetStart() == at:
                o.SetStart(pcbnew.VECTOR2I(at.x + dx_nm, at.y + dy_nm))
            if o.GetEnd() == at:
                o.SetEnd(pcbnew.VECTOR2I(at.x + dx_nm, at.y + dy_nm))
        item.SetPosition(pcbnew.VECTOR2I(at.x + dx_nm, at.y + dy_nm))
    else:
        _move_track(board, item, dx_nm, dy_nm)


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


def repair_clearances(board, rules, work_dir: Path, rounds: int = REPAIR_ROUNDS) -> dict:
    """Move tracks a few micrometres away from what they violate, under KiCad's own DRC, until it is clean.

    A track is moved once per round, by the largest shortfall on its open side plus a hair, or, when it is
    pressed from both sides, by half the difference of the two shortfalls, so it settles between its
    neighbours; the outcome does not depend on the order KiCad lists the violations (D25). The smoke board's
    three parallel SOT-563 exits oscillated under one move per violation, and overshot under a summed push."""
    from waffle_eda.route.obstacles import Obstacles
    design_rules(board, rules)  # the index reads the edge clearance from the design settings
    report = {"rounds": 0, "moved": 0, "remaining": 0, "unfixable": 0}
    for round_no in range(1, rounds + 1):
        report["rounds"] = round_no
        violations = [v for v in drc_violations(board, rules, work_dir / f"round{round_no}")
                      if v.type in ("clearance", "hole_clearance")]
        report["remaining"] = len(violations)
        if not violations:
            return report
        tracks = {t.m_Uuid.AsString(): t for t in kb.track_segments(board)}
        via_ids = {v.m_Uuid.AsString() for v in kb.vias(board)}
        # per track: the shortfalls on each side of it, along its own normal
        sides: dict[str, list[float]] = {}
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
        moved_now = 0
        obstacles = Obstacles(board)  # at the rule alone: the DRC rounds hold the per-pad overrides
        stuck: list[str] = []
        for uuid, (plus, minus) in sorted(sides.items()):
            nx, ny = normals[uuid]
            if plus > 0 and minus > 0:  # pressed from both sides: settle in the middle, no extra
                step = (plus - minus) / 2
            else:
                step = plus + NUDGE_EXTRA_MM if plus > 0 else -(minus + NUDGE_EXTRA_MM)
            if abs(step) < 1e-6:
                continue
            track = tracks[uuid]
            short = abs(step) - NUDGE_EXTRA_MM if not (plus > 0 and minus > 0) else abs(step)
            sign = 1 if step > 0 else -1
            room = _room(board, obstacles, track, nx * sign, ny * sign, rules)  # free travel that way
            if room < short - 1e-6:  # boxed in: no translation clears both sides
                stuck.append(uuid)
                continue
            move = min(abs(step), (short + room) / 2)  # the middle of the corridor, or the step if there is room
            if _move_checked(board, obstacles, track, nx * sign * move, ny * sign * move, rules):
                moved_now += 1
            else:
                stuck.append(uuid)
        # a track boxed in: the item it violates, then whatever blocks its way on the far side, is pushed
        # instead, where that is ours (a via or a track)
        vias = {v.m_Uuid.AsString(): v for v in kb.vias(board)}
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
                other = next((vias.get(u) or tracks.get(u) for u in ids if u != uuid), None)
                if other is None or other.m_Uuid.AsString() in sides:
                    continue
                step = v.short_mm + 2 * NUDGE_EXTRA_MM
                if _move_checked(board, obstacles, other, -nx * sign * step, -ny * sign * step, rules):
                    moved_now += 1
                    pushed = True
            if pushed:
                continue
            blocker = _blocker(board, obstacles, track, nx * sign, ny * sign, short + NUDGE_EXTRA_MM, rules)
            if blocker is None:
                continue
            uid = blocker.m_Uuid.AsString()
            other = vias.get(uid) or tracks.get(uid)
            if other is None or uid in sides:
                continue
            step = short + 2 * NUDGE_EXTRA_MM
            if _move_checked(board, obstacles, other, nx * sign * step, ny * sign * step, rules):
                moved_now += 1
        # a via against fixed copper: the via moves away from it
        for v in violations:
            ours_v = [(u, p) for u, _d, p in v.items if u in vias]
            if not ours_v or any(u in tracks for u, _d, _p in v.items) or v.short_mm <= 0:
                continue
            uuid, _p = ours_v[0]
            other = next(((u, p) for u, _d, p in v.items if u != uuid), None)
            if other is None:
                continue
            via = vias[uuid]
            at = via.GetPosition()
            dx, dy = kb.mm(at.x) - other[1][0], kb.mm(at.y) - other[1][1]
            length = (dx * dx + dy * dy) ** 0.5
            if length < 1e-9:
                continue
            ux, uy = dx / length, dy / length
            step = v.short_mm + NUDGE_EXTRA_MM
            for attempt in (step, step / 2):
                if _move_checked(board, obstacles, via, ux * attempt, uy * attempt, rules):
                    moved_now += 1
                    break
        report["moved"] += moved_now
        report["unfixable"] = unfixable
        if moved_now == 0:
            break
    violations = [v for v in drc_violations(board, rules, work_dir / "final")
                  if v.type in ("clearance", "hole_clearance")]
    report["remaining"] = len(violations)
    return report


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


def settings_json(work_dir: Path, threads: int, passes: int, fanout: bool = FANOUT) -> Path:
    """Freerouting's settings file for this run, in the work directory: telemetry off, the log there, the fanout
    stage as configured. The file must carry a version and a profile id or the jar stops with an exception."""
    import json
    import uuid
    cfg = {"version": VERSION,
           "profile": {"id": str(uuid.uuid4()), "email": "", "allow_telemetry": False, "allow_contact": False},
           "gui": {"enabled": True, "input_directory": "", "dialog_confirmation_timeout": 5,
                   "show_routing_summary": False},
           "router": {"max_passes": passes, "max_threads": threads, "fanout": {"enabled": fanout},
                      "optimizer": {"max_threads": threads}, "scoring": {"via_costs": VIA_COSTS}},
           "usage_and_diagnostic_data": {"disable_analytics": True, "track_window_changed": False,
                                         "track_button_clicked": False},
           "feature_flags": {"multi_threading": False},
           "logging": {"console": {"enabled": True, "level": "INFO"},
                       "file": {"enabled": True, "level": "INFO", "location": str(work_dir / "freerouting.log")}}}
    path = work_dir / "freerouting.json"
    path.write_text(json.dumps(cfg, indent=1))
    return path


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
    repair: dict = field(default_factory=dict)  # what repair_clearances did
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
                f"{self.widened} widened, repair {self.repair or 'none'}; "
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
    ok = pcbnew.ExportSpecctraDSN(board, str(out))
    if not ok or not out.is_file():
        raise RuntimeError(f"pcbnew.ExportSpecctraDSN returned {ok} and wrote {'a file' if out.is_file() else 'nothing'}"
                           f" (a duplicate reference is the known cause and was handled: {len(renamed)} renamed)")
    text = drop_pins(typed_clearances(out.read_text(), d), joined_pins(board))
    out.write_text(keepouts_dsn(text, pad_keepouts(board, d.clearance_mm, rules.hole_to_copper_mm)))
    return d, renamed


def run_jar(dsn: Path, ses: Path, log: Path, passes: int, threads: int, timeout_s: float) -> tuple[int | None, bool]:
    reason = available()
    if reason:
        raise RuntimeError(reason)
    settings_json(dsn.parent, threads, passes)
    cmd = ["xvfb-run", "-a", str(java_path()), "-jar", str(jar_path()), f"--user_data_path={dsn.parent}",
           "-de", str(dsn), "-do", str(ses), "-mp", str(passes), "-mt", str(threads)]
    if ses.is_file():
        ses.unlink()
    env = {k: v for k, v in os.environ.items() if k != "JAVA_TOOL_OPTIONS"}  # the proxy settings only add noise
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, cwd=dsn.parent, env=env)
    except subprocess.TimeoutExpired as why:
        log.write_text((why.stdout or b"").decode(errors="replace") + (why.stderr or b"").decode(errors="replace"))
        return None, True
    log.write_text(r.stdout + r.stderr)  # the same text the settings file sends to freerouting.log
    return r.returncode, False


def route_board(board, rules, work_dir: Path, passes: int = 30, threads: int = 1,
                timeout_s: float = 1200.0, stubs: bool = False, slack_all: bool = True,
                pours: list[dict] | None = None, say=lambda _m: None) -> FreeroutingResult:
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
    code, timed_out = run_jar(dsn, ses, log, passes, threads, timeout_s)
    facts = parse_log(log.read_text())
    result = FreeroutingResult(dsn=dsn, ses=ses, log=log, rules=d, renamed=len(renamed), stubs=len(laid),
                               exported_layers=layers,
                               passes=facts["passes"], unrouted=facts["unrouted"], violations=facts["violations"],
                               exit_code=code, timed_out=timed_out)
    if ses.is_file():
        before = len(list(board.GetTracks()))
        if not pcbnew.ImportSpecctraSES(board, str(ses)):
            raise RuntimeError(f"pcbnew.ImportSpecctraSES returned False for {ses}")
        result.widened = widen_tracks(board, d.width_mm)
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
    result.seconds = round(time.time() - t0, 1)
    return result
