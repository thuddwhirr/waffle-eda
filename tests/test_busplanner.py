"""The planner of M3a (decisions D37, D38): the mesh it routes on, the layers and styles it reads off the board,
and the plan it produces, which has to pass the gate of `test_busplan.py`.

The mesh carries the whole argument: crossing-freeness is not checked and repaired here, it follows from routing
node-disjoint paths on a grid whose lines only ever increase. So the first tests are of that property, and the
last is the one that matters -- a planned board passes the gate.
"""
import pytest

from waffle_eda.bench import references as refs, synthetic
from waffle_eda.kicad import board as kb
from waffle_eda.route import busplan as bp, busplanner as bpl


CLASS_C = [r.key for r in refs.REFERENCES.values() if r.has_bus and r.cls == "C"]

# What each reference's own bus uses, read off the board once (bus_design.reference_plan) and asserted here so a
# change to the rule that picks the layers has to face it.
BUS_LAYERS = {
    "orangecrab-r0.2.1": {"F.Cu", "In2.Cu", "B.Cu"},
    "logicbone": {"F.Cu", "B.Cu", "Sig1.Cu", "Sig2.Cu"},
    "butterstick": {"F.Cu", "In2.Cu", "In5.Cu", "B.Cu"},
}


class Ref:  # the synthetic pair, as a reference the planner understands
    key = "synthetic"
    cls = "C"
    bus_net_pattern = r"^BUS"
    bus_parts = ("U1", "U2")


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    path = tmp_path_factory.mktemp("plan") / "pair.kicad_pcb"
    synthetic.make_bga_pair(synthetic.CASES["pair-9x16-straight"], path)
    return kb.load_board(path)


def loaded(key):
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} is not fetched")
    return ref, kb.load_board(refs.board_path(ref))


@pytest.mark.parametrize("key", CLASS_C)
def test_the_layers_are_the_ones_the_board_routes_on(key):
    """A layer carrying almost no net but its own pour is a plane, and the bus does not cut it. The rule has to
    pick out the layers each reference's bus actually uses, because those are the board's signal layers."""
    ref, board = loaded(key)
    picked = {name for (_L, name, _n) in bpl.signal_layers(board, ref)}
    assert BUS_LAYERS[key] <= picked, f"{key}: the rule dropped a layer its own bus uses"
    assert picked == BUS_LAYERS[key], f"{key}: the rule kept a layer the bus does not use: {picked - BUS_LAYERS[key]}"


def test_a_board_with_nothing_routed_keeps_every_copper_layer(pair):
    """M6 starts from a board with no copper on it: the rule must not decide every layer is a plane."""
    picked = {name for (_L, name, _n) in bpl.signal_layers(pair, Ref())}
    assert picked == {name for _L, name in kb.copper_layers(pair)}


@pytest.mark.parametrize("key", CLASS_C)
def test_the_mesh_lines_only_increase(key):
    """The whole crossing argument rests on this: x grows with i and y with j, so the grid, however deformed by
    the packages' own pitches, is still a grid and orthogonal paths through disjoint nodes cannot cross."""
    ref, board = loaded(key)
    costs = bpl.PlanCosts()
    mesh = bpl.Mesh(board, ref, bpl.signal_layers(board, ref), costs)
    for lines in (mesh.X, mesh.Y):
        assert all(b > a for a, b in zip(lines, lines[1:])), "two lines of the mesh are out of order or equal"


@pytest.mark.parametrize("key", CLASS_C)
def test_every_ball_and_corner_of_every_package_is_a_node(key):
    """A via site the package's style allows has to be reachable, so the mesh carries each package's own
    half-pitch lines rather than rounding them to a step of its own."""
    ref, board = loaded(key)
    mesh = bpl.Mesh(board, ref, bpl.signal_layers(board, ref), bpl.PlanCosts())
    for pkg in mesh.packages:
        if pkg.lattice is None:
            continue
        for ball in pkg.lattice.balls.values():
            if not (mesh.region[0] <= ball.x_mm <= mesh.region[2]):
                continue
            assert abs(mesh.X[mesh.near_x(ball.x_mm)] - ball.x_mm) < 1e-3, f"{pkg.reference} ball {ball.number}"
            assert abs(mesh.Y[mesh.near_y(ball.y_mm)] - ball.y_mm) < 1e-3, f"{pkg.reference} ball {ball.number}"


@pytest.mark.parametrize("key", CLASS_C)
def test_a_package_the_board_escapes_keeps_its_measured_style(key):
    ref, board = loaded(key)
    measured = bp.styles_of(board, ref)
    for part, style in measured.items():
        assert style["vias"] > 0, f"{part} has no measured style on a board whose bus is routed"
        assert style is not bp.CROSS_BOARD_STYLE


def test_a_package_with_no_via_falls_back_to_the_cross_board_rule(pair):
    """D32: the ball or a corner between four balls, never the channel between two."""
    styles = bp.styles_of(pair, Ref())
    assert styles
    for part, style in styles.items():
        assert set(style["places"]) == {"on the ball", "on a corner"}, part


def test_the_planner_plans_the_synthetic_pair(pair):
    ref = Ref()
    plan = bpl.plan_bus(pair, ref, bpl.PlanCosts(rounds=12, budget_s=300))
    assert not plan.provenance["unrouted"], plan.provenance["unrouted"]
    findings = bp.check(plan, pair, ref)
    assert not findings, bp.report(findings)


@pytest.mark.parametrize("key", CLASS_C)
def test_the_planner_plans_a_reference(key):
    """M3a's criterion itself, one board at a time: `scripts/gate.py m3a` runs the same check over all of them."""
    ref, board = loaded(key)
    plan = bpl.plan_bus(board, ref)
    assert not plan.provenance["unrouted"], plan.provenance["unrouted"]
    findings = bp.check(plan, board, ref)
    assert not findings, bp.report(findings)
