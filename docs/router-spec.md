# The general router (M4): specification

Status: **proposed, for the owner to read before the router is trusted.** A first implementation exists in
`waffle_eda/route/board_router.py` and has never been executed; section 13 says exactly where it stands against
this document. Nothing here is a claim about working code.

Related: `docs/plan.md` M4, `docs/decisions.md` D49 (why M4 came before M3b) and D50 (the benchmark that grades
it). The benchmark is `waffle_eda/bench/rebuild.py` and the gate is `python3 scripts/gate.py m4`.


## 1. What it is for

Every router in the tree so far is anchored on a ball-grid package: `route.escape` works on a package's
quarter-pitch lattice, `route.bus` on a grid between two packages with layer changes only inside them. A class A
board has no package to anchor on. It is a microcontroller, some passives and headers, and its nets run wherever
there is room. This router is the first in the project with no such anchor, which is why M4 is where the tool's
general-purpose claim is first tested.


## 2. Inputs, outputs, invariants

**Input.** A board carrying placement, pads, board outline and keepouts, and no routed copper at all: what
`docs/definition.md` gives stage 5, and what `rebuild.strip_all` produces. Plus a `rebuild.BoardRules` measured
off the reference, and optionally a set of nets whose copper is already fixed (section 9).

**Output.** The same board with copper added, and a result object naming every net routed and, for every net not
routed, the pad it could not reach and why.

**Invariants the router may not break.**

* It never moves, rotates or deletes a footprint. Placement is an input at M4; placement is M5's problem.
* It never edits or deletes copper of a fixed net.
* It never returns a board it has not checked. Every piece of copper it adds cleared the board when it was laid.
* It never reports success for a net whose pads are not all joined.


## 3. Definition of done

M4 passes when `scripts/gate.py m4` exits 0: for every class A reference, every routable net connected and zero
electrical violations under the rules measured off that board. "Routable" is `rebuild.routable_nets`, the nets
reaching two or more pads.

The plan also requires *planes and power rails on continuous copper with feeds and plane vias*. Section 8 says
how, and section 12 raises the fact that the gate as written does not yet test for it.


## 4. The search space

A uniform grid on every copper layer over the board outline inset by the measured edge clearance plus half a
track, with:

* a node at every grid position on every copper layer;
* a node at every pad centre, on each copper layer that pad reaches, joined to the grid nodes around it;
* a via edge joining all copper layers at each grid position.

Step is `max(min_track + clearance, 0.2 mm)`, so two parallel runs can take neighbouring lines. Measured across
the ladder:

| board | outline mm | layers | routable nets | pads | track | clearance | step | grid nodes |
|---|---|---|---|---|---|---|---|---|
| tinkerforge-temperature | 15 x 25 | 2 | 6 | 30 | 0.300 | 0.197 | 0.50 | 3,224 |
| olimex-esp32c3-devkit | 28 x 38 | 2 | 34 | 204 | 0.127 | 0.126 | 0.25 | 34,048 |
| olimex-rp2040-pico-pc | 72 x 39 | 2 | 60 | 275 | 0.203 | 0.153 | 0.36 | 44,254 |
| open-book-c1 | 85 x 115 | 2 | 35 | 184 | 0.250 | 0.197 | 0.45 | 98,556 |
| libresolar-mppt-2420 | 115 x 61 | 2 | 102 | 483 | 0.250 | 0.118 | 0.37 | 102,960 |
| crkbd-corne-cherry | 277 x 108 | 2 | 152 | 648 | 0.203 | 0.189 | 0.39 | 389,400 |

**Why a grid rather than the alternatives.** A package lattice (`route.escape`) has no meaning here: there is no
pitch to be a fraction of. A visibility graph or rectangle decomposition would give shorter, non-lattice copper
and fewer nodes, and is the right answer eventually, but it needs a geometry layer the project does not have. A
grid is the cheapest structure that can be checked exactly, and exactness is the property worth keeping.

