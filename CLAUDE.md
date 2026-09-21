# waffle-eda: rules for every session

Read `docs/definition.md` (the pipeline, its gates, the working agreement) and `docs/plan.md` (milestones,
reference ladder) before changing anything. Decisions and numbers go in `docs/decisions.md`.

## Definition of done

- A milestone is complete only when `python3 scripts/gate.py <milestone>` exits 0: every reference in its class
  passes in full. Partial results are failures.
- Never narrow a milestone's scope yourself. If the criteria look wrong, say so with evidence and ask; the owner
  decides, and the decision is recorded in the decisions log before scope changes.
- A failing case is a failure until it passes or the owner removes it from scope. Never call it "open",
  "remaining", "pending" or "a known limitation".
- Tests assert the target, never the level reached. A failing test stays red. Never lower an expected value, and
  never skip, disable or quarantine a test.
- A decision recorded in `docs/decisions.md` is settled. Do not re-raise it, re-research it, or ask the owner
  about it again, unless a new measurement contradicts it. Say what the measurement is.
- Deferred is not open. An item marked deferred is answered at the milestone that needs it and not before.
- Do not research vendor capability, price, lead time or reputation. This environment cannot reach the sources
  (D44), and the attempt has already failed once. Those numbers come from the owner.

## Reporting

- Open every milestone report with PASS or FAIL against the plan's criteria as written before the work. List every
  failing case first, with its blocker.
- Give the gate result and any recommendation as two separate statements. Never propose the next milestone in a
  report whose gate fails; state the failures and the options, and ask.
- Before starting a new milestone, show the gate output for the current one and wait for the owner's word.
- Close a milestone by checking every claim against the written criteria. When a tool fails three times on the
  same problem, stop and find the missing constraint or test.

## Mechanics

Python 3.11 with KiCad 9's `pcbnew`; `scripts/check_env.py` verifies it. Reference boards are fetched by
`scripts/fetch_references.py`, never committed. KiCad API pitfalls are documented in `waffle_eda/kicad/board.py`.
