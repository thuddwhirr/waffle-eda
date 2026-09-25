"""Stage 5's baseline for class A: the Freerouting wrapper (`route/freerouting.py`, D56, D57).

Each test here guards a way the wrapper was found wrong by running it. None of them needs the jar: what the jar
does is measured by the class A gate, and its numbers are in the decisions log, not asserted here.
"""
import pcbnew
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
    assert d.clearance_mm == round(0.1972 - fr.CLEARANCE_SLACK_MM, 4)  # the slack the repair takes back
    assert d.smd_clearance_mm is None
    scoped = fr.dsn_rules(_rules(), None, slack_all=False)
    assert scoped.clearance_mm == 0.1972 and scoped.smd_clearance_mm == round(0.1972 - fr.CLEARANCE_SLACK_MM, 4)
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
    d = fr.dsn_rules(_rules(), pin_ring_mm=0.1, slack_all=False)
    text = fr.typed_clearances(DSN, d)
    structure = text[text.index("(structure"):text.index("(placement")]
    network = text[text.index("(network"):]
    for t in fr.VIA_TYPES + fr.PIN_TYPES + fr.SMD_TYPES:
        assert f"(type {t})" in structure
        assert f"(type {t})" not in network
    assert structure.index("(clearance 190)") < structure.index("(type via_via)") < structure.index("(type smd_smd)")


def test_the_via_cost_goes_into_the_settings_file(tmp_path):
    import json
    path = fr.settings_json(tmp_path, threads=1, passes=30, edge_clearance_mm=0.5948)
    cfg = json.loads(path.read_text())
    assert cfg["router"]["scoring"]["via_costs"] == fr.VIA_COSTS
    assert cfg["router"]["copper_to_edge_clearance_um"] == 594.8  # the measured rule, not the router's 0.5 mm
    assert cfg["router"]["optimizer"]["enabled"] is False
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


# --- rules the export does not carry (D59) --------------------------------------------------------------------
def test_pads_with_a_clearance_override_become_keepouts_grown_by_it():
    """The Specctra export carries the net-class clearance only. `olimex-esp32c3-devkit` gives its four mounting
    holes 1.85 mm and its six fiducials 1.016 mm, and the router routed past them at the ordinary clearance."""
    ref = _ref("olimex-esp32c3-devkit")
    bare, _ = rebuild.strip_all(ref)
    board = kb.load_board(bare)
    keepouts = fr.pad_keepouts(board, clearance_mm=0.1261)
    by_ref = {k.reference: k for k in keepouts}
    assert sorted(by_ref) == ["FID1", "FID2", "FID3", "FID4", "FID5", "FID6", "MH1", "MH2", "MH3", "MH4"]
    assert by_ref["MH1"].grow_mm == pytest.approx(1.85 - 0.1261, abs=1e-4)  # the router keeps the rest itself
    assert by_ref["FID1"].grow_mm == pytest.approx(1.016 - 0.1261, abs=1e-4)
    assert by_ref["MH1"].layers == ("F.Cu", "B.Cu") and by_ref["FID1"].layers == ("F.Cu",)
    text = fr.keepouts_dsn(DSN, keepouts)
    structure = text[text.index("(structure"):text.index("(placement")]
    assert structure.count("(keepout") == sum(len(k.layers) for k in keepouts)  # one per copper layer of the pad
    assert structure.index("(keepout") < structure.index("(via ")  # where KiCad puts its own


def test_the_smoke_board_carries_overrides_too_and_an_override_below_the_rule_is_none():
    """Its four mounting holes hold copper 0.899 mm away and its two fiducials 0.65; asked for a clearance above
    those, nothing is a keepout."""
    ref = _ref("tinkerforge-temperature")
    bare, _ = rebuild.strip_all(ref)
    board = kb.load_board(bare)
    keepouts = fr.pad_keepouts(board, clearance_mm=0.1972)
    assert sorted((k.reference, round(k.grow_mm + 0.1972, 3)) for k in keepouts) == \
        [("Fiducial_Mark", 0.65), ("Fiducial_Mark", 0.65), ("U3", 0.899), ("U4", 0.899), ("U5", 0.899), ("U6", 0.899)]
    assert fr.pad_keepouts(board, clearance_mm=0.9) == []


# --- necked traces (D59, kind 2) -------------------------------------------------------------------------------
def test_tracks_the_router_necked_are_restored_to_the_rule_width():
    """Freerouting narrows a trace where it enters a pad (40 width violations on `open-book-c1`, all by 0.03 mm
    or more); `automatic_neckdown` off changes nothing. After the import every track narrower than the rule is
    set back to it, and the gate's DRC says whether the widened copper then clears its neighbours."""
    import pcbnew
    board = pcbnew.BOARD()
    net = pcbnew.NETINFO_ITEM(board, "N1")
    board.Add(net)
    for width in (0.25, 0.2006, 0.1798, 0.25):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(0, 0))
        t.SetEnd(pcbnew.VECTOR2I(kb.nm(1.0), 0))
        t.SetWidth(kb.nm(width))
        t.SetNet(net)
        board.Add(t)
    widened = fr.widen_tracks(board, width_mm=0.25)
    assert widened == 2
    assert all(kb.mm(t.GetWidth()) == pytest.approx(0.25) for t in kb.track_segments(board))
    assert fr.widen_tracks(board, width_mm=0.25) == 0


# --- clearances a few micrometres short (D59, kind 1) -----------------------------------------------------------
def _two_track_board(tmp_path, gap_mm: float):
    """Two parallel tracks of different nets ``gap_mm`` apart, on a board with an outline, saved to a file."""
    import pcbnew
    board = pcbnew.BOARD()
    nets = {}
    for name in ("A", "B"):
        nets[name] = pcbnew.NETINFO_ITEM(board, name)
        board.Add(nets[name])
    for i, (name, y) in enumerate((("A", 5.0), ("B", 5.0 + 0.25 + gap_mm))):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(kb.nm(2.0), kb.nm(y)))
        t.SetEnd(pcbnew.VECTOR2I(kb.nm(8.0), kb.nm(y)))
        t.SetWidth(kb.nm(0.25))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(nets[name])
        board.Add(t)
    outline = pcbnew.PCB_SHAPE(board)
    outline.SetShape(pcbnew.SHAPE_T_RECT)
    outline.SetStart(pcbnew.VECTOR2I(0, 0))
    outline.SetEnd(pcbnew.VECTOR2I(kb.nm(10.0), kb.nm(10.0)))
    outline.SetLayer(pcbnew.Edge_Cuts)
    board.Add(outline)
    path = tmp_path / "two.kicad_pcb"
    kb.save_board(board, path)
    return path


