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
python3 scripts/report_references.py        # regenerates docs/references.md from the measurements
python3 scripts/bench_score.py butterstick --answer   # strip the DDR3 bus and score the original copper
python3 scripts/survey_references.py owner/repo     # probe a candidate repository for KiCad boards
python3 scripts/make_synthetic.py                   # write the synthetic BGA-pair cases to build/synthetic/
python3 -m waffle_eda.bench.fanout_measure          # how each reference escapes its bus balls (build/fanout-*.json)
python3 -m waffle_eda.bench.constraints             # each reference's constraints as if agreed upstream (build/constraints-*.json)
python3 scripts/gate.py m2                          # the milestone gate: PASS or FAIL, one line per case
python3 scripts/fanout_bench.py synthetic butterstick logicbone   # strip, escape, gate and DRC
python3 scripts/plan_bus.py butterstick             # plan the bus and check the plan (M3a)
python3 scripts/plan_bus.py butterstick --reference # read the board's own routing back as a plan: the answer key
python3 scripts/bus_bench.py butterstick            # route the bus and score it (M3b)
python3 scripts/compare_net.py butterstick --failed # our copper under the reference's route, net by net
python3 scripts/fab_attribution.py butterstick logicbone   # what each board asks of a fab, and where
python3 scripts/segment_lengths.py orangecrab-r0.2.1 logicbone butterstick  # each leg as length and as delay
python3 scripts/rebuild_bench.py tinkerforge-temperature   # strip a whole board and score a re-route (M4)
python3 scripts/gate.py m4                          # the M4 gate: red until the general router exists
python3 -m pytest -q
```

## Status

M2, the fan-out, complete: an escape router on a quarter-pitch grid with negotiated congestion escapes every bus
ball on every bus reference (ButterStick in both revisions, LogicBone, OrangeCrab at 0.5 mm pitch, ULX3S on two
layers) and every synthetic case, with zero electrical violations under each reference's own constraints (gate M2:
9 of 9 cases; decisions D17 to D20); 23 reference boards registered and measured
([`docs/references.md`](docs/references.md)); the strip-and-score harness. See [`docs/plan.md`](docs/plan.md).

M3a, the bus plan, complete: `python3 scripts/gate.py m3a` PASS on all three class C references (OrangeCrab,
LogicBone, ButterStick). The planner routes on a grid whose lines are every package's own half pitch, so a ball, a
corner between four balls and a channel between two of them are all nodes of it and the grid stays monotone -- and
two orthogonal paths through disjoint nodes of a monotone grid cannot cross, which makes crossing-freeness a
property of the construction rather than something to check and repair. Each plan fixes every net's layer, via
site, bundle order and length room, and is checked in under a second (decisions D39 to D41).

M4, a full re-route of a whole board from placement, is the milestone in progress (D49): the owner took it ahead
of M3b because M4 feeds M5 and the first manufacturable board, while M3b feeds M6. Its benchmark is built and its
gate is red -- `python3 scripts/gate.py m4` FAIL, 0 of 6 class A references. That run predates the first
router, which is now written in `waffle_eda/route/board_router.py` and has never been executed. The benchmark strips every track, via and pour from a reference and keeps
placement, pads, outline and keepouts, which is what stage 5 of the pipeline is given; a candidate is scored on
every routable net connected and zero electrical violations under rules measured off that board. On all six class
A references the original copper scores 1.000 and the stripped board 0.000 (D50).

M3b, the routing inside the M3a plan, deferred rather than descoped (D49); M6 still requires it. The last reproducible bus routing, from before there was a plan to
route inside, is 42 of 55 nets on ButterStick with zero electrical violations; the 53 to 54 of 55 recorded on
18 September is not reproducible and the reason is only half understood (D33). What the measurement established:
the negotiation's plateau is an ordering problem, not a capacity one (D29, D31, D32); the bench's own spacing
setting had made every net contested by construction (D33); a bus package's escape belongs to the bus plan rather
than to M2 (D36); and a criterion two knobs can trade against each other is a criterion with a missing mechanism
(D41).
