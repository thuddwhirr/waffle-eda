# waffle-eda: rules for working in this repository

This file is read at the start of every turn. It exists because a milestone was once reported as done while nine
reference balls still failed against the answer key (decisions D15). The rules below make that impossible to do
quietly. They apply to every session, human or agent.

## What this project is

A general-purpose, Claude Code driven pipeline from feature proposal to manufacturable design files, with zero
interactive routing. The definition, the six stages and their gates are in `docs/definition.md`; the milestones and
reference ladder in `docs/plan.md`; every decision, number and dropped attempt in `docs/decisions.md`; the measured
reference boards in `docs/references.md`. Read the definition and the plan before changing anything.

## Definition of done

- A milestone is complete only when `python3 scripts/gate.py <milestone>` exits 0: every reference board in the
  milestone's class passes the milestone's check, in full. Partial results are failures.
- Never narrow a milestone's scope yourself. If the criteria look wrong or unreachable, say so, with the evidence,
  and ask. The owner decides; the decision is recorded in `docs/decisions.md` before the scope changes.
- A case that fails is a failure until it passes or the owner removes it from scope in the decisions log. Never
  call it "open", "remaining", "pending", "a known limitation" or anything softer.
- Tests assert the target, never the level reached. A failing test stays red. Never lower an expected value to make
  a test pass, and never skip, disable or quarantine a test to get green.

## Reporting

- Open every milestone report with the word PASS or FAIL against the criteria in `docs/plan.md` as they stood
  before the work started. List every failing case first, each with what blocked it.
- Give the gate result and any recommendation as two separate statements. Do not propose the next milestone in a
  report whose gate fails; state the failures and the options, and ask.
- Before starting a new milestone, show the gate output for the current one and wait for the owner's word.
- Close every milestone by comparing your claims line by line with the written criteria; write down anything that
  does not match.
- Report numbers per stage, what failed, what was tried and dropped with numbers, and what is next. Do not narrate
  iterations. When a tool fails three times on the same problem, stop and find the missing constraint or test.

## Working agreement (from `docs/definition.md`, section 5)

- Measure the reference boards before writing a rule; state every rule with its evidence beside it.
- Build the benchmark before the tool. Never test a change only on the target board. Add a synthetic test with
  every new constraint, and check every constraint a tool imposes against the references before keeping it.
- A routing run ends complete, or fails with a diagnosis of the constraint that could not be met. It never hands
  back a list of nets for a human to finish in the interactive router.
- The tool changes placement, pin assignment, layers, via types and board size on its own, and asks the owner only
  about the maximum board size, material cost and agreed interface positions.

## Mechanics

- Python 3.11 with KiCad 9's `pcbnew` bindings. `python3 scripts/check_env.py` verifies the environment.
- Reference boards are fetched, never committed: `python3 scripts/fetch_references.py`. `build/` and `references/`
  are ignored by git.
- Measure and benchmark: `scripts/measure_references.py`, `python3 -m waffle_eda.bench.fanout_measure`,
  `scripts/bench_score.py`, `scripts/fanout_bench.py`, `python3 -m pytest -q`.
- KiCad pitfalls already paid for (see `waffle_eda/kicad/board.py`): `pcbnew.LoadBoard` returns None rather than
  raising; remove items with `board.Delete`, not `board.Remove`; a via's width needs a layer argument; refill zones
  before DRC, and refill in a child process (`waffle_eda/kicad/refill.py`) because the in-process filler can hang.
- Commit on the designated branch with clear messages; push when a piece of work is verified. Say plainly when
  something is not verified.
