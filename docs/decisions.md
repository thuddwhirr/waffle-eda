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

**D37. A proposed revision of the plan, for the owner.** Proposal, 2026-09-20, written into `docs/plan.md` under
"Proposed revision, awaiting the owner's word" and in force nowhere until the owner accepts it.

It carries five changes. M3 splits into M3a, a bus plan with a gate that runs in seconds and is checked against
the reference's own plan, and M3b, the routing inside that plan with M3's present criteria. The class C ladder is
re-ordered to rise, OrangeCrab then LogicBone then ButterStick, per D35. M2 keeps its gate for packages with no
bus and hands the bus packages' escapes to M3a, per D36. Measurement hygiene becomes a rule with a mechanism: the
bench records the commit, the environment and the resolved costs with every result, and a result without that
provenance is not quotable, per D33. And two debts are named as work rather than left as background: the
unattributed regression D33 did not close, and D30's length-criterion question that M3b's gate depends on.

The reasoning for the split is the one D29 measured and D33 sharpened. Capacity is not what the router cannot
solve; order is. A plan that fixes order, layer and via site is a smaller artifact than a route, it is checkable
against an answer key we can already read, and it costs seconds rather than an hour, so a mistake in it is caught
in the same session it is made. The present arrangement can only be tested by a route, which is why a bench setting
was able to invalidate six weeks of measurement without anyone noticing.

