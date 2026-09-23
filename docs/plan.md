# Plan

The plan is the reference ladder (D55): build the whole pipeline for class A boards to completion first, then
work through the pipeline again and extend it for class B, then B+, then C, then C'. A milestone is a class.
Everything else in this file serves that sentence.

## Next session starts here

This is the only part of the plan that says what to *do*. **Whoever finishes a piece of work updates it in the
same commit.** A stale next-step is worse than none.

**Confirm the state first.** On the web the session hook has already installed everything; elsewhere run the
installs `.claude/hooks/session-start.sh` lists (pip, Java 25, KiCad's symbol and footprint libraries, the jar,
the references).

```
python3 scripts/check_env.py            # python, kicad-cli, pcbnew, z3, numpy, shapely, pytest, java 25, the jar, kicad-libs
python3 scripts/gate.py a               # expect FAIL, 1 of 6: the rows below
python3 -m pytest -q -rs                # expect 0 failed (a skip is a guard for a build artifact, never a pass)
python3 scripts/design.py temperature-sensor status   # all six stages PASS, waiting on the owner's review
```

**Milestone A, task 2: the class A gate, one board at a time, smallest first.** Stage 5 exists and is behind
the gate (`route/stage5.py`: the specification's pours, a stitching via at every surface pad of a poured net,
Freerouting 2.4.1 headless under the measured rules, the fill, the DRC, the closure loop; D56). The smoke test
passes in 22 s. The next board is `open-book-c1` and its two failures are named:

1. **Necks the repair cannot widen** (14 on `open-book-c1`, the `track_width` rows of
   `scripts/route_reference.py open-book-c1`): the router's fanout stage escapes a button pad in a straight line
   past a 0.2 mm wide ground strip of the same footprint at three quarters of the width, and a full-width track
   does not fit there. `route.freerouting.repair_necks` widens, nudges sideways or re-lays out of the pad; none
   of the three helps a track boxed in along its whole length. What is missing is a repair that re-routes the
   escape around the strip (the pad's other side, or a via first), or a way to keep the fanout stage off that
   path. Measure before building: the reference's own escape from those pads is the answer key.
2. **A ground pad no stitching via fits** (U1.8 of the Pico module, a 3.5 x 1.7 mm pad in a row): the site
   search walks the pad's axis and then every 15 degrees around it up to 2 mm; that pad needs either a longer
   reach or a via between the row's pads. Look at where the reference puts its via for that pad.

Then `olimex-esp32c3-devkit` (0.127 mm tracks, a QFN), then the three boards the gate has numbers for below.
A board that fails gets its failing case in `tests/test_stage5.py` first, then the smallest change.

**Alongside: the owner's review of `designs/temperature-sensor/`.** Every stage passed; the outputs are in
`out/` and the renders in `reports/`. The milestone needs the owner's review of them, and the four asks
`scripts/design.py temperature-sensor status` prints (the review date in `design.md`, the unknown prices, the
uncaptured PCBWay price model, the assembler's BOM template) are the owner's, not a session's.

**What is not next.** Nothing in `route/bus.py`, `busplanner.py`, `escape.py`, `length.py` or
`board_router.py`; nothing on D30; nothing on the FPGA target; no research; no second router.

## How the ladder is climbed

1. **A milestone is a class.** It is complete when every reference in the class passes the class gate in full
   *and* one synthetic design of that class has gone through all six stages to fab outputs that the owner
   reviewed. A plan, an escape, a spec or a partial route is never a milestone.
2. **Two gates per class.** The re-route gate (strip a reference to placement, re-route, DRC clean under the
   board's own measured rules) proves stage 5. It cannot prove stages 1 to 4 or 6, because it starts from a
   finished placement; the synthetic design proves those.
3. **Lower classes stay green.** Before pushing a change to shared code, run every gate below the current class.
   The class A gate is the regression suite for everything after it.
4. **Cheapest tool that passes.** Each stage uses an existing tool where one passes the class: Freerouting for
   stage 5, `kicad-cli` for DRC and exports, KiCad's libraries for symbols and footprints. Own code is written
   where a measurement shows the baseline fails the class, and only for what fails.
5. **Revision is a failing case first, then the smallest change** that passes it and keeps every lower class
   green. A stage is never re-architected because of one board.
6. **Time box.** A class not passed after four sessions gets a written review with options for the owner in the
   fifth, not another iteration.
7. **Rungs are not equal.** A to B adds checks and rules around an existing router. B to B+ adds BGA escape,
   which passes its gate today. B+ to C is the cliff, and it is reached with a working general pipeline, a
   baseline to measure against, and the bus plan as an input.

## The classes and their references

Registry: `waffle_eda/bench/references.py`; measured facts: [`references.md`](references.md); survey and
rejections: D9. Selection rules: open hardware under a licence that allows the use, a KiCad board pcbnew 9
loads, a board that was manufactured and worked, a class the tool claims.

| Class | Board | The routing problem | References |
|---|---|---|---|
| A | 2 layers, a microcontroller or module, passives, headers | connectivity; fine-pitch pad escapes; ground as a pour; one board with real current | `tinkerforge-temperature`, `open-book-c1`, `olimex-esp32c3-devkit`, `olimex-rp2040-pico-pc`, `crkbd-corne-cherry`, `libresolar-mppt-2420` |
| B | 4 layers, fine-pitch QFN MCU or small FPGA, USB 2.0 pair, switching regulator, ground planes | electrical intent: a differential pair, plane integrity and return paths, a switcher's loop, decoupling placement, width by net class | `pico-ice-rev3`, `upduino-v3.01`, `sensor-watch-c1`, `tinkerforge-master-v3.2`, `buspirate5-rev10`, `olimex-esp32-poe-m1`, `tinytapeout-demo`, `mch2022-badge`, `fomu-pvt` |
| B+ | a BGA on 4 to 6 layers, with a slow bus or none | BGA escape, dog-bone and via-in-pad, 0.4 to 0.8 mm pitch, no length matching | `tinyfpga-bx`, `glasgow-revc3`, `ulx3s`, `cynthion` |
| C | BGA FPGA with a DDR3 bus, 6 to 8 layers, rising order | escapes planned jointly with the bus, per-lane length matching, layer assignment, via budgets, meanders | `orangecrab-r0.2.1`, `logicbone`, `butterstick` |
| C' | BGA FPGA with HyperRAM | the escape problem with a loose bus | `butterstick-r0.2` |

## Milestones

### A. A class A board, end to end

*Adds:* the six stages as a pipeline; the design directory; a baseline stage 5; supply nets as pours; escape
stubs for fine-pitch rows (D51/D52); a diagnosis when a net cannot be routed; the closure loop in its simplest
form (a placement change on a failed route, logged, retried within a budget).

*Gates:* `python3 scripts/gate.py a` on all six references, smallest first (D49); the temperature-sensor design
to fab outputs, re-parsed, reviewed by the owner.

*State (2026-09-23, evening):* gate FAIL, 1 of 6. `tinkerforge-temperature` PASS (6 of 6 nets, 0 violations, 22 s); `open-book-c1` 33 of 35,
14 `track_width` (necks the repair cannot widen) and one ground pad without a stitching site; `olimex-esp32c3-devkit`
31 of 34 with 17 `hole_clearance`, measured before the day's last two fixes; the gate was still on
`olimex-rp2040-pico-pc` when this was committed, and the rows for the three larger boards land in the next commit.
The synthetic design passes all six stage gates to fab outputs (D57); the owner's review is pending.

### B. A class B board, end to end

*Adds:* net classes with width per class from the reference (D50's criterion gains it here); a differential pair
routed as a pair and checked for gap and skew; planes with feeds and stitching, and a plane-integrity check (no
signal crosses a split in the plane that references it); a return via near every layer change; switching
regulator and decoupling placement rules from `lessons/layout-practices.md`; the fab profile's price model for a
four-layer board.

*Gates:* `gate.py b` on the nine references; a class B synthetic design (an MCU with USB and a buck regulator)
to fab outputs. *First task:* extend `tests/test_rebuild.py`'s sanity pair to the class B references, since the
benchmark was only asserted on class A.

### B+. A BGA without a matched bus

*Adds:* the escape router (`route/escape.py`, gate `escape`, D13 to D20) as stage 5's escape for ball grids, in
the role D36 gives it: packages with no length-matched bus behind them; via-in-pad as a fab option; the fab
demands a pitch implies, computed at stage 4 from part selection (D42).

*Gates:* `gate.py bplus` on the four references; a class B+ synthetic design.

### C. A BGA FPGA with DDR3

*Adds:* the bus plan (`route/busplan.py`, `busplanner.py`, gate `busplan`, D39 to D41) as the input to the
detailed stage; the detailed bus router, chosen by measurement between the baseline with the plan's escapes fixed
and the parked `route/bus.py`; length tuning; the length criterion of D30, decided here; the target board of
`lessons/tooling-project-brief.md` section 2 as the synthetic design, with the fab tier and via the owner
specifies (D53).

*Gates:* `gate.py busplan` (passes today, 3 of 3), `gate.py bus` and `gate.py c` on the three references in
rising order; the target board to fab outputs.

## What exists

| Path | State |
|---|---|
| `waffle_eda/kicad/` | board load/save/DRC helpers with the pitfalls documented in `board.py`; zone refill in a child process (D14); PNG/SVG renders (`render.py`) |
| `waffle_eda/bench/references.py`, `references.toml` | 23 boards, fetched by script |
| `waffle_eda/bench/harness.py`, `constraints.py` | bus strip-and-score, per-reference constraints (D10, D17, D18) |
| `waffle_eda/bench/rebuild.py` | whole-board strip-and-score with measured rules; sanity pair asserted on class A (D50) |
| `waffle_eda/bench/synthetic.py`, `survey.py`, `fanout_measure.py`, `bus_design.py`, `delay.py` | synthetic BGA pairs; the survey; measurements of how references escape and route their bus |
| `waffle_eda/fab/` | PCBWay profile as data (D5) |
| `waffle_eda/route/escape.py`, `fanout.py`, `lattice.py`, `obstacles.py` | BGA escape router, gate `escape` PASS 9 of 9 (D20); the exact collision index every router uses |
| `waffle_eda/route/busplan.py`, `busplanner.py` | the bus plan and its check, gate `busplan` PASS 3 of 3 (D41) |
| `waffle_eda/route/bus.py`, `length.py`, `plan.py` | **parked**: the detailed bus router (42 of 55 on ButterStick, D43), length tuner, the earlier cell planner |
| `waffle_eda/route/board_router.py` | **parked**: single-stage grid router, 4 of 6 on the smoke test (D52); its escape-stub finding stands |
| `waffle_eda/route/freerouting.py`, `pours.py`, `stitch.py`, `stage5.py` | stage 5 of class A: Freerouting 2.4.1 headless under the measured rules with the hole rule as via clearance, the neck repair; the specification's pours; stitching vias; the fill-check-stitch loop with its attempt log (D56) |
| `waffle_eda/sch/` | stage 3: a one-sheet schematic from `bom.csv` and `connectivity.toml`, ERC, the netlist compared one to one (from the salvage, D4) |
| `waffle_eda/design/` | the design directory's six stages and status (`pipeline.py`); the board from the netlist with the smallest placer that serves class A (`board.py`) |
| `designs/temperature-sensor/` | the class A synthetic design through all six stages to `out/` (D57) |
| `scripts/gate.py` | the gates: `a`, `escape`, `busplan`, `bus` (old names `m4`, `m2`, `m3a`, `m3b` still work) |
| `scripts/route_reference.py`, `design.py`, `fetch_freerouting.py` | one class A board through stage 5 with the knobs exposed; a design's stages and status; the pinned jar |
| `.claude/hooks/session-start.sh` | every install a web session needs (pip, Java 25, KiCad libraries, the jar, the references) |
| `tests/` | 200 tests: 197 passed, 3 skipped (build-artifact guards), 0 failed on 2026-09-23 in 24 min alongside the gate |
| `salvage/waffle-fpga/` | the old project's tools verbatim: Freerouting wrappers, a schematic generator, plane and power tools |

## Parked (class C, not before)

* **The bus routing inside the plan** (the old M3b). Last reproducible result 42 of 55 nets on ButterStick, no
  plan behind it (D43). The bus code is not touched until B+ passes.
* **D30, the class C length criterion.** Measured to exhaustion (D45, D47, D48, D54); decided when class C
  starts.
* **The target FPGA board** (the old M6), its via and its fab tier (D53).
* **The homegrown general router** and its spec (`archive/router-spec-2026-09-21.md`). Revisited only if the
  baseline is measured to fail a class and the failure is in the router rather than around it.

## Interface

This project's interface is Claude Code, files, renders and reports. A user interface is a separate project
that consumes them (D55). What this project provides:

* **A design is a directory**, `designs/<name>/`: `design.md` (stage 1), `bom.csv` (stage 2), the schematic and
  netlist (stage 3), `spec.toml` (stage 4), the board (stage 5), `reports/` (the gate output, the diagnosis, the
  bus and pair reports, the attempt log of the closure loop) and `out/` (stage 6). Every stage reads the
  previous stage's files and writes its own; nothing is passed in memory that a person cannot open.
* **A render at every gate**: placement and routing as PNG or SVG (`kicad/render.py`), failed nets highlighted,
  the diagnosis beside it.
* **A status command** that prints where a design is in the pipeline, which gate it is at, and what it is
  waiting on from the owner.
* **Owner input is a file edit**, never a drag: a locked constraint in `design.md`, a line vetoed in `bom.csv`.
  The acceptance rule (`definition.md` section 3) means there is nothing to manipulate, only to review.