def test_a_track_a_few_micrometres_too_close_is_moved_away_and_the_drc_then_passes(tmp_path):
    """The router's octagonal model leaves copper up to 0.011 mm closer than KiCad measures (D59). The repair
    reads KiCad's own report and moves the offending track by the shortfall plus a hair, until the report is
    clean or the rounds run out."""
    path = _two_track_board(tmp_path, gap_mm=0.19)
    rules = _rules(clearance_mm=0.1972, hole_to_copper_mm=0.0, edge_clearance_mm=0.0, min_track_mm=0.25)
    board = kb.load_board(path)
    before = fr.drc_violations(board, rules, tmp_path / "before")
    assert [v.type for v in before] == ["clearance"] and before[0].short_mm == pytest.approx(0.0072, abs=1e-4)
    report = fr.repair_clearances(board, rules, tmp_path / "repair")
    assert report["moved"] >= 1 and report["remaining"] == 0, report
    assert fr.drc_violations(board, rules, tmp_path / "after") == []
    ys = sorted(kb.mm(t.GetStart().y) for t in kb.track_segments(board))
    assert ys[1] - ys[0] >= 0.25 + 0.1972 - 1e-6  # moved apart, not narrowed


def test_a_track_squeezed_from_both_sides_settles_between_its_neighbours(tmp_path):
    """One move per violation oscillated the smoke board's middle SOT-563 exit between its two neighbours and
    ended at zero or one violation by the order KiCad listed them. The pushes are summed per track."""
    import pcbnew
    path = _two_track_board(tmp_path, gap_mm=0.19)
    board = kb.load_board(path)
    net = pcbnew.NETINFO_ITEM(board, "C")
    board.Add(net)
    t = pcbnew.PCB_TRACK(board)  # a third track above A, leaving A's corridor 0.19 on both sides
    t.SetStart(pcbnew.VECTOR2I(kb.nm(2.0), kb.nm(5.0 - 0.25 - 0.19)))
    t.SetEnd(pcbnew.VECTOR2I(kb.nm(8.0), kb.nm(5.0 - 0.25 - 0.19)))
    t.SetWidth(kb.nm(0.25))
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(net)
    board.Add(t)
    rules = _rules(clearance_mm=0.1972, hole_to_copper_mm=0.0, edge_clearance_mm=0.0, min_track_mm=0.25)
    report = fr.repair_clearances(board, rules, tmp_path / "repair")
    assert report["remaining"] == 0, report
    ys = sorted(kb.mm(t.GetStart().y) for t in kb.track_segments(board))
    assert ys[1] - ys[0] >= 0.25 + 0.1972 - 1e-6 and ys[2] - ys[1] >= 0.25 + 0.1972 - 1e-6


def test_a_clean_board_needs_no_repair(tmp_path):
    path = _two_track_board(tmp_path, gap_mm=0.25)
    rules = _rules(clearance_mm=0.1972, hole_to_copper_mm=0.0, edge_clearance_mm=0.0, min_track_mm=0.25)
    board = kb.load_board(path)
    report = fr.repair_clearances(board, rules, tmp_path / "repair")
    assert report == {"rounds": 1, "moved": 0, "remaining": 0, "unfixable": 0, "strategy": "floor", "worst_mm": 0.0}


# --- pads with the same number (D61) ------------------------------------------------------------------------
NETWORK = """  (network
    (net GND
      (pins B3-2 B3-2@1 B3-2@2 C1-2 "USB-C1"-0 "USB-C1"-0@1 U3-49 U3-49@3)
    )
    (net /BTN_LEFT
      (pins B5-1 B5-1@1 B5-1@2
        B5-1@3 R1-1)
    )
    (class kicad_default GND /BTN_LEFT
      (circuit
        (use_via "Via[0-1]_600:300_um")
      )
    )
  )
"""


def test_only_pad_pieces_that_touch_leave_the_pin_list():
    """The named pins go, quoted references included; everything else stays, class lists untouched."""
    text = fr.drop_pins(NETWORK, {"B3-2@1", "B3-2@2", "USB-C1-0@1", "B5-1@1", "B5-1@2", "B5-1@3"})
    assert '(pins B3-2 C1-2 "USB-C1"-0 U3-49 U3-49@3)' in text
    assert "(pins B5-1 R1-1)" in text
    assert text.count("(class kicad_default") == 1
    assert fr.drop_pins(NETWORK, set()) == NETWORK


def test_the_buttons_fingers_are_joined_and_the_connectors_two_eps_are_not():
    ref = _ref("open-book-c1")
    bare, _ = rebuild.strip_all(ref)
    joined = fr.joined_pins(kb.load_board(bare))
    b5 = sorted(n for n in joined if n.startswith("B5-"))
    assert len(b5) == 7, b5  # 9 pieces, two round pads stay as pins
    board = kb.load_board(bare)
    fp = board.FindFootprintByReference("B5")
    names = fr._pin_names(fp)
    round_pads = {f"B5-{names[i]}" for i, p in enumerate(fp.Pads()) if min(kb.mm(p.GetSize(p.GetLayerSet().CuStack()[0]).x), kb.mm(p.GetSize(p.GetLayerSet().CuStack()[0]).y)) > 2}
    assert len(round_pads) == 2 and not (round_pads & set(b5)), (round_pads, b5)
    ref = _ref("tinkerforge-temperature")
    bare, _ = rebuild.strip_all(ref)
    assert fr.joined_pins(kb.load_board(bare)) == set()  # P1's two EP pads are 11.6 mm apart: both routed


# --- supply nets as pours (item 4) ----------------------------------------------------------------------------
def test_the_problem_board_records_the_pours_it_strips():
    """Stage 4 would specify the pours; the benchmark hands the router the reference's own (D17): the net, the
    layers, the zone's clearance and minimum width, and its outline."""
    ref = _ref("tinkerforge-temperature")
    _bare, info = rebuild.strip_all(ref)
    pours = info["pours"]
    assert sorted((p["net"], p["layer"]) for p in pours) == [("GND", "Rückseite"), ("GND", "Vorderseite")]
    for p in pours:
        assert p["clearance_mm"] == pytest.approx(0.249, abs=1e-3) and p["min_thickness_mm"] == pytest.approx(0.249, abs=1e-3)
        assert len(p["outline_mm"]) >= 4 and p["pad_connection"] == 1


