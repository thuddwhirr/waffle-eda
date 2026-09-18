# Plan

## The reference ladder

The tool earns its general-purpose claim one board class at a time. Each class needs several open-hardware reference
boards in KiCad format, not one: a tool that passes one board has learned that board. ButterStick and LogicBone are
the two that happened to be measured first; the registry in `waffle_eda/bench/references.py` is meant to grow, and
the survey for the simpler classes is the first M1 task.

| Class | Board | References (registry keys) |
|---|---|---|
| A | 2 layers, a microcontroller or module, passives, headers | `tinkerforge-temperature`, `olimex-esp32c3-devkit`, `olimex-rp2040-pico-pc`, `open-book-c1`, `libresolar-mppt-2420`, `crkbd-corne-cherry` |
| B | 4 layers, fine-pitch QFN microcontroller or small FPGA, USB 2.0 pair, switching regulator, ground planes | `pico-ice-rev3`, `upduino-v3.01`, `sensor-watch-c1`, `tinkerforge-master-v3.2`, `buspirate5-rev10`, `olimex-esp32-poe-m1`, `tinytapeout-demo`, `mch2022-badge`, `fomu-pvt` |
| B+ | a BGA on four to six layers, with a slow bus or none | `tinyfpga-bx` (0.4 mm BGA), `glasgow-revc3` (BGA-121), `ulx3s` (caBGA381 and SDRAM on four layers), `cynthion` (caBGA256, six layers) |
| C | BGA FPGA with a DDR3 bus | `butterstick` (two x16, via-in-pad, 8 layers), `logicbone` (two x8, dog-bone, 8 layers), `orangecrab-r0.2.1` (one x16 on six layers, 0.5 mm-pitch FPGA) |
| C' | BGA FPGA with HyperRAM, no DDR3 | `butterstick-r0.2` |

The measured facts for every board are in [`references.md`](references.md), generated from the registry and the
measurement files. The survey that produced the picks, and the repositories rejected, are in `decisions.md` D9.

Selection rules for a reference: open hardware under a licence that allows the use (CERN OHL, MIT, CC BY), KiCad
board file (any version pcbnew 9 loads), a board that was manufactured and worked, and a class the tool claims.

## Milestones

**M0. Foundation** (done, session 1). Repository, definition, environment verified (KiCad 9, pcbnew bindings, z3),
reference boards fetched by script and loading in pcbnew 9, the `waffle-fpga` tools and documents carried over with
provenance, a first measurement of both references.

**M1. Benchmark harness** (done, session 2). For each class C reference: strip only the DDR3 bus copper, keep everything else as
obstacles, and score a candidate result against the original copper: nets connected, zero electrical violations
touching the bus under the reference's constraints (D17, D18; session 3, before that relative to the original's count),
lengths within the board's measured spread, vias inside the packages, layers used. The "do nothing" tool scores
zero, the original copper scores full marks. A synthetic BGA-pair generator (6 x 6, 9 x 16, 20 x 20 with a bus in one
bank) with known feasibility for unit tests. A measurement report for both references that states every rule with its
evidence. Runs in seconds to a minute. Pick and fetch the class A and B references.

**M2. Fan-out** (not complete; the session 3 gate under decisions D17 and D18: 7 of 9 cases, 452 of 461 bus balls, nine failures on OrangeCrab and ULX3S; decisions D13 to D18). The fan-out passes both class C references: every ball escaped, DRC clean, in both
via styles (dog-bone and via-in-pad). Synthetic tests in place.

**M3. Bus router.** Passes ButterStick, then LogicBone: all bus nets, DRC clean, lengths within the measured spread,
layer changes only at the packages. Fails with a diagnosis, never with a list.

**M4. The rest of the copper.** A router for the miscellaneous nets with the bus and pairs fixed (own, or Freerouting
if it can be made to respect fixed copper), planes and power rails on continuous copper with feeds and plane vias,
checks at every stage. Passes a full re-route of a class A or B reference from placement, DRC clean.

**M5. The front half and the first end-to-end run.** Design document, BOM under a cost ceiling, a readable schematic,
the PCB specification with a price estimate, then stages 5 and 6 on the class A or B target. First board to fab outputs
with no interactive routing.

**M6. The simplified FPGA board.** The `waffle-fpga` target reduced to what exercises the tool: ECP5 caBGA381 with
configuration and rails, one DDR3L, one differential-pair interface, power entry, a PMOD. End to end, no interactive
routing. The open questions from the brief's section 11 are answered here; the defaults are one x16 in FBGA-96, eight
layers, HDMI.

The order is deliberate: M1 to M4 put depth into the routing back half first, because that is the unsolved part; M5
then automates what the last project did by hand well enough.

## State of M1

Done: the survey and a registry of 23 boards across all classes; the strip-and-score harness, passing its two sanity
checks on ButterStick and LogicBone (the stripped board scores zero, the original copper 0.99, in 5 to 16 seconds);
the measurement report; the synthetic BGA-pair generator with four cases (6 x 6 straight and reversed, 9 x 16, 20 x 20
with a bus in one bank), each loading and passing DRC with only its bus open.

## Pending owner decisions

The fab tier for the target board (PCBWay standard with 0.45/0.15 vias is marginal; advanced tier or a thinner board is
comfortable) and the gate's DRC criterion for the benchmark: see decisions D16. Nothing in M3 depends on them; M6 and
the cost model do.

## State of M2

Not complete. Gate M2 under decisions D17 and D18 (session 3): FAIL, 7 of 9 cases pass, 452 of 461 bus balls escaped.
Failing cases first:

- orangecrab-r0.2.1 U3 (0.5 mm pitch): 42 of 50 balls escaped. C17, B7, J16, H16, G16, G15, F15 and D4 are not
  escaped: the top-layer channels they need are taken by the board's own copper (P1.35V, ECP5_VREF, IO_9 to IO_11,
  ADC_MUX1 tracks and vias) and the lattice has no free path left for them at this pitch.
- ulx3s U1: 38 of 39. N18 (ring 3) has no free lattice path on this two-layer board.

Passing: every synthetic case complete and DRC clean; ButterStick 155 of 155 (via-in-pad), LogicBone 128 of 128,
ButterStick r0.2 39 of 39, OrangeCrab U4 50 of 50; every ball we route on every board has zero electrical violations
under the reference's constraints, which the originals meet by construction. Under the working agreement the nine
balls are failures of the tool, not open items, and M2 is not passed until they escape or the owner removes the case
from scope in the decisions log: fix them (an exact packing for the 0.5 mm case, the single ball on ULX3S), or declare
0.5 mm pitch outside the tool's claimed capability so it refuses that class with a stated reason. The escapes on the
passing boards differ from the originals' in via count and layer use, and whether they are as good for a
length-matched bus is only known once M3 routes the bus from them.
