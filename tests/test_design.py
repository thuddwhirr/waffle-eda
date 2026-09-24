"""The pipeline on a design directory (`waffle_eda/design/`, `scripts/design.py`): the stage gates on the
synthetic temperature-sensor design, each on a copy of the committed design, and the pieces the stages rely
on. Stage 5's router is not run here (the jar is measured by `scripts/design.py run`, not asserted in a test);
its placer and board builder are."""
import shutil
from pathlib import Path

import pytest

from waffle_eda.design import (board_build, gate, placer, stage1_design as s1, stage2_bom as s2, stage3_schematic as s3,
                               stage4_spec as s4, stage5_layout as s5, stage6_outputs as s6)
from waffle_eda.design.directory import Design
from waffle_eda.kicad import board as kb, libs

SOURCE = Design.named("temperature-sensor")


def _need_libs():
    if libs.available():
        pytest.skip(libs.available())


@pytest.fixture
def copy(tmp_path) -> Design:
    """The committed design's inputs (design.md, bom.csv) in a scratch directory under another name."""
    root = tmp_path / "test-temperature-sensor"
    root.mkdir()
    shutil.copy(SOURCE.design_md, root / "design.md")
    shutil.copy(SOURCE.bom_csv, root / "bom.csv")
    return Design("test-temperature-sensor", root)


# --- stage 1 ------------------------------------------------------------------------------------------------
def test_the_design_document_reads_as_blocks_interfaces_nets_and_the_locked_set():
    doc = s1.load(SOURCE)
    assert not doc.problems
    assert set(doc.blocks) == {"sensor", "header", "cap", "pullup_sda", "pullup_scl", "led", "led_res", "hole1", "hole2"}
    assert doc.interfaces["host"].position.edge == "left" and doc.interfaces["indicator"].position.free
    assert set(doc.nets) == {"VCC", "GND", "SDA", "SCL", "LED_A"}
    assert ("sensor", "V+") in doc.nets["VCC"].pins and doc.unconnected == (("sensor", "ALERT"),)
    assert doc.max_size_mm == (25.0, 15.0) and doc.cost_ceiling is None and doc.fab_profile == "pcbway"
    assert set(s1.LOCKED) <= set(doc.locked)


def test_a_position_is_free_or_an_edge():
    assert s1.parse_position("free").free
    assert s1.parse_position("left edge, centred") == s1.Position("left", "centred")
    assert s1.parse_position("bottom edge, 5 mm from left") == s1.Position("bottom", "5 mm from left")
    with pytest.raises(ValueError):
        s1.parse_position("somewhere on the left")


def test_stage1_passes_and_waits_on_the_owner(copy):
    r = s1.run(copy)
    assert r.passed, r.report()
    assert {c.criterion for c in r.escalated} == {"the cost ceiling", "owner review"}
    assert (copy.reports / "stage1-design.md").read_text().startswith("# Stage 1, design: PASS")
    text = copy.design_md.read_text().replace("| owner review | pending |", "| owner review | accepted 2026-09-24 |")
    copy.design_md.write_text(text)
    assert [c.criterion for c in s1.run(copy).escalated] == ["the cost ceiling"]


def test_stage1_fails_on_an_interface_without_a_position_or_a_missing_locked_constraint(copy):
    text = copy.design_md.read_text()
    copy.design_md.write_text(text.replace("| host | header | VCC, GND, SDA, SCL | left edge, centred |",
                                           "| host | header | VCC, GND, SDA, SCL | somewhere |"))
    r = s1.run(copy)
    assert not r.passed and any("position" in c.detail for c in r.failing)
    copy.design_md.write_text(text.replace("| size | at most 25 x 15 mm |", ""))
    r = s1.run(copy)
    assert not r.passed and any("size" in c.detail for c in r.failing)


