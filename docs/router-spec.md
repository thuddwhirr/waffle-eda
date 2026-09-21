# The general router (M4): specification

Status: **proposed, for the owner to read before the router is trusted.** A first implementation exists in
`waffle_eda/route/board_router.py`, has never been executed, and contains only a fraction of what is below.
Section 14 is the honest table. Nothing here is a claim about working code.

**This is the third version, and each correction went the same way.** The first was written from the code plus
six fresh measurements; it cited seven of fifty decisions and nothing from the three research reports or the
carried lessons, and proposed an architecture both the research and this project's own history call wrong
(section 2). The second still framed the work as a menu with cheaper options, which is deciding in advance that
part of a board is a person's job; the goal is zero interactive routing, so there is no cheaper option, only an
order (section 13). The second also had no closure loop at all, which is the difference between a router and an
automated one (section 10).


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
| F. Closure | a change to a free variable when no copper works, and a retry | the loop terminates inside its budget (section 10) |

Each stage checks that the previous one delivered what it assumes. That is the recurring lesson of
`layout-practices.md`, stated there as item 3 and again in its closing line.


## 3. Inputs, outputs, invariants

**Input.** A board carrying placement, pads, outline and keepouts and no routed copper: what `definition.md`
gives stage 5, and what `rebuild.strip_all` produces. A `rebuild.BoardRules` measured off the reference. Optionally
a set of nets whose copper is fixed (section 11).

**Output.** The same board with copper added, and a result naming every net routed and, for each one not routed,
the pad it could not reach and why.

**Invariants.**

* Never moves, rotates or deletes a footprint **within a run**. Placement is an input to the router. When no
  arrangement of copper works, the router asks for a placement change rather than making one, and the tool
  retries: section 10.
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

One instance is already found: the gate accepts minimum-width copper on a 20 A rail. The electrical constraints
that belong in the criterion, in the order they are cheap to add:

1. **Track width by net class**, from the reference's own measured widths (section 5).
2. **A return via near every signal via.** UG583 codifies one ground via within a 50 mil perimeter of a layer
   transition (`foundational-reference.md` §1). Cheap to check, cheap to place.
3. **Plane integrity**: no net routed across a split in the plane that references it. This is the check that
   makes stage D worth doing rather than decorative.

**All three are required, and none of them is optional.** `definition.md` section 3 says a run ends complete or
failed with a report, and that "a partially routed board with a list of nets for a human to finish in KiCad's
interactive router is **not a valid outcome**". Anything the gate does not check is a defect the tool ships and a
human repairs, which is the thing this project exists to prevent. A criterion that omits current capacity does
not make the router simpler; it moves the work to a person.

Track width is not even a question of taste: `definition.md` section 4 lists "track width and spacing within the
fab's capability" among the **free variables the tool explores on its own**. Setting it correctly is the
router's job as already defined. The only open item is recording the change to D50's criterion, which CLAUDE.md
requires before scope changes.


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


## 7. Stage C: pad escape, then detailed route inside the guides

**C1. Escape every pad before routing anything** (D51, measured). A track of `tinkerforge-temperature`'s own
width needs 0.694 mm to pass between two pads; its TSSOP-8 leaves 0.245 mm and its SOT-563 leaves 0.198 mm, so
nothing passes between the pads of either part and every pad must be approached from outside its row. That is
escape routing. `route.escape` already does it for ball grids, and the first run of this router failed four of
six nets on exactly this, each on the net's last pad, each on a fine-pitch part.

The escape is a stage, not a step of the search. D36 reached the same conclusion for the bus from the other
direction: an escape computed independently of what comes after it can only be lucky. So C1 produces, per pad, a
stub to a point outside its pad row that the board-level search can start from, and C2 routes between those
points.

**C2. Detailed route.** Inside each net's guide, exact copper.

* **The search space** is a uniform grid on every copper layer, with a node at each pad's escape point and a via
  edge joining layers at each position, restricted to the cells of the net's guide.
* **The step is a fraction of the finest pad pitch on the board, not of the track width.** The first
  implementation used `max(width + clearance, 0.2 mm)`, which on this board is 0.4969 mm against a pad pitch of
  0.498 mm: the lattice and the pad row have the same spacing to within a micrometre, so no lattice line lies
  between two pads and no stub can be described. A step derived from track width describes copper it cannot
  place.
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


## 10. Failure, closure, and staged checks

