"""Probe a git repository for KiCad boards, to vet candidate reference boards before they enter the registry (D8).

A candidate is worth registering when it is open hardware under a licence that allows the use, has a board file that
pcbnew 9 loads, was manufactured and worked, and belongs to a class the tool claims (plan.md). This module answers
the mechanical part: what boards a repository holds, the licence text it carries, and each board's layers, outline,
packages and copper. It uses a shallow, blobless, no-checkout clone and fetches only the files it inspects, so
probing a large repository costs a few megabytes.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
from collections import Counter
from dataclasses import dataclass, asdict, field
from pathlib import Path

from waffle_eda.kicad import board as kb

LICENCE_RE = re.compile(r"(^|/)(LICEN[CS]E|COPYING)([.\-_][^/]*)?$", re.I)
BOARD_RE = re.compile(r"\.kicad_pcb$", re.I)
SKIP_PATH_RE = re.compile(r"(^|/)(\.|_)?(bak|backup|backups|old|test|tests|template|templates|autosave|examples?)(/|$)|-bak|\.bak", re.I)
MAX_BOARDS_PER_REPO = 15

_LICENCE_MARKS = (
    ("CERN-OHL-P", "CERN-OHL-P-2.0"), ("CERN-OHL-W", "CERN-OHL-W-2.0"), ("CERN-OHL-S", "CERN-OHL-S-2.0"),
    ("CERN Open Hardware Licence Version 2 - Permissive", "CERN-OHL-P-2.0"),
    ("CERN Open Hardware Licence Version 2 - Weakly", "CERN-OHL-W-2.0"),
    ("CERN Open Hardware Licence Version 2 - Strongly", "CERN-OHL-S-2.0"),
    ("CERN Open Hardware Licence v1.2", "CERN-OHL-1.2"), ("CERN OHL v1.2", "CERN-OHL-1.2"),
    ("CERN Open Hardware Licence v1.1", "CERN-OHL-1.1"), ("CERN Open Hardware Licence", "CERN-OHL"),
    ("Permission is hereby granted, free of charge", "MIT"), ("MIT License", "MIT"),
    ("Apache License", "Apache-2.0"), ("GNU LESSER GENERAL PUBLIC", "LGPL"), ("GNU GENERAL PUBLIC LICENSE", "GPL"),
    ("Attribution-ShareAlike", "CC-BY-SA"), ("Attribution-NonCommercial", "CC-BY-NC"),
    ("Attribution 4.0", "CC-BY-4.0"), ("Attribution 3.0", "CC-BY-3.0"), ("CC BY-SA", "CC-BY-SA"), ("CC BY", "CC-BY"),
    ("Creative Commons", "CC"), ("Redistribution and use in source and binary forms", "BSD"),
    ("TAPR Open Hardware License", "TAPR-OHL"), ("Solderpad", "Solderpad"), ("Unlicense", "Unlicense"),
    ("CC0", "CC0"),
)


def licence_guess(text: str) -> str:
    head = text[:4000]
    for mark, name in _LICENCE_MARKS:
        if mark.lower() in head.lower():
            return name
    return "unrecognised"


def _git(*args: str, cwd: Path | None = None) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def partial_clone(url: str, dest: Path, branch: str | None = None) -> str:
    """Shallow, blobless, no-checkout clone. Returns the HEAD commit. Blobs are fetched when a path is checked out."""
    if not (dest / ".git").is_dir():
        dest.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout"]
        if branch:
            args += ["--branch", branch]
        _git(*args, url, str(dest))
    return _git("rev-parse", "HEAD", cwd=dest).strip()


def list_files(dest: Path) -> list[str]:
    return _git("ls-tree", "-r", "--name-only", "HEAD", cwd=dest).splitlines()


def checkout_paths(dest: Path, paths: list[str]) -> None:
    if paths:
        _git("checkout", "--quiet", "HEAD", "--", *paths, cwd=dest)


def lattice_pitch_mm(points: list[tuple[float, float]]) -> float | None:
    """Pitch of a regular grid of pad centres (a BGA or LGA), or None when the pads do not form one."""
    if len(points) < 36:
        return None
    xs = sorted(set(round(x, 2) for x, _ in points))
    ys = sorted(set(round(y, 2) for _, y in points))
    if len(xs) < 4 or len(ys) < 4:
        return None
    px = statistics.median(b - a for a, b in zip(xs, xs[1:]))
    py = statistics.median(b - a for a, b in zip(ys, ys[1:]))
    if px <= 0.3 or px > 1.0 or abs(px - py) > 0.05:
        return None
    # A grid is filled; a perimeter package (QFP) also has regular x and y positions but almost no interior pads.
    if len(points) < 0.5 * len(xs) * len(ys):
        return None
    return round(px, 2)


@dataclass
class BoardFacts:
    path: str
    file_format_version: int | None
    copper_layers: int
    layer_names: list[str]
    outline_mm: list[float]
    footprints: int
    nets: int
    tracks: int
    vias: int
    min_track_mm: float | None
    track_widths_mm: list[list]  # [[width, count], ...] top 5
    via_sizes_mm: list[list]  # [[pad, drill, count], ...] top 3
    zones: int
    packages: list[dict] = field(default_factory=list)  # biggest 6 by pad count
    bga: list[str] = field(default_factory=list)
    qfn: list[str] = field(default_factory=list)
    qfp: list[str] = field(default_factory=list)
    through_hole_pads: int = 0
    smd_pads: int = 0
    error: str | None = None


def board_facts(path: Path, rel: str) -> BoardFacts:
    try:
        b = kb.load_board(path)
    except Exception as exc:  # a board pcbnew 9 cannot load is a fact worth recording
        return BoardFacts(rel, None, 0, [], [], 0, 0, 0, 0, None, [], [], 0, error=str(exc)[:200])
    layers = kb.copper_layers(b)
    fps = list(b.GetFootprints())
    th = smd = 0
    bga, qfn, qfp = [], [], []
    packages = []
    for fp in fps:
        pads = list(fp.Pads())
        drilled = sum(1 for p in pads if p.GetDrillSize().x > 0)
        th += drilled
        smd += len(pads) - drilled
        try:
            fpid = fp.GetFPIDAsString()
        except Exception:
            fpid = str(fp.GetFPID().GetLibItemName())
        up = fpid.upper()
        ref = fp.GetReference()
        pitch = None
        leadless = "QFN" in up or "DFN" in up or "SON" in up
        if drilled == 0 and len(pads) >= 36 and not leadless:
            pitch = lattice_pitch_mm([(kb.mm(p.GetPosition().x), kb.mm(p.GetPosition().y)) for p in pads])
        if leadless:
            qfn.append(f"{ref} {fpid.split(':')[-1]}")
        elif pitch is not None or "BGA" in up:
            bga.append(f"{ref} {fpid.split(':')[-1]} ({len(pads)} pads, pitch {pitch} mm)")
        elif "QFP" in up:
            qfp.append(f"{ref} {fpid.split(':')[-1]}")
        packages.append((len(pads), ref, fp.GetValue()[:24], fpid.split(":")[-1][:40]))
    packages.sort(reverse=True)
    widths = kb.track_width_histogram_mm(b)
    return BoardFacts(
        path=rel,
        file_format_version=kb.file_format_version(b),
        copper_layers=len(layers),
        layer_names=[n for _, n in layers],
        outline_mm=[round(v, 1) for v in kb.outline_size_mm(b)],
        footprints=len(fps),
        nets=len(kb.net_names(b)),
        tracks=len(kb.track_segments(b)),
        vias=len(kb.vias(b)),
        min_track_mm=min((w for w, _ in widths), default=None),
        track_widths_mm=[[w, n] for w, n in widths[:5]],
        via_sizes_mm=[[d, drill, n] for d, drill, n in kb.via_size_histogram_mm(b)[:3]],
        zones=len(list(b.Zones())),
        packages=[{"pads": n, "ref": r, "value": v, "footprint": f} for n, r, v, f in packages[:6]],
        bga=bga[:6],
        qfn=qfn[:6],
        qfp=qfp[:6],
        through_hole_pads=th,
        smd_pads=smd,
    )


def probe_repo(spec: str, work_dir: Path) -> dict:
    """``spec`` is ``owner/repo`` or ``owner/repo@branch`` (GitHub) or a full git URL."""
    branch = None
    if "@" in spec and not spec.startswith("git@"):
        spec, branch = spec.rsplit("@", 1)
    url = spec if "://" in spec else f"https://github.com/{spec}.git"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", spec.replace("https://github.com/", "").removesuffix(".git"))
    dest = work_dir / name
    result: dict = {"spec": spec, "url": url, "branch": branch}
    try:
        result["commit"] = partial_clone(url, dest, branch)
        files = list_files(dest)
    except Exception as exc:
        result["error"] = str(exc)[:300]
        return result
    boards = [f for f in files if BOARD_RE.search(f) and not SKIP_PATH_RE.search(f)]
    licences = [f for f in files if LICENCE_RE.search(f) and f.count("/") <= 1]
    result["board_files_total"] = sum(1 for f in files if BOARD_RE.search(f))
    result["boards_skipped_by_path"] = result["board_files_total"] - len(boards)
    boards = sorted(boards)[:MAX_BOARDS_PER_REPO]
    checkout_paths(dest, boards + licences[:3])
    result["licences"] = {}
    for lf in licences[:3]:
        try:
            result["licences"][lf] = licence_guess((dest / lf).read_text(errors="replace"))
        except Exception as exc:
            result["licences"][lf] = f"unreadable: {exc}"
    result["boards"] = [asdict(board_facts(dest / f, f)) for f in boards]
    return result


def summary_lines(repo: dict) -> list[str]:
    lines = []
    lic = ", ".join(f"{k}={v}" for k, v in repo.get("licences", {}).items()) or "no licence file"
    if "error" in repo:
        return [f"{repo['spec']:<44} ERROR {repo['error']}"]
    lines.append(f"{repo['spec']:<44} {repo.get('commit', '')[:10]}  {lic}  boards={repo.get('board_files_total', 0)}")
    for bd in repo.get("boards", []):
        if bd.get("error"):
            lines.append(f"    {bd['path'][:60]:<60} LOAD ERROR {bd['error'][:80]}")
            continue
        pk = ", ".join(f"{p['ref']}:{p['footprint'][:22]}({p['pads']})" for p in bd["packages"][:3])
        lines.append(
            f"    {bd['path'][:60]:<60} L{bd['copper_layers']} {bd['outline_mm'][0]}x{bd['outline_mm'][1]}mm "
            f"fp={bd['footprints']} nets={bd['nets']} tr={bd['tracks']} via={bd['vias']} "
            f"minw={bd['min_track_mm']} th/smd={bd['through_hole_pads']}/{bd['smd_pads']} "
            f"bga={len(bd['bga'])} qfn={len(bd['qfn'])} qfp={len(bd['qfp'])} fmt={bd['file_format_version']} | {pk}"
        )
    return lines


def survey(specs: list[str], work_dir: Path, out_path: Path | None = None, resume: bool = True) -> list[dict]:
    """Probe each spec; with ``resume`` (default) specs already present in ``out_path`` are kept, not re-probed."""
    results: list[dict] = []
    if resume and out_path and out_path.is_file():
        results = [r for r in json.loads(out_path.read_text()) if r.get("spec") in specs and "error" not in r]
    done = {r["spec"] for r in results}
    for spec in specs:
        if spec.split("@")[0] in done:
            continue
        repo = probe_repo(spec, work_dir)
        results.append(repo)
        print("\n".join(summary_lines(repo)), flush=True)
        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(results, indent=1))
    return results
