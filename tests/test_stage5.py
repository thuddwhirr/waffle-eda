"""Stage 5 of class A: the baseline router behind the gate, the pours, the stitching vias and the repairs.

The gate is the measurement; these tests pin the mechanics each piece was found to need on 2026-09-23, so a
change that quietly loses one is caught in seconds rather than in a board.
"""
from dataclasses import replace

import pytest

from waffle_eda.bench import rebuild, references as refs
from waffle_eda.kicad import board as kb
from waffle_eda.route import freerouting, pours, stage5, stitch


def _ref(key):
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} is not fetched; run scripts/fetch_references.py")
    return ref


def _rules(**over):
    base = rebuild.BoardRules(reference="x", board_mtime=0.0, clearance_mm=0.2, hole_to_copper_mm=0.5,
                              edge_clearance_mm=0.5, min_track_mm=0.3, min_via_mm=0.7, min_drill_mm=0.25,
                              min_annular_mm=0.225, layers=("F.Cu", "B.Cu"), nets=1)
    return replace(base, **over)


# --- the rules handed to the router -----------------------------------------------------------------------------
def test_a_via_needs_more_clearance_than_a_track_when_the_hole_rule_exceeds_its_ring():
    """Freerouting has one clearance and no hole-to-copper rule. With a 0.5 mm hole rule and a 0.225 mm ring, a
    via must keep 0.275 mm from other copper, or KiCad reports every via as a hole clearance violation."""
    ref = _ref("tinkerforge-temperature")
    board = kb.load_board(rebuild.strip_all(ref)[0])
    dsn = freerouting.dsn_rules(board, _rules())
    assert dsn.clearance_mm == 0.2
    assert dsn.via_clearance_mm == pytest.approx(0.275, abs=1e-6)
    assert dsn.hole_keepout_mm == pytest.approx(0.3, abs=1e-6)
    pairs = freerouting.type_clearances(dsn)
    assert pairs[("via", "wire")] == dsn.via_clearance_mm and ("via", "area") in pairs
    # a hole rule the ring already satisfies asks nothing extra
    loose = freerouting.dsn_rules(board, _rules(hole_to_copper_mm=0.3))
    assert loose.via_clearance_mm == loose.clearance_mm and freerouting.type_clearances(loose) == {}


def test_the_dsn_rewrite_adds_the_via_clearances_once_and_drops_the_class_clearance():
    text = ("(pcb x\n  (structure\n    (layer F.Cu\n      (type signal)\n    )\n    (rule\n      (width 300)\n"
            "      (clearance 200)\n      (clearance 50 (type smd_smd))\n    )\n  )\n  (network\n"
            "    (class kicad_default A B\n      (rule\n        (width 300)\n        (clearance 200)\n      )\n    )\n  )\n)\n")
    dsn = freerouting.DsnRules(clearance_mm=0.2, via_clearance_mm=0.275, pin_clearance_mm=0.2, hole_keepout_mm=0.3,
                               width_mm=0.3, via_mm=0.7, drill_mm=0.25)
    once = freerouting.rewrite_dsn(text, dsn)
    assert once.count("(type via_wire)") == 1 and "(clearance 275 (type via_via))" in once
    assert "(type smd_smd)" in once
    assert once.count("(clearance 200)") == 1, "the class rule's clearance line must go, the structure's stay"
    assert freerouting.rewrite_dsn(once, dsn) == once


def test_duplicate_references_are_made_unique_for_the_round_trip_and_restored():
    """The exporter refuses a board on which two footprints share a reference; the smoke-test board has two
    `VAL` and two `Fiducial_Mark`."""
    ref = _ref("tinkerforge-temperature")
    board = kb.load_board(rebuild.strip_all(ref)[0])
    before = sorted(fp.GetReference() for fp in board.GetFootprints())
    assert len(before) != len(set(before))
    renamed = freerouting.unique_references(board)
    after = [fp.GetReference() for fp in board.GetFootprints()]
    assert len(after) == len(set(after)) and all(after)
    assert len(renamed) == 4
    freerouting.restore_references(board, renamed)
    assert sorted(fp.GetReference() for fp in board.GetFootprints()) == before


