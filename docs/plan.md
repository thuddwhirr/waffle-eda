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
| C | BGA FPGA with a DDR3 bus, in rising order (D35, D38) | `orangecrab-r0.2.1` (one x16 on six layers, dog-bone at both, the target's shape), `logicbone` (two x8, dog-bone, 8 layers, inside the standard fab tier but for spacing), `butterstick` (two x16 dual rank, via-in-pad and hollow escapes, the finest rules of the four) |
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

**M2. Fan-out** (complete, session 3: `python3 scripts/gate.py m2` PASS, 9 of 9 cases, 461 of 461 bus balls, zero electrical violations under every reference's constraints; decisions D13 to D20). The fan-out passes both class C references: every ball escaped, DRC clean, in both
via styles (dog-bone and via-in-pad). Synthetic tests in place.

Its boundary changed in D36 and D38 without changing its result. The escape of a package that carries a bus is an
output of the bus plan, not an input to it: which via site each ball takes fixes the order that bundle leaves the
package, so an escape computed before the bus can only be lucky, and 50 to 65 % of what M2 certifies on the class C
boards is never requested by the bus router. M2's gate therefore stands for packages with no bus behind them, where
escaping is the whole job; for the bus packages the escape router is the subroutine M3a calls once it knows each
net's order and layer, and the escapes are judged by M3a and M3b.

**M3a. The bus plan** (D37, D38). For a reference, produce a plan before any detailed search: per net and leg, the
layer, the via site at each package taken from that package's measured escape style (D32), the order of each bundle
where it crosses each package boundary, and the length room reserved along each run. Gate (`scripts/gate.py m3a`):
every run placed; no two runs of one layer crossing; every via site legal for its package's style and used by one
net only; every net's reserved room at least its length deficit; the bus packages' escapes part of the plan rather
than taken from M2. The reference's own plan is the answer key and the tooling already reads it
(`bus_design.reference_plan`, `entry_order`, `via_sites`). The gate runs in seconds, which is the point: a plan is
a smaller artifact than a route and a mistake in it is caught in the session that makes it.

**M3b. The bus routing.** Route inside the plan of M3a, tune the lengths, check by DRC. Passes the class C
references in the ladder's order, OrangeCrab then LogicBone then ButterStick: all bus nets, DRC clean, lengths
matched as the reference matches them (each data lane within the reference's own lane spread on total length,
differential pairs within 0.2 mm, address and command within the reference's spread at each memory's pins;
decisions D27, subject to D30), layer changes only at the packages. Fails with a diagnosis, never with a list.

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

* **The fab tier for the target board** (PCBWay standard with 0.45/0.15 vias is marginal; advanced tier or a thinner
  board is comfortable) and the gate's DRC criterion for the benchmark: see decisions D16. M6 and the cost model
  depend on them; M3a and M3b do not.
* **The length criterion of M3b** (D30): stay with the reference's own spreads as D27 wrote them, move to the
  vendor's numbers for the part (Lattice's ECP5 checklist is tighter than D27 on address and command while D27 is
  the stricter test on lanes and pairs), or measure both references per segment against the clock first and decide
  after. M3b's gate depends on this; M3a does not.
* **The regression D33 did not close** (D33, D38): the 54 of 55 of 18 September is not reproducible and the spacing
  setting explains only part of the gap. Either bisect the rest, at a few hour-long runs, or accept 42 of 55 as the
  baseline and spend the time on M3a instead.

## State of M2

Complete. Gate M2 under decisions D17 to D20 (session 3): PASS, 9 of 9 cases, 461 of 461 bus balls escaped.

```
=== GATE M2: PASS (9 of 9 cases pass) ===
  pass  pair-6x6-straight      U1 16/16, U2 16/16; DRC electrical 0
  pass  pair-6x6-reversed      U1 16/16, U2 16/16; DRC electrical 0
  pass  pair-9x16-straight     U1 35/35, U2 35/35; DRC electrical 0
  pass  pair-20x20-bank        U1 84/84, U2 84/84; DRC electrical 0
  pass  butterstick            U4 55/55, U11 50/50, U12 50/50; DRC under the reference's constraints: ours 0
  pass  logicbone              IC1 50/50, IC2 39/39, IC3 39/39; DRC under the reference's constraints: ours 0
  pass  butterstick-r0.2       U3 26/26, U5 13/13; DRC under the reference's constraints: ours 0
  pass  ulx3s                  U1 39/39; DRC under the reference's constraints: ours 0
  pass  orangecrab-r0.2.1      U3 50/50, U4 50/50; DRC under the reference's constraints: ours 0
```

Every ball we route on every board has zero electrical violations under the reference's constraints, which the
originals meet by construction; every original passes its own constraints file. Per package the escape takes one to
eleven seconds. The escapes differ from the originals' in via count and layer use, and whether they are as good
for a length-matched bus is only known once M3 routes the bus from them. M3 starts on the owner's word.

## State of M3a and M3b

Both FAIL; M3a is not built. The sessions of 19 and 20 September spent themselves on measurement rather than on
routing, and what they establish is recorded in D28 to D38. In short: the negotiation's plateau is an ordering
problem and not a capacity one (D29, D31, D32); the bench's own spacing setting had made every net contested by
construction, so the routing measurements of six weeks were taken inside a stall (D33); and the escape of a bus
package belongs to the bus plan (D36).

Reproducible ButterStick results, both with the structural rules of D32 switched off and zero DRC errors:

| board | routed | electrical violations | lengths within spread | vias inside packages | run |
| --- | --- | --- | --- | --- | --- |
| ButterStick | 42 of 55 | 0 | 25 of 55 | 100 % | no extra bus spacing (D33) |
| ButterStick | 39 of 55 | 0 | 25 of 55 | 100 % | the 0.2 mm default (D33) |
| ButterStick | 53 to 54 of 55 | 0 | 27 to 36 of 55 | 100 % | 18 September, **not reproducible** (D33) |
| LogicBone | 45 of 50 | 0 | 40 of 50 | 100 % | 18 September, not re-measured since (D33) |

The repair stage is the binding constraint on the reproducible runs: it spends its whole budget and leaves 13 to 16
nets stranded. The 18 September rows are what the bench reported then and no number in them should be relied on.

The structural distance from the reference, which every bench run now prints (D32): 43 vias in the channels between
balls against the reference's 1, 168 vias against 149, up to 6 per net against 3.
