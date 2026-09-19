# Decisions log

Newest at the bottom. Each entry records what was decided, the evidence, and what was tried and dropped, so nothing is
tried twice. Numbers stay with the decision that produced them.

## 2026-09-17, session 1: definition and foundation (M0)

**D1. Scope.** The product is the six-stage pipeline in `definition.md`, general purpose. The `waffle-fpga` board is
the hardest benchmark, not the deliverable. The owner refined "zero intervention" to "zero interactive routing": the
owner intervenes on blockers and design revisions; the tool never hands back copper to draw. The tool changes
placement, pin assignment, layers, via types and board size on its own; the owner is asked only about the maximum board
size, material cost, and agreed interface positions (section 4 of the definition).

**D2. Language and stack.** Python 3.11, because it is the interpreter KiCad 9.0.9's `pcbnew` bindings are built for
in this environment. KiCad 9 CLI and Python API for every board operation. z3 for assignment and plan problems (the
brief: a plain satisfiability check solves in seconds; the optimiser with soft constraints timed out). numpy and
shapely for geometry. pytest. Freerouting is not installed at M0; whether it has any place is decided at M4.

**D3. Reference boards.** Fetched by script, never committed (both are CERN OHL v1.2; attribution lives in the fetch
script and in `plan.md`). Pinned commits: ButterStick `0694ddfa9824a07f0c6c6981186e45f80187659c` at
`butterstick-fpga/butterstick-hardware` (the brief's path `butterstick-hw` does not resolve), LogicBone
`96e7bede72569be4db95d78e45a689c939225802` at `oskirby/logicbone`. Measured on first load in pcbnew 9.0.9:

| Board | File format | Copper layers | FPGA | DRAM | Footprints / nets | Tracks / vias | Dominant track widths | Via sizes (pad/drill) |
|---|---|---|---|---|---|---|---|---|
| ButterStick r1.0 | 20211014 (KiCad 6) | 8: F, In1..In6, B | U4 ECP5UM5G-85 caBGA381 | U11, U12 MT41K64M16 FBGA-96, rotated 90, at (16.7, -4.0) and (16.7, 7.4) mm from the FPGA | 350 / 350 | 19487 / 1163 | 0.12 mm (10358), 0.089 mm (7701) | 0.45/0.2 (629), 0.4/0.2 (534) |
| LogicBone | 20171130 (KiCad 5) | 8: F, Gnd1, Sig1, Pwr1, Gnd2, Sig2, Gnd3, B | IC1 ECP5UM caBGA381, rotated 90 | IC2, IC3 DDR3 TFBGA-78 at (5.0, 20.6) and (-5.1, 20.6) mm | 276 / 387 | 9859 / 658 | 0.135 mm (5892), 0.15 mm (1624) | 0.5/0.2 (658) |
| ButterStick r0.2 | 20171130 (KiCad 5) | 6 | U3 ECP5U25 caBGA381 | none (HyperRAM) | 256 / 324 | 16942 / 792 | 0.10 mm | 0.45/0.2 |

The DDR3 bus copper, measured by `waffle_eda.bench.references.measure` (`build/measure-<board>.json`):

| Board | Bus nets | Vias, inside footprints | Vias per net | Length mm min / median / max | Layers (nets using) | Bus track widths |
|---|---|---|---|---|---|---|
| ButterStick r1.0 | 55 under `/FPGA-DDR3L/` | 149, 148 (99 %) | 0: 2, 2: 10, 3: 43 | 29.5 / 32.2 / 43.6 | F.Cu 45, In5 40, In2 28, B.Cu 21 | 0.12 mm (7650), 0.089 mm (1637) |
| LogicBone | 50 under `/FPGA Memory/`, five of them active-low `~{...}` | 99, 96 (97 %) | 0: 16, 2: 6, 3: 25, 4: 3 | 12.4 / 33.1 / 43.5 | F.Cu 50, B.Cu 28, Sig2 22, Sig1 19, Gnd2 1 | 0.135 mm (2959), 0.15 mm (1624), 0.14 mm (416) |
| ButterStick r0.2 (HyperRAM, not DDR3) | 26 under `HB[01]_` | 29, 13 (45 %) | 0: 10, 1: 3, 2: 13 | 10.4 / 10.8 / 14.1 | F.Cu 26, In2 13, B.Cu 6 | 0.102 mm |

These agree with the brief's figures (DRAM offsets to 0.1 mm, three vias on every ButterStick data net, 16 LogicBone
nets with no via, layer changes at the packages). Two findings for the harness: "inside the package" must be the
footprint bounding box (on the pad-centre box grown by half a pitch the shares read 92 % and 94 %, on the footprint
box 99 % and 97 %); and net naming is per board (LogicBone writes active-low names with KiCad's overline syntax and
has a `DDR3_VREF` supply under the same prefix), so the bus selector is a per-reference pattern with its expected
count recorded in the registry. LogicBone loads with "legacy zone fill strategy is not supported" and converts fills on
a best-effort basis; the harness must refill zones before any DRC or connectivity check on it. API finding: in KiCad 9
`PCB_VIA.GetWidth()` without a layer argument asserts (padstacks); `waffle_eda.kicad.board.via_diameter_mm` passes the
layer.

**D4. Salvage policy.** The `waffle-fpga` tools are copied verbatim into `salvage/waffle-fpga/` from branch
`claude/ecstatic-feynman-0oiyyn` at commit `9dc63f0656db2554ff5cc40bed9617599a823bed`. All 35 Python files parse. They
are reference material: the package never imports them. Each tool is rewritten into `waffle_eda/` with tests, against
the references, before it is used. The documents worth carrying are in `docs/lessons/`.

