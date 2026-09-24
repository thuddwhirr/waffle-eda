"""M4's benchmark (D49): strip every net's copper from a board and score a candidate that re-routes all of it.

The two checks that make the number trustworthy are the pair M1 used: the stripped board scores zero and the
original copper scores full marks. Everything else here guards a way that pair was quietly untrue while being
built, because each one made the do-nothing tool look better than it is.
"""
import pytest

from waffle_eda.bench import rebuild, references as refs
from waffle_eda.kicad import board as kb

# The class A ladder of D49, smallest first. The two largest are exercised by the gate rather than per test.
LADDER = ["tinkerforge-temperature", "open-book-c1", "olimex-esp32c3-devkit", "libresolar-mppt-2420"]


def _ref(key):
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} is not fetched; run scripts/fetch_references.py")
    return ref


@pytest.mark.parametrize("key", LADDER)
def test_the_original_copper_scores_full_marks(key):
    """The answer passes its own benchmark, or the benchmark is measuring something the board does not do."""
    ref = _ref(key)
    s = rebuild.score(ref, refs.board_path(ref))
    assert s.passed, s.summary()
    assert s.score == 1.0, s.summary()
    assert s.electrical == 0, s.electrical_by_type
    assert s.connected == s.nets


@pytest.mark.parametrize("key", LADDER)
def test_the_stripped_board_scores_zero(key):
    """The do-nothing tool scores zero. Anything above zero here is the benchmark crediting work nobody did."""
    ref = _ref(key)
    bare, info = rebuild.strip_all(ref, reuse=False)
    assert info["tracks"] > 0
    s = rebuild.score(ref, bare)
    assert not s.passed, s.summary()
    assert s.score == 0.0, s.summary()
    assert s.connected == 0, [n for n, v in s.per_net.items() if v["connected"]]


def test_the_problem_board_keeps_placement_and_loses_every_piece_of_copper():
    ref = _ref("tinkerforge-temperature")
    bare, info = rebuild.strip_all(ref, reuse=False)
    original = kb.load_board(refs.board_path(ref))
    stripped = kb.load_board(bare)
    assert len(list(stripped.GetFootprints())) == len(list(original.GetFootprints()))
    assert rebuild.all_nets(stripped) == rebuild.all_nets(original)
    assert kb.track_segments(stripped) == [] and kb.track_arcs(stripped) == [] and kb.vias(stripped) == []
    assert [z for z in stripped.Zones() if not z.GetIsRuleArea()] == []


def test_a_single_pad_net_is_not_something_to_route():
    """Five of `tinkerforge-temperature`'s eleven nets reach one pad. KiCad never reports them unconnected, so
    counting them would start the do-nothing tool at 0.45 instead of 0.00."""
    ref = _ref("tinkerforge-temperature")
    board = kb.load_board(refs.board_path(ref))
    assert len(rebuild.all_nets(board)) == 11
    assert len(rebuild.routable_nets(board)) == 6


def test_a_keepout_is_not_copper_and_survives_the_strip():
    """`open-book-c1` carries two rule areas inside the footprint of U3. A keepout is part of the specification
    the router is handed, so stripping it would hand the tool an easier board than the reference had."""
    ref = _ref("open-book-c1")
    bare, _info = rebuild.strip_all(ref, reuse=False)
    stripped = kb.load_board(bare)
    areas = [z for fp in stripped.GetFootprints() for z in fp.Zones() if z.GetIsRuleArea()]
    assert areas, "the rule areas of U3 were removed with the copper"


def test_the_board_outline_is_never_charged_to_the_router():
    """KiCad calls the outline's graphics ``Segment`` and ``Arc``, and ``Arc`` is also a routed copper arc. An
    Edge.Cuts item read as the router's copper made a board with no copper on it report a violation."""
    assert not rebuild._is_routed({"description": "Arc on Edge.Cuts"})
    assert not rebuild._is_routed({"description": "Segment on Edge.Cuts"})
    assert not rebuild._is_routed({"description": "Pad EP [GND] of P1 on Vorderseite"})
    assert rebuild._is_routed({"description": "Track [ALERT] on Vorderseite, length 0.4275 mm"})
    assert rebuild._is_routed({"description": "Via [GND] on Vorderseite - Rückseite"})
    assert rebuild._is_routed({"description": "Zone [GND] on Vorderseite, priority 0"})


def test_a_violation_between_two_fixed_items_is_not_the_routers():
    """The pad `EP` of `P1` sits on the board edge of `tinkerforge-temperature`. Grading that would measure the
    board's edge clearance as zero and let a candidate run track along the rim; it measures 0.5 mm instead."""
    report = {"violations": [
        {"type": "clearance", "items": [{"description": "Pad 1 [VCC] of U1"}, {"description": "Pad 2 [GND] of U1"}]},
        {"type": "clearance", "items": [{"description": "Track [VCC] on F.Cu"}, {"description": "Pad 2 [GND] of U1"}]},
    ]}
    facts = rebuild.board_facts(report)
    assert facts["electrical"] == 1
    assert facts["electrical_fixed"] == 1


def test_the_measured_edge_clearance_is_a_real_distance():
    ref = _ref("tinkerforge-temperature")
    rules = rebuild.measure_rules(ref)
    assert rules.edge_clearance_mm > 0.4, rules.summary()
    assert rules.min_track_mm > 0 and rules.clearance_mm > 0


def test_an_escaped_net_name_matches_the_name_the_drc_report_writes():
    """`open-book-c1` has `/RX{slash}SCL`, which a DRC report calls `/RX/SCL`. Comparing the two forms directly
    found the net in no unconnected list and scored it connected on a board with no copper."""
    assert kb.unescape_net("/RX{slash}SCL") == "/RX/SCL"
    assert kb.unescape_net("GND") == "GND"
    assert kb.unescape_net("A{lbrace}B{rbrace}") == "A{B}"


def test_the_rules_apply_to_the_whole_board_and_not_to_a_net_list():
    text = rebuild.rules_text({"clearance": 0.2})
    assert "(rule board" in text and "condition" not in text
    for constraint in rebuild.QUIET_CONSTRAINTS:
        assert f"(constraint {constraint} (min 0mm))" in text
    assert "edge_clearance" in rebuild.QUIET_CONSTRAINTS


def test_a_teardrop_is_the_references_routing_and_not_a_pour_to_lay():
    """`crkbd-corne-cherry` fillets its tracks with 921 teardrop zones; recorded as pours they were laid on the
    re-routed board as 921 slivers at the reference's own pad and via positions."""
    ref = _ref("crkbd-corne-cherry")
    bare, info = rebuild.strip_all(ref)
    assert info["teardrops"] == 921 and info["zones"] == 4
    assert sorted((p["net"], p["layer"]) for p in info["pours"]) == [("GND", "B.Cu"), ("GND", "F.Cu"), ("GNDR", "B.Cu"), ("GNDR", "F.Cu")]
    board = kb.load_board(bare)
    assert not any(z.IsTeardropArea() for z in board.Zones())
