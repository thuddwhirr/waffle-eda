# Project brief: an FPGA-board routing toolkit, tested against real boards

This document starts a new project. It is written for the next AI coding session and for the person directing it,
and it carries everything learned in the `waffle-fpga` repository (branch `claude/ecstatic-feynman-0oiyyn`, 152
commits, decisions D1 to D59) that the new project needs in order to begin well. Read it in full before doing anything.

## 1. The goal, in the owner's words

Use an AI coding agent to design a modern, high-speed FPGA board without the owner doing any hand routing. Copying a
reference board's copper is a failure: it produces a board but no general skill or tooling. The new project is
therefore a **tooling project**: build and test the tools on example boards that are known to work, until they are
good enough to produce a simplified version of the board originally specified, end to end, from schematic to a
fab-ready layout that passes DRC and the high-speed rules.

## 2. The original board and its simplified target

The original specification (`waffle-fpga`): Lattice ECP5 LFE5U-85F in caBGA381 (0.8 mm pitch), one DDR3L x16
(Micron MT41K512M16, FBGA-96), HDMI out, USB hub and ULPI PHY, an STM32H743 with FMC to the FPGA, an ESP32-C6, audio
codec, PMODs and a 2x20 expansion, eight layers, PCBWay standard capability, Eurocard 100 x 160 mm.

The simplified target for this project should keep exactly the parts that exercise the tooling and drop the rest:

* ECP5 caBGA381 with its configuration flash, JTAG/USB programming, and the four supply rails (1.1 V core, 1.35 V for
  the DDR3 banks, 2.5 V auxiliary, 3.3 V I/O).
* One DDR3L x16 in FBGA-96 (or two x8 in FBGA-78; see the references). This is the hard part and the point.
* One other high-speed interface with differential pairs, HDMI or USB, so the flow handles pairs as well as a bus.
* Power entry, decoupling, a few LEDs and a PMOD. Six or eight layers; whichever the impedance targets need.

Everything else from the original (STM32, ESP32, codec, hub) can come back later if the tooling proves out. Board
size should follow the parts, not a standard; the original's Eurocard size made no difference to the hard problem.

## 3. What happened last time, and why

The previous project got a complete schematic, a verified netlist, a generated placement, a fan-out generator, plane
repairs and two routing stages, but never a finished DDR3 bus. The chronology matters less than the causes:

1. **Standard practices were discovered after the fact.** Power balls served last, signal tracks on the power plane,
   a 3.3 V rail with no continuous copper, decoupling 25 mm from its balls, ground fills that vanished under the BGA
   via grid. Each was found while patching its consequences. `hw/layout-practices.md` in the old repo lists 18
   practices with before/after; read it first and hold the new tools to it from the start.
2. **Constraints were invented that the references do not have.** A 12 mm empty corridor between DRAM and FPGA
   (references use 3 mm or 20 mm with no keep-out), 0.20 mm spacing everywhere (references run 0.13 to 0.20), no
   vias in the open (a consequence of the corridor), strict same-order lines per layer, power balls exiting toward the
   bus. Every router version failed against constraints of our own making.
3. **No test oracle and a slow iteration cycle.** Every tool was tested only on the target board, where a failure
   could not be told apart from an impossible geometry, and a cycle took 5 to 20 minutes. Two working reference
   boards sat unmeasured for most of the project. This is the failure to fix first.
4. **The general-purpose autorouter (Freerouting 1.9) is not a bus router.** It was used for lack of anything else,
   behaved chaotically (5 versus 33 open nets from tiny input changes), cannot fix wires (any fixed wire freezes all)
   and needed pinless-net tricks to stage. Good for the miscellaneous nets, useless for the bus.
5. **Placement was treated as fixed.** The owner never said so; the agent assumed it. Where the DRAM sits relative to
   its bank is a design rule the tool should state and apply.

