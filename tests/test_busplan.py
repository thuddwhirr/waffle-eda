"""The M3a gate (decisions D37, D38): what a bus plan is and what the check must catch.

The first test is the answer key. Every class C reference's own routing, read back as a plan, must pass the check;
if it does not, the gate is wrong before any planner is. The rest give the check a plan with one thing wrong in it
and assert that it says so.
"""
import pytest

from waffle_eda.bench import references as refs, synthetic
from waffle_eda.kicad import board as kb
from waffle_eda.route import busplan as bp


CLASS_C = [r.key for r in refs.REFERENCES.values() if r.has_bus and r.cls == "C"]


@pytest.mark.parametrize("key", CLASS_C)
def test_a_reference_passes_its_own_gate(key):
    """The answer key: a board that was manufactured and works is a plan that must pass."""
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} is not fetched")
    board = kb.load_board(refs.board_path(ref))
    plan = bp.from_reference(board, ref)
    assert plan.legs, "a reference must read back as a plan with legs"
    findings = bp.check(plan, board, ref)
    assert not findings, bp.report(findings)


class Ref:  # the synthetic pair, as a reference the measurements understand
    key = "synthetic"
    cls = "C"
    bus_net_pattern = r"^BUS"
    bus_parts = ("U1", "U2")


@pytest.fixture
def pair(tmp_path):
    """The synthetic pair with a plain plan over it: one leg per net, U1's ball straight to U2's."""
    case = synthetic.CASES["pair-9x16-straight"]
    path = tmp_path / "pair.kicad_pcb"
    manifest = synthetic.make_bga_pair(case, path)
    board = kb.load_board(path)
    pads = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() in manifest["bus"]:
                p = pad.GetPosition()
                pads.setdefault(pad.GetNetname(), {})[fp.GetReference()] = (
                    f"{fp.GetReference()}.{pad.GetNumber()}", kb.mm(p.x), kb.mm(p.y))
    legs = []
    for net, ends in pads.items():
        if len(ends) != 2:
            continue
        (la, xa, ya), (lb, xb, yb) = ends["U1"], ends["U2"]
        legs.append(bp.Leg(net=net, a=bp.Site("pad", xa, ya, package="U1", label=la),
                           b=bp.Site("pad", xb, yb, package="U2", label=lb),
                           layer="In1.Cu", route=[(xa, ya), (xb, yb)]))
    return board, bp.BusPlan(board="synthetic", legs=legs)


def kinds(findings):
    return {f.kind for f in findings}


def test_a_plain_plan_over_the_synthetic_pair_passes(pair):
    board, plan = pair
    findings = bp.check(plan, board, Ref())
    assert not findings, bp.report(findings)


def test_a_net_with_no_leg_is_caught(pair):
    board, plan = pair
    plan.legs = [leg for leg in plan.legs if leg.net != plan.legs[0].net]
    assert "unplanned" in kinds(bp.check(plan, board, Ref()))


def test_a_net_left_in_pieces_is_caught(pair):
    board, plan = pair
    leg = plan.legs[0]
    leg.b = bp.Site("via", leg.b.x + 5.0, leg.b.y + 5.0, label="via@nowhere")  # no longer reaches its ball
    assert {"in pieces", "escape missing"} <= kinds(bp.check(plan, board, Ref()))


def test_two_legs_of_one_layer_crossing_are_caught(pair):
    """A real X: each leg keeps its own two terminals and still swaps sides of the other midway."""
    board, plan = pair
    rows = sorted(plan.legs, key=lambda leg: (leg.a.y, leg.a.x))
    a, b = rows[0], next(leg for leg in rows if leg.a.y > rows[0].a.y + 0.1)  # two legs on different rows
    mid = (a.a.x + a.b.x) / 2
    a.route = [(a.a.x, a.a.y), (mid, b.a.y), (a.b.x, a.b.y)]  # dips into b's row and comes back
    b.route = [(b.a.x, b.a.y), (mid, a.a.y), (b.b.x, b.b.y)]  # rises into a's row and comes back
    findings = bp.check(plan, board, Ref())
    assert "crossing" in kinds(findings), bp.report(findings)


def test_a_route_that_does_not_reach_its_terminal_is_caught(pair):
    board, plan = pair
    leg = plan.legs[0]
    leg.route = [(leg.a.x + 9.0, leg.a.y + 9.0), (leg.b.x, leg.b.y)]
    assert "route adrift" in kinds(bp.check(plan, board, Ref()))


def test_two_legs_side_by_side_are_not_a_crossing(pair):
    """Two runs a track apart share a corridor for millimetres; only a real intersection is a crossing."""
    board, plan = pair
    a, b = plan.legs[0], plan.legs[1]
    b.route = [(x, y + 0.2) for (x, y) in a.route]
    assert "crossing" not in kinds(bp.check(plan, board, Ref()))


def test_a_via_site_used_by_two_nets_is_caught(pair):
    board, plan = pair
    site = bp.Site("via", plan.legs[0].a.x + 1.0, plan.legs[0].a.y + 1.0, label="via@shared")
    for leg in plan.legs[:2]:
        leg.route = [(site.x, site.y), (leg.b.x, leg.b.y)]
        leg.a = site
    findings = bp.check(plan, board, Ref())
    assert "site shared" in kinds(findings)


def test_a_via_off_the_package_style_is_caught(pair):
    """A package whose style is the ball itself may not take a via on a corner between four balls."""
    board, plan = pair
    leg = plan.legs[0]
    leg.a = bp.Site("via", leg.a.x, leg.a.y, package="U1", label=leg.a.label, place="on a corner")
    findings = bp.check(plan, board, Ref(), styles={"U1": {"offsets": ((0.0, 0.0),), "places": {"on the ball": 1}},
                                                   "U2": {"offsets": ((0.0, 0.0),), "places": {"on the ball": 1}}})
    assert "site off style" in kinds(findings)


def test_a_length_deficit_with_no_room_is_caught(pair):
    board, plan = pair
    plan.deficit_mm = {plan.legs[0].net: 4.0}
    assert "no room" in kinds(bp.check(plan, board, Ref()))
    plan.legs[0].reserved_mm = 4.0
    assert "no room" not in kinds(bp.check(plan, board, Ref()))
