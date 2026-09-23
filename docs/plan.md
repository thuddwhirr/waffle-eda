# Plan

The plan is the reference ladder: one class of board at a time, the whole pipeline for that class before the
next class is touched (D55). A milestone is a class. Everything else in this file serves that sentence.

## Next session starts here

This is the only part of the plan that says what to *do*. **Whoever finishes a piece of work updates it in the
same commit.** A stale next-step is worse than none.

**Confirm the state first.** A fresh container has no references and no `build/`; fetching takes a few minutes.

```
python3 scripts/check_env.py            # KiCad 9, pcbnew, z3, Java, Xvfb: all present on 2026-09-23
python3 scripts/fetch_references.py     # clones the 23 reference boards into references/
python3 scripts/gate.py a               # expect FAIL: the parked router reaches 4 of 6 nets on the smoke test
python3 -m pytest -q -rs                # expect 0 failed; a skip is a guard for a build artifact, never a pass
```

**Milestone A, task 1: a baseline stage 5 behind the gate.** `scripts/gate.py a` strips each class A reference to
placement (`bench/rebuild.strip_all`), calls `route.board_router.route_board(board, rules)`, refills zones and
scores the result (`bench/rebuild.score`). Replace what that call does with a wrapper around Freerouting:
export the problem board with `pcbnew.ExportSpecctraDSN`, run the jar headless under `xvfb-run`, import the
session with `pcbnew.ImportSpecctraSES`, then refill and score exactly as now. The salvaged scripts show the
mechanics and the pitfalls (`salvage/waffle-fpga/hw/tools/export_dsn.py`, `import_ses.py`, `staged_route.sh`:
rule areas export as keepouts, plane layers must be typed `power`, a `fix`-typed wire freezes its whole net in
1.9). Supply nets on a two-layer board are pours, not tracks: pour them before routing, or let the router route
them and measure what that costs; either way the gate decides. Score the smoke test first, then walk the ladder.

Obtaining the jar, measured 2026-09-23: `git ls-remote` on `freerouting/freerouting` works from here (latest tag
v2.4.1), a GitHub release asset answered with a redirect, Maven Central answered 429. Try the current release
first; the old project settled on 1.9.0 because 2.1.0 ignored `-mp` and wrote no session file when killed
(`lessons/waffle-fpga-decisions.md` D51). Record the version and flags that worked as a decision. If no route
works, say so and the owner supplies the jar; do not spend the session on it.

**Milestone A, alongside task 1: the design directory and stages 1 to 4 and 6 for one class A design.** See
"Interface" below for the directory. The synthetic design is a temperature-sensor breakout (an I2C sensor, a
four-pin header, decoupling, one LED, two layers), which is what `tinkerforge-temperature` is. Stage 3 has a
starting point in `salvage/waffle-fpga/hw/tools/gen_sch.py` and `symlib.py`; stage 6 is `kicad-cli pcb export`
plus a re-parse of every file written.

**What is not next.** Nothing in `route/bus.py`, `busplanner.py`, `escape.py` or `length.py`; nothing on D30;
nothing on the FPGA target; no research. Those wait for class C (see "Parked").

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

*State (2026-09-23):* gate FAIL. The parked homegrown router: 4 of 6 nets on `tinkerforge-temperature`, 25 of
35 on `open-book-c1`, 29 of 34 on `olimex-esp32c3-devkit`, the other three not attemptable (D51/D52). Stages 1
to 4 and 6: nothing written. The benchmark and its sanity pair pass on all six (D50).

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
| `scripts/gate.py` | the gates: `a`, `escape`, `busplan`, `bus` (old names `m4`, `m2`, `m3a`, `m3b` still work) |
| `tests/` | 183 tests, 0 failed on 2026-09-21 |
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
