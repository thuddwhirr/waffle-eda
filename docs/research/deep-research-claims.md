# Deep research: automated routing of DDR3 buses, verified claims

The `/deep-research` run the owner asked for (2026-09-19, 103 agents, 5 search angles, 21 sources, 93 claims
extracted, 25 put to a three-vote adversarial check). Every claim below was confirmed by that check; none was
refuted. The run's own synthesis step never ran (the model hit an account limit), so the claims are recorded here
as the harness returned them, verbatim, each with its source and vote, rather than merged into prose. The earlier
hand-written report is `ddr3-bus-routing.md` and the owner's own report is `foundational-reference.md`; where they
disagree with a claim here, the claim's source is the primary document and wins.

Several sources could not be fetched directly: the egress policy denies IEEE Xplore, the ACM digital library,
doi.org, arXiv and their mirrors. Claims drawn from those carry a provenance note stating that the text is the
abstract as reproduced identically across several index entries, and that the body was not reachable. They are
weaker evidence than the vendor PDFs, which were fetched in full.

Counts: 22 confirmed, 0 refuted, 3 left unverified (the verification agents hit the same account limit).

## Confirmed claims

**1. (3-0)** Data byte-lane rules (Sec. 6.3.1.6, Table 6-4, p.19): every net in a byte lane (DQ[7:0], DM, DQS pair) must be length-
matched within ±10 mils (±0.254 mm, about ±1.8 ps at TI's own 180 ps/in), DQS/DQS# pairs within ±1 mil (±0.025 mm),
each data net may have at most two vias with identical via counts across the lane, the whole byte lane should sit on
one layer (so no mid-run layer changes, and p.16 forbids any mid-point via on data nets), data nets are point-to-point
with no VTT termination, and DQ bits inside a byte lane may be swapped for routing. This contradicts the measured
practice of matching data lanes on total length to <1 mm, pairs to 0.15 mm, and allowing three vias per data net.

> All nets in each data group must have same number of vias - maximum of two. The number per signal within each byte
> group must match. • All nets in a single byte-lane group should be routed on the same layer to eliminate the
> addition of length-skew from the via barrels. [...] • All data strobe pairs must be length-matched with ±1 mils of
> each other. • All nets within a single data group must be length-matched with ±10 mils. • Data bits within a byte-
> lane can be swapped to simplify routing. • Data group nets are routed point-to-point and do not have VTT
> terminations.

Source: <https://www.ti.com/lit/pdf/sprabi1>

**2. (3-0)** Address/command/control fly-by rules (Secs. 6.3.1.4-6.3.1.7, Tables 6-2/6-3/6-6, pp.18-20): fly-by (not T) is
mandatory for address, command, clock and control; each net is matched to the clock segment by segment, from the
controller to each SDRAM separately, within ±20 mils (±0.51 mm, about 3.6 ps), with the same via count in every
matched segment; stubs must be <80 mils (2.0 mm) and matched ±10 mils; CK/CK# pairs are matched ±1 mil per segment
with stubs <40 mils (1.0 mm); address lines may not be swapped. This is 12-24x tighter than the measured practice of
matching address/command only to 6-12 mm at the pins, and is defined per segment relative to CK rather than on total
length.

> All nets in the address and command fly-by groups must be length-matched from the controller to each SDRAM
> separately within ±20 mils of the clock along the same route. • All nets in the address and command fly-by groups
> must have the same number of vias in each length-matched segment. • Address lines cannot be swapped to simplify
> routing. • Address and command fly-by groups must have stubs less than 80 mils and be length-matched within ±10
> mils. [...] All clock pairs must be length-matched from the controller to each SDRAM separately within ±1 mils of
> each other. [...] Clock pair stubs must be less than 40 mils

Source: <https://www.ti.com/lit/pdf/sprabi1>

**3. (3-0)** Spacing and meander geometry (Sec. 6.3.1.3, pp.16-17): center-to-center spacing, explicitly including serpentine
(meander) segments, must be at least 5W (W = trace width); 4W is allowed only at or below 1066 MT/s; non-DDR3 nets on
the same layer need at least 6W separation; TI also recommends a minimum of four routing layers (two for
address/command/control, two for data), all long routes as stripline with microstrip limited to short BGA breakouts,
and all SDRAMs on the top side next to the SoC for single-rank designs. The 5W figure is a direct, stricter-than-3W
constraint on meander amplitude/pitch for an automated length-matching router.

> Center-to-center spacing, including serpentine, must be at least 5 W where W is the trace width. Additional spacing
> can be added between differential pairs and other routing groups to minimize crosstalk. Spacing of 4 W can be used,
> but is not appropriate for bus speeds over 1066 MT/s. [...] There must be additional separation of the DDR3 nets of
> at least 6W. [...] It is recommended that a DDR3 implementation make use of a minimum of four routing layers: two
> for address/command/control signals and two for data-group signals.

Source: <https://www.ti.com/lit/pdf/sprabi1>

**4. (3-0)** Termination and reference placement (Secs. 6.2.1, 6.3.1.8, 6.5, pp.14-15, 20-21, 28-29): address/command/control nets
are end-terminated after the last SDRAM in the fly-by chain with a 39 ohm (39.2 ohm) 1% resistor to VTT (VDDQ/2 = 0.75
V), the trace from the last SDRAM to the resistor must be at most 500 mils (12.7 mm) and the resistor must tie
directly to the VTT rail; each clock net gets a 39 ohm series resistor to a shared 0.1 uF capacitor to VDDQ (AC
termination); data nets use only ODT (RZQ/4 write termination, RZQ/7 read drive, 240 ohm RZQ per SDRAM); Vref is
decoupled at each SDRAM pin with 0.01 uF + 0.1 uF, routed 30 mil (0.762 mm) wide on the top layer with 15 mil (0.381
mm) clearance; the VTT island sits on the component-side layer with 0.1 uF per pin plus 10-22 uF bulk; 0402 parts
recommended. TI adds that external terminations may be unnecessary in short topologies but only full simulation can
decide.

> Each respective address and command net should be end-terminated using a resistor (in the range of 39 Ω to 42 Ω) and
> connected to VTT (preferred value is 39 Ω, 1%). VTT is defined as VDDq/2 or 0.75 V. [...] the parallel termination
> should be placed at the last SDRAM in the fly-by or daisy-chained architecture. Each trace to the respective
> termination should be ≤ within 500 mils and the opposite side of the termination resistor should tie directly to the
> VTT rail. [...] Traces between the decoupling capacitors and Vref pins should be a minimum of 30 mils (0.762 mm)
> wide and as short as possible. The Vref pins and interconnection to decoupling capacitors should maintain a minimum
> of 15 mils (0.381 mm) spacing from all other nets. All Vref nets should be routed on the top layer.

Source: <https://www.ti.com/lit/pdf/sprabi1>

**5. (3-0)** ISSI requires every DQ and DM in a byte lane to be routed on the same PCB layer as its DQS/DQS# pair and matched to
that strobe within ±10 ps, with a maximum trace-length difference of 50 mil (1.270 mm). The ps-to-length figures in
its table (10 ps = 50 mil, 2 ps = 10 mil, 50 ps = 261 mil) imply a propagation delay of about 192-200 ps/in, which is
slower than typical FR4 microstrip (140-150 ps/in) or stripline (about 170 ps/in); consequently ISSI's mm limits are
15-30% tighter than its ps limits would be on real FR4 (±10 ps would be ±1.5 mm on stripline and ±1.7 mm on
microstrip), and the 6.635 mm figure is internally inconsistent with 261 mil (6.629 mm) and with 50 ps at 200 ps/in
(250 mil, 6.35 mm).

> DQ and DM net groups should be routed with their respective DQS/DQS# and DM on the same PCB layer and matched within
> ±10ps, maximum difference of 50mils. DQS/DQS# should be used as the target trace propagation delay for the
> associated Data and data mask signals. ... Between signals within byte group (DQS,DM,8bits of DQ) ±10ps
> ±1.270mm(50mil)

Source: <https://www.digikey.com/en/pdf/i/issi/issi-ddr3-layout-guideline>

**6. (2-1)** Intra-pair skew for both the CK/CK# clock pair and each DQS/DQS# strobe pair must be within ±2 ps or a maximum of 10
mil (0.254 mm) between true and complement; differential clocks must be routed in parallel, kept short, on a single
layer, and placed on an internal layer. (The measured practice of 0.15 mm pair matching is inside this limit.)

> Overall routing lengths for these signals (CK/CK# & DQS/DQS#) should be controlled / matched to within ±2 ps or a
> maximum of 10mils between true and compliment signals. ... Between CK and CK#. Between DQSn and DQS#n ±2 ps ±0.254mm
> (10mil) ... 5. Differential clocks must be routed on the same layer and placed on an internal layer minimize the
> noise.

Source: <https://www.digikey.com/en/pdf/i/issi/issi-ddr3-layout-guideline>

**7. (3-0)** ISSI's cross-group tolerances are much tighter than the measured practice of 6-12 mm address/command matching: the
prose requires CK/CK# to be matched within ±5 ps of every DQS/DQS# pair (CK is the propagation-delay target for the DQ
groups) and the address/control group to be within ±10 ps of CK and ideally on the same layer as CK, while the summary
table separately allows ±50 ps / ±6.635 mm (261 mil) between signals within the address net, within the command net,
and between one byte group and another. The document is explicitly written for point-to-point applications, does not
mention fly-by or T-branch topology, write leveling, or the controller's per-lane deskew, and defers to the controller
vendor's guidelines where they add constraints.

> Route the CK/CK# clocks and set as the target trace propagation delays for the DQ net group. Match the CK/CK# clock
> to within ±5 ps of all DQS/DQS#. ... Route the address/control signal group ideally on the same layer as the CK/CK#
> clocks, to within ±10 ps skew of the CK/CK# traces. ... Between signals within address net. Between signals within
> commands net. Between one byte group and another byte group. ±50ps ±6.635mm(261mil)

Source: <https://www.digikey.com/en/pdf/i/issi/issi-ddr3-layout-guideline>

**8. (3-0)** Lattice's ECP5 DDR3/LPDDR3 rule for data lanes is a byte-group skew budget of +/-50 mil (+/-1.27 mm; about 7.5 ps
microstrip at 150 ps/in, about 8.5 ps stripline at 170 ps/in) between every DQ/DM and its own DQS, and the vendor
explicitly expects serpentine (meander) routing to be used to hit it. The document states this and all other
tolerances in mils only, never in ps. This is consistent with the measured practice of matching data lanes to under 1
mm.

