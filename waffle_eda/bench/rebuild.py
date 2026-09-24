"""The M4 benchmark: strip **every** net's copper from a reference and score a candidate that re-routes all of it.

M1's harness (`harness.py`) strips one bus and keeps the rest of the board as obstacles, which is the right
problem for a bus router and the wrong one for M4. M4's criterion in the plan is a full re-route of a class A or
B reference from placement, DRC clean, with planes and power rails on continuous copper. So the problem board
here is what stage 5 of the pipeline actually receives (`docs/definition.md`): a specification, a netlist and
footprints. Placement, the board outline and the pads stay; every track, arc, via and zone goes.

That is a deliberate reading and it is the strict one. Keeping the reference's zones would hand the tool most of
the ground connectivity on a two-layer board, where the pour *is* how ground is routed, and M4 is the milestone
that has to produce planes with their feeds and stitching. Stage 5's stated inputs settle it: no copper.

**What a candidate is scored on.** Every net connected and zero electrical violations under rules measured off
the board itself, which is the benchmark's criterion everywhere else in this project (D17, D18) and the standing
recommendation for the open question about it. The rules here are not scoped to a net list: they apply to the
whole board, because on this benchmark the whole board is ours.

**Two sanity checks**, the same pair M1 used and the reason to trust the number: the stripped board scores zero,
and the original copper scores full marks. Both are asserted in `tests/test_rebuild.py`.

**Layer names are not `F.Cu` and `B.Cu` on every board.** `tinkerforge-temperature`, the first board in the M4
ladder, calls them `Vorderseite` and `Rückseite`. Nothing here keys on a layer name.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

from waffle_eda.bench import harness, references as refs
from waffle_eda.kicad import board as kb

VERSION = 2  # bump when the measurement changes; cached files of another version are re-measured (2: D76)


def problem_path(ref: refs.Reference) -> Path:
    return harness.bench_dir() / f"{ref.key}-bare.kicad_pcb"


def answer_path(ref: refs.Reference) -> Path:
    return harness.bench_dir() / f"{ref.key}-answer.kicad_pcb"


ORPHAN = re.compile(r"^(Pad (\S+) \[<no net>\] of (\S+)|(?:PTH|NPTH) pad \[<no net>\] of (\S+)|Polygon \[<no net>\] of (\S+) on \S+)")


ORPHAN_PROBE_MM = 0.001  # the probe's clearance: KiCad reports no short at all under a clearance rule of zero
OVERLAP = re.compile(r"actual (< 0|0\.0000 mm)")


def _orphan_shorts(report: dict) -> dict[str, set[str]]:
    """From a DRC report, the no-net copper items the board's own copper overlaps, each with the nets
    involved: item description -> nets (as the report writes them). An overlap is a `shorting_items` finding,
    or a clearance or hole-clearance finding at an actual distance of zero or less (a via through a no-net pad
    reports "actual < 0" under the hole rule, and no short)."""
    out: dict[str, set[str]] = {}
    for v in report.get("violations", []):
        kind = v.get("type")
        if kind not in ("shorting_items", "clearance", "hole_clearance"):
            continue
        if kind != "shorting_items" and not OVERLAP.search(v.get("description", "")):
            continue
        items = v.get("items", [])
        orphans = [i["description"] for i in items if ORPHAN.match(i.get("description", ""))]
        nets = {n for i in items for n in harness.NET_IN_DESCRIPTION.findall(i.get("description", "")) if n != "<no net>"}
        if not orphans or not nets:
            continue
        for o in orphans:
            out.setdefault(o, set()).update(nets)
    return out


def adopt_orphans(board, shorts: dict[str, set[str]]) -> tuple[dict[str, str], dict[str, str]]:
    """Give every no-net pad the board's own copper shorts to exactly one net that net (D76): on `upduino-v3.01`
    the QFN's exposed pad carries no net in the file while the GND vias stitch it, and KiCad reports 24 shorts
    and 36 clearances on the original for it. A no-net graphic polygon (sensor-watch's buzzer contact) cannot
    take a net; its pairing is returned to be forgiven in scoring. Returns (pads adopted, graphics paired)."""
    by_name = {kb.unescape_net(n): n for n in kb.net_names(board)}
    pads: dict[str, str] = {}
    graphics: dict[str, str] = {}
    for desc, nets in shorts.items():
        if len(nets) != 1:
            continue
        net = next(iter(nets))
        m = ORPHAN.match(desc)
        if desc.startswith("Polygon"):
            graphics[desc] = net
            continue
        ref = m.group(3) or m.group(4)
        number = m.group(2)  # None for a "PTH pad [<no net>] of X" (an unnumbered pad)
        fp = board.FindFootprintByReference(ref)
        if fp is None or net not in by_name:
            continue
        netinfo = board.FindNet(by_name[net])
        for pad in fp.Pads():
            if pad.GetNetname() == "" and (number is None or pad.GetNumber() == number):
                pad.SetNet(netinfo)
                pads[f"{ref}.{pad.GetNumber() or 'PTH'}"] = net
    return pads, graphics


def answer_board(ref: refs.Reference, reuse: bool = True) -> tuple[Path, dict]:
    """The reference as the benchmark reads it: its zones refilled by KiCad 9 (a legacy fill fails the DRC
    until it is, D58) and its orphan pads adopted (D76), saved beside the problem board with the reference's
    project file. Every measurement and score reads this file, never the checkout's."""
    out = answer_path(ref)
    manifest = out.with_name(out.stem + ".json")
    src = refs.board_path(ref)
    if reuse and out.is_file() and manifest.is_file() and out.stat().st_mtime > src.stat().st_mtime:
        return out, json.loads(manifest.read_text())
    board = kb.load_board(src)
    kb.refill_zones(board)
    kb.save_board(board, out)
    pro = src.with_suffix(".kicad_pro")
    if pro.is_file():
        shutil.copy(pro, out.with_suffix(".kicad_pro"))
    work = refs.repo_root() / "build" / "boardrules" / ref.key / "orphans"
    report = _drc_report(out, rules_text({"clearance": ORPHAN_PROBE_MM, "hole_clearance": ORPHAN_PROBE_MM}), work,
                         tag="orphans", runs=1)
    shorts = _orphan_shorts(report)
    pads, graphics = adopt_orphans(board, shorts)
    if pads:
        kb.save_board(board, out)
    info = {"reference": ref.key, "adopted_pads": pads, "paired_graphics": graphics,
            "unresolved": {d: sorted(n) for d, n in shorts.items() if len(n) != 1}}
    manifest.write_text(json.dumps(info, indent=1))
    return out, info


def rules_path(ref: refs.Reference) -> Path:
    return refs.repo_root() / "build" / f"boardrules-{ref.key}.json"


# --- the problem board ----------------------------------------------------------------------------------------
def pour_facts(board, zone) -> dict:
    """What stage 4 would specify about a copper zone, and what the router is handed instead (D17): the net, the
    layer, the zone's own clearance and minimum width, how pads connect, and its outline in mm."""
    outline = zone.Outline()
    pts = [(kb.mm(outline.CVertex(i).x), kb.mm(outline.CVertex(i).y)) for i in range(outline.VertexCount(0))] \
        if outline.OutlineCount() else []
    local = zone.GetLocalClearance()
    clearance = local.value() if hasattr(local, "value") else (local or 0)
    return {"net": zone.GetNetname(), "layer": board.GetLayerName(zone.GetFirstLayer()),
            "clearance_mm": round(kb.mm(clearance), 4), "min_thickness_mm": round(kb.mm(zone.GetMinThickness()), 4),
            "pad_connection": int(zone.GetPadConnection()), "outline_mm": [(round(x, 4), round(y, 4)) for x, y in pts]}


def _strip(board, delete: bool = False) -> dict:
    """Count (and with ``delete`` remove) every piece of routed copper: tracks, arcs, vias and zones. The zones
    stripped are recorded as the pours the router is to lay (`pours`)."""
    removed = {"tracks": 0, "arcs": 0, "vias": 0, "zones": 0, "teardrops": 0, "pours": []}
    for item in list(board.GetTracks()):
        cls = item.GetClass()
        removed["tracks" if cls == "PCB_TRACK" else "arcs" if cls == "PCB_ARC" else "vias"] += 1
        if delete:
            board.Delete(item)  # not Remove(): the proxy would own a C++ object with no destructor
    for zone in list(board.Zones()):
        if zone.GetIsRuleArea():
            continue  # a keepout is part of the specification handed to the router, not copper it laid
        if zone.IsTeardropArea():  # a fillet on a track of the reference's own routing: copper, not a pour
            removed["teardrops"] += 1  # (crkbd carries 921 of them, and 4 pours)
            if delete:
                board.Delete(zone)
            continue
        removed["zones"] += 1
        for layer in zone.GetLayerSet().CuStack():
            facts = pour_facts(board, zone)
            facts["layer"] = board.GetLayerName(layer)
            removed["pours"].append(facts)
        if delete:
            board.Delete(zone)
    return removed


def strip_all(ref: refs.Reference, out_path: Path | None = None, reuse: bool = True) -> tuple[Path, dict]:
    """Write the problem board: the reference with placement, outline and pads, and no routed copper at all."""
    out_path = out_path or problem_path(ref)
    manifest = out_path.with_name(out_path.stem + ".strip.json")
    if reuse and out_path.is_file() and manifest.is_file() \
            and out_path.stat().st_mtime > refs.board_path(ref).stat().st_mtime:
        info = json.loads(manifest.read_text())
        if "adopted_pads" in info:  # a manifest from before the orphans were adopted (D76) is re-made
            return out_path, {**info, "reused": True}
    answer, adopted = answer_board(ref)
    board = kb.load_board(answer)
    removed = _strip(board, delete=True)
    info = {"reference": ref.key, "nets": len(all_nets(board)), "routable_nets": len(routable_nets(board)),
            **removed, "adopted_pads": adopted["adopted_pads"], "paired_graphics": adopted["paired_graphics"]}
    kb.save_board(board, out_path)
    manifest.write_text(json.dumps(info, indent=1, default=str))
    return out_path, info


def all_nets(board) -> set[str]:
    """Every named net on the board. The unnamed net (pads with no connection) is not one to route."""
    return {n for n in kb.net_names(board) if n}


def routable_nets(board) -> set[str]:
    """The nets a router has to connect: those reaching two or more pads.

    A net on a single pad has nothing to connect and KiCad never reports it unconnected, so counting it would
    score the do-nothing tool above zero. `tinkerforge-temperature` has five of them out of eleven nets, which
    is the difference between a benchmark that starts at 0.00 and one that starts at 0.45.
    """
    pads: dict[str, int] = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            name = pad.GetNetname()
            if name:
                pads[name] = pads.get(name, 0) + 1
    return {n for n, k in pads.items() if k >= 2}


# --- the rules the board itself demonstrates ------------------------------------------------------------------
# Every constraint the quiet rule zeroes. `harness.RULE_CONSTRAINTS` is the bus benchmark's list and leaves
# `edge_clearance` out, which it can afford because it only counts violations touching a bus net. Here the whole
# board is ours, so the board's own project setting would otherwise fail a candidate under a value nobody
# measured: `tinkerforge-temperature` asks 0.5 mm of edge clearance in its project file and has copper on the
# edge, so the *original* fails that rule twice.
QUIET_CONSTRAINTS = tuple(harness.RULE_CONSTRAINTS) + ("edge_clearance",)


def rules_text(values: dict[str, float]) -> str:
    """A KiCad rules file applying ``values`` to the whole board. The quiet rule first zeroes every constraint so
    the board's own netclass values cannot fail a candidate under a rule nobody measured; the unconditional rule
    after it is the one that applies, which is the same ordering `harness.rules_file` relies on."""
    quiet = "".join(f"  (constraint {c} (min 0mm))\n" for c in QUIET_CONSTRAINTS)
    scoped = "".join(f"  (constraint {c} (min {v:.4f}mm))\n" for c, v in values.items())
    return f"(version 1)\n(rule quiet\n{quiet})\n(rule board\n{scoped})\n"


@dataclass(frozen=True)
class BoardRules:
    """What the reference's own copper demonstrates, for the whole board rather than one bus."""

    reference: str
    board_mtime: float
    clearance_mm: float
    hole_to_copper_mm: float
    edge_clearance_mm: float
    min_track_mm: float
    min_via_mm: float
    min_drill_mm: float
    min_annular_mm: float
    layers: tuple[str, ...]
    nets: int
    forgiven_shorts: tuple[tuple[str, str], ...] = ()  # (no-net graphic, the net the reference shorts it to), D76

    @property
    def forgiven(self) -> dict[str, str]:
        return dict(self.forgiven_shorts)

    def values(self) -> dict[str, float]:
        return {"clearance": self.clearance_mm, "hole_clearance": self.hole_to_copper_mm,
                "edge_clearance": self.edge_clearance_mm, "track_width": self.min_track_mm,
                "via_diameter": self.min_via_mm, "hole_size": self.min_drill_mm,
                "annular_width": self.min_annular_mm}

    def rules_text(self) -> str:
        return rules_text(self.values())

    def summary(self) -> str:
        return (f"{self.reference}: clearance {self.clearance_mm} mm, hole-to-copper {self.hole_to_copper_mm}, "
                f"edge {self.edge_clearance_mm}, "
                f"track {self.min_track_mm}, via {self.min_via_mm}/{self.min_drill_mm} "
                f"(ring {self.min_annular_mm}), layers {list(self.layers)}, {self.nets} nets")


def _floor4(x: float) -> float:
    """Round down to 0.1 um so a rule never exceeds the copper it was measured from."""
    return math.floor(x * 10000 + 1e-6) / 10000


def _largest_met(board_path: Path, work_dir: Path, constraint: str, vtype: str,
                 lo: float, hi: float, steps: int = 7, forgiven: dict[str, str] | None = None) -> float:
    """Largest value of ``constraint`` under which the whole board has no violation of ``vtype``."""
    best = lo
    for _ in range(steps):
        mid = (lo + hi) / 2
        facts = _drc(board_path, rules_text({constraint: mid}), work_dir, tag="probe", runs=1, forgiven=forgiven)
        if facts["by_type"].get(vtype, 0) == 0:
            best, lo = mid, mid
        else:
            hi = mid
    # a hair below the largest met, so rounding never fails the original; never negative
    return max(0.0, round(best - 0.0005, 4))


# KiCad names each item of a violation by its kind. Tracks, arcs, vias and zones are copper the router laid and
# are its responsibility; pads, graphics and footprints are the placement, identical in the problem board and the
# answer, so a violation between two of them is not the router's and cannot be fixed by routing differently.
ROUTED_KINDS = ("Track", "Arc", "Via", "Zone")


def _is_routed(item: dict) -> bool:
    """Whether a violation item is copper the router laid. ``Arc`` and ``Segment`` are also what KiCad calls the
    graphics of the board outline, so an item on ``Edge.Cuts`` is never the router's however it is named."""
    description = item.get("description", "")
    return description.startswith(ROUTED_KINDS) and "Edge.Cuts" not in description


def _forgiven(v: dict, forgiven: dict[str, str] | None) -> bool:
    """A short between a no-net graphic and the one net the reference itself shorts it to (D76)."""
    if not forgiven or v.get("type") != "shorting_items":
        return False
    items = [i.get("description", "") for i in v.get("items", [])]
    for desc, net in forgiven.items():
        if desc in items and any(f"[{net}]" in i for i in items if i != desc):
            return True
    return False


def board_facts(report: dict, forgiven: dict[str, str] | None = None) -> dict:
    """Whole-board DRC facts. Deliberately not ``harness.drc_facts``, which counts only the violations touching a
    named net: copper with no net is still ours here, and an edge-clearance violation names no net at all, so
    that filter would hide exactly the violations this benchmark has to see.

    A violation counts against the router when at least one of its items is copper the router laid. Violations
    wholly between fixed items are reported separately and never graded: on `tinkerforge-temperature` the pad
    `EP` of the connector `P1` sits on the board edge, so grading those would measure the board's edge clearance
    as zero and let a candidate run track along the rim. The placement is given; only the copper is ours.
    """
    electrical = [v for v in report.get("violations", []) if v.get("type") in harness.ELECTRICAL_TYPES
                  and not _forgiven(v, forgiven)]
    ours = [v for v in electrical if any(_is_routed(i) for i in v.get("items", []))]
    by_type: dict = {}
    for v in ours:
        by_type[v["type"]] = by_type.get(v["type"], 0) + 1
    fixed_by_type: dict = {}
    for v in electrical:
        if v not in ours:
            fixed_by_type[v["type"]] = fixed_by_type.get(v["type"], 0) + 1
    unconnected = report.get("unconnected_items", [])
    nets: set[str] = set()  # as the report writes them: unescaped (kb.unescape_net)
    for u in unconnected:
        for item in u.get("items", []):
            nets |= set(harness.NET_IN_DESCRIPTION.findall(item.get("description", "")))
    return {"electrical": len(ours), "by_type": dict(sorted(by_type.items())),
            "electrical_fixed": len(electrical) - len(ours), "fixed_by_type": dict(sorted(fixed_by_type.items())),
            "unconnected_items": len(unconnected), "unconnected_nets": sorted(nets)}


DRC_RUNS = 2  # kicad-cli's report dropped a real violation in 1 run of 8 on one board (D63): the union of two


def _violation_id(v: dict) -> tuple:
    return (v.get("type"), tuple(sorted((i.get("description", ""), i.get("pos", {}).get("x"), i.get("pos", {}).get("y"))
                                        for i in v.get("items", []))))


SETUP_MINIMUMS = ("m_MinClearance", "m_HoleClearance", "m_CopperEdgeClearance", "m_TrackMinWidth", "m_ViasMinSize",
                  "m_MinThroughDrill", "m_ViasMinAnnularWidth", "m_HoleToHoleMin", "m_MinConn")


def _quiet_copy(board_path: Path, work_dir: Path) -> Path:
    """A copy of the board for the DRC with every board-setup minimum at zero: KiCad enforces those under any
    rules file ("board minimum hole clearance 0.2500 mm" on `tinkerforge-master-v3.2`, whose own copper sits at
    0.19), so the quiet rule alone did not silence them and the measurement could not go below them (D76)."""
    copy = harness._copy_board(board_path, work_dir)
    board = kb.load_board(copy)
    ds = board.GetDesignSettings()
    for name in SETUP_MINIMUMS:
        if hasattr(ds, name):
            setattr(ds, name, 0)
    kb.save_board(board, copy)
    return copy


def _drc_report(board_path: Path, rules: str, work_dir: Path, tag: str, runs: int = DRC_RUNS) -> dict:
    """KiCad's DRC on a quiet copy of ``board_path`` under ``rules``: the raw report, the union of ``runs``."""
    copy = _quiet_copy(board_path, work_dir)
    (work_dir / "board.kicad_dru").write_text(rules)
    merged: dict | None = None
    seen: set[tuple] = set()
    for k in range(runs):
        report = harness.run_drc(copy, work_dir / f"{tag}{'' if k == 0 else k}.json")
        if merged is None:
            merged = report
            seen = {_violation_id(v) for v in report.get("violations", [])}
            continue
        for v in report.get("violations", []):
            if _violation_id(v) not in seen:
                seen.add(_violation_id(v))
                merged.setdefault("violations", []).append(v)
        for u in report.get("unconnected_items", []):
            if u not in merged.get("unconnected_items", []):
                merged.setdefault("unconnected_items", []).append(u)
    return merged or {}


def _drc(board_path: Path, rules: str, work_dir: Path, tag: str, runs: int = DRC_RUNS,
         forgiven: dict[str, str] | None = None) -> dict:
    """Run KiCad's DRC on a copy of ``board_path`` under ``rules`` and return the whole-board facts, as the
    union of ``runs`` reports: a violation any run reports counts."""
    return board_facts(_drc_report(board_path, rules, work_dir, tag, runs), forgiven)


def drc_under_rules(board_path: Path, values: dict[str, float], work_dir: Path, tag: str = "drc") -> dict:
    """Whole-board DRC facts (`board_facts`) for any board under a rule set: what the class A gate does to a
    re-routed reference, for a design's own board (stage 5 of the pipeline)."""
    return _drc(board_path, rules_text(values), work_dir, tag)


def measure_rules(ref: refs.Reference, force: bool = False) -> BoardRules:
    """Measure (or load from cache) the rules the reference's own copper meets across the whole board."""
    path = rules_path(ref)
    board_file = refs.board_path(ref)
    mtime = board_file.stat().st_mtime
    if path.is_file() and not force:
        data = json.loads(path.read_text())
        if data.get("board_mtime") == mtime and data.pop("version", None) == VERSION:
            data["layers"] = tuple(data["layers"])
            data["forgiven_shorts"] = tuple(tuple(x) for x in data.get("forgiven_shorts", ()))
            return BoardRules(**data)
    board_file, adopted = answer_board(ref)
    board = kb.load_board(board_file)
    nets = all_nets(board)
    work = refs.repo_root() / "build" / "boardrules" / ref.key
    forgiven = adopted["paired_graphics"]
    clearance = _largest_met(board_file, work, "clearance", "clearance", 0.0, 0.40, forgiven=forgiven)
    hole = _largest_met(board_file, work, "hole_clearance", "hole_clearance", 0.0, 0.50, forgiven=forgiven)
    edge = _largest_met(board_file, work, "edge_clearance", "copper_edge_clearance", 0.0, 0.60, forgiven=forgiven)
    widths = [kb.mm(t.GetWidth()) for t in kb.track_segments(board) + kb.track_arcs(board)]
    via_sizes = [(kb.via_diameter_mm(v), kb.via_drill_mm(v)) for v in kb.vias(board)]
    layers = [name for _id, name in kb.copper_layers(board)]
    r = BoardRules(
        reference=ref.key, board_mtime=mtime, clearance_mm=clearance, hole_to_copper_mm=hole,
        edge_clearance_mm=edge,
        min_track_mm=_floor4(min(widths)) if widths else 0.1,
        min_via_mm=_floor4(min(d for d, _ in via_sizes)) if via_sizes else 0.45,
        min_drill_mm=_floor4(min(k for _, k in via_sizes)) if via_sizes else 0.2,
        min_annular_mm=_floor4(min((d - k) / 2 for d, k in via_sizes)) if via_sizes else 0.125,
        layers=tuple(layers), nets=len(nets), forgiven_shorts=tuple(sorted(forgiven.items())))
    # The original meets its own rules by construction. If it does not, the measurement is wrong, and a rules
    # file the original fails would judge the router against something nobody demonstrated (D17's rule).
    facts = _drc(board_file, r.rules_text(), work / "original", tag="original", forgiven=forgiven)
    if facts["electrical"]:
        raise AssertionError(f"{ref.key}: the original fails its own measured rules: {facts['by_type']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**asdict(r), "layers": list(r.layers), "forgiven_shorts": [list(x) for x in r.forgiven_shorts],
                                "version": VERSION}, indent=1))
    return r


