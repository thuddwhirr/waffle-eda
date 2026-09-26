#!/usr/bin/env python3
"""The milestone gate: PASS only when every reference in the milestone's class passes in full. Exit 0 on PASS.

    python3 scripts/gate.py a        # class A: the whole board re-routed from placement: every net of every
                                     # class A reference connected, zero electrical violations under the rules
                                     # measured off that board (D50, D55)
    python3 scripts/gate.py b        # class B: the same re-route on every class B reference (four layers, planes,
                                     # net classes, a USB pair), in the order the plan lists them (D75, D84),
                                     # under the class's configuration (`CLASS_B`: the GND plane fed and handed
                                     # to the router, D86)
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
from waffle_eda.kicad import board as kb


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
    return _reroute_gate(m4_references(), CLASS_A)


def gate_b() -> list[tuple[str, bool, str]]:
    """Class B: the same full re-route from placement, on the class B references (plan.md, milestone B), under
    the rules measured off each board, in the configuration D86 made the class's baseline (`CLASS_B`). What
    class B adds to the criterion (widths per net class, the pair's gap and skew, plane integrity, return vias)
    is added here as each is measured to matter, never before."""
    return _reroute_gate(class_b_references(), CLASS_B)


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


# The configuration a class's rows run under. `planes`: which of a reference's recorded pours the router gets
# before the export, on layers typed power (D81): "none", every pour laid after the import; "gnd", the ground
# plane's inner layers; "inner", every inner-layer pour. `feeds`: the plane feeds and the stitching
# (route/planes.py, D85) for the inner pours' nets, a fixed via and stub beside every SMD pad of theirs before
# the router and one more feed for every piece left after the fill. `stubs`: the exit stubs (D51/D52's corridor
# rule and D85's fine-pitch rule) out of every pad as fixed wires (measured worse on both classes: D57, D83,
# D85). `rounds`: the closure loop's rounds (`route.freerouting.route_rounds`, D86), a round that leaves a
# fine-pitch pad open followed by one with a fixed exit stub out of that pad. `gui`: the jar's window under
# Xvfb (D85: its renderer dies drawing a plane, so class B runs without). Class A's is the configuration its
# gate passed under (D73); class B's is the baseline of D86. `WAFFLE_PLANES`, `WAFFLE_FEEDS`, `WAFFLE_STUBS`,
# `WAFFLE_ROUNDS` and `WAFFLE_ROUTER_GUI` override a class's values for a measurement, and the row says so.
# `timeout_s` caps one run of the router where the wrapper's own cap (1200 s) is too short for the class's
# passes: upduino's 30 passes took 1305 s on 2026-09-25's container, and the cap killed the row in pass 26.
# `feeds_mode` is the form the router meets the feeds in (D91): "fixed" wires it routes around, "routable"
# wires of its own, "after" (none: laid after the import around its copper), "reserved" (their sites as
# keepouts, laid after the import); `WAFFLE_FEEDS_MODE` selects another for a measurement.
# `via_in_pad`: a feed's via in any pad it fits, the fab's filled-and-capped option (D93: routing before cost);
# `WAFFLE_VIA_IN_PAD=1` selects it for a measurement.
# `pour_pins`: a fine-pitch pin of a plane net left to the pour of its own layer, no feed beside it (D95, the
# reference's way at a QFN's GND pins); `WAFFLE_POUR_PINS=1` selects it for a measurement.
CLASS_A = {"planes": "none", "feeds": False, "stubs": False, "rounds": 1, "gui": True, "feeds_mode": "fixed",
           "via_in_pad": False, "pour_pins": False}
CLASS_B = {"planes": "inner", "feeds": True, "stubs": False, "rounds": 1, "gui": False, "timeout_s": 6000.0,
           "feeds_mode": "none", "via_in_pad": False, "pour_pins": False,
           # D120 (option 2 of docs/review-class-b.md): the clean-plane configuration, the planes on `signal`
           # layers the router connects itself with D107's jar keeping their layers priced through the DSN block,
           # a via at 20 and a plane via at 2 (D103), the ripup start at 400 (D111), no via keepout band (D104 helped at U3
           # alone, D121 hurt at every fine-pitch package, D123 measured none as best); the row passes with a
           # documented residue of at most `residue_max` open
           # nets and as many hair-width clearances, every plane net whole and no short. The cap fits the
           # class's slowest reference: pico-ice takes about 150 s a pass and was killed at pass 28 of 30 under
           # 4200 s with no session written (D122)
           "plane_type": "signal", "jar": "d107", "layer_costs": 30.0, "via_costs": 20, "plane_via_costs": 2,
           "ripup_costs": 400, "via_bands": None, "residue_max": 10}  # no band: 79 of 86 for 77 banded at U3 (D123)


def configuration(defaults: dict) -> dict:
    """The class's configuration with the environment's overrides applied."""
    out = dict(defaults)
    if os.environ.get("WAFFLE_PLANES"):
        out["planes"] = os.environ["WAFFLE_PLANES"]
    if os.environ.get("WAFFLE_FEEDS"):
        out["feeds"] = os.environ["WAFFLE_FEEDS"] == "1"
    if os.environ.get("WAFFLE_STUBS"):
        out["stubs"] = os.environ["WAFFLE_STUBS"] == "1"
    if os.environ.get("WAFFLE_ROUNDS"):
        out["rounds"] = int(os.environ["WAFFLE_ROUNDS"])
    if os.environ.get("WAFFLE_ROUTER_GUI"):
        out["gui"] = os.environ["WAFFLE_ROUTER_GUI"] != "0"
    if os.environ.get("WAFFLE_FEEDS_MODE"):
        out["feeds_mode"] = os.environ["WAFFLE_FEEDS_MODE"]
    if os.environ.get("WAFFLE_VIA_IN_PAD"):
        out["via_in_pad"] = os.environ["WAFFLE_VIA_IN_PAD"] == "1"
    if os.environ.get("WAFFLE_POUR_PINS"):
        out["pour_pins"] = os.environ["WAFFLE_POUR_PINS"] == "1"
    if os.environ.get("WAFFLE_RESIDUE_MAX") and "residue_max" in out:
        out["residue_max"] = int(os.environ["WAFFLE_RESIDUE_MAX"])
    if os.environ.get("WAFFLE_VIA_BANDS") and "via_bands" in out:  # "none" or "fine-pitch" (D120, D121)
        out["via_bands"] = None if os.environ["WAFFLE_VIA_BANDS"] == "none" else os.environ["WAFFLE_VIA_BANDS"]
    return out


def plane_split(board, pours: list[dict], planes: str) -> tuple[list[dict], list[dict]]:
    outer = {kb.copper_layers(board)[0][1], kb.copper_layers(board)[-1][1]}
    if planes == "inner":
        before = [p for p in pours if p["layer"] not in outer]
    elif planes == "gnd":
        before = [p for p in pours if p["layer"] not in outer and p["net"] == "GND"]
    elif planes == "none":
        before = []
    else:
        raise ValueError(f"WAFFLE_PLANES={planes!r}: none, gnd or inner")
    return before, [p for p in pours if p not in before]


def _reroute_gate(references, defaults: dict) -> list[tuple[str, bool, str]]:
    from waffle_eda.bench import rebuild
    from waffle_eda.route import freerouting, planes as feedlib
    rows = []
    missing = freerouting.available()
    cfg = configuration(defaults)
    overridden = {k: v for k, v in cfg.items() if v != defaults[k]}
    budget = router_budget()  # the environment's, over the class's own cap
    cap = {"timeout_s": cfg["timeout_s"]} if "timeout_s" in cfg else {}
    budget = {**cap, **budget}
    for ref in references:
        if not refs.is_fetched(ref):
            rows.append((ref.key, False, "not fetched"))
            continue
        if missing:
            rows.append((ref.key, False, missing))
            continue
        out = rebuild.problem_path(ref).with_name(f"{ref.key}-routed.kicad_pcb")
        finishing: dict = {}

        def finish(routed, _work):  # the gate's finishing of a routed board: the child-process fill with D14's
            finishing.update(feedlib.finish(routed, out, rules, plane_nets or set()))  # fallbacks (the
            return out  # in-process fill can take an hour), the plane nets stitched, the file scored below

        try:
            bare, info = rebuild.strip_all(ref)
            rules = rebuild.measure_rules(ref)
            board = kb.load_board(bare)
            planes, pours = plane_split(board, info["pours"], cfg["planes"])
            outer = {kb.copper_layers(board)[0][1], kb.copper_layers(board)[-1][1]}
            plane_nets = {p["net"] for p in info["pours"] if p["layer"] not in outer} if cfg["feeds"] else None
            extra: dict = {}
            if "plane_type" in cfg:  # the class B configuration of D120
                extra = {"plane_type": cfg["plane_type"], "jar_name": cfg["jar"], "via_costs": cfg["via_costs"],
                         "plane_via_costs": cfg["plane_via_costs"], "ripup_costs": cfg["ripup_costs"],
                         "via_bands": cfg["via_bands"],
                         "layer_trace_costs": {p["layer"]: cfg["layer_costs"] for p in planes} if planes else None}
            _final, results = freerouting.route_rounds(bare, rules, refs.repo_root() / "build" / "fr" / ref.key, finish,
                                                       rounds=cfg["rounds"], pours=pours, planes=planes, feeds=plane_nets,
                                                       stubs=cfg["stubs"], gui=cfg["gui"], feeds_mode=cfg["feeds_mode"],
                                                       via_in_pad=cfg["via_in_pad"], pour_pins_rule=cfg["pour_pins"],
                                                       **extra, **budget)
            result = results[-1]
        except Exception as why:  # a board the benchmark cannot even pose is a failure, not a skip
            rows.append((ref.key, False, f"{type(why).__name__}: {why}"))
            continue
        fill, stitched = finishing["fill"], finishing["stitched"]
        s = rebuild.score(ref, out)
        rebuild.write_score(s)
        fill_note = "" if fill["mode"] == "all" else f" | fill {fill}"
        # the row names the configuration that produced it (definition.md section 5)
        config_note = ((f" | router budget overridden: {router_budget()}" if router_budget() else "")
                       + (f" | cap {cap['timeout_s']:.0f} s" if cap else "")
                       + (f" | configuration overridden: {overridden}" if overridden else "")
                       + (f" | planes {cfg['planes']}" if cfg["planes"] != "none" else "")
                       + (f" | feeds {result.feeds} {result.feeds_mode}{' via-in-pad' if cfg['via_in_pad'] else ''}"
                          f"{' pour-pins' if cfg['pour_pins'] else ''}, stitched {len(stitched)}" if plane_nets else "")
                       + (f" | stubs {result.stubs}" if cfg["stubs"] else "")
                       + (f" | rounds {len(results)} of {cfg['rounds']}, exits {list(result.exits)}" if cfg["rounds"] > 1 else "")
                       + (" | no window" if not cfg["gui"] else ""))
        verdict, residue_note = s.passed, ""
        if "residue_max" in cfg:  # option 2 (D120): the row passes with a documented residue
            r = rebuild.residue(ref, out, s, plane_nets or set(), {p["layer"] for p in planes},
                                refs.repo_root() / "build" / "fr" / ref.key / "residue")
            page = out.with_name(f"{ref.key}-residue.md")
            page.write_text(rebuild.residue_markdown(r))
            verdict, residue_note = rebuild.residue_verdict(r, cfg["residue_max"])
            residue_note = f" | {residue_note} ({page.name})"
        rows.append((ref.key, verdict, s.summary() + residue_note + " | " + result.summary() + fill_note + config_note))
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