def test_the_pours_are_laid_after_the_import_with_the_hole_rule_in_their_clearance():
    """Laid before the export the router trusted the plane for a pad the fill cannot reach (D62)."""
    ref = _ref("tinkerforge-temperature")
    bare, info = rebuild.strip_all(ref)
    board = kb.load_board(bare)
    assert len(list(board.Zones())) == 0
    made = fr.add_pours(board, info["pours"], _rules(), ring_mm=0.226)
    assert len(made) == 2
    zones = {(z.GetNetname(), board.GetLayerName(z.GetFirstLayer())) for z in board.Zones()}
    assert zones == {("GND", "Vorderseite"), ("GND", "Rückseite")}
    for z in board.Zones():
        assert kb.mm(z.GetMinThickness()) >= 0.2997  # never below the rule width
        clearance = z.GetLocalClearance()
        clearance = clearance.value() if hasattr(clearance, "value") else clearance
        assert kb.mm(clearance) == pytest.approx(0.4964 - 0.226, abs=1e-4)  # the hole rule less the via ring
        assert not z.GetIsRuleArea()


def test_a_hole_without_copper_gets_a_no_pour_rule_area_sized_by_the_hole_rule():
    """The filler keeps the zone clearance from a pad's copper; a non-plated mounting hole has none, and
    open-book's pour came 0.1 mm too close to its four holes on both layers (8 violations)."""
    ref = _ref("open-book-c1")
    bare, _ = rebuild.strip_all(ref)
    board = kb.load_board(bare)
    rules = _rules(hole_to_copper_mm=0.2526)
    areas = fr.hole_rule_areas(board, rules)
    assert len(areas) >= 4
    for z in areas:
        assert z.GetIsRuleArea() and z.GetDoNotAllowCopperPour()
        bb = z.GetBoundingBox()
        assert kb.mm(bb.GetWidth()) >= 2 * 0.2526  # at least the rule around the hole


# --- the result must not depend on item order (D25) ---------------------------------------------------------
def _crowded_board(tmp_path, order):
    """Eight parallel tracks of four nets, 0.19 mm apart under a 0.1972 rule, inserted in ``order``."""
    import pcbnew
    board = pcbnew.BOARD()
    nets = {}
    for name in ("A", "B", "C", "D"):
        nets[name] = pcbnew.NETINFO_ITEM(board, name)
        board.Add(nets[name])
    specs = [(("A", "B", "C", "D")[i % 4], 3.0 + i * (0.25 + 0.19)) for i in range(8)]
    for i in order:
        name, y = specs[i]
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(kb.nm(2.0 + 0.1 * i), kb.nm(y)))  # staggered ends: no shared vertices
        t.SetEnd(pcbnew.VECTOR2I(kb.nm(8.0 - 0.1 * i), kb.nm(y)))
        t.SetWidth(kb.nm(0.25))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(nets[name])
        board.Add(t)
    outline = pcbnew.PCB_SHAPE(board)
    outline.SetShape(pcbnew.SHAPE_T_RECT)
    outline.SetStart(pcbnew.VECTOR2I(0, 0))
    outline.SetEnd(pcbnew.VECTOR2I(kb.nm(10.0), kb.nm(10.0)))
    outline.SetLayer(pcbnew.Edge_Cuts)
    board.Add(outline)
    path = tmp_path / f"crowded-{''.join(map(str, order))}.kicad_pcb"
    kb.save_board(board, path)
    return kb.load_board(path)


def test_the_repair_gives_the_same_copper_whatever_order_the_items_came_in(tmp_path):
    """The session import gives every item a fresh uuid, so a repair ordered by uuid is ordered by chance, and
    one board's result changed between two runs of one configuration that way. Inserted in another order the
    items also carry other uuids; the copper must come out identical."""
    rules = _rules(clearance_mm=0.1972, hole_to_copper_mm=0.0, edge_clearance_mm=0.0, min_track_mm=0.25)
    digests = []
    for order in (list(range(8)), list(reversed(range(8))), [3, 7, 1, 5, 0, 6, 2, 4]):
        board = _crowded_board(tmp_path, order)
        report = fr.repair_clearances(board, rules, tmp_path / f"repair-{''.join(map(str, order))}")
        assert report["remaining"] == 0, (order, report)
        digests.append(fr.geometry_digest(board))
    assert len(set(digests)) == 1, digests


def test_the_digest_ignores_order_and_sees_geometry(tmp_path):
    a = fr.geometry_digest(_crowded_board(tmp_path, list(range(8))))
    b = fr.geometry_digest(_crowded_board(tmp_path, list(reversed(range(8)))))
    assert a == b
    board = _crowded_board(tmp_path, list(range(8)))
    t = kb.track_segments(board)[0]
    t.SetStart(pcbnew_vec := __import__("pcbnew").VECTOR2I(t.GetStart().x + 1, t.GetStart().y))
    assert fr.geometry_digest(board) != a


# --- what the router leaves behind (D66) ---------------------------------------------------------------------
def test_dangling_spurs_and_duplicate_segments_are_pruned(tmp_path):
    """open-book's BTN_LOCK carried a 13 mm spur ending on nothing 0.1 mm from the board edge, with a second
    identical segment on top of it; KiCad's DRC reports a dangling track only as a warning."""
    import pcbnew
    board = pcbnew.BOARD()
    net = pcbnew.NETINFO_ITEM(board, "N")
    board.Add(net)
    via0 = pcbnew.PCB_VIA(board)  # stands for the pad end: a via of the net at (1, 1)
    via0.SetPosition(pcbnew.VECTOR2I(kb.nm(1.0), kb.nm(1.0)))
    via0.SetNet(net)
    board.Add(via0)
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(pcbnew.VECTOR2I(kb.nm(5.0), kb.nm(1.0)))
    via.SetNet(net)
    board.Add(via)

    def seg(x0, y0, x1, y1):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(kb.nm(x0), kb.nm(y0)))
        t.SetEnd(pcbnew.VECTOR2I(kb.nm(x1), kb.nm(y1)))
        t.SetWidth(kb.nm(0.25))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(net)
        board.Add(t)
        return t

    seg(1.0, 1.0, 5.0, 1.0)  # via to via: stays
    seg(1.0, 1.0, 5.0, 1.0)  # its duplicate: goes
    seg(5.0, 1.0, 5.0, 3.0)  # a spur off the via: goes
    seg(5.0, 3.0, 7.0, 3.0)  # the spur's continuation: goes too, in the second pass
    removed = fr.prune_dangling(board)
    assert removed == {"duplicates": 1, "dangling": 2}, removed
    assert len(kb.track_segments(board)) == 1