# --- scoring --------------------------------------------------------------------------------------------------
@dataclass
class RebuildScore:
    reference: str
    candidate: str
    nets: int
    connected: int
    unconnected_items: int
    electrical: int
    electrical_by_type: dict
    tracks: int
    vias: int
    tracks_answer: int
    vias_answer: int
    layers: list
    layers_answer: list
    seconds: float
    passed: bool = False
    score: float = 0.0
    per_net: dict = field(default_factory=dict)

    def summary(self) -> str:
        return (f"{self.reference:<26} score={self.score:.3f} {'PASS' if self.passed else 'fail'} | "
                f"connected {self.connected}/{self.nets}, unconnected items {self.unconnected_items} | "
                f"electrical {self.electrical} {self.electrical_by_type or ''} | "
                f"tracks {self.tracks} (answer {self.tracks_answer}), vias {self.vias} "
                f"(answer {self.vias_answer}) | {self.seconds:.1f}s")


def score(ref: refs.Reference, candidate_path: Path, work_dir: Path | None = None) -> RebuildScore:
    """Score a candidate re-route of the whole board against the reference's own demonstrated rules."""
    t0 = time.time()
    rules = measure_rules(ref)
    answer, _adopted = answer_board(ref)
    answer_board_ = kb.load_board(answer)
    answer_tracks = len(kb.track_segments(answer_board_)) + len(kb.track_arcs(answer_board_))
    answer_vias = len(kb.vias(answer_board_))
    answer_layers = sorted({name for _id, name in kb.copper_layers(answer_board_)})

    cand = kb.load_board(candidate_path)
    nets = routable_nets(cand)  # the nets a router has to connect; a one-pad net is not one of them
    missing = routable_nets(answer_board_) - nets
    if missing:
        raise ValueError(f"candidate is missing nets the answer has: {sorted(missing)}")
    work_dir = work_dir or harness.bench_dir() / "rebuild" / ref.key
    facts = _drc(candidate_path, rules.rules_text(), work_dir / candidate_path.stem, tag="candidate",
                 forgiven=rules.forgiven)

    copper = kb.net_copper(cand, sorted(nets))
    # the report names nets unescaped and the API escaped, so compare unescaped or a net with a slash in its
    # name is never found in the unconnected list and is scored connected with no copper on the board at all
    unconnected = set(facts["unconnected_nets"])
    per_net = {}
    for name in sorted(nets):
        nc = copper[name]
        per_net[name] = {"connected": kb.unescape_net(name) not in unconnected, "segments": nc.segments,
                         "length_mm": round(nc.length_mm, 3), "vias": nc.via_count,
                         "layers": sorted(nc.layers)}
    connected = sum(1 for v in per_net.values() if v["connected"])
    n = len(nets)
    conn_frac = connected / n if n else 0.0
    drc_ok = facts["electrical"] == 0
    passed = connected == n and facts["unconnected_items"] == 0 and drc_ok
    # the "do nothing" tool connects nothing and so scores zero; the answer connects everything with no
    # violation and so scores one. Nothing between them is a pass.
    composite = conn_frac * (0.7 + 0.3 * drc_ok)

    return RebuildScore(
        reference=ref.key, candidate=str(candidate_path), nets=n, connected=connected,
        unconnected_items=facts["unconnected_items"], electrical=facts["electrical"],
        electrical_by_type=facts["by_type"],
        tracks=len(kb.track_segments(cand)) + len(kb.track_arcs(cand)), vias=len(kb.vias(cand)),
        tracks_answer=answer_tracks, vias_answer=answer_vias,
        layers=sorted({name for _id, name in kb.copper_layers(cand)}), layers_answer=answer_layers,
        seconds=round(time.time() - t0, 1), passed=passed, score=round(composite, 3), per_net=per_net)


def write_score(s: RebuildScore, out_path: Path | None = None) -> Path:
    out_path = out_path or harness.bench_dir() / f"{s.reference}-rebuild-score.json"
    out_path.write_text(json.dumps(asdict(s), indent=1))
    return out_path
