<!-- Owner-supplied research report (Claude app, published artifact b9930902-e1fb-48fb-9ec2-51f357ebb7c7), pasted into the
repository on 2026-09-19 verbatim. The reconciliation with waffle-eda's own measurements is in ddr3-bus-routing.md. -->

# Foundational Reference: Automated Schematic Design and PCB Place-and-Route for High-Performance Boards

## TL;DR
- Fully automated (100%) place-and-route is achievable today only for low-to-mid-complexity boards; for an 8-layer DDR3/BGA/FPGA design the *constraint-derivation, fan-out/escape, and length-tuning* stages are solvable with classical algorithms, but *whole-board detailed routing at signal-integrity quality* remains the hard, unsolved core where no open tool matches a skilled human.
- The winning architecture is a staged pipeline — constraint extraction → placement → BGA fan-out/escape → global routing → detailed (push-shove) routing → length/skew tuning → SI/DRC verification — where classical, physics-derived constraints dominate and ML helps mainly at placement seeding and congestion prediction, not as an end-to-end black box.
- DDR3 rules are physics-derivable, not folklore: length-match tolerances come directly from timing-budget allocations (≈180 ps/inch stripline; 10 ps ≈ 60 mils), impedance targets (40 Ω single-ended / 80 Ω differential for the DATA group, 50/100 Ω for ADDR/CMD) come from the driver/ODT design, and fly-by topology is a deliberate SSN-reduction choice compensated by write leveling.

## Key Findings

1. **Constraint derivation is the automatable heart of the problem.** Every DDR length-match number in vendor guides (Xilinx UG583, Micron, TI, Intel/Altera) is back-solved from a picosecond timing budget using the FR-4 propagation constant. An automated tool can therefore *derive* constraints rather than hard-code them.
2. **BGA escape is a well-studied combinatorial problem** (Wong/Ozdal/Yan network-flow and boundary-routing algorithms; SAT- and ILP-based ordered escape), but production tools still leave "the last few pins" to humans.
3. **Classical routing (Lee/A*/line-probe + rip-up-reroute + negotiated congestion/PathFinder)** is mature and forms the backbone of every real router, including KiCad's PNS and FreeRouting.
4. **VLSI analytical placers (ePlace/RePlAce/DREAMPlace)** are extremely fast but assume homogeneous standard cells; PCB placement is dominated by heterogeneous parts, connectors, thermal and mechanical constraints, making direct transfer limited.
5. **AI-EDA claims need scrutiny.** Google's AlphaChip results are contested; commercial AI-PCB tools (Quilter, DeepPCB, Flux.ai) split between physics-driven + RL (Quilter), RL routing (DeepPCB/InstaDeep), and breadth (Flux).
6. **KiCad 9 provides the necessary substrate** — a stable IPC (Protocol-Buffers/NNG) API, S-expression file formats, a push-and-shove router with differential-pair and length/skew tuning, a rule-based DRC engine, and `kicad-cli` — but no built-in numerical field solver.
7. **Open-source SI verification exists** (openEMS FDTD, scikit-rf, IBIS-AMI Python tooling, atlc/FEMM 2D field solvers) and can be wired into an automated verification loop.

## Details

### 1. Industry best practices for high-speed PCB design

**Stackup design.** High-speed boards use symmetric, balanced stackups to prevent warpage and to give every high-speed signal an adjacent solid reference plane. The governing physics (articulated by Rick Hartley and Eric Bogatin) is that signal energy travels in the electromagnetic field between the trace and its reference plane, not "in the copper"; therefore the return path and the field's dielectric geometry determine impedance, crosstalk, and EMI. A typical 8-layer prototype stackup for DDR3+BGA is Signal-GND-Signal-PWR-GND-Signal-GND-Signal or similar, placing the two BGA-escape signal layers tight to ground and keeping a power/ground plane pair closely coupled for PDN capacitance.
Sources: https://www.protoexpress.com/blog/how-grounding-controls-noise-and-emi-by-rick-hartley/ ; https://startingelectronics.org/articles/proper-grounding/

- **Microstrip vs stripline.** Microstrip (outer layer, one reference plane, part of field in air) has εeff ≈ 2.8 on FR-4 and propagation delay ≈ 140–150 ps/inch. Stripline (inner layer, two reference planes, fully embedded) has εeff ≈ εr ≈ 4.5 and delay ≈ 180 ps/inch. Stripline gives better EMI containment and crosstalk isolation but is slower; microstrip is faster and easier to route/probe. Source (delay constants): https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7436267 ; https://www.analog.com/media/en/training-seminars/tutorials/MT-094.pdf
- **Controlled impedance.** Fabs like JLCPCB provide impedance-controlled multilayer at no extra charge, using defined prepreg (3313, 7628, 2116) and dynamically adjusting trace width (JLCPCB states "±20% (or ±10% for high-precision requirements)") to hit target impedance. Impedance tolerance is ±10% for Z ≥ 50 Ω and ±5 Ω for Z < 50 Ω. Sources: https://jlcpcb.com/blog/pcb-design-rules-best-practices ; https://jlcpcb.com/help/article/hdi-pcb-capabilities-faq

**Return-path management.** Every layer transition of a high-speed signal needs a nearby return via (stitching via) so the return current can follow. UG586/UG583 codify this: "Any signal layer switching via needs to have one ground via within a 50 mil perimeter range." Never route high-speed signals over split planes — the return current cannot cross the gap and is forced into a large loop, radiating EMI and coupling crosstalk. Source: https://fedevel.com/forum/your-projects/10831-ddr3l-rules-and-constrains-confirmations

**Decoupling / PDN design.** The PDN must present an impedance below a target impedance Z_target across the frequency band of interest. The canonical relationship (Bogatin/Smith, *Principles of Power Integrity for PDN Design*): Z_target = ΔV_ripple / ΔI_transient. Decoupling capacitors are local charge reservoirs; their effectiveness is limited by loop inductance (ESL + mounting/via inductance), which sets the frequency above which a capacitor becomes ineffective. The design rules that follow: place small-value caps closest to the power pins with the shortest, widest loop; use a hierarchy of values (bulk → mid → high-frequency); and minimize the via/spreading inductance. Steve Sandler's relation C = L/R² and matching ESR to Z_target give a flat impedance profile. Sources: https://www.zuken.com/en/blog/what-pdn-target-impedance-means-for-pcb-designers/ ; https://resources.pcb.cadence.com/pcb-design-blog/why-decoupling-capacitor-placement-becomes-harder-in-hdi-pcb-designs ; https://www.protoexpress.com/blog/decoupling-capacitor-placement-guidelines-pcb-design/

**Via design.** Through-hole vias create stubs; the unused barrel portion resonates (a quarter-wave stub resonance) and degrades signals at high frequency — sources place the practical concern above ~10 Gbps (NRZ). Remedies: backdrilling (removing the stub), blind/buried/microvias (HDI), and via-in-pad for fine-pitch BGAs. Anti-pads (plane clearances around via) control the via's impedance and the plane-to-plane capacitance. Source: https://www.atlaspcb.com/blog/bga-fanout-routing-strategies-dog-bone-via-in-pad/

