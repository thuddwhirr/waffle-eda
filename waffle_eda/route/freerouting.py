"""Stage 5's baseline router: Freerouting, driven headless under the board's measured rules (plan.md, milestone A).

D55 says each stage uses the cheapest existing tool that passes the class, and for stage 5 of class A that is
Freerouting. This module is the whole of what it takes to hand a board to it and get the copper back:

1. **Export.** ``pcbnew.ExportSpecctraDSN`` on the board, after the rules have been written into the board's
   net classes, because the DSN carries the net classes' width, clearance and via and nothing else. The
   exporter refuses a board on which two footprints share a reference designator (every real board has two
   logos or two fiducials called the same), so references are made unique for the round trip and restored
   after the import.
2. **Rules.** Freerouting has one clearance and no hole-to-copper rule. KiCad's DRC has both, and a via whose
   ring is thinner than the hole rule minus the clearance is a violation however it is routed. So the DSN's
   structure rule gets a larger clearance for the pairs that involve a via or a through-hole pin, computed
   from the measured hole-to-copper minus the ring, and non-plated holes are exported as keepouts grown by
   the same rule (the exporter sizes them from the board's hole clearance setting).
3. **Run.** The jar, headless, with its own settings file in the work directory so nothing depends on a
   settings file in the user's home; bounded by a pass count and a wall-clock budget (definition.md,
   section 3: a run that has not converged within its budget stops and reports).
4. **Import.** ``pcbnew.ImportSpecctraSES`` into the same board object; references restored.

What the salvaged scripts knew that still holds (D51 of the old project): every rule area exports as a keepout;
plane layers must be typed ``power`` (none on a class A board); a ``fix``-typed wire freezes its whole net.
"""
from __future__ import annotations

import collections
import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import pcbnew

from waffle_eda.kicad import board as kb

JAR_VERSION = "2.4.1"
JAR_SHA256 = "251101c3eeac22d7e7dfcf6796603279e5d1000283eb82d8f093780f7afc6aa9"
JAR_URL = f"https://github.com/freerouting/freerouting/releases/download/v{JAR_VERSION}/freerouting-{JAR_VERSION}.jar"
JAVA_MAJOR = 25  # freerouting 2.4.1 is compiled for class file version 69
NECK_RATIO = 0.75  # the fanout stage necks a pad's escape to this fraction of the class width (measured, 2026-09-23)
STUB_MARGIN_MM = 0.05  # a repaired escape leaves its pad straight by this much beyond the pad's edge


class FreeroutingUnavailable(RuntimeError):
    """The jar or a Java new enough to run it is not on this machine."""


# --- finding the tool ----------------------------------------------------------------------------------------
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def jar_path() -> Path:
    """``WAFFLE_FREEROUTING_JAR`` or the pinned jar under ``build/tools/`` (fetched by
    ``scripts/fetch_freerouting.py``, never committed: it is 64 MB)."""
    env = os.environ.get("WAFFLE_FREEROUTING_JAR")
    if env:
        return Path(env)
    return repo_root() / "build" / "tools" / f"freerouting-{JAR_VERSION}.jar"


def _java_major(java: str) -> int | None:
    try:
        out = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r'version "(\d+)', out.stderr + out.stdout)
    return int(m.group(1)) if m else None


def java_path(major: int = JAVA_MAJOR) -> str:
    """``WAFFLE_JAVA``, else the ``java`` on the path if it is new enough, else the newest JDK in /usr/lib/jvm."""
    env = os.environ.get("WAFFLE_JAVA")
    if env:
        return env
    candidates = []
    on_path = shutil.which("java")
    if on_path:
        candidates.append(on_path)
    candidates += sorted((str(p) for p in Path("/usr/lib/jvm").glob("*/bin/java")), reverse=True)
    for java in candidates:
        v = _java_major(java)
        if v is not None and v >= major:
            return java
    raise FreeroutingUnavailable(f"no Java {major}+ found (tried {candidates or 'nothing'}); set WAFFLE_JAVA")


def check() -> tuple[Path, str]:
    jar = jar_path()
    if not jar.is_file():
        raise FreeroutingUnavailable(f"{jar} is missing; run scripts/fetch_freerouting.py or set WAFFLE_FREEROUTING_JAR")
    return jar, java_path()