> 9.2 Maintain a maximum of ±50 mil between any DQ/DM and its associated DQS strobe within a DQ group. Use careful
> serpentine routing to meet this requirement.

Source: <https://www.latticesemi.com/view_document?document_id=50482>

**9. (3-0)** Intra-pair matching for the DQS and CK differential pairs is +/-10 mil (+/-0.254 mm) in the DDR3 checklist, but the
same document's general layout section gives +/-5 mil (+/-0.127 mm) as the rule of thumb for differential pairs, so
the document is internally inconsistent by a factor of two. The measured practice of 0.15 mm pair matching satisfies
the +/-10 mil DDR3 rule but slightly misses the +/-5 mil general rule.

> 9.7 Differential pair of DQS to DQS_N trace lengths should be matched at ±10 mil. [...] 9.11 CK to CK_N trace
> lengths must be matched to within ±10 mil. [...] 7. For differential pairs, be sure to match the length as closely
> as possible. A good rule of thumb is to match up to ±5mils.

Source: <https://www.latticesemi.com/view_document?document_id=50482>

**10. (3-0)** Address/control signals must be length-matched to the CK/CK_N clock within +/-100 mil (+/-2.54 mm; about 15-17 ps),
and the lower and upper byte strobes (LDQS vs UDQS) must match each other within +/-100 mil. This contradicts the
measured practice of matching address/command only to 6-12 mm at the pins: that is 2.4x to 4.7x looser than Lattice's
stated tolerance. The checklist gives no separate figure for CK-to-DQS matching.