**Crosstalk control.** The "3W rule" (center-to-center spacing ≥ 3× trace width, i.e. ~2W edge-to-edge gap) reduces edge-coupled crosstalk to roughly ~1%. This is a heuristic, not physics-exact: Rick Hartley and Eric Bogatin note that what matters is the ratio of spacing to dielectric height (coupling falls with plane proximity), so a tighter design over a thin dielectric can use less than 3W. The PCEA "High-Speed Constraint Values" note (Pfeil) frames these as "Effective" values (per Hartley/Bogatin, for dense designs) vs "Extreme" values that over-constrain. Guard traces are usually unnecessary and can be harmful unless via-stitched at ~λ/10 intervals. Source: https://pcea.net/wp-content/uploads/2022/04/High-Speed-Constraint-Values-v2-Pfeil.pdf

**Length matching / skew budgets** — see the constraint tables below. These derive from timing budgets, not tradition.

**Differential pairs.** Intra-pair skew must be minimized (matched within a few mils / ~1 ps) so common-mode conversion (and consequent EMI) stays low; Hartley notes perfect phase matching is impossible because fiber-weave (106/1080 glass) creates unavoidable skew — as he put it, "the perfect phase matching of a differential pair is nearly impossible. Fiber weave issues run amuck with 106 and 1080 glass" — and the concern is as much EMI as timing. Source: https://pcea.net/wp-content/uploads/2022/04/High-Speed-Constraint-Values-v2-Pfeil.pdf

**EMI/EMC.** Driven by field containment: tight signal-to-reference coupling, continuous return paths, controlled edge rates, and stitching. Henry Ott's *Electromagnetic Compatibility Engineering* is the canonical reference.

**DFM for prototype fabs (JLCPCB/PCBWay class).** JLCPCB standard capability: ~3.5 mil (≈0.09 mm) minimum trace/space at higher layer counts; minimum via ~0.15 mm hole; aspect ratio ≤ 16:1 for mechanical vias; HDI boards up to 2.4 mm with 0.15 mm min through-hole; via-in-pad (POFV, plated-over filled vias) free on 6–20 layer stackups; board thickness 0.4–3.2 mm; free impedance control on multilayer. Standard start points: 6 mil trace/space for 2-layer, 4 mil for 4-layer, 1 oz copper standard (2 oz needs ≥6.5 mil spacing). These numbers are the hard geometric floor an automated DRC must respect. Sources: https://jlcpcb.com/capabilities/pcb-capabilities ; https://jlcpcb.com/blog/optimize-pcb-trace-spacing ; https://www.schemalyzer.com/en/blog/manufacturing/jlcpcb/jlcpcb-design-rules

### 2. DDR memory routing (primary interest)

**Why fly-by (DDR3/DDR4).** DDR2 used a balanced T-branch (T-topology) tree for address/command/clock; DDR3 switched to fly-by daisy-chain to eliminate stubs and improve signal integrity at higher speed. Intel/Altera state it plainly: "Fly-by topology reduces simultaneous switching noise (SSN) by deliberately causing flight-time skew between the data and strobes at every DRAM." The cost is that the clock/address/command arrive at each DRAM at a different time than the data; JEDEC added **write leveling** so the controller compensates per-byte-lane skew during initialization. This is the key physical insight for an automated tool: fly-by intentionally *creates* skew that is corrected in the time domain by the controller, which is exactly why ADDR/CMD/CTRL are matched to the *clock* while DQ is matched to its *own* DQS strobe, and byte lanes need not be matched to each other. Sources: https://www.intel.com/content/www/us/en/docs/programmable/683385/17-0/read-and-write-leveling.html ; https://iconnect007.com/index.php/article/60600/pcb-design-techniques-for-ddr-ddr2-ddr3-part-2/60603

**DDR3 topology and termination.**
- ADDR/CMD/CTRL/CLK: fly-by daisy chain, routed controller → DRAM0 → … → DRAMn → VTT termination. VTT = VDDQ/2 (0.75 V for 1.5 V DDR3) pull-up resistors (~39–56 Ω) terminate the far end. Address lines cannot be swapped. TI SPRABI1: "All nets in the address and command fly-by groups must route along the same path from the controller to each SDRAM sequentially, and then to the VTT termination." Source: https://www.ti.com/lit/pdf/sprabi1
- Clock: differential, 100 Ω differential termination at the last device; a compensation capacitor can dampen ringing (Intel AN520). Source: https://community.intel.com/cipcp26785/attachments/cipcp26785/programmable-devices/3577/1/an520%20DDR3%20SDRAM%20Memory%20Interface%20Termination%20and%20Layout%20Guidelines.pdf
- Data (DQ/DQS/DM): point-to-point (controller ↔ single DRAM), terminated by **On-Die Termination (ODT)** — dynamic ODT in both controller and SDRAM. Series source resistors (~15–33 Ω) sometimes used for 2"–2.5" links. DQS is differential.
- Signaling: SSTL (Stub-Series-Terminated Logic), center-tapped termination, VREF = VDDQ/2 decides 0/1.

**DDR3 swap rules (critical for pin-assignment co-optimization).** Within a byte lane, DQ bits can be swapped freely to ease routing (physics: any bit maps to any position because DQS captures the whole lane and write-leveling/per-bit deskew handle timing) — but some vendors forbid swapping the lowest-order bit (e.g. ADI EE-434: "Within a byte lane, data bits can be swapped, except for the lowest order bit (DQ0)"). Byte lanes themselves can be swapped as whole groups. DQS must stay on a clock-capable (DQS) pair; CK must stay on a clock-capable pair. Address/command cannot be swapped. For Xilinx 7-series, address/control must be in the middle I/O bank when spanning three banks. Sources: https://manuals.plus/m/9523df23be4d4efa062c9f51e87bccea0fc6c6585567fbbfc9a645e72cb91ff6 ; https://www.ampheo.com/blog/xilinx-7-series-fpga-ddr3-hardware-design-rules

**DDR2 vs DDR4 vs DDR5.**
- DDR2: T-branch topology, SSTL_18 (1.8 V), no write leveling.
- DDR4: fly-by like DDR3; VDDQ dropped to 1.2 V (from DDR3's 1.5 V / DDR3L's 1.35 V); DATA signaling changed from SSTL to **POD (Pseudo-Open-Drain)** — terminates to VDDQ instead of VDDQ/2, so only 0's draw DC current (lower power, cleaner eye); adds Data Bus Inversion (DBI); ODT more sophisticated; clamshell (mirrored) topologies with address mirroring. DDR4 also has a 2.5 V VPP word-line supply and per-bit deskew. EDN: "By terminating to VDDQ instead of 1/2 of VDDQ, the amplitude and centre of the signal swing can be tailored to each design's need. POD I/O reduces switching current when driving data since only 0's consume power." Sources: https://www.edn.com/hardware-design-considerations-for-space-grade-ddr4/ ; https://www.systemverilog.io/design/ddr4-initialization-and-calibration/
- DDR5: 1.1 V; CA signaling changes SSTL→PODL; **Decision Feedback Equalization (DFE)** added for both DQ and (in the RCD) CA; two independent 32-bit sub-channels per DIMM; on-DIMM PMIC. Data rates 4.8→8.4 GT/s. Routing depth here is out of scope but the tool should know CA is now SI-critical. Source: https://www.rambus.com/blogs/get-ready-for-ddr5-dimm-chipsets/

