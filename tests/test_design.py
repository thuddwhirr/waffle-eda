"""The design directory and stages 1 to 4 of the temperature-sensor design (plan.md, milestone A): the
documents' gates, the schematic generator, ERC and the netlist comparison. Stages 5 and 6 are exercised by
`scripts/design.py` because they take minutes; their mechanics are tested in `test_stage5.py`."""
from pathlib import Path

import pytest

from waffle_eda.design import board as board_mod, pipeline
from waffle_eda.sch import schematic, sexp

DESIGN = "temperature-sensor"


def _dir() -> Path:
    d = pipeline.design_dir(DESIGN)
    if not d.is_dir():
        pytest.skip("the temperature-sensor design directory is missing")
    return d


def test_the_sexp_round_trip_keeps_symbols_strings_and_numbers():
    text = '(kicad_sch (version 20250114) (property "Value" "100nF" (at 1.27 -2.54 0)) (uuid "a b"))'
    doc = sexp.loads(text)
    assert doc[0] == "kicad_sch" and isinstance(doc[0], sexp.Sym)
    assert sexp.find(doc, "property")[2] == "100nF"
    assert sexp.loads(sexp.dumps(doc)) == doc


def test_the_connectivity_specification_is_read_with_its_power_nets():
    conn = schematic.read_connectivity(_dir() / "connectivity.toml")
    assert conn.power_nets == {"+3V3", "GND"}
    assert ("U1", "3") in conn.no_connect
    assert set(conn.nets["SDA"]) == {("J1", "3"), ("U1", "6"), ("R2", "2")}


def test_the_specification_checker_names_what_cannot_be_drawn():
    d = _dir()
    conn = schematic.read_connectivity(d / "connectivity.toml")
    parts = schematic.load_parts(schematic.read_bom(d / "bom.csv"))
    assert schematic.check_specification(parts, conn) == []
    conn.nets["SDA"].append(("U1", "1"))  # SCL's pin on SDA as well
    conn.nets["LONELY"] = [("R1", "2")]
    errors = schematic.check_specification(parts, conn)
    assert any("U1.1 is on several nets" in e for e in errors)
    assert any("LONELY has one pin" in e for e in errors)


def test_the_netlist_comparison_is_one_to_one():
    conn = schematic.read_connectivity(_dir() / "connectivity.toml")
    netlist = {net: set(pins) for net, pins in conn.nets.items()}
    assert schematic.compare(netlist, conn) == []
    netlist["SDA"].discard(("R2", "2"))
    netlist["EXTRA"] = {("R1", "1"), ("R1", "2")}
    diffs = schematic.compare(netlist, conn)
    assert any("SDA" in x and "R2" in x for x in diffs)
    assert any("EXTRA" in x for x in diffs)


def test_stage_1_2_and_4_gates_pass_on_the_design_and_ask_about_price():
    d = _dir()
    r1 = pipeline.stage1(d)
    assert r1.passed, r1.summary()
    assert r1.numbers["locked constraints"] >= 5
    r2 = pipeline.stage2(d)
    assert r2.passed, r2.summary()
    assert any("prices unknown" in a for a in r2.asks), "unknown prices must escalate, not pass silently"
    r4 = pipeline.stage4(d)
    assert r4.passed, r4.summary()
    assert r4.numbers["rules checked"] == 7 and any("price" in a for a in r4.asks)


def test_stage_3_draws_the_schematic_erc_clean_with_the_netlist_matching(tmp_path):
    d = _dir()
    r3 = pipeline.stage3(d)
    assert r3.passed, r3.summary()
    assert r3.numbers["erc errors"] == 0 and r3.numbers["nets"] == 5
    assert (d / f"{DESIGN}.kicad_sch").is_file() and (d / "reports" / "netlist.net").is_file()


def test_a_missing_locked_constraint_fails_stage_1(tmp_path):
    d = _dir()
    copy = tmp_path / DESIGN
    copy.mkdir()
    text = (d / "design.md").read_text().replace("| Feature set |", "| Features (unlocked) |")
    (copy / "design.md").write_text(text)
    (copy / "connectivity.toml").write_text((d / "connectivity.toml").read_text())
    r = pipeline.stage1(copy)
    assert not r.passed and any("Feature set" in f for f in r.findings)


def test_the_specification_stays_inside_the_fab_and_the_locked_size():
    spec = board_mod.Spec.read(_dir() / "spec.toml")
    rules = spec.board_rules(DESIGN)
    assert rules.min_track_mm == spec.track_mm and rules.layers == ("F.Cu", "B.Cu")
    assert [(p.net, p.layer) for p in spec.pour_spec()] == [("GND", "F.Cu"), ("GND", "B.Cu")]


def test_the_placer_keeps_the_header_on_the_west_edge_and_every_part_inside():
    d = _dir()
    if not (d / "reports" / "netlist.net").is_file():
        pipeline.stage3(d)
    board, spec, placement = board_mod.build(d, DESIGN)
    assert placement["J1"]["x_mm"] < spec.width_mm / 4
    for fp in board.GetFootprints():
        box = board_mod._box(fp)
        assert board_mod._inside(box, spec), (fp.GetReference(), box)
    assert placement["D1"]["x_mm"] >= spec.width_mm / 2  # the stated region
    again = board_mod.build(d, DESIGN)[2]
    assert again == placement, "placement must be deterministic (D25)"
