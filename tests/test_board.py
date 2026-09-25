"""Board helpers, on a board built in memory: no reference files needed."""
import pcbnew
import pytest

from waffle_eda.kicad import board as kb


@pytest.fixture
def tiny_board(tmp_path):
    b = pcbnew.BOARD()
    net = pcbnew.NETINFO_ITEM(b, "SIG")
    b.Add(net)
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(pcbnew.VECTOR2I(kb.nm(0), kb.nm(0)))
    t.SetEnd(pcbnew.VECTOR2I(kb.nm(10), kb.nm(0)))
    t.SetWidth(kb.nm(0.2))
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(net)
    b.Add(t)
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(kb.nm(10), kb.nm(0)))
    v.SetDrill(kb.nm(0.2))
    kb.set_via_diameter(v, 0.45)
    v.SetNet(net)
    b.Add(v)
    path = tmp_path / "tiny.kicad_pcb"
    kb.save_board(b, path)
    return kb.load_board(path)


def test_units_roundtrip():
    assert kb.nm(1.234567) == 1_234_567
    assert kb.mm(kb.nm(0.45)) == pytest.approx(0.45)


def test_via_diameter_needs_no_bare_getwidth(tiny_board):
    vias = kb.vias(tiny_board)
    assert len(vias) == 1
    assert kb.via_diameter_mm(vias[0]) == pytest.approx(0.45)
    assert kb.via_drill_mm(vias[0]) == pytest.approx(0.2)


def test_net_copper(tiny_board):
    copper = kb.net_copper(tiny_board, ["SIG"])
    sig = copper["SIG"]
    assert sig.segments == 1
    assert sig.length_mm == pytest.approx(10.0)
    assert sig.via_count == 1
    assert sig.layers == ("F.Cu",)
    assert sig.track_widths_mm == ((0.2, 1),)


def test_histograms(tiny_board):
    assert kb.track_width_histogram_mm(tiny_board) == [(0.2, 1)]
    assert kb.via_size_histogram_mm(tiny_board) == [(0.45, 0.2, 1)]


def test_nets_matching(tiny_board):
    assert kb.nets_matching(tiny_board, r"^SIG$") == ["SIG"]
    assert kb.nets_matching(tiny_board, r"^DDR") == []


def test_open_nets_reads_kicads_connectivity_pads_tracks_and_fills(tmp_path):
    """D79: two pads of a net are open until a track joins them, and a filled zone joins them too; the count
    of missing links is KiCad's own, which the DRC report caps at about 500."""
    b = pcbnew.BOARD()
    b.GetDesignSettings().SetCopperLayerCount(2)
    sig = pcbnew.NETINFO_ITEM(b, "SIG")
    gnd = pcbnew.NETINFO_ITEM(b, "GND")
    b.Add(sig)
    b.Add(gnd)
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference("U1")
    b.Add(fp)
    pads = []
    for i, (x, net) in enumerate(((0.0, sig), (10.0, sig), (0.0, gnd), (10.0, gnd))):
        pad = pcbnew.PAD(fp)
        pad.SetNumber(str(i + 1))
        pad.SetShape(pcbnew.PAD_SHAPE_RECT)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetSize(pcbnew.VECTOR2I(kb.nm(1.0), kb.nm(1.0)))
        pad.SetLayerSet(pcbnew.PAD.SMDMask())
        pad.SetPosition(pcbnew.VECTOR2I(kb.nm(x), kb.nm(0.0 if net is sig else 5.0)))
        pad.SetNet(net)
        fp.Add(pad)
        pads.append(pad)
    for (ax, ay), (bx, by) in (((-2, -2), (12, -2)), ((12, -2), (12, 7)), ((12, 7), (-2, 7)), ((-2, 7), (-2, -2))):
        seg = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(kb.nm(ax), kb.nm(ay)))
        seg.SetEnd(pcbnew.VECTOR2I(kb.nm(bx), kb.nm(by)))
        seg.SetLayer(pcbnew.Edge_Cuts)
        b.Add(seg)
    path = tmp_path / "conn.kicad_pcb"
    kb.save_board(b, path)
    loaded = kb.load_board(path)
    assert kb.open_nets(loaded) == {"SIG": 2, "GND": 2} and kb.unconnected_count(loaded) == 2
    # a track joins SIG
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(pcbnew.VECTOR2I(kb.nm(0), kb.nm(0)))
    t.SetEnd(pcbnew.VECTOR2I(kb.nm(10), kb.nm(0)))
    t.SetWidth(kb.nm(0.3))
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(sig)
    b.Add(t)
    # a filled pour joins GND
    zone = pcbnew.ZONE(b)
    zone.SetNet(gnd)
    zone.SetLayer(pcbnew.F_Cu)
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in ((-1.5, 3.0), (11.5, 3.0), (11.5, 6.5), (-1.5, 6.5)):
        outline.Append(kb.nm(x), kb.nm(y))
    zone.SetLocalClearance(kb.nm(0.2))
    zone.SetMinThickness(kb.nm(0.25))
    b.Add(zone)
    kb.save_board(b, path)  # filled from its file in a child process: the filler segfaults on a board built in
    from waffle_eda.kicad import refill  # memory and never saved (as the router did in stage 5, D74)
    assert refill.refill_file(path)["unfilled_zones"] == []
    loaded = kb.load_board(path)
    assert kb.open_nets(loaded) == {} and kb.unconnected_count(loaded) == 0
