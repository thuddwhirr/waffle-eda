"""The lattice escape router: every synthetic ball, and the references at the levels recorded in decisions D15."""
import json

import pytest

from waffle_eda.bench import harness, references as refs, synthetic
from waffle_eda.kicad import board as kb
from waffle_eda.route import escape as esc, fanout as fo
from waffle_eda.route.lattice import Lattice


@pytest.mark.parametrize("name", sorted(synthetic.CASES))
def test_synthetic_cases_escape_completely(name, tmp_path):
    case = synthetic.CASES[name]
    path = tmp_path / f"{name}.kicad_pcb"
    manifest = synthetic.make_bga_pair(case, path)
    board = kb.load_board(path)
    names = [n for _, n in kb.copper_layers(board)]
    rules = fo.FanoutRules(track_mm=case.track_mm, clearance_mm=case.clearance_mm, via_mm=case.via_mm,
                           via_drill_mm=case.via_drill_mm, inner_layers=tuple(n for n in names if n != "F.Cu"))
    bus, power = set(manifest["bus"]), {"GND", "VCC"}
    for part, side in (("U1", "E"), ("U2", "W")):
        result = esc.escape_package(board, part, bus, rules, exit_side=side, power_nets=power)
        assert not result.failed, result.summary()
        gate = fo.escape_gate(board, part, bus, power)
        assert gate["escaped"] == gate["total"], gate
    kb.refill_zones(board)
    out = tmp_path / f"{name}-escaped.kicad_pcb"
    kb.save_board(board, out)
    facts = harness.drc_facts(harness.run_drc(out, tmp_path / "drc.json"), bus | power)
    assert facts["electrical_total"] == 0, facts


def _rules_from_measurements(ref):
    """The bench's per-package rules, from the measurement files (scripts/measure_references.py and
    waffle_eda.bench.fanout_measure must have run)."""
    import sys
    sys.path.insert(0, str(refs.repo_root() / "scripts"))
    import fanout_bench  # noqa: E402
    return fanout_bench.rules_for_reference(ref)[0]


# The target: every bus ball of every BGA package on every bus reference (docs/plan.md, M2). These tests stay red
# until the tool reaches it; the numbers are the packages' bus ball counts, never a level reached (CLAUDE.md).
EXPECTED = {
    "butterstick": {"U4": 55, "U11": 50, "U12": 50},
    "logicbone": {"IC1": 50, "IC2": 39, "IC3": 39},
    "orangecrab-r0.2.1": {"U3": 50, "U4": 50},
    "ulx3s": {"U1": 39},
}


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_reference_escapes_every_bus_ball(key):
    ref = refs.REFERENCES[key]
    problem = harness.bench_dir() / f"{ref.key}-problem.kicad_pcb"
    fan = refs.repo_root() / "build" / f"fanout-{ref.key}.json"
    if not refs.is_fetched(ref) or not problem.is_file() or not fan.is_file():
        pytest.skip(f"{key}: fetch, measure and strip first (scripts/fanout_bench.py)")
    rules = _rules_from_measurements(ref)
    board = kb.load_board(problem)
    bus = set(kb.nets_matching(board, ref.bus_net_pattern))
    parts = {r: Lattice(kb.footprint(board, r)) for r in ref.bus_parts}
    first = parts[ref.bus_parts[0]]
    for part, expected in EXPECTED[key].items():
        lat = parts[part]
        other = first if part != ref.bus_parts[0] else parts[ref.bus_parts[1]]
        side = lat.facing_side((other.x0 + other.X(other.cols - 1)) / 2, (other.y0 + other.Y(other.rows - 1)) / 2)
        result = esc.escape_package(board, part, bus, rules[part], exit_side=side)
        assert len(result.escaped) == expected == result.total, (
            f"M2 target not met on {key} {part}: {result.summary()}; failed balls {result.failed}")
