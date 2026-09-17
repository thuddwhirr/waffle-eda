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

## Layout

| Path | What |
|---|---|
| [`docs/definition.md`](docs/definition.md) | the project definition: stages, gates, acceptance rule, free variables and locked constraints |
| [`docs/plan.md`](docs/plan.md) | the reference ladder and milestones |
| [`docs/decisions.md`](docs/decisions.md) | the decisions log: what was decided, tried and dropped, with numbers |
| [`docs/lessons/`](docs/lessons/README.md) | documents carried from `waffle-fpga`, with provenance |
| `waffle_eda/` | the package: `kicad/` board helpers, `bench/` reference boards and scoring, `fab/` vendor profiles |
| `scripts/` | entry points: environment check, reference fetch, reference measurement |
| `tests/` | unit tests; tests that need the reference boards skip when they are absent |
| [`salvage/waffle-fpga/`](salvage/waffle-fpga/README.md) | the previous project's tools, verbatim, for reference only |
| `references/` | the fetched reference boards (ignored by git; CERN OHL, see the fetch script) |
| `build/` | generated outputs (ignored by git) |

## Quick start

Needs KiCad 9 with its Python bindings on the interpreter that runs these scripts (`python3 -c "import pcbnew"`).

```sh
pip install -e ".[dev]"                     # z3-solver, numpy, shapely, pytest
python3 scripts/check_env.py                # KiCad 9, pcbnew, z3, Java, Xvfb
python3 scripts/fetch_references.py         # clones the reference boards into references/
python3 scripts/measure_references.py       # writes build/measure-<board>.json and prints a summary
python3 -m pytest -q
```

## Status

M0, foundation. See [`docs/plan.md`](docs/plan.md) for what comes next.
