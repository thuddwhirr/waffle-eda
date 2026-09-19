"""Length tuning (plan.md, M3): bring every bus net into the length window by replacing straight runs of its
copper with serpentines where the board has room, under KiCad's own collision test.

A serpentine on a run from P to Q leaves the line every ``pitch`` for a leg of amplitude ``A`` to one side and
comes back, adding 2A per bump. Bumps that would collide with copper of another net (or the board's) are left
out and the run stays straight there. The largest amplitude that fits is tried first, on either side. A net that
cannot reach its window is reported with the length still missing and the runs that were tried, never left
short in silence.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pcbnew

from waffle_eda.kicad import board as kb
from waffle_eda.route.obstacles import Obstacles


@dataclass
class LengthResult:
    tuned: dict = field(default_factory=dict)  # net -> (before_mm, after_mm)
    failed: dict = field(default_factory=dict)  # net -> diagnosis
    untouched: list = field(default_factory=list)

    def summary(self) -> str:
        return f"{len(self.tuned)} nets lengthened, {len(self.untouched)} already in window, {len(self.failed)} short"


def _net_tracks(board, net_name: str) -> list:
    return [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() == net_name]


def net_length_mm(board, net_name: str) -> float:
    return sum(kb.mm(t.GetLength()) for t in _net_tracks(board, net_name))


def _make_track(board, layer, width_mm, a, b, net):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(kb.nm(a[0]), kb.nm(a[1])))
    t.SetEnd(pcbnew.VECTOR2I(kb.nm(b[0]), kb.nm(b[1])))
    t.SetWidth(kb.nm(width_mm))
    t.SetLayer(layer)
    t.SetNet(net)
    return t


def _clear(obs: Obstacles, item, net_name: str, clearance_mm: float, hole_clearance_mm: float) -> bool:
    return obs.clear(item, clearance_mm, hole_clearance_mm=hole_clearance_mm) is None  # other nets only


def _serpentine(board, obs: Obstacles, track, amplitudes, pitch: float, clearance_mm: float,
                hole_clearance_mm: float, want_mm: float) -> tuple[list, float]:
    """Candidate replacement tracks for ``track`` with a bump every ``pitch``, each bump the largest of
    ``amplitudes`` that fits on either side; returns (tracks, added length). Bumps that fit nowhere are skipped.
    Stops adding bumps once ``want_mm`` is reached."""
    a, b = track.GetStart(), track.GetEnd()
    P = (kb.mm(a.x), kb.mm(a.y))
    Q = (kb.mm(b.x), kb.mm(b.y))
    L = math.hypot(Q[0] - P[0], Q[1] - P[1])
    if L < 3 * pitch:
        return [], 0.0
    d = ((Q[0] - P[0]) / L, (Q[1] - P[1]) / L)
    layer, width, net = track.GetLayer(), kb.mm(track.GetWidth()), track.GetNet()
    name = net.GetNetname()
    lead = pitch / 2  # straight lead-in and lead-out, so the corners clear whatever the run's ends touch
    m = int((L - 2 * lead) // (2 * pitch))
    if m < 1:
        return [], 0.0

    def pt(s: float, off: float, side: int):
        n = (-d[1] * side, d[0] * side)
        return (P[0] + d[0] * s + n[0] * off, P[1] + d[1] * s + n[1] * off)

    pts = [P]
    added = 0.0
    for i in range(m):
        if added >= want_mm:
            break
        base = lead + 2 * i * pitch
        for amplitude in amplitudes:
            placed = False
            for side in (1, -1):
                bump = [pt(base, 0.0, side), pt(base, amplitude, side), pt(base + pitch, amplitude, side),
                        pt(base + pitch, 0.0, side)]
                legs = [_make_track(board, layer, width, bump[k], bump[k + 1], net) for k in range(3)]
                if all(_clear(obs, leg, name, clearance_mm, hole_clearance_mm) for leg in legs):
                    pts += bump
                    added += 2 * amplitude
                    placed = True
                    break
            if placed:
                break
    pts.append(Q)
    if added == 0.0:
        return [], 0.0
    tracks = []
    for u, v in zip(pts, pts[1:]):
        if math.hypot(v[0] - u[0], v[1] - u[1]) < 1e-6:
            continue
        tracks.append(_make_track(board, layer, width, u, v, net))
    # the straight pieces between bumps must clear too (they lie on the original run, so they normally do)
    if not all(_clear(obs, t, name, clearance_mm, hole_clearance_mm) for t in tracks):
        return [], 0.0
    return tracks, added


def lengthen(board, obs: Obstacles, net_name: str, min_mm: float, max_mm: float, clearance_mm: float,
             hole_clearance_mm: float = 0.0, amplitudes=(1.2, 0.9, 0.7, 0.5, 0.35, 0.25), pitch_mm: float = 0.3,
             min_run_mm: float = 0.7, skip_region=None) -> tuple[bool, str]:
    """Bring ``net_name`` to at least ``min_mm`` (never above ``max_mm``) with serpentines on its straight runs.
    ``skip_region(x, y)`` says where runs are left alone (inside the pad arrays). Returns (ok, note)."""
    before = net_length_mm(board, net_name)
    if before >= min_mm - 1e-3:
        return True, f"{before:.2f} mm, in window"
    deficit = min_mm - before
    room = max_mm - before
    # a trombone, one bump as deep as the deficit asks (capped), before the small bumps
    amplitudes = tuple(sorted({min(round(deficit / 2, 2), 8.0), 6.0, 4.0, 2.5, *amplitudes}, reverse=True))
    tried = 0
    runs = sorted(_net_tracks(board, net_name), key=lambda t: -t.GetLength())
    for track in runs:
        if deficit <= 0:
            break
        if kb.mm(track.GetLength()) < min_run_mm:
            continue
        a, b = track.GetStart(), track.GetEnd()
        mx, my = (kb.mm(a.x) + kb.mm(b.x)) / 2, (kb.mm(a.y) + kb.mm(b.y)) / 2
        if skip_region is not None and skip_region(mx, my):
            continue
        tried += 1
        obs.remove(track)
        tracks, added = _serpentine(board, obs, track, amplitudes, pitch_mm, clearance_mm, hole_clearance_mm,
                                    min(deficit, room))
        if added <= 0:
            obs.add(track)
            continue
        board.Delete(track)
        for t in tracks:
            board.Add(t)
            obs.add(t)
        deficit -= added
        room -= added
    after = net_length_mm(board, net_name)
    if after >= min_mm - 1e-3:
        return True, f"{before:.2f} -> {after:.2f} mm"
    return False, (f"{before:.2f} -> {after:.2f} mm, {min_mm - after:.2f} mm still missing; "
                   f"{tried} run(s) tried, no room for more bumps")


def tune_lengths(board, nets, min_mm: float, max_mm: float, clearance_mm: float, hole_clearance_mm: float = 0.0,
                 region_mm=None, skip_region=None, windows: dict | None = None) -> LengthResult:
    """``windows`` gives a net its own (min_mm, max_mm) in place of the common one."""
    obs = Obstacles(board, region_mm)
    result = LengthResult()
    lengths = {n: net_length_mm(board, n) for n in nets}
    windows = windows or {}
    for name in sorted(nets, key=lambda n: lengths[n]):  # the shortest first: it needs the most room
        lo, hi = windows.get(name, (min_mm, max_mm))
        if lengths[name] >= lo - 1e-3:
            result.untouched.append(name)
            continue
        ok, note = lengthen(board, obs, name, lo, hi, clearance_mm, hole_clearance_mm, skip_region=skip_region)
        if ok:
            result.tuned[name] = note
        else:
            result.failed[name] = note
    return result


def lane_windows(board, lanes: dict, pairs: dict, pair_mm: float = 0.2) -> dict:
    """Per-net (min, max) windows that match each lane (name -> (nets, window width in mm)) on total length: the
    longest member sets the floor, the width the ceiling; a differential pair (name -> two nets) is then held
    within ``pair_mm`` of its longer member."""
    out = {}
    lengths = {}
    for nets, width in lanes.values():
        for n in nets:
            lengths[n] = net_length_mm(board, n)
        top = max(lengths[n] for n in nets)
        for n in nets:
            out[n] = (top, top + width)
    for a, b in pairs.values():
        la, lb = lengths.get(a, net_length_mm(board, a)), lengths.get(b, net_length_mm(board, b))
        shorter = a if la < lb else b
        top = max(la, lb)
        lo, hi = out.get(shorter, (0.0, math.inf))
        out[shorter] = (max(lo, top - pair_mm), min(hi, top))
    return out
