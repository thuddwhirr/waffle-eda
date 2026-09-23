"""Strip-and-score: the benchmark for the bus router and fan-out (plan.md, M1).

For a reference board whose registry entry names a bus, ``strip_bus`` removes only the bus nets' copper (tracks, arcs
and vias) and keeps everything else as obstacles: that file is the *problem*. The original board is the *answer*.
``score`` measures a candidate board against the answer:

* connectivity of every bus net, taken from a fresh ``kicad-cli pcb drc`` run (a separate process, so it does not
  suffer the in-process connectivity staleness the brief warns about);
* electrical DRC violations that touch a bus net under the reference's own constraints (``constraints.measure``,
  decisions D17): the target is zero, which the answer board meets by construction;
* per-net length inside the answer's measured spread; vias inside the packages; layers used; vias per net.

The composite score is zero when nothing is connected (the "do nothing" tool) and one for the answer's own copper.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from waffle_eda.bench import references as refs
from waffle_eda.kicad import board as kb, refill

# DRC violation types that are electrical (copper) rather than fabrication or documentation.
ELECTRICAL_TYPES = {
    "clearance", "shorting_items", "tracks_crossing", "track_width", "via_diameter", "via_hole", "hole_clearance",
    "hole_near_hole", "copper_edge_clearance", "track_dangling", "via_dangling", "annular_width", "zone_clearance",
    "copper_sliver", "diff_pair_gap_out_of_range", "diff_pair_uncoupled_length_too_long", "length_out_of_range",
    "skew_out_of_range", "too_many_vias", "unconnected_items", "connection_width", "isolated_copper",
}
NET_IN_DESCRIPTION = re.compile(r"\[([^\]]+)\]")


def bench_dir() -> Path:
    d = refs.repo_root() / "build" / "bench"
    d.mkdir(parents=True, exist_ok=True)
    return d


def strip_bus(ref: refs.Reference, out_path: Path | None = None, reuse: bool = True) -> tuple[Path, dict]:
    """Write the problem board: the reference with only the bus nets' tracks, arcs and vias removed. With ``reuse``
    an existing problem board newer than the reference file is returned as is (the refill can take minutes)."""
    if not ref.has_bus:
        raise ValueError(f"{ref.key} has no bus to strip")
    out_path = out_path or bench_dir() / f"{ref.key}-problem.kicad_pcb"
    manifest = out_path.with_name(out_path.stem + ".strip.json")  # what the strip removed, for a reused board
    if reuse and out_path.is_file() and out_path.stat().st_mtime > refs.board_path(ref).stat().st_mtime:
        if not manifest.is_file():
            nets, removed = _bus_copper(kb.load_board(refs.board_path(ref)), ref)
            manifest.write_text(json.dumps({"bus_nets": len(nets), **removed}, indent=1))
        return out_path, {**json.loads(manifest.read_text()), "reused": True}
    board = kb.load_board(refs.board_path(ref))
    nets, removed = _bus_copper(board, ref, delete=True)
    kb.save_board(board, out_path)
    fill = refill.refill_file(out_path)  # in a child process: the in-process filler hangs on some boards (D14)
    info = {"bus_nets": len(nets), **removed, "refill": fill}
    manifest.write_text(json.dumps(info, indent=1, default=str))
    return out_path, info


def _bus_copper(board, ref: refs.Reference, delete: bool = False) -> tuple[set[str], dict]:
    """The bus nets and a count of their tracks, arcs and vias; with ``delete`` those items are removed."""
    nets = set(kb.nets_matching(board, ref.bus_net_pattern))
    removed = {"tracks": 0, "arcs": 0, "vias": 0}
    for item in list(board.GetTracks()):
        if item.GetNetname() in nets:
            cls = item.GetClass()
            removed["tracks" if cls == "PCB_TRACK" else "arcs" if cls == "PCB_ARC" else "vias"] += 1
            if delete:
                board.Delete(item)  # not Remove(): the Python proxy would then own a C++ object with no destructor
    return nets, removed


def run_drc(board_path: Path, out_path: Path, severity: str = "--severity-error") -> dict:
    """Run kicad-cli DRC and return the parsed JSON report."""
    cli = shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("kicad-cli not found")
    cmd = [cli, "pcb", "drc", severity, "--format", "json", "--output", str(out_path), str(board_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode not in (0, 5) or not out_path.is_file():  # 5 = violations with --exit-code-violations
        raise RuntimeError(f"kicad-cli drc failed ({r.returncode}): {r.stderr[-500:]}")
    return json.loads(out_path.read_text())


# The rule-driven electrical constraints. KiCad's DRC stops reporting a violation type after about two hundred
# (five hundred for clearance) and which ones it keeps differs from run to run, so every count the benchmark relies
# on must stay far below that: the rules file holds every other item to nothing and applies the constraints only to
# pairs with a bus net (decisions D18).
RULE_CONSTRAINTS = ("clearance", "hole_clearance", "track_width", "via_diameter", "hole_size", "annular_width",
                    "hole_to_hole")


def rules_file(bus_nets, constraints: dict[str, float]) -> str:
    """A KiCad rules file: ``constraints`` (name -> minimum in mm) on every pair with a bus net, nothing elsewhere.
    Without bus nets only the quiet rule is written."""
    names = sorted(bus_nets)
    for n in names:
        if any(ch in n for ch in "'\"\\"):
            raise ValueError(f"net name {n!r} cannot be quoted in a rule condition")
    quiet = "".join(f"  (constraint {c} (min 0mm))\n" for c in RULE_CONSTRAINTS)
    text = f"(version 1)\n(rule quiet\n{quiet})\n"
    if names:
        condition = " || ".join(f"A.NetName == '{n}' || B.NetName == '{n}'" for n in names)
        scoped = "".join(f"  (constraint {c} (min {v:.4f}mm))\n" for c, v in constraints.items())
        text += f"(rule bus\n  (condition \"{condition}\")\n{scoped})\n"
    return text


def _copy_board(src: Path, work_dir: Path, name: str = "board") -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    for ext in (".kicad_pcb", ".kicad_pro"):
        f = src.with_suffix(ext)
        if f.is_file():
            shutil.copy(f, work_dir / (name + ext))
    return work_dir / (name + ".kicad_pcb")


def drc_with_rules(board_path: Path, rules_text: str, work_dir: Path, bus_nets: set[str], tag: str = "drc") -> dict:
    """Run KiCad's DRC on a copy of ``board_path`` under ``rules_text`` (a ``.kicad_dru`` next to the copy
    overrides the board's own values); return the electrical facts for the bus."""
    copy = _copy_board(board_path, work_dir)
    (work_dir / "board.kicad_dru").write_text(rules_text)
    report = run_drc(copy, work_dir / f"{tag}.json")
    return drc_facts(report, bus_nets)