**Fail with a diagnosis, never with a list**, which is the plan's rule for M3b and applies here. A net that
cannot be routed is reported with the pad it could not reach and why the search ended. A run that fails many
nets says what they have in common. A half-routed net is a failure, never a partial success. Every stage checks
that the previous one delivered what it assumes (`layout-practices.md`, item 3 and its closing line).

**A diagnosis is not the end of the run, and this is the part the first two versions of this spec left out.**
`definition.md` section 3 requires a failed run to name "the design changes that would resolve it", and section
4 lists what the tool may change **on its own, within a budget, logging every attempt so nothing is tried
twice**: placement, rotation and side; pin assignment; layer count and stack-up; via type; track width and
spacing; board size. The owner is asked only when the best solution found needs a *locked* constraint crossed:
maximum board size, cost ceiling, agreed interface positions, feature set.

So the router does not hand a diagnosis to a person. It emits a change an earlier stage can act on, and the
tool retries:

| What the router found | What it asks for | Which stage acts |
|---|---|---|
| a net with no path at any layer | one more layer pair | PCB specification (stage 4) |
| congestion concentrated around one part | that part moved or rotated | placement (stage 5) |
| two pads that cannot be reached in the order they sit | a pin or lane swap | pin assignment |
| a rail that cannot be fed as copper | a via type, or a layer for the plane | specification |
| copper that fits nowhere at this size | a larger board, inside the maximum | specification |
| any of the above needing more than the maximum size or the cost ceiling | **the owner**, with evidence and options | escalation |

This loop is what makes the difference between a router and an automated router, and nothing in the tree
implements it yet. M4's gate does not exercise it either, because the benchmark re-routes a board whose
placement and layer count are the reference's and are known to work. That makes it invisible to the gate and
still required: the first board where no arrangement works is the one that proves it, and by then it is too late
to design.

**Budgets, so the loop terminates.** Every retry is bounded and logged. A router that has not converged within
its budget stops and reports rather than running for hours (`definition.md` section 3). The log is what stops
the same change being tried twice.


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


## 13. What is actually the owner's

Earlier versions of this section asked four questions. Three of them were not the owner's and two were
scope reduction dressed as a choice: how much of stage B to build, and whether to grade current capacity at all.
Both amount to deciding in advance that some of the board is a person's job. The goal is zero interactive
routing, so the answer to "how much of this do we build" is all of it, and the only real questions are order and
evidence.

**The one decision to record.** D50's criterion gains width by net class, a return via near every signal via,
and plane integrity (section 4). CLAUDE.md requires a criterion change to be recorded in the decisions log
before the scope changes, so this needs the owner's word — not on whether, but to enter it in the log.

**Not the owner's, and already answered.** Track width is a free variable the tool sets (`definition.md`
section 4). Whether plane nets are declared or inferred is a question of which stage of the tool decides, and
both stages are the tool. How much of stage B to build is answered by the ladder: class A may survive coarse
cells without negotiation, and class B, B+ and C will not, so negotiation is built once rather than twice.

**A measurement worth making, not a permission to seek.** Freerouting, which the plan names and the research
recommends wrapping as a baseline. It is the kind of router the research says fails on electrical intent, so it
is a number to beat rather than a destination, and nobody has yet tested whether it will respect fixed copper.


## 14. What the code does today against this spec

`waffle_eda/route/board_router.py`, committed unrun:

Measured once, on `tinkerforge-temperature` (D51): **2 of 6 nets, 32 tracks, zero electrical violations, score
0.333, 1.5 s.** FAIL. The four failures are all the missing C1.

| Stage | In the code |
|---|---|
| A. rules and net classes | **no.** One board-wide minimum width for every net |
| B. global route | **no.** No coarse stage at all; A\* runs over the whole board |
| C1. pad escape | **no.** This is what the four failures are |
| C2. detailed route | partly: grid, exact feasibility, greedy Steiner growth, no guides, step too coarse |
| D. planes and rails | **no.** Supply nets are routed as ordinary tracks |
| Rip-up and reroute | **no.** Sequential; a blocked net fails |
| Fixed copper | argument exists, never exercised |
| Diagnosis | partial: names the unreachable pad, does not group causes |
| Closure: a change an earlier stage can act on | **no.** The loop of section 10 does not exist anywhere in the tree |
| Caching | **no** |

So the code is a fragment of stage C. On section 12 alone it should not be expected to finish
`crkbd-corne-cherry` or `libresolar-mppt-2420`, and on section 2 its architecture is the one this project
already abandoned once.