**D38. The owner accepted D37; the plan is revised.** Owner's word, 2026-09-20, on the proposal of D37. M3 becomes
M3a (the bus plan, gated in seconds against the reference's own plan) and M3b (the routing inside that plan, with
M3's present criteria). The class C ladder rises: OrangeCrab, LogicBone, ButterStick. M2 keeps its gate for
packages with no bus and hands the bus packages' escapes to M3a. Measurement provenance becomes a rule in the
working agreement with a mechanism in the bench. The two debts, the regression D33 did not close and D30's
length-criterion question, are named in the plan as pending owner decisions rather than left as background.

What is not decided by this, and still open: which way the regression debt goes (bisect, or accept 42 of 55 as the
baseline), and D30 itself.

**D39. How a bus plan is made crossing-free: a monotone mesh and node-disjoint paths.** Implementation with
measurements, 2026-09-20, in `waffle_eda/route/busplanner.py`, under M3a of D38.

The plan is routed on one grid per copper layer whose lines are not evenly spaced. Every bus package contributes
its own half-pitch lines, so a ball centre, a corner between four balls and a channel between two of them are all
nodes; the rest of the region is filled in at a step of its own. The three references make this necessary rather
than elegant: OrangeCrab's two packages are on 0.5 and 0.8 mm pitches, and LogicBone's and ButterStick's are on
one pitch but origins 9.4 and 18.3 mm apart, neither a multiple of a half pitch. No single even grid holds all of
their ball and corner positions.

Deformed like that the grid is still a grid: x increases with i and y with j. Two orthogonal paths through
disjoint sets of nodes of such a grid cannot cross. So the planner never checks for crossings and repairs them;
it routes every net on node-disjoint paths and crossing-freeness follows on every layer at once, whatever the
geometry. Negotiated congestion (PathFinder) is what drives the nets apart, and the plan is only finished when no
node is claimed twice.

Three things this settles that were being assumed:

* **Via sites.** A layer change happens at a column, held by one net on every layer as a through via is, so "one
  net to a via site" is a property of the construction too. A column inside a package's array is offered only
  where that package's measured style puts its vias (D32), so ButterStick's nets turn down inside their own balls
  and OrangeCrab's dog-bone out to a corner first, neither of them by instruction.
* **Which layers the bus may use.** Measured: a copper layer that carries fewer than 20 distinct non-bus nets is
  a plane and the bus does not cut it. The counts separate cleanly on all three boards (OrangeCrab 95, 55 and 39
  against 10, 1, 1; LogicBone 260, 113, 57 and 42 against 19, 1, 0, 0; ButterStick 232, 127, 57 and 52 against
  13, 8, 0, 0) and pick out exactly the layers each reference's own bus uses. Zone coverage does not separate
  them: LogicBone pours ground on its signal layers as well as its planes, so every layer of it reads as covered.
* **Rip-up.** Re-routing every net each round does not settle. A net moves off a contested node and another moves
  straight on to it and the two trade places; LogicBone and ButterStick sat at one to six contested nodes for a
  dozen rounds. After round one only the nets in a conflict are ripped up and re-routed against the others'
  standing claims. OrangeCrab settles in 5 rounds and 2 s where it had taken 17 rounds and 12 s.

**D40. What a length deficit is, and what room a plan may claim for it.** Implementation with measurements,
2026-09-20, in `waffle_eda/route/busplanner.py`, under M3a of D38.

Two numbers in M3a's fourth criterion ("every net's reserved room at least its length deficit") had no definition
and both were got wrong first.

*The deficit.* Against what, and how closely? The first answer was the longest net of the group exactly, which
asked ButterStick's ODT0 for 45.4 mm of meander where its own reference meanders at most 16.6 mm. The criterion
M3b is judged by is the reference's spread, not zero: plan.md asks for "lengths matched as the reference matches
them" and D27 measured what that is. So a group has to match to within the spread the board itself achieves, and
the plan records it: address/command 6.7 mm on OrangeCrab, 8.0 on ButterStick, 11.4 on LogicBone; the data lanes
0.5 to 0.8 mm on OrangeCrab and ButterStick, 4.2 and 7.1 on LogicBone. A board with no bus routed yet has no
spread to measure and its groups match exactly.

*The room.* A serpentine at the tightest period the mesh allows, one node out and one node back, turns a run of
length l into l*sqrt(1 + 4a^2) where a is its amplitude in mesh steps, so the room affords l*(sqrt(1+4a^2) - 1):
about 1.2 times the run at one node of amplitude, 3.1 at two, 5.1 at three. The first model counted two mesh
steps per node held and was three times too generous, which would have passed the gate on room that was not
there. The amplitude is what the net actually holds beside its run, not what happens to be free beside it: room
two nets could both use is room neither can rely on.

That distinction forces the plan to do area assignment rather than hope. A first pass lays every net down one
track wide and says what each is short of its group; a second routes them again, neediest first, each holding the
tracks beside its run that its deficit asks for; a net still short then takes what is left free beside its runs.
Without it the negotiation packs a bundle shoulder to shoulder, and a net short of its group has nowhere to make
the length up -- on ButterStick 21 nets had no room at all.

One more number had to be capped. Every cost in the planner is millimetres of run, and the congestion term grew
by 1.6 a round without bound, so by round 24 leaving a contested node was worth thirty metres of detour:
ButterStick's DQ10 came out 68.3 mm long against a reference of 30, and its lane 1 spread 48.3 mm against a
reference of 0.8. It is capped at 15 mm, a run may wander at most 1.5 times the distance it has to cover plus
4 mm, and a via costs 8 mm rather than 3.

**D41. Two structural gaps the tuning was standing in for.** Implementation with measurements, 2026-09-20, in
`waffle_eda/route/busplanner.py`, under M3a of D38.

Three times a change that made one class C reference pass made another fail: the congestion cap that fixed
ButterStick's detours put OrangeCrab 12 nets short of room, the room cost that fixed OrangeCrab's room left two
crossings on it, and the next turn of the same wheel put ButterStick back to 8 short and 2 crossing. The working
agreement says to stop at the third and look for the missing constraint. There were two, and neither is a number.

**A repair may not make a new conflict.** When the negotiation's rounds are spent, a node two nets still want is
not a near miss, it is a crossing, so the planner forbids the node to one of them and routes it again. That
re-route was free to take a third net's nodes, so it moved the conflict rather than removing it: ButterStick
cycled between 7 and 17 contested nodes for two hundred repairs and finished with two crossings. A repair now
routes on free nodes only. That makes it monotone -- the conflict it clears cannot reappear elsewhere, and a net
that cannot be moved that way is put back and the other net tried -- and ButterStick settles to zero contested
nodes in six moves.

**A plan must make its lengths, not only reserve room for them.** A bundle routed at its shortest comes out with
the spread of its geometry, not of its criterion. ButterStick's lane 1 spanned 29.2 mm where the board's own
spans 0.8; OrangeCrab's address and command spanned 21.9 mm against 6.7. A net 26 mm short of its group then
wants a corridor five tracks wide to meander in, and a packed bundle has no such corridor anywhere, so no amount
of care over the reservation could have worked. The reference does not reserve 26 mm either: it routes the short
nets long in the first place and meanders the last millimetres.

So a net below its group's target is grown in place before any room is reserved, by writing the serpentine into
the plan itself. Every edge of the mesh is one step, so an edge a--b is replaced by a--p--q--b one step to the
side, which adds two steps of length and takes two nodes that were free. The nodes are claimed as the net's own,
so node-disjointness holds and the plan stays crossing-free; nothing is grown past its group's longest, so
growing one net does not move the target for the rest; and only what cannot be grown is left as room to reserve.
OrangeCrab's lane 1 now spreads 0.8 mm against its board's 0.6 and its lane 0 9.4 against 0.5, at 4 vias a net
against the board's 3.

The general lesson is the one D33 taught in another form. A criterion that two knobs can trade against each
other is a criterion with a missing mechanism, and turning the knobs will find a board that passes and hide the
gap rather than close it.

**D42. What ButterStick asks of a fabricator that LogicBone does not, and which of it is the part's doing.**
Measurement, 2026-09-20, asked by the owner, in `scripts/fab_attribution.py`. It holds each reference's bus
against one yardstick -- PCBWay's standard quick-order tier as D16 read it, 0.1 mm track and space, 0.15 mm
annular ring -- and for every demand that exceeds it, reports where on the board the demand is made: inside a
ball array, where the pitch leaves no choice, or out in open board, where there was room.

The comparison that settles it: **ButterStick and LogicBone carry the same FPGA in the same package on the same
number of layers**, an ECP5 caBGA381, 381 balls at 0.8 mm, 8 layers. They ask for different processes.

| | ButterStick U4 | LogicBone IC1 |
| --- | --- | --- |
| ball pads | 0.4 mm | 0.3 mm |
| escape | via in the ball, 46 of them | dog-bone to a corner, 34 of them |
| vias | 0.4/0.2, ring 0.100 mm (**under**) | 0.5/0.2, ring 0.150 mm (meets it) |
| thinnest bus track | 0.089 mm (**under**) | 0.100 mm (meets it) |
| closest the bus comes to itself | 0.089 mm (**under**) | 0.081 mm (**under**) |

So for the same part, LogicBone meets the standard tier on everything but spacing, and ButterStick misses it on
three counts. The part is not what is asking.

Taking ButterStick's demands one at a time:

* **The via in the ball, and the 0.100 mm ring that follows from it, are a choice.** The diagonal gap between
  four of U4's balls leaves 0.366 mm of copper-free radius, so a via up to 0.53 mm across fits there with 0.1 mm
  to spare -- larger than the 0.5 mm standard-tier via LogicBone puts in the same gap on the same package. Once
  via-in-pad is chosen the via can be no wider than the 0.4 mm pad it sits in, which caps the ring at 0.100 mm
  whatever the drill. The ring is a consequence of the escape style, not of the ball pitch.
* **The 0.089 mm tracks are a board-wide choice, not congestion.** Of the 1437 segments at that width, 1133 are
  in package margins or open board and only 337 are inside a ball array. Congestion inside the arrays is not what
  sets the width; the likeliest reason is a target impedance on that stackup, which is a stackup decision. (This
  is where the measurement stops and inference begins: the boards do not record why.)
* **The 0.089 mm spacing is partly forced.** Of 59 places where the bus runs closer than 0.1 mm, 24 are inside
  ball arrays and hollows and 35 are in margins or open board.

Two findings beyond ButterStick:

* **Every DDR3 reference here runs its bus closer than 0.1 mm somewhere**, ButterStick, LogicBone and OrangeCrab
  alike, and LogicBone's tightest 38 places are in open board. Sub-0.1 mm spacing on a bus like this is the norm
  among these four, not an outlier -- ULX3S is the exception at 0.127 mm, and it is a four-layer board with a
  smaller and slower bus.
* **OrangeCrab is the one genuine case of the part asking, and it is a package choice inside one chip family.**
  All four boards carry a Lattice ECP5. Three use the caBGA381 at 0.8 mm (`ECP5UM5G-85`, `ECP5UM`,
  `LFE5U-85F-6BG381C`); OrangeCrab uses `LFE5U-25F-8MG285C`, the 285-ball csfBGA at 0.5 mm, presumably for the
  Feather form factor. At 0.5 mm pitch with 0.23 mm pads the diagonal point between four balls is 0.354 mm from
  each centre, leaving 0.239 mm of bare board, a circle 0.48 mm across. A standard-tier via is a 0.15 mm drill
  with a 0.15 mm ring all round, so a 0.45 mm pad, 0.65 mm with clearance: it does not fit, and it does not fit
  at any ball pad size, since shrinking the pads to 0.20 mm still yields only 0.51 mm. OrangeCrab uses 0.28/0.15,
  a ring of 0.065 mm, which is the largest that fits. The same sum at 0.8 mm gives 0.73 mm against the 0.65 mm
  needed, which is why LogicBone's standard-tier via fits. The threshold sits between the two package options of
  the same part. Note that OrangeCrab's memory, `MT41K64M16TW` at 0.8 mm, could have taken a standard-tier via
  and does not: its 0.3/0.15 vias are a board-wide via definition, a choice, not a constraint.

**The pitch sets the track width too, by the same arithmetic, and it is computable before anything is routed.**
One track passing through the channel between two neighbouring balls, with equal clearance either side, takes a
third of the gap the pads leave: `w = (pitch - pad) / 3`. Against what each board actually uses:

| package | pitch | pad | gap | (pitch - pad)/3 | measured track / clearance |
| --- | --- | --- | --- | --- | --- |
| OrangeCrab U3 | 0.5 | 0.230 | 0.270 | **0.090** | **0.089 / 0.0891** |
| ULX3S U1 | 0.8 | 0.400 | 0.400 | 0.133 | 0.127 / 0.1266 |
| LogicBone IC2, IC3 | 0.8 | 0.420 | 0.380 | 0.127 | 0.135 / 0.0797 |
| ButterStick U4 | 0.8 | 0.400 | 0.400 | 0.133 | 0.089 / 0.0891 |

Three of the four sit on the prediction. OrangeCrab's 0.089 mm track and 0.089 mm clearance are not a style at
all: they are what 0.5 mm pitch leaves, to the micrometre. ButterStick is the exception, using 0.089 where its
own pitch allows 0.133, which is the finding above reached from the other direction.

So a package's pitch and pad size fix three demands at once -- the track width, the clearance beside it, and the
via that fits between four balls -- and at 0.8 mm all three sit inside the standard tier while at 0.5 mm all
three fall outside it. It is a step rather than a slope, and the common pitches (1.0, 0.8, 0.65, 0.5, 0.4) leave
little middle ground. The consequence for the pipeline is that the fab tier, and therefore part of the cost, is
derivable from part selection before any routing happens; it belongs in the cost model of M5 rather than being
discovered from a finished layout.

What this means for the target board: a 0.8 mm caBGA381 does not require a finer process than the standard tier
for its escape, provided it is dog-boned rather than via-in-pad and the footprint uses the smaller pads. Track
width and spacing are separate questions, the first set by the stackup and impedance target and the second by how
hard the bus is packed, and both are the tool's to decide rather than the part's. The vendor landscape, which
D16 could only speak to for one fab, is being researched separately.

**D43. The unattributed regression is closed by accepting the baseline.** Owner's word, 2026-09-20, on the
question D33 and D38 left open. The 53 to 54 of 55 bus nets reported on 18 September is not reproducible and the
spacing default of D33 explains only part of the gap. The owner's decision is to accept 42 of 55 as the honest
baseline and not to spend further runs bisecting the difference, on the grounds that those runs were completing
boards that had no plan behind them: the router drew one net at a time with nothing deciding order, layer or via
site, which D29 and D38 identified as the actual defect. M3b routes inside an M3a plan, so neither the 42 nor the
54 is a number it can be compared against, and bisecting to recover a figure from a superseded arrangement buys
nothing.

This closes the third of the three questions the plan listed as pending. It does not reopen D33's substance: the
measurement-provenance rule stands, and no figure from before the provenance mechanism is quotable.

**D44. The vendor landscape research failed, and what it did and did not establish.** Research round, 2026-09-20
to 21, asked by the owner (all regions, prototype quantities of 5 to 20, vendors that also assemble fine-pitch
BGAs). Full result in the session's workflow journal; 6 angles, 27 sources fetched, 35 claims extracted, 25
verified, 10 confirmed, 15 refuted, 8 dropped.

**It did not answer the question.** Of roughly twenty vendors named across China, the US and Europe, surviving
evidence covers exactly one: PCBWay, which is the vendor already chosen in `docs/lessons/vendor-notes.md`. Every
verifier gave the same cause -- the session's web-search budget was exhausted at 200 of 200, `jlcpcb.com` is
blocked by this environment's egress proxy, search-engine fetches (duckduckgo, bing) are blocked, and
`web.archive.org` and `curl` are refused at the proxy. So the round was structurally unable to compare vendors:
it could only re-read the one domain that answered, and it deepened the incumbent rather than surveying the
alternatives. Fifteen of its twenty-five verified claims were refuted, so the round was policing itself; it could
not reach the material.

Two sub-questions came back empty for every vendor including PCBWay. **Price and lead time**: every pricing claim
in the round was refuted, and the capability pages publish no price delta for any tier. **Reliability and quality
reputation**: no user-reported experience of any kind was collected. The first of those is probably not
answerable by research at all -- PCBWay defers every price to a sales representative or to post-file-review
quoting -- so the cost half of the fab-tier decision needs the owner to request quotes, not another round.

What it did establish, all of it PCBWay's own published claims read 2026-09-20 and 21, none corroborated by a
third party, an audit or a realised order:

* **The package is not what pushes a board of this class into an advanced tier.** PCBWay's floors are 0.4 mm BGA
  pitch in fabrication and 0.3 mm in assembly, with a minimum BGA land of 8 mil; the caBGA381's 0.8 mm pitch and
  15.75 mil pads clear all three comfortably. Annular ring and trace width decide the tier, which is what D42
  measured from the boards.
* **The headline 2/2 mil is a localised escape figure**, said so in the specification cell itself, and 3.5/3.5
  mil is granted only "from the BGA chip area line to the pad". ButterStick's 0.089 mm used board-wide (D42:
  1133 of 1437 segments in margins or open board) is precisely the use PCBWay declines to grant.
