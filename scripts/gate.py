#!/usr/bin/env python3
"""The milestone gate: PASS only when every reference in the milestone's class passes in full. Exit 0 on PASS.

    python3 scripts/gate.py a        # class A: the whole board re-routed from placement: every net of every
                                     # class A reference connected, zero electrical violations under the rules
                                     # measured off that board (D50, D55)
    python3 scripts/gate.py b        # class B: the same re-route on every class B reference (four layers, planes,
                                     # net classes, a USB pair), in the order the plan lists them (D75)
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
Reference keys after the gate name (`gate.py a tinkerforge-temperature`) run those rows only, for climbing the
ladder one board at a time; the milestone is the whole gate, never a subset.
"""
from __future__ import annotations

import os
import sys

import _path  # noqa: F401
from waffle_eda.bench import harness, references as refs, synthetic
from waffle_eda.kicad import board as kb, refill


def bus_references():
    return [r for r in refs.REFERENCES.values() if r.has_bus]


ONLY: list[str] = []  # reference keys named on the command line; empty means every reference of the gate


def m4_references():
    """M4's ladder: class A, smallest first, as D49 sets it. `tinkerforge-temperature` is the registry's own
    smoke test for every stage; `libresolar-mppt-2420` is the one whose power on continuous copper matters."""
    order = ["tinkerforge-temperature", "open-book-c1", "olimex-esp32c3-devkit", "olimex-rp2040-pico-pc",
             "libresolar-mppt-2420"]  # crkbd-corne-cherry left the ladder (D72)
    return [refs.REFERENCES[k] for k in order if k in refs.REFERENCES and (not ONLY or k in ONLY)]


CLASS_B_ORDER = ["upduino-v3.01", "pico-ice-rev3", "sensor-watch-c1", "tinkerforge-master-v3.2", "buspirate5-rev10",
                 "olimex-esp32-poe-m1", "tinytapeout-demo", "mch2022-badge", "fomu-pvt"]


def class_b_references():
    """Class B's ladder in the order the plan lists its references (D75, reordered by D84): `upduino-v3.01`
    first as the class's simplest routing problem measured, `pico-ice-rev3` second, the densest small board
    third, the WLCSP at 0.35 mm pitch last."""
    return [refs.REFERENCES[k] for k in CLASS_B_ORDER if k in refs.REFERENCES and (not ONLY or k in ONLY)]


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
    """Class A: a full re-route of each class A reference from placement, DRC clean (plan.md, milestone A; D49).

    The ladder rises as class C's does: the smallest board first. The benchmark is `waffle_eda.bench.rebuild`,
    whose two sanity checks (the stripped board scores 0.000, the original 1.000) are asserted by the tests. This
    gate judges only what the tool produces: stage 5's baseline, Freerouting behind `route.freerouting` (D55,
    D56), with the DSN, session and log of every board left under `build/fr/<key>/`.
    """
    return _reroute_gate(m4_references())


def gate_b() -> list[tuple[str, bool, str]]:
    """Class B: the same full re-route from placement, on the class B references (plan.md, milestone B), under
    the rules measured off each board. What class B adds to the criterion (widths per net class, the pair's gap
    and skew, plane integrity, return vias) is added here as each is measured to matter, never before."""
    return _reroute_gate(class_b_references())


def router_budget() -> dict:
    """The router's passes and time cap: the defaults of `route_board` for a milestone run, or shorter ones
    from `WAFFLE_ROUTER_PASSES` and `WAFFLE_ROUTER_TIMEOUT_S` to fail faster while iterating on a board (D77).
    A row routed under an override says so; a milestone is never claimed on one."""
    import os
    out = {}
    if os.environ.get("WAFFLE_ROUTER_PASSES"):
        out["passes"] = int(os.environ["WAFFLE_ROUTER_PASSES"])
    if os.environ.get("WAFFLE_ROUTER_TIMEOUT_S"):
        out["timeout_s"] = float(os.environ["WAFFLE_ROUTER_TIMEOUT_S"])
    return out


