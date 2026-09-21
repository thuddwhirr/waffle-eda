# Automated routing of a DDR3 bus on a small FPGA board: what the field says

Research report for waffle-eda, 2026-09-19. Sources are linked where they were read; where the egress proxy blocked
a primary document (AMD, Intel, arXiv, ACM, researchgate, the Lattice checklist mirror) the numbers come from search
excerpts of that document and are marked "(excerpt)". Two vendor notes were read in full: TI's KeyStone DDR3 design
requirements (SPRABI1D, 2022) and ISSI's DDR3 SDRAM layout guidelines. Conversions use FR4 propagation of about
5.6 ps/mm for microstrip (140 to 150 ps/in) and 6.7 ps/mm for stripline (170 ps/in); the rule of thumb is 6 mils per
picosecond. (The tool now derives both from one formula and the board's own permittivity rather than quoting two
rules of thumb, which keeps 5.59 for microstrip and puts stripline at 7.08: D48, `waffle_eda/bench/delay.py`.) A companion deep-research run (verified, multi-agent) is appended when it completes.

## Summary: the three answers

**1. Length criteria for the benchmark, per signal group.**

> **Corrected 2026-09-21 (D45).** The sentence that stood here said the Lattice rules "agree with ISSI's
> memory-side guidance" and the table blended the two without attribution. A verified round reading the primary
> PDF in full established that they do not agree in kind: **Lattice's checklist is length-only, in mils, with no
> picosecond figure anywhere in its 36 pages and no strobe-to-clock tolerance at all.** Every picosecond number
> below is ISSI's or TI's, never Lattice's. The rows are re-attributed accordingly. ISSI's own text calls its
> figures a simulation-confirmable baseline subordinate to the controller vendor's rules and scopes them to
> point-to-point; TI's are KeyStone-PHY specific and must not be transplanted to an ECP5.

> **Measured 2026-09-21 (D48).** The "references measured" column below is copper length, which this report
> already warned is a proxy ("the tool should measure delay per layer", section 2). It has now been measured as
> delay, per leg, in `scripts/segment_lengths.py`. The byte-lane row is the one that moves: OrangeCrab's 0.5 and
> 0.6 mm become 27.2 and 25.2 ps, the furthest outside ISSI's ±10 ps of any board, while LogicBone's lane 0 at
> IC2 becomes 4.3 ps and is the only lane of any reference that meets the rule. The prediction made below about
> LogicBone's strobes is confirmed from the board; what was not predicted is that OrangeCrab has the opposite
> defect. The address-and-command row does not move: every reference is outside in every unit. Read that row's
> figures as copper length, and D48 for the same legs as delay.

| group | Lattice ECP5 (FPGA-TN-02038-2.1 §9, length only) | memory/other vendor | in mm | references measured |
| --- | --- | --- | --- | --- |
| DQ and DM to their DQS, one byte lane | **±50 mil** (§9.2) | ±10 ps (ISSI) | window 2.54 mm | ButterStick 0.73 and 0.84; OrangeCrab 0.5 and 0.6; LogicBone 4.15 and 7.1 |
| DQS pair (P to N) | **±10 mil** (§9.7) | ±2 ps (ISSI) | 0.51 mm | 0.00 to 0.15 mm |
| CK pair | **±10 mil** (§9.11) | — | 0.51 mm | 0.00 to 0.15 mm |
| byte lane to byte lane (LDQS to UDQS) | **±100 mil** (§9.9) | — | 5.08 mm | about 2 mm on both boards |
| CK to each DQS | **no rule at all** | ±5 ps (ISSI) | ±0.75 mm | ButterStick 2.3 mm |
| address, command, control to CK | **±100 mil** (§9.10) | ±10 ps (ISSI), ±8 ps (Xilinx, excerpt), ±20 mil per segment (TI) | 5.08 mm (Lattice) | OrangeCrab 6.7, ButterStick 8.0, LogicBone 11.4 on total net length |
| stubs on fly-by nets | — | under 80 mil address, 40 mil clock; stub skew ±10 mil (TI) | 2.0 and 1.0 mm | not measured |
| vias per data net | — | at most 2 (TI), same count within a lane | | ButterStick 3, LogicBone 0 |