# --- stage 2 ------------------------------------------------------------------------------------------------
def test_stage2_checks_every_part_against_the_libraries_and_the_design(copy):
    _need_libs()
    s1.run(copy)
    r = s2.run(copy)
    assert r.passed, r.report()
    assert {c.criterion for c in r.escalated} == {"cost within the ceiling", "long-lead parts flagged"}
    text = copy.bom_csv.read_text()
    copy.bom_csv.write_text(text.replace("Sensor_Temperature:TMP102xxDRL", "Sensor_Temperature:TMP102xxNOPE"))
    r = s2.run(copy)
    assert not r.passed and any("symbol" in c.criterion for c in r.failing)
    copy.bom_csv.write_text(text.replace("Package_TO_SOT_SMD:SOT-563", "Package_TO_SOT_SMD:SOT-5630"))
    r = s2.run(copy)
    assert not r.passed and any("footprint" in c.criterion for c in r.failing)
    copy.bom_csv.write_text(text.replace("Device:LED,LED_SMD", "Device:R,LED_SMD"))  # no pin named K or A
    r = s2.run(copy)
    assert not r.passed and any("pin" in c.criterion for c in r.failing)


def test_a_bom_line_reads_its_price_lead_time_and_alternates():
    line = s2.BomLine("b", "U9", "x", "specific", "Device:R", "Resistor_SMD:R_0603_1608Metric", price="1.25 EUR",
                      lead_time="10 weeks", alternates="ABC (Sensor_Temperature:TMP112xxDRL)")
    assert line.price_each == 1.25 and line.lead_weeks == 10 and line.alternate_symbols == ["Sensor_Temperature:TMP112xxDRL"]
    assert s2.BomLine("b", "U9", "x", "generic", "Device:R", "R", price="unknown").price_each is None


# --- stage 3 ------------------------------------------------------------------------------------------------
def test_stage3_writes_a_schematic_whose_netlist_matches_the_design_one_to_one(copy):
    _need_libs()
    s1.run(copy)
    s2.run(copy)
    r = s3.run(copy)
    assert r.passed, r.report()
    assert r.numbers["erc errors"] == 0 and r.numbers["erc warnings"] == 0
    assert copy.schematic.is_file() and copy.netlist.is_file() and (copy.kicad_dir / "sym-lib-table").is_file()
    nets = s3.read_netlist(copy.netlist)
    assert {s3.basename(n) for n in nets if not n.startswith("unconnected-")} == {"VCC", "GND", "SDA", "SCL", "LED_A"}
    assert {c["sheet"] for c in s3.netlist_components(copy.netlist).values()} == {"sensor", "host", "indicator", "mechanical"}


def test_the_netlist_comparison_names_every_difference():
    expected = {"A": {("U1", "1"), ("R1", "1")}, "B": {("U1", "2"), ("R1", "2")}}
    assert s3.compare(expected, {"/s/A": {("U1", "1"), ("R1", "1")}, "B": {("U1", "2"), ("R1", "2")}}, set()) == []
    diffs = s3.compare(expected, {"A": {("U1", "1")}, "C": {("U1", "2"), ("R1", "2")},
                                  "unconnected-(U1-X-Pad3)": {("U1", "3")}}, set())
    assert any(d.startswith("net A:") for d in diffs) and any("net B is in the design" in d for d in diffs)
    assert any("net C is in the netlist" in d for d in diffs) and any("U1', '3') is unconnected" in d for d in diffs)


# --- stage 4 ------------------------------------------------------------------------------------------------
def test_stage4_holds_the_rules_within_the_fab_and_under_the_tightest_pad_gap(copy):
    _need_libs()
    s1.run(copy)
    s2.run(copy)
    r = s4.run(copy)
    assert r.passed, r.report()
    spec = s4.load(copy)
    assert spec["rules"]["clearance"] < spec["rules"]["min_pad_gap_mm"] <= 0.2  # the SOT-563's gap
    assert spec["rules"]["clearance"] >= 0.1016 and spec["board"]["layers"] == 2
    assert spec["outline"]["width_mm"] <= 25 and spec["outline"]["height_mm"] <= 15
    assert spec["outline"]["height_mm"] >= 11.21 + 2 * (spec["rules"]["edge_clearance"] + s4.EDGE_PART_MARGIN_MM)