# --- references ----------------------------------------------------------------------------------------------
def unique_references(board) -> dict[str, str]:
    """Give every footprint a unique, non-empty reference for the DSN round trip. Returns uuid -> original
    reference for the ones renamed, for :func:`restore_references`."""
    seen = collections.Counter(fp.GetReference() for fp in board.GetFootprints())
    counts: collections.Counter = collections.Counter()
    renamed: dict[str, str] = {}
    for fp in board.GetFootprints():
        r = fp.GetReference()
        counts[r] += 1
        if r == "" or seen[r] > 1:
            renamed[fp.m_Uuid.AsString()] = r
            fp.SetReference(f"{r or 'X'}__{counts[r]}")
    return renamed


def restore_references(board, renamed: dict[str, str]) -> None:
    for fp in board.GetFootprints():
        u = fp.m_Uuid.AsString()
        if u in renamed:
            fp.SetReference(renamed[u])


# --- rules ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DsnRules:
    """What goes into the DSN, derived from the board's measured rules (`bench.rebuild.BoardRules`)."""

    clearance_mm: float  # copper to copper, every pair
    via_clearance_mm: float  # pairs with a via: the hole rule minus the via's ring, if larger
    pin_clearance_mm: float  # pairs with a through-hole pad: the hole rule minus the thinnest pin ring, if larger
    hole_keepout_mm: float  # a non-plated hole's keepout grows by this (the exporter reads it from the board)
    width_mm: float
    via_mm: float
    drill_mm: float

    def summary(self) -> str:
        return (f"clearance {self.clearance_mm} (via {self.via_clearance_mm}, pin {self.pin_clearance_mm}), "
                f"width {self.width_mm}, via {self.via_mm}/{self.drill_mm}, hole keepout {self.hole_keepout_mm}")


def _round_up(x: float, step: float = 0.001) -> float:
    return round((int(x / step + 1 - 1e-9)) * step, 4)


def dsn_rules(board, rules, margin_mm: float = 0.0) -> DsnRules:
    """The DSN rules from the measured ones. ``margin_mm`` is added to every clearance when a measurement shows
    the router undercutting its own rule (the old project saw about 0.02 mm on 45-degree geometry)."""
    clearance = _round_up(rules.clearance_mm + margin_mm)
    hole = rules.hole_to_copper_mm
    via_ring = (rules.min_via_mm - rules.min_drill_mm) / 2
    via_clearance = max(clearance, _round_up(hole - via_ring + margin_mm))
    pin_rings = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() and pad.GetDrillSizeX() > 0:
                size = pad.GetSize(pcbnew.F_Cu)
                ring = min(kb.mm(size.x) - kb.mm(pad.GetDrillSizeX()), kb.mm(size.y) - kb.mm(pad.GetDrillSizeY())) / 2
                pin_rings.append(ring)
    pin_clearance = max(clearance, _round_up(hole - min(pin_rings) + margin_mm)) if pin_rings else clearance
    return DsnRules(clearance_mm=clearance, via_clearance_mm=via_clearance, pin_clearance_mm=pin_clearance,
                    hole_keepout_mm=max(0.0, _round_up(hole - clearance + margin_mm)),
                    width_mm=rules.min_track_mm, via_mm=rules.min_via_mm, drill_mm=rules.min_drill_mm)


def apply_rules(board, dsn: DsnRules) -> dict[str, int]:
    """Write the DSN rules into the board's net classes and settings, which is where the exporter reads them.
    A class keeps its own width and via where they already satisfy the measured minimums (a wide power class
    is the reference's intent); its clearance is always the measured one, because the measured value is what
    the reference demonstrates and what the gate checks.

    Returns the class widths (nm), which :func:`repair_necks` restores after the import. (Handing the router
    the width over ``NECK_RATIO`` so its necks land on the class width was measured on 2026-09-23 and lost:
    3 of 6 nets on the smoke test against 5 of 6 at the class width.)"""
    widths = {}
    for name, nc in board.GetAllNetClasses().items():
        nc.SetClearance(kb.nm(dsn.clearance_mm))
        width = max(nc.GetTrackWidth(), kb.nm(dsn.width_mm))
        widths[str(name)] = width
        nc.SetTrackWidth(width)
        ring_ok = (nc.GetViaDiameter() - nc.GetViaDrill()) >= (kb.nm(dsn.via_mm) - kb.nm(dsn.drill_mm))
        if nc.GetViaDiameter() < kb.nm(dsn.via_mm) or nc.GetViaDrill() < kb.nm(dsn.drill_mm) or not ring_ok:
            nc.SetViaDiameter(kb.nm(dsn.via_mm))
            nc.SetViaDrill(kb.nm(dsn.drill_mm))
    ds = board.GetDesignSettings()
    ds.m_HoleClearance = kb.nm(dsn.hole_keepout_mm)
    return widths