> 9.9 LDQS/LDQS_N and UDQS/UDQS_N trace lengths should be matched within ±100 mil. 9.10 Address/control signals and
> the associated CK and CK_N differential FPGA clock should be routed with a control trace matching ±100 mil.

Source: <https://www.latticesemi.com/view_document?document_id=50482>

**11. (3-0)** Lattice caps the number of vias per DDR data net at three between FPGA and memory, requires all nets in a data group
(DQ, DM, DQS) to have similar routing and identical via counts, and permits swapping DQ/DM pin assignments within a
data group (but never DQS) to ease layout. This supports the measured practice of at most three vias per data net and
gives a router a legal pin-permutation freedom within each byte lane.

> 9.1 DQ, DM, and DQS signals should be routed in a data group and should have similar routing and matched via counts.
> Using more than three vias is not recommended in the route between the FPGA controller and memory device. [...] 9.6
> Assigned FPGA I/O within a data group can be swapped to allow clean layout. Do not swap DQS assignments.

Source: <https://www.latticesemi.com/view_document?document_id=50482>

**12. (3-0)** The paper's stated contribution is a router that enforces both minimum and maximum (min-max) net length bounds during
routing, and it asserts that prior routing literature handled only maximum-length constraints with no sophisticated
algorithm guaranteeing minimum-length constraints (i.e. no principled way to reserve room for length-up/meandering).
PROVENANCE NOTE: ieeexplore.ieee.org and every mirror (dl.acm.org, experts.illinois.edu, researchgate,
semanticscholar, openalex, crossref, arxiv) were blocked by the network egress proxy; the quote is the paper's
abstract text as returned verbatim in search-engine index snippets of the IEEE/ACM DL/Illinois Experts records,
identical across five independent queries. Bibliographic correction for the parent: the DOI is
10.1109/TCAD.2006.882584 (IEEE document 4015547), TCAD vol. 25 no. 12 pp. 2784-2794; the conference version is ICCAD
2003 (IEEE document 1257808), not 2004.

