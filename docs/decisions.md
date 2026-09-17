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