def _pad_at(board, point, net_code: int, layer: int):
    """The pad of net ``net_code`` on ``layer`` whose copper contains ``point``, or None."""
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() == net_code and pad.IsOnLayer(layer) and pad.HitTest(point):
                return fp, pad
    return None


NUDGE_MM = (0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5)
JOIN_TOL_NM = 10_000  # two track ends within 10 um are joined


def _joined(board, point, net_code: int, layer: int, uid: str) -> list:
    """The other tracks of the net on ``layer`` with an end at ``point``, each with which end it is."""
    out = []
    for t in kb.track_segments(board):
        if t.GetNetCode() != net_code or t.GetLayer() != layer or t.m_Uuid.AsString() == uid:
            continue
        for which in ("start", "end"):
            q = t.GetStart() if which == "start" else t.GetEnd()
            if abs(q.x - point.x) <= JOIN_TOL_NM and abs(q.y - point.y) <= JOIN_TOL_NM:
                out.append((t, which))
    return out


def _on_via(board, point, net_code: int) -> bool:
    for v in kb.vias(board):
        if v.GetNetCode() == net_code:
            q = v.GetPosition()
            if abs(q.x - point.x) <= JOIN_TOL_NM and abs(q.y - point.y) <= JOIN_TOL_NM:
                return True
    return False


def _nudge(board, obs, t, want: int, clr: float, hole: float) -> bool:
    """Widen ``t`` to ``want`` and move it sideways, by the smallest offset at which it and every track joined
    to a moved end clear the other nets. A neck through a channel is off its centre by the router's choice
    of turn, and a full-width track fits the same channel centred (measured 2026-09-23). An end that sits on
    a via stays. Returns whether it was done; the board and the index are unchanged on failure."""
    net, layer, uid = t.GetNetCode(), t.GetLayer(), t.m_Uuid.AsString()
    # GetStart/GetEnd hand back the live vector, not a copy: every point kept across a SetStart is copied
    s, e = pcbnew.VECTOR2I(t.GetStart()), pcbnew.VECTOR2I(t.GetEnd())
    dx, dy = e.x - s.x, e.y - s.y
    length = math.hypot(dx, dy)
    if length < 1:
        return False
    nx, ny = -dy / length, dx / length
    movable = {"start": not _on_via(board, s, net), "end": not _on_via(board, e, net)}
    joined = {"start": _joined(board, s, net, layer, uid), "end": _joined(board, e, net, layer, uid)}
    plans = [("start", "end"), ("start",), ("end",)]
    for d_mm in NUDGE_MM:
        for sign in (1, -1):
            for ends in plans:
                if not all(movable[w] for w in ends):
                    continue
                shift = pcbnew.VECTOR2I(int(round(nx * kb.nm(d_mm) * sign)), int(round(ny * kb.nm(d_mm) * sign)))
                touched = [t] + [j for w in ends for j, _ in joined[w]]
                saved = [(x, pcbnew.VECTOR2I(x.GetStart()), pcbnew.VECTOR2I(x.GetEnd()), x.GetWidth()) for x in touched]
                for x in touched:
                    obs.remove(x)
                t.SetWidth(want)
                if "start" in ends:
                    t.SetStart(s + shift)
                    for j, which in joined["start"]:
                        (j.SetStart if which == "start" else j.SetEnd)((s + shift))
                if "end" in ends:
                    t.SetEnd(e + shift)
                    for j, which in joined["end"]:
                        (j.SetStart if which == "start" else j.SetEnd)((e + shift))
                ok = all(obs.clear(x, clr, hole_clearance_mm=hole) is None for x in touched)
                if ok:
                    for x in touched:
                        obs.add(x)
                    return True
                for x, s0, e0, w0 in saved:
                    x.SetStart(s0)
                    x.SetEnd(e0)
                    x.SetWidth(w0)
                for x in touched:
                    obs.add(x)
    return False