# --- rule areas the export gets wrong -------------------------------------------------------------------------
def _rule_area_board(tmp_path):
    """Four rule areas, one of each kind KiCad can forbid, on an otherwise empty 20 mm board."""
    board = pcbnew.BOARD()
    for ax, ay, bx, by in ((0, 0, 20, 0), (20, 0, 20, 20), (20, 20, 0, 20), (0, 20, 0, 0)):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetStart(pcbnew.VECTOR2I(kb.nm(ax), kb.nm(ay)))
        s.SetEnd(pcbnew.VECTOR2I(kb.nm(bx), kb.nm(by)))
        board.Add(s)
    for x, flags, name in ((2, {"pour"}, "pour-only"), (6, {"tracks"}, "tracks-only"), (10, {"vias"}, "vias-only"),
                           (14, {"tracks", "vias", "pour"}, "all")):
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetLayer(pcbnew.F_Cu)
        z.SetZoneName(name)
        z.SetDoNotAllowCopperPour("pour" in flags)
        z.SetDoNotAllowTracks("tracks" in flags)
        z.SetDoNotAllowVias("vias" in flags)
        o = z.Outline()
        o.NewOutline()
        for px, py in ((x, 5), (x + 3, 5), (x + 3, 8), (x, 8)):
            o.Append(kb.nm(px), kb.nm(py))
        board.Add(z)
    return board


def test_a_rule_area_that_forbids_only_the_pour_is_not_a_keepout_to_the_router(tmp_path):
    """KiCad writes it as a plain (keepout), the same as one forbidding tracks and vias; the router then avoids
    the pads it covers. `olimex-rp2040-pico-pc` draws no-pour areas over both pad rows of its TSSOP-14."""
    board = _rule_area_board(tmp_path)
    assert [z.GetZoneName() for z in fr.pour_only_rule_areas(board)] == ["pour-only"]
    fr.export_dsn(board, _rules(), tmp_path / "board.dsn")
    text = (tmp_path / "board.dsn").read_text()
    assert text.count("(wire_keepout") == 1 and text.count("(via_keepout") == 1
    assert text.count('(keepout "" (polygon') == 1  # the one forbidding everything stays a keepout
    assert "2000 -5000" not in text  # the pour-only area's corner is in no keepout
    # and the area is back on the board for the fill, as it was
    names = {z.GetZoneName(): z for z in board.Zones()}
    assert sorted(names) == ["all", "pour-only", "tracks-only", "vias-only"]
    back = names["pour-only"]
    assert back.GetIsRuleArea() and back.GetDoNotAllowCopperPour() and not back.GetDoNotAllowTracks()
    ring = back.Outline().Outline(0)
    assert [(kb.mm(ring.CPoint(k).x), kb.mm(ring.CPoint(k).y)) for k in range(ring.PointCount())] == \
        [(2, 5), (5, 5), (5, 8), (2, 8)]
    assert back.IsOnLayer(pcbnew.F_Cu)


def test_the_rp2040_boards_no_pour_areas_leave_its_tssop_pads_to_the_router():
    ref = _ref("olimex-rp2040-pico-pc")
    bare, _ = rebuild.strip_all(ref)
    board = kb.load_board(bare)
    areas = fr.pour_only_rule_areas(board)
    assert len(areas) == 4 and len(list(board.Zones())) == 4
    u3 = {p.GetNumber(): p.GetPosition() for fp in board.GetFootprints() if fp.GetReference() == "U3" for p in fp.Pads()}
    covered = sum(1 for pos in u3.values() if any(z.Outline().Contains(pos) for z in areas))
    assert covered == 12  # 12 of the TSSOP-14's pad centres lie in a no-pour area; pads 2 and 3 are 0.3 mm from one
    out = refs.repo_root() / "build" / "fr" / "test-rp2040-areas" / "board.dsn"
    fr.export_dsn(board, rebuild.measure_rules(ref), out)
    text = out.read_text()
    assert '(keepout "" (polygon' not in text
    assert len(list(board.Zones())) == 4 and len(fr.pour_only_rule_areas(board)) == 4


# --- what the placer left on rp2040 (D68) ---------------------------------------------------------------------
def test_a_track_squeezed_between_a_pad_and_our_via_makes_the_via_give_way(tmp_path):
    """The track can only settle in the middle of a corridor 0.011 mm too narrow; it stayed short on both
    sides for twelve rounds, counted as moving, and the via was never asked to move."""
    import pcbnew
    path = _two_track_board(tmp_path, gap_mm=0.30)  # A at y 5.0 and B well away; A is the squeezed one
    board = kb.load_board(path)
    nets = {n: board.FindNet(n) for n in ("A", "B")}
    nets["C"] = pcbnew.NETINFO_ITEM(board, "C")
    board.Add(nets["C"])
    fp = pcbnew.FOOTPRINT(board)  # a pad of net C above A, 0.005 too close
    fp.SetFPID(pcbnew.LIB_ID("test", "pad"))
    fp.SetReference("P1")
    pad = pcbnew.PAD(fp)
    pad.SetNumber("1")
    pad.SetShape(pcbnew.PAD_SHAPE_RECT)
    pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    pad.SetSize(pcbnew.VECTOR2I(kb.nm(2.0), kb.nm(0.5)))
    y_pad = 5.0 - 0.125 - (0.1972 - 0.005) - 0.25
    pad.SetPosition(pcbnew.VECTOR2I(kb.nm(5.0), kb.nm(y_pad)))
    fp.SetPosition(pcbnew.VECTOR2I(kb.nm(5.0), kb.nm(y_pad)))
    ls = pcbnew.LSET()
    ls.AddLayer(pcbnew.F_Cu)
    pad.SetLayerSet(ls)
    pad.SetNet(nets["C"])
    fp.Add(pad)
    board.Add(fp)
    via = pcbnew.PCB_VIA(board)  # our via of net B below A, 0.006 too close
    via.SetWidth(kb.nm(0.701))
    via.SetDrill(kb.nm(0.249))
    via.SetPosition(pcbnew.VECTOR2I(kb.nm(5.0), kb.nm(5.0 + 0.125 + (0.1972 - 0.006) + 0.3505)))
    via.SetNet(nets["B"])
    board.Add(via)
    rules = _rules(clearance_mm=0.1972, hole_to_copper_mm=0.0, edge_clearance_mm=0.0, min_track_mm=0.25)
    from waffle_eda.route.obstacles import Obstacles
    before = fr.index_violations(board, Obstacles(board), rules)
    assert sorted(v.short_mm for v in before) == pytest.approx([0.005, 0.006], abs=5e-4)
    report = fr.repair_clearances(board, rules, tmp_path / "repair")
    assert report["remaining"] == 0, report
    assert fr.index_violations(board, Obstacles(board), rules) == []
    moved_via = next(v for v in kb.vias(board))
    assert kb.mm(moved_via.GetPosition().y) > 5.0 + 0.125 + 0.1972 + 0.3505 - 1e-6  # the via gave way


