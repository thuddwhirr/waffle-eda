"""DRC under a bus-scoped rules file (harness.rules_file): the constraints bind only pairs with a bus net and every
other item is held to nothing, so the bus counts stay far below KiCad's per-type reporting cap and are exact."""
import pytest

from waffle_eda.bench import harness, synthetic


def test_rules_file_text():
    text = harness.rules_file({"BUS01", "BUS00"}, {"clearance": 0.1, "track_width": 0.089})
    assert text.startswith("(version 1)\n(rule quiet\n")
    for c in harness.RULE_CONSTRAINTS:
        assert f"(constraint {c} (min 0mm))" in text
    assert "A.NetName == 'BUS00' || B.NetName == 'BUS00' || A.NetName == 'BUS01' || B.NetName == 'BUS01'" in text
    assert "(constraint clearance (min 0.1000mm))" in text and "(constraint track_width (min 0.0890mm))" in text
    assert "(rule bus" not in harness.rules_file(set(), {"clearance": 0.1})
    with pytest.raises(ValueError):
        harness.rules_file({"it's"}, {"clearance": 0.1})


def test_scoped_rules_bind_only_the_bus(tmp_path):
    case = synthetic.CASES["pair-6x6-straight"]
    path = tmp_path / "pair.kicad_pcb"
    manifest = synthetic.make_bga_pair(case, path)
    bus = set(manifest["bus"])
    one = {sorted(bus)[0]}
    # an impossible clearance on one net: violations, and every one of them touches that net
    facts = harness.drc_with_rules(path, harness.rules_file(one, {"clearance": 5.0}), tmp_path / "one", bus, "one")
    assert facts["electrical_bus_by_type"].get("clearance", 0) > 0
    only = harness.drc_with_rules(path, harness.rules_file(one, {"clearance": 5.0}), tmp_path / "one2", one, "one2")
    assert only["electrical_bus"] == facts["electrical_bus"]
    # the same clearance scoped to nothing: the quiet rule alone, and no rule-driven violation anywhere
    quiet = harness.drc_with_rules(path, harness.rules_file(set(), {"clearance": 5.0}), tmp_path / "quiet", bus, "q")
    assert quiet["electrical_bus"] == 0 and quiet["electrical_total"] == 0
