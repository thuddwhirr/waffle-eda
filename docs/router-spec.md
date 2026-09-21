# The general router (M4): specification

Status: **proposed, for the owner to read before the router is trusted.** A first implementation exists in
`waffle_eda/route/board_router.py`, has never been executed, and contains only a fraction of what is below.
Section 14 is the honest table. Nothing here is a claim about working code.

**This is the second version.** The first was written from the code I had just written plus six fresh
measurements. It cited seven of the fifty decisions and nothing at all from the three research reports or the
carried lessons, and it proposed an architecture that both the research and this project's own history say is
wrong. That is corrected here, and section 2 is the correction.


## 0. What this draws on

| Source | What it contributes |
|---|---|
| `research/foundational-reference.md` §4, and its staged architecture | two-level routing, PathFinder, rip-up and reroute, Steiner decomposition, why autorouters fail |
| `research/ddr3-bus-routing.md` §2 | the four-stage pipeline, and that negotiation is the wrong tool for layer assignment |
| `research/foundational-reference.md` §1 | return paths, plane integrity, 3W and its nuance, via stubs |
| `lessons/layout-practices.md` | eighteen practices learned by patching their consequences, with numbers |
| decisions D14, D17, D18, D29, D31, D32, D33, D36, D38, D41, D49, D50 | what this project has already paid for |
| M3a (`route.busplan`, `route.busplanner`) | the project's own instance of plan-before-route, and that it works |


## 1. What it is for

Every router in the tree so far is anchored on a ball-grid package: `route.escape` works on a package's
quarter-pitch lattice, `route.bus` on a grid between two packages. A class A board has no such anchor. It is a
microcontroller, some passives and headers, and its nets run wherever there is room. This is the first router in
the project with nothing to anchor on, which is why M4 is where the general-purpose claim is first tested.


## 2. The architecture: coarse plan first, exact copper second

**The correction.** A single-stage router that runs A\* per net across a fine grid over the whole board is Lee's
maze router with a heuristic, and its cost is the reason two-level routing exists: *global routing on coarse
cells produces route guides and a congestion map; detailed routing commits exact wire inside each cell*
(`foundational-reference.md` §4). The research report for this project reaches the same conclusion from the
other direction and adds the sharper claim: negotiation "is useful here only for the residual, local conflicts;
it is the wrong tool for layer assignment and for length" (`ddr3-bus-routing.md` §2).

**This project already re-derived it once, expensively.** D29 to D33 are the record of a detailed bus router
with no plan behind it stalling, and of the measurements that showed the plateau was an ordering problem rather
than a capacity one. The answer was M3a: a planning stage whose artifact is smaller than a route and whose
mistakes are caught in the session that makes them. M3a passes; M3b is the detailed stage inside it. Writing a
general router with no planning stage would repeat exactly the mistake that cost this project two sessions.

So the router is staged:

| Stage | Produces | Checked by |
|---|---|---|
| A. Rules and net classes | width, clearance and via per net class, from the reference | the original meets them by construction (D17) |
| B. Global route | per net, a layer and a sequence of coarse cells; a congestion map | every net has a guide; no cell over capacity |
| C. Detailed route | exact copper inside each guide | KiCad's own collision test, per edge |
| D. Planes and rails | pours, feeds, stitching | every rail in one piece, every pad fed |
| E. Verification | the gate's score | `scripts/gate.py m4` |

Each stage checks that the previous one delivered what it assumes. That is the recurring lesson of
`layout-practices.md`, stated there as item 3 and again in its closing line.


## 3. Inputs, outputs, invariants

**Input.** A board carrying placement, pads, outline and keepouts and no routed copper: what `definition.md`
gives stage 5, and what `rebuild.strip_all` produces. A `rebuild.BoardRules` measured off the reference. Optionally
a set of nets whose copper is fixed (section 11).

**Output.** The same board with copper added, and a result naming every net routed and, for each one not routed,
the pad it could not reach and why.

**Invariants.**

* Never moves, rotates or deletes a footprint. Placement is an input at M4; it is M5's problem.
* Never edits or deletes copper of a fixed net.
* Never returns a board it has not checked: every piece of copper cleared the board when it was laid.
* Never reports a net routed whose pads are not all joined.


