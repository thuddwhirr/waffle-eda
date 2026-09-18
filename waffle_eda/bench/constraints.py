"""Per-reference design constraints, as if agreed upstream (decisions D17).

For a reference board the benchmark stands in for stages 1 to 4 of the pipeline: the packages are the chosen parts,
and the fab class is what the board's own bus copper demonstrably meets. Those values are handed to the router as
its rules and the result is judged under the same values with KiCad's DRC, through an overriding rules file placed
next to a copy of the board. The original copper meets its own constraints by construction; ours must too.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

from waffle_eda.bench import harness, references as refs
from waffle_eda.kicad import board as kb


@dataclass(frozen=True)
class PackageConstraints:
    pitch_mm: float
    pad_mm: float
    track_mm: float  # narrowest width the board uses in numbers under this package
    via_mm: float
    via_drill_mm: float
    style: str  # "dogbone" or "in-pad"


@dataclass(frozen=True)
class Constraints:
    reference: str
    board_mtime: float
    clearance_mm: float  # largest clearance rule the board's bus copper meets
    hole_to_copper_mm: float  # largest hole-to-copper rule the board's bus copper meets
    min_track_mm: float  # narrowest bus track
    min_via_mm: float  # smallest bus via pad
    min_drill_mm: float  # smallest bus via drill
    min_annular_mm: float
    layers: tuple[str, ...]  # copper layers the bus uses
    thickness_mm: float | None
    packages: dict[str, PackageConstraints]

    def rules_text(self) -> str:
        """A KiCad rules file that enforces exactly these values on every item of the board."""
        return (
            "(version 1)\n"
            f"(rule reference_constraints\n"
            f"  (constraint clearance (min {self.clearance_mm:.4f}mm))\n"
            f"  (constraint hole_clearance (min {self.hole_to_copper_mm:.4f}mm))\n"
            f"  (constraint track_width (min {self.min_track_mm:.4f}mm))\n"
            f"  (constraint via_diameter (min {self.min_via_mm:.4f}mm))\n"
            f"  (constraint hole_size (min {self.min_drill_mm:.4f}mm))\n"
            f"  (constraint annular_width (min {self.min_annular_mm:.4f}mm)))\n"
        )


def constraints_path(ref: refs.Reference) -> Path:
    return refs.repo_root() / "build" / f"constraints-{ref.key}.json"


def _copy_board(src: Path, work_dir: Path, name: str = "board") -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    for ext in (".kicad_pcb", ".kicad_pro"):
        s = src.with_suffix(ext)
        if s.is_file():
            shutil.copy(s, work_dir / (name + ext))
    return work_dir / (name + ".kicad_pcb")


def drc_with_rules(board_path: Path, rules_text: str, work_dir: Path, bus_nets: set[str], tag: str = "drc") -> dict:
    """Run KiCad's DRC on a copy of ``board_path`` under ``rules_text``; return the electrical facts for the bus."""
    copy = _copy_board(board_path, work_dir)
    (work_dir / "board.kicad_dru").write_text(rules_text)
    report = harness.run_drc(copy, work_dir / f"{tag}.json")
    return harness.drc_facts(report, bus_nets)


def _largest_met(board_path: Path, work_dir: Path, bus: set[str], constraint: str, vtype: str,
                 lo: float, hi: float, steps: int = 7) -> float:
    """Largest rule value under which the board's bus copper has no violation of ``vtype`` (binary search)."""
    best = lo
    for _ in range(steps):
        mid = (lo + hi) / 2
        facts = drc_with_rules(board_path, f"(version 1)\n(rule probe (constraint {constraint} (min {mid:.4f}mm)))\n",
                               work_dir, bus, tag="probe")
        if facts["electrical_bus_by_type"].get(vtype, 0) == 0:
            best, lo = mid, mid
        else:
            hi = mid
    return round(best - 0.0005, 4)  # a hair below the largest value met, so rounding never fails the original


