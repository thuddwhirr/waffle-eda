# Plan

The plan is the reference ladder (D55): build the whole pipeline for class A boards to completion first, then
work through the pipeline again and extend it for class B, then B+, then C, then C'. A milestone is a class.
Everything else in this file serves that sentence.

## Next session starts here

This is the only part of the plan that says what to *do*. **Whoever finishes a piece of work updates it in the
same commit.** A stale next-step is worse than none.

**Confirm the state first.** A fresh container has no references, no tools and no `build/`; fetching takes a few
minutes. The Python dependencies are in `pyproject.toml` (`pip install z3-solver numpy shapely pytest`).

```
python3 scripts/fetch_tools.py          # Freerouting 2.4.1, a Java 25 and KiCad's symbol and footprint libraries at
                                        # tag 9.0.9 into build/tools/ (D56, D74); a few minutes
python3 scripts/check_env.py            # KiCad 9, pcbnew, z3, Java 25, the jar, Xvfb, the libraries: all present on 2026-09-24
python3 scripts/fetch_references.py     # clones the 23 reference boards into references/
python3 scripts/gate.py a               # expect PASS 5 of 5 (D73), about 12 minutes; the first three boards alone
                                        # (`gate.py a tinkerforge-temperature open-book-c1 olimex-esp32c3-devkit`) in two
python3 scripts/gate.py b pico-ice-rev3               # class B's first rung (D75): being measured, see below
python3 scripts/design.py status temperature-sensor   # the synthetic design: six gates PASS, what waits on the owner
python3 scripts/design.py run temperature-sensor      # re-runs all six stages, about 30 s; the committed files change
                                                      # only in their timestamps and in what the router lays
python3 -m pytest -q -rs                # class A only (the parked classes' tests carry a marker pyproject deselects;
                                        # `-m parked` runs them); expect 0 failed
```

**Milestone A, task 1 (continued): stage 5's baseline passes the gate.** `scripts/gate.py a` strips each class A
reference to placement, routes it with `route.freerouting.route_board` (Freerouting 2.4.1 headless: export DSN,
run the jar under `xvfb-run`, import the session; D56, D57), refills zones and scores it. Every board's DSN,
session and logs are under `build/fr/<key>/`. The failing cases, first (each row from the latest run of that board on the committed wrapper, 2026-09-24 20:15 UTC):