Two things the corrected table makes visible. **Lattice attaches no data rate, clock frequency or speed grade to
any of these**, so there is no DDR3-800-versus-1600 scaling to read off it; and its section heading is "LPDDR3 and
DDR3", so the numbers are not DDR3-specific. **Lattice does not say whether its tolerance is on total net length
or per segment**, and TI, the only vendor that states the convention unambiguously, measures address and command
from the controller to each SDRAM separately. On total net length, all three class C references exceed Lattice's
±100 mil address and command rule -- boards that were manufactured and work -- which is evidence that the
convention matters more than the number.

The lane, pair and lane-to-lane rows are what D27 already asks, restated in the vendor's numbers; the tool should
measure delay per layer (done, D48: `waffle_eda/bench/delay.py`, and it changes the lane row's verdict on two of
the three references). The CK-to-DQS and address-to-CK rows are where the references are far outside every
published rule (see the contradictions below); the benchmark should carry the published number and record the
references' actual figures as a known deviation, not adopt them.

**2. Router architecture.** Build the four-stage pipeline the PCB routing literature settled on, with length treated
as an area budget before detailed routing, and negotiation confined to the last stage:

1. *Rules and groups* from the memory and FPGA vendor tables (above), the board stack-up (per-layer velocity) and
   the netlist (byte lanes, pairs, fly-by or T topology). Everything downstream is judged in picoseconds.
