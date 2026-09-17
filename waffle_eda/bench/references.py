"""Registry of the open-hardware reference boards, how to fetch them, and a first measurement.

The boards are never committed to this repository: both are CERN OHL v1.2, and they are large. ``fetch`` clones each
at a pinned commit into ``references/`` (git-ignored). Attribution:

* ButterStick, Greg Davill, https://github.com/butterstick-fpga/butterstick-hardware, CERN OHL v1.2.
* LogicBone, Owen Kirby, https://github.com/oskirby/logicbone, CERN OHL v1.2.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

from waffle_eda.kicad import board as kb


@dataclass(frozen=True)
class Reference:
    key: str
    title: str
    repo: str
    branch: str
    commit: str
    board: str  # path of the .kicad_pcb inside the checkout
    licence: str
    attribution: str
    fpga_ref: str
    dram_refs: tuple[str, ...]
    bus_net_pattern: str  # regex over net names selecting the DDR3 bus (per board: naming differs)
    bus_net_count: int  # nets the pattern selects, as measured; a change means the board or the pattern changed
    notes: str = ""


REFERENCES: dict[str, Reference] = {
    "butterstick": Reference(
        key="butterstick",
        title="ButterStick r1.0",
        repo="https://github.com/butterstick-fpga/butterstick-hardware.git",
        branch="main",
        commit="0694ddfa9824a07f0c6c6981186e45f80187659c",
        board="hardware/ButterStick_r1.0/ButterStick.kicad_pcb",
        licence="CERN OHL v1.2",
        attribution="Greg Davill, butterstick-fpga",
        fpga_ref="U4",
        dram_refs=("U11", "U12"),
        bus_net_pattern=r"^/FPGA-DDR3L/",
        bus_net_count=55,
        notes="8 layers; ECP5UM5G-85 caBGA381; two DDR3L x16 FBGA-96 (dual rank) rotated 90; via-in-pad under the FPGA.",
    ),
    "logicbone": Reference(
        key="logicbone",
        title="LogicBone",
        repo="https://github.com/oskirby/logicbone.git",
        branch="master",
        commit="96e7bede72569be4db95d78e45a689c939225802",
        board="logicbone.kicad_pcb",
        licence="CERN OHL v1.2",
        attribution="Owen Kirby, oskirby",
        fpga_ref="IC1",
        dram_refs=("IC2", "IC3"),
        # Active-low nets carry KiCad's overline syntax: "/FPGA Memory/~{DDR3_CAS}". VREF is a supply, not the bus.
        bus_net_pattern=r"^/FPGA Memory/(?:~\{)?DDR3_(?!VREF)",
        bus_net_count=50,
        notes="8 layers; ECP5UM-85 caBGA381 rotated 90; two DDR3 x8 TFBGA-78 side by side; dog-bone fan-out; KiCad 5 file.",
    ),
    "butterstick-r0.2": Reference(
        key="butterstick-r0.2",
        title="ButterStick r0.2",
        repo="https://github.com/butterstick-fpga/butterstick-hardware.git",
        branch="main",
        commit="0694ddfa9824a07f0c6c6981186e45f80187659c",
        board="hardware/ButterStick_r0.2/ButterStick.kicad_pcb",
        licence="CERN OHL v1.2",
        attribution="Greg Davill, butterstick-fpga",
        fpga_ref="U3",
        dram_refs=(),
        bus_net_pattern=r"^HB[01]_",
        bus_net_count=26,
        notes="6 layers; ECP5U25 caBGA381; HyperRAM, no DDR3. Same checkout as butterstick. Class C' in the ladder.",
    ),
}

# Checkout directory per repository, so the two ButterStick revisions share one clone.
_CHECKOUT_NAME = {
    "https://github.com/butterstick-fpga/butterstick-hardware.git": "butterstick",
    "https://github.com/oskirby/logicbone.git": "logicbone",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def references_dir() -> Path:
    return Path(os.environ.get("WAFFLE_EDA_REFERENCES", repo_root() / "references"))


def checkout_dir(ref: Reference) -> Path:
    return references_dir() / _CHECKOUT_NAME[ref.repo]


def board_path(ref: Reference) -> Path:
    return checkout_dir(ref) / ref.board


def is_fetched(ref: Reference) -> bool:
    return board_path(ref).is_file()


def _git(*args: str, cwd: Path | None = None) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def fetch(ref: Reference) -> Path:
    """Clone the reference at its pinned commit (shallow). Idempotent."""
    dest = checkout_dir(ref)
    if not (dest / ".git").is_dir():
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", "--depth", "1", "--branch", ref.branch, ref.repo, str(dest))
    head = _git("rev-parse", "HEAD", cwd=dest)
    if head != ref.commit:
        # The branch tip moved since the pin: fetch the pinned commit itself and check it out.
        _git("fetch", "--quiet", "--depth", "1", "origin", ref.commit, cwd=dest)
        _git("checkout", "--quiet", ref.commit, cwd=dest)
    if not board_path(ref).is_file():
        raise FileNotFoundError(f"{ref.key}: board file missing after fetch: {board_path(ref)}")
    return board_path(ref)


def measure(ref: Reference) -> dict:
    """First measurement of a reference board: structure, packages, and the DDR3 bus copper."""
    board = kb.load_board(board_path(ref))
    layers = kb.copper_layers(board)
    packages = {}
    for r in (ref.fpga_ref, *ref.dram_refs):
        fp = kb.footprint(board, r)
        if fp is None:
            raise KeyError(f"{ref.key}: footprint {r} not found")
        packages[r] = kb.package_info(fp)
    fpga = packages[ref.fpga_ref]
    dram_offsets = {
        r: (round(packages[r].x_mm - fpga.x_mm, 2), round(packages[r].y_mm - fpga.y_mm, 2)) for r in ref.dram_refs
    }

    bus_nets = kb.nets_matching(board, ref.bus_net_pattern)
    copper = kb.net_copper(board, bus_nets)
    # A via is "inside a package" when it lies within the footprint bounding box of the FPGA or a DRAM. On the
    # pad-centre bbox grown by half a pitch the shares read 92 % and 94 %; on the footprint bbox 99 % and 96 %, which
    # is what the brief measured ("none outside the BGA footprints"; "103 of 106"). Evidence in decisions D3.
    per_net = {}
    vias_total = vias_inside = 0
    via_hist: Counter = Counter()
    layer_use: Counter = Counter()
    width_use: Counter = Counter()
    for name in bus_nets:
        nc = copper[name]
        inside = sum(1 for (x, y) in nc.via_positions_mm if any(p.in_footprint_mm(x, y) for p in packages.values()))
        vias_total += nc.via_count
        vias_inside += inside
        via_hist[nc.via_count] += 1
        for layer in nc.layers:
            layer_use[layer] += 1
        for w, n in nc.track_widths_mm:
            width_use[w] += n
        per_net[name] = {
            "length_mm": round(nc.length_mm, 3),
            "segments": nc.segments,
            "vias": nc.via_count,
            "vias_in_package": inside,
            "layers": list(nc.layers),
        }
    lengths = [v["length_mm"] for v in per_net.values() if v["segments"]]
    routed = [name for name, v in per_net.items() if v["segments"]]

    return {
        "reference": ref.key,
        "title": ref.title,
        "commit": ref.commit,
        "board": ref.board,
        "file_format_version": kb.file_format_version(board),
        "copper_layers": [name for _, name in layers],
        "outline_mm": [round(v, 2) for v in kb.outline_size_mm(board)],
        "footprints": len(list(board.GetFootprints())),
        "nets": len(kb.net_names(board)),
        "packages": {r: asdict(p) for r, p in packages.items()},
        "dram_offsets_from_fpga_mm": dram_offsets,
        "track_width_hist_mm": kb.track_width_histogram_mm(board)[:12],
        "via_sizes_mm": kb.via_size_histogram_mm(board),
        "bus": {
            "pattern": ref.bus_net_pattern,
            "net_count": len(bus_nets),
            "routed_net_count": len(routed),
            "vias_total": vias_total,
            "vias_in_packages": vias_inside,
            "vias_per_net_hist": dict(sorted(via_hist.items())),
            "layers_used": dict(layer_use.most_common()),
            "track_widths_mm": [[w, n] for w, n in width_use.most_common()],
            "length_mm": {
                "min": min(lengths) if lengths else None,
                "median": round(statistics.median(lengths), 3) if lengths else None,
                "max": max(lengths) if lengths else None,
            },
            "nets": per_net,
        },
    }


def write_measurement(ref: Reference, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (repo_root() / "build")
    out_dir.mkdir(parents=True, exist_ok=True)
    data = measure(ref)
    path = out_dir / f"measure-{ref.key}.json"
    path.write_text(json.dumps(data, indent=1))
    return path


def summary_line(data: dict) -> str:
    bus = data["bus"]
    inside = bus["vias_in_packages"]
    total = bus["vias_total"]
    share = f"{100 * inside / total:.0f}%" if total else "n/a"
    lengths = bus["length_mm"]
    return (
        f"{data['title']:<18} layers={len(data['copper_layers'])} bus nets={bus['net_count']} "
        f"vias/net={bus['vias_per_net_hist']} in-package={share} "
        f"length mm min/med/max={lengths['min']}/{lengths['median']}/{lengths['max']} "
        f"layers={list(bus['layers_used'])}"
    )
