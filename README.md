# waffle-eda

Goal: An automated, claude code compatable tool suite who's purpose is to take an idea from feature proposal to manufacturable design files, with zero intervention from a human on routing or schematic layout. 

Desired Outcome:
 - Take user description of desired features and refine it into a design document (capabilities, size, port layout, etc)
 - Take design document and build out a BOM (bill of materials), constrained by user's cost limits and manufacturer choice
 - Take parts list and build out a schematic (hopefully one a human EE could read and review)
 - Take design document, parts list and manufacturer choice and determine PCB charecteristcs (dimensions, layers, materials, via types, etc)
 - Place and Route loop: taking PCB specifications, schematic, and BOM: 
    - do a parts layout on the board. 
    - route traces
    - apply electric and design rule checks
    - revise as needed until completion, or fail with report of needed changes. 
 - Take completed PCB and BOM to create manufacturing files for upload to vendor.

## Definition

"Zero intervention" means zero interactive routing. The owner reviews outputs and decides design revisions; the tool
never hands back a list of nets to finish by hand. A routing run ends complete or fails with a diagnosis. The tool
may change placement, pin assignment, layer count, via type and board size on its own; it asks the owner only about
the maximum board size, material cost, and agreed interface positions. The full definition, the pipeline's six stages
and their gates, and the working agreement are in [`docs/definition.md`](docs/definition.md).

## Plan

One class of board at a time, the whole pipeline for that class before the next class is touched: class A (two
layers, a microcontroller, passives), then B (four layers, a USB pair, a switcher, planes), then B+ (a BGA with
no matched bus), then C (a BGA FPGA with DDR3). Each class is gated on every open-hardware reference board in
it and on one synthetic design taken to fab outputs. The interface is Claude Code, files, renders and reports; a
user interface is a separate project. See [`docs/plan.md`](docs/plan.md).

## Layout

| Path | What |
|---|---|
| [`docs/plan.md`](docs/plan.md) | the ladder, the milestones, what exists, and what the next session does |
| [`docs/definition.md`](docs/definition.md) | the project definition: stages, gates, acceptance rule, free variables and locked constraints |
| [`docs/decisions.md`](docs/decisions.md) | the decisions log: what the owner decided and what was measured |
| [`docs/references.md`](docs/references.md) | the reference boards, measured |
| [`docs/lessons/`](docs/lessons/README.md) | documents carried from `waffle-fpga`, with provenance |
| [`docs/research/`](docs/research/) | the DDR3 routing research; read when class C starts |
| [`docs/archive/`](docs/archive/README.md) | the first five days' plan, router spec and full log; not read at session start |
| `waffle_eda/` | the package: `kicad/` board helpers, `bench/` reference boards and scoring, `fab/` vendor profiles, `route/` routers |
| `scripts/` | entry points: environment check, tool and reference fetch, measurements, the gates, `design.py` (a design through the six stages, and its status) |
| `designs/` | design directories: `design.md`, `bom.csv`, `kicad/`, `netlist.net`, `spec.toml`, `reports/`, `out/` (the class A synthetic design, `temperature-sensor`) |
| `tests/` | unit tests; tests that need the reference boards or the fetched libraries skip when they are absent |
| [`salvage/waffle-fpga/`](salvage/waffle-fpga/README.md) | the previous project's tools, verbatim, for reference only |
| `references/` | the fetched reference boards (ignored by git; see the fetch script for licences) |
| `build/` | generated outputs (ignored by git) |

## Quick start

Needs KiCad 9 with its Python bindings on the interpreter that runs these scripts (`python3 -c "import pcbnew"`).

```sh
pip install -e ".[dev]"                     # z3-solver, numpy, shapely, pytest
python3 scripts/fetch_tools.py              # Freerouting, a Java 25, KiCad's symbol and footprint libraries, into build/tools/
python3 scripts/check_env.py                # KiCad 9, pcbnew, z3, Java, Xvfb, the libraries
python3 scripts/fetch_references.py         # clones the reference boards into references/
python3 scripts/gate.py a                   # the class A gate: strip each reference to placement, re-route, score
python3 scripts/design.py run temperature-sensor     # the class A synthetic design through the six stages to out/
python3 scripts/design.py status temperature-sensor  # each gate's state and what waits on the owner
python3 scripts/gate.py escape              # the BGA escape gate (class B+)
python3 scripts/gate.py busplan             # the bus plan gate (class C)
python3 scripts/rebuild_bench.py tinkerforge-temperature   # one board of the class A benchmark, with its files kept
python3 scripts/measure_references.py       # writes build/measure-<board>.json and prints a summary
python3 -m pytest -q -rs
```

## Status

2026-09-24. **Class A: both halves run green; the owner's review is what remains.** The class A gate passes on
all five references (every net routed, zero violations under each board's measured rules, 13 s to 7 min a
board) with Freerouting 2.4.1 inside the wrapper's repairs as stage 5's baseline. The synthetic
temperature-sensor design is through all six stages to fab outputs (`designs/temperature-sensor/out/`), every
gate PASS; it waits on the owner's review of its design document and outputs, and on prices, which are unknown
and escalated. The BGA escape gate (9 of 9 cases) and the bus plan gate (3 of 3 class C references) pass and
wait for classes B+ and C. The DDR3 bus routing is parked at 42 of 55 nets on ButterStick until then.