def _item_nets(item: dict) -> set[str]:
    return set(NET_IN_DESCRIPTION.findall(item.get("description", "")))


def drc_facts(report: dict, bus_nets: set[str]) -> dict:
    """Counts from a DRC report: electrical violations overall and those touching a bus net; unconnected bus nets."""
    electrical = [v for v in report.get("violations", []) if v.get("type") in ELECTRICAL_TYPES]
    touching = [v for v in electrical if any(_item_nets(i) & bus_nets for i in v.get("items", []))]
    unconnected = report.get("unconnected_items", [])
    unconnected_bus = set()
    for u in unconnected:
        for i in u.get("items", []):
            unconnected_bus |= _item_nets(i) & bus_nets
    return {
        "electrical_total": len(electrical),
        "electrical_bus": len(touching),
        "electrical_bus_by_type": _count_types(touching),
        "unconnected_items": len(unconnected),
        "unconnected_bus_nets": sorted(unconnected_bus),
    }


def _count_types(violations: list[dict]) -> dict:
    out: dict = {}
    for v in violations:
        out[v["type"]] = out.get(v["type"], 0) + 1
    return dict(sorted(out.items()))


@dataclass
class Score:
    reference: str
    candidate: str
    bus_nets: int
    connected: int
    unconnected_items: int
    drc_bus_errors: int
    drc_bus_errors_answer: int
    drc_bus_by_type: dict
    length_within_spread: int  # the earlier proxy (every net inside the answer's overall length window), kept for information
    length_spread_mm: tuple[float, float]
    vias_total: int
    vias_in_packages: int
    vias_share_answer: float
    max_vias_per_net: int
    max_vias_per_net_answer: int
    layers: list[str]
    layers_answer: list[str]
    seconds: float
    passed: bool = False
    score: float = 0.0
    nets: dict = field(default_factory=dict)
    matching_passed: bool = False  # D27: matched as the reference matches, per group
    matching_lines: list = field(default_factory=list)
    matching_failures: list = field(default_factory=list)

    def summary(self) -> str:
        share = f"{100 * self.vias_in_packages / self.vias_total:.0f}%" if self.vias_total else "n/a"
        return (
            f"{self.reference:<12} score={self.score:.3f} {'PASS' if self.passed else 'fail'} | "
            f"connected {self.connected}/{self.bus_nets}, unconnected items {self.unconnected_items} | "
            f"bus DRC errors {self.drc_bus_errors} (answer {self.drc_bus_errors_answer}) | "
            f"matching {'ok' if self.matching_passed else 'FAIL ' + '; '.join(self.matching_failures)} | "
            f"vias {self.vias_total}, in packages {share} (answer {100 * self.vias_share_answer:.0f}%), "
            f"max/net {self.max_vias_per_net} (answer {self.max_vias_per_net_answer}) | "
            f"layers {self.layers} | {self.seconds:.1f}s"
        )


