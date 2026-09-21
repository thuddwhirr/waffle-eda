"""The general router of M4: every net of a whole board, from placement, with no bus behind it.

**Not built.** This module exists so that M4's gate fails for a stated reason rather than for a missing import,
and so the interface the gate calls is fixed before the router is written. `scripts/gate.py m4` is red today and
stays red until :func:`route_board` returns a board that scores 1.0 on `waffle_eda.bench.rebuild`.

What it has to do, from M4 in `docs/plan.md`:

* connect every net of `rebuild.routable_nets` on a board that arrives with placement, outline and pads only;
* put planes and power rails on continuous copper, with their feeds and plane vias, rather than routing a
  supply net as if it were a signal;
* respect copper that is already fixed, because on a class C board the bus and its pairs are placed first and
  this router runs after them;
* stay inside the rules `rebuild.measure_rules` measured off the board, and end clean under KiCad's own DRC.

What it can reuse, and what it cannot. `route.obstacles` is the clearance index and is general. `route.length`
tunes a run's length under the same collision test and is general. The negotiated-congestion scheme is written
twice already, in `route.escape` for a package lattice and in `route.bus` for a bus grid, so the pattern is
known; neither router itself applies, because both are built around a ball-grid package and this board has none.
"""
from __future__ import annotations


def route_board(board, rules, fixed_nets: set[str] | None = None):
    """Route every net of ``board`` under ``rules`` (a :class:`waffle_eda.bench.rebuild.BoardRules`), leaving the
    copper of ``fixed_nets`` untouched. Returns the routed board.

    Raises :class:`NotImplementedError` until M4's router is built. The gate reports that as a failure with its
    reason, which is the honest state: a milestone with no tool is a failing milestone, not a pending one.
    """
    raise NotImplementedError(
        "M4's general router is not built. The benchmark it will be graded by is in waffle_eda/bench/rebuild.py "
        "and its two sanity checks pass: the stripped board scores 0.000 and the original copper 1.000.")