def repair_necks(board, widths: dict[str, int], floor_nm: int, rules) -> dict[str, int]:
    """Every track the router necked below its class width is set back to it: in place where that clears
    the other nets, else nudged sideways with the tracks joined to it (:func:`_nudge`), else, for an escape
    angled out of a pad, re-laid to leave the pad straight along its axis (the finding of D51/D52) and turn
    where the router turned. Collisions are judged by the exact index every router here uses. Returns counts;
    ``left`` is what could not be repaired and will fail the DRC."""
    from waffle_eda.route import stitch
    from waffle_eda.route.obstacles import Obstacles

    counts = {"widened": 0, "nudged": 0, "relaid": 0, "left": 0}
    default = max(widths.get("Default", floor_nm), floor_nm)
    necked = []
    for t in kb.track_segments(board):
        net = t.GetNet()
        cls = str(net.GetNetClassName()) if net else ""
        want = max(widths.get(cls, default), floor_nm)
        if t.GetWidth() < want:
            necked.append((t, want))
    if not necked:
        return counts
    obs = Obstacles(board)
    clr, hole = rules.clearance_mm, rules.hole_to_copper_mm
    for t, want in necked:
        obs.remove(t)
        was = t.GetWidth()
        t.SetWidth(want)
        if obs.clear(t, clr, hole_clearance_mm=hole) is None:
            obs.add(t)
            counts["widened"] += 1
            continue
        t.SetWidth(was)
        obs.add(t)
        if _nudge(board, obs, t, want, clr, hole):
            counts["nudged"] += 1
            continue
        obs.remove(t)
        relaid = False
        for pad_end, other_end in ((t.GetStart(), t.GetEnd()), (t.GetEnd(), t.GetStart())):
            found = _pad_at(board, pad_end, t.GetNetCode(), t.GetLayer())
            if not found:
                continue
            fp, pad = found
            axis = stitch.pad_axis(pad, fp)
            c = pad.GetPosition()
            reach = stitch._pad_half_extent(pad, axis) + kb.mm(want) / 2 + STUB_MARGIN_MM
            knee = (kb.mm(c.x) + axis[0] * reach, kb.mm(c.y) + axis[1] * reach)
            a = stitch._track(board, t.GetLayer(), (kb.mm(c.x), kb.mm(c.y)), knee, t.GetNet(), kb.mm(want))
            b = stitch._track(board, t.GetLayer(), knee, (kb.mm(other_end.x), kb.mm(other_end.y)), t.GetNet(), kb.mm(want))
            if obs.clear(a, clr, hole_clearance_mm=hole) is None and obs.clear(b, clr, hole_clearance_mm=hole) is None:
                board.Delete(t)
                board.Add(a)
                board.Add(b)
                obs.add(a)
                obs.add(b)
                relaid = True
                break
        if relaid:
            counts["relaid"] += 1
        else:
            obs.add(t)
            counts["left"] += 1
    return counts


_STRUCTURE_RULE = re.compile(r"(\(structure\n(?:.*\n)*?\s*\(rule\n)((?:\s*\(.*\)\n)*?)(\s*\)\n)")
_PLAIN_CLEARANCE = re.compile(r"^\s*\(clearance [\d.]+\)\n", re.MULTILINE)


def type_clearances(dsn: DsnRules) -> dict[tuple[str, str], float]:
    """The per-pair clearances the hole rule needs, in mm, for the item classes Freerouting knows (wire, via,
    pin, smd, area). A via-to-pin pair needs the larger of the two, since either hole faces the other's copper."""
    pairs: dict[tuple[str, str], float] = {}
    if dsn.via_clearance_mm > dsn.clearance_mm:
        for other in ("wire", "smd", "pin", "via", "area"):
            pairs[("via", other)] = dsn.via_clearance_mm
    if dsn.pin_clearance_mm > dsn.clearance_mm:
        for other in ("wire", "smd", "pin", "area"):
            pairs[("pin", other)] = dsn.pin_clearance_mm
        pairs[("via", "pin")] = max(dsn.via_clearance_mm, dsn.pin_clearance_mm)
    return pairs


_NET_PINS = re.compile(r'\(net ("(?:[^"\\]|\\.)*"|\S+)\n(\s*)\(pins[^)]*\)\n')


def _dsn_name(net: str) -> str:
    return f'"{net}"' if re.search(r'[\s()"]', net) or any(c in net for c in "-") else net