# Which of a reference's recorded pours the router gets before the export, as planes on layers typed power
# (D81): none, as class A does (every pour laid after the import); "gnd", the ground plane's inner layers; or
# "inner", every inner-layer pour. `WAFFLE_PLANES` selects it while the class B rungs are measured.
PLANES = os.environ.get("WAFFLE_PLANES", "none")
# The plane feeds and the stitching (route/planes.py, D85) for the inner pours' nets: a fixed via and stub
# beside every SMD pad of theirs before the router, one more feed for every piece left after the fill.
# `WAFFLE_FEEDS=1` selects it while the class B rungs are measured.
FEEDS = os.environ.get("WAFFLE_FEEDS", "0") == "1"
# The exit stubs (D51/D52's corridor rule and D85's fine-pitch rule) as fixed wires before the router:
# `WAFFLE_STUBS=1` selects them while the class B rungs are measured (off on class A, D57 and D83).
STUBS = os.environ.get("WAFFLE_STUBS", "0") == "1"


def plane_split(board, pours: list[dict]) -> tuple[list[dict], list[dict]]:
    outer = {kb.copper_layers(board)[0][1], kb.copper_layers(board)[-1][1]}
    if PLANES == "inner":
        planes = [p for p in pours if p["layer"] not in outer]
    elif PLANES == "gnd":
        planes = [p for p in pours if p["layer"] not in outer and p["net"] == "GND"]
    else:
        planes = []
    return planes, [p for p in pours if p not in planes]


def _reroute_gate(references) -> list[tuple[str, bool, str]]:
    from waffle_eda.bench import rebuild
    from waffle_eda.route import freerouting
    rows = []
    missing = freerouting.available()
    budget = router_budget()
    if PLANES != "none":
        budget = {**budget}  # the row says which planes it ran with (D38)
    for ref in references:
        if not refs.is_fetched(ref):
            rows.append((ref.key, False, "not fetched"))
            continue
        if missing:
            rows.append((ref.key, False, missing))
            continue
        try:
            bare, info = rebuild.strip_all(ref)
            rules = rebuild.measure_rules(ref)
            board = kb.load_board(bare)  # route_board modifies it in place and returns what it did
            planes, pours = plane_split(board, info["pours"])
            outer = {kb.copper_layers(board)[0][1], kb.copper_layers(board)[-1][1]}
            plane_nets = {p["net"] for p in info["pours"] if p["layer"] not in outer} if FEEDS else None
            result = freerouting.route_board(board, rules, refs.repo_root() / "build" / "fr" / ref.key,
                                             pours=pours, planes=planes, feeds=plane_nets, stubs=STUBS, **budget)
        except Exception as why:  # a board the benchmark cannot even pose is a failure, not a skip
            rows.append((ref.key, False, f"{type(why).__name__}: {why}"))
            continue
        out = rebuild.problem_path(ref).with_name(f"{ref.key}-routed.kicad_pcb")
        kb.save_board(board, out)
        fill = refill.refill_file(out)  # a child process with D14's fallbacks; the in-process fill can take an hour
        stitched = []
        if plane_nets:
            from waffle_eda.route import planes as feedlib
            routed = kb.load_board(out)
            stitched = feedlib.stitch(routed, rules, plane_nets)
            if stitched:
                kb.save_board(routed, out)
                fill = refill.refill_file(out)
        s = rebuild.score(ref, out)
        rebuild.write_score(s)
        fill_note = "" if fill["mode"] == "all" else f" | fill {fill}"
        budget_note = ((f" | router budget overridden: {budget}" if budget else "")
                       + (f" | planes {PLANES}" if PLANES != "none" else "")
                       + (f" | feeds {result.feeds}, stitched {len(stitched)}" if plane_nets else "")
                       + (f" | stubs {result.stubs}" if STUBS else ""))
        rows.append((ref.key, s.passed, s.summary() + " | " + result.summary() + fill_note + budget_note))
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
    "b": gate_b,
    "escape": gate_m2, "m2": gate_m2,
    "busplan": gate_m3a, "m3a": gate_m3a,
    "bus": gate_m3, "m3b": gate_m3, "m3": gate_m3,
    "harness": gate_m1, "m1": gate_m1,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in GATES:
        print(__doc__)
        return 2
    unknown = [k for k in argv[1:] if k not in refs.REFERENCES]
    if unknown:
        print(f"not a reference: {unknown}")
        return 2
    ONLY[:] = argv[1:]
    rows = GATES[argv[0]]()
    failed = [r for r in rows if not r[1]]
    print(f"\n=== GATE {argv[0].upper()}: {'PASS' if not failed else 'FAIL'} ({len(rows) - len(failed)} of {len(rows)} cases pass) ===")
    for key, ok, detail in sorted(rows, key=lambda r: r[1]):
        print(f"  {'pass' if ok else 'FAIL'}  {key:<22} {detail}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