* **Assembly does not exclude this build**: 0.3 mm BGA pitch placement, a stated five-piece minimum, turnkey,
  consigned or combined part sourcing, X-ray named for BGAs with no published price basis.
* **No HDI is needed** -- both shipped references are all through-hole -- but no-HDI does not mean standard tier.
* **PCBWay's pages contradict each other in two places that matter**: outer trace and space (2/2 mil on the
  advanced page against "local 3.5/3.5 mil" on the capabilities page) and board-thickness-to-hole aspect ratio
  (tiered 8 / 10 / above 12 on one page, a flat 20:1 on the other). The target's planned 0.15 mm drill on a
  1.6 mm board sits at 10.67:1, on the wrong side of one of those readings. The advanced page also carries a
  technical roadmap whose columns end in 2018, so it may be years old; that direction of error is conservative
  for capability floors but says nothing about prices.

**It corroborated D42 from a stronger angle than D42 used.** Re-parsing ButterStick's design file independently:
333 of 381 ball pads carry a 0.40/0.20 through via at the pad centre (331 within 10 um, 333 within 50 um -- not
"exact"), and all 1163 vias on the board span F.Cu to B.Cu with no blind, buried or microvia anywhere. The
control is better than D42's: the DDR3 BGA-96 parts **on the same board at the same 0.8 mm pitch** are dog-boned,
median nearest-via distance 0.566 mm, which is exactly the diagonal half pitch 0.8/sqrt(2). Same board, same
designer, same pitch, the opposite choice. D42's conclusion stands and is better supported than when it was
written. (Scope note, not a conflict: D42 counts 46 in-ball escapes because it holds only the bus nets; 333
counts all 381 balls.)