def test_the_toml_writer_round_trips_through_the_reader(tmp_path):
    import tomllib
    data = {"a": {"x": 1, "y": 2.5, "s": 'say "hi"', "l": [1.0, 2.0], "b": True}}
    s4.write_toml(data, tmp_path / "t.toml", "# head\n")
    assert tomllib.loads((tmp_path / "t.toml").read_text()) == data


# --- stage 5's pieces, without the router ---------------------------------------------------------------------
@pytest.fixture
def placed():
    _need_libs()
    spec = s4.load(SOURCE)
    doc, bom = s1.load(SOURCE), s2.load(SOURCE)
    board, fps = board_build.build(spec, SOURCE.netlist)
    p = placer.Placer(board, fps, board_build.outline_rect(spec), spec["rules"]["edge_clearance"],
                      s5.fixed_edges(doc, bom), seed=0)
    return spec, board, p, p.run()


def test_the_board_is_built_from_the_netlist_with_every_pad_on_its_net():
    _need_libs()
    board, fps = board_build.build(s4.load(SOURCE), SOURCE.netlist)
    assert set(fps) == {"U1", "J1", "C1", "R1", "R2", "R3", "D1", "H1", "H2"}
    nets = {n for n in kb.net_names(board) if n}
    assert {s3.basename(n) for n in nets} == {"VCC", "GND", "SDA", "SCL", "LED_A"}
    pads = {(fp.GetReference(), pad.GetNumber()): pad.GetNetname() for fp in board.GetFootprints() for pad in fp.Pads()}
    assert pads[("U1", "5")] == "VCC" and pads[("U1", "3")] == "" and pads[("J1", "2")] == "GND"
    assert kb.track_segments(board) == [] and len([d for d in board.GetDrawings()]) == 8  # four sides, four arcs


def test_the_placer_keeps_the_interface_on_its_edge_and_every_part_apart_inside_the_outline(placed):
    spec, board, p, result = placed
    assert result["overlaps"] == []
    x0, y0, x1, y1 = result["outline"]
    for part in p.parts.values():
        l, t, r, b = part.box()
        assert l >= x0 + spec["rules"]["edge_clearance"] - 1e-6 and r <= x1 - spec["rules"]["edge_clearance"] + 1e-6
        assert t >= y0 + spec["rules"]["edge_clearance"] - 1e-6 and b <= y1 - spec["rules"]["edge_clearance"] + 1e-6
    j1 = p.parts["J1"].box()
    assert j1[0] - x0 < spec["rules"]["edge_clearance"] + placer.EDGE_PART_MARGIN_MM + 0.01  # on the left edge
    assert abs((j1[1] + j1[3]) / 2 - (y0 + y1) / 2) < 0.6  # centred along it
    parts = list(p.parts.values())
    for i, a in enumerate(parts):
        for b_ in parts[i + 1:]:
            assert not placer._overlap(a.box(), b_.box(), placer.KEEP_APART_MM - 0.01), (a.ref, b_.ref)
    assert result["decoupling"] == [("C1", "U1")]
    for ref in ("H1", "H2"):  # the holes sit in corners
        l, t, r, b = p.parts[ref].box()
        assert min(abs(l - x0), abs(x1 - r)) < 1.0 and min(abs(t - y0), abs(y1 - b)) < 1.0


def test_the_placer_is_deterministic_and_pulls_the_outline_in(placed):
    spec, board, p, result = placed
    again_board, again_fps = board_build.build(spec, SOURCE.netlist)
    doc, bom = s1.load(SOURCE), s2.load(SOURCE)
    q = placer.Placer(again_board, again_fps, board_build.outline_rect(spec), spec["rules"]["edge_clearance"],
                      s5.fixed_edges(doc, bom), seed=0)
    assert q.run()["positions"] == result["positions"]
    ox0, oy0, ox1, oy1 = board_build.outline_rect(spec)
    x0, y0, x1, y1 = result["outline"]
    assert result["compacted"] and (x1 - x0) * (y1 - y0) < (ox1 - ox0) * (oy1 - oy0)
    other = placer.Placer(*board_build.build(spec, SOURCE.netlist), board_build.outline_rect(spec),
                          spec["rules"]["edge_clearance"], s5.fixed_edges(doc, bom), seed=1)
    assert other.run()["positions"] != result["positions"]  # the closure loop's next attempt is a different one


