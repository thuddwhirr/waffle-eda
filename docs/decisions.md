# Decisions

**An entry is one of two things:** a decision the owner made, or a measurement with its number, the commit and
the script that produced it. Ten lines at most. Recommendations, proposals and narrative do not go here; they go
to the owner in chat and come back as a decision or as nothing. An entry stands until a new measurement
contradicts it, and the entry that contradicts it says which measurement.

Numbers are kept from the first five days so that citations in code, tests and the lessons still resolve. The
full text of D1 to D54 is in [`archive/decisions-2026-09-21.md`](archive/decisions-2026-09-21.md); the entries
dropped from this log are listed at the end with the reason.

## The project

**D1. Scope.** A general-purpose, Claude Code driven tool suite: the six-stage pipeline of `definition.md`. The
`waffle-fpga` board (ECP5 caBGA381 with a DDR3 bus) is the hardest benchmark, not the deliverable. Owner, 2026-09-17.

**D2. Stack.** Python 3.11 with KiCad 9.0.9's `pcbnew` bindings; z3, numpy, shapely, pytest; Java and Xvfb for
Freerouting. `scripts/check_env.py` verifies it. Owner, 2026-09-17.

**D3. Reference boards** are fetched by `scripts/fetch_references.py` (pinned commits, partial clones) and never
committed; licences and attribution live in `waffle_eda/bench/references.toml`. Owner, 2026-09-17.

**D4. Salvage.** The `waffle-fpga` tools are in `salvage/waffle-fpga/` verbatim, for reference; nothing is imported
from there without a test here. Its documents are in `lessons/` with provenance. Owner, 2026-09-17.

**D5. Fab profile** is a data file (`waffle_eda/fab/profiles/pcbway.toml`) whose numbers come from the owner or
carry the date of the page they were read from. See D53 for what a session may not do about it. Owner, 2026-09-17.

**D6. The first end-to-end target is a class A board**, then B, and the FPGA board last. Owner, 2026-09-17;
restated as the whole plan in D55.

**D7. Repository layout.** `waffle_eda/` the package (`kicad/`, `bench/`, `fab/`, `route/`), `scripts/` entry
points, `tests/`, `docs/`, `references/` and `build/` ignored. Owner, 2026-09-17.

**D8. Many references per class, not two.** A tool that passes one board has learned that board. Every class in
the ladder has several open-hardware KiCad references; the registry is `waffle_eda/bench/references.py`. Owner,
2026-09-17.

