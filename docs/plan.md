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

**M2. Fan-out** (not complete, session 2; see decisions D13 to D15: 313 of 322 bus balls against the answer key, nine failures on OrangeCrab and ULX3S). The fan-out passes both class C references: every ball escaped, DRC clean, in both
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

Not complete. The lattice escape router (`waffle_eda/route/escape.py`) escapes every bus ball on ButterStick (in-pad)
and LogicBone (dog-bone) with DRC below the originals' own violation counts, and every ball of the synthetic cases DRC
clean, in a few seconds per package. It fails nine balls that the original boards escape: eight on OrangeCrab's 0.5 mm-
pitch FPGA and one on ULX3S. Under the working agreement those are failures of the tool, not open items, and M2 is not
passed until the owner decides otherwise: fix them (an exact packing for the 0.5 mm case, the single conflict on
ULX3S), or declare 0.5 mm pitch outside the tool's claimed capability so it refuses that class with a stated reason.
The escapes on the two passing boards also differ from the originals' (LogicBone: 22 vias against 34), and whether
they are as good for a length-matched bus is only known once M3 routes the bus from them.