def test_the_edge_clearance_is_measured_to_the_outline_not_its_stroke(tmp_path):
    """KiCad's DRC passed rp2040's LED1 track at 0.539 mm from the edge under a 0.4776 rule; the index read it
    0.25 short, measuring to the 0.254 mm stroke the edge is drawn with and stopping at 0.25 mm."""
    import pcbnew
    path = _two_track_board(tmp_path, gap_mm=0.30)
    board = kb.load_board(path)
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts:
            d.SetWidth(kb.nm(0.254))
    rules = _rules(clearance_mm=0.1972, hole_to_copper_mm=0.0, edge_clearance_mm=0.4776, min_track_mm=0.25)
    from waffle_eda.route.obstacles import Obstacles
    # track A runs from x 2.0 to 8.0 at y 5.0 on a 10 mm board: its end caps are 2.0 - 0.125 = 1.875 from the
    # left and right edges, and its sides 5.0 - 0.125 = 4.875 from the top and bottom: clear
    assert fr.index_violations(board, Obstacles(board), rules) == []
    a = next(t for t in kb.track_segments(board) if t.GetNetname() == "A")
    a.SetStart(pcbnew.VECTOR2I(kb.nm(0.6), kb.nm(5.0)))  # the end cap 0.475 from the left edge: 0.0026 short
    found = fr.index_violations(board, Obstacles(board), rules)
    assert [(v.type, v.short_mm) for v in found] == [("copper_edge_clearance", pytest.approx(0.0026, abs=5e-4))]  # 0.4776 - 0.475
    a.SetStart(pcbnew.VECTOR2I(kb.nm(0.61), kb.nm(5.0)))  # 0.485: clear, though 0.358 from the stroke
    assert fr.index_violations(board, Obstacles(board), rules) == []


def test_of_two_vias_too_close_whichever_can_give_way_does(tmp_path):
    """rp2040's SPI0_CSn1 via was 0.0055 short of MICRO_SD1's and boxed on its far side by a track; the placer
    asked only the first via of the pair to move and left the violation for nine rounds."""
    import pcbnew
    path = _two_track_board(tmp_path, gap_mm=0.30)
    board = kb.load_board(path)
    nets = {n: board.FindNet(n) for n in ("A", "B")}
    y_a = 5.0 - 0.125 - 0.1972 - 0.3505 - 1.0  # via A of net A well above track A, via B above it, 0.006 short
    for net, y in (("A", y_a), ("B", y_a - 0.701 - 0.1972 + 0.006)):
        via = pcbnew.PCB_VIA(board)
        via.SetWidth(kb.nm(0.701))
        via.SetDrill(kb.nm(0.249))
        via.SetPosition(pcbnew.VECTOR2I(kb.nm(5.0), kb.nm(y)))
        via.SetNet(nets[net])
        board.Add(via)
    wall = pcbnew.PCB_TRACK(board)  # net B's own track boxes via A from below, exactly at the rule
    wall.SetStart(pcbnew.VECTOR2I(kb.nm(3.0), kb.nm(y_a + 0.3505 + 0.1972 + 0.125)))
    wall.SetEnd(pcbnew.VECTOR2I(kb.nm(7.0), kb.nm(y_a + 0.3505 + 0.1972 + 0.125)))
    wall.SetWidth(kb.nm(0.25))
    wall.SetLayer(pcbnew.F_Cu)
    wall.SetNet(nets["B"])
    board.Add(wall)
    rules = _rules(clearance_mm=0.1972, hole_to_copper_mm=0.0, edge_clearance_mm=0.0, min_track_mm=0.25)
    from waffle_eda.route.obstacles import Obstacles
    before = fr.index_violations(board, Obstacles(board), rules)
    assert [v.short_mm for v in before] == [pytest.approx(0.006, abs=5e-4)]
    report = fr.repair_clearances(board, rules, tmp_path / "repair")
    assert report["remaining"] == 0, report
    ys = {v.GetNetname(): kb.mm(v.GetPosition().y) for v in kb.vias(board)}
    assert ys["A"] == pytest.approx(y_a, abs=1e-6)  # boxed: stayed
    assert ys["B"] < y_a - 0.701 - 0.1972 + 1e-6  # gave way


def test_a_run_killed_at_the_cap_takes_its_whole_process_group_with_it(monkeypatch, tmp_path):
    """Killing `xvfb-run` alone orphaned the JVM, which routed on beside the next run."""
    import os
    pidfile = tmp_path / "child.pid"
    java = tmp_path / "java"  # the stand-in JVM: a child of its own that outlives it unless the group is killed
    java.write_text(f"#!/bin/sh\nsleep 600 &\necho $! > {pidfile}\nsleep 600\n")
    java.chmod(0o755)
    xvfb = tmp_path / "xvfb-run"  # stands in for the real one: runs its command
    xvfb.write_text('#!/bin/sh\nshift\nexec "$@"\n')
    xvfb.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setattr(fr, "available", lambda: None)
    monkeypatch.setattr(fr, "java_path", lambda: java)
    monkeypatch.setattr(fr, "jar_path", lambda: tmp_path / "x.jar")
    code, timed_out = fr.run_jar(tmp_path / "board.dsn", tmp_path / "board.ses", tmp_path / "run.log", 1, 1, timeout_s=1.0)
    assert timed_out and code is None
    child = int(pidfile.read_text())
    assert not os.path.exists(f"/proc/{child}") or open(f"/proc/{child}/stat").read().split()[2] == "Z", child


