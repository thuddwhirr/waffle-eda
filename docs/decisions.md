# Decisions

**An entry is one of two things:** a decision the owner made, or a measurement with its number, the commit and
the script that produced it. Ten lines at most. Recommendations, proposals and narrative do not go here; they go
to the owner in chat and come back as a decision or as nothing. An entry stands until a new measurement
contradicts it, and the entry that contradicts it says which measurement.

Numbers are kept from the first five days so that citations in code, tests and the lessons still resolve. The
full text of D1 to D54 is in [`archive/decisions-2026-09-21.md`](archive/decisions-2026-09-21.md); the entries
dropped from this log are listed at the end with the reason.

## The project

**D1. Scope.** A general-purpose, Claude Code driven tool suite: the six-stage pipeline of `definition.md`. The
`waffle-fpga` board (ECP5 caBGA381 with a DDR3 bus) is the hardest benchmark, not the deliverable. Owner, 2026-09-17.

**D2. Stack.** Python 3.11 with KiCad 9.0.9's `pcbnew` bindings; z3, numpy, shapely, pytest; Java and Xvfb for
Freerouting. `scripts/check_env.py` verifies it. Owner, 2026-09-17.

**D3. Reference boards** are fetched by `scripts/fetch_references.py` (pinned commits, partial clones) and never
committed; licences and attribution live in `waffle_eda/bench/references.toml`. Owner, 2026-09-17.

**D4. Salvage.** The `waffle-fpga` tools are in `salvage/waffle-fpga/` verbatim, for reference; nothing is imported
from there without a test here. Its documents are in `lessons/` with provenance. Owner, 2026-09-17.

**D5. Fab profile** is a data file (`waffle_eda/fab/profiles/pcbway.toml`) whose numbers come from the owner or
carry the date of the page they were read from. See D53 for what a session may not do about it. Owner, 2026-09-17.

**D6. The first end-to-end target is a class A board**, then B, and the FPGA board last. Owner, 2026-09-17;
restated as the whole plan in D55.

**D7. Repository layout.** `waffle_eda/` the package (`kicad/`, `bench/`, `fab/`, `route/`), `scripts/` entry
points, `tests/`, `docs/`, `references/` and `build/` ignored. Owner, 2026-09-17.

**D8. Many references per class, not two.** A tool that passes one board has learned that board. Every class in
the ladder has several open-hardware KiCad references; the registry is `waffle_eda/bench/references.py`. Owner,
2026-09-17.