One claim it could not settle, recorded because our own notes assert it: `vendor-notes.md` records via-in-pad as
"advanced (extra cost)", while PCBWay's page lists via-in-pad among ordinary drill and through-plating
capabilities with no surcharge designation. Neither reading is established; it is a quote-time question.

What should happen next is not another identical round. Fetching each vendor's capability page by its known URL
avoids the exhausted search budget entirely, and that is the retry worth making; JLCPCB will still be
unreachable from here. Prices need quotes either way.

**D45. What the silicon vendors actually specify for DDR3 length matching, and the convention problem underneath
D30.** Research round, 2026-09-20 to 21, asked by the owner. 103 agents, 6.7 M tokens; the vendor-published half
is established for three vendors and nothing else.

**What came back, and what did not.** Lattice (ECP5 and ECP5-5G), ISSI and TI KeyStone are established from
primary documents read in full. **No Micron, AMD/Xilinx, Intel/Altera or JEDEC claim survived verification, and
no designer-practice claim survived at all**, so the requirement-against-practice comparison the round was asked
for cannot be made from this evidence. On speed scaling the answer is a negative: not one of the three vendors
attaches a clock rate or speed bin to a length tolerance, and a claim that TI affirmatively states its tolerances
are rate-independent was refuted 3-0. That is an absence in the documents, not a vendor statement.

