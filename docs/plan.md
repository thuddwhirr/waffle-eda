# Plan

The plan is the reference ladder (D55): build the whole pipeline for class A boards to completion first, then
work through the pipeline again and extend it for class B, then B+, then C, then C'. A milestone is a class.
Everything else in this file serves that sentence.

## Next session starts here

This is the only part of the plan that says what to *do*. **Whoever finishes a piece of work updates it in the
same commit.** A stale next-step is worse than none.

**Where the session of 2026-09-25 ended (D87 to D92), and the next step.** The closure loop was built and
measured on `upduino-v3.01` (`route.freerouting.route_rounds`: the fine-pitch pads a round leaves untouched get
a fixed exit stub in the next; `scripts/rung.py ... rounds=N`): 81 of 86, then 82 with a clearance the repair
could not settle, then 80 with all eight stubs (D87). It does not converge and stays a tool (`WAFFLE_ROUNDS`).
The router's own log names what leaves the nets open: the maze finds the path and the shove that lays it
fails ("the new connection could not be inserted", 117, 85 and 118 times a run, on the same nets each time);
the walled-in exits ("no connection was found") went from 70 to 7 with the stubs, so the stubs were not the
missing constraint (D88). Four passes without the plane and the feeds: 11 failed insertions, 28 paths not
found, 25 standing violations; with them 38, 14 and 127: the fixed feeds are what the shove cannot move, and
102 of the standing violations are theirs under the router's rules (KiCad's DRC counts 0). **The second half of the session (D90 to D92) worked the feeds' form.** The stop points of the failed
insertions, read back from the jar's own "insert trace failed" lines, sit against the router's own earlier
copper pinned between fixed items, not at a hair of clearance (D90; slack 0.03 measured as predicted: no
change, three clearances the repair could not take back). So the feeds' form was measured, all at four passes
on upduino against the fixed form's 51 unrouted, 127 standing violations, 38 failed insertions and 67 of 86
(D91): routable, identical; nothing of the plane nets in front of the router ("after"), 10 unrouted but only
38 feeds find room afterwards; the feed sites reserved as keepouts and the feeds laid after the import, 24
unrouted, 25 violations, 26 failed insertions with the new L-shaped sites (96 feeds for 88), and GND and
+3V3 in 3 and 5 pieces from the nine pads boxed in by other nets' pads that no site reaches; those nine left
in the router's network with their nearest feeds fixed as vias to route to, 30 unrouted, 51, 17 failed
insertions, the planes in 2 pieces each. **The reserved form's verdict rows at 30 passes** (`WAFFLE_FEEDS_MODE=reserved
python3 scripts/gate.py b upduino-v3.01`): **80 of 86**, 0 violations, the router at 8 unrouted for the fixed
form's 32, 788 s; and, as committed, with a plane net's plated pins counted as pads no feed reaches (J2-9
was the +3V3 stray): **78 of 86**, 2 clearances the repair could not settle, 10 unrouted, 996 s, the three
+3V3 capacitor pads at U2 joined to each other and not to a via (D92). Neither beats 81, so the fixed form
stays `CLASS_B`'s `feeds_mode` and the reserved form is the measured alternative. **The owner's guidance
(D93): routing before cost.** Via-in-pad, filled and capped, is allowed on class B; measured first (D94) it
does not route upduino better (62 of 86 at four passes for 67, the failed insertions 40 for 38), so it stays
an option. The class B row under the committed default (96 feeds, 8 of them L-shaped, the thermal pads'
in-pad via sites reserved on the other layers; `python3 scripts/gate.py b upduino-v3.01`, 2026-09-25 19:27
UTC): **FAIL, 80 of 86**, one clearance of 0.011 mm the repair could not settle, the router at 36 unrouted,
999 s, digests imported 9c9e33a96f and final d7a1a2db6c; open are the same three nets and /FLASH_MISO,
/FT_SSn, /IOT_49A. The 81 of D85 was the configuration with 88 straight feeds and no keepouts; a change to
the DSN moves this board's row by a net or two either way (78 to 82 across D87 to D94), so neither number
judges the L-shaped feeds, which pass their test and feed eight more pads. The feeds beside U3's GND pins,
which the reference does not have, were then left to the pour as the reference leaves them (D95): the router
gains little (43 unrouted for 51) and the pins come out as islands, with or without their exits kept free,
because the reference's pour reaches its pins only through routing that leaves the ring free. The feeds'
form has now been measured seven ways (D91, D94, D95) without a pass, and the router's shove against its
own copper around U3 is what stands in every one of them. **The next step** is what
fails under the reserved form, since it is named and small where the fixed form's failures are the
router's shove at large: (a) a pad no feed reaches that the router aims at the plane it cannot reach
("layers are disabled") instead of the fixed via beside it (U3-48; in the jar the airline goes to the
nearest item of the net, the plane under the pad): hand those pads' nets no plane at all, or fix the via
*in* the pad's exit so it is the nearest item; (b) the pads no feed reaches are back-side pads under the QFNs (C14-1, C30-1, R5-2 under U2,
U8-8; D92), which the reference connects with a 0.5 mm back-side track to a via 1.4 to 8 mm away: the feed
search holds a stub clear of pads on the *other* side of the board, so a layer-aware `stub_clear` with a
longer reach for such pads is the smallest change, and its failing case is those four pads on the bare
board; (c) the same three signal nets
as in every form, all at U3 and its capacitors (U3-1 to the oscillator, U3-5 to R3, U3-21 to TP1, their
untouched ends and stubs in D87 and D91): the reference's own copper there is the answer key to read
(`references/` has it), before anything else is built. Each is a four-pass measurement (six minutes) with a
failing case first; the router's remaining failed insertions against its own copper (17 to 38 a run) sit
inside the jar, where the fork is the place to work them (the shove's recursion depths are constants, 20
and 5, in `AutorouteControl`), and the review the ladder rules call for after the fourth session says so.
Threads are settled by reading (D89: the jar's autorouting stage is single-threaded). The configuration is the
class B gate's default (`scripts/gate.py`, `CLASS_B`: the GND plane on a `power` layer, the feeds, no window,
one round, a 2400 s cap per run). `pico-ice-rev3` under it (`WAFFLE_ROUTER_PASSES=20 WAFFLE_ROUTER_TIMEOUT_S=4200
python3 scripts/gate.py b pico-ice-rev3`, 2026-09-25, taken with the own-pad feeds D88 dropped, 87 of them,
so the committed feeds' row on pico-ice is not yet measured): **FAIL, 61 of 95**, one
clearance the repair could not settle (0.007 mm), 3624 s for 20 passes of 145 to 200 s each (its 30 would not
fit the 4200 s cap here, and 20 sit on D82's plateau: 57 unrouted from pass 19), GND whole, +3V3, VBUS and
+1V1 in pieces (In2's pours laid after the import and cut by the router's tracks, D82), 34 nets open; the
router's log: "could not be inserted" 535 times, "no connection was found" 40. That is 11 nets fewer than
the class A configuration's 72 (D80 to D82), so on pico-ice the fed GND plane costs more than it gives, and
the insertion failure is the case on both rungs. Class B has had two sessions (PR #4 and this one); the
fourth without a pass writes the review the ladder rules call for, not a fifth iteration.

**The third class B session (D96 to D98) measured the router's own plane mode.** Asked whether Freerouting
supports planes better than our feeds, the answer is yes and no (D96): a plane on a `signal` layer the router
connects itself, every pad, no feed, and its standing violations fall from 127 to 25; a plane on a `power`
layer it cannot reach at all (the layer is forced inactive), which is what the feeds of D85 were for. The count
does not move (64 and 68 of 86 at four passes for the fixed feeds' 67; the same failed insertions at U3), and
the router lays 674 mm of track through the GND plane, since the jar prices the plane layer as its cheapest and
overwrites any per-layer cost handed to it (D97: the DSN block is read, then `applyBoardSpecificOptimizations`
replaces it; the settings file has no field for it). A wrong constraint of our own was found on the way (D98):
another net's fill counted as copper, so on a board with a plane of another net a stitch via had no site
anywhere; fixed, with its test corrected, and behind D91's after form and D95's islands, both to be
re-measured. The plane mode's verdict row (D99): **FAIL, 77 of 86**, 10 clearances at the LED D3, the router at
12 unrouted, 1055 s; its two strays are a thermal pad whose centre other nets' tracks took (the stitch now
searches inside the pad) and a plated pin the router's own tracks on In2 fence off from the fill, which only
the jar can mend. The after form re-measured under D98 (D100): **75 of 86 at four passes**, the best four-pass
count of any form, the router at 10 unrouted with nothing of the plane nets before it, but 44 feeds find room
for 88 pads after the router and +3V3 is left in 28 pieces: the router's copper takes the sites. The after form with
the in-pad sites reserved before the router (D101): 69 of 86, the router at 16 unrouted, 10 clearances, +3V3
in 15 pieces; the 17 pads left are the QFN pins that hold no via, the back-side pads of D92 and a plated pin,
which no feed form reaches after the router has filled the ring. **Nine feed forms have now been measured
without a pass, and the same pins stand in every one; the feed forms are exhausted** (D101), and the rule on
a tool failing three times on one problem applies: the missing constraint is inside the jar, not in the feeds.
**The next step is the owner's decision between three options, each with its measurement:** (a) the fork,
the smallest change with a measurement behind it: `applyBoardSpecificOptimizations` keeps the trace costs the
DSN sets (D97), so the plane mode (the only configuration in which the router connected every plane pad but
two, D96 and D99) runs with tracks priced off the planes; the build through the proxy is untried, and the
U3 and D3 knots (the shove, D88 to D90) stay whatever the planes do; (b) the plane mode as it is (D99: 77 of
86, 10 clearances, 551 mm of track through the GND plane), which is not a board the owner would fab;
(c) the review the ladder rules call for, written now rather than after a fourth session, with pico-ice
(61 of 95, D82) alongside upduino. D95's pour pins under D98 are measured (D102): 64 of 86 again, 8 GND islands at U3 for 10, so nothing
cheap is left to measure; a tenth feed form is not the next step. The after form with via-in-pad stays an option
(`feeds after inpad`). Class A ran on this code: PASS 5 of 5 (2026-09-25 23:27 UTC). The class B gate's
default is unchanged (fixed feeds on a `power` plane); `feeds_mode="none"` (`stitch` in rung) and
`layer_trace_costs` are options. Class A ran once with the wrapper's changes in place (`python3 scripts/gate.py a`,
2026-09-25 22:52 UTC: PASS 5 of 5); the `planes.py` change came after that run and is outside class A's path,
which never imports it (feeds off).

**Freerouting's source is at hand.** The owner forked it to <https://github.com/thuddwhirr/freerouting>, for
reading and for changes if a measurement ever asks for one; `GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1
https://github.com/thuddwhirr/freerouting /home/user/thuddwhirr/freerouting` puts it on disk (a fresh container
has it no more than the references). Read it as a guide, not as the jar: the fork's main (`a9689b2` on
2026-09-25) is ahead of the 2.4.1 jar we run, with a `router.plane_nets` setting, plane nets routed first,
`plane_via_costs`, a `fanout.pin_sorting_order` and a relaxed plane validation, none of which the jar's classes
carry (its strings were checked). What it settled today (D85): a via over or touching a pad of its own net
counts as a violation while via-in-pad is off (`Via.isObstacle`, `Pin.isObstacle`), which KiCad's export leaves
it; the fanout stage vias every SMD pin with a net (`BatchFanout`); conduction areas are obstacles only when
`BoardRules.ignoreConduction` is off. Building the fork needs Gradle 9.7.1 from services.gradle.org and the
JDK 25 under `build/tools/`; whether the proxy serves the download is unknown, untried. The jar's own classes
are readable with `build/tools/jdk/bin/javap -p -c` after `unzip`, which is how D89 found its autorouting
stage single-threaded (`-mt` reaches only the optimiser, which is off) and how D88's failure messages were
traced to `FoundConnectionInserter` in the fork.

