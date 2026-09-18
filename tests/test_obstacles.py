"""The obstacle index answers copper-to-copper and hole-to-copper clearance for tracks, vias and through-hole pads
on an in-memory board, so the hole rule is exercised without a fetched reference."""
import pcbnew
import pytest

from waffle_eda.kicad import board as kb
from waffle_eda.route.obstacles import Obstacles


def _board():
    board = pcbnew.BOARD()
    nets = {}
    for name in ("A", "B"):
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net
    return board, nets


def _via(board, net, x_mm, y_mm, drill_mm=0.2, diameter_mm=0.4):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(kb.nm(x_mm), kb.nm(y_mm)))
    v.SetDrill(kb.nm(drill_mm))
    kb.set_via_diameter(v, diameter_mm)
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNet(net)
    return v


def _track(board, net, x_mm, width_mm=0.1, layer=pcbnew.F_Cu):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(kb.nm(x_mm), kb.nm(-1.0)))
    t.SetEnd(pcbnew.VECTOR2I(kb.nm(x_mm), kb.nm(1.0)))
    t.SetWidth(kb.nm(width_mm))
    t.SetLayer(layer)
    t.SetNet(net)
    return t


def _pth_pad(board, net, x_mm, y_mm, drill_mm=0.2, size_mm=0.4):
    fp = pcbnew.FOOTPRINT(board)
    fp.SetReference("J1")
    fp.SetPosition(pcbnew.VECTOR2I(kb.nm(x_mm), kb.nm(y_mm)))
    pad = pcbnew.PAD(fp)
    pad.SetNumber("1")
    pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    pad.SetSize(pcbnew.VECTOR2I(kb.nm(size_mm), kb.nm(size_mm)))
    pad.SetDrillSize(pcbnew.VECTOR2I(kb.nm(drill_mm), kb.nm(drill_mm)))
    pad.SetLayerSet(pad.PTHMask())
    pad.SetPosition(pcbnew.VECTOR2I(kb.nm(x_mm), kb.nm(y_mm)))
    pad.SetNet(net)
    fp.Add(pad)
    board.Add(fp)
    return pad


# Geometry of every case: the hole is 0.2 mm (wall at 0.1 mm from centre), the copper ring reaches 0.2 mm, and the
# other net's track edge is at 0.3 mm: 0.1 mm copper to copper, 0.2 mm hole wall to copper.
COPPER_GAP, HOLE_GAP = 0.1, 0.2


def test_other_via_hole_against_our_track():
    board, nets = _board()
    board.Add(_via(board, nets["A"], 0, 0))
    obs = Obstacles(board)
    track = _track(board, nets["B"], 0.35)
    assert obs.clear(track, COPPER_GAP - 0.01) is None
    assert obs.clear(track, COPPER_GAP + 0.01) is not None
    assert obs.clear(track, COPPER_GAP - 0.01, hole_clearance_mm=HOLE_GAP - 0.01) is None
    assert obs.clear(track, COPPER_GAP - 0.01, hole_clearance_mm=HOLE_GAP + 0.01) is not None


def test_our_via_hole_against_other_track():
    board, nets = _board()
    board.Add(_track(board, nets["B"], 0.35))
    obs = Obstacles(board)
    via = _via(board, nets["A"], 0, 0)
    assert obs.clear(via, COPPER_GAP - 0.01) is None
    assert obs.clear(via, COPPER_GAP - 0.01, hole_clearance_mm=HOLE_GAP - 0.01) is None
    assert obs.clear(via, COPPER_GAP - 0.01, hole_clearance_mm=HOLE_GAP + 0.01) is not None


def test_through_hole_pad_against_our_track_and_via():
    board, nets = _board()
    _pth_pad(board, nets["A"], 0, 0)
    obs = Obstacles(board)
    track = _track(board, nets["B"], 0.35)
    assert obs.clear(track, COPPER_GAP - 0.01, hole_clearance_mm=HOLE_GAP - 0.01) is None
    assert obs.clear(track, COPPER_GAP - 0.01, hole_clearance_mm=HOLE_GAP + 0.01) is not None
    # our via 0.7 mm away: copper gap 0.3, its hole wall to the pad's copper 0.4, the pad's hole wall to its ring 0.4
    via = _via(board, nets["B"], 0.7, 0)
    assert obs.clear(via, 0.29, hole_clearance_mm=0.39) is None
    assert obs.clear(via, 0.29, hole_clearance_mm=0.41) is not None


def test_same_net_is_not_an_obstacle():
    board, nets = _board()
    board.Add(_via(board, nets["A"], 0, 0))
    obs = Obstacles(board)
    assert obs.clear(_track(board, nets["A"], 0.1), 0.5, hole_clearance_mm=0.5) is None
