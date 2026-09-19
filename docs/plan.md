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

**M2. Fan-out** (complete, session 3: `python3 scripts/gate.py m2` PASS, 9 of 9 cases, 461 of 461 bus balls, zero electrical violations under every reference's constraints; decisions D13 to D20). The fan-out passes both class C references: every ball escaped, DRC clean, in both
via styles (dog-bone and via-in-pad). Synthetic tests in place.

**M3. Bus router.** Passes ButterStick, then LogicBone: all bus nets, DRC clean, lengths matched as the reference
matches them (each data lane within the reference's own lane spread on total length, differential pairs within
0.2 mm, address and command within the reference's spread at each memory's pins; decisions D27), layer changes
only at the packages. Fails with a diagnosis, never with a list.

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

## State of M3

FAIL, in progress (session 3, decisions D21 to D29). Criteria: all bus nets, DRC clean, lengths matched as the
reference matches them (D27; the table below still shows the earlier "within the measured spread" proxy), layer
changes only at the packages, on ButterStick then LogicBone. The course changed on the step-1 measurements
(D26, `docs/bus-design.md`): the router is being re-planned from the references' own structure, ButterStick first. Best complete runs of
`scripts/bus_bench.py` (the gate runs the same bench), each about an hour:

| board | routed | electrical violations | lengths within spread | vias inside packages | run |
| --- | --- | --- | --- | --- | --- |
| ButterStick | 42 of 55 | 0 | 25 of 55 | 100 % | today's code, no extra bus spacing (D33) |
| ButterStick | 39 of 55 | 0 | 25 of 55 | 100 % | today's code at the 0.2 mm default (D33) |
| ButterStick | 53 to 54 of 55 | 0 | 27 to 36 of 55 | 100 % | 18 September, **not reproducible** (D33) |
| LogicBone | 45 of 50 | 0 | 40 of 50 (12.4 to 43.5 mm) | 100 % | 18 September, not re-measured since (D33) |

The 18 September rows are what the bench reported then. D33 could not reproduce them: with the bus spacing that
makes the negotiation work at all, today's code reaches 42 of 55. The spacing was one cause and is fixed; the rest
of the gap is unattributed, and no number in the two older rows should be relied on until it is.

Failing cases and their blockers. ButterStick: CKE0 (to U4.F18) and DQ5 (to U12.H8) end the negotiation
contested with an adjacent ball's net and are walled in by the other 53 nets in the final pass; each routes alone
on the stripped board in a second, and with the bus copper within 1.5 mm of its pads removed, but no re-packing of
that neighbourhood (greedy, or negotiated locally) has placed all of it again. Nineteen nets are below the
reference's shortest length, the command nets (CK, CKE, CS, ODT) by 9 to 16 mm: the reference makes those lengths
with meanders inside the DRAM footprints and ours has no room left there once routed. LogicBone: five nets
(A1 to RN2.2, A12 to IC3.K7, A15 to IC3.J7, DQ5 to IC2.E8, DQ7 to IC2.E7) walled in the same way at the DRAM
balls; ten nets short. The negotiation plateaus on both boards with a handful of crossing conflicts of three or
four samples each (two single-layer routes between in-pad vias that must cross): more vias per leg and a wider
corridor lower the plateau (24 to 13 contested at twenty rounds) without clearing it; re-routing every net every
round, waypoints from the first round and uniform spacing made it worse.

The replay of the reference's structure (D28) showed the detailed search sound and the negotiation unable to pack
the reference's own runs; the bus planner (D29, `waffle_eda/route/plan.py`) then planned capacity and layers on
0.4 mm cells with the reference's escapes and vias kept: every run placed with no boundary over capacity in
seconds, the bundle structure as the reference's, but 186 to 241 crossings between same-layer runs left where the
reference has none, and crossings are what strands the detailed router. Next, unless the owner objects: the
structural planner of D29 (ordered escapes per package on the inner layers, bundles as ordered rivers, layers per
bundle by colouring), the capacity model kept as its check.

The deep research the owner asked for landed (D30, `docs/research/deep-research-claims.md`): it confirms that
architecture (topology first, then area assignment, then meanders inside the assigned area), and raises a question
about M3's length criterion, since Lattice's own ECP5 numbers are tighter than D27 on address and command while the
lane and pair figures of D27 are the stricter test. The question is D30's; the criterion stands as D27 wrote it
until the owner answers.