def score(ref: refs.Reference, candidate_path: Path, work_dir: Path | None = None) -> Score:
    from waffle_eda.bench import constraints  # measured with this module's DRC, hence imported here

    t0 = time.time()
    answer = refs.measure(ref)
    bus_nets = set(answer["bus"]["nets"])
    rules = constraints.measure(ref).rules_text()
    work_dir = work_dir or bench_dir() / "drc" / ref.key
    answer_facts = drc_with_rules(refs.board_path(ref), rules, work_dir / "answer", bus_nets, tag="answer")

    cand_board = kb.load_board(candidate_path)
    cand_nets = kb.nets_matching(cand_board, ref.bus_net_pattern)
    if set(cand_nets) != bus_nets:
        raise ValueError(f"candidate bus nets differ from the answer's: {set(cand_nets) ^ bus_nets}")
    copper = kb.net_copper(cand_board, cand_nets)
    packages = {r: kb.package_info(kb.footprint(cand_board, r)) for r in ref.bus_parts}

    cand_facts = drc_with_rules(candidate_path, rules, work_dir / candidate_path.stem, bus_nets, tag="candidate")
    unconnected = set(cand_facts["unconnected_bus_nets"])

    lo, hi = answer["bus"]["length_mm"]["min"], answer["bus"]["length_mm"]["max"]
    nets = {}
    within = vias_total = vias_inside = 0
    layers: set[str] = set()
    max_vias = 0
    for name in cand_nets:
        nc = copper[name]
        inside = sum(1 for (x, y) in nc.via_positions_mm if any(p.in_footprint_mm(x, y) for p in packages.values()))
        ok_len = nc.segments > 0 and (lo - 1e-3) <= nc.length_mm <= (hi + 1e-3)  # answer lengths are rounded to 1 um
        within += ok_len
        vias_total += nc.via_count
        vias_inside += inside
        max_vias = max(max_vias, nc.via_count)
        layers |= set(nc.layers)
        nets[name] = {
            "connected": name not in unconnected and nc.segments > 0,
            "length_mm": round(nc.length_mm, 3),
            "answer_length_mm": answer["bus"]["nets"][name]["length_mm"],
            "vias": nc.via_count,
            "vias_in_package": inside,
            "layers": list(nc.layers),
        }
    connected = sum(1 for v in nets.values() if v["connected"])
    n = len(cand_nets)
    ans_bus = answer["bus"]
    ans_share = ans_bus["vias_in_packages"] / ans_bus["vias_total"] if ans_bus["vias_total"] else 1.0
    ans_max_vias = max(int(k) for k in ans_bus["vias_per_net_hist"]) if ans_bus["vias_per_net_hist"] else 0
    ans_layers = sorted(ans_bus["layers_used"])

    drc_ok = cand_facts["electrical_bus"] == 0  # the answer's count is zero by construction (D17)
    length_frac = within / n if n else 0.0
    vias_ok = (vias_inside / vias_total >= ans_share - 0.05) if vias_total else True
    layers_ok = layers <= set(ans_layers)
    vias_count_ok = max_vias <= ans_max_vias
    conn_frac = connected / n if n else 0.0
    # D27: lengths matched as the reference matches them, per group
    from waffle_eda.bench import bus_design
    reference_design = bus_design.measure_bus_design(ref.key)
    candidate_design = bus_design.measure_board(cand_board, ref)
    verdict = bus_design.judge(candidate_design, reference_design)
    composite = conn_frac * (0.6 + 0.15 * drc_ok + 0.15 * verdict["passed"] + 0.05 * (vias_ok and vias_count_ok) + 0.05 * layers_ok)
    passed = connected == n and cand_facts["unconnected_items"] == 0 and drc_ok and verdict["passed"]

    return Score(
        reference=ref.key,
        candidate=str(candidate_path),
        bus_nets=n,
        connected=connected,
        unconnected_items=cand_facts["unconnected_items"],
        drc_bus_errors=cand_facts["electrical_bus"],
        drc_bus_errors_answer=answer_facts["electrical_bus"],
        drc_bus_by_type=cand_facts["electrical_bus_by_type"],
        length_within_spread=within,
        length_spread_mm=(lo, hi),
        matching_passed=verdict["passed"],
        matching_lines=verdict["lines"],
        matching_failures=verdict["failures"],
        vias_total=vias_total,
        vias_in_packages=vias_inside,
        vias_share_answer=round(ans_share, 3),
        max_vias_per_net=max_vias,
        max_vias_per_net_answer=ans_max_vias,
        layers=sorted(layers),
        layers_answer=ans_layers,
        seconds=round(time.time() - t0, 1),
        passed=passed,
        score=round(composite, 3),
        nets=nets,
    )


def write_score(s: Score, out_path: Path | None = None) -> Path:
    out_path = out_path or bench_dir() / f"{s.reference}-{Path(s.candidate).stem}-score.json"
    out_path.write_text(json.dumps(asdict(s), indent=1))
    return out_path
