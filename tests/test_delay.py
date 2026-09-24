"""The per-layer propagation model (D48): outer copper is faster than inner, a path's delay is its length on each
layer against that layer's rate, and equal copper length on different layers is not equal delay."""
import math

import pytest

from waffle_eda.bench import delay, references as refs
from waffle_eda.kicad import board as kb

pytestmark = pytest.mark.parked  # class B+/C machinery: not run until its class is reached (docs/plan.md)


def test_outer_copper_is_faster_than_inner():
    """The whole reason delay and length differ: a surface line's field runs partly in air."""
    assert delay.ps_per_mm(4.5, outer=True) < delay.ps_per_mm(4.5, outer=False)


def test_the_model_reproduces_the_documented_microstrip_figure():
    """5.6 ps/mm on FR-4 is the figure `docs/research/ddr3-bus-routing.md` converts with; the formula has to
    land on it from the permittivity rather than carry it as a constant."""
    assert delay.ps_per_mm(delay.DEFAULT_ER, outer=True) == pytest.approx(5.6, abs=0.05)
    assert delay.ps_per_mm(delay.DEFAULT_ER, outer=False) == pytest.approx(7.08, abs=0.05)


def test_a_vacuum_dielectric_travels_at_the_speed_of_light():
    assert delay.ps_per_mm(1.0, outer=False) == pytest.approx(1 / 0.299792458, rel=1e-9)


def test_stripline_equivalent_of_an_all_stripline_path_is_its_own_length():
    """TI's convention is an identity on a path that never leaves an inner layer; it is only a conversion for
    one that does."""
    s = delay.Stackup(er=4.5, source="test", layers={"F.Cu": delay.ps_per_mm(4.5, True),
                                                     "In1.Cu": delay.ps_per_mm(4.5, False)})
    assert s.equivalent_stripline_mm({"In1.Cu": 20.0}) == pytest.approx(20.0)


def test_equal_copper_length_on_different_layers_is_not_equal_delay():
    """The measurement D47 asked for: two legs matched in copper, skewed in time."""
    s = delay.Stackup(er=4.5, source="test", layers={"F.Cu": delay.ps_per_mm(4.5, True),
                                                     "In1.Cu": delay.ps_per_mm(4.5, False)})
    outer = s.delay_ps({"F.Cu": 15.0})
    inner = s.delay_ps({"In1.Cu": 15.0})
    assert inner > outer
    assert inner - outer == pytest.approx(15.0 * (delay.ps_per_mm(4.5, False) - delay.ps_per_mm(4.5, True)))
    # 15 mm of the reference boards' scale is worth more than 20 ps of skew, which is twice ISSI's tolerance
    assert inner - outer > 20.0


def test_a_mixed_path_lies_between_the_two_pure_ones():
    s = delay.Stackup(er=4.5, source="test", layers={"F.Cu": delay.ps_per_mm(4.5, True),
                                                     "In1.Cu": delay.ps_per_mm(4.5, False)})
    mixed = s.delay_ps({"F.Cu": 5.0, "In1.Cu": 5.0})
    assert s.delay_ps({"F.Cu": 10.0}) < mixed < s.delay_ps({"In1.Cu": 10.0})


def test_an_undeclared_layer_still_gets_the_rate_for_its_kind():
    """A candidate may route on a layer the reference never used; it is measured, not silently dropped."""
    s = delay.Stackup(er=4.5, source="test", layers={"F.Cu": delay.ps_per_mm(4.5, True)})
    assert s.rate("In3.Cu") == pytest.approx(delay.ps_per_mm(4.5, False))
    assert s.rate("B.Cu") == pytest.approx(delay.ps_per_mm(4.5, True))


def test_butterstick_permittivity_comes_from_its_own_stackup():
    """ButterStick is the only class C reference whose file records a stackup, so it is the one board where the
    permittivity is measured rather than assumed."""
    ref = refs.REFERENCES["butterstick"]
    if not refs.is_fetched(ref):
        pytest.skip("butterstick is not fetched")
    ers = delay.read_epsilon_r(refs.board_path(ref))
    assert ers and all(e == pytest.approx(4.5) for e in ers)
    board = kb.load_board(refs.board_path(ref))
    stack = delay.stackup_of(board)
    assert stack.er == pytest.approx(4.5)
    assert "board's stackup" in stack.source


def test_a_board_without_a_stackup_says_so_rather_than_inventing_a_number():
    ref = refs.REFERENCES["orangecrab-r0.2.1"]
    if not refs.is_fetched(ref):
        pytest.skip("orangecrab-r0.2.1 is not fetched")
    assert delay.read_epsilon_r(refs.board_path(ref)) == []
    stack = delay.stackup_of(kb.load_board(refs.board_path(ref)))
    assert stack.er == delay.DEFAULT_ER
    assert "default" in stack.source


