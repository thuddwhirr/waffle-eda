"""Fan-out on the synthetic cases: every ball escapes, the independent gate agrees, and DRC is clean."""
import pytest

from waffle_eda.bench import harness, synthetic
from waffle_eda.kicad import board as kb
from waffle_eda.route import fanout as fo
from waffle_eda.route.lattice import Lattice


def _rules(case, board):
    names = [n for _, n in kb.copper_layers(board)]
    return fo.FanoutRules(track_mm=case.track_mm, clearance_mm=case.clearance_mm, via_mm=case.via_mm,
                          via_drill_mm=case.via_drill_mm, inner_layers=tuple(n for n in names if n != "F.Cu"))


@pytest.mark.parametrize("name", sorted(synthetic.CASES))
def test_every_ball_escapes_and_drc_is_clean(name, tmp_path):
    case = synthetic.CASES[name]
    path = tmp_path / f"{name}.kicad_pcb"
    manifest = synthetic.make_bga_pair(case, path)
    board = kb.load_board(path)
    rules = _rules(case, board)
    bus, power = set(manifest["bus"]), {"GND", "VCC"}
    for part, side in (("U1", "E"), ("U2", "W")):
        result = fo.fanout(board, part, bus, rules, exit_side=side, power_nets=power)
        assert not result.failed, result.summary()
        assert result.total == case.bus_nets + case.power_balls
        gate = fo.escape_gate(board, part, bus, power)
        assert gate["escaped"] == gate["total"], gate
    kb.refill_zones(board)
    out = tmp_path / f"{name}-fanout.kicad_pcb"
    kb.save_board(board, out)
    facts = harness.drc_facts(harness.run_drc(out, tmp_path / "drc.json"), bus | power)
    assert facts["electrical_total"] == 0, facts


def test_lattice_geometry(tmp_path):
    case = synthetic.CASES["pair-6x6-straight"]
    path = tmp_path / "l.kicad_pcb"
    synthetic.make_bga_pair(case, path)
    board = kb.load_board(path)
    u1, u2 = Lattice(kb.footprint(board, "U1")), Lattice(kb.footprint(board, "U2"))
    assert (u1.rows, u1.cols, u1.pitch) == (6, 6, 0.8)
    assert u1.facing_side(u2.X(0), u2.Y(0)) == "E" and u2.facing_side(u1.X(0), u1.Y(0)) == "W"
    corner, centre = u1.balls["A1"], u1.by_index[(2, 2)]
    assert corner.ring == 1 and centre.ring == 3
    # pt/key round trip: the east edge seen from E is along 0; one pitch outside is along -1
    x_edge, _ = u1.pt("E", 0, 0)
    x_out, _ = u1.pt("E", 0, -1)
    assert x_edge == pytest.approx(u1.X(5)) and x_out == pytest.approx(u1.X(6))
    assert u1.key("E", 2.5, 0.5) == (4.5, 2.5) and u1.key("N", 2.5, 0.5) == (2.5, 0.5)