**Lattice, FPGA-TN-02038-2.1, ECP5 and ECP5-5G Hardware Checklist, September 2025, section 9** (verified by full
text extraction of the live PDF, not by search excerpt; the same text is in revisions 2.0 and 1.4, so it is
revision-stable):

| item | rule |
| --- | --- |
| 9.2 | DQ or DM to its associated DQS within a DQ group: **±50 mil**, "use careful serpentine routing to meet this requirement" |
| 9.7 | DQS to DQS_N: **±10 mil** |
| 9.11 | CK to CK_N: **±10 mil** |
| 9.9 | LDQS/LDQS_N to UDQS/UDQS_N: **±100 mil** |
| 9.10 | address and control to CK/CK_N: **±100 mil** |

Everything Lattice states is a **physical length in mils**. A grep over all 36 pages returns zero occurrences of
ps, picosecond, propagation delay or skew, and zero occurrences of Mbps, MT/s, any DDR3 speed bin, "data rate" or
"speed grade". **There is no strobe-to-clock (DQS to CK) tolerance in the document at all.** Three qualifications
travel with these numbers: the section heading is "LPDDR3 and DDR3", so they are not DDR3-specific; the checklist
self-describes as "a high-level summary checklist" and defers detail to documents that turn out not to cover the
subject; and section 15 item 7 gives a general ±5 mil differential rule of thumb, twice as tight as 9.7 and 9.11.

**ISSI** publishes both a picosecond and a length column (CK to DQS ±5 ps, DQ to DQS ±10 ps or 50 mil) but calls
it a simulation-confirmable baseline subordinate to the controller vendor's rules, and scopes it to
point-to-point. **TI KeyStone** is the tightest and the only vendor stating the measurement convention
unambiguously: address, command and control matched to the clock within ±20 mil **measured controller-to-each-
SDRAM separately**, data ±10 mil within a byte lane, DQS pairs ±1 mil. Those are KeyStone-PHY figures and must
not be transplanted to an ECP5.