def test_the_repair_keeps_the_strategy_whose_deepest_violation_is_shallowest(monkeypatch, tmp_path):
    """On crkbd the free strategy left fewer violations than the floor but four of them were shorts (D70)."""
    outcomes = {True: {"rounds": 12, "moved": 9, "remaining": 60, "unfixable": 0, "worst_mm": 0.011},
                False: {"rounds": 12, "moved": 9, "remaining": 51, "unfixable": 0, "worst_mm": 0.19}}
    monkeypatch.setattr(fr, "_repair_rounds", lambda board, rules, work, rounds: dict(outcomes[fr.DRAG_FLOOR]))
    path = _two_track_board(tmp_path, gap_mm=0.30)
    board = kb.load_board(path)
    report = fr.repair_clearances(board, _rules(), tmp_path / "repair")
    assert report["strategy"] == "floor" and report["remaining"] == 60
    outcomes[False]["worst_mm"] = 0.011  # as shallow: then the fewer wins
    report = fr.repair_clearances(board, _rules(), tmp_path / "repair")
    assert report["strategy"] == "free" and report["remaining"] == 51


def test_a_gap_within_rounding_of_the_rule_is_no_violation_and_never_a_hole_one(tmp_path):
    """crkbd's KEY3 stub sat 0.18896 mm from a pad under a 0.189 rule: the shortfall rounded to zero, the
    index took that for a hole case, and a pad with no hole gave a 0.0605 mm violation the placer chased."""
    import pcbnew
    path = _two_track_board(tmp_path, gap_mm=0.30)
    board = kb.load_board(path)
    net_c = pcbnew.NETINFO_ITEM(board, "C")
    board.Add(net_c)
    fp = pcbnew.FOOTPRINT(board)
    fp.SetFPID(pcbnew.LIB_ID("test", "pad"))
    fp.SetReference("P1")
    pad = pcbnew.PAD(fp)
    pad.SetNumber("1")
    pad.SetShape(pcbnew.PAD_SHAPE_RECT)
    pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    pad.SetSize(pcbnew.VECTOR2I(kb.nm(1.0), kb.nm(0.5)))
    y = 5.0 - 0.125 - 0.18896 - 0.25  # 0.18896 from track A's edge
    pad.SetPosition(pcbnew.VECTOR2I(kb.nm(5.0), kb.nm(y)))
    fp.SetPosition(pcbnew.VECTOR2I(kb.nm(5.0), kb.nm(y)))
    ls = pcbnew.LSET()
    ls.AddLayer(pcbnew.F_Cu)
    pad.SetLayerSet(ls)
    pad.SetNet(net_c)
    fp.Add(pad)
    board.Add(fp)
    rules = _rules(clearance_mm=0.189, hole_to_copper_mm=0.2495, edge_clearance_mm=0.0, min_track_mm=0.25)
    from waffle_eda.route.obstacles import Obstacles
    found = fr.index_violations(board, Obstacles(board), rules)
    assert [v.type for v in found if v.short_mm > 0.001] == []
    assert fr.repair_clearances(board, rules, tmp_path / "repair")["worst_mm"] <= 0.001


def test_a_kept_collision_never_deepens_under_an_end_move_or_a_push(tmp_path):
    """crkbd's KEY5 ran 0.006 mm too close to KEY10 along 4 mm; an end move for a violation at its other end
    swung its far end 0.28 mm into KEY10, an overlap KiCad reports as a short (D70)."""
    import pcbnew
    from waffle_eda.route.obstacles import Obstacles
    path = _two_track_board(tmp_path, gap_mm=0.183)  # A at y 5.0, B 0.006 too close below it, x 2..8
    board = kb.load_board(path)
    rules = _rules(clearance_mm=0.189, hole_to_copper_mm=0.0, edge_clearance_mm=0.0, min_track_mm=0.25)
    a = next(t for t in kb.track_segments(board) if t.GetNetname() == "A")
    # floored: swinging A's far end 0.1 mm down keeps the collision with B (it had it) but deepens it past the
    # router's own clearance; free: the same swing may deepen, but 0.2 mm would overlap B, a short
    for floor, swing in ((True, 0.1), (False, 0.2)):
        fr.DRAG_FLOOR = floor
        obstacles = Obstacles(board)
        assert not fr._move_end_checked(board, obstacles, a, 1, 0.0, swing, rules)
        # a push of A with nothing vouched for (as in a chain push), straight into B
        assert not fr._move_checked(board, obstacles, a, 0.0, swing, rules)
        # the same push away from B is fine
        assert fr._move_checked(board, obstacles, a, 0.0, -swing, rules, keep=False)
    fr.DRAG_FLOOR = True
    assert kb.mm(a.GetEnd().y) == pytest.approx(5.0)  # nothing moved


# --- pad pieces the router leaves apart (D73) -----------------------------------------------------------------
def test_piece_groups_the_router_left_apart_are_joined_where_the_run_is_clear():
    """libresolar's USB shield: twelve pieces in six groups; the router reached 1 of the 6 connections."""
    ref = _ref("libresolar-mppt-2420")
    bare, _ = rebuild.strip_all(ref)
    board = kb.load_board(bare)
    rules = rebuild.measure_rules(ref)
    p3 = board.FindFootprintByReference("P3")
    groups = fr.piece_groups(p3)
    assert len(groups["6"]) == 6 and sum(len(g) for g in groups["6"]) == 12
    names = fr._pin_names(p3)
    kept = {f"P3-{names[i]}" for i in range(len(names)) if names[i].startswith("6")} - fr.joined_pins(board)
    assert kept == {"P3-6@2", "P3-6@9", "P3-6@4", "P3-6@7", "P3-6@5", "P3-6@6"}, kept  # the plated pieces stay the pins of their groups
    made = fr.join_piece_groups(board, rules)  # no copper yet: every group is unreached
    p3_joins = [t for t in made if t.GetNetname() == "Net-(C25-Pad1)"]
    assert len(p3_joins) == 5, len(p3_joins)  # a chain through the six groups
    from waffle_eda.route.obstacles import Obstacles
    assert fr.index_violations(board, Obstacles(board), rules) == []
    ref = _ref("tinkerforge-temperature")
    bare, _ = rebuild.strip_all(ref)
    board = kb.load_board(bare)
    rules = rebuild.measure_rules(ref)
    import pcbnew
    p1 = board.FindFootprintByReference("P1")
    eps = [p for p in p1.Pads() if p.GetNumber() == "EP"]
    assert len(fr.piece_groups(p1)["EP"]) == 2  # 11.6 mm apart: two groups, both pins to the router
    for pad in eps:  # the router reached both: a short track of the net leaves each
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(pad.GetPosition()))
        t.SetEnd(pcbnew.VECTOR2I(pad.GetPosition().x + kb.nm(0.5), pad.GetPosition().y))
        t.SetWidth(kb.nm(0.3))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(pad.GetNet())
        board.Add(t)
    before = len(kb.track_segments(board))
    fr.join_piece_groups(board, rules)
    assert len(kb.track_segments(board)) == before  # reached on both sides: nothing to join


