"""The structural rules the references taught us (D31, D32): where a via may sit inside a pad array, how a board's
escape style is measured, and that the router obeys the style it is given."""
import pcbnew
import pytest

from waffle_eda.bench import bus_design, synthetic
from waffle_eda.kicad import board as kb
from waffle_eda.route import bus as busr
from waffle_eda.route.lattice import Lattice

DIAGONAL = ((0.0, 0.0), (0.5, 0.5), (0.5, -0.5), (-0.5, 0.5), (-0.5, -0.5))


def _graph(board, rules, parts=("U1", "U2")):
    lats = [Lattice(kb.footprint(board, r)) for r in parts]
    fps = {r: kb.package_info(kb.footprint(board, r)) for r in parts}
    layer_ids = {name: lid for lid, name in kb.copper_layers(board)}
    layers = [layer_ids[n] for n in rules.layers if n in layer_ids]
    boxes = [fp.bbox_mm for fp in fps.values()]
    m = rules.margin_mm
    region = (min(b[0] for b in boxes) - m, min(b[1] for b in boxes) - m,
              max(b[2] for b in boxes) + m, max(b[3] for b in boxes) + m)
    return busr.BusGraph(board, lats, rules, layers, pcbnew.F_Cu, region, fps), lats


def _offsets_of_via_sites(g, lat):
    """Every via site inside a ball's cell of this package, as its offset from that ball in pitches."""
    out = set()
    for node, (x, y) in enumerate(g.xy):
        if not g.via_site[node]:
            continue
        fi, fj = (x - lat.x0) / lat.pitch, (y - lat.y0) / lat.pitch
        i, j = round(fi), round(fj)
        if abs(fi - i) > 0.5 + 1e-9 or abs(fj - j) > 0.5 + 1e-9 or (i, j) not in lat.by_index:
            continue
        out.add((round(fi - i, 2), round(fj - j, 2)))
    return out


@pytest.fixture
def pair(tmp_path):
    case = synthetic.CASES["pair-9x16-straight"]
    path = tmp_path / "pair.kicad_pcb"
    manifest = synthetic.make_bga_pair(case, path)
    board = kb.load_board(path)
    names = [n for _, n in kb.copper_layers(board)]
    rules = busr.BusRules(track_mm=case.track_mm, clearance_mm=case.clearance_mm, via_mm=case.via_mm,
                          via_drill_mm=case.via_drill_mm, layers=tuple(names), margin_mm=3.0,
                          hole_clearance_mm=case.clearance_mm)
    return board, rules, manifest


def test_without_a_style_the_channel_between_two_balls_is_a_via_site(pair):
    """The router's own default: every half-pitch node inside the array may take a via, the edge midpoints
    between two neighbouring balls included. This is the behaviour D32 found in our boards and not in the
    references, so the rule below has something to remove."""
    board, rules, _ = pair
    g, lats = _graph(board, rules)
    offsets = _offsets_of_via_sites(g, lats[0])
    assert (0.5, 0.0) in offsets or (0.0, 0.5) in offsets


def test_a_package_style_keeps_the_vias_off_the_channel_between_balls(pair):
    """Both references put a via in a ball's cell only on the ball or on a diagonal corner, never on the edge
    midpoint, which is the channel its neighbours escape through (D32)."""
    board, rules, _ = pair
    rules = busr.BusRules(**{**rules.__dict__, "ball_via_offsets": {"U1": DIAGONAL, "U2": DIAGONAL}})
    g, lats = _graph(board, rules)
    for lat in lats:
        offsets = _offsets_of_via_sites(g, lat)
        assert offsets, "a diagonal style must leave the corners usable"
        assert offsets <= {(round(a, 2), round(b, 2)) for a, b in DIAGONAL}
        assert (0.5, 0.0) not in offsets and (0.0, 0.5) not in offsets


def test_an_in_pad_style_leaves_no_via_site_off_the_ball(pair):
    """ButterStick's U4 and U11: every via in the array sits on a ball, so nothing else in the array is a site."""
    board, rules, _ = pair
    rules = busr.BusRules(**{**rules.__dict__, "ball_via_offsets": {"U1": ((0.0, 0.0),)},
                             "in_pad_packages": ("U1",)})
    g, lats = _graph(board, rules)
    assert _offsets_of_via_sites(g, lats[0]) <= {(0.0, 0.0)}


def test_an_empty_style_forbids_every_via_in_the_array(pair):
    board, rules, _ = pair
    rules = busr.BusRules(**{**rules.__dict__, "ball_via_offsets": {"U1": ()}})
    g, lats = _graph(board, rules)
    assert _offsets_of_via_sites(g, lats[0]) == set()


def test_the_escape_style_is_measured_from_a_board(pair, tmp_path):
    """What ``escape_style`` reads back: vias placed on a diagonal corner of their ball come back as that offset,
    and a via far from any ball is not part of a package's style."""
    board, rules, manifest = pair
    lat = Lattice(kb.footprint(board, "U1"))
    nets = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() in manifest["bus"]:
                nets.setdefault(pad.GetNetname(), pad.GetNet())
    placed = 0
    balls = [(k, b) for k, b in sorted(lat.by_index.items()) if b.net in nets]
    for (i, j), ball in balls[:6]:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(kb.nm(lat.X(i) + lat.pitch / 2), kb.nm(lat.Y(j) - lat.pitch / 2)))
        v.SetWidth(kb.nm(0.4))
        v.SetDrill(kb.nm(0.2))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(nets[ball.net])
        board.Add(v)
        placed += 1
    assert placed, "the synthetic pair must give some balls a bus net"
    out = tmp_path / "styled.kicad_pcb"
    kb.save_board(board, out)

    class Ref:  # the measurement takes a reference's net pattern and its bus parts
        bus_net_pattern = r"^BUS"
        bus_parts = ("U1", "U2")

    style = bus_design.escape_style(kb.load_board(out), Ref())
    assert style["U1"]["vias"] == placed
    assert style["U1"]["places"] == {"on a corner": placed}  # a dog-bone into the widest gap of the lattice
    assert set(style["U1"]["offsets"]) == {(0.5, 0.5), (0.5, -0.5), (-0.5, 0.5), (-0.5, -0.5)}
    st = bus_design.structure(kb.load_board(out), Ref())
    assert st["vias_between_balls"] == placed