2. *Escape planning*, both packages at once, as ordered escape routing: choose for every ball its exit side, the via
   site (dog-bone in the array, in the package's empty centre rows, or in the pad) and the layer it comes out on,
   so that the two ends of each net leave in compatible order and on the same layer. Network-flow or ILP
   formulations exist and are small at this size (55 nets); the memory's empty centre is a routing lane, as TI's
   BGA escape notes describe ("positioning vias where pads are not present creates a routing lane").
3. *Bus planning*: assign each lane (and the address group) to layers, order the nets within a layer so that they
   are planar between their two vias (no crossings on a layer; a crossing is resolved here by swapping layers or
   the escape order, never by a mid-route via), and assign each net a corridor whose area carries its length
   budget: minimum length from the group's longest member, maximum from the window, area from the meander
   geometry rules. This is Kong, Yan and Wong's bus planner combined with Ozdal and Wong's min-max length-matching
   by area assignment (BSG-Route, and the 2025 LP-based multilayer version).
4. *Detailed routing inside the corridors*, per layer: river-style routing of the planar bundle, meanders generated
   inside each net's assigned area with 3W to 5W spacing, then exact DRC. Negotiation (PathFinder) is useful here
   only for the residual, local conflicts; it is the wrong tool for layer assignment and for length.

Length room is reserved in stage 3 as area, not found afterwards by a tuner: that is the single biggest change from
the current tool, and it is what both reference boards' designers did by hand.

**3. Which structural choices the literature favours.** Escape: dog-bones for pitches of 0.5 mm and above and
via-in-pad below that (JLCPCB, Cadence, MacroFab guides), so both references' memory escapes are within practice;
escaping the memory's balls on the top layer into its empty centre and dropping the via there (ButterStick) is the
documented lane technique and yields the vendor-preferred structure, one via and one inner-layer run per net, or
none at all for a data net routed on the top layer (LogicBone, which also meets TI's "at most two vias" rule).
Meanders: the literature's length-matching routers put snaking in the channel between components (river routing
in a channel is the model in Ozdal and Wong's algorithm and in BSG-Route), which is LogicBone's practice; vendors
add spacing rules (TI: 5W centre-to-centre including serpentines, 4W below 1066 MT/s; ISSI: 8 mil within a net,
15 mil between groups). ButterStick's meanders inside the memory area at a 0.3 mm pitch are a fit to a board with no
channel (0.5 mm between packages), not a recommended practice. The tool should support both placements and prefer
the channel when one exists.

**Contradictions between the measured practice and the published guidance.**
- ButterStick's address and command group is 8 mm spread on total length and 11.9 mm at U11's pins, and its CK0 is
  2.3 mm from the DQS strobes at U11; every vendor rule is ±0.5 to ±1.3 mm (address to CK) and ±0.75 mm (CK to
  DQS). LogicBone's address group is 6 to 7 mm spread at each memory against TI's ±0.5 mm per segment. Both boards
  work because the controllers run far below DDR3-1600 and because write and read leveling absorb the address
  versus data flight difference, but the benchmark should not enshrine this.
- ButterStick's data nets carry three vias; TI allows at most two and forbids mid-route vias on data nets.
- ButterStick's meanders between the memory balls run at about 0.3 mm pitch with 0.09 to 0.12 mm tracks, under the
  5W (0.45 to 0.6 mm) and even the 3W spacing rules; ISSI's 20 mm total-length recommendation is also exceeded by
  every ButterStick net.
- LogicBone's strobes are 3.5 to 4 mm shorter in copper than their data bits, which looks like a violation of the
  ±10 ps lane rule until velocity is applied: 17.3 mm of top-layer microstrip is about 97 ps and 13.8 mm of
  stripline about 93 ps, within the rule. This is the strongest argument for judging delay, not length; TI states
  the same ("all length-matching is based on an equivalent stripline length").

## 1. DDR3 layout rules as practised

**JEDEC.** JESD79-3 specifies the timing at the DRAM, not board geometry: the write-leveling window tDQSS of
±0.25 tCK with tDSS and tDSH at 0.2 tCK, the fly-by topology for address, command, control and clock, and read and
write leveling as the mechanism that absorbs the different flight times to each DRAM ([JEDEC JESD79-3](https://www.jedec.org/standards-documents/docs/jesd-79-3d);
[Intel EMIF, write leveling tDQSS](https://www.intel.com/content/www/us/en/docs/programmable/683385/17-0/write-leveling-tdqss.html)).
Board rules are the vendors' translation of those windows into skew budgets.

**Texas Instruments, KeyStone DDR3 (SPRABI1D, read in full).** Data: all nets of a byte lane on one layer, same
via count, at most two vias, no mid-route vias, matched within ±10 mils; strobe pairs within ±1 mil. Address and
command fly-by: matched to the clock from the controller to each SDRAM separately within ±20 mils along the same
route, same via count per segment, stubs under 80 mils matched within ±10 mils. Clock pairs: matched to each SDRAM
within ±1 mil, stubs under 40 mils. Spacing: at least 5W centre-to-centre including serpentines (4W below
1066 MT/s), 6W to other signals, no plane splits under the routes. VTT terminations at the end of the net, each
trace to its termination within 500 mils, VTT tracking VDDQ/2 from a 1 % divider; Vref within ±1 %. All matching on
equivalent stripline length; long routes stripline, breakouts microstrip and short. Minimum four routing layers,
two for address and command and two for data ([TI SPRABI1](https://www.ti.com/lit/pdf/sprabi1)).

**ISSI DDR3 layout guidelines (read in full).** Byte group (DQS, DM, eight DQ) within ±10 ps or ±1.27 mm; CK and
DQS pairs within ±2 ps or 0.254 mm; CK to every DQS within ±5 ps; address and control to CK within ±10 ps; address
net, command net and byte group to byte group within ±50 ps or 6.6 mm; same layer for a net group and for a byte
group; minimum track 0.13 mm, 8 mil within a net, 15 mil between groups; total lengths preferably under 20 mm;
Vref decoupled at source and every destination, 20 mil wide, 25 mil from other signals
([ISSI](https://www.digikey.com/Site/Global/Layouts/DownloadPdf.ashx?pdfUrl=036C264570594B5589E336C3F96AB73F)).

**Lattice ECP5 (FPGA-TN-02038 hardware checklist; TN1265 for termination; excerpt).** DQS pair ±10 mil; DQ and DM
with their DQS on the same layer within ±10 ps, maximum 50 mil; LDQS and UDQS lanes within ±100 mil; CK pair
±10 mil; CK within ±5 ps of all DQS; 50 Ω single-ended and 100 Ω differential ±10 %; the ECP5 has dynamically
controlled internal termination for DQ and DQS ([checklist](https://0x04.net/~mwk/doc/lattice/ecp5/FPGA-TN-02038-2-0-ECP5-and-ECP5-5G-Hardware-Checklist.pdf),
[TN1265](https://www.latticesemi.com/~/media/LatticeSemi/Documents/ApplicationNotes/EH/TN1265.pdf?document_id=50467)).

**Xilinx UG583 (UltraScale; excerpt).** DQ to DQS ±5 ps (±29 mils) in the example skew table; CK to address,
command and control ±8 ps (±47 mils); fly-by CK to DQS between −149 ps and +1796 ps from first to last memory;
DQ and DQS of a byte on the same layer except in the breakout ([UG583 constraints](https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/DDR3-SDRAM-Routing-Constraints)).
UG586 (7 series MIG) requires fly-by for component designs and gives CK-to-DQS of 150 to 1600 ps ([UG483](https://www.amd.com/content/dam/xilinx/support/documents/user_guides/ug483_7Series_PCB.pdf), [summary](https://www.ampheo.com/blog/xilinx-7-series-fpga-ddr3-hardware-design-rules)).

**Intel EMIF handbook (excerpt).** DQ, DQS and DM board traces matched within 20 ps, ±10 ps of skew allowed within a
DQS group; fly-by address and command matched to CK with package delays added to board delays; the controller
deskews ([Intel DDR3 board design guidelines](https://www.intel.com/content/www/us/en/docs/programmable/683106/21-1-19-2-0/ddr3-board-design-guidelines.html)).

**Micron TN-41-13, point-to-point (excerpt).** DQ bus lengths of 25 to 75 mm; DQS may be matched loosely to DQ when
the controller can skew DQS; point-to-two-point address links (a T) trade signalling rate for capacity
([TN-41-13](https://www.semanticscholar.org/paper/TN-41-13:-DDR3-Point-to-Point-Design-Support-DDR2/c9a674a5a60c38062c4d4655f153378b0a026c7f)).

**Fly-by versus T.** Fly-by (JEDEC's DDR3 topology) has no or very short stubs and relies on leveling; T (double-T)
branches the clock, address and command to two chips and needs matched branches ([Altium, topologies](https://resources.altium.com/p/ddr3-routing-guidelines-and-routing-topologies);
[Altium, fly-by](https://resources.altium.com/p/fly-topology-routing-ddr3-and-ddr4-memory)). ButterStick's dual rank is
a T on address with per-rank clocks and controls; LogicBone is fly-by with termination networks.

**Vref and VTT.** VTT terminators at the end of the fly-by chain or the farthest T point, 0.2 to 0.55 in from the
last device, decoupled next to the resistors; Vref generated near its ball, decoupled at source and destination,
never on the VTT plane ([NXP AN2582](https://www.nxp.com/docs/en/application-note/AN2582.pdf), [ST AN5692](https://www.st.com/resource/en/application_note/an5692-ddr-memory-routing-guidelines-for-stm32mp13x-product-lines--stmicroelectronics.pdf), TI SPRABI1).

**Where vendors disagree.** Lane matching spans ±1 mil (TI's strobe pairs) to ±10 ps (Lattice, ISSI) to 20 ps
(Intel); address to CK spans ±8 ps (Xilinx), ±10 ps (ISSI) and ±20 mils per segment (TI); the CK-to-DQS relation is a
±5 ps rule for T and point-to-point designs (ISSI, Lattice) and a leveling window of more than a nanosecond for
fly-by (Xilinx). Serpentine spacing is 3W or 3H in the common guides and 5W in TI's note.

## 2. Bus routing with length control

The academic line starts with **Ozdal and Wong** (TCAD 2006): nets with minimum and maximum length bounds, routed as
river routing within channels, where the length is made by assigning each net an area of the channel and snaking
inside it; the same authors' single-layer bus routing (TCAD 2006) handles the planarity of a bundle
([TCAD 2006](https://dl.acm.org/doi/10.1109/TCAD.2006.882584), [publications](https://www.cs.bilkent.edu.tr/~mustafa.ozdal/publications.html)).
**BSG-Route** (Yan and Wong, ICCAD 2008) generalises this to any topology: length matching is an area-assignment
problem on a bounded sliceline grid, gridless, with the detailed snaking generated inside the assigned area
([BSG-Route](https://dl.acm.org/doi/abs/10.5555/1509456.1509569)). **Kohira and Takahashi's CAFE router** extends
each route toward its target length on a grid with obstacles ([IEICE 2010](https://www.researchgate.net/publication/4050961_Length-matching_routing_for_high-speed_printed_circuit_boards)).
The most recent step is **LP-based area assignment for multilayer PCBs with any-direction wires** (TODAES 2025), a
minimum-weight hierarchical-flow formulation with primal-dual LP that allows the wire topology to change to reach
a better area assignment ([TODAES](https://doi.org/10.1145/3795795)); obstacle-aware any-direction length matching
([arXiv 2407.19195](https://arxiv.org/html/2407.19195v1)) and the dense-meander alleviation papers
([arXiv 1705.04983](https://arxiv.org/pdf/1705.04983), [arXiv 1705.04984](https://arxiv.org/pdf/1705.04984)) deal
with the post-route legality of meanders (crosstalk and impedance from tightly packed segments).

The common structure: what is decided **before** detailed routing is the topology (which channel, which side of
which obstacle), the layer, the order of the nets in the bundle and the **area** each net may use for its length;
what is decided **after** is the exact meander shape inside that area. Meander geometry follows the vendor spacing
rules (3W edge to edge as the general guide, 5W centre to centre in TI's note, amplitude kept small relative to
width and segments long enough that self-coupling does not shorten the effective delay)
([Altium, tuning structures](https://resources.altium.com/p/length-matching-high-speed-signals-trombone-accordion-and-sawtooth-tuning),
[Cadence, serpentine tips](https://resources.pcb.cadence.com/blog/2019-serpentine-routing-tips-to-snake-in-your-tuned-traces),
[3W rule](https://greatpcb.com/the-3w-rule-in-pcb-signal-routing/)). Commercial tools (Allegro, Altium) tune
after routing but let the designer reserve room by routing the bundle with the spacing set for later tuning;
KiCad's tuning patterns take amplitude, spacing and corner radius as parameters
([KiCad MEANDER_SETTINGS](https://docs.kicad.org/doxygen/classPNS_1_1MEANDER__SETTINGS.html)).

## 3. Router architecture for dense two-terminal buses on few layers

PCB routers separate **escape routing** (from the pins to the component boundary), **bus planning** (assign each bus
to layers and route it planar on each layer, with the min-max length bounds considered) and **detailed routing**.
Kong, Yan and Wong's automatic bus planner (DAC 2009) solves bus decomposition, escape routing, layer assignment and
global bus routing together because manual bus planning "takes about two months per board"; an ILP formulation
followed ([DAC 2009](https://dl.acm.org/doi/10.1145/1629911.1630000), [ILP planner](https://ieeexplore.ieee.org/abstract/document/6509593)).
Ozdal and Wong's TCAD 2005 work does simultaneous escape routing and layer assignment for dense PCBs
([TCAD 2005](https://dl.acm.org/doi/10.1109/TCAD.2005.857376)). The crossing conflict between two nets that must each
stay on one layer between two vias is, in this framing, a layer-assignment and net-ordering problem: the planner
reduces topological crossings per layer (finding the largest non-crossing subset is a longest-path-with-forbidden-
pairs problem) and moves the rest to another layer or changes the escape order; it is not left to detailed routing.

**Negotiated congestion** (PathFinder, McMurchie and Ebeling 1995) converges by raising present and history costs
on shared resources ([PathFinder](https://dl.acm.org/doi/10.1145/201310.201328)). Applied to PCB escape routing
(Ma, Yan and Wong's NCER, ISQED 2010) it matched Cadence Allegro's routability on 14 industrial cases, each solving
most of what the other could not ([NCER](https://ieeexplore.ieee.org/document/5450514/)). Its known pathologies are
oscillation and long tails when a few resources are contested by nets with no alternative (VPR exposes the
present-cost growth and iteration cap as tuning knobs; "timing-driven PathFinder pathology" studies the noise it
introduces) ([VPR options](https://docs.verilogtorouting.org/en/latest/vpr/command_line_usage/),
[pathology](https://dl.acm.org/doi/10.1145/1950413.1950447)). What replaces or augments it here: ILP or SAT for the
layer assignment and net ordering (small at bus size), rip-up and reroute with topology change (the 2025 LP
area-assignment router allows topology changes), conflict-based search treating nets as agents on unstructured
meshes ([Supercomputing 2025](https://link.springer.com/article/10.1007/s11227-025-07569-0)), and pattern routing
for the regular parts (escapes and channel bundles). A unified PCB router with constraints and differential pairs is
described at ASP-DAC 2021 ([ASP-DAC](https://dl.acm.org/doi/pdf/10.1145/3394885.3431568)).

## 4. BGA escape routing

Escape routing is unordered or ordered; ordered escape (the wires must leave the boundary in a prescribed order so
that they meet the other component's order) is NP-hard and handled by ILP for small cases, by network flow with
ordering heuristics, and lately by Monte-Carlo tree search
([two-stage LP plus heuristic](https://www.sciencedirect.com/science/article/abs/pii/S0167926024001342),
[ordered escape with pairs and blockages](https://dl.acm.org/doi/10.1145/3185783), [MCMC-Escape](https://dl.acm.org/doi/10.1145/3795522)).
Yan and Wong's correct network flow model (DAC 2009) fixed the diagonal capacity that earlier flow models got wrong
and gives an optimal unordered escape ([DAC 2009](https://dl.acm.org/doi/10.1145/1629911.1630001)). **Simultaneous
escape routing** escapes both components so that their nets meet in order, by network flow or ILP
([MJCS](https://ejournal.um.edu.my/index.php/MJCS/article/download/7006/4659/15036), [dual-model node](https://pmc.ncbi.nlm.nih.gov/articles/PMC8056246/)),
which is the joint planning the brief asks about: the escape is chosen with the bus, not before it. Practice notes:
dog-bones at 0.5 mm pitch and above, via-in-pad below (filled and capped); the first two rings leave on the top
layer, interior rings by via; vias placed where pads are absent create lanes ([JLCPCB](https://jlcpcb.com/blog/effective-escape-routing-strategies),
[Cadence](https://resources.pcb.cadence.com/blog/2019-best-pcb-routing-methods-for-bga-escape-routing),
[TI AM62 escape routing](https://www.ti.com/lit/an/sprad13a/sprad13a.pdf)).

## 5. Open tools

- **Freerouting** (Java, GPL-3): maze and shove routing with fanout and a batch optimiser over the Specctra DSN and
  SES interface; no length matching ([freerouting](https://github.com/freerouting/freerouting)). Useful as a
  reference for shove and rip-up mechanics and for the DSN interchange; its licence rules out linking.
- **KiCad's interactive router (PNS)** (C++, GPL): walkaround and shove, differential pairs, single-track,
  pair and skew tuning with amplitude, spacing and radius settings; no autorouter
  ([MEANDER_SETTINGS](https://docs.kicad.org/doxygen/classPNS_1_1MEANDER__SETTINGS.html), [tuning guide](https://techexplorations.com/guides/kicad/high-speed-pcb-design/kicad-9-differential-pair-length-tuning-guide/)).
  Its meander placer is the model for a legal serpentine generator; the router itself is interactive by design.
- **OrthoRoute** (Python and CUDA, MIT): GPU PathFinder on a Manhattan lattice for very large regular boards and
  BGA escapes; a KiCad plugin ([OrthoRoute](https://github.com/bbenchoff/OrthoRoute)). Same algorithm family as our
  first router, and the same limits; worth reading for its escape planner and lattice model.
- **copperroute** (GPL-3): fanout, maze routing and optimiser derived from Freerouting ([copperroute](https://github.com/emshotton/copperroute)).
- **OpenROAD** FastRoute and TritonRoute (BSD): IC global and detailed routers with capacities, guides and
  rip-up-and-reroute; no PCB stack-up, no length constraints; the guide-based split between global and detailed
  routing is the pattern to copy, not the code ([TritonRoute](https://github.com/The-OpenROAD-Project/TritonRoute)).
- No open length-matching bus router was found; the academic routers above are not published as code.

## Reconciliation with the owner's foundational reference (`foundational-reference.md`)

The owner's report (Claude app research, 2026-09-19) covers the whole flow from schematic to verification; this
report is the bus-routing slice. Where they overlap:

**Agreements.** Length rules are timing budgets translated through the layer's propagation delay and should be
derived and judged in picoseconds (its Stage 0 and Table C; this report's summary and D27 restated in delay).
Escape routing is a network-flow, SAT or ILP problem (Ozdal, Yan, Wong, Luo; B-escape beat Allegro on every case
it tried). Negotiated congestion belongs in global routing, push-and-shove and rip-up in detailed routing.
Byte lanes need not match each other because write leveling absorbs the difference; address and command are
matched to the clock, data to its own strobe. Dog-bones are the practice at 0.8 mm and via-in-pad below 0.5 mm.

**Numbers that differ, and why.** Its Table A gives the tighter, mil-based memory-vendor rules (DQ to DQS ±10 mil,
address to CK ±20 to ±25 mil, NXP and TI), this report the picosecond rules of the FPGA vendor the references use
(Lattice: ±10 ps, no more than 50 mil apart) and ISSI. Both are real vendor practice; the benchmark should carry
the Lattice numbers as the pass line (the parts on the boards) and the TI and NXP numbers as the target the tool
aims for. Its delay constant for stripline (180 ps/in from εr 4.5) is above this report's 170 ps/in and Micron's
165 ps/in; the conversions agree within ten percent and the anchor (10 ps ≈ 1.5 mm inner layer) is common.

**One disagreement that matters for the router.** The foundational reference keeps length tuning as a stage
after detailed routing ("deterministic once topology is fixed"). For the boards in this project that is exactly
what failed: ButterStick's packages are 0.5 mm apart, the whole bus lives inside the memory footprints, and once
the nets were routed there was no room for the tuner. The length-matching literature (Ozdal and Wong 2006,
BSG-Route 2008, the 2025 LP area-assignment router) reserves the length as an area budget during global routing
and only shapes the meanders afterwards. This report keeps that order: room first, meanders last. Post-route
tuning is sufficient only where a channel with slack exists, which is LogicBone's case, not ButterStick's.

**A claim to correct against our measurements.** Its Table E says 0.8 mm pitch at 4-mil rules leaves "about zero
channels" between balls so HDI is often needed. ButterStick routes its 0.8 mm memories with one 0.089 mm track per
channel at 0.0886 mm clearance on a standard through-hole board: floor((0.8 − 0.4 − 2×0.0886)/(0.089 + 0.0886)) = 1
by the same formula. Zero channels follows only from 5-mil rules; at 3.5 mil (the JLCPCB floor in its Table D) the
channel exists, and the M2 fan-out used it on every reference.

**Levers it raises that this report had not.** Data bits within a byte lane may be swapped (except DQ0 for some
controllers) and byte lanes may be swapped whole; FPGA pins are reassignable. A router that may choose the ball
for each bit has far fewer crossings to resolve than one that takes the netlist as fixed, which is what ours does.
The references' designers had this freedom; whether they used it is measurable from their pinouts. KiCad 9 and 10
expose delay-based tuning profiles per net class, which is the form the tuner's targets should take.

## What this means for waffle-eda

- Restate the benchmark in delay (ps) per group from the vendor tables above, with per-layer velocity from the
  stack-up; keep the references' figures as evidence of what works, and flag where they sit outside the rules.
- Replace the single negotiated router with the pipeline of the summary: escape planning for both packages at
  once, bus planning with layer assignment and area budgets, detailed routing inside corridors, negotiation only
  for local residue.
- Keep both escape styles and both meander placements as options chosen by the geometry: the ButterStick structure
  when the packages touch, the channel between packages when there is one.
- Treat bit swapping within lanes and FPGA pin assignment as part of the planning problem, once the references
  show whether their designers used them.
