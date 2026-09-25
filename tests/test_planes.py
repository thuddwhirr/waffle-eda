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
    # the via and its stub clear the signal pad next to it by the rule
    sig = [r for r in planes._rects(b) if r.net == b.GetNetsByName()["SIG"].GetNetCode() and r.centre[0] == 10.5][0]
    assert sig.distance(c1.via) >= 0.3 + 0.2
    assert all(f.via_mm == 0.6 and f.drill_mm == 0.3 and f.width_mm == 0.2 for f in feeds)


def test_feeds_are_laid_once_and_the_relay_adds_nothing():
    b = _board()
    feeds = planes.plane_feeds(b, RULES, {"GND"})
    made = planes.lay_feeds(b, feeds)
    assert len(made) == 3  # a via in the thermal pad; a stub and a via for the capacitor
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
    mark = _pad(fid, "1", nets["SIG"], 8.0, 0, 0.4, 0.4)  # beyond C1's exit; the via at 8.95 clears it by 0.55
    before = {f.pad: f for f in planes.plane_feeds(b, RULES, {"GND"})}["C1-1"].via
    assert before == (8.95, 0.0)
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
