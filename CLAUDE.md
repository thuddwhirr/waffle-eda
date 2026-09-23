# waffle-eda: rules for every session

Read `docs/plan.md` first, starting with "Next session starts here", then `docs/definition.md`. Decisions and
numbers go in `docs/decisions.md`. Do not read `docs/archive/` unless a specific entry is cited.

## Session

- **Start** by running the current class's gate and the tests, as the plan's next-step section says. The state
  of the project is what the gate prints, not what any document says.
- **End** with the gate output, a commit, and the next-step section updated in the same commit.

## Definition of done

- A milestone is a class of board (`docs/plan.md`). It is complete only when `python3 scripts/gate.py <class>`
  exits 0 on every reference in the class and one synthetic design of that class has gone through all six
  stages to fab outputs the owner reviewed. A plan, an escape, a spec or a partial route is never a milestone.
- Every lower class's gate stays green. Run them before pushing a change to shared code.
- Never narrow a milestone's scope yourself. If the criteria look wrong, say so with evidence and ask.
- A failing case is a failure until it passes or the owner removes it from scope. Never call it "open",
  "remaining", "pending" or "a known limitation".
- Tests assert the target, never the level reached. Never lower an expected value; never skip, disable or
  quarantine a test.
- A decision in `docs/decisions.md` is settled. Do not re-raise it unless a new measurement contradicts it, and
  then say which.

## How to change things

- A failing board gets a failing gate or test case first, then the smallest change that passes it and keeps
  every lower class green. A stage is never re-architected because of one board.
- Each stage uses the cheapest existing tool that passes the class. Own code is written where a measurement
  shows the baseline fails, and only for what fails.
- When a tool fails three times on the same problem, stop and find the missing constraint or test.
- A class not passed after four sessions gets a written review with options for the owner, not a fifth iteration.
- Facts from outside this repository (vendor capability, price, lead time, a datasheet not on disk) come from
  the owner or are marked unknown. No research rounds, no agent fan-outs against the network.

## Writing

- A decision entry is an owner's decision or a measurement (number, commit, script). Ten lines at most.
  Recommendations, proposals and narrative go to the owner in chat, not in the log.
- A specification is one page and is written after the code runs, not before.
- A report opens with PASS or FAIL against the criteria as written before the work, lists every failing case
  first with its blocker, gives numbers per stage and what is next. Do not narrate iterations. Give the gate
  result and any recommendation as two separate statements.

## Mechanics

Python 3.11 with KiCad 9's `pcbnew`; `scripts/check_env.py` verifies it. Reference boards are fetched by
`scripts/fetch_references.py`, never committed. KiCad API pitfalls are documented in `waffle_eda/kicad/board.py`.
