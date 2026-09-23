"""The bus planner: crossings between cell paths, capacities from fixed copper, and the negotiation's layer choice."""
import pcbnew

from waffle_eda.route import plan as planr


def test_crossing_through_one_shared_cell():
    P = [(0, 1), (1, 1), (2, 1), (3, 1)]
    Q = [(2, 0), (2, 1), (2, 2), (2, 3)]
    assert len(planr.path_crossings(P, Q)) == 1
    assert len(planr.path_crossings(P, Q[::-1])) == 1  # direction does not matter


def test_swapping_sides_over_a_shared_stretch_is_a_crossing():
    P = [(0, 1), (1, 1), (2, 1), (3, 1), (3, 2)]
    Q = [(1, 2), (1, 1), (2, 1), (3, 1), (3, 0)]
    assert len(planr.path_crossings(P, Q)) == 1


def test_leaving_across_the_other_is_a_crossing():
    # Q enters the shared column from the left and goes on ahead; P enters from behind and leaves to the left
    P = [(0, 0), (1, 0), (1, 1), (1, 2), (0, 2)]
    Q = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3)]
    assert len(planr.path_crossings(P, Q)) == 1


def test_side_by_side_is_no_crossing():
    P = [(1, 0), (1, 1), (2, 1), (3, 1), (3, 0)]
    Q = [(1, 2), (1, 1), (2, 1), (3, 1), (3, 2)]
    assert planr.path_crossings(P, Q) == []
    assert planr.path_crossings(P, Q[::-1]) == []
    # both come from the left and leave to the left, one inside the other
    P = [(0, 0), (1, 0), (1, 1), (1, 2), (1, 3), (0, 3)]
    Q = [(0, 1), (1, 1), (1, 2), (0, 2)]
    assert planr.path_crossings(P, Q) == []


def test_a_terminal_on_the_other_route_is_no_crossing():
    assert planr.path_crossings([(2, 1), (3, 1)], [(2, 0), (2, 1), (2, 2)]) == []


def _empty_cells(region, layers, track=0.1, clearance=0.1, cell=0.4):
    board = pcbnew.BOARD()
    fixed = planr.Fixed(board, region, layers)
    return planr.Cells(region, layers, fixed, track, clearance, cell_mm=cell)


def test_capacity_counts_tracks_between_vias():
    """A via field at 0.8 mm pitch with 0.4 mm vias leaves 0.134 mm for track centres between two vias under
    0.0889/0.0886 rules: one track per channel, none through a via, two where the grid step allows it."""
    board = pcbnew.BOARD()
    region = (0.0, 0.0, 8.0, 8.0)
    L = pcbnew.In1_Cu
    fixed = planr.Fixed(board, region, [L])
    for i in range(2, 8):
        for j in range(2, 8):
            fixed._add_circle(L, i * 0.8 + 0.4, j * 0.8 + 0.4, 0.2, "GND")  # via centres on cell corners
    cells = planr.Cells(region, [L], fixed, 0.0889, 0.0886, cell_mm=0.4)
    # a cell in the field: its boundaries on the via lines (x = 2.0 and y = 2.8) hold one track, the gap between
    # two vias; the boundaries on the mid-lines between via rows hold more, but no route reaches them without
    # crossing a via line
    i, j = cells.cell_of(2.2, 2.6)
    assert cells.capacity(L, ("h", i - 1, j)) == 1  # x = 2.0, between the vias at (2.0, 2.0) and (2.0, 2.8)
    assert cells.capacity(L, ("v", i, j)) == 1  # y = 2.8
    assert cells.capacity(L, ("h", i, j)) >= 1 and cells.capacity(L, ("v", i, j - 1)) >= 1
    # far from the field: a 0.4 mm boundary holds floor(0.4 / 0.1775) + 1 = 3 tracks
    assert cells.capacity(L, ("h", 0, 0)) == 3
    coarse = planr.Cells(region, [L], fixed, 0.0889, 0.0886, cell_mm=0.4, grid_mm=0.2)
    assert coarse.capacity(L, ("h", 0, 0)) == 3  # 0.4 / 0.2 + 1: the grid's nodes on the boundary
    assert coarse.pitch == 0.2