## 4. Definition of done, and why the gate is not enough

M4 passes when `scripts/gate.py m4` exits 0: every routable net connected and zero electrical violations under
the rules measured off that board.

**That criterion is geometric completion, and geometric completion is the named failure mode of every autorouter
that came before.** The research is blunt about it: commercial routers "optimize geometric completion (connect
all nets, pass geometric DRC) but are blind to *electrical* intent: return paths, impedance continuity,
crosstalk, length/skew, plane integrity, via-stub resonance", and the lesson drawn is that "constraints must be
*electrical and physics-derived*, fed to the router as hard/soft costs, not applied as an afterthought"
(`foundational-reference.md` §4).

Section 13 question 1 is one instance already found: the gate accepts minimum-width copper on a 20 A rail. The
electrical constraints that belong in the criterion, in the order they are cheap to add:

1. **Track width by net class**, from the reference's own measured widths (section 5).
2. **A return via near every signal via.** UG583 codifies one ground via within a 50 mil perimeter of a layer
   transition (`foundational-reference.md` §1). Cheap to check, cheap to place.
3. **Plane integrity**: no net routed across a split in the plane that references it. This is the check that
   makes stage D worth doing rather than decorative.

These are proposed for the gate, not assumed. They change D50's criterion, so they are the owner's.


## 5. Stage A: rules and net classes

`rebuild.measure_rules` measures one set of minima for the whole board. That is the right floor and the wrong
ceiling. `layout-practices.md` item 12 records the practice the last project settled on: *fab rules set from the
fab's capability before routing; net classes carry widths and impedance geometry.*

So stage A derives, per net class, from the reference:

* **width**: the width that class uses on the reference, not the board minimum. Measured on
  `libresolar-mppt-2420`: signals 0.25 mm, `GND`, `+3V3` and `+5V` 0.4 mm, `BAT+` and `BAT-` 0.5 mm on a 20 A
  stage.
* **clearance**: the measured board clearance, with the option of more for a class that asks for it.
* **via size and drill**: the measured minima.
* **class membership**: supply nets by name and pad count, signals otherwise (section 13 question 2).

The original board meets these by construction, which is D17's rule and is what makes them legitimate as a
criterion.


## 6. Stage B: global route

A coarse grid of cells over the board, several millimetres each, one layer set. For every net, a sequence of
cells and a layer, produced by negotiated congestion:

> PathFinder (McMurchie & Ebeling, FPGA95): nets initially share resources, then a per-node cost
> `f(n) = (b(n) + h(n)) x p(n)` — base cost plus accumulated historical congestion, times present congestion —
> is iteratively raised so overused resources are negotiated away until a legal solution emerges.

Cell capacity is the number of tracks of the net's class that fit across the cell boundary, less the fixed
copper already crossing it. This is the same quantity `route.plan` computes for the bus, and that code is the
closest thing in the tree to reuse for this stage.

**Electrical costs belong here, not afterwards.** A cell crossing a plane split, or a layer whose reference
plane is discontinuous under it, costs more. This is where "hard/soft costs" from section 4 enter.

**What this stage buys.** It is the answer to the performance problem in section 12, and it is what makes
rip-up tractable: ripping up a guide is cheap, ripping up exact copper is not.


## 7. Stage C: detailed route inside the guides

Inside each net's guide, exact copper.

* **The search space** is a uniform grid on every copper layer, step `max(width + clearance, 0.2 mm)`, with a
  node at each pad centre joined to the grid nodes around it, and a via edge joining layers at each position.
  Restricted to the cells of the net's guide, which is what makes it affordable.
* **Feasibility is exact, never a proxy.** An edge is usable when the track or via it would become clears the
  board under the class's rules, asked of `route.obstacles`, which is KiCad's own shape collision. D33 is why:
  a bench setting once stood in for the real test and made every measurement meaningless. The grid decides
  *where* copper may run; it never decides *whether it fits*.