**A correction to our own material.** `docs/research/ddr3-bus-routing.md` stated that the Lattice rules "agree
with ISSI's memory-side guidance" and gave a table blending the two without attribution, so ISSI's ±10 ps
data-to-strobe and ±5 ps clock-to-strobe figures read as Lattice's. They are not; Lattice states no picosecond
figure and no clock-to-strobe rule whatever. The table is corrected and re-attributed in place. This did not
affect any gate: the benchmark's criteria come from D27, which uses the references' own measured spreads, not
from that table. It would have affected D30's second option, which is exactly the option that draws on it.

**The finding that bears on D30.** Lattice's ±100 mil address-and-command rule is a 5.08 mm window. On total net
length the three class C references measure 6.7 mm (OrangeCrab), 8.0 mm (ButterStick) and 11.4 mm (LogicBone);
measured at each memory's pins as D27 does, ButterStick is 11.9 and 7.5 mm and LogicBone 6.6 and 6.1 mm. **Every
reference exceeds the rule on either measure.** These are manufactured, working boards, so one of two things is
true: the published guidance is conservative by a factor of two or more, or the tolerance is not measured the way
we are measuring it. Lattice does not say which convention it means, and TI, the only vendor that does say,
measures per segment from the controller to each memory rather than on total net length. A fly-by or dual-rank
net's total length is the sum of segments, so the spread of totals can be far wider than the spread of segments
and the two measures are not comparable.

Adopting Lattice's numbers against our present measurement would therefore fail all three references by
construction -- the same trap that D44's companion decision split out for the fab tier. The recommendation to the
owner is D30's third option: measure both references per segment against the clock first, then decide. The
numbers to decide against now exist; the convention does not yet.