> Although the problem of routing nets to satisfy maximum length constraints is a well-studied problem, there exists
> no sophisticated algorithm in literature that ensures that minimum length constraints are also satisfied. The
> authors propose a novel algorithm that effectively incorporates the min-max length constraints into the routing
> problem.

Source: <https://ieeexplore.ieee.org/document/4015547/>

**13. (3-0)** Tuning room is reserved DURING routing, not after detailed routing: the algorithm uses a Lagrangian-relaxation
framework to allocate extra routing resources (area for length extension) around each net simultaneously with routing
it, so meander space is a routing-stage decision rather than a post-route fix. (Abstract text via search-index
snippet; direct fetch blocked.)

> The approach uses a Lagrangian-relaxation (LR) framework to allocate extra routing resources around nets
> simultaneously during routing them.

Source: <https://ieeexplore.ieee.org/document/4015547/>

**14. (3-0)** The method includes a graph model whose purpose is to guarantee that every unit of routing resource allocated to a net
can actually be consumed by length extension (snaking) without violating design rules, i.e. reserved area is provably
usable for meanders rather than merely nominal. (Abstract text via search-index snippet; direct fetch blocked.)

> The authors also propose a graph model that ensures that all the allocated routing resources can be used effectively
> for extending lengths.

Source: <https://ieeexplore.ieee.org/document/4015547/>

