"""The pipeline of `docs/definition.md` section 2 on a design directory (`docs/plan.md`, "Interface").

A design is `designs/<name>/`: `design.md` (stage 1), `bom.csv` (stage 2), `kicad/` (the schematic, stage 3,
and the board, stage 5, in one KiCad project) with `netlist.net` (stage 3), `spec.toml` (stage 4), `reports/` (every gate's report and render, the attempt
log) and `out/` (stage 6). Every stage reads the previous stage's files and writes its own; each ends in a
:class:`waffle_eda.design.gate.GateResult` written under `reports/`, which `scripts/design.py status` reads.
"""
