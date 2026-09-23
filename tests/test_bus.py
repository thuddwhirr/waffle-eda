"""The bus router on the synthetic pairs after the fan-out: every bus net connected, DRC clean."""
import pytest

from waffle_eda.bench import harness, synthetic
from waffle_eda.kicad import board as kb
from waffle_eda.route import bus as busr, escape as esc, fanout as fo, length as lengthr


# The reversed pair is not a bus case: every pair of its nets crosses, and with layer changes only inside the
# packages a fully reversed order needs one layer per net. It stays an escape (M2) case.
@pytest.mark.parametrize("name", ["pair-6x6-straight", "pair-9x16-straight", "pair-20x20-bank"])
def test_bus_connects_every_net_drc_clean(name, tmp_path):
    case = synthetic.CASES[name]
    path = tmp_path / f"{name}.kicad_pcb"
    manifest = synthetic.make_bga_pair(case, path)
    board = kb.load_board(path)
    names = [n for _, n in kb.copper_layers(board)]
    rules = fo.FanoutRules(track_mm=case.track_mm, clearance_mm=case.clearance_mm, via_mm=case.via_mm,
                           via_drill_mm=case.via_drill_mm, inner_layers=tuple(n for n in names if n != "F.Cu"))
    bus = set(manifest["bus"])
    brules = busr.BusRules(track_mm=case.track_mm, clearance_mm=case.clearance_mm, via_mm=case.via_mm,
                           via_drill_mm=case.via_drill_mm, layers=tuple(names), margin_mm=3.0,
                           hole_clearance_mm=case.clearance_mm)
    res = busr.route_bus(board, ["U1", "U2"], bus, brules)  # from the pads: the bus router fans out itself
    assert not res.failed, res.summary() + " " + str(res.failed)
    kb.refill_zones(board)
    out = tmp_path / f"{name}-bus.kicad_pcb"
    kb.save_board(board, out)
    facts = harness.drc_facts(harness.run_drc(out, tmp_path / "drc.json"), bus)
    assert facts["electrical_bus"] == 0, facts
    assert not facts["unconnected_bus_nets"], facts


def test_length_tuning_reaches_the_window_drc_clean(tmp_path):
    name = "pair-6x6-straight"
    case = synthetic.CASES[name]
    path = tmp_path / f"{name}.kicad_pcb"
    manifest = synthetic.make_bga_pair(case, path)
    board = kb.load_board(path)
    names = [n for _, n in kb.copper_layers(board)]
    rules = fo.FanoutRules(track_mm=case.track_mm, clearance_mm=case.clearance_mm, via_mm=case.via_mm,
                           via_drill_mm=case.via_drill_mm, inner_layers=tuple(n for n in names if n != "F.Cu"))
    bus, power = set(manifest["bus"]), {"GND", "VCC"}
    for part, side in (("U1", "E"), ("U2", "W")):
        esc.escape_package(board, part, bus, rules, exit_side=side, power_nets=power)
    brules = busr.BusRules(track_mm=case.track_mm, clearance_mm=case.clearance_mm, via_mm=case.via_mm,
                           via_drill_mm=case.via_drill_mm, layers=tuple(names), margin_mm=3.0, spacing_mm=0.6,
                           hole_clearance_mm=case.clearance_mm)
    res = busr.route_bus(board, ["U1", "U2"], bus, brules)
    assert not res.failed
    before = {n: lengthr.net_length_mm(board, n) for n in bus}
    lo = 1.3 * max(before.values())
    # a second pass with the window: nets far short take a detour through free board area, the tuner does the rest
    res = busr.route_bus(board, ["U1", "U2"], bus, brules, length_windows={n: (lo, 3 * lo) for n in bus})
    assert not res.failed
    tuned = lengthr.tune_lengths(board, sorted(bus), lo, 3 * lo, case.clearance_mm)
    assert not tuned.failed, tuned.failed
    for n in bus:
        assert lengthr.net_length_mm(board, n) >= lo - 1e-3
    kb.refill_zones(board)
    out = tmp_path / f"{name}-tuned.kicad_pcb"
    kb.save_board(board, out)
    facts = harness.drc_facts(harness.run_drc(out, tmp_path / "drc.json"), bus)
    assert facts["electrical_bus"] == 0 and not facts["unconnected_bus_nets"], facts
