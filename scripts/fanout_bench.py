#!/usr/bin/env python3
"""Run the fan-out on the synthetic cases and on the bus references' problem boards, gate and DRC each result.

    python3 scripts/fanout_bench.py synthetic              # every synthetic case
    python3 scripts/fanout_bench.py butterstick logicbone  # references (strips the bus first)

Writes build/bench/<name>-fanout.kicad_pcb and prints one line per package plus the DRC summary.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.bench import constraints, harness, references as refs, synthetic
from waffle_eda.kicad import board as kb, refill
from waffle_eda.route import fanout as fo, escape as esc

ENGINE = os.environ.get("FANOUT_ENGINE", "lattice")  # "lattice" (escape.py) or "recipe" (fanout.py)


def run_engine(board, part, bus, rules, exit_side, power=frozenset()):
    if ENGINE == "recipe":
        return fo.fanout(board, part, bus, rules, exit_side=exit_side, power_nets=power)
    return esc.escape_package(board, part, bus, rules, exit_side=exit_side, power_nets=power)
from waffle_eda.route.lattice import Lattice

NOISE = ("memory leak",)


def rules_for_reference(ref: refs.Reference) -> tuple[dict[str, fo.FanoutRules], dict]:
    """Per package: the router's rules from the reference's constraints file (decisions D17)."""
    c = constraints.measure(ref)
    rules = {part: constraints.fanout_rules(c, part) for part in c.packages}
    return rules, {"constraints": constraints.summary(c)}


def drc_summary(board_path: Path, nets: set[str], baseline: dict | None, tag: str) -> dict:
    report = harness.run_drc(board_path, board_path.with_suffix(".drc.json"))
    facts = harness.drc_facts(report, nets)
    line = f"   DRC {tag}: electrical touching nets {facts['electrical_bus']} {facts['electrical_bus_by_type']}"
    if baseline is not None:
        line += f" | original board {baseline['electrical_bus']} {baseline['electrical_bus_by_type']}"
    print(line)
    return facts


def run_synthetic(name: str) -> dict:
    case = synthetic.CASES[name]
    out = Path("build/synthetic") / f"{name}.kicad_pcb"
    manifest = synthetic.make_bga_pair(case, out)
    board = kb.load_board(out)
    names = [n for _, n in kb.copper_layers(board)]
    rules = fo.FanoutRules(track_mm=case.track_mm, clearance_mm=case.clearance_mm, via_mm=case.via_mm,
                           via_drill_mm=case.via_drill_mm, inner_layers=tuple(n for n in names if n != "F.Cu"))
    bus = set(manifest["bus"])
    power = {"GND", "VCC"}
    results = {}
    for part, side in (("U1", "E"), ("U2", "W")):
        r = run_engine(board, part, bus, rules, side, power)
        g = fo.escape_gate(board, part, bus, power)
        print(f"{name:<22} {r.summary()} | gate {g['escaped']}/{g['total']} missing {list(g['missing'])[:6]}")
        results[part] = {"placed": len(r.escaped), "total": r.total, "gate": g}
    kb.refill_zones(board)
    result_path = Path("build/bench") / f"{name}-fanout.kicad_pcb"
    kb.save_board(board, result_path)
    results["drc"] = drc_summary(result_path, bus | power, None, "synthetic rules")
    return results


def run_reference(key: str) -> dict:
    ref = refs.REFERENCES[key]
    rules, facts = rules_for_reference(ref)
    print(f"== {key}: {facts['constraints']}", flush=True)
    problem, removed = harness.strip_bus(ref)
    board = kb.load_board(problem)
    bus = set(kb.nets_matching(board, ref.bus_net_pattern))
    parts = {r: Lattice(kb.footprint(board, r)) for r in ref.bus_parts}
    first = parts[ref.bus_parts[0]]
    results = {}
    for part, lat in parts.items():
        if lat.rows < 4 or lat.cols < 4:  # a TSOP or similar: not a BGA, no fan-out to do
            print(f"   {part}: {lat.rows}x{lat.cols}, not a ball grid, skipped")
            continue
        other = first if part != ref.bus_parts[0] else parts[ref.bus_parts[1]]
        ocx = (other.x0 + other.X(other.cols - 1)) / 2
        ocy = (other.y0 + other.Y(other.rows - 1)) / 2
        side = lat.facing_side(ocx, ocy)
        t0 = time.time()
        r = run_engine(board, part, bus, rules[part], side)
        g = fo.escape_gate(board, part, bus)
        print(f"   {r.summary()} | exit {side} | gate {g['escaped']}/{g['total']} missing {list(g['missing'].items())[:5]} | {time.time() - t0:.1f}s", flush=True)
        results[part] = {"placed": len(r.escaped), "total": r.total, "gate": g, "failed": r.failed}
    result_path = Path("build/bench") / f"{key}-fanout.kicad_pcb"
    kb.save_board(board, result_path)
    refill.refill_file(result_path)
    c = constraints.measure(ref)
    work = Path("build/constraints") / key
    ours = harness.drc_with_rules(result_path, c.rules_text(), work / "ours", bus, tag="fanout")
    orig = harness.drc_with_rules(refs.board_path(ref), c.rules_text(), work / "original", bus, tag="original")
    print(f"   DRC under the reference's constraints: ours {ours['electrical_bus']} {ours['electrical_bus_by_type']}"
          f" | original {orig['electrical_bus']} {orig['electrical_bus_by_type']}", flush=True)
    results["drc"] = {"ours": ours, "original": orig}
    return results


def main(argv: list[str]) -> int:
    out = {}
    for arg in argv or ["synthetic"]:
        if arg == "synthetic":
            for name in synthetic.CASES:
                out[name] = run_synthetic(name)
        else:
            out[arg] = run_reference(arg)
    Path("build/bench/fanout-results.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
