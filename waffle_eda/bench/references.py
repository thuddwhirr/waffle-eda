"""The reference-board registry (``references.toml``), fetching, and a first measurement of each board.

The boards are never committed to this repository: they are open hardware under their own licences (recorded per
entry), and they are large. ``fetch`` makes a shallow, blobless, no-checkout clone of each repository and checks out
only the board's directory files (board, project, rules) and the licence file, pinned to the recorded commit.
Attribution for every board is in the registry entry and in docs/plan.md.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import tomllib
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

from waffle_eda.kicad import board as kb

REGISTRY_FILE = Path(__file__).with_name("references.toml")
CLASSES = ("A", "B", "B+", "C", "C'")
BOARD_DIR_SUFFIXES = (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".kicad_prl", ".pro")


@dataclass(frozen=True)
class Reference:
    key: str
    title: str
    cls: str  # ladder class, see docs/plan.md
    repo: str
    commit: str
    board: str  # path of the .kicad_pcb inside the checkout
    licence: str
    attribution: str
    branch: str | None = None  # None: the repository's default branch
    checkout: str | None = None  # directory name under references/; default derived from the repo
    licence_file: str | None = None
    key_parts: tuple[str, ...] = ()  # references of the main packages to measure
    bus_net_pattern: str | None = None  # regex over net names selecting the bus, when the board has one
    bus_net_count: int | None = None  # nets the pattern selects, as measured
    bus_parts: tuple[str, ...] = ()  # the packages the bus runs between; first is the controller (FPGA)
    notes: str = ""

    @property
    def has_bus(self) -> bool:
        return bool(self.bus_net_pattern)

    @property
    def checkout_name(self) -> str:
        if self.checkout:
            return self.checkout
        name = self.repo.removeprefix("https://github.com/").removesuffix(".git")
        return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def load_registry(path: Path = REGISTRY_FILE) -> dict[str, Reference]:
    data = tomllib.loads(path.read_text())
    out: dict[str, Reference] = {}
    for entry in data["reference"]:
        e = dict(entry)
        ref = Reference(
            cls=e.pop("class"),
            key_parts=tuple(e.pop("key_parts", ())),
            bus_parts=tuple(e.pop("bus_parts", ())),
            **e,
        )
        if ref.key in out:
            raise ValueError(f"duplicate reference key {ref.key}")
        out[ref.key] = ref
    return out


REFERENCES: dict[str, Reference] = load_registry()


def by_class(cls: str) -> list[Reference]:
    return [r for r in REFERENCES.values() if r.cls == cls]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def references_dir() -> Path:
    return Path(os.environ.get("WAFFLE_EDA_REFERENCES", repo_root() / "references"))


def checkout_dir(ref: Reference) -> Path:
    return references_dir() / ref.checkout_name


def board_path(ref: Reference) -> Path:
    return checkout_dir(ref) / ref.board


def is_fetched(ref: Reference) -> bool:
    return board_path(ref).is_file()


def _git(*args: str, cwd: Path | None = None) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:400]}")
    return r.stdout.strip()


def fetch(ref: Reference) -> Path:
    """Fetch the reference at its pinned commit: partial clone, then only the files the benchmark needs. Idempotent."""
    dest = checkout_dir(ref)
    if not (dest / ".git").is_dir():
        dest.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout"]
        if ref.branch:
            args += ["--branch", ref.branch]
        _git(*args, ref.repo, str(dest))
    if _git("rev-parse", "HEAD", cwd=dest) != ref.commit:
        # The branch tip moved since the pin: fetch the pinned commit and move HEAD without touching the worktree
        # (a plain checkout of the commit would populate the whole tree and fetch every blob).
        _git("fetch", "--quiet", "--depth", "1", "origin", ref.commit, cwd=dest)
        _git("reset", "--soft", ref.commit, cwd=dest)
    board_dir = str(Path(ref.board).parent)
    listing = _git("ls-tree", "--name-only", "HEAD", f"{board_dir}/" if board_dir != "." else ".", cwd=dest)
    wanted = [f for f in listing.splitlines() if f.endswith(BOARD_DIR_SUFFIXES)]
    if ref.board not in wanted:
        wanted.append(ref.board)
    if ref.licence_file:
        wanted.append(ref.licence_file)
    _git("checkout", "--quiet", "HEAD", "--", *wanted, cwd=dest)
    if not board_path(ref).is_file():
        raise FileNotFoundError(f"{ref.key}: board file missing after fetch: {board_path(ref)}")
    return board_path(ref)


def _measure_bus(board, ref: Reference, packages: dict[str, kb.PackageInfo]) -> dict:
    bus_nets = kb.nets_matching(board, ref.bus_net_pattern)
    copper = kb.net_copper(board, bus_nets)
    bus_packages = [packages[r] for r in ref.bus_parts]
    per_net = {}
    vias_total = vias_inside = 0
    via_hist: Counter = Counter()
    layer_use: Counter = Counter()
    width_use: Counter = Counter()
    for name in bus_nets:
        nc = copper[name]
        # "Inside a package" is the footprint bounding box: on ButterStick and LogicBone this reproduces the brief's
        # measurement (99 % and 97 % of bus vias); the pad-centre box grown by half a pitch read 92 % and 94 % (D3).
        inside = sum(1 for (x, y) in nc.via_positions_mm if any(p.in_footprint_mm(x, y) for p in bus_packages))
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
    return {
        "pattern": ref.bus_net_pattern,
        "parts": list(ref.bus_parts),
        "net_count": len(bus_nets),
        "routed_net_count": len(lengths),
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
    }


def measure(ref: Reference) -> dict:
    """First measurement of a reference board: structure, its key packages, and its bus copper when it has one."""
    board = kb.load_board(board_path(ref))
    layers = kb.copper_layers(board)
    packages: dict[str, kb.PackageInfo] = {}
    for r in dict.fromkeys((*ref.key_parts, *ref.bus_parts)):
        fp = kb.footprint(board, r)
        if fp is None:
            raise KeyError(f"{ref.key}: footprint {r} not found")
        packages[r] = kb.package_info(fp)
    widths = kb.track_width_histogram_mm(board)
    data = {
        "reference": ref.key,
        "title": ref.title,
        "class": ref.cls,
        "commit": ref.commit,
        "board": ref.board,
        "file_format_version": kb.file_format_version(board),
        "copper_layers": [name for _, name in layers],
        "outline_mm": [round(v, 2) for v in kb.outline_size_mm(board)],
        "footprints": len(list(board.GetFootprints())),
        "nets": len(kb.net_names(board)),
        "packages": {r: asdict(p) for r, p in packages.items()},
        "track_width_hist_mm": widths[:12],
        "min_track_mm": min((w for w, _ in widths), default=None),
        "via_sizes_mm": kb.via_size_histogram_mm(board),
    }
    if ref.bus_parts:
        first = packages[ref.bus_parts[0]]
        data["part_offsets_mm"] = {
            r: (round(packages[r].x_mm - first.x_mm, 2), round(packages[r].y_mm - first.y_mm, 2)) for r in ref.bus_parts[1:]
        }
    if ref.has_bus:
        data["bus"] = _measure_bus(board, ref, packages)
    return data


def write_measurement(ref: Reference, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (repo_root() / "build")
    out_dir.mkdir(parents=True, exist_ok=True)
    data = measure(ref)
    path = out_dir / f"measure-{ref.key}.json"
    path.write_text(json.dumps(data, indent=1))
    return path


def summary_line(data: dict) -> str:
    head = (
        f"{data['reference']:<26} {data['class']:<3} L{len(data['copper_layers'])} "
        f"{data['outline_mm'][0]}x{data['outline_mm'][1]}mm fp={data['footprints']} nets={data['nets']} "
        f"minw={data['min_track_mm']}"
    )
    bus = data.get("bus")
    if not bus:
        return head
    inside = bus["vias_in_packages"]
    total = bus["vias_total"]
    share = f"{100 * inside / total:.0f}%" if total else "n/a"
    lengths = bus["length_mm"]
    return (
        f"{head} | bus {bus['net_count']} nets, vias/net {bus['vias_per_net_hist']}, in-package {share}, "
        f"len {lengths['min']}/{lengths['median']}/{lengths['max']} mm, layers {list(bus['layers_used'])}"
    )