What worked and should be carried over: the practices audit, the deterministic fan-out generator (every ball owns a
diagonal gap, power balls first and unconditionally), the plane-via and fill-repair tools with their gates, the
z3-based layer/exit-row plan, the negotiated-congestion lattice router (correct in structure, weak in convergence),
straight corridor lines checked against real copper, length tuning by meanders, per-stage DRC and route reports.

## 4. The reference boards, measured

Both are open hardware for the same FPGA package. Fetch them by script at project start; do not commit their files
(CERN OHL licences; keep attribution in the fetch script). Load with KiCad 9's `pcbnew` Python (LogicBone is a KiCad 5
file and loads with a legacy-zone warning).

**ButterStick** (Greg Davill, github.com/butterstick-fpga/butterstick-hw): ECP5UM5G-85 caBGA381, two DDR3L x16
FBGA-96 (dual rank), 8 layers.

* DRAM U11 at FPGA centre + (16.7, −4.0) mm, rotated 90 degrees, same side, 3 mm between the ball arrays; U12 at
  (16.7, +7.4). DDR3 on FPGA columns 16 to 20 (banks 2/3), rows C to U.
* FPGA balls per signal: A0=G16 A1=E19 A2=E20 A3=F16 A4=F19 A5=E16 A6=F17 A7=L20 A8=M20 A9=E18 A10=G18 A11=D18
  A12=H18 A13=C18 A14=D17 A15=G20 BA0=H16 BA1=F20 BA2=H20 CAS=J17 RAS=K18 WE=G19 CS0=J20 CKE0=F18 ODT0=K20 RST=E17
  CK0_P=C20 CK0_N=D19 DQ0=U19 DQ1=T18 DQ2=U18 DQ3=R20 DQ4=P18 DQ5=P19 DQ6=P20 DQ7=N20 LDM=U20 LDQS_P=T19 LDQS_N=R18
  DQ8=L19 DQ9=L17 DQ10=L16 DQ11=R16 DQ12=N18 DQ13=R17 DQ14=N17 DQ15=P17 UDM=L18 UDQS_P=N16 UDQS_N=M17.
* Bus copper: 0.12 mm tracks (some 0.089), gaps to the nearest same-layer neighbour 0.13 to 0.20 mm, most 0.16 to
  0.18. Every data net has exactly three vias, address nets two or three, and none outside the BGA footprints: layer
  changes happen at the dog-bone vias under the packages, and lines are re-ordered on the ball lattice there. Layers
  In2, In5, B.Cu plus F.Cu near the packages.
* FPGA-side vias are in the pads (333 of 386 under the FPGA), 0.4 or 0.45 mm on a 0.2 mm drill, which needs the fab's
  filled-and-capped option. DRAM side is a mix of in-pad and gap vias.

**LogicBone** (github.com/oskirby/logicbone): ECP5UM-85 caBGA381, two DDR3 x8 TFBGA-78 side by side, 8 layers.

* FPGA rotated 90, DRAMs at FPGA centre + (±5, +20.6) mm, rotation 0. DDR3 on FPGA columns 1 to 5 (banks 6/7).
* Dog-bone fan-out with standard 0.5/0.2 mm through vias in the diagonal gaps, 0.30 mm BGA pads (ours were 0.40).
  106 bus vias, 103 inside the BGA footprints; 16 of 51 bus nets have no via at all (top layer end to end). Tracks
  0.135 and 0.15 mm. Layers F.Cu (heavily), Sig1, Sig2, B.Cu.

Take from the two together: short bus lines, spacing near one width, layer changes only at the packages, ordering on
the lattice, power balls away from the bus, and the fan-out via style that matches a standard fab (LogicBone) versus
via-in-pad (ButterStick). Both boards passed the same physics; the tool must be able to reproduce either.

## 5. What the toolkit is

A pipeline of small, testable tools, each with a gate, driven by scripts and KiCad 9's CLI and Python API:

1. **Placement rules**: where a BGA's bus partner goes (distance, rotation, side), decoupling at its balls, a
   parts-free band only where a rule says so. Output: anchor positions the generator honours.
2. **Pin assignment**: bus signals assigned in ball order to make the bus crossing-free, differential pairs on true
   pads, DDR3 groups within DQS groups, validated against the device database (prjtrellis) as before. Include the
   case of a pair whose balls sit in opposite order at the two chips (swap the pins, invert in the FPGA).
3. **Fan-out**: every ball owns a diagonal gap; power balls first, dog-boned toward their nearest edge; outer rings
   on the top layer; inner rings on inner layers between the via rows; commit each escape only if it clears existing
   copper; gate: no ball without a connection. Optional via-in-pad mode.
4. **Bus router**: for each bus net, a dog-bone via at each end, a lattice path under each package to an exit row,
   and a straight or gently bent line between. A global assignment of layer and exit rows (SAT/CP), a
   negotiated-congestion lattice router with real-copper obstacles, and feedback between them. Then length matching.
5. **Miscellaneous routing**: an autorouter for the rest, with the bus and pairs fixed. Accept Freerouting's limits
   or replace it; either way it is not the bus router.
6. **Planes and power**: rails on continuous copper with feeds, fills at the fab minimum under BGAs, plane vias for
   every plane-net pad, a fill-piece report per rail.
7. **Checks**: DRC at every stage, a bus report (length per net against its strobe or clock, via counts, layers),
   connectivity gates. Nothing advances on an assumption the previous stage did not verify.

## 6. The benchmark, before any routing code

Build the test harness first and keep it fast:

* **Reference reproduction.** For each reference board: strip only the DDR3 nets' copper, keep everything else as
  obstacles, run the toolkit's fan-out and bus router, and score: nets connected, DRC clean under the board's own
  rules, lengths within the board's measured spread, vias inside the packages, layers used. The original copper is
  the answer key; compare per net. A run must take seconds to a minute.
* **Synthetic cases.** Small artificial BGA pairs (6 x 6, 9 x 16, 20 x 20 with a bus in one bank) with known
  feasibility, for the lattice router and the assignment solver alone, run as unit tests on every change.
* **Rules.** Never test a change only on the target board. A failure on the target board is not a result until the
  same tool passes the references. Record every constraint the tool imposes and check it against the references
  before keeping it.

Acceptance for the toolkit: passes both references; then produces the simplified board with no hand routing.

## 7. Environment and tool facts worth knowing

* KiCad 9: `kicad-cli pcb drc --severity-all --format json`, `kicad-cli pcb export`, `kicad-cli pcb render`;
  `pcbnew` from Python (`LoadBoard`, `SaveBoard`, `ZONE_FILLER(b).Fill(b.Zones())`). Zone fills are not updated
  automatically: refill before DRC or the vias read as clearance errors. A freshly generated board has no fills.
* `pcbnew` pitfalls: reshaping a zone's outline in place leaves the filler with stale data (replace the zone by a
  new object); `GetFilledPolysList` references can dangle (copy the polygon set); connectivity queries are unreliable
  across calls (keep your own union-find); footprint parents need casting; `m_Uuid.AsString()` for identity.
* z3 (`pip install z3-solver`) solves the layer/exit-row plan in seconds when it is a plain satisfiability check;
  the optimiser with soft constraints times out on the same model.
* Freerouting 1.9: DSN in, SES out; mark plane layers `(type power)`; a `(type fix)` wire freezes every wire; strip
  pins of nets that must not be routed; results vary chaotically with tiny input changes.
* PCBWay standard 8-layer: 0.10 mm track and clearance, 0.45/0.20 mm vias, 0.2 mm hole clearance; via-in-pad and
  filled vias are options. Impedance geometry per layer was derived in `hw/tools/impedance.py`.