**D5. Fab profile.** PCBWay first, as a data file (`waffle_eda/fab/profiles/pcbway.toml`) built from the capability
numbers the last project captured, so JLCPCB becomes a second profile rather than a rewrite. Price is recorded as
unknown until real quotes are captured. Via-in-pad is off by default (LogicBone's style) and available as an option.

**D6. First end-to-end target and build order.** A small class A or B board is the first end-to-end target; the
simplified FPGA board is the stretch benchmark scored from the start. Build order: benchmark and routing depth (M1 to
M4) before the front half (M5). Rationale: the routing back half is the unsolved part, and the front half is what the
last project did by hand well enough.

**D7. Repository layout.** `waffle_eda/` is the package (`kicad/` board helpers, `bench/` references and scoring,
`fab/` profiles; stages are added as they are built). `scripts/` are thin entry points. `tests/` run without the
references and skip what needs them. `references/` and `build/` are ignored by git. `docs/` holds the definition, plan,
this log, and the carried lessons. `salvage/` holds the old code.

**D8. Many references, not two.** The owner's note (session 1): ButterStick and LogicBone are two boards that happened
to be picked; the tool needs many more and simpler ones. The registry (`waffle_eda/bench/references.py`) is a dict
meant to grow, and the ladder in `plan.md` now asks for several boards per class. Candidate repositories confirmed to
exist on 2026-09-17 (format, licence and layer count still to verify): `orangecrab-fpga/orangecrab-hardware` (ECP5 and
DDR3L in a Feather outline, class C), `emard/ulx3s` (ECP5 with SDRAM, no DDR3), `im-tomu/fomu-hardware` and
`tinyfpga/TinyFPGA-BX` (small iCE40 boards), `icebreaker-fpga/icebreaker` (default branch `archive`). The class A and
B survey is the first M1 task: open hardware, KiCad format, permissive licence, one or more per class.

## 2026-09-17, session 2: M1, the benchmark

**D9. The reference survey and the ladder.** 33 candidate repositories were probed with `scripts/survey_references.py`
(shallow blobless clones, only the board and licence files fetched): 25 held KiCad boards, 108 board files in all, 7
of which pcbnew 9.0.9 cannot load. Picked, 20 new boards plus the 3 from M0, all fetched and measured (see
`references.md`). Rejected: `icebreaker-fpga/icebreaker`, `greatscottgadgets/greatfet`, `micropython/pyboard`,
`jakkra/ZSWatch`, `sparkfun/SparkFun_Thing_Plus_RP2350`, `adafruit/Adafruit-Feather-RP2040-PCB`, `vroland/epdiy`
(no `.kicad_pcb` at the pinned commit: other formats, or files elsewhere); `hydrabus/hydrabus`,
`Tinkerforge/ethernet-extension`, `icebreaker-fpga/icebreaker-pmod` (no licence file); `Hanqaqa/Easyduino` (all six
boards fail to load, a newer file format); `greatscottgadgets/hackrf` (RF layout is a non-goal). Two picks are GPL
hardware (the OLIMEX class A boards) and three are CC-BY-SA; they are benchmark inputs only and nothing from them is
redistributed. Two boards carry a bus other than DDR3 and enter the harness: ULX3S (SDRAM, 39 nets) and OrangeCrab
(DDR3L, 50 nets under `RAM_`). Survey findings worth keeping: the KiCad footprint name is not a package type
(TinyFPGA's BGA is called `CM81`), so the survey detects a BGA as a filled lattice of pad centres, which a perimeter
package (LQFP) fails; `pcbnew.LoadBoard` returns None rather than raising for a file it cannot parse.

**D10. The strip-and-score harness.** `waffle_eda/bench/harness.py` strips only the bus nets' tracks and vias (pads
and every other net stay as obstacles) and scores a candidate against the original: connectivity and unconnected
items from a fresh `kicad-cli pcb drc` run, electrical violations touching bus nets relative to the answer board's
own count under the same rules (the references are not clean under KiCad 9: ButterStick 53 violations, 16 clearance;
LogicBone 639, 227 clearance, 72 of them touching the bus), per-net length within the answer's spread, vias inside
the packages, vias per net, layers used. Composite score is connectivity times a weighted sum, so "do nothing" scores
0.000 and the answer 0.992 (ButterStick) and 0.997 (LogicBone); a run takes 5 to 16 seconds, DRC included. Pitfall
recorded in the board helpers: remove items with `board.Delete`, not `board.Remove`, or SWIG prints a leak warning per
item and the next load in the process can come back without its proxy class. Open: the LogicBone harness test failed
once in a full-suite run (41 passed, 1 failed) and passed on every rerun, alone and in the suite; the assertion text
was lost to a pipe. The test now prints the score summary on failure so a recurrence explains itself.

**D11. Measured bus facts on the new boards.** OrangeCrab r0.2.1: DDR3L bus of 50 nets between a 0.5 mm-pitch
csBGA285 and one FBGA-96, 6 layers, 42 nets with exactly two vias, 95 % of vias inside the footprints, lengths 15.0 to
29.0 mm (median 15.3), on F.Cu, In2.Cu and B.Cu: one DRAM on six layers, the closest reference to the simplified
target. ULX3S: SDRAM bus of 39 nets between a caBGA381 and a TSOP-54, 4 layers, 27 nets on the top layer only, 12 with
two vias, 54 % of vias inside the footprints, lengths 16.5 to 32.9 mm, F.Cu and B.Cu only: a caBGA381 fan-out on four
layers with a slow bus. ButterStick r0.2 (HyperRAM): 69 % of vias inside the footprints on the footprint-box test.

**D12. Synthetic cases.** `waffle_eda/bench/synthetic.py` writes two-package BGA boards with pcbnew: rows x columns
of 0.4 mm balls at 0.8 mm pitch, a bus between the facing columns in straight, reversed or random ball order, a few
GND and VCC balls at the centre, the fab rules in the design settings, an outline and courtyards. Four cases: 6 x 6 on
4 layers (straight and reversed), 9 x 16 on 6 layers, 20 x 20 on 8 layers with a three-column bus. Each loads, passes
DRC with zero electrical violations and exactly its bus and power nets open. Feasibility per case is recorded as
unknown until a router or a proof settles it (M2, M3); the reversed 6 x 6 is the first case expected to need layer
changes.

## 2026-09-17, session 2 (continued): M2, the fan-out

**D13. How the references escape their bus balls (evidence for the fan-out).** Measured by
`waffle_eda/bench/fanout_measure.py` (`build/fanout-<key>.json`): for every bus ball, its ring, the nearest via of
its net in pitches, and the layers inside the package.

| Board, package | Pitch, pad | Via at the ball | Outer rings on the top layer without a via | Via sizes |
|---|---|---|---|---|
| LogicBone IC1 (FPGA) | 0.8 mm, 0.3 mm | 32 of 34 in the diagonal gap, 2 one gap further | ring 1: 9 of 16, ring 2: 5 of 11, ring 3: 2 of 10 | 0.5 / 0.2 mm |
| LogicBone IC2, IC3 (DRAM) | 0.8 mm, 0.42 mm | 22 and 26 diagonal, a few one gap further | ring 2: 5 of 15, ring 3: 3 of 17 | 0.5 / 0.2 mm |
| ButterStick U4 (FPGA) | 0.8 mm, 0.4 mm | 46 of 53 in the pad | ring 1: 4 of 13 on F.Cu, 7 leave on B.Cu | 0.4 / 0.2 mm, filled and capped |
| ButterStick U11, U12 (DRAM) | 0.8 mm, 0.4 mm | 10 and 8 in the pad, most balls leave on the top layer into the empty middle rows | rings 2 and 3 mostly | 0.4 / 0.2 mm |
| OrangeCrab U3 (FPGA) | 0.5 mm, 0.23 mm | 17 diagonal, many one to two gaps away and off the lattice, in depopulated positions | ring 1: 9 of 20, ring 2: 4 of 12 | 0.28 and 0.3 / 0.15 mm |
| OrangeCrab U4 (DRAM) | 0.8 mm, 0.4 mm | 24 diagonal, 8 near | ring 2: 2 of 18 | 0.3 / 0.15 mm |
| ULX3S U1 (FPGA) | 0.8 mm, 0.4 mm | 12 diagonal; 27 of 39 nets have no via at all | rings 2 and 3 entirely on F.Cu | 0.419 / 0.2 mm; only B.Cu is available below |

Rules the measurements support: the dog-bone via belongs in the diagonal gap and the outermost one or two rings
leave on the top layer without a via (every board); via-in-pad is one board's choice, not the norm; where a
package has empty positions (a DRAM's middle rows, a depopulated csBGA) the copper uses them; a package's
escapes leave on several sides, not only toward the bus partner (ButterStick's DRAM: S 17, W 16, N 10). Rules the
fan-out must be told per package: track width and via size differ per package on one board (OrangeCrab's 0.5 mm
FPGA uses 0.089 mm tracks and 0.28 mm vias; its DRAM 0.105 mm and 0.3 mm). Two boards carry design rules their own
copper violates (LogicBone's 0.25 mm hole clearance, 70 violations; ULX3S's 0.5 mm minimum via against its 0.419 mm
vias), so the DRC gate for the fan-out compares violations touching the bus nets against the original's own
counts by type, and the fan-out works to the net class clearance and the measured copper.

**D14. KiCad's zone filler hangs on the OrangeCrab board.** `ZONE_FILLER.Fill` on all zones, and on the group of
25 top-layer zones, never returns; every zone alone fills in 0.3 s and every other layer group in about a second.
A hang inside a C++ call cannot be interrupted from Python, so `waffle_eda/kicad/refill.py` fills in a child
process on the saved file: all zones, then per layer where that times out, then per zone. The harness reuses a
stripped board it already has, because that refill takes about three minutes on OrangeCrab.

**D15. The fan-out is a lattice router with negotiated congestion, not a recipe.** The recipe from `waffle-fpga`
(`waffle_eda/route/fanout.py`, kept for comparison) reached 154 of 155 balls on ButterStick and 116 of 128 on
LogicBone and could not go further: a trace along the package edge blocks the top layer, capacitors on the back
block in-pad vias, the empty middle of a DRAM is where the original escapes. `waffle_eda/route/escape.py` treats
the package region as a half-pitch lattice on every routable layer, checks every step and via against the real
copper with KiCad's collision test, and resolves conflicts between the balls by negotiated congestion (PathFinder):
each ball routes with a cost on lattice resources other balls use, the penalty rises per iteration, only balls in
conflict are re-routed, and the final pass commits the conflict-free negotiated paths as they are and re-routes the
rest with hard occupancy and a local rip-up repair. Resources are lattice nodes per layer, diagonal cells, and via
neighbourhoods that grow with the pitch: at 0.5 mm a via blocks the four channels beside it and a diagonal its two
corners, computed from the rule values, not assumed. Results, `scripts/fanout_bench.py`, on the problem boards with
all other copper in place (session 2): synthetic cases 4 of 4 complete and DRC clean; ButterStick 155 of 155 balls,
DRC clean, in-pad style; LogicBone 128 of 128, 2 hole-clearance hits against the original's 70; OrangeCrab 92 of 100
(the 0.8 mm DRAM complete, the 0.5 mm-pitch FPGA 42 of 50); ULX3S 38 of 39. Two to five seconds per package.
What was tried and dropped, with numbers: deepest-first order with cheap top-layer steps (deep balls consumed the
outer rings' channels: 66 of 84 on the synthetic 20 x 20); a shared edge-clearance cache (one net's own copper read
as clear for the next: shorts); a resource list with duplicates (single-user resources counted as shared, no
convergence: 15 of 16 on a 6 x 6); a hard site assignment by bipartite matching before routing (less flexible than
the cost preference: 39 against 45 of 50 on LogicBone IC1); re-routing every ball in the final pass (lost five where
three conflicts existed). Open: the 0.5 mm-pitch packing (OrangeCrab U3, 8 balls) and one ULX3S ball whose only
inner layer is contested; both fail with the per-ball blockers reported, as the definition requires.

## 2026-09-18, session 3: manufacturability of the references and the target

**D16. Manufacturability of the references and the target at PCBWay, corrected.** Raised by the owner. The first
version of this entry, written on 2026-09-18 from an automated summary of PCBWay's capability page, assigned rows of
the advanced-tier table (5/6 mil outer, 0.5 mm vias) to the standard tier and concluded that a 0.8 mm caBGA could
not be dog-boned there. The page text, read directly the same day, says otherwise. What PCBWay publishes
(https://www.pcbway.com/capabilities.html, 2026-09-18):

* Standard quick-order tier: minimum trace and spacing 0.1 mm (4 mil); drill 0.15 to 6.0 mm, holes under 0.2 mm
  at extra charge; minimum annular ring 0.15 mm (6 mil); 1 to 14 layers.
* Advanced tier, 0.5 oz outer copper before plating, by difficulty (normal / medium / high): outer trace and spacing
  4/5 mil, 4/4 mil or 3.5/3.5 mil locally between a BGA's pads, finer on review; inner 4/4 mil normal, 4/3.5 mil
  medium; via annular ring 5 mil normal, 4 mil medium; inner-layer hole isolation on 8 layers 9 mil normal, 7 mil
  medium, 6 mil high; thickness-to-hole ratio 8 normal, 10 medium, above 12 not offered; via-in-pad, filled vias,
  blind and buried vias.

The references' bus copper, measured on 2026-09-18 by binary search with an overriding rules file
(`build/rules/demonstrated.json`), against the standard tier:

| Board | Bus spacing | Bus tracks | Via pad/drill, ring | Hole to copper | Outside the standard tier on |
|---|---|---|---|---|---|
| ButterStick (8 L) | 0.089 mm | 0.089, 0.10, 0.12 mm | 0.4/0.2 and 0.45/0.2, ring 0.10 and 0.125 mm | 0.189 mm | spacing, tracks, ring; via-in-pad is advanced |
| LogicBone (8 L) | 0.080 mm | 0.135 mm | 0.5/0.2, ring 0.15 mm | 0.229 mm | spacing only (3.15 mil) |
| OrangeCrab (6 L) | 0.089 mm | 0.089, 0.105, 0.12 mm | 0.3/0.15 and 0.28/0.15, ring 0.075 and 0.065 mm | 0.154 mm | spacing, tracks, ring (2.6 mil, below the advanced tier's 4 mil medium) |
| ULX3S (4 L) | 0.127 mm | 0.127, 0.19 mm | 0.42/0.2, ring 0.11 mm | 0.236 mm | ring only (4.3 mil) |
| waffle-fpga's own rules | 0.10 mm | 0.10 mm and up | 0.45/0.2, ring 0.125 mm | 0.25 mm rule | ring (4.9 mil), within the advanced tier's 5 mil at rounding |

So none of the four references is entirely within the standard tier, each for a different reason, and everything
they do except OrangeCrab's 2.6 mil rings is within PCBWay's advanced tier at normal or medium difficulty. The
references remain valid answer keys for routing under their own demonstrated rules, which the benchmark measures;
they are not evidence about any one fab.

The target, a 0.8 mm caBGA with 0.4 mm pads at the standard tier's 4/4 mil and 0.15 mm ring: a 0.5/0.2 via in the
diagonal gap clears the pads (0.116 mm) and the top-layer channel between two pads carries one track (0.197 mm
free), but the 0.3 mm between 0.5 mm via columns cannot carry a 4 mil track with 4 mil on each side (0.305 mm
needed), so the inner rings cannot run out between the dog-bone vias. With 0.45/0.15 vias the gap is 0.35 mm and the
track fits with 0.045 mm to spare; that needs the 0.15 mm drill (surcharge, and 10.7:1 on a 1.6 mm board, which the
advanced table calls medium difficulty; 8:1 on a 1.2 mm board). The dog-bone fan-out of the target is therefore
feasible at the standard tier with 0.45/0.15 vias, marginal on drill and aspect ratio, and comfortable at the
advanced tier or with a thinner board. Board thickness and the fab tier are variables the tool can trade, with a
cost attached, once quotes are captured.

Consequences that stand from the first version: the benchmark's DRC criterion should be zero violations of our bus
copper under each reference's demonstrated rule values, fed to the router as its rules (pending the owner's word);
the fab tier for the target is a cost-ceiling decision the owner makes before M6, with confirmed capability and
quotes captured as profiles. Lesson recorded: an automated page summary is not a source; read the text.

**D17. The benchmark hands the router each reference's constraints as if agreed upstream.** Owner's decision,
2026-09-18. For every reference, the benchmark builds a constraints file that stands for the output of stages 1 to
4 that a real run would have produced for that board: the packages as chosen parts (pitch, pad size, ball map), the
fab class the board's own bus copper demonstrably meets (copper spacing and hole-to-copper distance measured by
binary search with an overriding rules file; track width, via pad and drill measured under each package), the
layers the bus may use, the via style and the board thickness. The router is fed those values and judged under
them: the gate requires zero electrical violations of our bus copper under the same rules, which the original
meets by construction. This replaces the relative comparison of violation counts (D10, D15) and removes the rule
values KiCad 9 injects into old files (D16) from the benchmark. The router had been working at each board's net
class clearance, 0.089 mm on ULX3S where the copper holds 0.127 mm, and without any hole-to-copper rule; both are
now inputs. Fab tiers and prices are a separate question for the target (D16); the references decide nothing about
any fab.

**D18. DRC counts are exact only under bus-scoped rules; M1 is judged at zero, like M2.** Measurement, 2026-09-18.
KiCad 9.0.9's DRC stops reporting a violation type at a cap, and which violations it keeps differs from run to run.
Observed on the LogicBone original: 199 to 202 hole-to-copper and solder-mask violations whatever the rule, and 501
under a 0.5 mm clearance rule against 502 under a 2.0 mm one; three identical runs each reported 200 hole-to-copper
violations, of which 77, 75 and 74 touched a bus net, where the answer report cached in session 2 had 70. Any count
taken where a type reaches the cap is truncated and not repeatable. This bit the M1 harness test on LogicBone (the
original scored 76 to 79 against its own cached 72 and failed against itself) and, in principle, the D17 search and
gate, where a bus violation could go unreported behind two hundred non-bus ones. Fix: the rules file the benchmark
writes (`harness.rules_file`) holds every rule-driven electrical constraint to zero for all items and applies the
measured values only to pairs with a bus net, through an explicit `A.NetName == ... || B.NetName == ...` condition
(a net class injected into the copied project file did not take effect under kicad-cli; the explicit list costs
two seconds on LogicBone). Bus counts are then exact while the bus itself has fewer violations than the cap, and a
nonzero count is nonzero either way. The M1 harness now judges a candidate under the same rules and the same target
as M2: zero electrical violations touching the bus, the answer's count being zero by construction; the relative
criterion of D10 is retired. Two corrections found in the same pass: the constraints file's minima are taken over
every bus track, arc and via on the board rather than the common sizes under the packages (LogicBone's bus has three
0.1 mm necks that the common 0.135 mm value failed, so the original failed its own file), and `measure` runs the
original under the file it writes and raises if it fails. A reused problem board reports what was stripped from a
manifest instead of None. A pcbnew pitfall found by the first gate run under D17 (a `SHAPE_CIRCLE` built in Python
collides only with a `SEG`) is recorded in `board.py` and covered by `tests/test_obstacles.py`.

**D19. 0.5 mm pitch stays in scope; the tool is fixed, not the criteria.** Owner's decision, 2026-09-18. The nine
failing balls of the M2 gate (OrangeCrab U3, eight balls at 0.5 mm pitch; ULX3S N18) are failures of the router and
are fixed as M2 work. The benchmark does not change: the problem board keeps every non-bus item as a fixed obstacle,
and the router must escape every bus ball through what the board leaves. The lattice model, which put vias only on
half-pitch nodes and paths only on lattice edges, is what has to change: the original fan-outs at 0.5 mm put vias off
the lattice and run longer top-layer paths. M2 passes only when `scripts/gate.py m2` exits 0.

**D20. The escape router routes inner layers on a quarter-pitch grid and negotiates per ball.** Measurement and
tool change, 2026-09-18, under D19. Why the old router missed nine balls the boards escape: its half-pitch lattice
had no legal inner-layer line next to a via row at 0.5 mm pitch (the line between two via rows is 0.25 mm from
each, and a 0.28 mm via, a 0.089 mm track and 0.0886 mm of clearance need 0.273), while the OrangeCrab fan-out
runs its inner tracks 0.04 mm off the ball rows, where the geometry works; and its negotiation stalled on small
clusters that a settled third ball could have resolved. What changed (`waffle_eda/route/escape.py`): inner layers
and the top layer outside the array are a quarter-pitch grid, the top layer inside the array keeps the half-pitch
nodes (a channel at a fine pitch has no slack), vias sit on half-pitch nodes inside the array and anywhere outside;
conflicts between escapes are judged on an eighth-pitch grid with offsets derived from the rules (track + clearance,
via radius + clearance + half a track, via + clearance) and counted per other ball, not per sample, so that a long
overlap costs what a short one does; when the contested set stops shrinking the contested balls' partners are ripped
up too, then the partners' partners, with the contested balls choosing first; the final pass commits under the exact
collision test against committed copper, with the negotiated history as guidance and nothing blocked by the model;
a stranded ball has its neighbours ripped up and re-placed around it in a growing radius and several orders. A
version that counted conflicts per sample made one overlap cost ten balls' worth and stopped negotiating; a version
that blocked on the model in the final pass refused paths the geometry allowed. Results in `docs/plan.md`. Tools
kept from the work: `scripts/draw_package.py` draws a package region (bus copper saturated, the rest faint) as SVG
and PNG through the headless Chromium on this machine; `ESCAPE_TRACE=1` prints the negotiation round by round.

**D21. M3 starts.** Owner's word, 2026-09-18, on the M2 gate output (PASS, 9 of 9). M3's criteria stand as the plan
writes them: ButterStick, then LogicBone; all bus nets connected, DRC clean under the reference's constraints,
every net's length within the original's measured spread, layer changes only inside the packages; a failure is a
diagnosis, never a list. The other bus references are run for information and reported; adding them to the M3 gate
is the owner's call.

**D22. The bus router fans out from the pads itself.** Measurement and tool change, 2026-09-18, under D21. With
the M2 escapes as its terminals, the bus router routed every ButterStick net in its first round but 47 of 55 stayed
contested for forty rounds, and on LogicBone one net never reached its second DRAM. The cause is the fan-out: a
dog-bone via in every gap of a DRAM's array leaves no channel on the inner layers for a bus that has to pass
through that array (the DRAMs sit 0.5 mm from the FPGA), while the original ButterStick escapes most DRAM balls on
the top layer into the empty middle rows and keeps the inner layers for the bus (D13). A fan-out chosen without the
bus in mind is not the bus's fan-out. So M3 strips the bus copper and routes each bus net from its pads: the pad is
the island, the via goes where the negotiation puts it (in the pad where the package uses in-pad vias, in a gap or
a channel otherwise, anywhere inside the footprint outside the array), and the top layer inside an array moves
between half-pitch nodes as the escape router does. M2's escape router and gate stand as they are; they answer
whether every ball can escape, and the bus router uses the same rules and the same geometry.

**Partly re-founded after D33.** The contested count quoted here (47 of 55 for forty rounds) was measured at
18:29 on 18 September, after the bench's 0.8 mm bus spacing arrived at 17:37, so that number is inside the stall
D33 describes and proves nothing on its own. The geometric reason does stand and was re-measured cleanly in D34:
our fan-out puts 24 vias between the balls of ButterStick's memories where the reference puts one, and uses 3 of
the hollow sites where the reference uses 72. The decision to route the memories from their pads therefore rests
on geometry, not on that count. The experiment it replaced (keep every package's escapes and route the bus at a
spacing the negotiation can work in) has not been redone and would settle it.

**D23. Length comes from meanders inside the DRAM area, not from detours through free board area.** Measurement
and tool change, 2026-09-18, under D21. The original ButterStick keeps its whole bus (55 nets, 29.5 to 43.6 mm)
inside the two DRAM footprints and a margin of a millimetre or two around them, on four layers, and makes the
lengths with tight serpentines in the empty middle columns of each DRAM and along the DRAM edges; the rest of the
board is packed with the other nets' copper and offers nothing. The bus router's first detour stage (a waypoint
in free board area for a net far below its window) therefore never fired on ButterStick: its estimate took the
two largest islands, which on ButterStick are the net's two DRAM pads 0.2 mm apart, and its candidates were
looked for on whole millimetres the quarter-pitch grid never lands on. Fixed (the estimate spans the tree's start
island and the farthest island, candidates are the node nearest each square millimetre, the second leg leaves the
waypoint and may not retrace the first, any island may start, the search learns how much longer a routed detour
runs than its estimate) the detours fire, but once the other 54 nets are placed a net is walled in: on the routed
v2 board every net that failed later routes alone on the stripped board in a second, and on the packed board no
waypoint is reachable from either of its ends. Giving the short nets their waypoint before the negotiation (v4,
38 nets) made every round seven times slower with every net contested; giving it only to nets more than 10 mm
short (v6, 20 nets) kept 50 of 55 nets contested where the plain negotiation has 19 by the tenth round. So the
detour stays a final-pass tool, the serpentine tuner is allowed inside the packages wherever it is more than half
a pitch from a pad (the DRAM hollows are where the reference meanders), and the router reports which nets its
tuner could not lengthen. Numbers: ButterStick v5 (pads, tuner in the hollows, nine detours) 36 of 55 nets within
the window against 28 before, with the command nets (CK, CKE, CS, ODT) 9 to 16 mm short.

**D24. A stranded net is repaired by negotiating its neighbourhood, not by re-placing it greedily.** Measurement,
2026-09-18. On the v5 ButterStick board the two stranded nets (CKE0 to U4.F18, DQ5 to U12.H8) route at once when
the bus copper within 1.5 mm of their pads is removed (17 nets), yet the final pass's repair, which rips those
nets up, places the stranded net and then re-places the others one by one, fails: one of the neighbours is
stranded instead, and everything is put back. The repair now negotiates the stranded net together with its
ripped-up neighbours against all other copper (fixed and committed) for a bounded number of rounds and commits only
a result in which every one of them is routed and uncontested; the exact geometry test decides at commit time and
a net the samples misjudged is searched again. Ripping up on the diagnosis's named blockers alone is kept as the
first, cheaper attempt. Measured on the v5 board around CKE0 the local negotiation of 18 nets still plateaus at
six contested after twelve rounds: the stall is the negotiation's, not the repair's (D25).

**D25. The negotiation's outcome depended on the order of the board's tracks; islands are now ordered by geometry.**
Measurement and tool change, 2026-09-18. The 20x20 synthetic bus case converged in six rounds in one process and
ran sixty rounds and stranded one net in two others, with identical boards and escapes. The cause: a net's islands
were listed in the order of the board's items, the tree started from the first of two equal islands, and that
order varied with the process's string hashing upstream. The islands are sorted by size and then by their
lowest point, so a run is now the same in every process (checked: the per-round path digests agree across hash
seeds). That the same problem converges under one order and stalls under another is the negotiation's weakness to
work on: the stall sets in with a few pairs that each have no conflict-free path while the nets holding the
alternatives are never asked to move.

**D26. The references are read before the router is designed further.** Owner's direction, 2026-09-19. The
references were chosen as ground truth for what a working, manufacturable bus is; the router had used them only for
constraints and for a score, and the score's length criterion (every net inside the reference's overall length
window) was a proxy the references themselves do not meet uniformly. Work on the negotiation stops. The plan:
measure each reference's bus design per net, per group and per package (`docs/bus-design.md`, step 1, done);
restate M3's length criterion from those measurements (owner's decision); check the router can reproduce the
reference's structure when given it as input (replay); turn the measured practice into the router's plan (layer
per group, entry sides, via budget, meander room reserved before routing); LogicBone second. Measured on step 1:
both boards match their data lanes on total net length to under a millimetre and their address and command
loosely (6 to 12 mm at the pins); every run between vias stays on one layer; ButterStick escapes the memory balls
on the top layer into the hollow and makes its length inside and around the memories, LogicBone dog-bones in the
array and makes its length between the packages.

**D27. M3's length criterion is the matching the references achieve, per group.** Owner's decision, 2026-09-19,
on the step-1 measurements (`docs/bus-design.md`). A bus passes on length when each data lane (its bits, strobe
pair and mask) lies within a window as narrow as the reference's own lane spread on total net length, each
differential pair is matched within 0.2 mm, and the address, command and clock group lies within the reference's
spread at each memory's pins. Measured windows: ButterStick lane 0 0.73 mm, lane 1 0.84 mm, address and command
11.9 mm at U11 and 7.5 mm at U12; LogicBone lane 0 4.15 mm and lane 1 7.1 mm on total length (the bits alone 0.11
and 0.38 mm; the strobes are routed shorter), address and command 6.6 mm at IC3 and 6.1 mm at IC2. The absolute
length is free. This replaces "lengths within the measured spread" (plan, M3), a proxy the references themselves
do not meet uniformly. Replay (D26, step 3) starts with ButterStick.

**D28. Replay of ButterStick: the search reproduces the reference's runs, the negotiation cannot pack them, and the
grid is not the reason.** Measurement, 2026-09-19 (`scripts/replay_bus.py`, logs `build/replay-butterstick*.log`).
The reference's 149 vias were put back on the stripped board and its 183 single-layer runs between terminals
(`bus_design.reference_plan`) given to the router as links, each searched on its layer with no via. Findings:
(1) every link routes on its own once a top-layer search may end on a via that sits off the half-pitch lattice
(the hollow vias do; fixed in `_search`); before that fix 2 of 183 failed and 5 more were the plan reader's own
fault (an inner-layer track passing under a pad was taken for its end; fixed). (2) With the reference's layers and
vias fixed, the negotiation still leaves 40 to 43 of 55 nets contested after 60 rounds; confined to a 0.35 mm band
around the reference's own route for every link it leaves 24 to 26. The reference's routes are therefore a packing
the negotiation does not find even when told where to look. (3) The grid pitch is not what stands in the way: on
both references no bus track runs closer than 0.20 mm centre to centre to another bus track on its layer, and most
of the close running is at 0.25 to 0.45 mm (ButterStick In5.Cu: 215 of 738 mm at 0.25 to 0.30), which a 0.2 mm
grid can represent; what it represents badly are the parallel diagonal runs, which need a two-step (0.28 mm)
offset on a square grid and whose sampled occupancy flags a one-step offset as a conflict. (4) The lanes are
twisted between the two packages: ordered across the bus direction, ButterStick's lane 0 changes order between
U4 and U11 by 34 inversions of a possible 55, lane 1 by 23; LogicBone's lanes by 11 and 19; the address groups by
110 to 177 of 351. The designers untangled them with the memory's hollow via field (a via's position in the hollow
sets the order in which the run leaves it) and with one layer per lane per leg, not with pin choice. What this
settles: the detailed search is sound; ordering, layer and via placement (the bus plan) must be decided before it,
as D26 step 4 and the research report say, and the bundle's detailed routing wants track-based river routing with
explicit spacing rather than a square grid with negotiation. Final pass of the band variant, for the record: 44 of
55 nets connected, zero electrical violations, 13 bus nets left unconnected, the D27 judgement failing on every
group because of them (14 minutes in all, most of it the repair).

