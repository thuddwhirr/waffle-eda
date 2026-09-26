# Class B review (2026-09-26)

**FAIL** against the criteria as written before the work: `python3 scripts/gate.py b` must exit 0 on every
reference in the class, and one synthetic class B design must go through all six stages to fab outputs the
owner reviewed. Neither has happened after four sessions on the class (PR #4 and the sessions of 2026-09-24
to 26; D77 to D114).

## Failing cases, each with its blocker

| Reference | Best row | Blocker |
|---|---|---|
| `upduino-v3.01` | 80 of 86, 1 clearance (the committed default: fixed feeds on a `power` plane, D85); 77 of 86 with whole, clean planes (D107's jar, the band, the via costs, ripup 400; D112) | The router's own insertion failures in the ring round U3 (QFN-48, 0.5 mm pitch), at the LED D3 and at the FLASH pins: the maze finds a path and the inserter's check rejects it against copper the shove cannot move ("insert trace failed at corner N/N", D88, D90, D109). The same 6 to 9 nets in every configuration. |
| `pico-ice-rev3` | 61 of 95, 1 clearance (D82, the old configuration; not re-measured since) | The same failure, 535 failed insertions in 20 passes, and the class A configuration did better (72), so the fed plane costs more than it gives there. |

## Numbers per stage (upduino, 30 passes)

| Configuration | Connected | Router unrouted | Electrical | Planes |
|---|---|---|---|---|
| Committed default (D85) | 80 of 86 | 36 | 1 clearance | whole by 96 feeds, 127 standing violations under the router's rules |
| Clean planes (D107 jar, band, via 20 and 2, ripup 400; D112) | 77 of 86 | 15 | 6 clearances | whole, 28 tracks on In1, none on In2 |
| Plane mode, stock jar (D99) | 77 of 86 | 12 | 10 clearances | 335 tracks through the GND plane |

Everything measured from outside the jar is measured out: nine feed forms (D85 to D101), the via cost (D103),
a via keepout band round the QFN (D104), per-layer trace costs (D97, D107), routing the hard nets first and the
reference's answer key (D106), the ripup ramp from 50 to 1600 (D110 to D114). Each moves the four-pass count;
none moves the 30-pass count out of 76 to 80. Inside the jar the shove's depths change nothing (D109). What is
left is the inserter's own rule, `FoundConnectionInserter`, a change deeper than one constant, and the jar is
now patchable one class at a time (`scripts/patch_freerouting.py`, D107).

## Option 1, taken and measured (D115 to D119, 2026-09-26)

The inserter's forced ripup of what blocks a failed segment: under the segment, no gain (D116); the router's
neckdown, a no-op on traces narrower than the pad (D117); the blockers found by shape, the failed insertions cut
by a third to a half at four passes (D118), and at 30 passes 69 of 86 with 5 clearances, the ripups re-opening
nets faster than they close them (D119). The line is spent. The remaining options are 2, 3 and 4 below.

## Options for the owner

1. **Work the inserter in the jar**, one session, by the patch script: on a failed insertion, rip up the
   blocking items of other nets and re-queue them instead of discarding the found path (the fork's own research
   note names the same failure). Measurable at four passes against 29 failed insertions (D107) and 39 (D111);
   the bar is the 30-pass row above 80. Effort inside a 5-line class: unknown until read.
2. **Accept the router's output plus hand-finishing of the residue.** 6 to 9 nets on upduino, the same ones
   every time, which a designer routes in minutes; the tool then documents what it left. This changes the
   definition of done, which is the owner's call, not a narrowing the work may make.
3. **Re-scope the class.** upduino's QFN ring and pico-ice's density may sit above the synthetic class B design
   the owner has in mind; the class is a class of boards, and its references decide its bar.
4. **Another router.** No fact about one is on disk; unknown until the owner names one.

The class A gate stays green under every change made (PASS 5 of 5 at each push); nothing of class B's is the
default for class A.