def test_a_via_in_the_channel_between_two_balls_is_read_as_such(pair, tmp_path):
    """The place a reference never uses: half a pitch along a row, where the neighbouring balls escape."""
    board, _, manifest = pair
    lat = Lattice(kb.footprint(board, "U1"))
    nets = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() in manifest["bus"]:
                nets.setdefault(pad.GetNetname(), pad.GetNet())
    balls = [(k, b) for k, b in sorted(lat.by_index.items()) if b.net in nets]
    (i, j), ball = balls[0]
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(kb.nm(lat.X(i) + lat.pitch / 2), kb.nm(lat.Y(j))))
    v.SetWidth(kb.nm(0.4))
    v.SetDrill(kb.nm(0.2))
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNet(nets[ball.net])
    board.Add(v)
    out = tmp_path / "channel.kicad_pcb"
    kb.save_board(board, out)

    class Ref:
        bus_net_pattern = r"^BUS"
        bus_parts = ("U1", "U2")

    style = bus_design.escape_style(kb.load_board(out), Ref())
    assert style["U1"]["places"] == {"in the channel": 1}


def test_the_via_budget_keeps_one_for_each_leg_still_to_route():
    """A net whose tree has several legs must not let the first leg spend the whole budget: the references give
    each leg its own layer change, one via at each package (D32). The net's own copper has already spent one of
    the three vias here (the fan-out's in-pad via), so two are left for two legs."""
    budget, per_leg = 3 - 1, 2
    assert busr.leg_budget(budget, 0, 2, per_leg) == 1  # two legs to go: one via held back for the second
    assert busr.leg_budget(budget, 1, 1, per_leg) == 1  # the last leg may spend what is left
    assert busr.leg_budget(budget, 0, 1, per_leg) == 2  # a single leg may use the per-leg limit
    assert busr.leg_budget(budget, 2, 1, per_leg) == 0  # nothing left
    assert busr.leg_budget(None, 9, 3, per_leg) == per_leg  # no per-net limit: the per-leg limit stands


def test_the_sites_a_package_offers_follow_its_style(pair):
    """What the structural planner has to hand out (D29): the hollow cells, plus the ball or corner positions the
    package's style allows. A corner is only a site when every ball whose cell holds it allows that offset."""
    board, _, _ = pair

    class Ref:
        bus_net_pattern = r"^BUS"
        bus_parts = ("U1", "U2")

    lat = Lattice(kb.footprint(board, "U1"))
    corners = bus_design.via_sites(board, Ref(), {"U1": {"offsets": DIAGONAL[1:]}, "U2": {"offsets": ()}})
    assert corners["U1"]["ball"] == [], "a corner style puts no via on a ball"
    assert corners["U1"]["corner"], "a corner style must offer the corners"
    assert corners["U2"]["corner"] == [] and corners["U2"]["ball"] == []
    assert corners["U2"]["capacity"] == len(corners["U2"]["hollow"])

    in_pad = bus_design.via_sites(board, Ref(), {"U1": {"offsets": ((0.0, 0.0),)}})
    assert in_pad["U1"]["corner"] == []
    assert len(in_pad["U1"]["ball"]) == len(lat.by_index)

    # every corner offered sits half a pitch diagonally from a ball, never in a channel between two
    for (x, y) in corners["U1"]["corner"]:
        cells = bus_design.ball_cells(lat, x, y)
        assert cells, "a corner belongs to at least one ball's cell"
        assert all(abs(di) == 0.5 and abs(dj) == 0.5 for (_, _, _, di, dj) in cells)


def test_a_stalled_negotiation_stops_and_a_repair_budget_is_spent(tmp_path):
    """A run must end with a board and a score: the negotiation stops when it has not bettered its contested
    count for ``stall_stop`` rounds, and the repair stage stops when its budget is spent. Both are measured on
    the synthetic pair, where the router succeeds, so the settings must not change a good result."""
    case = synthetic.CASES["pair-6x6-straight"]
    path = tmp_path / "pair.kicad_pcb"
    manifest = synthetic.make_bga_pair(case, path)
    board = kb.load_board(path)
    names = [n for _, n in kb.copper_layers(board)]
    rules = busr.BusRules(track_mm=case.track_mm, clearance_mm=case.clearance_mm, via_mm=case.via_mm,
                          via_drill_mm=case.via_drill_mm, layers=tuple(names), margin_mm=3.0,
                          hole_clearance_mm=case.clearance_mm)
    costs = busr.Costs(stall_stop=3, repair_budget_s=30.0)
    res = busr.route_bus(board, ["U1", "U2"], set(manifest["bus"]), rules, costs=costs)
    assert not res.failed, res.summary() + " " + str(res.failed)
    assert res.counts["iterations"] <= costs.iterations