**D29. The bus planner's first form, capacity negotiation on cells, plans capacity and layers but not order; order
is the whole problem.** Measurement and decision, 2026-09-19 (`waffle_eda/route/plan.py`, `scripts/replay_bus.py`
with `REPLAY_PLANNER=1`, logs `build/replay-butterstick-planner.log`, `build/plan-wide.log`). What was built
(D26 step 4, on the reference's escapes as the owner asked): a grid of 0.4 mm cells per bus layer over the routing
region; the capacity of each cell boundary is the number of tracks that cross it clear of the fixed copper (pads
as circles or rectangles, vias, tracks, and the escapes the plan keeps), the narrowest of three parallel cuts,
counted at the detailed grid's step (0.2 mm) so that the plan promises no more than the detailed router can hold;
around a run's own terminals the capacities are recomputed without its net's copper (the clock termination
resistors sit against U11's balls and only their own net gets out). Runs are the reference's via-to-via links and
its long runs to a pad (102 of 55 nets; the 81 escapes, top-layer pad-to-via runs under 8 mm, stay the reference's);
each is searched on every layer it may take (a pad terminal restricts it, a via allows all four) inside a corridor
around its terminals, with a turn cost, a bias off the top layer, a bundle affinity (runs of one group between the
same two packages prefer one layer) and PathFinder costs on the boundaries' usage; the length a net is short of its
group (D27 windows) is asked for as extra tracks beside its runs, taken where a boundary has them to spare and paid
for where it has not. Findings on ButterStick: (1) capacity is not what constrains this board: 113 by 87 cells,
23 to 31 thousand track-boundaries per layer, all 102 runs placed with no boundary over capacity within 3 to 12
rounds, 8 to 10 s in all; length room found for 27 of the 35 nets that need it, the per-rank command nets short
(ODT0 8.8 of 18.7 mm, CKE0 10.8 of 15.3, CS0 14.4 of 17.2), which is where the reference meanders in U11's margin.
(2) The layer choice with the bundle affinity reproduces the reference's bundle structure (lane 0 from U4 to U12
on B.Cu 11 of 11, lane 1 from U12 to U11 on In5.Cu 11 of 11, 55 of 102 runs on the reference's layer, the rest
on another inner layer). (3) Crossings decide everything and the cell negotiation does not resolve them: the
reference's own runs, rasterised to the same cells, cross nowhere on any layer (0 of 42 In5.Cu, 32 In2.Cu, 21 B.Cu,
7 F.Cu runs); the planner's shortest runs on the reference's own layers start with 234 crossings and 40 rounds of
negotiation with crossings as conflicts (the runs a run crossed cost it like an overflow, the shared cells gain
history) leave 186 to 241, spread over every layer (In5.Cu 162 of them at the end); with free layers 590 fall to
186 to 231; with the corridor widened to 12 mm, so that a run may come around the memory as the reference's do,
and 80 rounds, 259 remain (`build/plan-wide.log`) and the runs pushed off their partners detour to 44 and 53 mm
instead. Of the 241 crossings with the reference's layers, 184 are between runs of one bundle (address between
U11 and U4 48, address between U11 and U12 41, lane 0 between U11 and U12 33, lane 1 between U11 and U12 33, lane 1
between U12 and U4 23), 8 between bundles of one group and 49 between groups (`scripts/draw_plan.py` on the dump
`build/plan-ref-layers.json`, drawings in `build/plan-draw/`): the twist of D28, an order at one end that is not
the order at the other. The drawing shows the difference plainly: the reference's runs of a bundle go as ordered
rivers, around the memory where the order asks for it, and enter the hollows in the order of their vias; the
planner's go straight through the memory area and cross each other on the way. The routes' order within a layer
is set by the side each run passes each via and each package on (its homotopy), and a congestion negotiation swaps
two runs that cross back and forth: the plateau of D28 again, at 0.4 mm instead of 0.2. The reference's answer is
structural: its runs come around the memory (U11 is entered from the north 58 times, the south 31, the west 28,
the east 18) and the hollow via field is where the order changes (a run leaves the hollow on the row its via's
position allows). (4) The detailed router under the planner's guides (free layers, 265 crossings planned): 55 of
55 nets contested in every one of 60 rounds, and the final pass's repair, working through 46 stranded nets, had
not finished when the run hit its 50-minute limit (`build/replay-butterstick-planner.log`); the band replay of D28
with the reference's own routes ended at 44 of 55 in 14 minutes. Decision: the planner keeps the capacity model as
its check and gets a structural front end, to be built next unless the owner objects: (a) at each package, an
ordered escape of every run from its via to the package boundary on the run's layer, which is the M2 escape
router's problem on the inner layers with the reference's vias as input and the order along the boundary as its
output; (b) between packages, each bundle as an ordered river, its members' order fixed by the escapes' exit order
at both ends, a mismatch resolved by choosing the exits (the via field as a permutation network) rather than by
crossing; (c) layers per bundle from a crossing graph of the bundles' rivers, a small colouring, with the affinity
and the capacity model deciding among the colourings. The detailed router then routes inside the rivers with its
existing plan mode.

