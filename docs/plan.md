# Plan

## The reference ladder

The tool earns its general-purpose claim one board class at a time. Each class needs several open-hardware reference
boards in KiCad format, not one: a tool that passes one board has learned that board. ButterStick and LogicBone are
the two that happened to be measured first; the registry in `waffle_eda/bench/references.py` is meant to grow, and
the survey for the simpler classes is the first M1 task.

| Class | Board | References | State |
|---|---|---|---|
| A | 2 layers, one QFP, QFN or through-hole microcontroller, passives, headers | to pick, several | exercises all six stages end to end; routing is easy |
| B | 4 layers, fine-pitch QFN microcontroller or small FPGA, USB 2.0 pair, switching regulator, ground planes | to pick, several; candidates confirmed to exist: `im-tomu/fomu-hardware`, `tinyfpga/TinyFPGA-BX`, `icebreaker-fpga/icebreaker` (format, licence and layer count to verify); the Raspberry Pi Pico design files (KiCad; to verify) | the first real end-to-end target |
| B+ | 4 or 6 layers, BGA FPGA with a single-data-rate bus (SDRAM), no DDR3 | candidate: `emard/ulx3s` (to verify) | BGA fan-out and a slow bus before DDR3 |
| C | 6 or 8 layers, BGA FPGA, DDR3 bus, differential pairs | ButterStick r1.0 (8 layers, two x16 FBGA-96, via-in-pad); LogicBone (8 layers, two x8 TFBGA-78, dog-bone); candidate: `orangecrab-fpga/orangecrab-hardware` (one DDR3L, small outline; to verify) | two fetched, measured and loading (M0) |
| C' | 6 layers, caBGA381 FPGA, HyperRAM, no DDR3 bus | ButterStick r0.2 (in the same repository) | measured (M0) |

Selection rules for a reference: open hardware under a licence that allows the use (CERN OHL, MIT, CC BY), KiCad
board file (any version pcbnew 9 loads), a board that was manufactured and worked, and a class the tool claims.

## Milestones

**M0. Foundation** (this session). Repository, definition, environment verified (KiCad 9, pcbnew bindings, z3),
reference boards fetched by script and loading in pcbnew 9, the `waffle-fpga` tools and documents carried over with
provenance, a first measurement of both references.

**M1. Benchmark harness.** For each class C reference: strip only the DDR3 bus copper, keep everything else as
obstacles, and score a candidate result against the original copper: nets connected, DRC clean under the board's own
rules, lengths within the board's measured spread, vias inside the packages, layers used. The "do nothing" tool scores
zero, the original copper scores full marks. A synthetic BGA-pair generator (6 x 6, 9 x 16, 20 x 20 with a bus in one
bank) with known feasibility for unit tests. A measurement report for both references that states every rule with its
evidence. Runs in seconds to a minute. Pick and fetch the class A and B references.

**M2. Fan-out.** The deterministic BGA fan-out passes both class C references: every ball escaped, DRC clean, in both
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

## Next step after M0

M1: the reference survey for classes A, B and B+ (several boards each, added to the registry with pinned commits),
the strip-and-score harness on ButterStick and LogicBone, the measurement report with rules and evidence, and the
synthetic generator.
