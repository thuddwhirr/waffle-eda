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

**M3a. The bus plan** (complete: `python3 scripts/gate.py m3a` PASS, 3 of 3 class C references; decisions D39 to
D41). For a reference, produce a plan before any detailed search: per net and leg, the
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

* **The target board's via, which is recorded two ways and decides the answer to the tier question.** D16 and
  the table above plan 0.45/0.15, a ring of 0.150 mm, which meets PCBWay's published standard 6 mil; the carried
  project's own rules (`docs/lessons/stackup.md`, `tooling-project-brief.md`, and D45 of
  `docs/lessons/waffle-fpga-decisions.md`) use 0.45/0.20, a ring of 0.125 mm, which does not. D44 found the
  discrepancy. So "outside the standard tier on: nothing, by intent" is true of the first number and false of the
  second, and which one the target uses has not been decided. The 0.15 mm drill carries a surcharge and sits at
  10.67:1 on a 1.6 mm board, which D44 found PCBWay's own pages disagree about.
* **The fab tier for the target board**: see D16. M6 and the cost model depend on it; M3a and M3b do not. D42
  measured what a board of this shape actually needs: a 0.8 mm caBGA381 does not require a finer process than
  the standard tier for its escape if it is dog-boned rather than via-in-pad, which is what LogicBone does with
  the same part; OrangeCrab's 0.5 mm pitch is the one case where the part itself rules the standard tier out.
  The vendor landscape asked for on 2026-09-20 **did not come back** (D44): the search budget and this
  environment's egress blocks left evidence for one vendor, the incumbent, and none at all for price, lead time
  or reputation at any vendor. Fetching each vendor's capability page by its known URL is the retry worth making;
  prices need quotes from the owner either way, since PCBWay defers every price to a representative.
* **The benchmark's DRC criterion**, which D16 raised alongside the fab tier and which must be decided apart
  from it. The benchmark holds each reference to the rules measured off that board
  (`waffle_eda/bench/constraints.py`, which refuses to proceed if the original would fail its own measured
  rules), never to a fab's tier. Answering this one with a fab tier instead would fail every class C reference by
  construction: D42 measured that OrangeCrab's 0.089 mm tracks and 0.065 mm rings are what its 0.5 mm pitch
  leaves, so no tier that rules them out can be met on that board by anyone, and the tool would spend the
  milestone chasing something the board's own designer did not achieve either. The recommendation is to keep the
  per-board demonstrated rules as the benchmark's criterion and to hold the fab tier where it belongs, on the
  target board of M6.
* **The length criterion of M3b** (D30), now with the vendor's numbers verified (D45): stay with the references'
  own spreads as D27 wrote them, move to Lattice's published rules for the part, or measure both references per
  segment against the clock first and decide after. **The recommendation is the third.** Lattice's checklist is
  length-only in mils, with no picosecond figure and no clock-to-strobe rule anywhere in it: ±50 mil DQ to its
  DQS, ±10 mil on each pair, ±100 mil lane-to-lane and address-and-command to CK. Its address-and-command rule is
  a 5.08 mm window, and **all three class C references exceed it** -- 6.7 mm, 8.0 mm and 11.4 mm on total net
  length, 6.1 to 11.9 mm measured at each memory's pins. Since those boards were manufactured and work, either
  the guidance is conservative or the tolerance is not measured the way we measure it, and Lattice does not say
  which convention it means; TI, the only vendor that does say, measures per segment from the controller to each
  memory. Adopting the numbers against our present measurement would fail every reference by construction.
  M3b's gate depends on this, and so does M3a: D40 took D27's answer for what a deficit is measured against, so
  a change tightens every window, grows every deficit and forces M3a to be re-run.
* ~~The regression D33 did not close~~ **Decided (D43)**: 42 of 55 stands as the baseline and the difference is
  not bisected. Those runs were completing boards with no plan behind them, so neither figure is one M3b can be
  compared against.

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

## State of M3a

**PASS.** `python3 scripts/gate.py m3a` exits 0: all three class C references, every net planned in one piece, no
two runs of one layer crossing, every via site legal for its package's measured style and used by one net only,
room for every net's length deficit, and every bus ball escaped by the plan rather than by M2.

```
=== GATE M3A: PASS (3 of 3 cases pass) ===
  pass  butterstick            the plan passes
  pass  logicbone              the plan passes
  pass  orangecrab-r0.2.1      the plan passes
```

How the plans compare with the boards' own, ours first in each pair (D39, D40, D41):

| board | nets | legs | address/command spread | lane 0 | lane 1 | vias, most per net | vias in all | to build |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OrangeCrab | 50 | 145 | 17.1 / 6.7 mm | 9.4 / 0.5 | 0.8 / 0.6 | 4 / 2 | 93 / 87 | 9 s |
| LogicBone | 50 | 272 | 11.7 / 11.4 mm | 4.4 / 4.2 | 7.2 / 7.1 | 7 / 4 | 154 / 99 | 94 s |
| ButterStick | 55 | 255 | 28.4 / 8.0 mm | 1.3 / 0.7 | 10.8 / 0.8 | 13 / 3 | 193 / 149 | 114 s |

The gate is met on all three and the plan is not equally good on all three. LogicBone's spreads land on its
board's own to a tenth of a millimetre; ButterStick's address and command still spread 28.4 mm against its
board's 8.0, and one of its nets takes 13 vias against a reference of 3. Those are differences M3b has to live
with, and they are the first place to look when it fails.

Checking a plan takes under a second on every board, which is the point of the split (D37): a mistake in a plan
is caught in the session that makes it rather than after an hour of routing.

## State of M3b

FAIL; the routing inside the plan is not built. What the measurement sessions of 19 and 20 September established
is recorded in D28 to D41: the negotiation's plateau is an ordering problem and not a capacity one (D29, D31,
D32); the bench's own spacing setting had made every net contested by construction, so the routing measurements
of six weeks were taken inside a stall (D33); a bus package's escape belongs to the bus plan (D36); and a
criterion two knobs can trade against each other is a criterion with a missing mechanism (D41).

The last reproducible bus routing, from before M3a existed, both with the structural rules of D32 switched off
and zero DRC errors:

| board | routed | electrical violations | lengths within spread | vias inside packages | run |
| --- | --- | --- | --- | --- | --- |
| ButterStick | 42 of 55 | 0 | 25 of 55 | 100 % | no extra bus spacing (D33) |
| ButterStick | 39 of 55 | 0 | 25 of 55 | 100 % | the 0.2 mm default (D33) |
| ButterStick | 53 to 54 of 55 | 0 | 27 to 36 of 55 | 100 % | 18 September, **not reproducible** (D33) |
| LogicBone | 45 of 50 | 0 | 40 of 50 | 100 % | 18 September, not re-measured since (D33) |

The repair stage was the binding constraint on the reproducible runs: it spent its whole budget and left 13 to 16
nets stranded. The 18 September rows are what the bench reported then and no number in them should be relied on.
None of these runs had a plan to route inside, which is what M3b changes.