| Board | Nets | Electrical violations | Blocker |
|---|---|---|---|
| `tinkerforge-temperature` | **6 of 6, PASS** | 0 | none: green since D60 (items 1 to 3 below) |
| `open-book-c1` | **35 of 35, PASS** | 0 | none: green since D62 |
| `olimex-esp32c3-devkit` | **34 of 34, PASS** | 0 | none: green since D66 |
| `olimex-rp2040-pico-pc` | **60 of 60, PASS** | 0 | none: green since D69 (D67 to D69 are what it took) |
| `libresolar-mppt-2420` | **102 of 102, PASS** | 0 | none: green since D73 (the USB shield's pad pieces) |

**Where it stands (2026-09-24, 21:00 UTC):** milestone A is provisionally complete (D75): the gate PASS 5 of
5 (D73; 13 s to 7 min a board, 12 minutes in all), the synthetic design `designs/temperature-sensor/` through
all six stages (D74) with its fab outputs under `out/`, and the owner's review of those outputs recorded as
provisional until checked with the manufacturer. Prices and lead times stay unknown and escalated
(`python3 scripts/design.py status temperature-sensor` lists them). **Class B has started (D75)** with its first
task: the benchmark's sanity pair on the nine class B references (`tests/test_rebuild.py`, `LADDER_B`). Three
boards needed the benchmark to read a reference as it is (D76: the answer board); the pair on all nine and the
first rung of `gate.py b` (`pico-ice-rev3`) are the measurements this commit leaves running, and the next
session starts by reading them: `pytest tests/test_rebuild.py -k "pico-ice or upduino or sensor-watch or
tinkerforge-master or buspirate5 or olimex-esp32-poe or tinytapeout or mch2022 or fomu"` and `gate.py b
pico-ice-rev3`. A board the benchmark cannot bracket is a failing test to fix in the benchmark first; a rung
the router fails is the class's first real case, measured as class A's were (D57, D59), with the class B
additions of "B. A class B board" below made only as each is measured to matter. The loop that got a class A
rung green stays the tool: run the gate row once (the wrapper saves the router's output as
`build/fr/<key>/imported.kicad_pcb`), then `python3 scripts/repair_only.py <key> --twice` to measure a repair
change in a minute without the router, and the gate row again to confirm. Freerouting's optimiser is off
(D65); run one Freerouting at a time (two at once have left an empty session file, `route/freerouting.py`,
pitfalls). `crkbd-corne-cherry` left the ladder (D72).

**How a design runs (D74).** `scripts/design.py run <name>` takes `designs/<name>/design.md` and `bom.csv`
through stages 1 to 6, each reading the previous stage's files and writing its own plus
`reports/stage<N>-<name>.md` (PASS or FAIL first, the failing criteria, what waits on the owner, the numbers).
A criterion the tool cannot check (a price with no quote, the owner's review) is escalated, not failed. Stage
5 is the class A gate's router inside a closure loop: a seeded placement (`design/placer.py`: interfaces on
their locked edges, parts with no net in the corners, the rest annealed on wire length with courtyards 1.5 mm
apart, then the outline pulled in to the parts), `route.freerouting.route_board`, the ground pours, KiCad's
DRC under the specification's rules; a failed attempt is logged to `reports/attempts.log` and the next one
re-places with the next seed on an outline grown within the locked maximum. Stage 6 is `kicad-cli pcb export`
with every file re-parsed against the board and the vendor's checklist in the fab profile.

**Why it failed, measured (D57, D59), and the repair order the owner agreed on 2026-09-23.** The router connects
nearly everything and leaves violations of four kinds, each with a known cause: (1) clearances short by less
than 0.011 mm, the error of the router's octagonal model of round copper against KiCad's exact DRC; (2) traces
necked below the rule where they enter a pad, the router's own behaviour, which its setting does not switch
off; (3) per-pad clearance overrides (mounting holes at 1.85 mm, fiducials at 1.016 mm) that KiCad's Specctra
export does not carry, so the router never saw them; (4) ground routed as tracks where every class A reference
pours it. Our copper fails the designers' own project rules the same way (open-book 48, esp32c3 31), so the
criterion is not the problem and is not loosened. **One more session, as repair, not tuning**, in this order,
each item behind a failing gate or test case that names the board and the violation kind, every lower item
kept green:

1. *done:* every pad with a clearance override exported as a keepout grown by the override less the clearance
   (`freerouting.pad_keepouts`; the esp32c3's 16 hole violations to 0);
2. *done:* necked traces restored to the rule width after the import (`widen_tracks`; open-book's 40 to 0);
3. *done:* each remaining clearance shortfall nudged away under KiCad's own DRC (`repair_clearances`; the
   smoke board's 9 to 0, and green);
4. *done:* the reference's pours laid after the import, with the hole rule in their clearance and no-pour
   rule areas around holes without a ring (`add_pours`, `hole_rule_areas`; D62);
5. then, and only then, the fine-pitch exits again (`freerouting.escape_stubs`), whose only measurement so far
   was confounded by 1 to 4.

**The stop:** if `tinkerforge-temperature` and `open-book-c1` are not green after that session, Freerouting is
not the baseline; the session after writes the review the ladder rules call for, with two options: our own
router for exits and pours with Freerouting between them, or our own router outright. No fifth tuning session.

**Milestone A, the other half, done (D74): the design directory and stages 1 to 6 on one class A design.**
See "Interface" below for the directory. The synthetic design is a temperature-sensor breakout (an I2C sensor,
a four-pin header, decoupling, one LED, two layers), which is what `tinkerforge-temperature` is. Stage 3 is the
salvaged schematic generator ported with tests (`design/schematic.py`); stage 6 is `kicad-cli pcb export` plus
a re-parse of every file written.

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
| A | 2 layers, a microcontroller or module, passives, headers | connectivity; fine-pitch pad escapes; ground as a pour; one board with real current | `tinkerforge-temperature`, `open-book-c1`, `olimex-esp32c3-devkit`, `olimex-rp2040-pico-pc`, `libresolar-mppt-2420` (`crkbd-corne-cherry` left the ladder, D72) |
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

*State (2026-09-24, 20:30 UTC):* gate PASS, 5 of 5, and the synthetic design through all six stages (D74);
what remains is the owner's review. Stage 5's baseline (Freerouting 2.4.1, optimiser off, inside the repairs
of `route/freerouting.py`, D56 to D73) passes all five: `tinkerforge-temperature` (6 of 6), `open-book-c1`
(35 of 35), `olimex-esp32c3-devkit` (34 of 34), `olimex-rp2040-pico-pc` (60 of 60) and `libresolar-mppt-2420`
(102 of 102), 0 violations each, in 13 s to 7 min a board; `crkbd-corne-cherry` left the ladder (D72). The
synthetic design `designs/temperature-sensor/`: six gates PASS (numbers in D74), 22.5 x 12.7 mm, fab outputs
under `out/`. Tests: the class A suite, 116 passed in 31 s (the parked classes' 128 deselected).
The benchmark and its sanity pair pass on all six (D50).

### B. A class B board, end to end

*Adds:* net classes with width per class from the reference (D50's criterion gains it here); a differential pair
routed as a pair and checked for gap and skew; planes with feeds and stitching, and a plane-integrity check (no
signal crosses a split in the plane that references it); a return via near every layer change; switching
regulator and decoupling placement rules from `lessons/layout-practices.md`; the fab profile's price model for a
four-layer board.

*Gates:* `gate.py b` on the nine references, in the order the plan's table lists them (D75); a class B synthetic
design (an MCU with USB and a buck regulator) to fab outputs. *First task, in progress:* the sanity pair of
`tests/test_rebuild.py` on the class B references (D76 is what it found first).

*State (2026-09-24, 21:00 UTC):* started. `gate.py b` exists (the class A gate's mechanics over the class B
ladder); the sanity pair on the nine and the first rung are being measured (see the next-step section).

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
| `waffle_eda/route/freerouting.py` | stage 5's baseline for class A: Freerouting 2.4.1 headless through KiCad's Specctra export and import, the measured rules written into the DSN, the pitfalls in its docstring (D56, D57); `scripts/fetch_tools.py` fetches the jar and its Java |
| `waffle_eda/route/board_router.py` | **parked**: single-stage grid router, 4 of 6 on the smoke test (D52); its escape-stub finding stands and is now `freerouting.escape_stubs` (off: measured worse, D57) |
| `waffle_eda/design/` | the six stages on a design directory (D74): `stage1_design` to `stage6_outputs`, `gate` (a stage's criteria, escalations and report), `schematic` (the generator, from the salvage), `board_build`, `placer` (edges, corners, annealing, compaction, silkscreen references) |
| `waffle_eda/kicad/libs.py`, `sexp.py`, `symbols.py` | KiCad's libraries found on disk (fetched at the release's tag), an S-expression reader and writer, symbols with their pins |
| `designs/temperature-sensor/` | the class A synthetic design: `design.md`, `bom.csv`, `kicad/` (schematic and board in one project), `netlist.net`, `spec.toml`, `reports/`, `out/` |
| `scripts/gate.py` | the gates: `a`, `escape`, `busplan`, `bus` (old names `m4`, `m2`, `m3a`, `m3b` still work) |
| `scripts/design.py` | `run <name>` (stages in order, stopping at a failing gate), `status <name>` (each gate, what waits on the owner) |
| `tests/` | 244 tests; the class A suite is 116 of them, 31 s (`pytest`); the parked classes' tests carry the `parked` marker and run with `pytest -m parked` |
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
* **A status command**, `scripts/design.py status <name>`, that prints where a design is in the pipeline,
  which gate it is at, and what it is waiting on from the owner; `scripts/design.py run <name>` runs the stages.
* **Owner input is a file edit**, never a drag: a locked constraint in `design.md`, a line vetoed in `bom.csv`.
  The acceptance rule (`definition.md` section 3) means there is nothing to manipulate, only to review.