def test_a_plane_layer_handed_to_the_router_is_typed_power_in_the_dsn():
    """D81: a plane on a `signal` layer makes 2.4.1 call the layer a dedicated power plane and write an empty
    session; the layers of the planes handed over are typed power, and a layer the DSN does not carry as a
    signal layer is an error, not a silent no-op."""
    dsn = "(pcb x\n  (structure\n    (layer F.Cu\n      (type signal)\n    )\n    (layer In1.Cu\n      (type signal)\n    )\n  )\n)"
    out = fr.type_layers_power(dsn, ["In1.Cu"])
    assert "(layer In1.Cu\n      (type power)" in out and "(layer F.Cu\n      (type signal)" in out
    with pytest.raises(ValueError):
        fr.type_layers_power(dsn, ["In9.Cu"])
    with pytest.raises(ValueError):
        fr.type_layers_power(out, ["In1.Cu"])  # already power: typing it again is a mistake


def test_a_plane_nets_pins_leave_the_network_and_the_net_stays():
    """D85: the router routes nothing of a plane net (its pours and feeds connect it) but the net must stay in
    the network section, since the fixed feed wires and vias name it."""
    from waffle_eda.route.freerouting import drop_net_pins
    dsn = ('(structure (rule (width 150)))\n  (network\n    (net GND\n      (pins C1-2 U1-49 J1-6@2)\n    )\n'
           '    (net "Net-(C4-Pad1)"\n      (pins C4-1 U1-3)\n    )\n    (net +3V3\n      (pins C1-1)\n    )\n  )\n'
           '  (wiring\n    (wire (path F.Cu 150  1 2  3 4)(net GND)(type fix))\n  )\n')
    out = drop_net_pins(dsn, {"GND", "Net-(C4-Pad1)"})
    assert "(net GND\n      (pins )" in out and '(net "Net-(C4-Pad1)"\n      (pins )' in out
    assert "(pins C1-1)" in out and "(net GND)(type fix)" in out
    assert drop_net_pins(dsn, set()) == dsn


def _qfn_board(edge_y: float = -3.3):
    """A 0.5 mm pitch package with a row of pads on its north side, a thermal pad, a resistor in one pad's exit,
    and the board's edge close to another; nets on two pads each so the stubs count them as routable."""
    from tests.test_planes import _pad
    b = pcbnew.BOARD()
    b.GetDesignSettings().SetCopperLayerCount(2)
    nets = {}
    for k in range(6):
        nets[k] = pcbnew.NETINFO_ITEM(b, f"N{k}")
        b.Add(nets[k])
    u1 = pcbnew.FOOTPRINT(b)
    u1.SetReference("U1")
    u1.SetPosition(pcbnew.VECTOR2I(0, 0))
    b.Add(u1)
    for k in range(5):  # the north row: pads 0.25 wide, 0.9 long, exits pointing up (-y)
        _pad(u1, str(k + 1), nets[k], -1.0 + 0.5 * k, -2.5, 0.25, 0.9)
    _pad(u1, "9", nets[5], 0, 0, 3.0, 3.0)  # the thermal pad
    r1 = pcbnew.FOOTPRINT(b)  # the other pad of every net, and a resistor pad right in pad 3's exit
    r1.SetReference("R1")
    r1.SetPosition(pcbnew.VECTOR2I(kb.nm(10), 0))
    b.Add(r1)
    for k in range(6):
        _pad(r1, str(k + 1), nets[k], 10 + k, 5, 0.6, 0.6)
    _pad(r1, "7", nets[5], 0.0, -3.4, 0.2, 0.6)  # net N5, 0.15 mm beyond pad 3's edge, in pad 3's exit only
    for (ax, ay), (bx, by) in (((-6, edge_y), (16, edge_y)), ((16, edge_y), (16, 8)), ((16, 8), (-6, 8)), ((-6, 8), (-6, edge_y))):
        seg = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(kb.nm(ax), kb.nm(ay)))
        seg.SetEnd(pcbnew.VECTOR2I(kb.nm(bx), kb.nm(by)))
        seg.SetLayer(pcbnew.Edge_Cuts)
        b.Add(seg)
    return b


def test_fine_pitch_stubs_leave_every_pad_straight_and_stop_at_pads_and_the_edge():
    """D85: a straight exit out of every pad of a 0.5 mm package, shortened by another net's pad in the way,
    dropped when the edge rule leaves too little, none for the thermal pad."""
    b = _qfn_board()
    nets = {f"N{k}" for k in range(6)}
    stubs = fr.escape_stubs(b, width_mm=0.15, clearance_mm=0.14, nets=nets, fine_pitch_mm=0.5, edge_mm=0.3, hole_mm=0.25)
    by_net = {s.net: s for s in stubs}
    assert "N5" not in by_net  # the thermal pad
    # the free pads: straight up, 0.5 mm beyond the pad's edge at y = -2.95, but the edge rule at y = -3.3
    # allows copper down to -3.3 + 0.3 + 0.075 = -2.925, so nothing fits: the whole row is inside the rule
    assert all(len(s.points) == 2 and s.points[1][0] == pytest.approx(s.points[0][0]) for s in stubs)
    assert all(s.points[1][1] < s.points[0][1] for s in stubs)  # up, away from the package
    assert set(by_net) <= {"N0", "N1", "N2", "N3", "N4"}
    b2 = _qfn_board(edge_y=-8.0)  # the edge out of the way
    stubs2 = fr.escape_stubs(b2, width_mm=0.15, clearance_mm=0.14, nets=nets, fine_pitch_mm=0.5, edge_mm=0.3, hole_mm=0.25)
    by_net2 = {s.net: s for s in stubs2}
    assert set(by_net2) == {"N0", "N1", "N3", "N4"}  # pad 3 (N2): the resistor pad 0.15 mm ahead leaves under the minimum
    assert all(abs(s.length_mm() - (0.45 + 0.5)) < 1e-6 for s in stubs2)  # half the pad plus the exit


