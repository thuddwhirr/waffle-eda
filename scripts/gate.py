#!/usr/bin/env python3
"""The milestone gate: PASS only when every reference in the milestone's class passes in full. Exit 0 on PASS.

    python3 scripts/gate.py a        # class A: the whole board re-routed from placement: every net of every
                                     # class A reference connected, zero electrical violations under the rules
                                     # measured off that board (D50, D55)
    python3 scripts/gate.py escape   # BGA escape (class B+): every bus ball on every BGA of every bus reference,
                                     # zero electrical violations under the reference's constraints; every
                                     # synthetic case complete and DRC clean
    python3 scripts/gate.py busplan  # the bus plan (class C): for every class C reference, our plan passes the
                                     # check of `waffle_eda.route.busplan` (every net in one piece, no crossings,
                                     # every via site legal for its package's style and its own, room for every
                                     # length deficit, the bus packages' escapes part of the plan)
    python3 scripts/gate.py bus      # the bus routing inside that plan (class C): every bus net connected, zero
                                     # violations under the constraints, lengths matched as the reference matches
                                     # them (D27), vias only inside the packages
    python3 scripts/gate.py harness  # the bus strip-and-score harness itself: do nothing scores 0, the original
                                     # copper passes

The milestone names of the first five days (m1, m2, m3a, m3b, m4) still work and mean the same gates.
A reference that is not fetched is a FAIL, not a skip: the gate cannot vouch for what it did not run.
"""
from __future__ import annotations

import sys

import _path  # noqa: F401
from waffle_eda.bench import harness, references as refs, synthetic
from waffle_eda.kicad import board as kb


def bus_references():
    return [r for r in refs.REFERENCES.values() if r.has_bus]


def m4_references():
    """M4's ladder: class A, smallest first, as D49 sets it. `tinkerforge-temperature` is the registry's own
    smoke test for every stage; `libresolar-mppt-2420` is the one whose power on continuous copper matters."""
    order = ["tinkerforge-temperature", "open-book-c1", "olimex-esp32c3-devkit", "olimex-rp2040-pico-pc",
             "crkbd-corne-cherry", "libresolar-mppt-2420"]
    return [refs.REFERENCES[k] for k in order if k in refs.REFERENCES]


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


def gate_m3a() -> list[tuple[str, bool, str]]:
    """M3a: our plan for every class C reference passes the check. The reference's own plan passing is the answer
    key and is asserted by the tests, not here: this gate judges what the tool produces."""
    import plan_bus  # noqa: E402  (scripts/)
    from waffle_eda.route import busplan as bp
    rows = []
    for ref in bus_references():
        if ref.cls != "C":
            continue
        if not refs.is_fetched(ref):
            rows.append((ref.key, False, "not fetched"))
            continue
        try:
            _ref, board, plan = plan_bus.build(ref.key, "planner")
        except SystemExit as why:
            rows.append((ref.key, False, str(why)))
            continue
        findings = bp.check(plan, board, _ref)
        rows.append((ref.key, not findings, bp.report(findings).splitlines()[0]))
    return rows


def gate_m4() -> list[tuple[str, bool, str]]:
    """Class A: a full re-route of each reference from placement, DRC clean under its own measured rules (D50,
    D55). The ladder rises smallest board first. The benchmark is `waffle_eda.bench.rebuild`, whose two sanity
    checks (the stripped board scores 0.000, the original 1.000) are asserted by the tests; stage 5 is
    `waffle_eda.route.stage5` (the specification's pours, stitching vias, Freerouting, the fill and the
    closure loop). A missing jar or Java is a failing row, not a skip."""
    from waffle_eda.bench import rebuild
    from waffle_eda.route import freerouting, stage5
    rows = []
    for ref in m4_references():
        if not refs.is_fetched(ref):
            rows.append((ref.key, False, "not fetched"))
            continue
        try:
            freerouting.check()
            bare, _info = rebuild.strip_all(ref)
            rules = rebuild.measure_rules(ref)
            board = kb.load_board(bare)
            out = rebuild.problem_path(ref).with_name(f"{ref.key}-routed.kicad_pcb")
            result = stage5.route(board, rules, rebuild.pour_spec(ref), harness.bench_dir() / "stage5" / ref.key,
                                  out_path=out)
        except freerouting.FreeroutingUnavailable as why:
            rows.append((ref.key, False, str(why)))
            continue
        except Exception as why:  # a board the benchmark cannot even pose is a failure, not a skip
            rows.append((ref.key, False, f"{type(why).__name__}: {why}"))
            continue
        s = rebuild.score(ref, out)
        rebuild.write_score(s)
        detail = s.summary()
        if result.failed:
            detail += f" | first failure: {sorted(result.failed.items())[0][1]}"
        rows.append((ref.key, s.passed, detail))
    return rows


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
              and b["passed"] and b["matching"] and not b["vias_outside"])
        detail = (f"routed {b['routed']}/{b['total']}; DRC {drc['electrical_bus_by_type'] or 0}; unconnected "
                  f"{len(drc['unconnected_bus_nets'])}; matching {'ok' if b['matching'] else 'FAIL'}; "
                  f"nets with vias outside packages {len(b['vias_outside'])}")
        rows.append((key, ok, detail))
    return rows


GATES = {
    "a": gate_m4, "m4": gate_m4,
    "escape": gate_m2, "m2": gate_m2,
    "busplan": gate_m3a, "m3a": gate_m3a,
    "bus": gate_m3, "m3b": gate_m3, "m3": gate_m3,
    "harness": gate_m1, "m1": gate_m1,
}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in GATES:
        print(__doc__)
        return 2
    rows = GATES[argv[0]]()
    failed = [r for r in rows if not r[1]]
    print(f"\n=== GATE {argv[0].upper()}: {'PASS' if not failed else 'FAIL'} ({len(rows) - len(failed)} of {len(rows)} cases pass) ===")
    for key, ok, detail in sorted(rows, key=lambda r: r[1]):
        print(f"  {'pass' if ok else 'FAIL'}  {key:<22} {detail}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