**What the grid costs.** Copper runs only on lattice lines, at multiples of 45 degrees, so the result is longer
and uglier than a human's. M4's criterion does not grade length or beauty. If that changes, this is the decision
to revisit first.


## 5. Feasibility is exact, never a proxy

An edge is usable when the track or via it would become clears the board's copper under the measured rules,
asked of `route.obstacles`, which is KiCad's own shape collision. The grid decides **where** a track may run; it
never decides **whether one fits**.

This is the rule the rest of the project already follows, and D33 is why: a bench setting once made every
measurement meaningless because a proxy stood in for the real test. A router that believes its own occupancy map
rather than the geometry will produce boards that fail DRC and reports that look fine.

Same-net copper is not an obstacle. That is how a net's own tree is joined, and it is why a later pad can land on
copper already laid for the same net.


## 6. Nets: decomposition and order

A net with *k* pads is a tree, not a path. Each net is grown: the first pad seeds the tree, and each further pad
is reached by an A\* whose sources are **every node the tree already occupies**, so a pad joins where the net is
nearest rather than at its first pad. This is a greedy Steiner approximation and is the standard one.

Nets are routed shortest first, by the diagonal of their pad bounding box. Rationale: short nets have the least
freedom, and routing them first leaves the long nets, which have alternatives, to work around them. This is a
heuristic and it is not defended by measurement yet; section 12 lists it as something to measure rather than
assume.

Copper enters the board and the obstacle index as it is laid, so a net routed later sees every net routed before
it exactly.


## 7. Conflicts: rip-up and negotiation

**Not in the first implementation, and it will be needed.** Both existing routers needed it, and D29 to D33 are a
long record of what happens without it. A purely sequential router fails a net whose route was taken by an
earlier one, and has no way to recover.

The proposal, in the order it should be built:

1. **Rip-up and retry.** When a net fails, rip up the nets whose copper blocks its best blocked path, route the
   failing net, then re-route the ripped ones. Bounded by a number of rounds and by a rule that a net may not be
   ripped twice for the same blocker.
2. **Negotiated congestion**, the scheme already in `route.escape` and `route.bus`: route every net ignoring
   other nets but at a cost that rises with how often a node has been wanted, and iterate until no node is
   shared. This is the one that scales, and it is what D31 and D32 concluded for the bus.

The order matters: rip-up is a day and may be enough for two-layer boards with dozens of nets; negotiation is a
week and is the answer for the dense ones. Build the first, measure, and only build the second if the ladder
demands it. Do not build both speculatively.


## 8. Planes, power rails, feeds and stitching

**The part with no precedent anywhere in the tree**, and the likeliest place M4 stalls. On a two-layer board the
ground pour *is* how ground is routed: `tinkerforge-temperature` has a GND zone on each side and 9 GND pads.

Proposed design:

1. **Choose the plane nets.** A net is a plane candidate when its name matches a supply pattern (`GND`, `VCC`,
   `VDD`, `VSS`, `+3V3`, `+5V`, `BAT+`) or it reaches more pads than any signal net by a wide margin. Section 12
   asks the owner whether this should be a declared input instead of a heuristic.
2. **Route signals first**, leaving the plane nets unrouted.
3. **Author one zone per plane net per layer**, outlining the board inset by the measured edge clearance, with
   the zone's priority set so that a higher-priority supply carves out of a lower one.
4. **Fill with KiCad's own filler** (`kicad.refill`, in a child process: the in-process filler hangs on some
   boards, D14), never with our own polygon arithmetic.
5. **Find the islands.** After filling, a plane net can be in several disconnected pieces, and a pad can sit on a
   piece that reaches nothing. This is the step that decides whether the approach works.
6. **Stitch.** Join pieces on different layers with vias where they overlap; join pieces on the same layer with a
   track, or accept a track from an orphaned pad to the main piece.
7. **Fall back to tracks** for any plane net still not whole, and say so in the result rather than leaving it.

