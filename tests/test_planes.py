"""Plane feeds (route/planes.py, D85): a via beside every plane-net SMD pad with room, in a thermal pad, none
where the pad is hemmed in; laid once, re-laid idempotently."""
import math
from types import SimpleNamespace

import pcbnew

from waffle_eda.kicad import board as kb
from waffle_eda.route import planes

RULES = SimpleNamespace(clearance_mm=0.2, hole_to_copper_mm=0.25, edge_clearance_mm=0.3, min_track_mm=0.2,
                        min_via_mm=0.6, min_drill_mm=0.3)


def _pad(fp, number, net, x, y, w, h, smd=True, drill=0.0):
    pad = pcbnew.PAD(fp)
    pad.SetNumber(number)
    pad.SetShape(pcbnew.PAD_SHAPE_RECT)
    if smd:
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetLayerSet(pcbnew.PAD.SMDMask())
    else:
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetLayerSet(pcbnew.PAD.PTHMask())
        pad.SetDrillSize(pcbnew.VECTOR2I(kb.nm(drill), kb.nm(drill)))
    pad.SetSize(pcbnew.VECTOR2I(kb.nm(w), kb.nm(h)))
    pad.SetPosition(pcbnew.VECTOR2I(kb.nm(x), kb.nm(y)))
    pad.SetNet(net)
    fp.Add(pad)
    return pad


def _board():
    b = pcbnew.BOARD()
    b.GetDesignSettings().SetCopperLayerCount(4)
    nets = {}
    for name in ("GND", "SIG"):
        nets[name] = pcbnew.NETINFO_ITEM(b, name)
        b.Add(nets[name])
    u1 = pcbnew.FOOTPRINT(b)  # a package: a 3 mm thermal pad on GND ringed by signal pads
    u1.SetReference("U1")
    u1.SetPosition(pcbnew.VECTOR2I(0, 0))
    b.Add(u1)
    _pad(u1, "9", nets["GND"], 0, 0, 3.0, 3.0)
    for k in range(4):
        _pad(u1, str(k + 1), nets["SIG"], -1.5 + k, -2.5, 0.3, 0.9)
    c1 = pcbnew.FOOTPRINT(b)  # a chip capacitor: GND on one end, free space beyond it
    c1.SetReference("C1")
    c1.SetPosition(pcbnew.VECTOR2I(kb.nm(10), 0))
    b.Add(c1)
    _pad(c1, "1", nets["GND"], 9.5, 0, 0.6, 0.9)
    _pad(c1, "2", nets["SIG"], 10.5, 0, 0.6, 0.9)
    c2 = pcbnew.FOOTPRINT(b)  # a GND pad hemmed in by signal pads within the reach on every side
    c2.SetReference("C2")
    c2.SetPosition(pcbnew.VECTOR2I(kb.nm(20), 0))
    b.Add(c2)
    _pad(c2, "1", nets["GND"], 20, 0, 0.6, 0.6)
    for k, (dx, dy) in enumerate(((1.0, 0), (-1.0, 0), (0, 1.0), (0, -1.0))):
        _pad(c2, str(k + 2), nets["SIG"], 20 + dx * 1.2, dy * 1.2, 1.6 if dy else 0.4, 1.6 if dx else 0.4)
    for (ax, ay), (bx, by) in (((-6, -6), (26, -6)), ((26, -6), (26, 6)), ((26, 6), (-6, 6)), ((-6, 6), (-6, -6))):
        seg = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(kb.nm(ax), kb.nm(ay)))
        seg.SetEnd(pcbnew.VECTOR2I(kb.nm(bx), kb.nm(by)))
        seg.SetLayer(pcbnew.Edge_Cuts)
        b.Add(seg)
    return b