**D9. The survey and the ladder.** 33 repositories probed (`scripts/survey_references.py`); 23 boards registered
across classes A, B, B+, C and C' (`references.md`). Rejected and why: no `.kicad_pcb` at the pinned commit
(icebreaker, greatfet, pyboard, ZSWatch, SparkFun Thing Plus, Adafruit Feather RP2040, epdiy); no licence file
(hydrabus, Tinkerforge ethernet-extension, icebreaker-pmod); unloadable format (Easyduino); RF is a non-goal
(hackrf). Pitfalls: a footprint name is not a package type (TinyFPGA's BGA is `CM81`), so a BGA is detected as a
filled lattice of pad centres; `pcbnew.LoadBoard` returns None for a file it cannot parse. Measurement, 2026-09-17.

**D53. A reference board proves its own manufacturability, and vendor limits are deferred.** Every reference was
fabricated, so the rules its copper demonstrates are achievable: the benchmark's DRC criterion is the per-board
measured rules (`bench/constraints.py`, `bench/rebuild.py`), and no fab tier is applied to a reference. The
target board's via size and fab tier are specified by the owner when a class C design is started, not before, and
not researched. No vendor research of capability, price, lead time or reputation: this environment cannot reach
the sources (two rounds, 316 agents and 19.5 M tokens, returned evidence for one vendor). Owner, 2026-09-21.

**D55. Build the whole pipeline for class A boards to completion first; then work through the pipeline again
and extend it for class B, then B+, then C, then C'.** Owner, 2026-09-23, on the review of the first five days.
"Completion" for a class: every reference board in the class passes the class gate through all six stages
with no interactive routing, and one synthetic design of that class reaches fab files the owner reviewed. The
next class is not started until the current one is complete, and every earlier class stays passing. Each stage
uses the cheapest existing tool that passes the class (Freerouting for stage 5 of class A, `kicad-cli` for DRC
and exports); own code is written where a measurement shows the baseline fails, and never re-architected
because of one board. The DDR3 bus work (M3b, D30, the M6 target board) is parked inside class C. The user
interface is a separate project that consumes this one's files, renders and reports. The first five days' plan,
router spec and full log are archived (`archive/`); this log is condensed to what stands; CLAUDE.md is
rewritten to the rules in it.

**D56. Stage 5's baseline is Freerouting 2.4.1 on Java 25, fetched, not installed.** The current release needs
Java 25 (class file 69); the container has 21. `scripts/fetch_tools.py` puts the jar and a Temurin 25 JDK under
`build/tools/` from GitHub releases (Maven Central answers 429, Adoptium's API 403 through the proxy);
`scripts/check_env.py` requires both. The wrapper is `route/freerouting.py`; the class A gate runs it.
Owner (the version), 2026-09-23; the rest measured the same day.

**D57. What the wrapper had to learn, each by running it** (`route/freerouting.py`, 2026-09-23).
`pcbnew.ExportSpecctraDSN` returns False and writes nothing when two footprints share a reference (five of six
class A boards); duplicates are renamed for the export and restored after the import. The DSN carries the
board's net-class values, not the measured rules; written in, the router asked for `tinkerforge-temperature`'s
measured clearance (0.1972 mm, 0.003 under its SOT-563's pad gap) attaches nothing to that part: its maze finds
the path and its exact insertion check rejects the last segment; at 0.190 it routes the whole board in 2 passes.
So the wire-to-SMD-pad clearance is handed over as the rule less 0.0072 (4 of 6 nets, 2 clearance violations);
the same slack on every clearance gives 6 of 6 there and 175 violations of exactly that slack on
`libresolar-mppt-2420`, so it stays scoped. The default via cost of 50 stops the router placing any via of its
own on a 15 x 25 mm board (0 vias, 18 passes alternating between two top-layer solutions); `router.scoring
.via_costs` 1 in its settings file gives 14 to the reference's 15. The same setting as an `(autoroute_settings)`
block in the DSN made the loader drop every pin of `olimex-rp2040-pico-pc` (0 unrouted items) when placed
before the structure's rule block and was not read after it. The fanout stage necks its stubs to 75 % of the
width, below the rule, and is off. The session file truncates via drills to whole micrometres (248.9 became
248), so the drill is rounded up to one. Hole-to-copper is not a Specctra rule: typed via and pin clearances of
the rule less the smallest ring carry it. Escape stubs laid by the wrapper (D51's finding, the reference's own
exit pattern) made the smoke test worse (2 of 6 against 6 of 6 under the global slack) and stay off. Runs are
deterministic per configuration.

## Benchmark and measurement

**D10. Strip-and-score.** `bench/harness.py` strips the bus nets' tracks and vias, keeps everything else as
obstacles, and scores a candidate on connectivity, violations, lengths, vias and layers. Do-nothing scores 0.000,
the original 0.99. 5 to 16 s a run. Pitfall: delete items with `board.Delete`, not `board.Remove`. Measurement,
2026-09-17.

**D12. Synthetic BGA-pair cases** (`bench/synthetic.py`): 6x6 straight and reversed on 4 layers, 9x16 on 6, 20x20
on 8 with a three-column bus; each loads, passes DRC, and has exactly its bus and power nets open. 2026-09-17.

**D17. The benchmark hands the router each reference's constraints as if agreed upstream.** A constraints file
per reference stands for what stages 1 to 4 would have produced: pitch, pad, ball map, the copper spacing and
hole-to-copper the board's own copper meets (binary search under an overriding rules file), widths and vias per
package, the layers the bus may use, via style, thickness. The gate is zero electrical violations under those
values, which the original meets by construction. Owner, 2026-09-18.

**D18. KiCad 9.0.9's DRC caps each violation type at about 200 and which ones it keeps varies run to run**, so a
count near the cap is truncated and not repeatable. The benchmark's rules file holds every electrical rule at
zero for all items and applies the measured values only to pairs touching the nets under test, by explicit net
name (a net class injected into the project file did not take effect under `kicad-cli`). Measurement, 2026-09-18.

**D25. A result must not depend on item order.** The negotiation converged in one process and stalled in
another on identical input because islands were listed in board-item order, which varies with string hashing.
Inputs are sorted by geometry; per-round digests agree across hash seeds. Measurement, 2026-09-18.

**D33. A bench parameter chosen by assumption invalidated every routing measurement taken under it.** The bus
bench's default 0.8 mm extra spacing between bus nets made every net contested by construction on a 0.8 mm
lattice; 0.4 stalls too, 0.0 and 0.2 do not. Every bus routing figure from 18 September was taken inside that
stall. Rule (D38): every recorded result names its commit, environment overrides and resolved settings, and a
parameter that changes a result is measured before it is set. Measurement, 2026-09-19.

**D38. Provenance is a rule with a mechanism**: the bench writes the commit, overrides and resolved costs with
every result, and a result without them is not quotable. Also: M3 split into a plan (M3a) and a route inside it
(M3b); the class C ladder rises OrangeCrab, LogicBone, ButterStick. Owner, 2026-09-20.

**D43. The 54-of-55 bus result of 18 September is not reproducible and is not bisected**; 42 of 55 is the
baseline. Those runs had no plan behind them, so neither figure is comparable to a route inside one. Owner,
2026-09-20.

**D50. The whole-board benchmark** (`bench/rebuild.py`, `scripts/gate.py m4`, now `a`). The problem board is
placement, pads, outline and keepouts with every track, arc, via and pour removed; the criterion is every
routable net connected and zero electrical violations under rules measured off that board. The sanity pair
(original 1.000, stripped 0.000) is asserted per board in `tests/test_rebuild.py` and found four scoring
defects: single-pad nets counted as connected; violations between two fixed items charged to the router; an
`Arc` on `Edge.Cuts` read as copper; net names escaped in the API and unescaped in the DRC report
(`kb.unescape_net`). `harness.drc_facts` has the fourth defect latent. Measurement, 2026-09-21.

**D58. A KiCad 5 board's legacy zone fills fail KiCad 9's DRC until refilled; its net-class rules survive the
conversion, its project rules do not.** Under the rules KiCad 9 applies with no project file, the three KiCad 5
class A references show 19, 4 and 241 violations, almost all "zone clearance" of the zone's own setting short by
0.01 mm: the legacy fill converted "best effort". After `ZONE_FILLER` in KiCad 9: 0, and 15 on
`libresolar-mppt-2420` (3 at KiCad 9's default 0.2 mm, which its designer never used, 12 edge). `kicad-cli pcb
drc` never refills. The designers' net-class clearance and width are in the board file and load (tinkerforge
0.150 / 0.300 mm); the project-level rules of KiCad 5's `.pro` are not read. The benchmark's measured rules are
unaffected: they are measured off the copper and every converted original passes them (`tests/test_rebuild.py`).
Measurement, 2026-09-23.

**D59. Why Freerouting's copper fails the rules the reference meets** (four class A boards, 2026-09-23,
`build/bench/rebuild/*/candidate.json`). Same widths and vias as the reference; the copper is placed
differently. (1) 48 clearance violations short by under 0.011 mm: the router keeps every coordinate as an
integer at 0.1 um and every round shape as an octagon (`geometry/planar/IntOctagon`), which lies inside the
true circle by up to 7.6 % of the radius (0.011 mm on a 0.30 mm trace end, 0.027 on a 0.70 mm via); its own
check passes, KiCad's exact one does not. (2) 40 width violations by 0.03 mm or more on `open-book-c1`: traces
necked where they enter a pad; `automatic_neckdown` off changes nothing. (3) 26 violations of 1.016 and
1.85 mm: per-pad clearance overrides on fiducials and mounting holes, which the Specctra export does not carry.
(4) Ground left as tracks where every class A reference pours it. Under the designers' own project rules our
copper fails the same way (open-book 48, esp32c3 31; the originals 0). Measurement.

**D60. The smoke test passes the class A gate with Freerouting inside three repairs** (`gate.py a
tinkerforge-temperature`, 2026-09-24, commit of this entry): 6 of 6 nets, 0 violations, score 1.000, 28 s.
The router is handed every clearance less 0.0072 mm (D57) and its output is repaired under KiCad's own DRC
(`route/freerouting.py`): pads with a clearance override exported as keepouts grown by the override less the
clearance (D59 kind 3; on `olimex-esp32c3-devkit` 16 hole violations to 0); tracks the router necked set back
to the rule width (kind 2; on `open-book-c1` 40 width violations to 0, 40 clearance ones in their place); each
clearance violation's track moved away by the shortfall plus 0.002 mm, tracks sharing its ends carried along,
up to four DRC rounds (kind 1; on the smoke board 9 violations to 0 in 3 rounds, 8 moves). Runs are
deterministic per configuration; a subset of the gate is a rung, never the milestone. Measurement.

## Class A (in progress)

**D49. The class A ladder rises**: `tinkerforge-temperature`, `open-book-c1`, `olimex-esp32c3-devkit`,
`olimex-rp2040-pico-pc`, `crkbd-corne-cherry`, `libresolar-mppt-2420`; the last is the one whose power on
continuous copper matters. Owner, 2026-09-21. (The rest of D49, taking M4 ahead of M3b, is superseded by D55.)

**D51/D52. The homegrown single-stage router reaches 4 of 6 nets on the smoke test and is parked.**
`route/board_router.py` (grid A\*, exact collision per edge, no global stage, no rip-up): on
`tinkerforge-temperature` 4 of 6 nets, 0 violations, score 0.667, 8 s; `open-book-c1` 25 of 35;
`olimex-esp32c3-devkit` 29 of 34 in 441 s; `olimex-rp2040-pico-pc` killed at 13.3 GB; two boards exceed its
400,000-node ceiling. Facts that stand for any stage 5: a TSSOP-8 or SOT-563 row leaves 0.2 to 0.25 mm between
pads, so nothing passes between them and every such pad needs an escape stub ending at a computed point, not a
lattice node; a failed net's copper must come off the board inside the run; a one-way graph and copper left
behind were both found only by running. Measurement, 2026-09-21.

## BGA escape (the class B+ machinery; passes its gate)

**D13. How the references escape their bus balls** (`bench/fanout_measure.py`). Dog-bone vias sit in the
diagonal gap and the outer one or two rings leave on the top layer without a via, on every board; via-in-pad is
one board's choice (ButterStick); empty positions (a DRAM's middle rows, a depopulated csBGA) are used; escapes
leave on several sides. Width and via size differ per package on one board (OrangeCrab: 0.089 mm tracks and
0.28 mm vias at its 0.5 mm FPGA, 0.105 and 0.3 at its DRAM). Measurement, 2026-09-17.

**D14. `ZONE_FILLER.Fill` hangs on OrangeCrab's top-layer zones** and cannot be interrupted from Python, so
`kicad/refill.py` fills in a child process: all zones, then per layer, then per zone. Measurement, 2026-09-17.

**D15. The escape is a lattice router with negotiated congestion (PathFinder), not a recipe.** The salvaged
recipe stopped at 154 of 155 and 116 of 128 balls. Dropped with numbers in the archive: deepest-first order,
a shared edge-clearance cache (shorts), duplicate resources (no convergence), hard site assignment by matching,
re-routing every ball in the final pass. Measurement, 2026-09-17.

**D19. 0.5 mm pitch stays in scope; the tool is fixed, not the criteria.** Owner, 2026-09-18.

**D20. Inner layers on a quarter-pitch grid, conflicts judged per ball on an eighth-pitch grid, partners ripped
up when the contested set stops shrinking, final pass under the exact collision test.** Gate `m2` (now
`escape`): 9 of 9 cases, 461 of 461 bus balls, zero violations. Measurement, 2026-09-18.

**D36. An escape computed before the bus is not the bus's escape.** On the class C boards 50 to 65 % of the
balls the escape gate certifies are never requested by the bus router, because which via site a ball takes
fixes the order its lane leaves the package. The escape gate therefore stands for packages with no
length-matched bus behind them (class B+); for a bus package the escape is an output of the bus plan.
Measurement, 2026-09-19.

## DDR3 bus (class C; parked by D55)

**D11. Bus facts.** OrangeCrab: 50 nets, csBGA285 at 0.5 mm to one FBGA-96, 6 layers, 15 to 29 mm. ULX3S:
SDRAM, 39 nets, 4 layers, 27 nets on the top layer only. Measurement, 2026-09-17.

**D22. The bus router routes each memory from its bare pads**, because a dog-bone via in every gap of a DRAM's
array leaves no inner-layer channel for a bus that passes through it: our fan-out put 24 vias between
ButterStick's memory balls where the reference puts one and used 3 hollow sites where it uses 72. The
contested-net count originally quoted here was measured inside D33's stall and proves nothing; the geometry
stands. Measurement, 2026-09-18 and 2026-09-19.

**D23. Length is made by meanders inside the DRAM area, not by detours through free board.** ButterStick keeps
its 55-net bus (29.5 to 43.6 mm) inside the two DRAM footprints plus a millimetre or two; detours through free
board fired late and walled nets in. Measurement, 2026-09-18.

**D27. The length criterion is the matching the references achieve, per group**: each data lane within the
reference's own lane spread on total length (ButterStick 0.73 and 0.84 mm; LogicBone 4.15 and 7.1), each pair
within 0.2 mm, address/command/clock within the reference's spread at each memory's pins (ButterStick 11.9 and
7.5 mm; LogicBone 6.6 and 6.1). Absolute length is free. Owner, 2026-09-19. Subject to D30.

**D29. A capacity-only planner plans layers and capacity but not order**; the crossings are the bundles' own
twist (34 inversions of 55 in ButterStick's lane 0). `route/plan.py` is that cell planner, kept for the replay
and comparison scripts. Measurement, 2026-09-19.

**D30. Open: the class C length criterion.** Either D27 (the references' own spreads, which they pass by
definition) or the silicon vendor's rule for the part (Lattice FPGA-TN-02038: ±50 mil DQ to DQS, ±10 mil per
pair, ±100 mil address/command to CK, length only, no picoseconds and no DQS-to-CK rule). Measured (D45, D47,
D48): every class C reference is outside Lattice's address-and-command window at every memory, on total length,
per leg, and as delay alike. Byte lanes: LogicBone matched its lanes in delay and OrangeCrab in length, so no
single unit grades all three answer keys the same way. Decided when class C starts, not before.

**D31/D32. What both references obey inside a ball array**: a via sits on a ball or on a corner between four,
never in the channel between two (0 of 154 reference array vias; ours put 8 and 6 there); each package keeps to
one escape style; the reference uses at most 3 (ButterStick) or 4 (LogicBone) vias per net. "No via between
balls, ever" and "the top layer carries escapes only" were ButterStick-only and LogicBone refutes both (89
corner vias, 170 mm of top-layer transit). ButterStick's hollow cells are a permutation network allocated by
lane order, not first come. Measurement, 2026-09-19.

**D39. The bus plan is crossing-free by construction**: one grid per layer whose lines are every package's own
half pitch (a ball, a corner and a channel are all nodes), node-disjoint paths on a monotone grid cannot cross,
via sites are columns held by one net, and a layer carrying fewer than 20 non-bus nets is a plane the bus does
not cut (separates cleanly on all three boards). After round one only the nets in conflict are re-routed.
Measurement, 2026-09-20.

**D40. A deficit is measured against the group's spread (D27), not its longest net; room is the serpentine a
run's held amplitude affords, `l*(sqrt(1+4a^2)-1)`**, and only room the net holds alone counts. Congestion cost
capped at 15 mm, wander at 1.5x plus 4 mm, a via costs 8 mm. Measurement, 2026-09-20.

**D41. A repair may not make a new conflict, and a plan must make its lengths, not only reserve room for them.**
Repairs route on free nodes only (monotone); a net below its group is grown in place by writing the serpentine
into the plan. Lesson: a criterion two knobs can trade against each other has a missing mechanism. Gate `m3a`
(now `busplan`): 3 of 3 class C references. Measurement, 2026-09-20.

**D42. The fab demands of a BGA follow from pitch and pad, before routing**: one track through the channel is
`(pitch - pad)/3` (OrangeCrab's 0.089 mm is exactly that at 0.5 mm; 0.8 mm gives 0.133), and the via that fits
between four balls is standard-tier at 0.8 mm and not at 0.5 mm. Via-in-pad and 0.089 mm tracks on ButterStick
are choices, not the part's. Every DDR3 reference runs its bus under 0.1 mm spacing somewhere. Measurement,
2026-09-20.

**D45. Vendor rules verified from primary text**: Lattice (above); ISSI ±10 ps DQ to DQS, ±5 ps CK to DQS,
point-to-point, subordinate to the controller vendor; TI KeyStone ±20 mil address to CK measured controller to
each SDRAM separately. No vendor ties a tolerance to a data rate. `research/ddr3-bus-routing.md` had blended
ISSI's picoseconds into Lattice's rules; corrected in place. Measurement, 2026-09-21.

**D47/D48. Per leg against the signal each rule names, in copper and as delay** (`scripts/segment_lengths.py`,
`bench/delay.py`): address/command is outside Lattice's 2.54 mm at all five memories in every unit; OrangeCrab's
lane 0 runs its bits on `B.Cu` and its strobe on `In2.Cu`, 27 ps of skew at matched copper. Measurement,
2026-09-21.

**D54. The delay model is length times one of two constants** (5.59 ps/mm outer, 7.08 inner at er 4.5; no
width, no dielectric height; a real stackup on ButterStick only) and is not a tolerance. The constraint every
vendor states removes the need for one: all nets of a matched group on one layer, then matching length is
matching delay. Report modelled delay beside a result, never as its criterion. Measurement, 2026-09-21.

## Dropped from this log

Full text in the archive. D16 (PCBWay tier applied to references; superseded by D53). D21 (M3 start; procedural).
D24 (bus repair by local negotiation; parked code). D26 (owner's direction to read the references first; now the
working agreement). D28 (replay numbers measured inside D33's stall). D34 (a review). D35 (class C order; in
D38). D37 (the proposal D38 accepted). D44 and D46 (the failed research rounds; the rule is in D53 and
CLAUDE.md). The remainder of D49 (M4 before M3b) and D51/D52's router-specific detail (superseded by D55).