def test_own_copper_is_no_obstacle_around_a_terminal():
    board = pcbnew.BOARD()
    region = (0.0, 0.0, 4.0, 4.0)
    L = pcbnew.B_Cu
    fixed = planr.Fixed(board, region, [L])
    fixed._add_rect(L, 2.0, 2.0, 0.6, 0.6, "CK")  # a wide pad fills its cell and the neighbours' boundaries
    cells = planr.Cells(region, [L], fixed, 0.0889, 0.0886, cell_mm=0.4)
    i, j = cells.cell_of(2.0, 2.0)
    assert all(cells.capacity(L, k) == 0 for k in cells.boundaries_of((i, j)))
    own = cells.capacity_near(L, 2.0, 2.0, 1.0, "CK")
    assert all(own[k] > 0 for k in cells.boundaries_of((i, j)))
    other = cells.capacity_near(L, 2.0, 2.0, 1.0, "DQ0")
    assert all(other[k] == 0 for k in cells.boundaries_of((i, j)))


def test_two_crossing_runs_take_different_layers():
    """Two runs whose straight routes cross, with two layers to choose from: the negotiation separates them."""
    region = (0.0, 0.0, 6.0, 6.0)
    layers = [pcbnew.In1_Cu, pcbnew.In2_Cu]
    board = pcbnew.BOARD()
    fixed = planr.Fixed(board, region, layers)
    runs = [planr.Run("A", (0.2, 3.0), (5.8, 3.0), tuple(layers)),
            planr.Run("B", (3.0, 0.2), (3.0, 5.8), tuple(layers))]
    for run in runs:  # the terminals are vias: no other run gets through their cells
        for (x, y) in (run.a, run.b):
            for L in layers:
                fixed._add_circle(L, x, y, 0.2, run.net)
    cells = planr.Cells(region, layers, fixed, 0.1, 0.1, cell_mm=0.4)
    planner = planr.Planner(cells, planr.PlanCosts(iterations=20))
    res = planner.route(runs)
    assert res["unrouted"] == 0
    assert res["crossings"] == [], res
    assert runs[0].layer != runs[1].layer


def test_a_bundle_shares_a_layer():
    region = (0.0, 0.0, 8.0, 8.0)
    layers = [pcbnew.In1_Cu, pcbnew.In2_Cu]
    cells = _empty_cells(region, layers)
    runs = [planr.Run(f"DQ{k}", (1.0, 1.0 + k), (7.0, 1.0 + k), tuple(layers), group="lane") for k in range(4)]
    planner = planr.Planner(cells, planr.PlanCosts(iterations=10, layer_bias={pcbnew.In1_Cu: 0.05}))
    planner.route(runs)
    assert len({r.layer for r in runs}) == 1
    assert runs[0].layer == pcbnew.In2_Cu  # the bias keeps them off In1


def test_length_room_is_taken_where_there_is_room():
    region = (0.0, 0.0, 8.0, 4.0)
    layers = [pcbnew.In1_Cu]
    cells = _empty_cells(region, layers)
    runs = [planr.Run("short", (1.0, 2.0), (7.0, 2.0), tuple(layers)),
            planr.Run("long", (1.0, 1.0), (7.0, 3.0), tuple(layers))]
    planner = planr.Planner(cells, planr.PlanCosts(iterations=10))
    planner.route(runs)
    deficit = planr.reserve_lengths(runs, {"long": 4.0}, [(["short", "long"], 0.5)], factor=2.0)
    assert deficit["short"] > 3.0 and deficit["long"] == 0.0
    assert runs[0].units > 1 and runs[1].units == 1
    planner.route(runs)
    assert runs[0].reserved_mm >= deficit["short"]  # open board: all the room it asked for