**15. (3-0)** BSG-Route reformulates PCB length-matching routing as an AREA ASSIGNMENT problem: a given (already planar) routing
topology is embedded onto a Bounded-Sliceline Grid placement structure, and the BSG cells are then sized by
mathematical programming so that the total cell area occupied by each net equals the area implied by its target length
(wire modelled as a 'fat wire' of width = trace + spacing, so length = area / separation rule epsilon); snaking is
then realised inside the assigned area. Implication for router architecture: topology/ordering is decided BEFORE this
stage and tuning room (area) is allocated before detailed geometry is drawn. [Quotes from abstract and indexed body
excerpt; full PDF was egress-blocked in this session, so the excerpt may be the TODAES 2025 paper's restatement of
BSG-Route's method rather than BSG-Route's own wording.]

> The novelty of the work is viewing the length-constrained routing problem as an area assignment problem and using a
> placement structure, which is the bounded-sliceline grid, to help transform the area assignment problem into a
> mathematical programming problem. ... The BSG routing method firstly embeds the given topology onto a BSG, and then
> sizes the cells to make the total area of the cells occupied by a net satisfying its target length. The length of a
> wire is the area it occupies divided by a separation rule (ε) if regarded as a fat wire; therefore, instead of
> detouring wires to meet length bounds, an alternative is to assign area to nets such that the assigned area matches
> length bounds.

Source: <https://www.cecs.uci.edu/~papers/iccad08/PDFs/Papers/07A.1.pdf>

**16. (3-0)** BSG-Route claims to be the first length-matching router with no restriction on routing topology: earlier length-
matching routers (e.g., Ozdal & Wong's river-routing / single-layer bus routing work) all assume a specific topology
such as river or bus routing, whereas BSG-Route accepts any general planar topology. For a DDR3 tool this means the
length-tuning stage need not be confined to parallel river-routed bundles between two packages.

> Length-matching routing is a very important issue for PCB routing. Previous length-matching routers all have
> assumptions on the routing topology whereas practical designs may be free of any topological constraint. ... Unlike
> previous routers, the router does not impose any restriction on the routing topology.

Source: <https://www.cecs.uci.edu/~papers/iccad08/PDFs/Papers/07A.1.pdf>

**17. (3-0)** The paper formulates length-matching routing as two orthogonal stages: first assign a non-overlapping routing region
to each trace (i.e., reserve the tuning room per net before meandering), then meander each trace strictly inside its
own region to reach its target length. This is the 'what is decided before detailed meandering' split: region/area
assignment precedes meander synthesis, and the meander stage never leaves its region. (The region-assignment stage is
treated separately by the same group in the TODAES 'LP-Based Area Assignment for Length-Matching Routing of Complex
Multilayer PCBs with Any-Direction Wires' paper, DOI 10.1145/3795795.)

> The challenges can be addressed through two orthogonal stages: assign non-overlapping routing regions to each trace
> and meander the traces within their regions to reach the target length.

Source: <https://arxiv.org/abs/2407.19195>

**18. (2-1)** The paper's contribution is confined to the meandering (detailed) stage: an obstacle-aware detailed routing method
that adds length inside the assigned region while keeping the trace's original path/topology (it does not re-route the
net), with the objective of maximising use of the available space around obstacles. Search-index snippets of the paper
body describe the method as combining greedy, dynamic programming (DP) and computational geometry to meander the trace
while 'maintaining direction and limiting overriding changes in topology' (body text not verified verbatim, arxiv.org
blocked).

> In this paper, mainly focusing on the meandering stage, we propose an obstacle-aware detailed routing approach to
> optimize the utilization of available space and achieve length matching while maintaining the original routing of
> traces.

Source: <https://arxiv.org/abs/2407.19195>

**19. (3-0)** The paper decides length-matching 'tuning room' BEFORE detailed meandering: it converts length matching of any-
direction wires into an area-assignment problem in which the board is partitioned (grid/region division that discards
subregions too small for a detour) into subregions, a linear program assigns subregion area to each wire, and only
afterwards are wires detoured/meandered inside their assigned areas by a separate wire-detouring step. This is the
journal-stage counterpart of the group's DAC 2024 paper (Fang, Guo, Lin, Xiong, He, Xu, Chen, DOI
10.1145/3649329.3655915), which defined the same two-stage flow (assign non-overlapping routing regions, then meander
within them) and handled the meandering stage. [Provenance: DOI/ACM pages blocked by egress proxy; wording verified by
exact-phrase web searches returning the ACM record.]