def measure(ref: refs.Reference, force: bool = False) -> Constraints:
    """Measure (or load from cache) the constraints of a reference board."""
    path = constraints_path(ref)
    board_file = refs.board_path(ref)
    mtime = board_file.stat().st_mtime
    if path.is_file() and not force:
        data = json.loads(path.read_text())
        if data.get("board_mtime") == mtime:
            data["packages"] = {k: PackageConstraints(**v) for k, v in data["packages"].items()}
            data["layers"] = tuple(data["layers"])
            return Constraints(**data)
    board = kb.load_board(board_file)
    bus = set(kb.nets_matching(board, ref.bus_net_pattern))
    work = refs.repo_root() / "build" / "constraints" / ref.key
    clearance = _largest_met(board_file, work, bus, "clearance", "clearance", 0.05, 0.25)
    hole = _largest_met(board_file, work, bus, "hole_clearance", "hole_clearance", 0.10, 0.40)
    measure_json = refs.repo_root() / "build" / f"measure-{ref.key}.json"
    if not measure_json.is_file():
        refs.write_measurement(ref)
    m = json.loads(measure_json.read_text())
    fan_json = refs.repo_root() / "build" / f"fanout-{ref.key}.json"
    if not fan_json.is_file():
        from waffle_eda.bench import fanout_measure
        fan_json.write_text(json.dumps(fanout_measure.measure_fanout(ref), indent=1))
    fan = json.loads(fan_json.read_text())
    widths = Counter()
    vias: Counter = Counter()
    packages = {}
    for part, p in fan["packages"].items():
        pw, pv, classes = Counter(), Counter(), Counter()
        for ball in p["balls"]:
            for w, n in ball["widths_inside"].items():
                pw[float(w)] += n
                widths[float(w)] += n
            if ball["via"] and ball["via_class"] in ("in-pad", "diagonal", "channel", "near"):
                pv[(ball["via"]["dia"], ball["via"]["drill"])] += 1
                vias[(ball["via"]["dia"], ball["via"]["drill"])] += 1
                classes[ball["via_class"]] += 1
        common = [w for w, n in pw.items() if n >= 0.05 * sum(pw.values())]
        track = min(common) if common else (pw.most_common(1)[0][0] if pw else 0.1)
        via_d, via_drill = pv.most_common(1)[0][0] if pv else (0.45, 0.2)
        style = "in-pad" if classes and classes.most_common(1)[0][0] == "in-pad" else "dogbone"
        packages[part] = PackageConstraints(pitch_mm=p["pitch_mm"], pad_mm=p["pad_mm"], track_mm=track,
                                            via_mm=via_d, via_drill_mm=via_drill, style=style)
    common = [w for w, n in widths.items() if n >= 5]
    min_track = min(common) if common else min(widths)
    min_via = min(d for d, _ in vias) if vias else 0.45
    min_drill = min(drill for _, drill in vias) if vias else 0.2
    min_annular = min((d - drill) / 2 for d, drill in vias) if vias else 0.125
    try:
        thickness = kb.mm(board.GetDesignSettings().GetBoardThickness())
    except Exception:
        thickness = None
    c = Constraints(reference=ref.key, board_mtime=mtime, clearance_mm=clearance, hole_to_copper_mm=hole,
                    min_track_mm=min_track, min_via_mm=min_via, min_drill_mm=min_drill,
                    min_annular_mm=round(min_annular, 4), layers=tuple(m["bus"]["layers_used"]),
                    thickness_mm=thickness, packages=packages)
    path.write_text(json.dumps(asdict(c), indent=1))
    return c


def fanout_rules(c: Constraints, part: str):
    from waffle_eda.route.fanout import FanoutRules
    p = c.packages[part]
    return FanoutRules(track_mm=p.track_mm, clearance_mm=c.clearance_mm, via_mm=p.via_mm,
                       via_drill_mm=p.via_drill_mm, inner_layers=tuple(l for l in c.layers if l != "F.Cu"),
                       style=p.style, hole_clearance_mm=c.hole_to_copper_mm)


def summary(c: Constraints) -> str:
    parts = ", ".join(f"{k}: {v.pitch_mm} mm pitch, track {v.track_mm}, via {v.via_mm}/{v.via_drill_mm} {v.style}"
                      for k, v in c.packages.items())
    return (f"{c.reference}: clearance {c.clearance_mm} mm, hole-to-copper {c.hole_to_copper_mm} mm, "
            f"track >= {c.min_track_mm}, via >= {c.min_via_mm}/{c.min_drill_mm} (ring {c.min_annular_mm}), "
            f"layers {list(c.layers)}, thickness {c.thickness_mm} | {parts}")


if __name__ == "__main__":
    import sys
    keys = sys.argv[1:] or [k for k, r in refs.REFERENCES.items() if r.has_bus and refs.is_fetched(r)]
    for key in keys:
        print(summary(measure(refs.REFERENCES[key], force="--force" in sys.argv)), flush=True)