**D30. The deep research landed: the vendors' own rules are tighter than D27 on address and command, and both TI
and Lattice permit swapping the data bits inside a byte lane. Question to the owner.** Evidence, 2026-09-19
(`docs/research/deep-research-claims.md`, 22 claims confirmed by a three-vote adversarial check, 0 refuted; the
run's synthesis step never ran, so the claims are recorded verbatim with their sources). What bears on our work:

1. *Lattice's own checklist for the ECP5* (FPGA-TN-02038, the family on ButterStick) gives a byte-group skew budget
   of ±50 mil (±1.27 mm) between every DQ or DM and its own DQS, ±10 mil (±0.254 mm) intra-pair for DQS and CK,
   address and command to CK within ±100 mil (±2.54 mm), LDQS to UDQS within ±100 mil, at most three vias per data
   net with identical via counts across the group, and it expects meanders to be used to hit these.
2. *Our D27 criterion* judges a candidate by the reference's own spreads: lanes within 0.73 and 0.84 mm on total
   length, pairs within 0.2 mm, address and command within the reference's spread at each memory's pins (11.9 mm at
   U11, 7.5 mm at U12). The lane and pair figures are inside Lattice's budget, so D27 is the stricter test there.
   The address and command figure is not: 11.9 mm is 4.7 times Lattice's ±2.54 mm. Either ButterStick's address
   group is outside its own vendor's rule, or the quantity we measure (spread of total length at the pins) is not
   the quantity the vendor constrains (each net against CK, segment by segment along the fly-by chain, which on a
   dual-rank T-branch board is measured per branch). Both readings are consistent with what we measured; we have
   not yet measured the reference per segment against CK. TI's SPRABI1 is tighter again (±10 mil in a byte lane,
   ±20 mil to CK per segment, at most two vias, 5W spacing including meanders) and ISSI's guideline tighter still
   on cross-group skew; the vendors disagree with each other by more than an order of magnitude.
