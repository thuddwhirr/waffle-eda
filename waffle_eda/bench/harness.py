"""Strip-and-score: the benchmark for the bus router and fan-out (plan.md, M1).

For a reference board whose registry entry names a bus, ``strip_bus`` removes only the bus nets' copper (tracks, arcs
and vias) and keeps everything else as obstacles: that file is the *problem*. The original board is the *answer*.
``score`` measures a candidate board against the answer:

* connectivity of every bus net, taken from a fresh ``kicad-cli pcb drc`` run (a separate process, so it does not
  suffer the in-process connectivity staleness the brief warns about);
* electrical DRC violations that touch a bus net, compared with the answer board's own count under the same rules
  (the references are not violation-free under KiCad 9's checks, so the comparison is relative);
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
from waffle_eda.kicad import board as kb

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


def strip_bus(ref: refs.Reference, out_path: Path | None = None) -> tuple[Path, dict]:
    """Write the problem board: the reference with only the bus nets' tracks, arcs and vias removed."""
    if not ref.has_bus:
        raise ValueError(f"{ref.key} has no bus to strip")
    board = kb.load_board(refs.board_path(ref))
    nets = set(kb.nets_matching(board, ref.bus_net_pattern))
    removed = {"tracks": 0, "arcs": 0, "vias": 0}
    for item in list(board.GetTracks()):
        if item.GetNetname() in nets:
            cls = item.GetClass()
            removed["tracks" if cls == "PCB_TRACK" else "arcs" if cls == "PCB_ARC" else "vias"] += 1
            board.Delete(item)  # not Remove(): the Python proxy would then own a C++ object with no destructor
    kb.refill_zones(board)
    out_path = out_path or bench_dir() / f"{ref.key}-problem.kicad_pcb"
    kb.save_board(board, out_path)
    return out_path, {"bus_nets": len(nets), **removed}


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


def answer_drc(ref: refs.Reference) -> dict:
    """DRC report of the answer board, cached in build/bench."""
    out = bench_dir() / f"{ref.key}-answer-drc.json"
    if out.is_file():
        return json.loads(out.read_text())
    return run_drc(refs.board_path(ref), out)


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
    length_within_spread: int
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

    def summary(self) -> str:
        share = f"{100 * self.vias_in_packages / self.vias_total:.0f}%" if self.vias_total else "n/a"
        return (
            f"{self.reference:<12} score={self.score:.3f} {'PASS' if self.passed else 'fail'} | "
            f"connected {self.connected}/{self.bus_nets}, unconnected items {self.unconnected_items} | "
            f"bus DRC errors {self.drc_bus_errors} (answer {self.drc_bus_errors_answer}) | "
            f"length within spread {self.length_within_spread}/{self.bus_nets} | "
            f"vias {self.vias_total}, in packages {share} (answer {100 * self.vias_share_answer:.0f}%), "
            f"max/net {self.max_vias_per_net} (answer {self.max_vias_per_net_answer}) | "
            f"layers {self.layers} | {self.seconds:.1f}s"
        )


def score(ref: refs.Reference, candidate_path: Path, drc_out: Path | None = None) -> Score:
    t0 = time.time()
    answer = refs.measure(ref)
    bus_nets = set(answer["bus"]["nets"])
    answer_facts = drc_facts(answer_drc(ref), bus_nets)

    cand_board = kb.load_board(candidate_path)
    cand_nets = kb.nets_matching(cand_board, ref.bus_net_pattern)
    if set(cand_nets) != bus_nets:
        raise ValueError(f"candidate bus nets differ from the answer's: {set(cand_nets) ^ bus_nets}")
    copper = kb.net_copper(cand_board, cand_nets)
    packages = {r: kb.package_info(kb.footprint(cand_board, r)) for r in ref.bus_parts}

    drc_out = drc_out or bench_dir() / f"{ref.key}-{candidate_path.stem}-drc.json"
    cand_facts = drc_facts(run_drc(candidate_path, drc_out), bus_nets)
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

    drc_ok = cand_facts["electrical_bus"] <= answer_facts["electrical_bus"]
    length_frac = within / n if n else 0.0
    vias_ok = (vias_inside / vias_total >= ans_share - 0.05) if vias_total else True
    layers_ok = layers <= set(ans_layers)
    vias_count_ok = max_vias <= ans_max_vias
    conn_frac = connected / n if n else 0.0
    composite = conn_frac * (0.6 + 0.15 * drc_ok + 0.15 * length_frac + 0.05 * (vias_ok and vias_count_ok) + 0.05 * layers_ok)
    passed = connected == n and cand_facts["unconnected_items"] == 0 and drc_ok

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
