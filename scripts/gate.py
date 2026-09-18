#!/usr/bin/env python3
"""The milestone gate: PASS only when every reference in the milestone's class passes in full. Exit 0 on PASS.

    python3 scripts/gate.py m1     # strip-and-score harness: do nothing scores 0, the original copper passes
    python3 scripts/gate.py m2     # fan-out: every bus ball on every BGA of every bus reference, zero electrical
                                   # violations under the reference's constraints; every synthetic case complete
                                   # and DRC clean
    python3 scripts/gate.py m3     # bus: ButterStick and LogicBone, every bus net connected, zero violations under
                                   # the constraints, every net's length within the original's spread, vias only
                                   # inside the packages

A reference that is not fetched is a FAIL, not a skip: the gate cannot vouch for what it did not run.
"""
from __future__ import annotations

import sys

import _path  # noqa: F401
from waffle_eda.bench import harness, references as refs, synthetic


def bus_references():
    return [r for r in refs.REFERENCES.values() if r.has_bus]


def gate_m1() -> list[tuple[str, bool, str]]:
    rows = []
    for ref in bus_references():
        if not refs.is_fetched(ref):
            rows.append((ref.key, False, "not fetched"))
            continue
        problem, _ = harness.strip_bus(ref)
        nothing = harness.score(ref, problem)
        answer = harness.score(ref, refs.board_path(ref))
        ok = nothing.score == 0.0 and nothing.connected == 0 and answer.passed
        rows.append((ref.key, ok, f"do nothing {nothing.score:.3f} ({nothing.connected} connected); "
                                  f"answer {'passed' if answer.passed else 'FAILED'} score {answer.score:.3f}"))
    return rows


def gate_m2() -> list[tuple[str, bool, str]]:
    import fanout_bench  # noqa: E402  (scripts/)
    rows = []
    for name in synthetic.CASES:
        result = fanout_bench.run_synthetic(name)
        parts = [k for k in result if k != "drc"]
        escaped = all(result[p]["placed"] == result[p]["total"] and result[p]["gate"]["escaped"] == result[p]["gate"]["total"] for p in parts)
        clean = result["drc"]["electrical_total"] == 0
        rows.append((name, escaped and clean, ", ".join(f"{p} {result[p]['placed']}/{result[p]['total']}" for p in parts)
                     + f"; DRC electrical {result['drc']['electrical_total']}"))
    for ref in bus_references():
        if not refs.is_fetched(ref):
            rows.append((ref.key, False, "not fetched"))
            continue
        result = fanout_bench.run_reference(ref.key)
        parts = [k for k in result if k != "drc"]
        escaped = all(result[p]["placed"] == result[p]["total"] for p in parts)
        ours = result["drc"]["ours"]
        orig = result["drc"]["original"]
        clean = ours["electrical_bus"] == 0
        detail = ", ".join(f"{p} {result[p]['placed']}/{result[p]['total']}" for p in parts)
        detail += f"; DRC under the reference's constraints: ours {ours['electrical_bus_by_type'] or 0}"
        if orig["electrical_bus"]:
            detail += f" (original itself {orig['electrical_bus_by_type']}: constraints suspect)"
        rows.append((ref.key, escaped and clean and orig["electrical_bus"] == 0, detail))
    return rows


M3_REFERENCES = ("butterstick", "logicbone")  # plan.md M3: "Passes ButterStick, then LogicBone"


def gate_m3() -> list[tuple[str, bool, str]]:
    import bus_bench  # noqa: E402  (scripts/)
    rows = []
    for key in M3_REFERENCES:
        ref = refs.REFERENCES[key]
        if not refs.is_fetched(ref):
            rows.append((key, False, "not fetched"))
            continue
        result = bus_bench.run_reference(key, draw=False)
        b = result["bus"]
        drc = b["drc"]
        ok = (b["routed"] == b["total"] and drc["electrical_bus"] == 0 and not drc["unconnected_bus_nets"]
              and b["passed"] and b["length_within"] == b["bus_nets"] and not b["vias_outside"])
        detail = (f"routed {b['routed']}/{b['total']}; DRC {drc['electrical_bus_by_type'] or 0}; unconnected "
                  f"{len(drc['unconnected_bus_nets'])}; lengths in spread {b['length_within']}/{b['bus_nets']}; "
                  f"nets with vias outside packages {len(b['vias_outside'])}")
        rows.append((key, ok, detail))
    return rows


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("m1", "m2", "m3"):
        print(__doc__)
        return 2
    rows = {"m1": gate_m1, "m2": gate_m2, "m3": gate_m3}[argv[0]]()
    failed = [r for r in rows if not r[1]]
    print(f"\n=== GATE {argv[0].upper()}: {'PASS' if not failed else 'FAIL'} ({len(rows) - len(failed)} of {len(rows)} cases pass) ===")
    for key, ok, detail in sorted(rows, key=lambda r: r[1]):
        print(f"  {'pass' if ok else 'FAIL'}  {key:<22} {detail}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