# --- pours -------------------------------------------------------------------------------------------------------
def test_the_pour_specification_is_the_references_own_zones_without_teardrops():
    """`olimex-esp32c3-devkit` stores 154 teardrops as zones next to its two ground pours."""
    tf = _ref("tinkerforge-temperature")
    spec = rebuild.pour_spec(tf)
    assert [(p.net, p.layer) for p in spec] == [("GND", "Rückseite"), ("GND", "Vorderseite")]
    assert all(len(p.outline_mm) >= 4 for p in spec)
    esp = _ref("olimex-esp32c3-devkit")
    assert [(p.net, p.layer) for p in rebuild.pour_spec(esp)] == [("GND", "B.Cu"), ("GND", "F.Cu")]


def test_a_pour_is_recreated_on_the_bare_board_at_or_above_the_measured_rules():
    ref = _ref("tinkerforge-temperature")
    board = kb.load_board(rebuild.strip_all(ref)[0])
    assert [z for z in board.Zones() if not z.GetIsRuleArea()] == []
    zones = pours.add_pours(board, rebuild.pour_spec(ref), clearance_floor_mm=0.3, min_width_floor_mm=0.3)
    assert len(zones) == 2
    assert {z.GetNetname() for z in zones} == {"GND"}
    assert all(kb.mm(z.GetLocalClearance()) >= 0.3 and kb.mm(z.GetMinThickness()) >= 0.3 for z in zones)
    assert pours.pours_from_json(pours.pours_to_json(rebuild.pour_spec(ref))) == rebuild.pour_spec(ref)


# --- stitching and the repairs ------------------------------------------------------------------------------------
def test_a_stitching_via_is_found_next_to_a_ground_pad_on_the_bare_board():
    ref = _ref("tinkerforge-temperature")
    board = kb.load_board(rebuild.strip_all(ref)[0])
    from waffle_eda.route.obstacles import Obstacles
    rules = stitch.ViaRules.from_board_rules(rebuild.measure_rules(ref))
    laid = stitch.stitch_poured_pads(board, Obstacles(board), {"GND"}, rules)
    assert laid["no_site"] == []
    assert "U2.2" in laid["stitched"] and "C1.2" in laid["stitched"]
    assert len(kb.vias(board)) == len(laid["stitched"])
    assert all(kb.via_diameter_mm(v) == pytest.approx(rules.via_mm, abs=1e-4) for v in kb.vias(board))


def test_an_unconnected_pad_is_read_from_the_drc_report_by_reference_number_and_net():
    report = {"unconnected_items": [
        {"items": [{"description": "Pad 2 [GND] of U2 on Vorderseite"}, {"description": "Zone [GND] on Vorderseite, priority 0"}]},
        {"items": [{"description": "Zone [GND] on Vorderseite, priority 0"}, {"description": "Pad 2 [GND] of U2 on Vorderseite"}]},
        {"items": [{"description": "Pad 1 [/RX/SCL] of U1 on F.Cu"}, {"description": "Track [/RX/SCL] on F.Cu, length 1.0 mm"}]},
    ]}
    assert stage5.unconnected_pads(report) == [("U1", "1", "/RX/SCL"), ("U2", "2", "GND")]


def test_the_tool_is_found_or_the_reason_is_named():
    jar, java = freerouting.check()  # the environment provides both (scripts/check_env.py, the session hook)
    assert jar.is_file() and freerouting._java_major(java) >= freerouting.JAVA_MAJOR


# --- the smoke test through the whole stage -----------------------------------------------------------------------
def test_the_smoke_test_board_routes_from_placement_to_a_clean_board(tmp_path):
    """The class A gate's first rung, kept under half a minute: every net connected, zero violations under the
    measured rules, with the pours, the stitching vias and the necks repaired."""
    ref = _ref("tinkerforge-temperature")
    freerouting.check()
    rules = rebuild.measure_rules(ref)
    board = kb.load_board(rebuild.strip_all(ref)[0])
    result = stage5.route(board, rules, rebuild.pour_spec(ref), tmp_path / "stage5")
    assert result.ok, result.summary()
    s = rebuild.score(ref, tmp_path / "stage5" / "routed.kicad_pcb", work_dir=tmp_path / "score")
    assert s.passed and s.score == 1.0, s.summary()
    assert (tmp_path / "stage5" / "attempts.json").is_file()
    assert (tmp_path / "stage5" / "freerouting" / "board.ses").is_file()