* **Same-net copper is not an obstacle.** That is how a net's own tree is joined.
* **Multi-pad nets** are decomposed as a Steiner tree. The standard fast builder is FLUTE (RSMT, and OARSMT
  when obstacles are included); the greedy form, growing the tree by A\* from every node it already holds, is
  the cheap approximation and is what stage C uses until measurement says otherwise.

Measured grid sizes, for the record:

| board | outline mm | layers | nets | pads | width | clearance | step | full-grid nodes |
|---|---|---|---|---|---|---|---|---|
| tinkerforge-temperature | 15 x 25 | 2 | 6 | 30 | 0.300 | 0.197 | 0.50 | 3,224 |
| olimex-esp32c3-devkit | 28 x 38 | 2 | 34 | 204 | 0.127 | 0.126 | 0.25 | 34,048 |
| olimex-rp2040-pico-pc | 72 x 39 | 2 | 60 | 275 | 0.203 | 0.153 | 0.36 | 44,254 |
| open-book-c1 | 85 x 115 | 2 | 35 | 184 | 0.250 | 0.197 | 0.45 | 98,556 |
| libresolar-mppt-2420 | 115 x 61 | 2 | 102 | 483 | 0.250 | 0.118 | 0.37 | 102,960 |
| crkbd-corne-cherry | 277 x 108 | 2 | 152 | 648 | 0.203 | 0.189 | 0.39 | 389,400 |

**What the grid costs.** Copper runs on lattice lines at multiples of 45 degrees, so it is longer and uglier
than a human's. Topological routers (TopoR and its line) use no preferred direction and claim less parallelism
and so less crosstalk; that is the upgrade path, not the starting point.


## 8. Stage D: planes, rails, feeds and stitching

**Not an unknown.** The first version of this spec called it "the part with no precedent anywhere in the tree",
which was wrong: `lessons/layout-practices.md` items 4, 5, 6 and 11 are precisely this, learned by patching the
consequences, with the numbers.

What that document records:

* **Item 4. Power layers carry no signal tracks.** Treating a power layer as a routing layer put 99 nets and
  3.3 m of track on it and cut the 3V3 fill into 47 pieces. A plane layer is typed as a plane.
* **Item 5. Every rail has continuous copper: a plane, an island with a real feed, or a deliberate pour.** The
  failure was feeds drawn as bounding rectangles, leaving a rail in 47 pieces and a core cluster cut off. The
  fix was feed strips, a second sheet on the other layer, and a report of pieces per rail.
* **Item 6. Fill clearance and width at the fab minimum, so the plane survives the via grid.** Measured: at
  0.125 / 0.2 mm the 0.8 mm via grid left 0.1 mm webs that dropped, and ground under the FPGA was 80 % in 8
  pieces; at 0.1 / 0.15 mm it was 86 % in 5 pieces.
* **Item 11. Ground stitching next to every high-speed via and on a grid.**

So stage D is:

1. Choose the plane nets (section 13 question 2).
2. Author one zone per plane net per layer, board outline inset by the measured edge clearance, priority set so
   a higher-priority supply carves out of a lower one, **fill clearance and minimum width at the measured
   minimum** per item 6.
3. Fill with KiCad's own filler, in a child process: the in-process filler hangs on some boards (D14). Never
   with our own polygon arithmetic.
4. **Report pieces per rail**, which is item 5's gate. A rail in more than one piece is a finding, not a note.
5. Feed and stitch: join pieces across layers with vias where they overlap, give an orphaned pad a feed strip to
   the main piece, and stitch ground beside every signal via per item 11 and the 50 mil rule of section 4.
6. Fall back to a wide track for any rail still not whole, and say so.

**Return path is the reason any of this exists.** Signal energy travels in the field between trace and reference
plane, so a plane split under a signal forces the return current into a loop. A router that produces a connected
board over a fragmented plane has passed the gate and failed the job.


## 9. Rip-up and reroute

Net ordering is a chicken-and-egg problem, which is why routers "route greedily then selectively rip up and
reroute congested/violating nets" (`foundational-reference.md` §4). Ordering heuristics are a weak substitute
and the first version of this spec leaned on one.