def test_the_reference_texts_land_beside_their_parts_or_are_hidden(placed):
    spec, board, p, result = placed
    for part in p.parts.values():
        ref = part.fp.Reference()
        if part.ref in result["references_hidden"]:
            assert not ref.IsVisible()
            continue
        bb = ref.GetBoundingBox()
        box = (kb.mm(bb.GetLeft()), kb.mm(bb.GetTop()), kb.mm(bb.GetRight()), kb.mm(bb.GetBottom()))
        for other in p.parts.values():
            assert not placer._overlap(box, other.box(), -0.05), (part.ref, other.ref)


def test_the_rules_and_pours_stage5_hands_the_router_come_from_the_spec():
    spec = s4.load(SOURCE)
    rules = s5.rules_for(spec, "x", 5)
    assert rules.clearance_mm == spec["rules"]["clearance"] and rules.layers == ("F.Cu", "B.Cu")
    board, _fps = board_build.build(spec, SOURCE.netlist)
    pours = s5.pours_for(spec, board)
    assert [p["layer"] for p in pours] == ["F.Cu", "B.Cu"] and all(p["net"] == "GND" for p in pours)


def test_a_failed_run_reports_the_constraint_the_evidence_and_the_changes():
    doc = s1.load(SOURCE)
    spec = s4.load(SOURCE)
    a = s5.Attempt(1, 0, (25.0, 15.0), placement={"overlaps": []}, facts={"unconnected_nets": ["SDA"], "electrical": 2,
                                                                          "by_type": {"clearance": 2}}, router_unrouted=1)
    spec["outline"]["width_mm"], spec["outline"]["height_mm"] = 25.0, 15.0
    text = s5.diagnosis([a], spec, doc)
    assert "SDA" in text and "clearance" in text and "25.0 x 15.0" in text and "host" in text


# --- stage 6's parsers on the committed outputs --------------------------------------------------------------
def test_the_committed_outputs_re_parse():
    out = SOURCE.out
    if not out.is_dir():
        pytest.skip("no outputs committed")
    gerbers = sorted((out / "gerbers").glob("*.gbr"))
    assert len(gerbers) == len(s6.GERBER_LAYERS)
    for g in gerbers:
        p = s6.parse_gerber(g)
        assert p["format"] and p["units"] and p["end"] and p["apertures"] > 0, g.name
    drills = {d.name: s6.parse_excellon(d) for d in (out / "drill").glob("*.drl")}
    assert all(d["header"] and d["metric"] and d["end"] for d in drills.values()) and len(drills) == 2
    board = kb.load_board(SOURCE.board)
    plated, non_plated = s6.board_holes(board)
    assert sum(d["hits"] for n, d in drills.items() if "NPTH" not in n) == plated
    assert sum(d["hits"] for n, d in drills.items() if "NPTH" in n) == non_plated == 2
    ipc = s6.parse_ipc356(next(out.glob("*.d356")))
    sch = {frozenset(p) for n, p in s3.read_netlist(SOURCE.netlist).items() if not (n.startswith("unconnected-") and len(p) <= 1)}
    assert {frozenset(p) for p in ipc.values()} == sch


def test_the_status_command_reads_the_gate_reports(tmp_path):
    d = Design("empty", tmp_path)
    assert "stage 1 design     not run" in d.status()
    r = gate.GateResult(1, "design")
    r.ok("a criterion")
    r.escalate("owner review", "pending")
    gate.write_report(r, d.reports)
    text = d.status()
    assert "stage 1 design     PASS" in text and "waiting on the owner:" in text and "owner review" in text
    assert gate.read_report(d.reports, 1, "design").passed
    f = gate.GateResult(2, "bom")
    f.fail("cost within the ceiling", "over")
    assert not f.passed and f.report().startswith("# Stage 2, bom: FAIL\n") and "## Failing" in f.report()