> ...the initial PCB region into a set of subregions and ... an LP formulation to model the area assignment of
> subregions to the wires in sparse PCB layouts (exact-phrase verified); index-reported wording: the use of grids and
> region division aims at excluding subregions that are too small to accommodate wire detouring and the approach
> adjusts the wire topology according to the solution to obtain an area assignment solution, which can then be
> utilized with wire detouring methods to detour the wires within designated areas to achieve length matching

Source: <https://doi.org/10.1145/3795795>

**20. (3-0)** For dense boards and complex obstacles the plain LP is insufficient: the authors refine the LP for dense layouts, add
'utility constraints' modelling complex obstacles, and arrive at an ILP; because the ILP is too expensive, they
replace it with a combinatorial minimum-weight hierarchical-flow algorithm that they argue is near-optimal via LP
primal-dual analysis under upper-bound (area-cap) constraints, and that extends to lower-bound (minimum-area)
constraints by restricting augmenting-path search to paths whose minimum residual capacity exceeds a threshold.
Practical implication for a router: area/tuning-room reservation can be solved as a network-flow problem rather than a
general ILP.

> refine[s] the LP formulation for dense PCB layouts; utility constraints that consider complex obstacles and an
> Integer Linear Programming (ILP) model to optimize the subregion area assignment; a combinatorial algorithm based on
> minimum-weight hierarchical flow to efficiently tackle the area assignment problem; lower bounds handled by limiting
> the search for augmenting paths to those whose minimum residual capacity exceeds the specified threshold (all exact-
> phrase verified); index-reported: achieves near-optimal solutions even under upper bound constraints using LP
> primal-dual techniques

Source: <https://doi.org/10.1145/3795795>

**21. (3-0)** The area assignment carries an explicit feasibility guarantee usable as a router invariant: every subregion assigned
to a wire is large enough to host at least one detour of that wire, and all area assigned to a wire is actually usable
for its detouring (no unusable slivers). The method may also change a wire's topology (re-route it among obstacles,
guided by constrained minimum-weight hierarchical flows) to obtain a better area assignment, i.e. the pre-detour
planning stage is allowed to alter routing topology, not just reserve space along a fixed path.

> each assigned subregion (corresponding to the area assignment) can at least facilitate the detouring of a single
> wire, and it is guaranteed that all the assigned area of a wire is available for its detouring; modification of the
> wire topology to generate better area assignment solutions; adjusts wire topology among obstacles according to
> constrained minimum-weight hierarchical flows (exact-phrase verified)

Source: <https://doi.org/10.1145/3795795>

**22. (3-0)** PROVENANCE NOTE: ieeexplore.ieee.org and every mirror tried (ACM DL, doi.org, IEICE/J-STAGE/globals.ieice.org, Tokyo
Tech T2R2, U-Aizu, ResearchGate, Semantic Scholar, DBLP, arXiv, OpenAlex, Crossref, CiNii, CORE, Google Scholar, IA
Scholar, ADS, aspdac.com) are blocked by this session's egress policy (403 CONNECT denials, which the proxy README
says to report rather than route around). Quotes below are the paper's abstract, reproduced word-for-word identically
by the ACM DL, IEEE Xplore, IEICE and T2R2 index entries surfaced through WebSearch; the body text (algorithm details,
experimental tables) was not reachable. CLAIM: The CAFE router addresses exactly the detailed-routing sub-problem
relevant to DDR byte-lane tuning, namely routing many two-pin nets, each with its own target wire length, on a single-
layer routing grid containing obstacles; it does not perform layer assignment, via planning or escape routing, so in a
PCB router architecture it belongs after global routing and layer assignment have fixed each net to one layer between
two vias.

