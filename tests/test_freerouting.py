"""Stage 5's baseline for class A: the Freerouting wrapper (`route/freerouting.py`, D56, D57).

Each test here guards a way the wrapper was found wrong by running it. None of them needs the jar: what the jar
does is measured by the class A gate, and its numbers are in the decisions log, not asserted here.
"""
import pytest

from waffle_eda.bench import rebuild, references as refs
from waffle_eda.kicad import board as kb
from waffle_eda.route import freerouting as fr

DSN = """(pcb "x"
  (resolution um 10)
  (structure
    (layer F.Cu
      (type signal)
    )
    (boundary
      (path pcb 0  0 0  1000 0  1000 1000  0 1000  0 0)
    )
    (via "Via[0-1]_701:249_um")
    (rule
      (width 299.7)
      (clearance 190)
      (clearance 47.5 (type smd_smd))
    )
  )
  (placement
  )
  (network
    (class kicad_default GND
      (circuit
        (use_via "Via[0-1]_701:249_um")
      )
      (rule
        (width 299.7)
        (clearance 190)
      )
    )
  )
)
"""


def _rules(**over):
    base = dict(reference="x", board_mtime=0.0, clearance_mm=0.1972, hole_to_copper_mm=0.4964,
                edge_clearance_mm=0.5479, min_track_mm=0.2997, min_via_mm=0.701, min_drill_mm=0.2489,
                min_annular_mm=0.226, layers=("F.Cu", "B.Cu"), nets=11)
    base.update(over)
    return rebuild.BoardRules(**base)


def _ref(key):
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} is not fetched; run scripts/fetch_references.py")
    return ref


# --- the board before export ----------------------------------------------------------------------------------
def test_duplicate_references_are_renamed_for_the_export_and_restored_after_it():
    """`pcbnew.ExportSpecctraDSN` returns False and writes nothing when two footprints share a reference (five of
    the six class A references have logos or fiducials that do). The rename is what makes the export possible."""
    import pcbnew
    board = pcbnew.BOARD()
    for ref in ("U1", "REF**", "REF**", "G***", "G***", "G***"):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        board.Add(fp)
    renamed = fr.unique_references(board)
    assert len(renamed) == 3
    names = sorted(fp.GetReference() for fp in board.GetFootprints())
    assert len(set(names)) == 6, names
    assert "U1" in names and "REF**" in names and "REF**~2" in names
    fr.restore_references(board, renamed)
    assert sorted(fp.GetReference() for fp in board.GetFootprints()) == ["G***", "G***", "G***", "REF**", "REF**", "U1"]


def test_the_export_itself_needs_the_rename():
    """The pitfall as pcbnew shows it: the same board exports once its references are unique."""
    import pcbnew
    ref = _ref("tinkerforge-temperature")
    bare, _ = rebuild.strip_all(ref)
    out = rebuild.harness.bench_dir() / "export-probe.dsn"
    board = kb.load_board(bare)
    if out.is_file():
        out.unlink()
    assert not pcbnew.ExportSpecctraDSN(board, str(out)) and not out.is_file()
    assert fr.unique_references(board)
    assert pcbnew.ExportSpecctraDSN(board, str(out)) and out.is_file()


# --- the rules handed to the router ---------------------------------------------------------------------------
def test_the_measured_rules_become_the_routers_rules():
    d = fr.dsn_rules(_rules(), pin_ring_mm=None)
    assert d.width_mm == 0.2997  # exactly the rule: the router keeps the width it is given
    assert d.clearance_mm == 0.1972  # exactly the rule; only the wire-to-SMD-pad clearance carries the slack
    assert d.smd_clearance_mm == round(0.1972 - fr.CLEARANCE_SLACK_MM, 4)
    assert fr.dsn_rules(_rules(), None, slack_all=True).clearance_mm == round(0.1972 - fr.CLEARANCE_SLACK_MM, 4)
    assert fr.dsn_rules(_rules(), None, slack_all=True).smd_clearance_mm is None
    assert d.via_drill_mm == 0.249  # rounded up to a whole micrometre: the session file truncates to one
    assert d.via_diameter_mm == 0.701
    # hole-to-copper for a via: the rule less the via's ring, so copper at that clearance from the via's pad is
    # at the rule's distance from its hole
    assert d.via_clearance_mm == round(0.4964 - (0.701 - 0.249) / 2, 4)
    assert d.pin_clearance_mm is None


def test_a_hole_rule_the_ordinary_clearance_already_meets_needs_no_typed_rule():
    d = fr.dsn_rules(_rules(hole_to_copper_mm=0.3), pin_ring_mm=0.3)
    assert d.via_clearance_mm is None and d.pin_clearance_mm is None


def test_plated_pins_get_their_own_typed_clearance_from_the_smallest_ring():
    d = fr.dsn_rules(_rules(), pin_ring_mm=0.1)
    assert d.pin_clearance_mm == round(0.4964 - 0.1, 4)


