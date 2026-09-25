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
# Class B, in the order the plan lists its references (D75, reordered by D84): the benchmark was only asserted
# on class A, so its sanity pair is the first thing class B measures (docs/plan.md, "B. A class B board").
LADDER_B = ["upduino-v3.01", "pico-ice-rev3", "sensor-watch-c1", "tinkerforge-master-v3.2", "buspirate5-rev10",
            "olimex-esp32-poe-m1", "tinytapeout-demo", "mch2022-badge", "fomu-pvt"]
# The class B boards cost minutes each here (one DRC of mch2022-badge takes 158 s, D77), so their cases carry the
# `bench` marker: run by default, left out of a quick run with `pytest -m "not parked and not bench"` (a
# `-m` on the command line replaces the one in pyproject, so the parked marker is named again).
SANITY = LADDER + [pytest.param(k, marks=pytest.mark.bench) for k in LADDER_B]


def _ref(key):
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} is not fetched; run scripts/fetch_references.py")
    return ref


@pytest.mark.parametrize("key", SANITY)
def test_the_original_copper_scores_full_marks(key):
    """The answer passes its own benchmark, or the benchmark is measuring something the board does not do.
    The answer is the reference as the benchmark reads it (`answer_board`, D76): its zones refilled by KiCad 9
    (a legacy fill in the file can sit closer to a hole than the refilled one, D58) and its orphan pads
    adopted."""
    ref = _ref(key)
    answer, _info = rebuild.answer_board(ref)
    s = rebuild.score(ref, answer)
    assert s.passed, s.summary()
    assert s.score == 1.0, s.summary()
    assert s.electrical == 0, s.electrical_by_type
    assert s.connected == s.nets


@pytest.mark.parametrize("key", SANITY)
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


def test_a_no_net_item_the_reference_shorts_to_one_net_is_adopted_or_paired():
    """D76: `upduino-v3.01` leaves its QFN's exposed pad with no net while GND vias stitch it (24 shorts and 36
    clearances on the original); `sensor-watch-c1` draws a buzzer contact as a no-net polygon its track runs
    over. A pad takes the net; a polygon, which cannot, is paired and the pairing forgiven; an item two nets
    reach (a solder jumper) is neither."""
    report = {"violations": [
        {"type": "shorting_items", "description": "Items shorting two nets (nets  and GND)",
         "items": [{"description": "Pad 49 [<no net>] of U3 on F.Cu"}, {"description": "Track [GND] on F.Cu, length 1.2 mm"}]},
        {"type": "hole_clearance", "description": "Hole clearance violation (rule 'quiet' clearance 0 mm; actual < 0)",
         "items": [{"description": "Pad 49 [<no net>] of U3 on F.Cu"}, {"description": "Via [GND] on F.Cu - B.Cu"}]},
        {"type": "clearance", "description": "Clearance violation (rule 'board' clearance 0.1 mm; actual 0.0500 mm)",
         "items": [{"description": "Pad 49 [<no net>] of U3 on F.Cu"}, {"description": "Track [SDA] on F.Cu, length 1 mm"}]},
        {"type": "shorting_items", "description": "Items shorting two nets (nets  and /BUZZER_HV)",
         "items": [{"description": "Polygon [<no net>] of U$2 on B.Cu"}, {"description": "Track [/BUZZER_HV] on B.Cu, length 1.9 mm"}]},
        {"type": "shorting_items", "description": "Items shorting two nets (nets +3V3 and )",
         "items": [{"description": "Pad 1 [+3V3] of SJ20 on F.Cu"}, {"description": "Polygon [<no net>] of SJ20 on F.Cu"}]},
        {"type": "shorting_items", "description": "Items shorting two nets (nets X and )",
         "items": [{"description": "Pad 2 [X] of SJ20 on F.Cu"}, {"description": "Polygon [<no net>] of SJ20 on F.Cu"}]},
    ]}
    shorts = rebuild._orphan_shorts(report)
    assert shorts == {"Pad 49 [<no net>] of U3 on F.Cu": {"GND"}, "Polygon [<no net>] of U$2 on B.Cu": {"/BUZZER_HV"},
                      "Polygon [<no net>] of SJ20 on F.Cu": {"+3V3", "X"}}
    import pcbnew
    board = pcbnew.BOARD()
    gnd = pcbnew.NETINFO_ITEM(board, "GND")
    board.Add(gnd)
    fp = pcbnew.FOOTPRINT(board)
    fp.SetReference("U3")
    for number in ("48", "49"):
        pad = pcbnew.PAD(fp)
        pad.SetNumber(number)
        fp.Add(pad)
    board.Add(fp)
    pads, graphics = rebuild.adopt_orphans(board, shorts)
    assert pads == {"U3.49": "GND"} and graphics == {"Polygon [<no net>] of U$2 on B.Cu": "/BUZZER_HV"}
    assert {p.GetNumber(): p.GetNetname() for p in fp.Pads()} == {"48": "", "49": "GND"}
    forgiven = graphics
    short = report["violations"][3]
    assert rebuild._forgiven(short, forgiven) and not rebuild._forgiven(report["violations"][0], forgiven)
    facts = rebuild.board_facts({"violations": [short, report["violations"][0]]}, forgiven)
    assert facts["electrical"] == 1  # the pad's short is counted, the paired polygon's is not