> CAFE router obtains routes of multiple nets with target wire lengths for single layer routing grid with obstacles.

Source: <https://ieeexplore.ieee.org/document/5419882/>

## Left unverified

The verification agents for these three stopped on an account limit; they are recorded as claims, not as facts.

**1.** CAFE's method is a greedy, net-by-net constructive extension: each net's route is grown from one pin toward the other
pin such that its length converges on the per-net target, rather than routing shortest paths first and adding meanders
afterwards. The 'connectivity aware' part of the name (expanded by the DAC 2024 obstacle-aware length-matching paper
as 'Connectivity Aware Frontier Exploration') refers to checking, while extending a route, that the remaining unrouted
nets can still be connected; this makes it a length-driven maze/frontier router with a feasibility guard, not a global
length-budgeting or ILP approach.

Source: <https://ieeexplore.ieee.org/document/5419882/>

**2.** Length matching alone does not guarantee matched arrival times: when a router produces dense meander (serpentine)
segments with small spacing between adjacent legs of the same trace, coupling between those legs of the same wire
makes the signal propagate faster (a 'speedup effect'), so two nets with identical physical length can still arrive at
different times. For an automated DDR3 router this means meander pitch/leg spacing must be a controlled design
variable, not just total length. (Direct fetch of arxiv.org was blocked by the egress proxy; quote taken from search-
engine-indexed text of the arXiv abstract, corroborated across several independent queries.)

Source: <https://arxiv.org/abs/1705.04983>

**3.** The paper's remedy is a post-route (post-processing) step, not a change to the router: it removes the dense meanders
from an already length-matched routing, then enlarges both the width (leg-to-leg distance) and the spacing of meander
segments and spreads them more evenly over the board, keeping the compensating wire length. This supports an
architecture where detailed routing/length tuning is followed by a meander-relaxation pass that trades free board area
for wider meander geometry.

Source: <https://arxiv.org/abs/1705.04983>

## Sources fetched

- <https://www.ti.com/lit/pdf/sprabi1>
- <https://www.digikey.com/en/pdf/i/issi/issi-ddr3-layout-guideline>
- <https://www.latticesemi.com/view_document?document_id=50482>
- <https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/DDR3-SDRAM-Routing-Constraints>
- <https://ieeexplore.ieee.org/document/4015547/>
- <https://www.cecs.uci.edu/~papers/iccad08/PDFs/Papers/07A.1.pdf>
- <https://arxiv.org/abs/2407.19195>
- <https://doi.org/10.1145/3795795>
- <https://ieeexplore.ieee.org/document/5419882/>
- <https://arxiv.org/abs/1705.04983>
- <https://dl.acm.org/doi/10.1145/1629911.1630000>
- <https://dl.acm.org/doi/10.1109/TCAD.2005.857376>
- <https://ieeexplore.ieee.org/document/6509593/>
- <https://ieeexplore.ieee.org/document/5450514/>
- <https://dl.acm.org/doi/pdf/10.1145/201310.201328>
- <https://github.com/bbenchoff/OrthoRoute>
- <https://dl.acm.org/doi/10.1145/1629911.1630001>
- <https://ieeexplore.ieee.org/document/10528693/>
- <https://github.com/drandyhaas/KiCadRoutingTools>
- <https://github.com/KiCad/kicad-source-mirror/blob/master/pcbnew/router/pns_meander.h>
- <https://github.com/tscircuit/bus-lanes-solver>