**D9. The survey and the ladder.** 33 repositories probed (`scripts/survey_references.py`); 23 boards registered
across classes A, B, B+, C and C' (`references.md`). Rejected and why: no `.kicad_pcb` at the pinned commit
(icebreaker, greatfet, pyboard, ZSWatch, SparkFun Thing Plus, Adafruit Feather RP2040, epdiy); no licence file
(hydrabus, Tinkerforge ethernet-extension, icebreaker-pmod); unloadable format (Easyduino); RF is a non-goal
(hackrf). Pitfalls: a footprint name is not a package type (TinyFPGA's BGA is `CM81`), so a BGA is detected as a
filled lattice of pad centres; `pcbnew.LoadBoard` returns None for a file it cannot parse. Measurement, 2026-09-17.

**D53. A reference board proves its own manufacturability, and vendor limits are deferred.** Every reference was
fabricated, so the rules its copper demonstrates are achievable: the benchmark's DRC criterion is the per-board
measured rules (`bench/constraints.py`, `bench/rebuild.py`), and no fab tier is applied to a reference. The
target board's via size and fab tier are specified by the owner when a class C design is started, not before, and
not researched. No vendor research of capability, price, lead time or reputation: this environment cannot reach
the sources (two rounds, 316 agents and 19.5 M tokens, returned evidence for one vendor). Owner, 2026-09-21.

**D55. Build the whole pipeline for class A boards to completion first; then work through the pipeline again
and extend it for class B, then B+, then C, then C'.** Owner, 2026-09-23, on the review of the first five days.
"Completion" for a class: every reference board in the class passes the class gate through all six stages
with no interactive routing, and one synthetic design of that class reaches fab files the owner reviewed. The
next class is not started until the current one is complete, and every earlier class stays passing. Each stage
uses the cheapest existing tool that passes the class (Freerouting for stage 5 of class A, `kicad-cli` for DRC
and exports); own code is written where a measurement shows the baseline fails, and never re-architected
because of one board. The DDR3 bus work (M3b, D30, the M6 target board) is parked inside class C. The user
interface is a separate project that consumes this one's files, renders and reports. The first five days' plan,
router spec and full log are archived (`archive/`); this log is condensed to what stands; CLAUDE.md is
rewritten to the rules in it.

**D56. Stage 5's baseline is Freerouting 2.4.1 on Java 25, fetched, not installed.** The current release needs
Java 25 (class file 69); the container has 21. `scripts/fetch_tools.py` puts the jar and a Temurin 25 JDK under
`build/tools/` from GitHub releases (Maven Central answers 429, Adoptium's API 403 through the proxy);
`scripts/check_env.py` requires both. The wrapper is `route/freerouting.py`; the class A gate runs it.
Owner (the version), 2026-09-23; the rest measured the same day.

**D57. What the wrapper had to learn, each by running it** (`route/freerouting.py`, 2026-09-23).
`pcbnew.ExportSpecctraDSN` returns False and writes nothing when two footprints share a reference (five of six
class A boards); duplicates are renamed for the export and restored after the import. The DSN carries the
board's net-class values, not the measured rules; written in, the router asked for `tinkerforge-temperature`'s
measured clearance (0.1972 mm, 0.003 under its SOT-563's pad gap) attaches nothing to that part: its maze finds
the path and its exact insertion check rejects the last segment; at 0.190 it routes the whole board in 2 passes.
So the wire-to-SMD-pad clearance is handed over as the rule less 0.0072 (4 of 6 nets, 2 clearance violations);
the same slack on every clearance gives 6 of 6 there and 175 violations of exactly that slack on
`libresolar-mppt-2420`, so it stays scoped. The default via cost of 50 stops the router placing any via of its
own on a 15 x 25 mm board (0 vias, 18 passes alternating between two top-layer solutions); `router.scoring
.via_costs` 1 in its settings file gives 14 to the reference's 15. The same setting as an `(autoroute_settings)`
block in the DSN made the loader drop every pin of `olimex-rp2040-pico-pc` (0 unrouted items) when placed
before the structure's rule block and was not read after it. The fanout stage necks its stubs to 75 % of the
width, below the rule, and is off. The session file truncates via drills to whole micrometres (248.9 became
248), so the drill is rounded up to one. Hole-to-copper is not a Specctra rule: typed via and pin clearances of
the rule less the smallest ring carry it. Escape stubs laid by the wrapper (D51's finding, the reference's own
exit pattern) made the smoke test worse (2 of 6 against 6 of 6 under the global slack) and stay off. Runs are
deterministic per configuration.

## Benchmark and measurement

**D10. Strip-and-score.** `bench/harness.py` strips the bus nets' tracks and vias, keeps everything else as
obstacles, and scores a candidate on connectivity, violations, lengths, vias and layers. Do-nothing scores 0.000,
the original 0.99. 5 to 16 s a run. Pitfall: delete items with `board.Delete`, not `board.Remove`. Measurement,
2026-09-17.

**D12. Synthetic BGA-pair cases** (`bench/synthetic.py`): 6x6 straight and reversed on 4 layers, 9x16 on 6, 20x20
on 8 with a three-column bus; each loads, passes DRC, and has exactly its bus and power nets open. 2026-09-17.

**D17. The benchmark hands the router each reference's constraints as if agreed upstream.** A constraints file
per reference stands for what stages 1 to 4 would have produced: pitch, pad, ball map, the copper spacing and
hole-to-copper the board's own copper meets (binary search under an overriding rules file), widths and vias per
package, the layers the bus may use, via style, thickness. The gate is zero electrical violations under those
values, which the original meets by construction. Owner, 2026-09-18.

**D18. KiCad 9.0.9's DRC caps each violation type at about 200 and which ones it keeps varies run to run**, so a
count near the cap is truncated and not repeatable. The benchmark's rules file holds every electrical rule at
zero for all items and applies the measured values only to pairs touching the nets under test, by explicit net
name (a net class injected into the project file did not take effect under `kicad-cli`). Measurement, 2026-09-18.

**D25. A result must not depend on item order.** The negotiation converged in one process and stalled in
another on identical input because islands were listed in board-item order, which varies with string hashing.
Inputs are sorted by geometry; per-round digests agree across hash seeds. Measurement, 2026-09-18.

**D33. A bench parameter chosen by assumption invalidated every routing measurement taken under it.** The bus
bench's default 0.8 mm extra spacing between bus nets made every net contested by construction on a 0.8 mm
lattice; 0.4 stalls too, 0.0 and 0.2 do not. Every bus routing figure from 18 September was taken inside that
stall. Rule (D38): every recorded result names its commit, environment overrides and resolved settings, and a
parameter that changes a result is measured before it is set. Measurement, 2026-09-19.

**D38. Provenance is a rule with a mechanism**: the bench writes the commit, overrides and resolved costs with
every result, and a result without them is not quotable. Also: M3 split into a plan (M3a) and a route inside it
(M3b); the class C ladder rises OrangeCrab, LogicBone, ButterStick. Owner, 2026-09-20.

**D43. The 54-of-55 bus result of 18 September is not reproducible and is not bisected**; 42 of 55 is the
baseline. Those runs had no plan behind them, so neither figure is comparable to a route inside one. Owner,
2026-09-20.

**D50. The whole-board benchmark** (`bench/rebuild.py`, `scripts/gate.py m4`, now `a`). The problem board is
placement, pads, outline and keepouts with every track, arc, via and pour removed; the criterion is every
routable net connected and zero electrical violations under rules measured off that board. The sanity pair
(original 1.000, stripped 0.000) is asserted per board in `tests/test_rebuild.py` and found four scoring
defects: single-pad nets counted as connected; violations between two fixed items charged to the router; an
`Arc` on `Edge.Cuts` read as copper; net names escaped in the API and unescaped in the DRC report
(`kb.unescape_net`). `harness.drc_facts` has the fourth defect latent. Measurement, 2026-09-21.

**D58. A KiCad 5 board's legacy zone fills fail KiCad 9's DRC until refilled; its net-class rules survive the
conversion, its project rules do not.** Under the rules KiCad 9 applies with no project file, the three KiCad 5
class A references show 19, 4 and 241 violations, almost all "zone clearance" of the zone's own setting short by
0.01 mm: the legacy fill converted "best effort". After `ZONE_FILLER` in KiCad 9: 0, and 15 on
`libresolar-mppt-2420` (3 at KiCad 9's default 0.2 mm, which its designer never used, 12 edge). `kicad-cli pcb
drc` never refills. The designers' net-class clearance and width are in the board file and load (tinkerforge
0.150 / 0.300 mm); the project-level rules of KiCad 5's `.pro` are not read. The benchmark's measured rules are
unaffected: they are measured off the copper and every converted original passes them (`tests/test_rebuild.py`).
Measurement, 2026-09-23.

**D59. Why Freerouting's copper fails the rules the reference meets** (four class A boards, 2026-09-23,
`build/bench/rebuild/*/candidate.json`). Same widths and vias as the reference; the copper is placed
differently. (1) 48 clearance violations short by under 0.011 mm: the router keeps every coordinate as an
integer at 0.1 um and every round shape as an octagon (`geometry/planar/IntOctagon`), which lies inside the
true circle by up to 7.6 % of the radius (0.011 mm on a 0.30 mm trace end, 0.027 on a 0.70 mm via); its own
check passes, KiCad's exact one does not. (2) 40 width violations by 0.03 mm or more on `open-book-c1`: traces
necked where they enter a pad; `automatic_neckdown` off changes nothing. (3) 26 violations of 1.016 and
1.85 mm: per-pad clearance overrides on fiducials and mounting holes, which the Specctra export does not carry.
(4) Ground left as tracks where every class A reference pours it. Under the designers' own project rules our
copper fails the same way (open-book 48, esp32c3 31; the originals 0). Measurement.

**D60. The smoke test passes the class A gate with Freerouting inside three repairs** (`gate.py a
tinkerforge-temperature`, 2026-09-24, commit of this entry): 6 of 6 nets, 0 violations, score 1.000, 28 s.
The router is handed every clearance less 0.0072 mm (D57) and its output is repaired under KiCad's own DRC
(`route/freerouting.py`): pads with a clearance override exported as keepouts grown by the override less the
clearance (D59 kind 3; on `olimex-esp32c3-devkit` 16 hole violations to 0); tracks the router necked set back
to the rule width (kind 2; on `open-book-c1` 40 width violations to 0, 40 clearance ones in their place); each
clearance violation's track moved away by the shortfall plus 0.002 mm, tracks sharing its ends carried along,
up to four DRC rounds (kind 1; on the smoke board 9 violations to 0 in 3 rounds, 8 moves). Runs are
deterministic per configuration; a subset of the gate is a rung, never the milestone. Measurement.

**D61. A pad's pieces that touch are one connection to KiCad and separate pins to Freerouting.** KiCad exports
the pieces of a pad with one number as `REF-N`, `REF-N@1`, ...; where their copper overlaps (the 0.2 mm fingers
of `open-book-c1`'s buttons touch their round pad) KiCad's connectivity joins them, while Freerouting tried to
route between the interleaved fingers of the two nets and left 14 GND connections open. Where they do not
overlap (the smoke board's connector has two `EP` pads 11.6 mm apart) KiCad wants copper between them. So only
the pieces joined by copper to another piece of the same number leave the router's pin lists
(`freerouting.joined_pins`, `drop_pins`); dropping every suffixed pin cost the smoke board a net. With it,
open-book's violations went from 47 to 0 under the cruder filter. Measurement, 2026-09-24.

**D62. Two rungs green: `open-book-c1` passes the class A gate after the smoke test** (2026-09-24: 35 of 35
nets, 0 violations, score 1.000, 135 s; `tinkerforge-temperature` 6 of 6, 0, 25 s). What it took beyond D60:
pours laid after the import, not before (as planes the router trusted them for the SOT-563's middle GND pad,
which the fill cannot reach), with the hole rule less the smallest ring in their clearance and a no-pour rule
area around every hole whose ring is under the rule (the fill keeps its clearance from a pad's copper, not its
hole; open-book's four mounting holes); the router's pin lists reduced to one piece per pad where pieces touch
(D61); a router keepout by the hole rule around holes with no net. And the repair became a small placer under
the exact collision index: every track and via of a violation is pushed, a track pressed from both sides
settles in the middle, a track moves to the middle of the corridor the index measures or is left as boxed in,
a boxed track's violating item and then its far-side blocker are pushed instead where they are ours, a via
against fixed copper moves away, and a move may keep only the collisions it moves away from, so none deepens
(the rule that took open-book from 2 violations to 0). Runs are deterministic per configuration. Measurement.

**D63. `kicad-cli pcb drc` does not report the same violations on every run of one file.** Eight runs on a
saved board of eight parallel tracks with seven pairs 0.19 mm apart under a 0.1972 rule: seven runs report 7
clearance violations, one reports 6 (2026-09-24). D18 recorded the same for counts near the cap; this is far
below it. Consequences: the gate's scoring DRC runs twice and a violation either run reports counts
(`bench/rebuild.DRC_RUNS`); the repair steers by the exact collision index (`freerouting.index_violations`)
and not by the report, which also removes one DRC per repair round; and the order test
(`tests/test_freerouting.py`) found this through a digest that differed between insertion orders of the same
copper. Measurement.

**D64. The repair runs under two rules in turn and keeps the clean result.** Whether a track end dragged by a
neighbour's move may come closer to old copper than the router's own clearance decides two boards opposite
ways: floored, `olimex-esp32c3-devkit` repairs to 0 violations and `open-book-c1` keeps 5; free, open-book
repairs to 0 and the esp32c3 keeps 2 (a pair deepened to 0.039 mm). One rule serves neither; the repair now
tries the floor first and, if the index is not clean, restores the imported copper and tries free
(`freerouting.STRATEGIES`). Measured with `scripts/repair_only.py` on the three imported boards, 2026-09-24:
smoke 0 (floor, digest c30c3f3d1e), open-book 0 (free, d6ec360560), esp32c3 0 (floor, b9c2ad5f17), each
reproducible run to run. Measurement.

**D65. Freerouting's optimiser is off: it is where the time and the variation were.** Its maze search, rip-up
resolver, pass runner and optimiser draw on Java's random generator with no seed setting; on
`olimex-esp32c3-devkit` the same DSN (md5 40ee4f1c09) gave three different boards in three runs, the optimiser
taking 11 of each run's 12 minutes for a score it never improved. With `optimizer.max_passes` 0 the same board
routes in 34 s and two runs agree to the digest (imported c0c904b4ac); the smoke test routes in 21 s. The gate
scores connectivity and DRC, which the optimiser does not change; it costs vias (107 to 71 there) and stays off
until a gate scores what it buys. Measurement, 2026-09-24.

**D66. Three rungs green through the gate in a few minutes** (`gate.py a tinkerforge-temperature open-book-c1
olimex-esp32c3-devkit`, 2026-09-24: PASS 3 of 3; 6 of 6, 35 of 35, 34 of 34 nets, 0 violations each). What
the last rung took: the router's copper-to-edge clearance handed over as the measured rule (its own default
is 0.5 mm; open-book's rule is 0.5948 and a diagonal from a button pad cut the corner of a step in the edge at
0.25 mm, which no move of the placer could fix); duplicate and dangling segments pruned after the import (the
router leaves spurs and counts them among its own violations; KiCad's DRC reports them as warnings only); a
short connected segment carried whole with a move; a via boxed on the straight line away from a track moved
along an axis that still gains the distance; and an end-only move of a long track as the last fallback. The
loop that found each of these: `scripts/repair_only.py` on the imported boards, a minute a board with no
router run. Measurement.

**D67. A rule area that forbids only the copper pour leaves the router's DSN.** KiCad's Specctra export writes
it as a plain `(keepout)`, the same as one forbidding tracks and vias (tracks alone give `wire_keepout`, vias
alone `via_keepout`; measured on a board of one area of each kind, `tests/test_freerouting.py`).
`olimex-rp2040-pico-pc` draws no-pour areas over both pad rows of its TSSOP-14 (U3), and the router could not
start a search from any of its pins: 13 of the board's 14 open connections were on U3. The wrapper lifts the
pour-only areas off the board for the export and lays them back for the fill (`lift_pour_only_rule_areas`).
Gate row before and after (2026-09-24): 52 of 60 nets, 0 violations, 650 s; 59 of 60, 0 violations, 214 s.
Measurement.

**D68. `olimex-rp2040-pico-pc`'s last open net, `Net-(LED1-Pad1)`, and what was measured** (2026-09-24). Its
only corridor runs along the bottom edge; the router's GND track and via take it, and the router then rejects
its own path at insertion ("could not be inserted", 18 passes). The router keeps the edge setting plus 0.03 mm
(slot board: at 0.4776 a 0.86 mm slot routes and 0.84 does not; at 0.30, 0.68 and 0.66); its maze accepts
about 0.03 mm less than its inserter. Handing the router 0.30 at the edge (DRC and repair at the 0.4776 rule):
60 of 60, no edge violation (closest copper 0.5389), 1 clearance the placer left (via to track, 0.0054 short).
GND routed last around the signals (signals as obstacles, then fixed or shoveable): LED1 routes at the rule,
but `/SPI0_CSn1` then fails at insertion, U3's pad 10 GND piece (in a no-pour area) is left, and the placer
made a short between the two I2C1 tracks: 58 of 60 either way. Measurements; the choice is the owner's.

**D69. Four rungs green: `olimex-rp2040-pico-pc` passes the class A gate** (2026-09-24: `gate.py a` on the
four, PASS 4 of 4; 60 of 60 nets, 0 violations, 265 s; the three below unchanged at 6, 35, 34 of their nets, 15
to 44 s). What it took after D67: the router keeps 0.30 mm from the board edge (`ROUTER_EDGE_MM`, D68) with
the DRC and the repair at the measured rule, and three placer defects the leftovers exposed, each with a test:
a track pressed from both sides of a corridor too narrow for it settled 0.0002 mm a round and counted as
moving, so the via pressing it was never asked to give way; of two vias too close only the first was asked,
though only the second could move; and the edge clearance was measured to the stroke the edge is drawn with
(0.127 mm of it) and capped at 0.25 mm, so a track KiCad passed at 0.539 mm read as 0.25 short. The repair
alone (`repair_only.py --twice`) reproduces to the digest `42389e3b93`, the gate's final. Measurement.

**D70. `crkbd-corne-cherry`, measured** (2026-09-24). 277 x 108 mm, 950 pads (344 plated, 302 with no net),
158 nets; the reference lays 3027 tracks and 452 vias. The router's passes take 170 to 230 s each and leave
96, 73, 49, 51, 39, ... 36 unrouted after passes 1 to 12; the 20-minute cap falls in pass 6 and a killed run
writes no session. Freerouting's `job_timeout` does not stop its auto-routing stage (only its fanout and
optimiser stages read it; a 14-minute setting routed on to the cap), so a run that must finish gets a pass
budget instead. Two defects found on the way, fixed with tests: the cap killed `xvfb-run` and orphaned the
JVM, which routed on beside the next run (D57's empty session file); and the benchmark recorded the
reference's 921 teardrop zones as pours (esp32c3 had 154; it still passes without them). The router's 12
standing violations are conflicts among fixed items, four of them EXLED1's override keepouts over its
neighbouring pads. With a five-pass budget (24 min with the repair and the DRC): 119 of 152 nets, 39 open connections
of which 25 on the two RP2040s' QFN-56 (0.4 mm pitch); 833 violations at import, none over 0.011 mm; after the repair 51
by the index, up to 0.19 mm, four shorts, under either strategy. Measurement.

**D71. Three placer defects crkbd's five-pass board exposed, fixed with tests** (2026-09-24). A gap within
rounding of the rule (KEY3's stub, 0.18896 under 0.189) read as a hole violation of 0.0605 mm on a pad with no
hole, which the placer then chased; an end move kept a track's 0.006 mm violation and swung its far end 0.28 mm
into the neighbour (KEY5 into KEY10, a short), and a chain push could deepen the same way: both movers now hold
one rule, a kept collision never closes below the router's own clearance floored, nor within 0.01 mm of a short
free (D64); and the repair keeps the strategy whose deepest violation is shallowest before the fewest. Repair
alone on `build/fr/crkbd-p5/imported.kicad_pcb`: 833 violations at import (none over 0.011 mm); before, 51 left
up to 0.19 mm with 4 shorts (KiCad 40); after, 39 left none over 0.0075 mm (KiCad 32, no shorts), digest
598d5f711d. The four green rungs pass; open-book now cleans under the floor. Measurement.

**D72. `crkbd-corne-cherry` leaves the class A ladder.** A keyboard panel is a very unusual project, driven by
its physical layout rather than a chip layout problem; it stays in the registry (class `-`) and fetched, for the
measurements D70 and D71 cite. Class A is the other five, `libresolar-mppt-2420` last. Owner, 2026-09-24.

**D73. Class A's gate passes on all five boards** (`gate.py a`, 2026-09-24: PASS 5 of 5; 6 of 6, 35 of 35, 34 of
34, 60 of 60, 102 of 102 nets, 0 violations each; 12 to 590 s a board). What `libresolar-mppt-2420` took: its USB
connector's shield is twelve pad pieces in six overlapping groups that the reference joins with short tracks,
and D61's rule left the router one pin per group with the other pieces as pads of no net, obstacles walling the
pin in: 1 of 6 connections routed. Every piece as a pin with a fixed wire across each overlap measured worse
(open-book 32 of 35, esp32c3 33 of 34, rp2040 58 of 60) and was reverted. What holds: a plated piece stays the
group's pin where there is one (the router reaches it on either layer), the groups the router leaves apart are
joined after the import by a straight track where the run clears every other net (4 laid), and a via boxed
between a pad and a track pushes the track as a boxed track would (its two 0.002 and 0.004 mm leftovers).
Measurement; the milestone's other half, the synthetic design through the six stages, is untouched.

## Class A (in progress)

**D49. The class A ladder rises**: `tinkerforge-temperature`, `open-book-c1`, `olimex-esp32c3-devkit`,
`olimex-rp2040-pico-pc`, `crkbd-corne-cherry`, `libresolar-mppt-2420`; the last is the one whose power on
continuous copper matters. Owner, 2026-09-21. (The rest of D49, taking M4 ahead of M3b, is superseded by D55.)

**D51/D52. The homegrown single-stage router reaches 4 of 6 nets on the smoke test and is parked.**
`route/board_router.py` (grid A\*, exact collision per edge, no global stage, no rip-up): on
`tinkerforge-temperature` 4 of 6 nets, 0 violations, score 0.667, 8 s; `open-book-c1` 25 of 35;
`olimex-esp32c3-devkit` 29 of 34 in 441 s; `olimex-rp2040-pico-pc` killed at 13.3 GB; two boards exceed its
400,000-node ceiling. Facts that stand for any stage 5: a TSSOP-8 or SOT-563 row leaves 0.2 to 0.25 mm between
pads, so nothing passes between them and every such pad needs an escape stub ending at a computed point, not a
lattice node; a failed net's copper must come off the board inside the run; a one-way graph and copper left
behind were both found only by running. Measurement, 2026-09-21.

**D74. The synthetic temperature-sensor design goes through all six stages to fab outputs**
(`scripts/design.py run temperature-sensor`, 2026-09-24, commit of this entry). Stage 1 `design.md`: 9 blocks, 5
nets, the locked set; stage 2 `bom.csv`: 9 parts, each symbol and footprint found in KiCad's libraries; stage 3: a
four-sheet schematic, ERC 0 errors and 0 warnings, its netlist matching the design one to one (5 nets, 19 pins);
stage 4 `spec.toml`: two layers, clearance 0.14 mm held 0.01 under the SOT-563's 0.15 mm pad gap; stage 5: placed,
routed and pulled in to 22.5 x 12.7 mm in one attempt, 5 of 5 nets, 0 violations, 0 DRC warnings, 13 s; stage 6:
nine Gerbers, drill files (14 plated and 2 non-plated holes), positions, the vendor BOM, the assembly drawing, the
stack-up note and an IPC-D-356 netlist grouping the pins as the schematic does, every file re-parsed. Found on the
way: the container lacks KiCad's libraries (fetched at the release's tag); ERC warns on every symbol without project
library tables; a board built in memory and handed to the router segfaults `pcbnew` (saved and reloaded instead).
Waiting on the owner: the review of `design.md` and the outputs; prices and lead times, unknown. Measurement.

**D75. Milestone A's fab outputs are taken as correct for now; class B starts.** The owner checks
`designs/temperature-sensor/out/` with the manufacturer, which takes time; until that check is recorded here the
design's `owner review` reads "accepted, provisional" and milestone A's completion is provisional on it. The
prices and lead times the BOM and the spec escalate stay unknown. Class B begins with the first task the plan
names, the benchmark's sanity pair on the nine class B references, in the order the plan lists them. Owner,
2026-09-24.

**D76. The benchmark reads a reference as it is: measured on class B** (2026-09-24). Three of the nine class B
references failed the sanity pair's first half, the original not meeting its own measured rules. `upduino-v3.01`
leaves its QFN's exposed pad and its USB shield with no net while GND vias and tracks stitch them (24 shorts, 36
clearances; the clearance search poisoned to 0.0495); `sensor-watch-c1` pours to 0.0894 mm of a non-plated hole,
under the search's 0.10 floor, and runs a track over a no-net polygon that is its buzzer contact;
`tinkerforge-master-v3.2`'s copper sits 0.19 mm from a hole against a board-setup minimum of 0.25 that KiCad
enforces under any rules file. The benchmark now reads an answer board (`rebuild.answer_board`): the checkout's
board with every no-net pad the reference's own copper overlaps given that net (probed at a 0.001 mm clearance:
a rule of zero reports no short), a no-net polygon paired with its net and the pairing forgiven in scoring, the
DRC copy's setup minimums zeroed, the searches from zero. All three measure (clearance / hole: 0.1495 / 0.2495,
0.087 / 0.0893, 0.1464 / 0.1557); class A still brackets. Measurement.

**D77. A run fails in minutes, not an hour: every long call bounded** (2026-09-24). The first class B sanity run
spent 28 minutes in KiCad's zone fill of `mch2022-badge` in this process (D14's pathology: every zone alone fills
in seconds), and its rule measurement was 21 DRC runs of 158 s each. Now: the benchmark's and the gate's fills run
in the child process with D14's caps (`kicad/refill.py`); every `kicad-cli` DRC has a budget
(`WAFFLE_DRC_TIMEOUT_S`, 900 s) and fails with a message, and each report records its seconds; the measurement
bisects the three constraints in one DRC per step, 7 runs instead of 21, to the same values (the smoke board:
0.1964 / 0.4253 / 0.5479 either way, 8 s); a gate row takes a shorter router budget through
`WAFFLE_ROUTER_PASSES` and `WAFFLE_ROUTER_TIMEOUT_S` for an iteration and says so in its detail (D38), never
for a milestone. Owner (fail faster), the rest measured, 2026-09-24.

**D78. The reference's fill is not refilled: a fill by KiCad 9 is other copper** (2026-09-24). D76's first
version refilled the answer board's zones (after D58), and the class A gate went red, 3 of 5: `olimex-rp2040-pico-pc`
measured a clearance of 0.212 mm where its own pours sit 0.153 from its tracks (the refill under the project's
settings keeps more), so the router was asked for a rule the board never demonstrated, routed differently (a
different DSN) and left one net open; `libresolar-mppt-2420` kept 8 clearances the repair could not settle.
Without the refill the two read 0.1558 / 0.2534 and 0.1182 / 0.2456 (clearance / hole), still not the earlier
0.1534 / 0.2526 and 0.1179 / 0.2464: the bisection's path, hence its value, depends on its bounds, and D76 had
moved them to zero; under the 0.0024 mm stricter rule the RP2040 board's route changed and one clearance stayed.
So the bounds class A was measured with stand (`SEARCHES`), and a board that fails at a bound is searched below it
(sensor-watch: 0.0878 / 0.0893). Under that, the class A rules reproduce exactly. The file's fill is the copper
the designer had made; only a candidate's pours are filled here (D62). Measurement.

**D79. Connectivity is read from KiCad's own graph; the DRC report's unconnected list stops at about 500.**
The class B sanity pair's second half (2026-09-24, 39 minutes for the nine, 31 of them `mch2022-badge`'s rule
measurement): the three largest boards stripped bare scored 0.574, 0.693 and 0.302 (`buspirate5-rev10`,
`tinytapeout-demo`, `mch2022-badge`), their reports listing 499, 501 and 501 unconnected items with 78, 42 and
125 of their nets never named, so those read as connected with no copper on the board. D18's cap, on another
list. `kb.open_nets` now joins each net's pads, tracks, vias and fills through KiCad's one-hop connectivity
queries in a union-find (the whole-cluster query needs a vector type the bindings do not wrap) and
`kb.unconnected_count` is KiCad's own uncapped count; `rebuild.score` and stage 5 use them, the DRC report only
for violations. Stripped `buspirate5-rev10`: 183 nets open of 183, 0.1 s; its answer: 0. Under it the second
half passes on all nine class B boards and the four class A ones tested (5.5 minutes, 5 of them mch2022's two
DRC runs), and the five class A routed boards re-score 1.000. Measurement.

**D80. Class B's first rung, `pico-ice-rev3`, measured at the class A configuration** (`gate.py b
pico-ice-rev3`, 2026-09-24): the router hit the 20-minute cap in its ninth pass and, killed, wrote no session
(D70), so 0 of 95 nets; passes of about two minutes each left 313, 56, 57, 43, 47, 35, 27, 32, 27, 27 items
unrouted after passes 0 to 9, with 13 standing violations from the first pass on. Every layer went to the router
as `signal` and the reference's planes were stripped with the rest of its copper (D50), so the ground and
supply nets that the reference pours on In1 and In2 (GND; +3V3, VBUS, VDC) were being routed as tracks. KiCad
exports a zone laid before the export as a DSN `(plane NET (polygon LAYER ...))`, which Freerouting connects to
by via (the salvaged exporter's way). The reference routes 273 tracks on In2 and 11 on In1 beside its planes,
so the layers stay `signal`. Measurement; the change it asks for is the next step.

**D81. The planes stay out of the router's DSN on class B; what stays open on `pico-ice-rev3`** (2026-09-25,
four passes each, `scripts/_run_rung_scratch.py`). The reference's inner-layer pours handed over before the
export: on `signal` layers Freerouting 2.4.1 calls each "a dedicated power plane" (a conduction area over half
the board) and writes an empty session, three runs; typed `power`, In1 and In2 both: 132 and 119 items
unrouted after passes 1 and 2 against 56 and 57 with no planes; In1 (GND) alone: 102, 83, 73, 76 after passes 1
to 4, 68 of 95 nets, 51 missing links, 9 clearances, GND itself in 3 pieces. No planes, every pour laid after
the import (class A's way, D62): 56, 57, 43, 47; 72 of 95 nets, 30 missing links, 1 clearance, 517 s. The 30
missing links are all signals of the two QFNs (U3, the RP2040 at 0.4 mm pitch; U6, the iCE40 at 0.5) to each
other and to the headers J2 and J3, and the router lays 533 of its 1577 tracks on In1, which the reference
keeps as its GND plane (11 tracks). So the gate hands over no planes (`WAFFLE_PLANES` selects the others for a
measurement), and the rung's cases are the fine-pitch exits and the plane layers. Measurement.

**D82. Time alone does not close `pico-ice-rev3`: the plateau** (2026-09-25, `_run_rung_scratch.py pico-ice-rev3
none 30 4200`, no planes in the DSN). Thirty passes in 67 minutes, about two minutes each; the router's own
count after each pass 27, 27, 34, 32, 32, 27, 27, 33, 31, 39, 27, 27, 33, 23, 31, 23, 23, 25, 26, 28, 23, 23,
24, 21, 22, 21, 21, 19, 29, 29, 19: a noisy drift from 30 to 19, never towards 0, with the same 13 standing
violations throughout. Imported: 1679 tracks and 281 vias to the reference's 1689 and 189; after the repair
(5 left by its index, worst 0.126 mm) and the pours, 72 of 95 nets, 35 missing links, 3 clearances: the same
72 the four-pass run reached. Two nets the reference pours, +3V3 and +1V1, come out in four pieces each: the
pours are laid over the router's tracks on In1 and In2 and the tracks cut them, which is what class B's
plane-integrity criterion is for. So the rung is not a budget question; the fine-pitch exits and the plane
layers are its cases (D81). Measurement.

**D83. The escape stubs do not help `pico-ice-rev3` either** (2026-09-25, `scripts/rung.py pico-ice-rev3 none 4
900 stubs`). `freerouting.escape_stubs` lays 19 stubs on the board (the rows whose corridor is under 0.02 mm);
with them the router leaves 69, 55, 46, 42 unrouted after passes 1 to 4 against 56, 57, 43, 47 without, with
25 standing violations against 13; imported and re-laid (a fixed wire does not come back in the session, D57):
65 of 95 nets, 43 missing links, 8 electrical (4 clearances, a short, 3 tracks crossing the re-laid stubs). The
class A finding (D57) holds on class B: the stubs stay off. What the rung has left, in order: the plane
layers kept for the planes (D82), the 13 standing violations every run reports from its first pass (conflicts
among fixed items under the router's rules, to be named), and threads. Measurement.

**D84. Class B's first rung is `upduino-v3.01`; `pico-ice-rev3` is second** (owner, 2026-09-25). The ladder's
order (D75) put pico-ice first as the class's most representative board; measured, upduino is the class's
simplest routing problem: pico-ice without the RP2040 (91 nets to 97, 363 netted pads to 423, 106 pads at
0.5 mm pitch or finer to 143, no 0.4 mm part against 66 pads, GND on In1 and +3V3 on In2 against a split In2).
Class B's two smallest boards, `fomu-pvt` and `sensor-watch-c1`, are its two hardest fine-pitch cases (4.0 and
9.3 mm² a net). At the class A configuration under the four-pass budget (`scripts/rung.py upduino-v3.01 none 4
900`): 270 items handed over, 52, 29, 27, 14 unrouted after passes 1 to 4 (pico-ice 313; 56, 57, 43, 47), 76
of 86 nets, 10 open (GND and +3V3 in two pieces each, 8 signals with 7 pads of U2 untouched), 0 violations
after the repair (pico-ice 3 to 9), 288 s the row (pico-ice about 15 minutes). The rest of the order and the
milestone (all nine) are unchanged. Owner's decision on the measurement.

## BGA escape (the class B+ machinery; passes its gate)

**D13. How the references escape their bus balls** (`bench/fanout_measure.py`). Dog-bone vias sit in the
diagonal gap and the outer one or two rings leave on the top layer without a via, on every board; via-in-pad is
one board's choice (ButterStick); empty positions (a DRAM's middle rows, a depopulated csBGA) are used; escapes
leave on several sides. Width and via size differ per package on one board (OrangeCrab: 0.089 mm tracks and
0.28 mm vias at its 0.5 mm FPGA, 0.105 and 0.3 at its DRAM). Measurement, 2026-09-17.

**D14. `ZONE_FILLER.Fill` hangs on OrangeCrab's top-layer zones** and cannot be interrupted from Python, so
`kicad/refill.py` fills in a child process: all zones, then per layer, then per zone. Measurement, 2026-09-17.

**D15. The escape is a lattice router with negotiated congestion (PathFinder), not a recipe.** The salvaged
recipe stopped at 154 of 155 and 116 of 128 balls. Dropped with numbers in the archive: deepest-first order,
a shared edge-clearance cache (shorts), duplicate resources (no convergence), hard site assignment by matching,
re-routing every ball in the final pass. Measurement, 2026-09-17.

**D19. 0.5 mm pitch stays in scope; the tool is fixed, not the criteria.** Owner, 2026-09-18.

**D20. Inner layers on a quarter-pitch grid, conflicts judged per ball on an eighth-pitch grid, partners ripped
up when the contested set stops shrinking, final pass under the exact collision test.** Gate `m2` (now
`escape`): 9 of 9 cases, 461 of 461 bus balls, zero violations. Measurement, 2026-09-18.

**D36. An escape computed before the bus is not the bus's escape.** On the class C boards 50 to 65 % of the
balls the escape gate certifies are never requested by the bus router, because which via site a ball takes
fixes the order its lane leaves the package. The escape gate therefore stands for packages with no
length-matched bus behind them (class B+); for a bus package the escape is an output of the bus plan.
Measurement, 2026-09-19.

## DDR3 bus (class C; parked by D55)

**D11. Bus facts.** OrangeCrab: 50 nets, csBGA285 at 0.5 mm to one FBGA-96, 6 layers, 15 to 29 mm. ULX3S:
SDRAM, 39 nets, 4 layers, 27 nets on the top layer only. Measurement, 2026-09-17.

**D22. The bus router routes each memory from its bare pads**, because a dog-bone via in every gap of a DRAM's
array leaves no inner-layer channel for a bus that passes through it: our fan-out put 24 vias between
ButterStick's memory balls where the reference puts one and used 3 hollow sites where it uses 72. The
contested-net count originally quoted here was measured inside D33's stall and proves nothing; the geometry
stands. Measurement, 2026-09-18 and 2026-09-19.

**D23. Length is made by meanders inside the DRAM area, not by detours through free board.** ButterStick keeps
its 55-net bus (29.5 to 43.6 mm) inside the two DRAM footprints plus a millimetre or two; detours through free
board fired late and walled nets in. Measurement, 2026-09-18.

**D27. The length criterion is the matching the references achieve, per group**: each data lane within the
reference's own lane spread on total length (ButterStick 0.73 and 0.84 mm; LogicBone 4.15 and 7.1), each pair
within 0.2 mm, address/command/clock within the reference's spread at each memory's pins (ButterStick 11.9 and
7.5 mm; LogicBone 6.6 and 6.1). Absolute length is free. Owner, 2026-09-19. Subject to D30.

**D29. A capacity-only planner plans layers and capacity but not order**; the crossings are the bundles' own
twist (34 inversions of 55 in ButterStick's lane 0). `route/plan.py` is that cell planner, kept for the replay
and comparison scripts. Measurement, 2026-09-19.

**D30. Open: the class C length criterion.** Either D27 (the references' own spreads, which they pass by
definition) or the silicon vendor's rule for the part (Lattice FPGA-TN-02038: ±50 mil DQ to DQS, ±10 mil per
pair, ±100 mil address/command to CK, length only, no picoseconds and no DQS-to-CK rule). Measured (D45, D47,
D48): every class C reference is outside Lattice's address-and-command window at every memory, on total length,
per leg, and as delay alike. Byte lanes: LogicBone matched its lanes in delay and OrangeCrab in length, so no
single unit grades all three answer keys the same way. Decided when class C starts, not before.

**D31/D32. What both references obey inside a ball array**: a via sits on a ball or on a corner between four,
never in the channel between two (0 of 154 reference array vias; ours put 8 and 6 there); each package keeps to
one escape style; the reference uses at most 3 (ButterStick) or 4 (LogicBone) vias per net. "No via between
balls, ever" and "the top layer carries escapes only" were ButterStick-only and LogicBone refutes both (89
corner vias, 170 mm of top-layer transit). ButterStick's hollow cells are a permutation network allocated by
lane order, not first come. Measurement, 2026-09-19.

**D39. The bus plan is crossing-free by construction**: one grid per layer whose lines are every package's own
half pitch (a ball, a corner and a channel are all nodes), node-disjoint paths on a monotone grid cannot cross,
via sites are columns held by one net, and a layer carrying fewer than 20 non-bus nets is a plane the bus does
not cut (separates cleanly on all three boards). After round one only the nets in conflict are re-routed.
Measurement, 2026-09-20.

**D40. A deficit is measured against the group's spread (D27), not its longest net; room is the serpentine a
run's held amplitude affords, `l*(sqrt(1+4a^2)-1)`**, and only room the net holds alone counts. Congestion cost
capped at 15 mm, wander at 1.5x plus 4 mm, a via costs 8 mm. Measurement, 2026-09-20.

**D41. A repair may not make a new conflict, and a plan must make its lengths, not only reserve room for them.**
Repairs route on free nodes only (monotone); a net below its group is grown in place by writing the serpentine
into the plan. Lesson: a criterion two knobs can trade against each other has a missing mechanism. Gate `m3a`
(now `busplan`): 3 of 3 class C references. Measurement, 2026-09-20.

**D42. The fab demands of a BGA follow from pitch and pad, before routing**: one track through the channel is
`(pitch - pad)/3` (OrangeCrab's 0.089 mm is exactly that at 0.5 mm; 0.8 mm gives 0.133), and the via that fits
between four balls is standard-tier at 0.8 mm and not at 0.5 mm. Via-in-pad and 0.089 mm tracks on ButterStick
are choices, not the part's. Every DDR3 reference runs its bus under 0.1 mm spacing somewhere. Measurement,
2026-09-20.

**D45. Vendor rules verified from primary text**: Lattice (above); ISSI ±10 ps DQ to DQS, ±5 ps CK to DQS,
point-to-point, subordinate to the controller vendor; TI KeyStone ±20 mil address to CK measured controller to
each SDRAM separately. No vendor ties a tolerance to a data rate. `research/ddr3-bus-routing.md` had blended
ISSI's picoseconds into Lattice's rules; corrected in place. Measurement, 2026-09-21.

**D47/D48. Per leg against the signal each rule names, in copper and as delay** (`scripts/segment_lengths.py`,
`bench/delay.py`): address/command is outside Lattice's 2.54 mm at all five memories in every unit; OrangeCrab's
lane 0 runs its bits on `B.Cu` and its strobe on `In2.Cu`, 27 ps of skew at matched copper. Measurement,
2026-09-21.

**D54. The delay model is length times one of two constants** (5.59 ps/mm outer, 7.08 inner at er 4.5; no
width, no dielectric height; a real stackup on ButterStick only) and is not a tolerance. The constraint every
vendor states removes the need for one: all nets of a matched group on one layer, then matching length is
matching delay. Report modelled delay beside a result, never as its criterion. Measurement, 2026-09-21.

## Dropped from this log

Full text in the archive. D16 (PCBWay tier applied to references; superseded by D53). D21 (M3 start; procedural).
D24 (bus repair by local negotiation; parked code). D26 (owner's direction to read the references first; now the
working agreement). D28 (replay numbers measured inside D33's stall). D34 (a review). D35 (class C order; in
D38). D37 (the proposal D38 accepted). D44 and D46 (the failed research rounds; the rule is in D53 and
CLAUDE.md). The remainder of D49 (M4 before M3b) and D51/D52's router-specific detail (superseded by D55).