**The physics behind the numbers.** Signal propagation delay: t_pd = √(εeff)/c. On FR-4 this is ≈ 85 ps/inch × √εeff → ≈180 ps/inch stripline (εr ≈ 4.5, per t_pd = 85·√εr) and ≈140 ps/inch microstrip (εeff ≈ 2.8, per t_pd = 85·√(0.475·εr+0.67)). Micron uses ~6.5 ps/mm (~165 ps/inch) for inner layers. **Conversion anchor: 10 ps ≈ 60 mils ≈ 1.5 mm (Micron); 25 mils ≈ ~4–4.5 ps.** Length-match tolerances are chosen by allocating a small fraction of the DDR data-eye budget (governed by tDQSQ, the DQS-to-DQ read skew, and tDQSS, the write-strobe-to-clock window) to board skew. An automated tool should compute: (available window in ps) → (board-skew allocation in ps) → (tolerance in mils via the layer's t_pd). Xilinx UG583 in fact specifies its DDR3/DDR4 constraints directly in picoseconds (e.g. a CK offset expressed as "42 ps/250 mil" with tolerances of a few ps), reinforcing the timing-first approach. Sources: https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7436267 ; https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7453143 ; https://www.analog.com/media/en/training-seminars/tutorials/MT-094.pdf ; https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design

**Vendor guidance to encode.** Xilinx/AMD UG586 (7-series MIS) and UG583 (UltraScale PCB design, current rev 1.29, 2025-12-23); Intel/Altera external memory interface handbook & AN520; TI KeyStone DDR3 (SPRABI1); Micron TN design-support notes; NXP i.MX DDR3 hardware design guides (AN3940); Analog Devices EE-434. Representative concrete tolerances appear in the tables below. Sources: https://www.xilinx.com/support/documentation/ip_documentation/ug586_7Series_MIS.pdf ; https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design ; https://hands.com/~lkcl/eoma/rockchip_rk3288/AN3940.pdf

### 3. BGA fan-out and escape routing

**Dog-bone vs via-in-pad.** Dog-bone (via placed in the gap between four balls, short trace to pad) works reliably for pitch ≥ 0.5 mm (comfortably at 0.8–1.27 mm). Via-in-pad (via in the ball pad, must be filled with epoxy and capped/plated — POFV/VIPPO — so solder doesn't wick during reflow) is needed for ≤0.5 mm and increasingly at 0.65 mm. PCBSync notes VIPPO "adds approximately 20% to board fabrication cost but can eliminate two routing layers on a dense BGA — often a net saving." Sources: https://jlcpcb.com/blog/effective-escape-routing-strategies ; https://pcbsync.com/bga-pcb-design/ ; https://resources.altium.com/p/which-bga-pad-and-fanout-strategy-right-your-pcb

**Channel geometry (the core algorithmic constraint).** Between two adjacent pads the number of routable traces (channels) = floor((pitch − pad_diameter − clearance) / (trace_width + space)). Worked examples (AtlasPCB): at 1.0 mm pitch / 0.5 mm pad / 0.1 mm clearance / 0.1/0.1 mm trace-space → floor((1.0 − 0.5 − 0.2)/0.2) = 1 trace per channel; at 0.8 mm pitch with 4-mil rules → effectively zero channels, "which is exactly why HDI becomes mandatory below 0.8mm pitch." For a 0.8 mm pitch NSMD pad of 0.32 mm (MacroFab example), gap ≈ 0.48 mm (18.9 mil); a 5-mil trace leaves ~6.95 mil clearance to each pad. Sources: https://www.atlaspcb.com/blog/bga-fanout-routing-strategies-dog-bone-via-in-pad/ ; https://www.macrofab.com/blog/escaping-bgas-methods-routing-traces-bga-footprints

**Layer assignment for escape.** The outermost 1–2 ball rows escape on the surface without vias; each deeper row generally needs its own inner signal layer (two rows can share one layer if traces alternate left/right). This directly sets the layer-count budget: for a 1.0 mm-pitch Artix-7 FG676 (26×26), AtlasPCB recommends ~10–12 layers depending on center power/ground density. Power/ground balls in the BGA core are dropped straight down on vias to plane layers, freeing signal channels and providing PDN current paths. NXP AN10778 gives per-pitch fan-out patterns for 1.0/0.8/0.65/0.5 mm. Sources: https://www.atlaspcb.com/blog/bga-fanout-routing-strategies-dog-bone-via-in-pad/ ; https://www.nxp.com/docs/en/application-note/AN10778.pdf ; https://www.nwengineeringllc.com/article/bga-escape-routing-with-impedance-control-in-hdi-pcbs.php

**FPGA pin-swap co-optimization.** FPGA I/O pins (unlike fixed CPU/SoC balls) are largely reassignable in the synthesis constraints (XDC/UCF). The huge automation opportunity: co-optimize pin assignment *with* escape routing so that byte lanes/differential pairs land on adjacent, easily-escapable balls. Academic ordered-escape work (below) with routability-driven pin assignment (Yan/Ke/Chen) targets exactly this.

**Escape-routing algorithms (academic).** Martin D. F. Wong's group established the field: Ozdal & Wong, "Simultaneous escape routing and layer assignment for dense PCBs" (ICCAD 2004) and "…for via minimization of high-speed boards" (IEEE TCAD 27(1):84–95, 2008); Luo & Wong, "Ordered escape routing based on Boolean satisfiability" (ASP-DAC 2008); Luo, Yan, Ma, Wong, Shibuya, "B-escape: a simultaneous escape routing algorithm based on boundary routing" (ISPD 2010, pp. 19–25) — which reports "our algorithm successfully solved all of them while Cadence Allegro PCB router was only able to complete the routing of half of the problems"; Yan & Wong, "A correct network flow model for escape routing" (DAC 2009); Ma, Yan, Wong negotiated-congestion escape router (ISQED 2010); Ma/Young/Wong on the NP-complete rectangle-escape problem (IEEE TCAD 31(9):1356–1365, 2012). Recent: MC-MCF multi-capacity ordered escape (2023), genetic-algorithm ordered escape (MDPI Applied Sciences 2026), and two-stage LP+heuristic escape (2024). These treat escape as network flow / SAT / ILP with non-crossing and channel-capacity constraints. Sources: https://dl.acm.org/doi/10.1145/1735023.1735033 ; https://dl.acm.org/doi/10.1145/3185783 ; https://www.mdpi.com/2076-3417/16/4/2010 ; https://www.sciencedirect.com/science/article/abs/pii/S0167926024001342

### 4. Routing algorithms — commercial and academic

**Foundational.** Lee's maze router (1961) is a breadth-first wavefront that guarantees the shortest path but is "slow and memory consuming" (NTU Chang course notes); Hadlock's detour-numbering and Soukup's variants speed it up. A* adds a heuristic to guide the search. Line-probe/line-search (Mikami-Tabuchi, Hightower) trades completeness for speed by working with line segments instead of a grid — Hightower "might fail to find a path even if one exists." Two-level routing (global then detailed) tames Lee's cost: global routing on coarse GCELLs produces route guides and a congestion map; detailed routing commits exact wires within each cell. Source: https://cc.ee.ntu.edu.tw/~ywchang/Courses/PD_Source/EDA_routing.pdf

**Rip-up and reroute (R&R).** Since net ordering is a chicken-and-egg problem, routers route greedily then selectively rip up and reroute congested/violating nets. Classic detailed router: Mighty (rip-up-reroute). Modern: BoxRouter (box expansion + progressive ILP + adaptive maze), FastRoute (fast global), NTHU-Route, TritonRoute (pin-access + track assignment + initial detailed routing + search-and-repair + DRC), Dr. CU (Dijkstra + sparse grid-graph + partitioning). Sources: https://www.academia.edu/2739203/Mighty_a_rip_up_and_reroute_detailed_router ; https://arxiv.org/pdf/2512.03594

**Negotiated-congestion / PathFinder.** McMurchie & Ebeling's PathFinder (FPGA95) is the single most influential idea for congestion-driven routing: nets initially share resources, then a per-node cost f(n) = (b(n) + h(n)) × p(n) — base cost + accumulated historical congestion + present congestion — is iteratively increased so overused resources are "negotiated" away until a legal, congestion-free solution emerges. Widely used in FPGA routers (VPR) and directly transferable to PCB global routing. Sources: https://www.cecs.uci.edu/~papers/compendium94-03/papers/1995/fpga95/pdffiles/6a.pdf ; https://arxiv.org/pdf/2407.00009

**Push-and-shove / interactive.** KiCad's PNS (Push-and-Shove) router shoves existing traces aside while maintaining DRC, with walk-around and highlight-collision modes and differential-pair + length/skew tuning. Commercial analogs: Altium ActiveRoute, Cadence Allegro (and Allegro X AI), Siemens/Mentor Xpedition, Zuken. Push-shove is the workhorse for interactive high-speed routing. Source: https://docs.kicad.org/9.0/en/pcbnew/pcbnew.html

**Gridless / shape-based / topological.** Specctra (Cadence) pioneered shape-based autorouting with the DSN/SES interchange format still used today. Electra (Konekt) and FreeRouting (Alfons Wirtz, 2004; GPL 2014) are DSN/SES-compatible. **TopoR** (Eremex, topological roots from 1988) uses *no preferred routing directions* and free-angle/arc traces; Eremex claims this "reduces wire parallelism, which in its turn reduces electromagnetic crosstalks" and yields fewer vias/layers/length. gEDA's Toporouter and EAGLE's TopRouter are other topological routers. Sources: https://en.wikipedia.org/wiki/Specctra ; https://en.wikipedia.org/wiki/TopoR ; https://en.wikipedia.org/wiki/Routing_(electronic_design_automation)

**Differential-pair and length-tuning algorithms.** Diff-pair routing routes the pair as a coupled unit maintaining gap and intra-pair skew; length tuning inserts serpentine/trombone/accordion meanders to add delay. KiCad 9/10 overhauled length tuning with time-domain (propagation-delay) constraints and per-net-class Tuning Profiles. Source: https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html

**Steiner trees & via assignment.** Multi-pin nets are decomposed via rectilinear Steiner minimal trees (RSMT/OARSMT — obstacle-avoiding); FLUTE is the standard fast RSMT builder. Layer/via assignment is a separate optimization (minimize vias subject to capacity). Source: https://arxiv.org/pdf/2503.07268

**Stochastic methods.** Simulated annealing and Monte-Carlo Tree Search appear in placement and some gridless routers (He et al. MCTS gridless 2D routing, cited in Nature Sci. Reports 3D LineExplore). Source: https://www.nature.com/articles/s41598-026-36925-0

**Why commercial PCB autorouters historically produced poor results.** They optimize geometric completion (connect all nets, pass geometric DRC) but are blind to *electrical* intent: return paths, impedance continuity, crosstalk, length/skew, plane integrity, via-stub resonance, and the manufacturability/debuggability a human considers. Freerouting achieves high routability but degrades in high-density SI-critical designs; a 2024 ScienceDirect survey states bluntly that "there is no mature commercial or academic router that can automatically route boards at the board level" to human quality on hard designs. The lesson for an automated tool: constraints must be *electrical and physics-derived*, fed to the router as hard/soft costs, not applied as an afterthought. Source: https://www.sciencedirect.com/science/article/abs/pii/S0167926024001342

### 5. Placement algorithms

**Analytical / force-directed.** Model nets as springs (quadratic wirelength) and solve for minimum-energy positions; add a density/spreading term to avoid overlap. The modern state of the art is **electrostatics-based**: ePlace/RePlAce (Lu et al., ACM TODAES 2015; Cheng/Kahng/Kang/Wang, IEEE TCAD 2019) model every cell as a charge and density cost as the potential energy of an electrostatic system (eDensity), solved with FFT and Nesterov's method. **DREAMPlace** (Lin et al., DAC 2019 / IEEE TCAD 40(4):748–761, 2020) recasts this as a neural-network training problem on PyTorch; the authors report "around 40× speedup in global placement without quality degradation compared to the state-of-the-art multithreaded placer RePlAce" (GitHub notes over 30× on ISPD 2005 with a Tesla V100). DREAMPlaceFPGA and elfPlace extend it to heterogeneous FPGAs. Sources: https://research.nvidia.com/sites/default/files/pubs/2019-06_DREAMPlace:-Deep-Learning/54_1_Lin_DREAMPLACE.pdf ; https://dl.acm.org/doi/10.1145/3316781.3317803

**Combinatorial.** Min-cut/partitioning (Fiduccia-Mattheyses, hMETIS) recursively bisects; simulated annealing (Kirkpatrick, Gelatt & Vecchi, *Science* 220(4598):671–680, 1983; TimberWolf) is flexible and quality-good but slow.

**Applicability/limits for PCB.** VLSI placers assume millions of near-homogeneous standard cells in rows; PCB placement has hundreds of *heterogeneous* components with wildly different sizes, fixed connectors and mounting holes, mechanical keep-outs, thermal dissipation, double-sided placement, and human-readability/serviceability. Analytical placers transfer partially (good for the "put connected things close" objective) but must be heavily constrained. PCB-specific high-speed placement objectives: minimize DDR route lengths (place DRAM in a fan-by arc off the controller), place decoupling caps immediately at BGA power pins, keep crystals/sensitive analog away from switchers, and pre-place connectors at board edges.

### 6. AI/ML approaches

**Google AlphaChip (RL macro placement).** Nature 2021 (Mirhoseini et al., "A graph placement methodology for fast chip design," Nature 594(7862):207–212): a deep RL policy places macros to maximize a reward (wirelength, congestion, density), then force-directed placement handles standard cells; the policy is pre-trained on a corpus of 20 prior designs before fine-tuning. DeepMind claims superhuman TPU layouts and external adoption (MediaTek). **The claims are contested**: Cheng et al. (ISPD 2023) and Igor L. Markov's "The False Dawn: Reevaluating Google's Reinforcement Learning for Chip Macro Placement," *Communications of the ACM* 67(11):60–71 (2024), which concludes "Google RL lags behind (i) human designers, (ii) a well-known algorithm (Simulated Annealing), and (iii) generally-available commercial software, while being slower; and in a 2023 open research contest, RL methods weren't in top 5." The "An Updated Assessment of Reinforcement Learning for Macro Placement" (arXiv 2302.11014) reports that as of November 2025 "no successful reproduction by others…has been published," and that on CT-Ariane-X4 (532 macros, TSMC 7nm) "SA achieves better results than AlphaChip in both post-detailed placement HPWL and proxy cost, using a fraction of runtime and computing resources." DeepMind rebutted (arXiv 2411.10053) that critics didn't pre-train or use adequate compute. For an implementer: treat RL placement as promising but unproven — useful for seeding, not for trust. Sources: https://en.wikipedia.org/wiki/AlphaChip_(controversy) ; https://dl.acm.org/doi/full/10.1145/3676845 ; https://arxiv.org/pdf/2302.11014 ; https://arxiv.org/html/2411.10053v1

**Commercial silicon-EDA AI.** Cadence Cerebrus and Synopsys DSO.ai automate PPA tuning of existing tool flows via RL/Bayesian search — orchestration, not raw placement.

**AI-PCB startups (2026 landscape).**
- **Quilter** — physics-driven + reinforcement learning; validates every trace against circuit-level constraints (return paths, impedance via an integrated Simbeor field solver, PDN, diff-pair integrity, bypass-cap placement); generates multiple candidates; works alongside Altium/Cadence/Siemens/KiCad; free tier. In its "Project Speedrun" it ran an NXP i.MX 8M Mini SOM+baseboard (2 GB LPDDR4, 843 components, 5,141 pins, 8-layer HDI, fabbed by Sierra Circuits): reported ~27 hours of automated placement/routing/physics validation reaching 98% routing completion, 38.5 hours human cleanup vs a quoted 428 hours for equivalent manual layout, and boot on first power-up with no re-spins. Self-hostable/air-gapped. Sources: https://www.quilter.ai/blog/the-2026-guide-to-autonomous-pcb-design-quilter-vs-deeppcb-vs-flux-ai ; https://hw.dev/signal/autonomous-pcb-design-2026-guide/
- **DeepPCB (InstaDeep)** — cloud, AI-first RL routing engine integrating via API; focuses on geometric DRC (clearances, trace widths, via counts); public tier caps ~1,000 components / 2,200 pins; free tier + pay-as-you-go. Sources: https://deeppcb.ai/deeppcb-vs-quilter-open-source-routing-compared-2026/ ; https://www.protoflow.ai/compare/ai-pcb-autorouter-comparison
- **Flux.ai** — browser-native ECAD with AI copilot, Auto-Layout for simpler boards, schematic-through-routing breadth, firmware generation; Series B ($37M, 8VC, Feb 2026); examples ~40–100 components on 2–4 layers. Sources: https://www.atlaspcb.com/blog/ai-powered-eda-pcb-design-autonomous-agents-2026/ ; https://www.protoflow.ai/compare/best-ai-pcb-design-software-2026
- **Siemens Fuse EDA AI Agent** — orchestrates multi-tool placement/routing/SI/DFM. Others: JITX (code-driven), Celus/CircuitMind (design automation), Cadence Allegro X AI, Zuken AIPR.
- Honest caveat surfaced in the research: the board-level schematic benchmark HWE-Bench ("Can Language Models Perform Board-level Schematic Designs?", arXiv 2603.18102; 300 tasks over 2,914 IC datasheets) reports the top model reaching only an 8.15% overall pass rate and that models "lack physical intuition." Schematic/netlist generation automates well; full placement+routing of a mixed-signal board still needs a human pass.

**GNN / representation.** Netlists are naturally graphs; GNNs are used for congestion prediction, routability estimation, and as policy/value features in RL placement. Detailed-routing convergence via offline RL is an active 2025 arXiv topic (arXiv 2512.03594). LLM-based schematic generation (ChipGPT, LaMAGIC, AnalogCoder; VerilogEval/RTLLM for HDL) is emerging but immature for board-level analog intent.

### 7. Automated schematic design

**Design-as-code tools.**
- **SKiDL** (Python, MIT) — describe circuits in Python, run ERC, emit a KiCad netlist. Best for algorithmic/parametric circuit generation. Source: https://devbisme.github.io/skidl/
- **atopile** (`.ato` language, compiler/toolchain, MIT) — declarative modules, interfaces, units, tolerances, assertions; automatic parametric component picking; compiles to a `.kicad_pcb`; VS Code/Cursor extension. Source: https://github.com/atopile/atopile
- **tscircuit** (TypeScript/React for electronics) — experimental, small boards; JSX components. Source: https://hackaday.com/2025/04/30/layout-a-pcb-with-tscircuit/
- **JITX** (Julia-based, proprietary runtime) — code-driven design with solver-based automation.
- **CircuitJS** — simulation, not capture. **pcbdl** (Google, Python) — netlist-as-code.

**Constraint capture / schematic-to-constraint extraction.** The pipeline's leverage point: annotate nets with net classes and design intent in the schematic (e.g. `DDR3_DATA_LANE0`, `impedance=40`, `match_group=DQS0 ±25mil`), then extract these into router constraints automatically. KiCad 9 supports multiple net classes per net with cascading priority and component classes for grouping — a natural target for machine-generated constraints. Pin-swap/part-swap metadata (which DQ bits/lanes are swappable) should be captured at schematic time so the router/placer can exploit it. Source: https://docs.kicad.org/9.0/en/introduction/introduction.html

### 8. Signal-integrity verification & constraint derivation

**Impedance / field solving.** Closed-form (Wheeler/Hammerstad) equations give first-order microstrip/stripline Z; accurate work needs a 2D field solver. Open options: **atlc** (Arbitrary Transmission Line Calculator; C, GPL — finite-difference Z0/L/C/velocity plus odd/even/differential/common-mode Z for arbitrary 2-/3-conductor cross-sections; https://atlc.sourceforge.net/), **FEMM** (C++/pyfemm, Aladdin Free Public License — 2D FEM electrostatics → per-unit-length C → impedance; note AFPL is *not* a GNU/OSI license, with restrictions on commercial redistribution; https://www.femm.info/), and **RF2DFieldSolver** (dedicated open-source PCB cross-section impedance; https://github.com/jankae/RF2DFieldSolver). KiCad 9's PCB Calculator uses closed-form Transcalc equations (Atwater microstrip, Kirschning-Jansen coupled), *not* a numerical solver; its coupled-microstrip diff calc (Zdiff = 2·Zodd) is a known approximation (GitLab #9077), and no numerical field solver ships in KiCad 9 (integration request GitLab #12321 open). Sources: https://docs.kicad.org/9.0/en/pcb_calculator/pcb_calculator.html ; https://gitlab.com/kicad/code/kicad/-/work_items/12321

**Full-wave / SI simulation.** **openEMS** (C++ engine, Python/Octave interface, GPLv3) — 3D FDTD full-wave solver that "solves Maxwell's equations in discretized space and time"; https://github.com/thliebig/openEMS . **gerber2ems** (Antmicro) converts KiCad Gerbers → openEMS mesh for trace SI; https://github.com/antmicro/gerber2ems . **scikit-rf** (Python, BSD-3) — S/Z/Y network analysis, Touchstone, de-embedding, plotting; the natural post-processor for openEMS output; https://scikit-rf.org/ . Commercial: Mentor HyperLynx, Cadence Sigrity, Keysight ADS, Simbeor. (Note: "OpenEMS/openems" AGPL Java on GitHub is an unrelated *energy management* project — cite only thliebig/openEMS for the field solver.)

**IBIS / channel simulation.** IBIS models give I/V and switching behavior of driver/receiver pins for reflection/eye simulation. Open tooling: **pyibis-ami** (Python, BSD) and **PyBERT** (Python channel/BER simulator with IBIS-AMI; https://github.com/capn-freako/PyBERT), **pybis** (pure-Python IBIS *file* parser — does *not* parse AMI files; https://github.com/russdill/pybis), **ibisami** (public-domain C++ AMI model boilerplate; https://ibis.org/tools/tools.htm).

**Deriving timing budgets → tolerances automatically.** The algorithm: (1) parse controller and DRAM datasheets/IBIS for the data-valid window, tDQSQ, tDQSS, setup/hold; (2) subtract controller/DRAM internal skews and margins to get the board-skew budget in ps; (3) convert to a length tolerance using the specific layer's t_pd (√εeff/c); (4) emit as a net-class match rule. Example (Micron): allocate 10 ps of board skew → ~60 mils tolerance on inner-layer stripline ("For inner layer propagation, velocity is about 6.5 ps/mm. To match all traces within 10ps, traces must be held within a range of 1.5mm, 60 mils"). This is the concrete mechanism by which the tool *derives* rather than copies constraints.

**DRC as a constraint system.** KiCad 9's rule-based DRC engine (custom rules with wildcard net-class matching, per-layer padstacks, creepage/clearance, diff-pair gap/via spacing) is effectively a declarative constraint checker — the verification backstop for every automated decision. Source: https://www.kicad.org/blog/2025/10/KiCad-9.0.5-Release/

### 9. Teaching resources

- **Howard Johnson & Martin Graham**, *High-Speed Digital Design: A Handbook of Black Magic* (1993) and *High-Speed Signal Propagation: Advanced Black Magic* (2003) — the foundational transmission-line/SI texts.
- **Eric Bogatin**, *Signal and Power Integrity — Simplified* (3rd ed.) — the most implementer-friendly SI/PI book (PDN target impedance in Ch. 13); with Larry Smith, *Principles of Power Integrity for PDN Design — Simplified*.
- **Lee Ritchey**, *Right the First Time: A Practical Handbook on High-Speed PCB and System Design*.
- **Henry Ott**, *Electromagnetic Compatibility Engineering* — canonical EMC.
- **Rick Hartley** — PCB West / Sierra Circuits talks ("How to Achieve Proper Grounding", "How to Control Noise and EMI"); field-not-copper energy model; critiques of rules-of-thumb. https://www.youtube.com/watch?v=DcninUyq0Pw
- **VLSI physical design texts**: Kahng, Lienig, Markov & Hu, *VLSI Physical Design: From Graph Partitioning to Timing Closure* (2nd ed., Springer) — the modern algorithms bible (partitioning, placement, routing); Sherwani, *Algorithms for VLSI Physical Design Automation*; Sait & Youssef. NTU Yao-Wen Chang's course notes (global/detailed routing chapter, https://cc.ee.ntu.edu.tw/~ywchang/Courses/PD_Source/EDA_routing.pdf) are excellent free references.
- **Online**: Phil's Lab, Robert Feranec/FEDEVEL (OpenRex DDR3 layout), Sierra Circuits (Protoexpress) app notes, Altium/Cadence resource blogs, Signal Integrity Journal, JEDEC standards (JESD79-3/4/5).

### 10. Open-source projects

- **KiCad 9** (C++, GPLv3) — PNS push-and-shove router (walk-around/shove/highlight, diff-pair, length/skew tuning with time-domain Tuning Profiles in 9.x/10), rule-based DRC engine, S-expression file formats, IPC API (Protocol Buffers + NNG over sockets; PCB editor only in 9.0; headless via kicad-cli added in KiCad 11), legacy SWIG Python bindings, kicad-cli for plot/export. The primary integration substrate. Sources: https://docs.kicad.org/9.0/en/introduction/introduction.html ; https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/index.html
- **FreeRouting** (Java, GPL) — DSN/SES batch autorouter using A* maze + rip-up-reroute + 45°/free-angle; now has a Model Context Protocol (MCP) server so LLM agents can drive it; high routability, weak on dense SI-critical boards. Sources: https://github.com/freerouting/freerouting ; https://www.freerouting.app/
- **OpenROAD / OpenLANE** (C++, BSD) — full RTL→GDSII VLSI flow: RePlAce (placement), FastRoute (global), TritonRoute (detailed: pin access, track assignment, initial detailed routing, search-and-repair, DRC), TritonCTS, OpenSTA, OpenRCX. Algorithms transfer conceptually to PCB (negotiated congestion, track assignment, pin access) but the tools target IC LEF/DEF, not PCB. Sources: https://github.com/jkim971201/OpenROAD ; https://en.wikipedia.org/wiki/OpenROAD_Project
- **DREAMPlace** (Python/PyTorch/CUDA, BSD) — GPU analytical placer; reference implementation of ePlace/RePlAce.
- **Horizon EDA** (C++, GPLv3) — modern integrated EDA with a strong parametric/pool-based part model.
- **LibrePCB** (C++, GPLv3) — clean library model; simpler autorouting.
- **Toporouter** (in gEDA PCB, GPL) — open topological router.
- **Ecosystem/glue**: KiKit (panelization), pcbflow, pcb-tools (Gerber parsing), pcbdl, atopile, tscircuit, gerber2ems, RF2DFieldSolver, openEMS, scikit-rf.
- **Recent AI-routing research repos**: Google circuit_training (AlphaChip; https://github.com/google-research/circuit_training), plus 2025–2026 arXiv works (offline-RL detailed routing arXiv 2512.03594, 3D LineExplore multilayer PCB line-exploration in Nature Sci. Reports, Unet-Astar learned area routing).

## Constraint Tables (concrete numbers with sources)

**Table A — DDR3 length-match / skew (representative; always defer to the specific controller's guide).**

| Group | Rule | Source |
|---|---|---|
| DQ within a byte lane (to its DQS) | ±10 mil typical; ±5 mil for >1600 MT/s; some allow ±20–25 mil | NXP AN3940; TI SPRABI1; Micron |
| DQ–DQ intra-lane | ~2–10 mil practical | TI E2E / NXP |
| DQS / CK differential intra-pair | ±1–10 mil (≈1 ps) | TI SPRABI1; Altium |
| ADDR/CMD/CTRL to CLK | ±20 mil (±25 mil = 50 mil window common); NXP ±25 mil | NXP AN3940; TI |
| ADDR/CMD group internal | ±10 mil, stubs <80 mil (fly-by) | Xilinx UG586 |
| Byte-lane to byte-lane | not required to match (write leveling handles) | Xilinx UG586; Micron |
| Max trace length (controller→DRAM) | ~2–2.5" (series-R zone); ≤7" lead-in | TI SPRABI1; NXP AN3940 |
| Analog Devices SC59x DDR3 | DQ/DM ±40 mil to DQS; ADDR/CMD ±40 mil to CK; diff ±10 mil; max 2" | ADI EE-434 |

Sources: https://hands.com/~lkcl/eoma/rockchip_rk3288/AN3940.pdf ; https://www.ti.com/lit/pdf/sprabi1 ; https://manuals.plus/m/9523df23be4d4efa062c9f51e87bccea0fc6c6585567fbbfc9a645e72cb91ff6 ; https://e2e.ti.com/support/processors-group/processors/f/processors-forum/547347/ddr3-length-matching

**Table B — DDR3 impedance targets.**

| Signal | Single-ended | Differential | Source |
|---|---|---|---|
| DATA group (DQ/DQS/DM) | 40 Ω option (allows tighter spacing) or 50 Ω | 80 Ω (DQS) | NXP AN3940; UG586 |
| ADDR/CMD/CTRL | 50 Ω | — | Logic-Fruit/JEDEC |
| CLK | 50 Ω | 100 Ω | Logic-Fruit; TI |
| Spacing over like signals | 3× width (5 mil) / 2.5× (6 mil) | — | NXP AN3940 |
| Keep-out to memory clocks | ≥25 mil (0.635 mm) | — | Logic-Fruit/NXP |
| Edge-of-plane gap | ≥30–40 mil | — | NXP AN3940 |

Sources: https://hands.com/~lkcl/eoma/rockchip_rk3288/AN3940.pdf ; https://www.logic-fruit.com/wp-content/uploads/2021/09/DDR3.pdf

**Table C — Propagation delay / skew conversion (FR-4).**

| Medium | Delay | Source |
|---|---|---|
| Air/vacuum | 85 ps/in (3.33 ps/mm = 1/c) | physics (1/c); US Pat 7,436,267 |
| FR-4 stripline (εr≈4.5) | ≈180 ps/in (t_pd = 85·√εr) | US Pat 7,436,267 / 7,453,143 |
| FR-4 stripline (Micron inner) | ~6.5 ps/mm ≈165 ps/in | Micron TN 2013 |
| FR-4 microstrip (εeff≈2.8) | ≈140–150 ps/in (85·√(0.475εr+0.67)) | US Pat 7,436,267 / 7,453,143 |
| Anchor | 10 ps ≈ 60 mils ≈ 1.5 mm; 25 mil ≈ 4–4.5 ps | Micron / Cypress AN4065 |

Sources: https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7436267 ; https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7453143 ; https://www.analog.com/media/en/training-seminars/tutorials/MT-094.pdf

**Table D — Prototype fab (JLCPCB-class) DFM floor.**

| Parameter | Value | Source |
|---|---|---|
| Min trace/space | ~3.5 mil (0.09 mm) multilayer; 4 mil 4-layer; 6 mil 2-layer | JLCPCB |
| Min via hole | 0.15 mm | JLCPCB |
| Aspect ratio | ≤16:1 mech; HDI to 2.4 mm w/ 0.15 mm min hole | JLCPCB |
| Impedance tol | ±10% (≥50 Ω); ±5 Ω (<50 Ω); width trimmed ±20% | JLCPCB |
| Via-in-pad (POFV) | free on 6–20 layer | JLCPCB |
| Board thickness | 0.4–3.2 mm | JLCPCB |

Sources: https://jlcpcb.com/capabilities/pcb-capabilities ; https://jlcpcb.com/help/article/hdi-pcb-capabilities-faq ; https://www.schemalyzer.com/en/blog/manufacturing/jlcpcb/jlcpcb-design-rules

**Table E — BGA fan-out by pitch.**

| Pitch | Strategy | Trace/space | Notes | Source |
|---|---|---|---|---|
| ≥1.0 mm | dog-bone | ~5–10 mil | 1 trace/channel at 1.0 mm | AtlasPCB/JLCPCB |
| 0.8 mm | dog-bone (tight) / VIP | ~4 mil / 3.5 mil | ~0 channels at 4 mil → HDI often needed | PCBSync/JLCPCB |
| 0.65 mm | VIP recommended | 3–4 mil, ≥0.1 mm clr | confirm with fab | ALLPCB/NXP |
| ≤0.5 mm | via-in-pad, filled+capped | microvia ~6 mil | HDI/stacked/staggered | JLCPCB/NWES |

Sources: https://www.atlaspcb.com/blog/bga-fanout-routing-strategies-dog-bone-via-in-pad/ ; https://pcbsync.com/bga-pcb-design/ ; https://www.nwengineeringllc.com/article/bga-escape-routing-with-impedance-control-in-hdi-pcbs.php ; https://www.nxp.com/docs/en/application-note/AN10778.pdf

## Recommended Algorithmic Architecture (staged, with honest difficulty assessment)

**Stage 0 — Constraint extraction (SOLVED / high leverage).** Parse schematic net-class annotations + component classes; parse datasheets/IBIS for timing budgets; derive impedance targets, length-match tolerances (timing-budget → ps → mils via layer t_pd), diff-pair rules, keep-outs, PDN target impedance, and swap groups. Emit a machine-readable constraint DB feeding all later stages. *Classical + parsing/LLM assist; this is where an AI-EDA tool wins first.*

**Stage 1 — Stackup synthesis (SOLVED).** Choose symmetric 6–8 layer stackup; solve trace geometry for each impedance class with a 2D field solver (atlc/RF2DFieldSolver/openEMS) against fab prepregs; verify manufacturability. *Deterministic given fab library.*

**Stage 2 — Placement (PARTIALLY SOLVED; hardest to get "right" electrically).** Pre-place fixed items (connectors, mounting holes, BGA). Cluster by function; place DRAM in a fan-by arc off the controller; use analytical/force-directed (ePlace-style) seeding constrained by heterogeneity, thermal, and mechanical rules; refine with simulated annealing. Place decoupling caps at power pins as a post-step. *ML (RL/GNN) helps seed and predict congestion but is not trustworthy end-to-end; classical + constraints dominate.*

**Stage 3 — BGA fan-out / escape (SOLVED algorithmically, HARD at density).** Assign power/ground balls straight to planes; run ordered simultaneous escape (network-flow / SAT / ILP per Wong et al.) with layer assignment; co-optimize FPGA pin assignment with escape. *Deterministic optimization; "the last few pins" remain the practical failure mode — budget layers accordingly.*

**Stage 4 — Global routing (SOLVED).** Coarse GCELL routing with negotiated-congestion (PathFinder) cost including electrical penalties (crossing plane splits, reference discontinuity); produce route guides + congestion map; decide layer/via assignment. *Classical; well understood.*

**Stage 5 — Detailed routing (THE UNSOLVED CORE for SI-critical boards).** A*/maze + push-and-shove within guides, honoring impedance width, diff-pair gap, return-via placement, and clearance; iterate rip-up-reroute. Route buses/DDR lanes as topological bundles (river routing). *This is where every tool struggles; classical push-shove (KiCad PNS / TopoR topological) is the strongest base; RL is experimental. Expect human touch-up on the hardest ~5–15%.*

**Stage 6 — Length / skew tuning (SOLVED).** Insert serpentine/trombone meanders to meet per-net-class match tolerances in the time domain (KiCad time-domain tuning profiles). *Deterministic once topology is fixed.*

**Stage 7 — Verification loop (SOLVED to derive, PARTIAL to close).** Rule-based DRC (KiCad engine); impedance check (field solver); return-path/plane-integrity check; PDN target-impedance check (decap optimization); optional openEMS/scikit-rf full-wave + IBIS-AMI eye simulation on critical nets. Feed violations back to the relevant stage. *Verification math is solved; automatic *closure* (converging without human) is the frontier.*

**Where AI/ML helps vs. where classical dominates.** ML helps at: placement seeding, congestion/routability prediction (GNN), constraint extraction from datasheets (LLM), and candidate generation/ranking. Classical algorithms dominate at: escape (network flow/ILP), global routing (PathFinder), detailed routing (maze/A*/push-shove), length tuning, and all verification. The realistic near-term "100% automation" target is *low-to-mid-complexity boards end-to-end* and *high-value automation of the tedious-but-deterministic stages* (constraint derivation, fan-out, tuning, DRC) on hard boards, with a human reviewing the SI-critical detailed routing.

## Recommendations

1. **Build Stage 0 (constraint extraction) first** — it is the highest-leverage, most-solvable, and most-differentiating piece. Encode the timing-budget→tolerance derivation (Table C) so the tool computes rules from datasheets, not a hard-coded table. *Threshold to proceed: the tool reproduces UG583/NXP tolerances within ±10% from datasheet inputs alone.*
2. **Adopt KiCad 9 as substrate now, plan for KiCad 11 headless.** Use the IPC API for interactive control and kicad-cli for batch export; keep the constraint DB in KiCad net-classes/component-classes + custom DRC rules. *Threshold: full round-trip (constraints → route → DRC clean → export) automated.*
3. **Use classical algorithms as the routing backbone**; wrap FreeRouting (DSN/SES + MCP) and/or a PNS-driven flow for baseline, and prototype a PathFinder global router with electrical costs. Treat RL routing as research, benchmarked against these baselines. *Threshold to invest in ML routing: it must beat negotiated-congestion + push-shove on your own DDR3 test board on completion AND SI metrics, not just airwire count.*
4. **Implement escape routing as network-flow/ILP** (Wong et al.) with FPGA pin-swap co-optimization — a concrete, publishable, high-value win. *Threshold: solve the FG676 escape at target layer count with all pins escaped.*
5. **Wire in verification early**: RF2DFieldSolver/atlc for impedance, a return-path/plane-split checker, PDN decap optimizer, and openEMS+scikit-rf for spot-checking critical nets. Make verification a hard gate, not a report.
6. **Stage the ambition**: (a) auto-route simple 2–4 layer boards 100%; (b) auto-do the deterministic stages (constraints, fan-out, tuning, DRC) on the 8-layer DDR3 board with human detailed-routing review; (c) push detailed-routing automation on DDR lanes as bundles last. *Benchmark that would change the plan: if an RL/physics router demonstrably closes SI-clean DDR3 detailed routing unaided on your test board, promote it from research to pipeline.*

## Caveats
- **Length-match numbers vary by controller and speed grade.** Tables A/B are representative; the specific controller's guide (UG583/UG586, NXP, TI, ADI) and the actual data rate always govern. UG583 itself specifies constraints in picoseconds, which is the more fundamental form.
- **The 3W rule and many spacing "rules" are heuristics, not physics-exact.** Hartley/Bogatin show coupling depends on the spacing-to-dielectric-height ratio; over-constraining wastes layers. Flag folklore vs. field-derived numbers explicitly in the constraint DB.
- **AlphaChip's superhuman claims are disputed** (Cheng et al. ISPD 2023; Markov CACM 67(11), 2024; the arXiv 2302.11014 reassessment vs. DeepMind's arXiv 2411.10053 rebuttal). Do not assume RL placement beats tuned simulated annealing.
- **AI-PCB vendor benchmarks are self-published** (Quilter vs DeepPCB vs Flux comparisons are written by the vendors; Quilter's 843-component "Speedrun" figures are Quilter's own). Verify on your own boards; the HWE-Bench 8.15% end-to-end figure is the sober reality check. (Note: a distinct arXiv "HWE-Bench" is a hardware bug-repair benchmark — cite the schematic-design paper, arXiv 2603.18102.)
- **No open tool has a numerical field solver inside KiCad 9**; impedance from KiCad's calculator is closed-form and its diff-pair calc is a known approximation — use an external 2D solver for anything critical.
- **"100% automated place-and-route" for the reference 8-layer DDR3/BGA class is not achieved by any tool today** to full SI quality without human review of the hardest nets; the realistic near-term goal is full automation of the deterministic stages plus assisted detailed routing.
- Some sourced figures come from vendor blogs and forums (JLCPCB, Sierra Circuits, FEDEVEL, AtlasPCB, PCBSync); these corroborate primary vendor app notes but should be treated as secondary where they conflict with JEDEC/vendor datasheets. Several FR-4 delay-constant values were sourced from issued US patents (verbatim technical language) and the Analog Devices MT-094 tutorial; the exact tDQSQ/tDQSS numeric values should be pulled from the specific Micron DDR3 datasheet AC-timing table when precision is required.

---

### Glossary (acronyms defined inline above; consolidated here)
BGA (Ball Grid Array); DDR (Double Data Rate SDRAM); DQ (data), DQS (data strobe), DM (data mask), CK (clock), ADDR/CMD/CTRL (address/command/control); ODT (On-Die Termination); VTT (termination voltage, = VDDQ/2); SSTL (Stub-Series-Terminated Logic); POD/PODL (Pseudo-Open-Drain Logic); DBI (Data Bus Inversion); DFE (Decision Feedback Equalization); RCD (Registering Clock Driver); PMIC (Power-Management IC); SSN (Simultaneous Switching Noise); SI/PI (Signal/Power Integrity); PDN (Power Distribution/Delivery Network); ESL/ESR (Equivalent Series Inductance/Resistance); EMI/EMC (Electromagnetic Interference/Compatibility); DFM (Design for Manufacturability); DRC/ERC (Design/Electrical Rule Check); HDI (High-Density Interconnect); POFV/VIPPO (Plated-Over Filled Via / Via-In-Pad Plated-Over); NSMD/SMD (Non-Solder-Mask-Defined / Solder-Mask-Defined pad); PNS (Push-and-Shove, KiCad's router); DSN/SES (Specctra design/session interchange files); RSMT/OARSMT (Rectilinear Steiner Minimal Tree / Obstacle-Avoiding variant); ILP (Integer Linear Programming); SAT (Boolean Satisfiability); RL (Reinforcement Learning); GNN (Graph Neural Network); FDTD (Finite-Difference Time-Domain); IBIS/IBIS-AMI (I/O Buffer Information Specification / Algorithmic Modeling Interface); IPC API (KiCad's Inter-Process-Communication API); GCELL (global-routing cell); t_pd (propagation delay); εr/εeff (relative/effective dielectric constant).