def test_feeds_go_in_a_thermal_pad_beside_a_free_pad_and_nowhere_when_hemmed_in():
    b = _board()
    feeds = planes.plane_feeds(b, RULES, {"GND"})
    by_pad = {f.pad: f for f in feeds}
    assert set(by_pad) == {"U1-9", "C1-1"}
    assert by_pad["U1-9"].in_pad and by_pad["U1-9"].via == (0.0, 0.0)
    c1 = by_pad["C1-1"]
    assert not c1.in_pad and c1.via[0] < 9.5 and abs(c1.via[1]) < 1e-9  # away from the part, along its axis
    assert c1.length_mm <= planes.REACH_MM
    assert c1.via[0] + 0.3 <= 9.5 - 0.3 - 0.2  # the clearance from its own pad's edge, as the router wants
    # the via and its stub clear the signal pad next to it by the rule
    sig = [r for r in planes._rects(b) if r.net == b.GetNetsByName()["SIG"].GetNetCode() and r.centre[0] == 10.5][0]
    assert sig.distance(c1.via) >= 0.3 + 0.2
    assert all(f.via_mm == 0.6 and f.drill_mm == 0.3 and f.width_mm == 0.2 for f in feeds)


def test_feeds_are_laid_once_and_the_relay_adds_nothing():
    b = _board()
    feeds = planes.plane_feeds(b, RULES, {"GND"})
    assert len(planes.lay_feeds(b, feeds, in_pad=False)) == 2  # the router's view: no via in the thermal pad
    made = planes.lay_feeds(b, feeds)
    assert len(made) == 1  # the via in the thermal pad, after the import
    assert len(kb.vias(b)) == 2 and len(kb.track_segments(b)) == 1
    assert planes.lay_feeds(b, feeds) == []
    via = [v for v in kb.vias(b) if v.GetNetname() == "GND" and kb.mm(v.GetPosition().x) < 9.5][0]
    assert math.isclose(kb.via_diameter_mm(via), 0.6) and math.isclose(kb.via_drill_mm(via), 0.3)
    # a dropped via comes back alone
    b.Delete(via)
    assert len(planes.lay_feeds(b, feeds)) == 1


def test_a_pads_own_clearance_is_honoured():
    """A pad in the exit's way with its own clearance (a fiducial's 0.375 mm on upduino) pushes the via off."""
    b = _board()
    nets = b.GetNetsByName()
    fid = pcbnew.FOOTPRINT(b)
    fid.SetReference("FID1")
    fid.SetPosition(pcbnew.VECTOR2I(kb.nm(8.0), 0))
    b.Add(fid)
    mark = _pad(fid, "1", nets["SIG"], 7.8, 0, 0.4, 0.4)  # beyond C1's exit; the via at 8.69 clears it by 0.39
    before = {f.pad: f for f in planes.plane_feeds(b, RULES, {"GND"})}["C1-1"].via
    assert before == (8.69, 0.0)
    mark.SetLocalClearance(kb.nm(0.5))
    after = {f.pad: f for f in planes.plane_feeds(b, RULES, {"GND"})}["C1-1"].via
    rect = [r for r in planes._rects(b) if r.local > 0][0]
    assert after != before and rect.distance(after) >= 0.3 + 0.5


def test_a_hole_keeps_the_via_away():
    b = _board()
    nets = b.GetNetsByName()
    j1 = pcbnew.FOOTPRINT(b)
    j1.SetReference("J1")
    j1.SetPosition(pcbnew.VECTOR2I(kb.nm(8), 0))
    b.Add(j1)
    _pad(j1, "1", nets["SIG"], 8.3, 0, 1.2, 1.2, smd=False, drill=0.8)  # a through-hole pin beside C1's exit
    feeds = {f.pad: f for f in planes.plane_feeds(b, RULES, {"GND"})}
    assert "C1-1" in feeds
    via = feeds["C1-1"].via
    hole_edge = math.hypot(via[0] - 8.3, via[1]) - 0.4
    assert hole_edge >= 0.3 + 0.25 and math.hypot(via[0] - 8.3, via[1]) - 0.6 >= 0.3 + 0.2


