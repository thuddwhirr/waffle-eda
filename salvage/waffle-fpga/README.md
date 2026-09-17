# Salvaged from `waffle-fpga`

Verbatim copies from `thuddwhirr/waffle-fpga`, branch `claude/ecstatic-feynman-0oiyyn`, commit
`9dc63f0656db2554ff5cc40bed9617599a823bed`. Reference material only: nothing in `waffle_eda/` imports from here, and
these files expect the old repository's layout (`hw/`, `build/`, `pinmap.csv`) so most will not run in place. Each tool
is rewritten into the package with tests, against the reference boards, before it is used (decision D4).

What the brief (section 8) says to keep, and what it is:

| File | Keep as | Note |
|---|---|---|
| `hw/tools/gen_pcb.py` | placement generator, islands, stack-up, project rules | anchors, attractor placement, feed strips, 1V35 patch |
| `hw/tools/bga_escape.py` | fan-out | standard policy, `SKIP_NETS`, `ONLY_OPEN`, copper-aware commit |
| `hw/tools/fix_open_pads.py` | plane vias and gate | own connectivity, fills first, keep-outs |
| `hw/tools/fix_pwr_fill.py` | fill repair and report | pieces per rail |
| `hw/tools/ddr_bus.py` | bus router skeleton | z3 plan, negotiated lattice, corridor lines; converged one layer per run |
| `hw/tools/ddr_plan.py`, `ddr_swap.py`, `ddr_corridor.py` | reference only | earlier attempts, documented in D57 and D59 |
| `hw/tools/export_dsn.py`, `merge_ses_nets.py`, `staged_route.sh`, `rip_nets.py` | autorouter staging | PWR as plane, pinless nets |
| `hw/tools/ddr3_tune.py`, `route_report.py`, `stitch_vias.py`, `widen.py`, `power_widen.py`, `drc_cleanup.py` | finishing and checks | |
| `hw/tools/impedance.py` | impedance geometry for the PCBWay eight-layer stack | feeds the fab profile |
| `hw/tools/plane_vias.py`, `place_opt.py` | plane vias before routing; rotation scoring by ratsnest length | |
| `hw/tools/gen_sch.py`, `gen_lib.py`, `symlib.py`, `sexp.py`, `hw/design.py` | schematic generator (netlist style) and S-expression helpers | stage 3 will need a readable-schematic writer; these are the starting point |
| `pinmap/gen_pinmap.py`, `pinmap/check_nextpnr.py`, `pinmap/db/` | pin assignment validation against the prjtrellis device database (CC0) | |
| `hw/lib/ddr3_x16_balls.json` | DDR3 x16 FBGA-96 ball map | |

All 35 Python files parse under Python 3.11 (checked at import time, M0).