def rewrite_dsn(text: str, dsn: DsnRules, poured: set[str] = frozenset()) -> str:
    """Add the per-item-type clearances to the structure rule; drop the plain clearance line from every net
    class rule so that all nets share the structure's clearance classes (each class already carries the same
    number, so nothing is lost); and take the pins off every poured net, so the router has nothing to route on
    it and its fanout stage leaves those pads alone (its necked escapes to pads the fill already reaches were
    21 of the 21 violations left on `open-book-c1`, 2026-09-23). The pour's own copper stays as an obstacle.
    Idempotent."""
    unit = 1000.0  # the exporter writes micrometres
    if poured:
        names = {_dsn_name(n) for n in poured} | {f'"{n}"' for n in poured} | set(poured)
        text = _NET_PINS.sub(lambda m: m.group(0) if m.group(1) not in names else f"(net {m.group(1)}\n{m.group(2)}(pins)\n", text)
    m = _STRUCTURE_RULE.search(text)
    if not m:
        raise ValueError("no structure rule in the DSN")
    body = "".join(line + "\n" for line in m.group(2).splitlines() if "(type via_" not in line and "(type pin_" not in line)
    extra = "".join(f"      (clearance {v * unit:g} (type {a}_{b}))\n" for (a, b), v in type_clearances(dsn).items())
    text = text[:m.start()] + m.group(1) + body + extra + m.group(3) + text[m.end():]
    i = text.find("(network")
    if i >= 0:
        text = text[:i] + _PLAIN_CLEARANCE.sub("", text[i:])
    return text


# --- the run -------------------------------------------------------------------------------------------------
@dataclass
class RouteResult:
    """What Freerouting did, in the terms the gate and the diagnosis need."""

    routed: list = field(default_factory=list)
    failed: dict = field(default_factory=dict)  # net -> why
    tracks: int = 0
    vias: int = 0
    seconds: float = 0.0
    passes: int = 0
    unrouted: int | None = None  # as the router's own log counts them
    violations: int | None = None  # as the router's own DRC counts them
    converged: bool = False
    version: str = JAR_VERSION
    work_dir: str = ""
    log: str = ""
    dsn_rules: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        return (f"freerouting {self.version}: {len(self.routed)} nets routed, {len(self.failed)} failed; "
                f"{self.tracks} tracks, {self.vias} vias; router counts unrouted {self.unrouted}, violations "
                f"{self.violations}; {'converged' if self.converged else 'stopped at its budget'} in {self.seconds:.0f}s")


# The jar's own settings file, written into the work directory (``--user_data_path``) so a run never reads the
# one in the user's home. It needs a version and a profile id or the jar stops with a null pointer before
# loading the design; the id is fixed and anonymous.
SETTINGS = {
    "version": JAR_VERSION,
    "profile": {"id": "00000000-0000-4000-8000-000000000000", "email": "", "allow_telemetry": False,
                "allow_contact": False},
    "gui": {"enabled": False},
    "usage_and_diagnostic_data": {"disable_analytics": True},
    "router": {},  # the defaults: measured 2026-09-23, fanout off leaves the router unable to place a via at all,
                   # and automatic_neckdown false leaves nets unrouted while still necking pad entries
    "logging": {"console": {"enabled": True, "level": "INFO"}, "file": {"enabled": False}},
}

_COMPLETED = re.compile(r"Auto-routing stage completed:.*?\((\d+) unrouted and (\d+) violations\)")
_PASS = re.compile(r"Auto-routing pass #(\d+)")


