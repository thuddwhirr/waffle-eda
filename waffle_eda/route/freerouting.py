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
# 0.190 it connects the whole board. So the clearance between a wire and an SMD pad is handed over as the rule
# less this slack, and the gate's DRC reports where the router used it. Every other clearance is handed over
# exactly: on `libresolar-mppt-2420` a global slack produced 175 track-to-track and track-to-via violations of
# exactly that slack. ``slack_all`` in :func:`dsn_rules` applies it globally for a measurement.
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


def dsn_rules(rules, pin_ring_mm: float | None, slack_all: bool = False) -> DsnRules:
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
                f"and {self.violations} violations; imported {self.tracks} tracks, {self.vias} vias; "
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


def export_dsn(board, rules, out: Path, slack_all: bool = False) -> tuple[DsnRules, dict[str, str]]:
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
    out.write_text(typed_clearances(out.read_text(), d))
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
                timeout_s: float = 1200.0, stubs: bool = False, slack_all: bool = False,
                say=lambda _m: None) -> FreeroutingResult:
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
        result.tracks = len(kb.track_segments(board)) + len(kb.track_arcs(board))
        result.vias = len(kb.vias(board))
        say(f"imported {ses.name}: tracks+vias {before} -> {result.tracks + result.vias}")
        if laid:  # the session file does not carry fixed wires; the import dropped them with the rest
            lay_stubs(board, laid)
    restore_references(board, renamed)
    result.seconds = round(time.time() - t0, 1)
    return result