@pytest.mark.parametrize("key", ["orangecrab-r0.2.1", "logicbone", "butterstick"])
def test_every_path_records_where_its_copper_lies_and_the_split_is_the_whole_path(key):
    """The extension D47 asked for: ``NetDesign.paths`` records the length on each layer, and those lengths are
    the path, not a sample of it."""
    from waffle_eda.bench import bus_design as bd

    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} is not fetched")
    d = bd.measure_board(kb.load_board(refs.board_path(ref)), ref)
    seen = 0
    for net, nd in d["nets"].items():
        for pad, p in (nd.get("paths") or {}).items():
            assert "per_layer_mm" in p, f"{net} {pad}"
            assert sum(p["per_layer_mm"].values()) == pytest.approx(p["length_mm"], abs=0.02), f"{net} {pad}"
            assert set(p["per_layer_mm"]) == set(p["layers"]), f"{net} {pad}"
            seen += 1
    assert seen > 0


def test_orangecrab_matches_its_data_lanes_in_copper_and_not_in_delay():
    """The finding of D48, as a regression test: OrangeCrab's lane 0 is inside Lattice's length rule at 0.98 mm
    and outside ISSI's delay rule, because it matched length across two kinds of layer. If a change to the
    measurement makes these agree again, one of them has stopped being computed."""
    from waffle_eda.bench import bus_design as bd

    ref = refs.REFERENCES["orangecrab-r0.2.1"]
    if not refs.is_fetched(ref):
        pytest.skip("orangecrab-r0.2.1 is not fetched")
    board = kb.load_board(refs.board_path(ref))
    d = bd.measure_board(board, ref)
    stack = delay.stackup_of(board)
    # the anchor is the strobe pair, averaged, and the strobes are not compared against themselves: the same
    # convention scripts/segment_lengths.py prints, so the test and the report cannot drift apart silently
    members, strobes = [], []
    for net, nd in d["nets"].items():
        if nd["group"] != "lane 0":
            continue
        best = None
        for pad, p in (nd.get("paths") or {}).items():
            if pad.split(".")[0] == "U4" and (best is None or p["length_mm"] < best["length_mm"]):
                best = p
        if best is None:
            continue
        (strobes if nd["role"] == "strobe" else members).append(best)
    assert strobes and len(members) > 4
    anchor_mm = sum(p["length_mm"] for p in strobes) / len(strobes)
    anchor_ps = sum(stack.delay_ps(p["per_layer_mm"]) for p in strobes) / len(strobes)
    worst_mm = max(abs(p["length_mm"] - anchor_mm) for p in members)
    worst_ps = max(abs(stack.delay_ps(p["per_layer_mm"]) - anchor_ps) for p in members)
    assert worst_mm <= 1.27, f"copper {worst_mm:.2f} mm: Lattice's length rule was met when D48 measured it"
    assert worst_ps > 10.0, f"delay {worst_ps:.1f} ps: ISSI's delay rule was missed when D48 measured it"


def test_the_delay_of_a_path_is_never_shorter_than_light_over_its_length():
    s = delay.Stackup(er=4.5, source="test", layers={})
    per_layer = {"F.Cu": 8.0, "In2.Cu": 12.0}
    assert s.delay_ps(per_layer) > sum(per_layer.values()) / 0.299792458
    assert not math.isnan(s.equivalent_stripline_mm(per_layer))


def test_a_solder_mask_permittivity_is_not_averaged_into_the_laminate(tmp_path):
    """KiCad writes an ``epsilon_r`` for the solder mask on a board where one has been set. No signal travels
    through it, so it must not pull the model towards a number the copper never sees."""
    board_file = tmp_path / "masked.kicad_pcb"
    board_file.write_text(
        '(setup\n'
        '    (stackup\n'
        '      (layer "F.Mask" (type "Top Solder Mask") (thickness 0.01) (epsilon_r 3.3))\n'
        '      (layer "F.Cu" (type "copper") (thickness 0.035))\n'
        '      (layer "dielectric 1" (type "core") (thickness 0.13) (material "FR4") (epsilon_r 4.6))\n'
        '      (layer "B.Cu" (type "copper") (thickness 0.035))\n'
        '      (layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01) (epsilon_r 3.3))\n'
        '    )\n'
        '    (pad_to_mask_clearance 0)\n'
        '  )\n')
    assert delay.read_epsilon_r(board_file) == [4.6]


def test_a_file_with_no_stackup_reads_as_no_permittivities(tmp_path):
    board_file = tmp_path / "plain.kicad_pcb"
    board_file.write_text('(kicad_pcb (version 20240108) (setup (pad_to_mask_clearance 0)))\n')
    assert delay.read_epsilon_r(board_file) == []
