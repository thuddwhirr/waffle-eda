# Plan

The plan is the reference ladder (D55): build the whole pipeline for class A boards to completion first, then
work through the pipeline again and extend it for class B, then B+, then C, then C'. A milestone is a class.
Everything else in this file serves that sentence.

## Next session starts here

This is the only part of the plan that says what to *do*. **Whoever finishes a piece of work updates it in the
same commit.** A stale next-step is worse than none. The history of how the state below was reached is the
decision log, D87 to D152, and `docs/review-class-b.md`; do not re-derive it.

**State (2026-09-29, `claude/clever-knuth-c41w4c`).** Class B: FAIL, 5 of 8. Every row below is a replay
of its frozen session on this code (`scripts/replay.py`) or a cloud worker's row (D151, D152); class A's gate PASS 5 of 5 on
this code.

| Gate | Result | What it means |
|---|---|---|
| `python3 scripts/gate.py a` | PASS 5 of 5 | DSNs unchanged; finals changed on 4 boards by D149's repair; run it clean (no `WAFFLE_*`) and alone before any push to shared code |
| `python3 scripts/gate.py b upduino-v3.01` | PASS, 83 of 86 | repeatable (D151) |
| `python3 scripts/gate.py b pico-ice-rev3` | PASS, 85 of 95 | at the bound, repeatable; 90 with the router held to the edge rule (D152) |
| `python3 scripts/gate.py b sensor-watch-c1` | PASS, 57 of 61 | residue U$2's four pads across the outline (D135); 52, FAIL, at the edge rule (D152) |
| `python3 scripts/gate.py b tinkerforge-master-v3.2` | PASS, 144 of 151 | repeatable |
| `python3 scripts/gate.py b buspirate5-rev10` | PASS, 174 of 183 | 174 to 175 run to run (D151); 176 at the edge rule |
| `python3 scripts/gate.py b tinytapeout-demo` | FAIL, 131 of 137 | 131 to 135 run to run; J5-R41 unrouted and 3 edge clearances of the router's +3V3 track every run (D149, D151); PASS 134 at the edge rule (D152) |
| `python3 scripts/gate.py b olimex-esp32-poe-m1` | FAIL, 81 of 101 | repeatable; with D150's carve GND is whole and the router ends at 22 unrouted (36 before, 68 of 101); 20 open, 1 clearance, Spare2 open |
| `mch2022-badge` | cannot run | its outline is lost on any pcbnew save; the DSN has no boundary (D133) |

fomu-pvt left class B (owner, D137: its reference is HDI). A routed row takes 4 to 70 minutes and the whole class B
gate 4 h 10 min on one container; a replayed row takes 3 s to 2 minutes, all twelve under two (D148).