def test_exit_stubs_are_laid_for_the_named_pads_only_and_name_them():
    """D86: the closure loop reserves the exits of the pads a run left open, not every pad of the package."""
    b = _qfn_board(edge_y=-8.0)
    from tests.test_planes import RULES
    stubs = fr.exit_stubs(b, RULES, {"U1-1", "U1-4", "U1-3", "R1-2"})
    assert sorted(s.pad for s in stubs) == ["U1-1", "U1-4"]  # pad 3's exit is blocked; R1 is not fine pitch
    assert {s.net for s in stubs} == {"N0", "N3"}
    assert all(len(s.points) == 2 for s in stubs)


def test_untouched_pads_are_the_pads_no_copper_reaches():
    b = _qfn_board(edge_y=-8.0)
    nets = b.GetNetsByName()
    track = pcbnew.PCB_TRACK(b)  # N0 from the QFN pad to the resistor pad: both reached
    track.SetStart(pcbnew.VECTOR2I(kb.nm(-1.0), kb.nm(-2.5)))
    track.SetEnd(pcbnew.VECTOR2I(kb.nm(10.0), kb.nm(5.0)))
    track.SetWidth(kb.nm(0.15))
    track.SetLayer(pcbnew.F_Cu)
    track.SetNet(nets["N0"])
    b.Add(track)
    assert fr.untouched_pads(b, {"N0", "N1"}) == {"U1-2", "R1-2"}


def test_the_rounds_loop_stubs_the_open_pads_and_stops_when_no_stub_is_left_to_add(monkeypatch, tmp_path):
    """D86: round one leaves every net open; round two runs with an exit stub out of each open fine-pitch pad
    whose exit is free; the nets no stub can help stay open and end the loop with a round to spare."""
    from tests.test_planes import RULES
    problem = tmp_path / "problem.kicad_pcb"
    kb.save_board(_qfn_board(edge_y=-8.0), problem)
    seen = []

    def stand_in(board, rules, work_dir, say=lambda _m: None, stub_pads=None, **kw):
        """Connects every net whose QFN pad got a stub, by a track to its resistor pad; the rest stay open."""
        seen.append(set(stub_pads or ()))
        (work_dir / "board.ses").write_text("stand-in")
        nets = board.GetNetsByName()
        for fp in board.GetFootprints():
            if fp.GetReference() != "U1":
                continue
            for pad in fp.Pads():
                if f"U1-{pad.GetNumber()}" in (stub_pads or ()):
                    k = int(pad.GetNumber()) - 1
                    track = pcbnew.PCB_TRACK(board)
                    track.SetStart(pad.GetPosition())
                    track.SetEnd(pcbnew.VECTOR2I(kb.nm(10 + k), kb.nm(5)))
                    track.SetWidth(kb.nm(0.15))
                    track.SetLayer(pcbnew.F_Cu)
                    track.SetNet(nets[f"N{k}"])
                    board.Add(track)
        return fr.FreeroutingResult(dsn=work_dir / "board.dsn", ses=work_dir / "board.ses", log=work_dir / "run.log",
                                    rules=None, renamed=0, exits=tuple(sorted(stub_pads or ())))

    monkeypatch.setattr(fr, "route_board", stand_in)
    work = tmp_path / "work"
    work.mkdir()

    def finish(board, work_dir):
        out = work_dir / "routed.kicad_pcb"
        kb.save_board(board, out)
        return out

    out, results = fr.route_rounds(problem, RULES, work, finish, rounds=4)
    assert seen == [set(), {"U1-1", "U1-2", "U1-4", "U1-5"}]  # pad 3's exit is blocked by the resistor pad
    assert len(results) == 2 and results[-1].exits == ("U1-1", "U1-2", "U1-4", "U1-5")
    assert set(kb.open_nets(kb.load_board(out))) == {"N2", "N5"}  # no stub can help these: the loop ended
    assert (work / "round-1" / "board.ses").read_text() == "stand-in" and (work / "board.ses").is_file()
    assert not (work / "round-2").exists()  # the last round's files stay in the work directory


def test_fine_pitch_plane_pins_are_left_to_their_layers_pour():
    """D95: a 0.5 mm package's pin on a net that pours on the pin's layer gets no feed and leaves the router's
    network; a pin of a net with no pour there, a passive's pad and a thermal pad do not."""
    b = _qfn_board(edge_y=-8.0)
    pours = [{"net": "N0", "layer": "F.Cu"}, {"net": "N1", "layer": "B.Cu"}]
    left = fr.pour_pins(b, pours, {"N0", "N1", "N5"})
    assert left == {"U1-1"}  # N0 pours on F.Cu where pad 1 sits; N1 pours on B.Cu only; N5 is the thermal pad
    assert fr.pour_pins(b, [], {"N0"}) == set()
    from tests.test_planes import RULES
    from waffle_eda.route import planes
    feeds = planes.plane_feeds(b, RULES, {"N0", "N1"}, skip=left)
    assert "U1-1" not in {f.pad for f in feeds} and "U1-2" in {f.pad for f in feeds}


def test_the_autoroute_settings_block_follows_the_boundary_in_the_jars_own_form():
    """D96: trace costs raised on a plane's layer through the DSN, every layer active, the block after the boundary
    and before the first plane or keepout, which the loader reads only in that order."""
    dsn = ('(pcb "x"\n  (structure\n    (layer F.Cu\n      (type signal)\n    )\n    (layer In1.Cu\n      (type signal)\n    )\n'
           '    (boundary\n      (path pcb 0  0 0  1000 0)\n    )\n    (plane GND (polygon In1.Cu 0  0 0  1000 0))\n'
           '    (keepout "" (circle F.Cu 100 0 0))\n    (via "Via[0-1]_600:300_um")\n    (rule\n      (width 150)\n'
           '      (clearance 140.7)\n    )\n  )\n  (placement\n  )\n)')
    out = fr.autoroute_settings_dsn(dsn, ["F.Cu", "In1.Cu"], {"In1.Cu": 30.0}, via_costs=1)
    assert out.index("(boundary") < out.index("(autoroute_settings") < out.index("(plane GND") < out.index("(keepout")
    assert out.index("      (path pcb 0  0 0  1000 0)\n    )\n    (autoroute_settings\n") > 0
    assert "(layer_rule In1.Cu\n        (active on)\n        (preferred_direction horizontal)\n        (preferred_direction_trace_costs 30.0)\n        (against_preferred_direction_trace_costs 30.0)" in out
    assert "(layer_rule F.Cu\n        (active on)\n        (preferred_direction vertical)\n        (preferred_direction_trace_costs 1.0)\n        (against_preferred_direction_trace_costs 2.5)" in out
    assert "(via_costs 1)" in out and "(plane_via_costs 5)" in out