Rip-up operates on **guides** (stage B), where it is cheap, and only on exact copper (stage C) for residual
local conflicts. Bounded by rounds, and by a rule that a net may not be ripped twice for the same blocker.

D41's warning applies: a criterion two knobs can trade against each other has a missing mechanism. If rip-up and
ordering can be traded against each other to reach the same score, the score is not measuring what it should.


## 10. Failure reporting and staged checks

**Fail with a diagnosis, never with a list**, which is the plan's rule for M3b and applies here. A net that
cannot be routed is reported with the pad it could not reach and why the search ended. A run that fails many
nets says what they have in common.

Every stage checks that the previous one delivered what it assumes (`layout-practices.md`, item 3 and its
closing line). A half-routed net is a failure, never a partial success.


## 11. Fixed copper

M4's text says the router runs *with the bus and pairs fixed*, which is how it will be used on a class C board
after M3b. Fixed nets sit in the obstacle index like any other copper, are never edited, and are not routed.

D36 and D38 are the caution: a stage boundary drawn in the wrong place made 50 to 65 % of what M2 certified
useless to the bus router. Whether the bus should be fixed before this router runs, or planned jointly with it,
is the same question in a new place, and no class A reference exercises it. Untested, and not to be claimed
until a class C board runs through it.


## 12. Performance budget

One exact collision check costs **12 to 13 microseconds**, measured on the smallest and the largest board in the
ladder, and is flat in the number of obstacles because the index buckets them. The budget is set by the number
of checks.

A full 8-neighbour sweep of `crkbd-corne-cherry`'s grid is about **40 seconds** of checks. With 152 nets, several
searches each, and rip-up on top, a single-stage router will not finish that board.

**The fix is stage B, not a cache.** Restricting stage C to a net's guide is what two-level routing is for, and
it cuts the searched space by the ratio of guide to board. Caching edge feasibility by (layer, node pair), and
invalidating only entries within one clearance of copper just placed, is a second-order win worth taking after;
`route.bus` already caches this way and `obstacles.hits` exists so one geometric answer can be shared.

Target: the smallest board in seconds, the largest in minutes, which is the standard M1's harness set.


## 13. Questions for the owner

1. **Track width, and what else belongs in the criterion.** The gate accepts minimum-width copper everywhere;
   `libresolar-mppt-2420` carries 20 A on 0.5 mm while its signals are 0.25 mm, so a router laying 0.25 mm
   everywhere passes and is wrong. Section 4 proposes three additions: width by net class, a return via near
   every signal via, and plane integrity. All three change D50's criterion.
2. **Plane nets: declared or inferred?** A declared list is what stages 1 to 4 of the pipeline would supply and
   is honest; inference by name and pad count is what the benchmark can do unaided.
3. **How much of stage B to build now.** A full PathFinder global router is the right answer and is a week.
   A cheaper version, coarse cells with capacities and no negotiation, may carry the class A ladder. The
   research says negotiation is for residual conflicts, which argues for the cheaper version first.
4. **Freerouting.** The plan names it as the alternative and the research recommends wrapping it as a baseline
   to measure against. Nobody has tested whether it can be made to respect fixed copper. Worth a day to find
   out, and it would give every later number something to be compared with.


## 14. What the code does today against this spec

`waffle_eda/route/board_router.py`, committed unrun:

| Stage | In the code |
|---|---|
| A. rules and net classes | **no.** One board-wide minimum width for every net |
| B. global route | **no.** No coarse stage at all; A\* runs over the whole board |
| C. detailed route | partly: grid, exact feasibility, greedy Steiner growth, no guides |
| D. planes and rails | **no.** Supply nets are routed as ordinary tracks |
| Rip-up and reroute | **no.** Sequential; a blocked net fails |
| Fixed copper | argument exists, never exercised |
| Diagnosis | partial: names the unreachable pad, does not group causes |
| Caching | **no** |

So the code is a fragment of stage C. On section 12 alone it should not be expected to finish
`crkbd-corne-cherry` or `libresolar-mppt-2420`, and on section 2 its architecture is the one this project
already abandoned once.