**How to work (D147, D148): the harness first, the router last.** A fix names the tier-0 or tier-1 check it must
pass before code is written; if tier 1 shows no gain in three attempts, stop and find the missing constraint.
- *Tier 0, seconds: a micro-board.* Built from the failure's own geometry in a test (`_com1_board`, `_finger_board`,
  the edge test in tests/test_freerouting.py), or cut from the real board: `python3 scripts/crop.py cut <board>
  <x> <y> <half> <out> [--edge]` (a failure of the finishing: cut the replay's `build/fr/<key>/imported.kicad_pcb`
  and run `repair_clearances` on it; tinytapeout's edge run reproduces in under a second), `python3 scripts/crop.py
  route <key> <x> <y> <half>` (the stripped board's window routed: 19 to 42 s; a crop the router cannot finish
  locates a blocker, one it finishes proves less).
- *Tier 1, minutes, no router.* `python3 scripts/replay.py [-j 4]` replays every row from its frozen session
  (tests/fixtures/sessions) and says per row whether the board came out as frozen; `pytest -m replay` asserts the
  invariants (the finishing never parts pads the router joined, every plated pad left to a plane is reached by its
  fill, the row passes). A deliberate finishing change is adopted with `scripts/freeze_sessions.py --rebase`.
- *Tier 2, hours, the router.* Only when the DSN or the router's settings change (the replay then says
  `StaleSession`) or to confirm; never as the loop. Rows fan out to cloud sessions, one row a worker (below); a
  row routed again is frozen with `scripts/freeze_sessions.py <key>`, or a worker's taken with
  `scripts/collect_workers.py <tag> --adopt`. The router is not repeatable on the large boards (buspirate5,
  libresolar gave another session on one DSN and settings, D148, D149), so a routed row is one sample.

**Fanning gate rows out to cloud sessions (D147).** Per row, from the orchestrating session: `create_session` with
`source_url` the repository, `source_revision` the pushed branch under test, `outcome_branch`
`claude/gate-<tag>-<key>`, an appended system prompt telling the worker to run only its command (not CLAUDE.md's
session start), and the prompt "run `[WAFFLE_...=...] bash scripts/cloud_worker.sh <a|b> <key> <tag>
claude/gate-<tag>-<key>` with run_in_background, wait for it, reply with its last lines". A worker sets its container
up (`scripts/setup_container.sh`, about four minutes), routes the row and pushes `results/<tag>/<key>/` (the gate
line, row.json, the residue page, the frozen session); sensor-watch took 9 minutes end to end.
`python3 scripts/collect_workers.py <tag>` reads the branches back.

**First thing next session: the router's edge margin (D152).** Held to the measured edge rule the router passes
tinytapeout and gains on pico-ice and buspirate5, and loses sensor-watch (57 to 52: /~{RESET}, GND, Net-(D2A-CR),
VBUS and VCC open besides U$2's four). The edge rule of pico-ice, sensor-watch and buspirate5 is the rule search's
upper bound (0.5948), not a measurement. Steps: (1) tier 0: `WAFFLE_ROUTER_EDGE=rule python3 scripts/crop.py route
sensor-watch-c1 ...` round the nets it loses, to see what the 0.5948 margin closes; (2) the edge rule measured past
the bound where the reference allows it, or the router's margin taken as the smaller of the rule and what the
reference's own copper keeps (`rebuild.SEARCHES`); (3) the class B rows fanned out once under the candidate
(`WAFFLE_ROUTER_EDGE=...`), against D151's band; the default changes only if no row falls.

**Then, in this order.**
1. poe-m1: Spare2 open and the router's own 22 unrouted (22 of 31 open nets ended at U6 in D138; translation line
   292): crop round U6 wider than 6 mm, where the router fails; the 1 clearance (D136's pads D3 and D1).
2. mch2022's outline lost on a pcbnew save (D133): tier 0, load, save, compare the outline.
3. D61's netless pad pieces walling their own net (fomu's U9, poe-m1's exposed pad U4-33; D73 settled it on class
   A); fanout, the optimizer and the outer pours (D57, D65, D62) re-measured only with a stated hypothesis.
4. More frozen sessions a board (the workers' `results/<tag>/<key>/` hold them) so the replay tests cover several
   router outputs of the noisy boards.

**What "done" means for class B now (the owner's decision, D120; the rule as corrected, D124).** A reference
passes when the router's board has every plane net whole, no short, and a documented residue of at most ten
open nets and ten clearances the repair left; the page beside the routed board lists each with its pieces,
pad positions and shortfall. The bound of ten is an assumption from the measured residue, not the owner's
number. The class B default (`scripts/gate.py`, `CLASS_B`): only the GND plane (In1) handed to the router, on a `signal`
layer it connects itself, the other inner pours laid after the import (D131), `build/tools/freerouting-2.4.1-d107.jar` (the one-class patch that
keeps the DSN's layer costs, D107; built by `python3 scripts/patch_freerouting.py <fork checkout> d107` from a
checkout with the upstream `v2.4.1` tag), In1 and In2 priced at 30 through the DSN block, a via at 20 and a plane
via at 2 (D103), the ripup start at 400 (D111), no via keepout band (D123), no feed, the stitching after, 6000 s,
no clearance slack (D127): the router is handed the measured rule, not the rule less D57's 0.0072 mm, a
slotted pad's ring measured along its axes (D130; class A keeps the old measure, under which its gate passes), and
vias allowed on same-net SMD pads (D132). Every class B row also prints the reference's own copper checked against
the DSN it was routed from (D133): a row whose line shows violations nobody has explained is not believed.

**What the last sessions found (D126 to D152).** Every gain came from making the DSN say what the board says, found
by `scripts/translation_check.py` (the reference's own copper under our DSN) and the router's own view of the DSN
(`tools/DsnDrc.java`, and a probe of its via rules): a slotted pad's ring (D130), the inner layers the references
route on (D131), vias on SMD pads (D132), rule areas that forbid nothing (D133), keepouts round pads their own net
must reach (D136), a via name with a decimal point that left the router no via (buspirate5 94 to 168, D140), board
files typing inner layers `power` (poe-m1's router 77 to 28 unrouted, D141), copper graphics (D143), a plane under a
no-pour area (D150); and from our finishing, which opened nets the router had joined (D144), fenced plated pads off
their own plane (D145) and could not move copper in from the edge (D149). Router parameter changes gained nothing
(D103 to D125), except the edge margin now (D152). The router is repeatable on one input for most boards and not for
buspirate5, tinytapeout and at times libresolar (D151), and every board swings on a small change of its input
(poe-m1 68 to 84 on a 0.02 mm edge margin, D152): one routed row is one sample.

**Decisions the owner owes.**
1. The residue bound, ten or another number (pico-ice sits at ten).
2. The synthetic class B design of the milestone: it needs the owner's board.

One router at a time on one container: two Freerouting runs at once wrote libresolar an empty session on 2026-09-28
(the pitfall in `freerouting.py`); in parallel, each row in its own cloud worker (above).

**Tools for a measurement**, all measured, none the default: `scripts/rung.py` (one row with every knob:
`stitch`, `band=`, `costs=`, `first=`, `answer=`, the feed forms), the environment overrides `WAFFLE_VIA_COSTS`,
`WAFFLE_PLANE_VIA_COSTS`, `WAFFLE_RIPUP_COSTS`, `WAFFLE_VIA_BANDS`, `WAFFLE_RESIDUE_MAX`, `WAFFLE_CLEARANCE_SLACK_MM`,
`WAFFLE_FREEROUTING_JAR` (an absolute path: the jar runs in the board's work directory), the patches
`tools/freerouting-2.4.1-d109.patch` (the shove's depths, no effect), `-d116.patch` (the inserter's ripup, fewer
failed insertions and no gain at 30 passes), `-d126.patch` (no insertion margin, D126) and `-diag.patch` (every
failed insertion's blockers in `freerouting.log`, which the jar appends across runs: delete it first),
`scripts/insertion_stops.py`, `scripts/insertion_blockers.py`, `scripts/translation_check.py` (the router's version of a
reference against its own copper, D130). The fork at <https://github.com/thuddwhirr/freerouting>
builds through the proxy with Gradle since 2026-09-27: `JAVA_HOME=<waffle-eda>/build/tools/jdk ./gradlew test` in
the checkout runs its 499 tests in a few minutes, `--tests '*ClearanceMarginRoutingTest'` in seconds; its
`AGENTS.md` asks for `spotlessCheck` and the Checkstyle tasks before a push, and `spotlessApply` on the changed
files only (`-PspotlessIdeHook=<file>`). `scripts/patch_freerouting.py` still builds one class at a time against
the release jar, which keeps the jar the gate runs identical to 2.4.1 but for the patched classes.

**Confirm the state first.** A fresh container has no references, no tools and no `build/`; one command sets it
up in about four minutes.

```
bash scripts/setup_container.sh         # the Python packages, Freerouting 2.4.1 with its Java and KiCad's libraries
                                        # (fetch_tools.py), the 23 references, the class B jar (D107) built from the
                                        # upstream v2.4.1 source, check_env.py; each step skipped when already done
python3 scripts/replay.py -j 4          # every frozen row replayed, under two minutes: each "same board" (D148)
python3 scripts/preflight.py            # the class B exports up to the router: the plane-reach check, "same DSN"
python3 -m pytest -q -m "not parked and not bench and not replay"   # the quick run, 160 tests in a minute
python3 -m pytest -q -m replay          # the replay's invariants and each row's verdict, about four minutes; expect
                                        # tinytapeout and poe-m1 to fail (their rows fail) until they pass
python3 scripts/gate.py a               # expect PASS 5 of 5, about 12 minutes; before any push to shared code
python3 scripts/gate.py b <key>         # one class B row through the router, 4 to 70 minutes; all eight in parallel
                                        # through cloud workers (above)
python3 scripts/design.py status temperature-sensor   # the synthetic design: six gates PASS, what waits on the owner
python3 scripts/design.py run temperature-sensor      # re-runs all six stages, about 30 s; the committed files change
                                                      # only in their timestamps and in what the router lays
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

**Where it stands (2026-09-25):** milestone A is provisionally complete (D75): the gate PASS 5 of
5 (D73; 13 s to 7 min a board, 12 minutes in all), the synthetic design `designs/temperature-sensor/` through
all six stages (D74) with its fab outputs under `out/`, and the owner's review of those outputs recorded as
provisional until checked with the manufacturer. Prices and lead times stay unknown and escalated
(`python3 scripts/design.py status temperature-sensor` lists them). **Class B has started (D75)** with its first
task: the benchmark's sanity pair on the nine class B references (`tests/test_rebuild.py`, `LADDER_B`). What
the pair found: three boards needed the benchmark to read a reference as it is (D76: the answer board); a
refill of that board turned the class A gate red and came out again (D78); the long calls are bounded (D77);
and the DRC report's unconnected list is capped at about 500 items, which credited the three largest boards
stripped bare with a third of their nets, so connectivity now comes from KiCad's own graph (D79). **The pair
passes on all nine** (both halves; it costs 39 minutes, 31 of them `mch2022-badge`'s rule measurement, so it
carries the `bench` marker). **Class B's first rung is `upduino-v3.01` (D84); the class's configuration reaches 81 of 86 (D85 to D87).** The
ladder's listed first rung, `pico-ice-rev3`, fails at the class A configuration (D80 to D83: 72 of 95 nets
after four passes and after thirty, the two QFNs' fine-pitch exits and the planes the router's tracks cut).
Upduino is pico-ice without the RP2040, and the measurements on it (D85) settle the plane case: the router
cannot connect a plane net itself (with no plane in the DSN it routes the net as tracks and walls pins in; a
plane handed over it vias no SMD pad to), so `route/planes.py` lays a feed beside every plane-net SMD pad with
room (88 of 105 on upduino: a fixed via the clearance from the pad and a stub to it, in a thermal pad after
the import), and with the GND plane handed over on In1 typed `power` and In2 left to the router, 30 passes
reach 81 of 86, DRC clean, GND and +3V3 whole, no track on In1; that is the class B gate's configuration
(D86, `scripts/gate.py`, `CLASS_B`) and its row on upduino (`python3 scripts/gate.py b upduino-v3.01`,
2026-09-25 08:39 UTC, this container, 88 feeds: **FAIL, 81 of 86**, 0 electrical, 1334 s, digests imported
0304390121 and final 32de2e0f91, the same as `scripts/rung.py`'s round 1 three hours earlier, so D65's
determinism holds across the two tools). That row is the committed configuration's (a feed kept to its own pad,
56 feeds, was measured worse in between and dropped, D88).
Both inner layers kept for planes do not converge (60 of 86); the jar's window is what wrote the empty
sessions (class B runs without one). What stays open is five signal nets, and the session of 2026-09-25 found
what holds them (D87, D88): not the exits alone (the closure loop's stubs open them and the nets stay open,
80 to 82 of 86 over three rounds) but the router's insertion, which fails on the same nets every run where
its shove meets the fixed feeds. The feeds in a form the shove can work with are the next step, above. The
rung's tools: `python3 scripts/gate.py b upduino-v3.01` for the verdict (30 passes, about 22 minutes);
`WAFFLE_ROUTER_GUI=0 python3 scripts/rung.py upduino-v3.01 gnd 4 900 feeds` under a short budget (six
minutes; the options `stubs`, `fanout`, `rounds=N`, `open=<board>`, `exits=...` and `WAFFLE_VIA_COSTS` are
the measured alternatives, all worse, D85, D87); the stitching (`planes.stitch`) runs after the fill and found
nothing to add on upduino. A board the benchmark cannot bracket is a failing test to fix in the benchmark
first; a rung the router fails is the class's first real case, measured as class A's were (D57, D59), with
the class B additions of "B. A class B board" below made only as each is measured to matter. Iterate on the
one board that fails (`pytest -k <board>`, one gate row), under a short router budget where the router is the
slow part (`WAFFLE_ROUTER_PASSES=8 WAFFLE_ROUTER_TIMEOUT_S=300`, D77), and let the full budget confirm. The
loop that got a class A rung green stays the tool: run the gate row once (the wrapper saves the router's
output as `build/fr/<key>/imported.kicad_pcb`), then `python3 scripts/repair_only.py <key> --twice` to
measure a repair change in a minute without the router, and the gate row again to confirm. Freerouting's
optimiser is off (D65); run one Freerouting at a time (two at once have left an empty session file,
`route/freerouting.py`, pitfalls), and nothing heavy beside it (a test run alongside doubled a pass's time).
`crkbd-corne-cherry` left the ladder (D72).

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
| B | 4 layers, fine-pitch QFN MCU or small FPGA, USB 2.0 pair, switching regulator, ground planes | electrical intent: a differential pair, plane integrity and return paths, a switcher's loop, decoupling placement, width by net class | `upduino-v3.01`, `pico-ice-rev3` (in this order, D84), `sensor-watch-c1`, `tinkerforge-master-v3.2`, `buspirate5-rev10`, `olimex-esp32-poe-m1`, `tinytapeout-demo`, `mch2022-badge`, `fomu-pvt` |
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

*Gates:* `gate.py b` on the nine references, in the order the plan's table lists them (D75, D84); a class B synthetic
design (an MCU with USB and a buck regulator) to fab outputs. *First task, in progress:* the sanity pair of
`tests/test_rebuild.py` on the class B references (D76 is what it found first).

*State (2026-09-25):* the first task is done: the sanity pair passes on all nine references (D76 to D79 are
what it took). `gate.py b` exists (the class A gate's mechanics over the class B ladder). `pico-ice-rev3`, the
listed first rung, fails at the class A configuration (D80): 72 of 95 nets after four passes and after thirty
(D82), the rest the QFNs' fine-pitch exits and the planes the router's tracks cut; the planes stay out of the
router's DSN (D81) and the stubs stay off (D83). The owner made `upduino-v3.01`, the class's simplest routing
problem measured, the first rung (D84): 76 of 86 nets at the class A configuration, 81 of 86 with the planes
fed and the GND plane kept (D85: `route/planes.py`, the class B plane machinery, measured in); what is left is
the five QFN exits the router walls in, in the next-step section.

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
| `waffle_eda/bench/rebuild.py` | whole-board strip-and-score with measured rules; sanity pair asserted on class A (D50); the residue of a routed board and class B's verdict on it (D120, D124) |
| `waffle_eda/bench/synthetic.py`, `survey.py`, `fanout_measure.py`, `bus_design.py`, `delay.py` | synthetic BGA pairs; the survey; measurements of how references escape and route their bus |
| `waffle_eda/fab/` | PCBWay profile as data (D5) |
| `waffle_eda/route/escape.py`, `fanout.py`, `lattice.py`, `obstacles.py` | BGA escape router, gate `escape` PASS 9 of 9 (D20); the exact collision index every router uses |
| `waffle_eda/route/busplan.py`, `busplanner.py` | the bus plan and its check, gate `busplan` PASS 3 of 3 (D41) |
| `waffle_eda/route/bus.py`, `length.py`, `plan.py` | **parked**: the detailed bus router (42 of 55 on ButterStick, D43), length tuner, the earlier cell planner |
| `waffle_eda/route/freerouting.py` | stage 5's baseline for class A: Freerouting 2.4.1 headless through KiCad's Specctra export and import, the measured rules written into the DSN, the pitfalls in its docstring (D56, D57); `scripts/fetch_tools.py` fetches the jar and its Java; the closure loop `route_rounds` (a round's untouched fine-pitch pads get a fixed exit stub in the next; D87: a tool, not a default) |
| Freerouting's source | the owner's fork, <https://github.com/thuddwhirr/freerouting>, cloned when needed (the next-step section says how); ahead of the 2.4.1 jar, a guide to what the jar counts and refuses (D85) |
| `waffle_eda/route/planes.py` | class B's plane feeds and stitching (D85): a via and stub beside every plane-net SMD pad with room, straight or L-shaped (D91), one more for every piece left after the fill; the pads no feed reaches and the feeds the router gets as targets for them (`targets_for_unfed`) |
| `waffle_eda/route/board_router.py` | **parked**: single-stage grid router, 4 of 6 on the smoke test (D52); its escape-stub finding stands and is now `freerouting.escape_stubs` (off: measured worse, D57) |
| `waffle_eda/design/` | the six stages on a design directory (D74): `stage1_design` to `stage6_outputs`, `gate` (a stage's criteria, escalations and report), `schematic` (the generator, from the salvage), `board_build`, `placer` (edges, corners, annealing, compaction, silkscreen references) |
| `waffle_eda/kicad/libs.py`, `sexp.py`, `symbols.py` | KiCad's libraries found on disk (fetched at the release's tag), an S-expression reader and writer, symbols with their pins |
| `designs/temperature-sensor/` | the class A synthetic design: `design.md`, `bom.csv`, `kicad/` (schematic and board in one project), `netlist.net`, `spec.toml`, `reports/`, `out/` |
| `scripts/gate.py` | the gates: `a`, `b`, `escape`, `busplan`, `bus` (old names `m4`, `m2`, `m3a`, `m3b` still work); each re-route class runs under its own configuration (`CLASS_A`, `CLASS_B`: planes, feeds, stubs, rounds, window; D86), overridable by `WAFFLE_*` for a measurement, and the row names what it ran under |
| `scripts/design.py` | `run <name>` (stages in order, stopping at a failing gate), `status <name>` (each gate, what waits on the owner) |
| `scripts/patch_freerouting.py` | builds a patched Freerouting jar, one class at a time recompiled from the upstream `v2.4.1` tag plus the patches in `tools/` (D107: the DSN's layer costs kept; D109, D116 measured and not used) |
| `tools/freerouting-2.4.1-*.patch` | the patches, unified diffs against the 2.4.1 source |
| `scripts/insertion_stops.py` | where a run's failed insertions stopped (D90): the jar's "insert trace failed" lines read back onto the routed board, the nearest copper by kind and the corridor at each stop |
| `scripts/rung.py` | one class B gate row with the plane handling, the feeds and their form (`stitch` for none, D96; `loose`, `after`, `reserved`, `vias`; `costs=L:C,...` for D97's block), the stubs, the router's fanout stage and the closure loop's rounds selectable (`rounds=N`, `open=<board>`, `exits=...`), for iterating on a rung under a short budget (D77, D81 to D91) |
| `tests/` | 341 tests: 160 in the quick run (`pytest -m "not parked and not bench and not replay"`, about a minute), 37 replay (`-m replay`, the frozen rows, D147), 16 bench (the class B sanity pair, minutes a board), 128 parked (`pytest -m parked`) |
| `tests/fixtures/sessions/` | the frozen router session of every class A and B row with its DSN's md5, router settings and row (`bench/replay.py`, D147, D148) |
| `scripts/replay.py`, `preflight.py`, `crop.py`, `freeze_sessions.py` | the harness (D147 to D150): rows replayed from frozen sessions, a row up to the router, micro-boards cut or routed, sessions frozen and rebased |
| `scripts/setup_container.sh`, `cloud_worker.sh`, `collect_workers.py` | a container set up in one command; one gate row in a cloud worker session, and the rows read back (D147) |
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