* Process pitfalls that cost hours: `pkill -f` with a pattern that also matches the calling shell kills the session's
  own command; background jobs need detaching (`nohup setsid`) and unbuffered Python (`-u`) or their output never
  appears; a 10 minute tool timeout does not stop a routing run, so watch logs instead.

## 8. Code to salvage from `waffle-fpga`

All under `hw/tools/` on branch `claude/ecstatic-feynman-0oiyyn`:

| file | keep as | note |
|---|---|---|
| `gen_pcb.py` | placement generator, islands, stack-up, project rules | anchors, attractor placement, feed strips, 1V35 patch |
| `bga_escape.py` | fan-out | standard policy, `SKIP_NETS`, `ONLY_OPEN`, copper-aware commit |
| `fix_open_pads.py` | plane vias + gate | own connectivity, fills first, keep-outs |
| `fix_pwr_fill.py` | fill repair + report | pieces per rail |
| `ddr_bus.py` | bus router skeleton | z3 plan + negotiated lattice + corridor lines; converges one layer per run |
| `ddr_plan.py`, `ddr_swap.py`, `ddr_corridor.py` | reference only | earlier attempts, documented in D57/D59 |
| `export_dsn.py`, `merge_ses_nets.py`, `staged_route.sh`, `rip_nets.py` | autorouter staging | PWR as plane, pinless nets |
| `ddr3_tune.py`, `route_report.py`, `stitch_vias.py`, `widen.py`, `power_widen.py`, `drc_cleanup.py` | finishing and checks | |
| `pinmap/gen_pinmap.py` + `pinmap/db/` | pin assignment validation | prjtrellis database |

Documents to carry: `hw/layout-practices.md` (the audit), `ddr3-routing-guide.md` (rules in plain language),
`decisions.md` D51 to D59 (what was tried and why it failed), `stackup.md`, `power-tree.md`.

## 9. Working agreement for the new session

* Measure the references before designing anything; state every rule with the reference evidence beside it.
* Build the benchmark before the router. Keep runs under a minute. Add a synthetic test with every new constraint.
* Every stage has a gate that checks what the next stage assumes. A gate that fails stops the pipeline.
* Keep a decisions log. Record what was tried, the numbers, and why it was dropped, so nothing is tried twice.
* Report honestly and briefly: numbers per stage, what is open, what is next. Do not narrate iterations.
* When a tool fails three times on the same problem, stop and find the constraint or the missing test, do not
  brute-force. Ask the owner before a pivot that changes the design (memory configuration, fab options, placement).
* Placement, pinout and fab options are all in scope for the tool to change. Nothing about the target board is fixed
  except the owner's stated goal.

## 10. First milestones

* **M0**: repo skeleton, fetch script for the two references, KiCad 9 and z3 verified, the salvaged tools imported
  and importable, this brief and the practices list at the root.
* **M1**: benchmark harness with scoring, reference boards loading, their bus stripped and re-scored against their
  own copper (a run of the "do nothing" tool scores zero; the original copper scores full marks).
* **M2**: fan-out tool passes on both references (every ball escaped, DRC clean), synthetic tests in place.
* **M3**: bus router passes ButterStick (50 nets, DRC clean, lengths within spread), then LogicBone.
* **M4**: the simplified target board: schematic, placement by rule, fan-out, bus, pairs, the rest, planes, fab
  outputs; no hand routing.

## 11. Questions for the owner at the start of the new session

1. Memory configuration for the simplified board: one x16 in FBGA-96 (as ButterStick) or two x8 in TFBGA-78 (as
   LogicBone)? The tool should handle both eventually; the first target needs one.
2. Via-in-pad allowed as a fab option, or standard dog-bones only? This decides which reference the fan-out mode
   must match first.
3. Fab and layer count for the simplified board (PCBWay 6 or 8 layers), so the rules and impedance geometry are fixed
   before routing.
4. The one other high-speed interface to keep (HDMI or USB).
