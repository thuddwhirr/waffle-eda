"""Stage 5 for a class A board: pours and stitching vias, the baseline router, the fill, and the closure loop.

This is the order the pieces run in and the file trail they leave (``work_dir``), so that a run is a thing a
person can open at every step (definition.md, section 7):

1. ``pours``: the specification's pours are created on the bare board and filled (`route.pours`), and every
   surface pad of a poured net gets its stitching via while there is still room for one (`route.stitch`).
2. ``freerouting``: the baseline routes every other net; its DSN, session and log are in ``work_dir/freerouting``.
3. ``fill and check``: the board is saved, refilled in a child process (D14) and checked with KiCad's DRC under
   the measured rules. A pad of a poured net the fill did not reach gets a stitching via (`route.stitch`), and
   the fill and check run again, at most ``STITCH_ROUNDS`` times: that is the closure loop in its simplest
   form, and every round is logged in ``attempts.json``.

Escape stubs laid before the router (D51/D52) were tried here and measured out on 2026-09-23, twice: with the
router's fanout stage on, it escapes a stubbed pin a second time and the two escapes collide (2 of 6 nets on the
smoke test, 17 violations by its own count); with that stage off and a stub at every surface pad, 8 of 16 pads
found no via site under the hole rule and the router placed no via of its own (1 of 6). The neck it puts on its
own escapes is handled in `route.freerouting` instead.

The result names every net still unconnected and why, which is what the report in section 3 of the definition
is built from.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from waffle_eda.bench import harness
from waffle_eda.kicad import board as kb, refill
from waffle_eda.route import freerouting, pours as pours_mod, stitch
from waffle_eda.route.obstacles import Obstacles

STITCH_ROUNDS = 3
PAD_ITEM = re.compile(r"^Pad (\S+) \[(.+?)\] of (\S+) on ")


@dataclass
class Stage5Result:
    routed: list = field(default_factory=list)
    failed: dict = field(default_factory=dict)  # net -> why
    pours: int = 0
    stitched: list = field(default_factory=list)
    unstitchable: list = field(default_factory=list)
    router: str = ""
    rounds: int = 0
    seconds: float = 0.0
    board: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        return (f"{len(self.routed)} nets routed, {len(self.failed)} failed | pours {self.pours}, stitching vias "
                f"{len(self.stitched)} (none possible {len(self.unstitchable)}), {self.rounds} fill rounds | "
                f"{self.router} | {self.seconds:.0f}s")


def apply_settings(board, rules) -> None:
    """The board settings the fill and the DRC read when no rules file overrides them: hole and edge clearance
    at the measured values, so a pour keeps the hole rule around every via and stays off the edge."""
    ds = board.GetDesignSettings()
    ds.m_HoleClearance = kb.nm(rules.hole_to_copper_mm)
    ds.m_CopperEdgeClearance = kb.nm(rules.edge_clearance_mm)
    ds.m_MinClearance = kb.nm(rules.clearance_mm)


def unconnected_pads(report: dict) -> list[tuple[str, str, str]]:
    """(reference, pad number, net) for every pad the DRC report lists as unconnected, sorted, once each."""
    out = set()
    for u in report.get("unconnected_items", []):
        for item in u.get("items", []):
            m = PAD_ITEM.match(item.get("description", ""))
            if m:
                out.add((m.group(3), m.group(1), m.group(2)))
    return sorted(out)


def drc(board_path: Path, rules, work_dir: Path, tag: str) -> dict:
    copy = harness._copy_board(board_path, work_dir)
    (work_dir / "board.kicad_dru").write_text(rules.rules_text())
    return harness.run_drc(copy, work_dir / f"{tag}.json")


def route(board, rules, pour_spec: list, work_dir: Path, nets: list[str] | None = None,
          out_path: Path | None = None, passes: int = 100, timeout_s: float = 600.0) -> Stage5Result:
    """Run stage 5 on ``board`` (a bare board: placement, pads, outline, keepouts) and write the routed board
    to ``out_path`` (default ``work_dir/routed.kicad_pcb``), filled. ``rules`` is `bench.rebuild.BoardRules`."""
    from waffle_eda.bench import rebuild

    t0 = time.time()
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_path or work_dir / "routed.kicad_pcb"
    result = Stage5Result(board=str(out_path))
    attempts: list[dict] = []
    if nets is None:
        nets = sorted(rebuild.routable_nets(board))
    poured = {p.net for p in pour_spec}
    via_rules = stitch.ViaRules.from_board_rules(rules)

    # 1. pours
    apply_settings(board, rules)
    pours_mod.add_pours(board, pour_spec, clearance_floor_mm=rules.clearance_mm, min_width_floor_mm=rules.min_track_mm)
    kb.refill_zones(board)
    result.pours = len(pour_spec)
    if poured:
        before = stitch.stitch_poured_pads(board, Obstacles(board), poured, via_rules)
        result.stitched += before["stitched"]
        attempts.append({"step": "stitching vias before routing", **before})

    # 2. the baseline router
    fr = freerouting.route_board(board, rules, work_dir / "freerouting", nets=[n for n in nets if n not in poured],
                                 passes=passes, timeout_s=timeout_s, poured=poured)
    result.router = fr.summary()
    attempts.append({"step": "freerouting", "summary": fr.summary(), "failed": fr.failed})
    apply_settings(board, rules)  # the export set the hole clearance to the keepout growth
    kb.save_board(board, out_path)

    # 3. fill, check, stitch
    for round_no in range(1, STITCH_ROUNDS + 2):
        result.rounds = round_no
        refill.refill_file(out_path)
        report = drc(out_path, rules, work_dir / "check", tag=f"round{round_no}")
        pads = unconnected_pads(report)
        to_stitch = [(ref, num, net) for ref, num, net in pads if net in poured]
        attempts.append({"step": f"fill and check {round_no}", "unconnected_pads": pads})
        if not to_stitch or round_no > STITCH_ROUNDS:
            break
        board = kb.load_board(out_path)
        apply_settings(board, rules)
        obs = Obstacles(board)
        for ref, num, net in to_stitch:
            fp = board.FindFootprintByReference(ref)
            pad = next((p for p in fp.Pads() if p.GetNumber() == num), None) if fp else None
            if pad is None:
                continue
            name = f"{ref}.{num}"
            if name in result.unstitchable:
                continue
            at = stitch.stitch_pad(board, obs, pad, fp, via_rules)
            (result.stitched if at else result.unstitchable).append(name)
        kb.save_board(board, out_path)

    # what is still unconnected, per net
    unconnected_nets: dict[str, list[str]] = {}
    for ref, num, net in pads:
        unconnected_nets.setdefault(net, []).append(f"{ref}.{num}")
    for name in nets:
        if name in unconnected_nets:
            why = fr.failed.get(name, "")
            if name in poured:
                why = f"the fill does not reach {', '.join(unconnected_nets[name])} and no stitching via fits"
            elif not why:
                why = f"routed with copper that does not reach {', '.join(unconnected_nets[name])}"
            result.failed[name] = why
        else:
            result.routed.append(name)
    result.seconds = round(time.time() - t0, 1)
    (work_dir / "attempts.json").write_text(json.dumps({"result": asdict(result), "attempts": attempts}, indent=1, default=str))
    return result