**Confirm the state first.** A fresh container has no references, no tools and no `build/`; fetching takes a few
minutes. The Python dependencies are in `pyproject.toml` (`pip install z3-solver numpy shapely pytest`).

```
python3 scripts/fetch_tools.py          # Freerouting 2.4.1, a Java 25 and KiCad's symbol and footprint libraries at
                                        # tag 9.0.9 into build/tools/ (D56, D74); a few minutes
python3 scripts/check_env.py            # KiCad 9, pcbnew, z3, Java 25, the jar, Xvfb, the libraries: all present on 2026-09-24
python3 scripts/fetch_references.py     # clones the 23 reference boards into references/
python3 scripts/gate.py a               # expect PASS 5 of 5 (D73), about 12 minutes; the first three boards alone
                                        # (`gate.py a tinkerforge-temperature open-book-c1 olimex-esp32c3-devkit`) in two
python3 scripts/gate.py b upduino-v3.01   # class B's first rung (D84) under the class's configuration (D86, the
                                        # gate's default since D87): FAIL, 80 of 86 with one clearance (D94's
                                        # row; 81 under D85's feeds), 17 to 22 minutes on this container (30
                                        # passes; the wrapper's 1200 s cap killed it in pass 26, so class B's
                                        # rows run under a 2400 s cap)
python3 scripts/design.py status temperature-sensor   # the synthetic design: six gates PASS, what waits on the owner
python3 scripts/design.py run temperature-sensor      # re-runs all six stages, about 30 s; the committed files change
                                                      # only in their timestamps and in what the router lays
python3 -m pytest -q -rs                # classes A and B (the parked classes' tests carry a marker pyproject deselects;
                                        # `-m parked` runs them); expect 0 failed; the class B sanity pair costs minutes a
                                        # board, so `-m "not parked and not bench"` is the quick run, 137 tests in a minute
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
| `waffle_eda/bench/rebuild.py` | whole-board strip-and-score with measured rules; sanity pair asserted on class A (D50) |
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
| `scripts/insertion_stops.py` | where a run's failed insertions stopped (D90): the jar's "insert trace failed" lines read back onto the routed board, the nearest copper by kind and the corridor at each stop |
| `scripts/rung.py` | one class B gate row with the plane handling, the feeds and their form (`stitch` for none, D96; `loose`, `after`, `reserved`, `vias`; `costs=L:C,...` for D97's block), the stubs, the router's fanout stage and the closure loop's rounds selectable (`rounds=N`, `open=<board>`, `exits=...`), for iterating on a rung under a short budget (D77, D81 to D91) |
| `tests/` | 283 tests: 137 in the quick run (`pytest -m "not parked and not bench"`, about a minute), 18 more in the default run (the class B sanity pair, `bench`, minutes a board), 128 parked (`pytest -m parked`) |
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