def test_pieces_follow_kicads_connectivity_and_stitch_feeds_every_piece_but_the_largest(tmp_path):
    """D85: a plane net's pads grouped by what joins them; the stitch gives each piece beyond the largest one
    feed, so a refill of the plane joins it."""
    b = _board()
    path = tmp_path / "pieces.kicad_pcb"
    kb.save_board(b, path)
    loaded = kb.load_board(path)
    groups = planes.pieces(loaded, "GND")
    assert sorted(sorted(g) for g in groups) == [["C1-1"], ["C2-1"], ["U1-9"]]
    laid = planes.stitch(loaded, RULES, {"GND"})
    # three pieces of one pad each: the first by name, C1-1, stands for the plane; U1-9 (the thermal pad)
    # gets its via in the pad; C2-1 is hemmed in and stays a piece
    assert [f.pad for f in laid] == ["U1-9"] and laid[0].in_pad
    assert all(planes._via_at(loaded, f) is not None for f in laid)
    # a track joining two pads makes them one piece
    t = pcbnew.PCB_TRACK(loaded)
    t.SetStart(pcbnew.VECTOR2I(kb.nm(0), kb.nm(0)))
    t.SetEnd(pcbnew.VECTOR2I(kb.nm(9.5), kb.nm(0)))
    t.SetWidth(kb.nm(0.2))
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(loaded.GetNetsByName()["GND"])
    loaded.Add(t)
    loaded.BuildConnectivity()
    assert len(planes.pieces(loaded, "GND")) == 2


def test_another_nets_pour_keeps_a_stitch_via_out(tmp_path):
    """On a routed board the fills are copper too: a via may not land in another net's pour."""
    from waffle_eda.kicad import refill
    b = _board()
    nets = b.GetNetsByName()
    zone = pcbnew.ZONE(b)  # a SIG pour over the free space left of C1, where its feed would go
    zone.SetNet(nets["SIG"])
    zone.SetLayer(pcbnew.F_Cu)
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in ((6.0, -2.0), (8.2, -2.0), (8.2, 2.0), (6.0, 2.0)):
        outline.Append(kb.nm(x), kb.nm(y))
    zone.SetLocalClearance(kb.nm(0.2))
    zone.SetMinThickness(kb.nm(0.2))
    b.Add(zone)
    path = tmp_path / "pour.kicad_pcb"
    kb.save_board(b, path)
    assert refill.refill_file(path)["unfilled_zones"] == []
    loaded = kb.load_board(path)
    assert any(z.GetFilledPolysList(pcbnew.F_Cu).OutlineCount() for z in loaded.Zones())
    feeds = {f.pad: f for f in planes.plane_feeds(loaded, RULES, {"GND"}, copper=True)}
    assert "C1-1" in feeds and feeds["C1-1"].via != (8.69, 0.0)  # the pour took the spot the bare board gave
    fill = [z for z in loaded.Zones() if z.GetNetname() == "SIG"][0].GetFilledPolysList(pcbnew.F_Cu)
    via = feeds["C1-1"].via
    assert not fill.Collide(pcbnew.VECTOR2I(kb.nm(via[0]), kb.nm(via[1])), kb.nm(0.3 + 0.2))


def test_feeds_keep_clear_of_copper_already_on_the_board_when_asked():
    """A fixed exit stub of another net laid before the feeds (the closure loop's, D86): placed against the pads
    alone a feed lands on it; placed with the board's copper as obstacles it slides clear."""
    b = _board()
    nets = b.GetNetsByName()
    blind = {f.pad: f for f in planes.plane_feeds(b, RULES, {"GND"})}["C1-1"].via
    track = pcbnew.PCB_TRACK(b)  # a signal track right across C1's exit, where the blind feed's via sits
    track.SetStart(pcbnew.VECTOR2I(kb.nm(blind[0]), kb.nm(-2.0)))
    track.SetEnd(pcbnew.VECTOR2I(kb.nm(blind[0]), kb.nm(2.0)))
    track.SetWidth(kb.nm(0.2))
    track.SetLayer(pcbnew.F_Cu)
    track.SetNet(nets["SIG"])
    b.Add(track)
    assert {f.pad: f for f in planes.plane_feeds(b, RULES, {"GND"})}["C1-1"].via == blind  # pads only: unmoved
    seeing = {f.pad: f for f in planes.plane_feeds(b, RULES, {"GND"}, copper=True)}["C1-1"]
    assert seeing.via != blind
    assert abs(seeing.via[0] - blind[0]) >= 0.3 + 0.1 + 0.2 - 1e-9  # the via's radius, the track's half width, the rule

