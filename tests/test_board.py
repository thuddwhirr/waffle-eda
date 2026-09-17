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