The risk to confront first is step 5: if a board's pours routinely fragment, the whole approach is wrong and the
supply nets should be routed as wide tracks with pours as decoration. Measure this on
`tinkerforge-temperature` before building steps 6 and 7.


## 9. Fixed copper

M4's text says the router runs *with the bus and pairs fixed*, which is how it will be used on a class C board
after M3b: the bus is routed first and this router fills in everything else. The mechanism is the `fixed_nets`
argument. Fixed nets are in the obstacle index like any other copper and are never edited, and the router does
not route them.

No class A reference exercises this, so it is untested by the M4 gate and must not be claimed until a class C
board runs through it.


## 10. Failure reporting

The plan's rule for M3b applies here too: **fail with a diagnosis, never with a list.** A net that cannot be
routed is reported with the pad it could not reach and the reason the search ended: out of budget, or no edge out
of the frontier. A run that fails many nets should say what they have in common, not print them.

A half-routed net is a failure, not a partial success. The router never reports a net routed whose pads are not
all joined.


## 11. Performance budget

One exact collision check costs **12 to 13 microseconds**, measured on both the smallest and the largest board in
the ladder, and it is flat in the number of obstacles because the index buckets them. So the budget is set by the
**number of checks**, not by the board's complexity.

A single full 8-neighbour sweep of `crkbd-corne-cherry`'s grid is about **40 seconds** of checks. With 152 nets,
each needing several searches, and rip-up rounds on top, an uncached router will not finish that board.

Therefore: **edge feasibility must be cached.** A check's answer depends on the edge's geometry and on the copper
near it, so cache by (layer, node pair) and invalidate only the entries whose geometry lies within one clearance
of copper just placed. The existing bus router already caches this way (`_edge_hits`), and `obstacles.hits`
exists precisely so one geometric answer can be shared between nets.

Target: the smallest board in seconds, the largest in minutes. M1's harness runs in seconds to a minute and that
is the standard this should be held to.


## 12. Questions for the owner

1. **Track width.** The router lays every net at the board's minimum track width, and the benchmark accepts it.
   `libresolar-mppt-2420` routes its signals at 0.25 mm and its power at 0.4 to 0.5 mm, with `BAT+` and `BAT-`
   at 0.5 mm on a 20 A stage. A router that laid that at 0.25 mm would **pass the M4 gate and be wrong**. This
   is a gap in D50's criterion, not only in the router. Options: widen by net class from the reference's own
   measured widths; require the candidate to match the reference's width per net; or leave it and accept that
   M4 does not grade current capacity. My recommendation is the first, and it needs a decision because it
   changes the benchmark.
2. **Plane nets: declared or inferred?** Section 8 infers them by name and pad count. A declared list is
   honest and is what stages 1 to 4 would supply in the real pipeline. Inference is what the benchmark can do
   unaided.
3. **Net ordering.** Shortest-first is asserted, not measured. Worth one experiment before it hardens.
4. **How far to take the grid.** Section 4 accepts 45-degree lattice copper. If the tool is ever to produce
   boards a human would sign off, this is the first thing to revisit.


## 13. What the code does today against this spec

`waffle_eda/route/board_router.py`, committed unrun:

| section | in the code |
|---|---|
| 4 search space | yes, as described |
| 5 exact feasibility | yes |
| 6 tree growth, shortest-first | yes |
| 7 rip-up and negotiation | **no.** Sequential only; a blocked net fails |
| 8 planes and power | **no.** Supply nets are routed as ordinary tracks |
| 9 fixed copper | argument exists, never exercised |
| 10 diagnosis | partial: names the unreachable pad, does not group causes |
| 11 caching | **no.** Every edge is checked afresh, so the large boards will not finish |

So the written code is section 4, 5 and 6 only, and it has not been run. On the strength of section 11 alone it
should not be expected to complete `crkbd-corne-cherry` or `libresolar-mppt-2420`.
