# waffle-eda: project definition

Agreed with the owner on 2026-09-17 (session 1). Changes to anything here go through `decisions.md`.

## 1. Purpose

A Claude Code driven tool suite that takes a feature proposal to manufacturable design files. It is a general-purpose
tool, not a board. The FPGA board from the `waffle-fpga` project (an ECP5 caBGA381 with a DDR3 bus) is the hardest
benchmark the tool must eventually pass, and the reason the tool exists, but it is not the deliverable.

The owner's own statement of the goal is in `../README.md`.

## 2. The pipeline

Six stages. Each has an input, an output and a gate. A gate checks what the next stage assumes; a failing gate stops
the pipeline with a report. Nothing advances on an assumption the previous stage did not verify.

| # | Stage | Input | Output | Gate |
|---|---|---|---|---|
| 1 | Design document | the owner's feature description, cost ceiling, fab and assembler choice | capabilities, interfaces, port and edge positions, size limits, the **locked set** (section 4) | owner review; every locked constraint explicit; every interface has a stated position or is marked free |
| 2 | BOM | design document, cost ceiling, fab/assembler | parts list with manufacturer part numbers, alternates, price, stock, symbol and footprint source | cost within ceiling; every part has a symbol, a footprint and a datasheet reference; long-lead parts flagged |
| 3 | Schematic | BOM, design document | a KiCad schematic a human EE can read and review, and its netlist | ERC clean; netlist matches the design's connectivity specification one to one; sheets grouped by function, not netlist style |
| 4 | PCB specification | design document, BOM, fab profile | layer count, stack-up, impedance geometry, via types, design rules, outline, price estimate | every rule within the fab's capability; every impedance target covered; price within ceiling |
| 5 | Layout: placement, routing, checks | specification, netlist, footprints | a routed board, DRC clean, bus and pair reports | the acceptance rule in section 3 |
| 6 | Manufacturing outputs | routed board, BOM | gerbers, drill, pick-and-place, BOM in the vendor's template, assembly drawing, impedance and stack-up note | the vendor's checklist satisfied; every file re-parsed after export |

## 3. The routing acceptance rule

A run of stage 5 ends in exactly one of two states.

1. **Complete.** Every net routed. DRC clean under the fab profile's rules. Every bus and pair rule met: length
   against strobe or clock, pair skew and gap, layers, via count.
2. **Failed, with a report** that names the constraint that could not be met, the evidence, and the design changes
   that would resolve it.

A partially routed board with a list of nets for a human to finish in KiCad's interactive router is **not a valid
outcome**. That is how `waffle-fpga` ended three times (its decisions D51, D54 and D57), and it is what this project
exists to prevent. Consequences:

* Failure is diagnosed, not counted. "17 nets open" is a symptom. The report says: congestion on this row, no via
  site for this ball, this pair's balls sit in opposite order at the two chips, this length cannot be met on this path.
* Runs are bounded. A router that has not converged within its budget stops and reports rather than running for hours.
* The interactive router is never part of the flow. The owner reviews outputs and decides revisions. The owner does
  not draw copper.

## 4. Free variables and locked constraints

Every design has two kinds of parameters.

**Free variables.** The tool explores these on its own, within a budget, and logs every attempt and its result so
nothing is tried twice:

* part placement, rotation and side;
* pin assignment within what the parts allow (DDR3 bit and lane swaps, FPGA pin choice validated against the device
  database, connector pin order where the standard allows);
* layer count and stack-up;
* via type: through, via-in-pad, filled and capped, and later blind or buried;
* track width and spacing within the fab's capability;
* board size within the maximum;
* any other option the fab offers.

**Locked constraints.** Only the owner changes these:

* the maximum board size;
* the cost ceiling for board, assembly and parts;
* the agreed interface positions (which edge a connector sits on and where), as recorded in the design document;
* the feature set.

**Escalation.** The tool asks the owner only when the best solution it found requires crossing a locked constraint.
By then it has exhausted the free space, so the question comes with evidence and options, never a symptom: what was
tried (from the log), the options with their cost, and a recommendation. For example: "the board routes with HDMI on
the left edge; keeping it on the back needs ten layers at a stated amount over the ceiling, or dropping one PMOD."

**Cost is a number.** Each fab profile carries a price model (layer count, area, via type, finish, quantity). Until
real quotes are captured, the price is recorded as unknown and any decision that depends on it escalates.

## 5. Working agreement

Adapted from the `waffle-fpga` brief, section 9, and kept.

* Measure reference boards before designing a rule. State every rule with its evidence beside it.
* Build the benchmark before the tool. Keep runs under a minute where possible. Add a synthetic test with every new
  constraint.
* Never test a tool only on the target board. A tool must pass the reference boards of every class it claims to handle.
  A failure on the target board is not a result until the same tool passes the references.
* Record every constraint a tool imposes and check it against the references before keeping it. The last project
  failed against constraints of its own invention.
* Keep the decisions log: what was tried, the numbers, why it was dropped.
* Every recorded result names the configuration that produced it: the commit, the environment overrides and the
  resolved settings the tool ran with. A result without that provenance is not quotable in the plan. Any bench
  parameter that changes a result is measured before it is set, never assumed (D33: a spacing chosen by
  assumption made every net contested by construction and invalidated every routing measurement taken under it).
* One class of board at a time, the whole pipeline for that class, every lower class kept green (D55). Each stage
  uses the cheapest existing tool that passes the class; own code is written where a measurement shows the
  baseline fails, and a stage is never re-architected because of one board.
* When a tool fails three times on the same problem, stop and find the missing constraint or the missing test. Do not
  brute-force. A class not passed after four sessions gets a written review, not a fifth iteration.
* Facts from outside the repository come from the owner or are marked unknown. No research rounds against the
  network (D53: two rounds ran for hours against domains the egress policy had already refused).
* Report briefly: numbers per stage, what is open, what is next. Do not narrate iterations.
* Ask the owner only for locked-constraint changes and design revisions.

## 6. Non-goals, for now

* Flex and rigid-flex, RF layout, more than eight layers, HDI blind and buried vias. These become fab options later.
* Signal and power integrity simulation beyond closed-form impedance and the length and spacing rules.
* Firmware and gateware for the boards produced.
* A user interface. That is a separate project that consumes this one's files, renders and reports (D55).

## 7. Interface

The tool is driven from Claude Code and speaks in files. A design is a directory, one file per stage, so every
stage's output is something a person can open in an editor or in KiCad; every gate produces a render and a
report; a status command says where a design is and what it waits on. The owner's input is an edit to one of
those files (a locked constraint, a vetoed part), never a drag or a drawn track: under section 3 there is nothing
to manipulate, only to review. The directory layout is in `plan.md`, "Interface".