3. *The literature confirms the D29 architecture and adds one stage*: Ozdal and Wong reserve length room during
   routing by Lagrangian relaxation with a graph model that guarantees the reserved area is usable for snaking;
   BSG-Route decides topology first and then assigns area by mathematical programming; the TODAES/DAC area-assignment
   work partitions the board, assigns each wire a region by linear program (refined to a hierarchical flow for dense
   boards), guarantees every assigned subregion can host at least one detour, and is explicitly allowed to change a
   wire's topology to get a better assignment. Our cell planner's "length room as optional capacity" is the same
   idea in weaker form; its missing stage is the one D29 named, the ordering and topology decision before area.
4. *Pin permutation is legal and we are not using it.* TI: "Data bits within a byte-lane can be swapped to simplify
   routing." Lattice: DQ and DM may be swapped within a data group, DQS never. The twist that D28 and D29 measured
   (34 inversions of 55 in ButterStick's lane 0, 184 of 241 planner crossings inside one bundle) is exactly what a
   permutation removes: on a board we design, a byte lane's crossings can be relabelled away rather than routed
   around. It does not help the replay, where the reference fixes the assignment, but it changes the target board's
   problem, and it means the planner should own the assignment inside each byte lane.

Question to the owner, on which no work depends until answered: should M3's length criterion stay as D27 wrote it
(the reference's own spreads, which the reference by definition passes), or become the vendor rule for the part in
question (Lattice's ECP5 numbers for these boards), which the reference may itself fail on address and command? The
first asks the router to match a designer's practice; the second asks it to meet the part's specification, and would
make a failing reference possible. No scope change is made here either way. A third option, if the owner wants the
evidence first: measure both references per segment against CK, as the vendors define the quantity, and decide after.

**D31. Why the reference is not blocked where we are: it never drops a via between the balls, it keeps the top
layer for escapes, and it collects the layer changes in the hollows.** Measurement, 2026-09-19, with the new
`scripts/compare_net.py` (the reference's own route for a net laid over our routed board, point by point, naming
our copper that sits in it) against `build/bench/butterstick-bus.kicad_pcb`, the run that scored 54 of 55 nets
connected, 0 electrical violations, 27 of 55 in their length window, DQ5 failed.

Vias by place, the whole bus (reference 149, ours 172):

| where | reference | ours |
| --- | --- | --- |
| in a pad | 64 | 56 |
| hollow of U11 | 35 | 18 |
| hollow of U12 | 37 | 17 |
| between the balls of U4 | 0 | 13 |
| between the balls of U11 | 0 | 13 |
| between the balls of U12 | 1 | 22 |
| margins of U4, U11, U12 | 11 | 33 |

The reference puts one via between two balls in the entire bus; we put 48. A via between balls closes the only
channel its neighbours have out of the array, on every layer at once. Top layer: the reference gives a data net
2 to 4 mm of F.Cu (an escape) and nothing else, its only long top runs being the seven nets it routes entirely on
top (CKE0 and CKE1 at 33.7 mm, A8, A7, RST, CS1, ODT1); ours has 22 nets over 5 mm on F.Cu, eight of them data
nets (DQ7 22.6 mm, DQ6 19.6, DQ3 17.7, DQ14 16.2), and 84 mm of top copper inside U4's footprint against the
reference's 35 mm, which is copper lying across the escape channels of balls that have not escaped yet.

DQ5, the net that failed: the reference routes it U4.P19 in-pad via, B.Cu 14.9 mm to a via in U12's hollow at
(151.26, 110.70), F.Cu 1.9 mm from there to the ball, In5.Cu 13.5 mm up to a via in U11's hollow at
(151.50, 99.30), F.Cu 2.0 mm to U11.H8. On our board that U12 hollow site is held by DQ4's via, the U11 site is
crossed by five address tracks, and 54 % of the reference's 32.2 mm route is under our copper (RAS, the CK1 pair,
UDQS_N, ODT1, DQ11). Our router's own diagnosis agrees: it could not reach U12.H8 because our A14 and DQ14 tracks
run across that escape on F.Cu. The nets in the way are on different layers in the reference: RAS is In2.Cu 36.2
mm there and F.Cu 1.1 mm, ours is In5.Cu 15.3 and F.Cu 14.2.

Hollow sites: 11 of the reference's 37 sites in U12's hollow carry one of our vias, and 8 of those 11 carry a
different net's (the reference's A1 site holds our A0, its A15 site our WE, its DQ12 site our DQ14). The hollow is
a permutation network with a fixed number of cells and the reference assigns each net the cell that untwists its
lane; our negotiation hands out cells first come, so the late nets find none.

What this settles: the hollow cells of each memory are allocated as a permutation, by the order the lane needs,
before any detailed search, and the capacity model of D29 measures the channels but cannot invent that allocation.

**Corrected by D32.** Two rules stated here as general ("no via between balls, ever" and "the top layer carries
escapes only") were drawn from ButterStick alone and LogicBone refutes both: its reference puts 89 vias between
balls and runs 170 mm of top-layer transit. What both references do obey is narrower and exact, and D32 states it.
Everything above about ButterStick, and the diagnosis of DQ5, stands as measured.

**D32. What both references actually obey: a via in a pad array sits on a ball or on a corner between four, never
in the channel between two; and each package keeps to one escape style.** Measurement, 2026-09-19, with
`bus_design.escape_style` and `bus_design.structure` over both references and our best board for each.

A via inside a pad array is in one of three places, and the three are worth separating because they are not alike:
on the ball (an in-pad via), on a corner between four balls (the widest gap of a square lattice), or in the channel
between two neighbouring balls (the narrowest gap, and the one those balls' neighbours escape through). Counted
that way:

| vias inside the arrays | on the ball | on a corner | in the channel |
| --- | --- | --- | --- |
| ButterStick reference | 64 | 1 | 0 |
| ButterStick, ours | 54 | 46 | 8 |
| LogicBone reference | 0 | 89 | 0 |
| LogicBone, ours | 0 | 87 | 6 |

Neither reference puts a single via in a channel, over 154 array vias between them. Both of ours do, 8 and 6. That
is the rule that holds across boards, and it is the one D31 should have drawn. The rest of D31's via rule is a
per-package style, not a law: ButterStick escapes in-pad at U4 (46 of 46 on the ball) and U11 (10 of 10), and
dog-bones U12; LogicBone dog-bones all three packages onto corners. Our ButterStick run mixes the two styles inside
one array, putting 13 corner vias in U4 and 15 in U11 where every reference via is on the ball.

D31's top-layer rule does not survive either: the references run 122 mm (ButterStick) and 170 mm (LogicBone) of
top-layer copper further than 3 mm from any pad of its own net, against our 149 mm and 116 mm. We are not worse on
LogicBone and only slightly worse on ButterStick, so "the top layer carries escapes only" was wrong. The knob is
implemented (`BusRules.top_escape_mm`) and left off.

Via counts do separate us from both references: ButterStick's reference uses 149 vias with at most 3 per net,
LogicBone's 99 with at most 4; ours 172 with 4 and 123 with 5. Lattice's own checklist caps a DDR data net at 3
(D30), so on ButterStick we exceed both the reference and the vendor.

What went into the pipeline. `BusRules.ball_via_offsets` maps a package to the offsets from a ball its vias may
take, and the bus graph drops every via site that any containing ball sees at a forbidden offset (a point on a
corner lies in four cells at once, so each is checked; rounding to one of them breaks ties arbitrarily, which is a
bug this work found and fixed in `Package.where` as well). `Costs.max_vias_per_net` spends one budget across the
legs of a net's tree, counting the vias its copper already carries. `scripts/bus_bench.py` measures the reference's
escape style and via budget and hands both to the router (`BUS_STYLE=diagonal` gives the cross-board rule instead,
which is what a board with no reference of its own gets; `BUS_STYLE=off` restores the old freedom), and every run
now prints its structure against the reference's, so the distance is measured rather than guessed.

**D33. The bench's 0.8 mm spacing between bus nets is what stalls the negotiation, and every measurement since
18 September was taken inside that stall.** Measurement, 2026-09-19 (`scripts/bus_bench.py` with `BUS_SPACING`,
probe logs `build/probe-spacing0.log`, `build/probe-margin4.log`, `build/probe-a07c503.log`,
`build/probe-10d645b.log`).

Applying D32's rules to the pipeline made ButterStick far worse, and the attribution runs said the cause was
neither rule:

| ButterStick, one run each | nets connected |
| --- | --- |
| the 18 September run recorded in the plan | 54 of 55 |
| the reference's escape style, via budget 3 | 15 of 55 |
| the cross-board style (ball or corner), via budget 3 | 19 of 55 |
| no style, via budget 3 | 20 of 55 |
| the reference's style, no via budget | 18 of 55 |
| the cross-board style, no via budget | 19 of 55 |

Every one of those stalls at 55 of 55 nets contested from round 0 and never improves, where the 18 September run
fell 55, 53, 48, 35 over four rounds. Neither rule explains it, since turning both off changes nothing. What does:
the bench keeps `BUS_SPACING` mm of extra room between bus nets outside the pad arrays, so that the length tuner
has somewhere to meander, and its default is 0.8 mm. At 0.8 mm two bus nets cannot run in neighbouring channels of
an 0.8 mm lattice at all, so every net is in conflict by construction. The same probe with the spacing at zero
falls to 52 contested in round 1 and runs twice as fast per round; a sibling run of 18 September at 0.4 mm
(`build/bus-butterstick-sp04.log`) stalls at 55 exactly as today's do.

Ruled out on the way, each by its own probe: the region margin (4 mm, as the good run used, stalls the same way at
today's code), the board outline becoming an obstacle (the first commit after the good run, stalls), the islands
and repair changes of 10d645b (stalls), and the escape router (unchanged since before the good run, and the
fan-out is identical at 55 of 55).

What this costs us: the plateau of D28 and D29, read as evidence that ordering and crossings are what the
negotiation cannot resolve, was measured inside this stall and cannot carry that weight. The crossing counts of
D29 come from the planner, which has no spacing, and stand. D31's and D32's structural measurements are of the
boards themselves and stand. The **rules** of D32 are unmeasured: they were only ever run inside the stall.

What changed: the bench's default spacing is now 0.2 mm, the most room of the values the negotiation can work in
(0.4 and 0.8 stall it, 0.0 and 0.2 do not). Nothing in the router changed.

With that fixed, the full bench on ButterStick with both D32 rules off reaches **42 of 55 nets at 0.0 mm spacing**
(27 kept from the negotiation, 13 stranded when the repair budget ran out, zero electrical violations) and **39 of
55 at 0.2 mm**. Neither reproduces the 54 of 55 of 18 September, whose negotiation reached 13 contested by round
19 where today's settles at 28. So the spacing was one cause of the collapse and not the whole of it: a further
regression sits somewhere between that run and today, and the recorded M3 numbers in the plan cannot be relied on
until it is found. The repair stage is now the binding constraint, spending its whole budget and leaving 13 to 16
nets stranded.

**D34. What of the research is in the tooling, and what it says about M1 and M2.** Review with measurements,
2026-09-19, prompted by the owner's question.

*In the tooling: one thing.* `Costs.max_vias_per_net` caps a net's layer changes, which both references and
Lattice's checklist support (D30, D32); D33 measured what it costs us and it is off by default. Everything else the
research gave us sits in `docs/research/` and in D30's open question, not in code: judging length as delay in ps
with a per-layer velocity, the vendors' per-segment matching against CK rather than a total-length spread, TI's 5W
centre-to-centre including serpentines, the freedom to swap DQ and DM inside a byte lane, and the Vref and VTT
placement rules (which belong to M4, not here). The literature's architecture claims (topology first, then area
assignment, then meanders inside the assigned area) agree with D29's planner and changed nothing in it.

*M1 is not invalidated.* Its harness measures what it says it measures: nets connected, electrical violations,
length against the board's measured spread, vias inside packages, layers used. The research does not contradict
any of that; it says the length criterion should be a delay and per segment, which is exactly D30's open question
for the owner. One measured caution on TI's 5W rule (0.44 mm centre to centre at our 0.0889 mm track): neither
reference obeys it, both run bus tracks at 0.20 mm centre to centre (D28), so it cannot be imposed without
declaring both references non-compliant.

*M2 passes what it asserts and asserts too little.* Its gate is every bus ball escaped with zero electrical
violations, and the fan-out does that on 9 of 9 cases. But measured the way D32 measures a board, our escape is the
opposite of ButterStick's at the memories:

| ButterStick bus vias | in a ball's pad | in the hollows | between the balls |
| --- | --- | --- | --- |
| reference (149) | 64 | 72 | 1 |
| our fan-out (88) | 60 | 3 | 24 |

The reference dog-bones U12 into the hollow; we dog-bone into the array. On LogicBone our fan-out matches its
reference closely (61 corner vias against 89, 3 in hollows against 5, and both boards use the corners). So the
gap is ButterStick-specific and it is the same one D22 found empirically, which is why M3 keeps only the
controller's escapes and routes the memories from their pads: two thirds of M2's output is discarded by the next
stage. Nothing here says M2's result is wrong; it says the criteria do not distinguish an escape the bus router
can use from one it cannot.

Not a scope change, and not made here: adding a structural criterion to M2 (the escape style of each package, and
whether the hollow is used where the reference uses it) would turn our present ButterStick fan-out into a failing
case. That is the owner's call. Reopening M1 is not recommended on this evidence.

**D35. Is ButterStick the right first class C reference? Measured against the target and the other two.** Review,
2026-09-19, prompted by the owner's doubt.

The target of M6 is an ECP5 caBGA381 with **one** DDR3L x16 in FBGA-96 on eight layers, whose fan-out D16 planned
as dog-bones at PCBWay's standard tier with 0.45/0.15 vias. Against that, the three class C references:

| | memories | escape style | bus layers | track | via, ring | outside PCBWay's standard tier on |
| --- | --- | --- | --- | --- | --- | --- |
| target (M6) | one x16 | dog-bone (planned) | eight board layers | 0.1 mm | 0.45/0.15 | nothing, by intent |
| OrangeCrab | one x16 | dog-bone at both | 3 | 0.089 | 0.28/0.15, ring 0.065 | spacing, tracks, ring |
| LogicBone | two x8, fly-by | dog-bone at all three | 5 | 0.1 | 0.5/0.2, ring 0.15 | spacing only |
| ButterStick | two x16, dual rank | in-pad at two, hollow dog-bone at the third | 4 | 0.0889 | 0.4/0.2, ring 0.1 | spacing, tracks, ring, and via-in-pad is advanced |

On the three things that decide how much a reference teaches us about the target, ButterStick is the outlier of
the three. It has two memories in a dual-rank arrangement the target does not have. Its escape technique, a via in
the ball's pad at the controller and the first memory with the second memory's dog-bones driven into the package's
hollow, needs via-in-pad, which is an advanced-tier process the target is not planned to use. And it is the finest
of the four references on every rule at once. The registry's own note on OrangeCrab already says it is "the closest
reference to the simplified target"; M3's criteria nonetheless name ButterStick first and OrangeCrab not at all.

What this is not: evidence that ButterStick is a bad board or an invalid answer key. It is a manufactured, working,
open board and its techniques are real practice at the tier it was built for. Nor is our difficulty with it
evidence, since D33 showed the runs that produced that impression were measured inside a stall.

Options, for the owner; no scope changed here. (a) Reorder M3 to LogicBone first, then ButterStick: LogicBone is
the closest of the three to the target's planned rules, its escape style is the one the target will use, and our
own fan-out already matches its reference's style, so a pass there says something about the tool rather than about
advanced-tier tricks. Nothing is dropped and it costs nothing. (b) Make OrangeCrab the entry case, then LogicBone,
then ButterStick, so the ladder rises in difficulty: it is structurally nearest the target, at the price of
extending `bus_design.classify` to its net names (its 50 bus nets all fall into "other" today, so the D27 group
criteria do not apply to it yet) and of its 0.065 mm rings, which are the most aggressive of any reference. (c)
Hold ButterStick out of M3 as a later stretch case. (d) Leave the criteria as they are.

**D36. What M2 proved, and the workflow error underneath it.** Review, 2026-09-19, prompted by the owner's
observation that a chip that exists can be escaped, so proving escape and then discarding the escapes says little.

The observation is right, and the proportion is larger than it looked. M3 asks the escape router only for the
controller's balls and routes every memory from its bare pads (D22):

| board | bus balls | asked for by M3 | certified by M2 and never requested |
| --- | --- | --- | --- |
| ButterStick | 155 | 55 | 100 (65 %) |
| LogicBone | 128 | 50 | 78 (61 %) |
| OrangeCrab | 100 | 50 | 50 (50 %) |

What M2 did buy, so the ledger is honest. It is not a feasibility proof, since the references escape these parts
already; it is a test of our machinery against boards whose answer is known, and it failed twice before it passed:
nine balls at OrangeCrab's 0.5 mm pitch and ULX3S's N18 were beyond the old half-pitch lattice, and D19 and D20
rebuilt the escape router on a quarter-pitch grid with per-ball negotiation to reach them. That machinery, its
geometry and its rules are the same ones the bus router uses (D22), so the code earned its keep even where the
artifact did not. M2 also remains a proper standalone stage for a package with no bus behind it, where escaping is
the whole job.

The error is in the stage boundary, not in the milestone. M2's criterion is "every ball escapes, DRC clean", which
says nothing about whether the escape leaves the bus a way through; D34 measured that ours does not, putting 24
vias in the channels between ButterStick's memory balls where the reference puts one, and using 3 hollow sites
where the reference uses 72. The references show why no criterion on the escape alone could have caught it: on
ButterStick the escape **is** the bus plan, because which hollow cell each ball's via lands in fixes the order that
lane leaves the package, and D28 measured that order as nearly reversed between the two memories. The research says
the same (D30): escapes are planned jointly with the bus, not before it. So the escape is an output of the bus
plan, not an input to it, and a pipeline that computes it first can only be lucky.

For the owner, and not decided here: this is a larger change than the structural criterion D34 floated. It says the
escape router should become a subroutine the bus planner calls once it knows the order and the layer each net
needs, with M2's gate retained for packages with no bus, and M3's own criteria covering the escapes of the bus
packages. It does not invalidate M2's result or its code.
