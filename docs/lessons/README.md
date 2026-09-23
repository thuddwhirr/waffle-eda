# Lessons carried from `waffle-fpga`

Copied verbatim from `thuddwhirr/waffle-fpga`, branch `claude/ecstatic-feynman-0oiyyn`, commit
`9dc63f0656db2554ff5cc40bed9617599a823bed`. Every number in these documents refers to that board (ECP5 LFE5U-85F,
one DDR3L x16, PCBWay eight layers, 100 x 160 mm) and is evidence, not a rule for this project. Rules for this
project are stated in `../definition.md` and justified in `../decisions.md` with reference-board measurements.

| File | What it is | Why it is here |
|---|---|---|
| `tooling-project-brief.md` | The brief for this project, written at the end of the last one | the diagnosis, the measured references, the toolkit shape, the salvage list |
| `layout-practices.md` | The audit of 18 standard practices, with before and after | the checklist every layout tool is held to from the start |
| `ddr3-routing-guide.md` | The DDR3 bus rules in plain language | the bus and pair rules the router must meet and the report must check |
| `waffle-fpga-decisions.md` | The full decision log, D1 to D59 | D51 to D59 are what was tried on routing and why it failed |
| `stackup.md` | Eight-layer stack-up, impedance geometry, design rules | the starting point for the PCBWay fab profile |
| `power-tree.md` | Rails, budget, sequencing, decoupling plan | an example of what stage 1 and 2 must produce |
| `vendor-notes.md` | PCBWay capability and the rules derived from it | source of the fab profile numbers |
| `bom-notes.md` | Part selection rationale | an example of what stage 2 must produce |
| `block-diagram.md` | System block diagram, clock tree, boot sequence | an example of what stage 1 must produce |