def test_typed_clearances_go_into_the_structures_rule_block_only():
    d = fr.dsn_rules(_rules(), pin_ring_mm=0.1)
    text = fr.typed_clearances(DSN, d)
    structure = text[text.index("(structure"):text.index("(placement")]
    network = text[text.index("(network"):]
    for t in fr.VIA_TYPES + fr.PIN_TYPES + fr.SMD_TYPES:
        assert f"(type {t})" in structure
        assert f"(type {t})" not in network
    assert structure.index("(clearance 190)") < structure.index("(type via_via)") < structure.index("(type smd_smd)")


def test_the_via_cost_goes_into_the_settings_file(tmp_path):
    import json
    path = fr.settings_json(tmp_path, threads=1, passes=30)
    cfg = json.loads(path.read_text())
    assert cfg["router"]["scoring"]["via_costs"] == fr.VIA_COSTS
    assert cfg["router"]["fanout"]["enabled"] is False
    assert cfg["version"] == fr.VERSION and cfg["profile"]["id"]
    assert cfg["usage_and_diagnostic_data"]["disable_analytics"] is True


# --- the log ---------------------------------------------------------------------------------------------------
LOG = """
2026-09-23 22:09:19.307 INFO   [X] Auto-routing pass #1 on board 'a' was completed in 1.45 seconds with score 610.52 (7 unrouted and 2 violations), using 0.64 CPU seconds
2026-09-23 22:09:20.354 INFO   [X] Auto-routing pass #2 on board 'b' was completed in 0.97 seconds with score 557.89 (8 unrouted and 2 violations), using 1.05 CPU seconds
2026-09-23 22:09:33.171 INFO   [X] Auto-routing stage completed: started with 19 unrouted nets, completed in 15.45 seconds, final score: 610.52 (7 unrouted and 2 violations), using 7.63 total CPU seconds
2026-09-23 22:09:40.000 INFO   [X] Optimization stage completed: started with score 610.52 (7 unrouted and 2 violations), completed in 18.17 seconds, final score: 620.00 (0 unrouted and 1 violations), using 4 CPU seconds
"""


def test_the_routers_own_numbers_come_from_its_last_stage():
    facts = fr.parse_log(LOG)
    assert facts == {"passes": 2, "unrouted": 0, "violations": 1}
    assert fr.parse_log("") == {"passes": 0, "unrouted": None, "violations": None}


# --- escape stubs (D51/D52) ----------------------------------------------------------------------------------
def test_stubs_are_laid_only_where_the_row_leaves_no_corridor():
    """On the smoke test only the SOT-563 (0.200 mm between pads) is that tight under its measured rules; the
    TSSOP-8 (0.251) and the connector (0.4) leave room. End pads turn away, the middle pad goes straight."""
    ref = _ref("tinkerforge-temperature")
    bare, _ = rebuild.strip_all(ref)
    board = kb.load_board(bare)
    stubs = fr.escape_stubs(board, width_mm=0.2997, clearance_mm=0.1972)
    assert sorted(s.net for s in stubs) == sorted(["ALERT", "GND", "SCL", "SDA", "VCC", "Net-(P1-Pad6)"])
    u2 = board.FindFootprintByReference("U2")
    pad_at = {(round(kb.mm(p.GetPosition().x), 3), round(kb.mm(p.GetPosition().y), 3)): p.GetNumber() for p in u2.Pads()}
    for s in stubs:
        x0, y0 = s.points[0]
        assert (round(x0, 3), round(y0, 3)) in pad_at, s
        assert len(s.points) == (2 if pad_at[(round(x0, 3), round(y0, 3))] in ("2", "5") else 3), s
        assert s.width_mm == 0.2997
    made = fr.lay_stubs(board, stubs)
    assert len(made) == sum(len(s.points) - 1 for s in stubs)
    assert all(kb.mm(t.GetWidth()) == pytest.approx(0.2997) for t in made)


def test_a_one_pad_net_gets_no_stub():
    ref = _ref("tinkerforge-temperature")
    bare, _ = rebuild.strip_all(ref)
    board = kb.load_board(bare)
    stubs = fr.escape_stubs(board, width_mm=0.2997, clearance_mm=0.1972, nets={"GND"})
    assert [s.net for s in stubs] == ["GND"]


def test_fixing_the_wires_types_every_exported_wire():
    text = "(wiring\n  (wire (path F.Cu 299.7 0 0 1 1)(net GND)(type route))\n)"
    assert fr.fix_wires(text).count("(type fix)") == 1 and "(type route)" not in fr.fix_wires(text)


# --- availability ---------------------------------------------------------------------------------------------
def test_a_missing_jar_is_named_with_the_script_that_fetches_it(monkeypatch, tmp_path):
    monkeypatch.setenv("WAFFLE_FREEROUTING_JAR", str(tmp_path / "none.jar"))
    reason = fr.available()
    assert reason and "fetch_tools" in reason and "none.jar" in reason


def test_an_old_java_is_named_with_its_version(monkeypatch, tmp_path):
    jar = tmp_path / "freerouting.jar"
    jar.write_bytes(b"")
    monkeypatch.setenv("WAFFLE_FREEROUTING_JAR", str(jar))
    monkeypatch.setattr(fr, "java_major", lambda _java: 21)
    reason = fr.available()
    assert reason and "21" in reason and str(fr.JAVA_MAJOR) in reason