def run_jar(dsn: Path, ses: Path, work_dir: Path, passes: int = 100, timeout_s: float = 600.0,
            threads: int | None = None) -> dict:
    """Run the jar headless on ``dsn`` and write ``ses``. Returns the facts read from its log."""
    jar, java = check()
    work_dir.mkdir(parents=True, exist_ok=True)
    settings = dict(SETTINGS)
    if threads:
        settings = {**settings, "router": {**settings["router"], "max_threads": threads}}
    (work_dir / "freerouting.json").write_text(json.dumps(settings, indent=1))
    log = work_dir / "freerouting.log"
    cmd = [java, "-Djava.awt.headless=true", "-jar", str(jar), f"--user_data_path={work_dir}",
           "-de", str(dsn), "-do", str(ses), "-mp", str(passes)]
    if threads:
        cmd += ["-mt", str(threads)]
    if ses.exists():
        ses.unlink()
    t0 = time.time()
    env = {k: v for k, v in os.environ.items() if k != "JAVA_TOOL_OPTIONS"}  # the proxy settings there are noise
    with open(log, "w") as out:
        try:
            r = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, timeout=timeout_s, cwd=work_dir, env=env)
            returncode, timed_out = r.returncode, False
        except subprocess.TimeoutExpired:
            returncode, timed_out = None, True
    text = log.read_text(errors="replace")
    m = _COMPLETED.search(text)
    pass_numbers = [int(p) for p in _PASS.findall(text)]
    return {"command": cmd, "returncode": returncode, "timed_out": timed_out, "seconds": round(time.time() - t0, 1),
            "session_written": ses.is_file(), "unrouted": int(m.group(1)) if m else None,
            "violations": int(m.group(2)) if m else None, "passes": max(pass_numbers, default=0),
            "log": str(log)}


def export_dsn(board, dsn: DsnRules, path: Path, poured: set[str] = frozenset()) -> tuple[dict[str, str], dict[str, int]]:
    """Export the board (rules applied, references unique) to ``path``; returns the renames to restore and the
    class widths to restore. ``poured`` names the nets the fill connects, which the router is not to route."""
    widths = apply_rules(board, dsn)  # before any other edit: the net-class proxies go stale after one (salvage)
    renamed = unique_references(board)
    if not pcbnew.ExportSpecctraDSN(board, str(path)):
        restore_references(board, renamed)
        raise RuntimeError("pcbnew.ExportSpecctraDSN refused the board (see the module notes for why it does)")
    path.write_text(rewrite_dsn(path.read_text(), dsn, poured))
    return renamed, widths


def route_board(board, rules, work_dir: Path, nets: list[str] | None = None, passes: int = 100,
                timeout_s: float = 600.0, margin_mm: float = 0.0, threads: int | None = None,
                poured: set[str] = frozenset()) -> RouteResult:
    """Route every routable net of ``board`` in place under ``rules`` (`bench.rebuild.BoardRules`).

    ``nets`` names the nets the caller expects connected (default: every net on two or more pads); a net with
    no copper afterwards is reported failed with the reason the router's log gives. ``poured`` names the nets
    the fill connects: the router gets no pins on them.
    """
    from waffle_eda.bench import rebuild

    t0 = time.time()
    if nets is None:
        nets = sorted(rebuild.routable_nets(board))
    dsn = dsn_rules(board, rules, margin_mm=margin_mm)
    work_dir.mkdir(parents=True, exist_ok=True)
    dsn_path, ses_path = work_dir / "board.dsn", work_dir / "board.ses"
    renamed, widths = export_dsn(board, dsn, dsn_path, poured)
    try:
        facts = run_jar(dsn_path, ses_path, work_dir, passes=passes, timeout_s=timeout_s, threads=threads)
        if facts["session_written"]:
            if not pcbnew.ImportSpecctraSES(board, str(ses_path)):
                raise RuntimeError(f"pcbnew.ImportSpecctraSES refused {ses_path}")
            facts["necks"] = repair_necks(board, widths, kb.nm(dsn.width_mm), rules)
    finally:
        restore_references(board, renamed)
    (work_dir / "run.json").write_text(json.dumps({**facts, "dsn_rules": dsn.__dict__}, indent=1, default=str))
    copper = kb.net_copper(board, nets)
    result = RouteResult(tracks=len(kb.track_segments(board)) + len(kb.track_arcs(board)), vias=len(kb.vias(board)),
                         passes=facts["passes"], unrouted=facts["unrouted"], violations=facts["violations"],
                         converged=facts["session_written"] and not facts["timed_out"] and facts["unrouted"] == 0,
                         work_dir=str(work_dir), log=facts["log"], dsn_rules=dsn.summary())
    why = ("the router did not finish within its budget" if facts["timed_out"]
           else "the router wrote no session file" if not facts["session_written"]
           else f"the router left it unrouted ({facts['unrouted']} unrouted after {facts['passes']} passes)")
    for name in nets:
        if copper[name].segments == 0 and copper[name].via_count == 0:
            result.failed[name] = f"{name}: no copper laid; {why}"
        else:
            result.routed.append(name)
    result.seconds = round(time.time() - t0, 1)
    return result