One correction to plan.md carried here: its summary of D30 said "D27 is the stricter test on lanes and pairs".
That holds for ButterStick (0.73 and 0.84 mm against Lattice's 2.54 mm window) and OrangeCrab (0.5 and 0.6), but
not for LogicBone, whose lanes measure 4.15 and 7.1 mm on total length and are **looser** than Lattice's rule.

**D46. Two research rounds were launched without a reachability check, and their failure went unreported for two
hours.** Process failure, 2026-09-20 to 21, raised by the owner. Recorded as a rule, not as an apology.

**What happened.** Both rounds of D44 and D45 were launched at about 22:20 with no check that their sources were
reachable. The environment publishes a proxy status endpoint, named in this session's own environment notes,
whose `recentRelayFailures` list answers the question directly. Run afterwards it showed `403 to CONNECT (policy
denial)` for `jlcpcb.com` and `comparepcb.com` at 22:25, `www.edaboard.com` and `www.micron.com` at 22:37 -- four
of the domains the rounds most needed. The first agent complaint about a block or an exhausted search budget was
written at 22:23, three minutes after launch. The failure was reported to the owner on completion, about two
hours later for the first round and two and a half for the second: 213 agents and 12.8 M tokens, for a vendor
landscape covering one vendor and a practice survey covering none.

**Three errors, in order of cost.**

1. *No pre-flight.* The check costs one command and a few seconds. It was documented in the environment and was
   not run. A deep-research round had already been run earlier in the same session, so search-budget pressure was
   foreseeable as well.
2. *The wrong shape.* Both rounds were built to lean on web search, when the material actually needed -- vendor
   capability pages, Lattice's checklist, ISSI's guidelines -- sits at known stable URLs. Direct fetches worked
   throughout: the Lattice PDF was read in full, and that is where D45's entire usable result came from. The
   retry proposed afterwards, fetch by URL rather than search, was the right design before launch, not after.
3. *Liveness checked instead of health.* Asked mid-run whether the rounds were still going, the answer given was
   that both were running and "doing real primary-source work", from reading the last three lines of the journal.
   That was true and beside the point. The evidence of failure was in the same directory, and a grep for a
   failure signal would have surfaced it at the first check rather than at completion.

**The rule, added to the working agreement.** Before a long background job: check that its sources are reachable
and prefer fetching known documents by URL over searching for them. While it runs: grep its output for failure
signals rather than confirming it is alive. A job that cannot reach its sources is a failure from its third
minute, and saying so then costs nothing.

This is D33's lesson in another costume. There, a bench setting made every measurement meaningless and nobody
looked at the setting; here, an egress policy made a round's sources unreachable and nobody looked at the policy.
Both were one cheap check away, and in both cases the expensive artifact looked healthy while it was running.

**D47. Measured per leg against the signal each rule names: the convention is not what puts the references
outside Lattice's numbers.** Measurement, 2026-09-21, in `scripts/segment_lengths.py`, answering the question D45
left open and refuting the reading D45 recommended.

D45 found every class C reference outside Lattice's address-and-command rule on total net length, and proposed
that the convention was to blame: Lattice does not say whether its tolerance is on the whole net or on one leg,
and TI, the only vendor that does say, measures from the controller to each memory separately. Measuring it that
way, and comparing each group against the signal its own rule names -- a data bit against its byte lane's strobe,
address and command against the clock, both at the same memory -- does not reconcile them.

| board | memories | address/command against CK | data against its DQS |
| --- | --- | --- | --- |
| ButterStick | two, dual rank | 9.82 mm at U11, 6.05 at U12 | 1.88 to 4.05 mm |
| LogicBone | two, fly-by | 4.08 mm at IC2, 3.54 at IC3 | 3.68 to 4.07 mm |
| OrangeCrab | one, point to point | 4.46 mm | **0.98 and 0.54 mm** |
| Lattice's tolerance (D45) | | 2.54 mm | 1.27 mm |

Every board is outside on address and command at every memory. The convention change moves the numbers and does
not change the verdict: on ButterStick it makes address and command worse (11.92 mm spread on legs against 6.76
on totals) and on LogicBone better (6.07 against 11.38), because the total of a fly-by net is the sum of its legs
and the two quantities are simply different, not one a proxy for the other.

**What the measurement did find is a topology split.** OrangeCrab, the only point-to-point board of the three, is
the only one whose data lanes meet Lattice's rule, and it meets it comfortably at 0.98 and 0.54 mm against 1.27.
Both two-memory boards miss it. That is consistent with the scope ISSI states for its own figures, point to
point, and with DDR3 carrying write levelling and read training precisely to absorb the flight-time differences a
multi-memory topology creates (`docs/research/ddr3-bus-routing.md`, JESD79-3). It bears directly on M6, whose
target board is one memory: that is the topology Lattice's numbers appear to be written for, and the reference
where they nearly hold.

**Recommendation for D30**, unchanged in shape from the one D44's companion gave for the fab tier, and for the
same reason: **gate on what the references demonstrate (D27) and report against the published specification
beside it.** A gate set to Lattice's numbers would fail all three answer keys on address and command and two of
three on data, which is a criterion no manufactured working board in our set meets. Printing both columns costs
nothing, shows how near the published rule the tool gets, and leaves the owner able to tighten later. For the
target board of M6, aim at Lattice's numbers directly, since its topology is OrangeCrab's.

**One measurement not yet made that could still move this.** These are copper lengths. The references mix
microstrip and stripline, whose propagation differs by roughly 5.6 against 6.7 ps/mm, so equal length is not
equal delay and the gap on address and command could be partly an artifact of measuring the wrong quantity.
`NetDesign.paths` records the layer sequence of each path but not the length on each layer, so this needs a small
extension before it can be measured. It is the one remaining thing that could change the answer to D30, and it
does not need research either.

**D48. Measured as delay, not copper: the address-and-command verdict does not move, and the data-lane verdict
reverses.** Measurement, 2026-09-21, in `waffle_eda/bench/delay.py` and `scripts/segment_lengths.py`, answering
the one question D47 left open and closing it.

D47 ended by naming a measurement that could still change the answer to D30: every figure to that point was
copper length, the references mix microstrip and stripline, and equal copper is not equal delay. `NetDesign.paths`
recorded each path's layer sequence but not its length on each layer, so the quantity could not be computed. It
can now: each path carries `per_layer_mm`, and `delay.Stackup` turns that into picoseconds.

**The model.** IPC-2141's effective permittivity, one formula for both layer kinds rather than two rules of thumb:
`t_pd = sqrt(er_eff)/c`, with `er_eff = er` for an inner layer and `0.475 er + 0.67` for an outer one. At er 4.5
that is 5.59 ps/mm outer and 7.08 ps/mm inner; the 5.59 is the 5.6 ps/mm the research note converts with, and the
7.08 replaces its 6.7, which came from a rule of thumb assuming er 4.0. ButterStick's file records its own
stackup (FR-4, er 4.5, seven dielectrics); OrangeCrab's and LogicBone's record none, so those two use the FR-4
default and every report prints which. Outer is decided by position in the copper stack, not by layer name,
because LogicBone renames its inner layers. The standing assumption, stated so it can be rejected: every inner
layer is treated as stripline. On LogicBone that is checkable and true -- its bus runs on `Sig2.Cu`, between
`Gnd2.Cu` and `Gnd3.Cu`.

**Address and command against CK, worst deviation at each memory.** D47's verdict stands, in every unit.

| board | memory | copper | as delay | equivalent | Lattice 2.54 mm | ISSI 10 ps |
| --- | --- | --- | --- | --- | --- | --- |
| OrangeCrab | U4 | 4.46 mm | 30.7 ps | 4.34 mm | OUTSIDE | OUTSIDE |
| LogicBone | IC2 | 4.08 mm | 23.8 ps | 3.37 mm | OUTSIDE | OUTSIDE |
| LogicBone | IC3 | 3.54 mm | 21.9 ps | 3.09 mm | OUTSIDE | OUTSIDE |
| ButterStick | U11 | 9.82 mm | 49.5 ps | 6.99 mm | OUTSIDE | OUTSIDE |
| ButterStick | U12 | 6.05 mm | 82.4 ps | 11.64 mm | OUTSIDE | OUTSIDE |

Delay narrows the gap at four of the five memories and widens it at the fifth, and no memory of any board comes
inside. **The delay measurement was the last thing that could have changed the answer to D30 and it does not.**

**Data against its own strobe, worst deviation.** Here the two units disagree, in both directions.

| board | memory | lane | copper (tol 1.27 mm) | delay (tol 10 ps) | verdict |
| --- | --- | --- | --- | --- | --- |
| OrangeCrab | U4 | 0 | 0.98 mm within | 27.2 ps OUTSIDE | **within becomes OUTSIDE** |
| OrangeCrab | U4 | 1 | 0.54 mm within | 25.2 ps OUTSIDE | **within becomes OUTSIDE** |
| LogicBone | IC2 | 0 | 4.07 mm OUTSIDE | 4.3 ps within | **OUTSIDE becomes within** |
| LogicBone | IC3 | 1 | 3.68 mm OUTSIDE | 27.2 ps OUTSIDE | unchanged |
| ButterStick | U11 | 0 | 2.23 mm OUTSIDE | 40.5 ps OUTSIDE | unchanged |
| ButterStick | U11 | 1 | 4.05 mm OUTSIDE | 32.9 ps OUTSIDE | unchanged |
| ButterStick | U12 | 0 | 1.88 mm OUTSIDE | 20.4 ps OUTSIDE | unchanged |
| ButterStick | U12 | 1 | 3.69 mm OUTSIDE | 24.1 ps OUTSIDE | unchanged |

**This overturns the topology reading of D47.** D47 found OrangeCrab, the only point-to-point board, the only one
whose data lanes meet Lattice's rule, and read that as the rule being written for a one-memory topology. Measured
as delay, OrangeCrab's lanes are the furthest outside of the three, and LogicBone's lane 0 is the only lane of
any board that meets the rule. The topology split was an artifact of the unit.

**The cause is visible in the copper, and the two boards did opposite things.** In OrangeCrab's lane 0 the eight
data bits run on `B.Cu` and the strobe pair and mask on `In2.Cu`, every leg cut to about 15 mm: matched in
copper, and 79.6 to 88.6 ps against the strobes' 103.1 to 110.7 ps, a 27.2 ps skew between a byte lane and the
strobe that clocks it. In LogicBone's lane 0 at IC2 the eight data bits run 17.2 mm on `F.Cu` and the strobes
12.7 to 13.8 mm on `Sig2.Cu` -- 3.5 to 4.6 mm apart in copper and 89.0 to 96.8 ps, within 8 ps. LogicBone made
the inner-layer strobe shorter because inner copper is slower. **LogicBone matched delay; OrangeCrab matched
length.** Two of the three answer keys were built to different conventions, which is why no single unit grades
all three the same way. The research note predicted the LogicBone half of this from the totals
(`docs/research/ddr3-bus-routing.md`, "the strongest argument for judging delay, not length"); it is now measured
per leg from the board, and the OrangeCrab half is new.

**Recommendation for D30, revised from D47's.** D47 recommended gating on D27 and reporting Lattice beside it.
That still holds for address and command, where every reference is outside in every unit. For the byte lanes it
is no longer enough, because a length criterion and a delay criterion disagree about two of our three answer
keys, and D27's criterion is a length one:

1. **Keep D27's spreads as the gate's tolerance** -- the recommendation is unchanged, and M3a's PASS stands
   untouched, since nothing here changes what a deficit is measured against.
2. **Measure the byte lanes in delay rather than copper, at D27's numbers converted per board.** A router graded
   on copper length can reproduce OrangeCrab's own mistake: match a group across two kinds of layer, pass the
   gate, and leave 27 ps of skew between a lane and its strobe. That is a criterion a tool can satisfy while
   producing a worse board, which is the defect D41 named in another form.
3. **Report Lattice's millimetres and ISSI's picoseconds beside the gate, as now.** ISSI's figures need no
   conversion, so they are the honest column: against them, one lane of one reference passes.

Both parts are the owner's to settle, and the pending-decisions list in the plan carries them.

**What was tried and dropped.** Converting Lattice's mils to picoseconds at a single velocity, to give one number
per rule. It cannot be done honestly: the conversion depends on the layer, which is what the rule fails to say,
and 2.54 mm is 14.2 ps of outer copper or 18.0 ps of inner. The report prints the stripline-equivalent length
instead, which is TI's stated convention, and ISSI's picoseconds alongside, which assume nothing at all.
