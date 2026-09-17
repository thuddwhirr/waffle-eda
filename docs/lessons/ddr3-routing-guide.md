# Routing the DDR3 bus by hand — the requirements in plain language

This is what the DDR3 connection between the FPGA (U1) and the memory chip (U2) has to look like, written for
someone doing it for the first time in KiCad. The numbers come from the DDR3 rules used on every such board; the
project's design rules already enforce the hard limits, so KiCad's DRC will refuse anything that is actually illegal.
The remaining requirements are about *length* and *tidiness*, which DRC does not check but the report script does.

## Words used below

* **Ball, BGA.** Both chips are ball-grid arrays: their connections are a grid of solder balls under the package, 0.8 mm
  apart. A ball in the middle of the grid cannot be reached by a track drawn across the board.
* **Via.** A plated hole that carries a connection from one copper layer to another.
* **Escape stub.** The first few millimetres of every connection to a ball: a very short track from the ball into a gap
  between its neighbours, usually down a via to an inner layer, then straight out along a gap between two rows of balls
  until it clears the package. It ends in open board with nothing attached yet, hence "stub". Every DDR3 ball on both
  chips already has one; start routing from the stub's free end, never from the ball.
* **Net.** One electrical connection, whatever its name (DDR3_DQ5 is the net of data bit 5). **Net class**: a group of
  nets that share track width and spacing settings; KiCad applies them automatically.
* **Byte lane.** Eight data wires (DQ), their data-mask wire (DM) and their strobe pair, which travel and are timed
  together. This memory has two lanes.
* **Strobe pair (DQS).** DDR3 sends no clock with the data; each lane carries its own timing wire, the strobe, whose
  edges tell the receiver exactly when to read the eight data bits. That is why every data wire must be the same length
  as its strobe. The strobe is a **differential pair**: two wires, P and N, carrying opposite copies of the signal, laid
  side by side with a constant gap and equal length; the receiver compares them, which gives a sharp, noise-immune
  edge. The clock CK for the address/command group is a pair of the same kind.
* **Serpentine.** A wiggle drawn into a track to make it longer without moving its ends.

## What has to be connected

50 wires run between the two chips, in three groups, plus one clock pair:

| Group | Wires | What they are |
|---|---|---|
| Byte lane 0 | DQ0–DQ7, DM0, DQS0 pair (P and N) | 8 data bits, their "data mask", and the strobe that clocks them |
| Byte lane 1 | DQ8–DQ15, DM1, DQS1 pair | the same for the upper 8 bits |
| Address/command | A0–A15, BA0–BA2, RAS_N, CAS_N, WE_N, CS_N, CKE, ODT, RESET_N | tells the memory what to do and where |
| Clock | CLK pair (P and N) | the clock every address/command line is judged against |

Three small parts belong to the bus: R29 (100 Ω across the clock pair, right next to the memory chip), the ZQ resistor
R28 (240 Ω to ground, next to the memory chip), and the VREF divider. They are placed already; only the tracks are open.

## The rules, in order of importance

1. **Every wire goes straight from one chip to the other, no branches, no loops.** Point to point.

2. **Data must arrive with its strobe.** Inside a byte lane, all nine wires (DQ0–7 and DM0, or DQ8–15 and DM1) must be
   within **±0.5 mm** of the length of that lane's DQS pair. The two halves of the DQS pair must be within **0.3 mm** of
   each other. This is the one rule that decides whether the memory works.

3. **Address and command must arrive with the clock.** All 26 address/command wires within **±2 mm** of the clock pair's
   length; the two halves of the clock pair within **0.3 mm** of each other. Looser than the data rule, because the
   memory samples these lines only every other clock edge.

4. **Pairs travel together.** DQS0, DQS1 and CLK are each two wires that must run side by side on the same layer with a
   constant gap of **0.15 mm**, like railway tracks, from one chip to the other.

5. **Keep DDR3 wires apart from each other and from everything else.** Aim for a gap of **0.15 mm** between DDR3 tracks
   in the open board (the ButterStick reference runs 0.13 to 0.20 mm, D59); under the BGAs the fab minimum of 0.1 mm is
   what fits. DRC enforces 0.1 mm everywhere.

6. **Stay on the four signal layers: F.Cu, SIG2, SIG3, B.Cu.** Each of them has a solid ground plane next to it, which
   the signals need as a return path. Do not use the PWR layer for DDR3 wires.

7. **At most two vias per wire**, and the vias are already there: every DDR3 ball has a short escape stub leaving the
   BGA, on the DRAM's east side and the FPGA's west side, ending in the empty corridor between the chips. Start from
   those stub ends, not from the balls.

8. **Track widths come from the net classes** (0.10 mm inside the BGA areas, 0.13 mm on inner layers and 0.21 mm on the
   outer layers elsewhere). KiCad picks them up automatically when you route a net; you do not set them by hand.

## How the length rules are met in practice

A wire that is too short gets a **serpentine**: a wiggle drawn into a straight part of the track to add length. KiCad
has a tool for it (Route → Tune length of a single track, and Tune skew of a differential pair): you click the track,
move the mouse, and it draws the wiggles to the target length you set. Keep wiggles at least three track widths apart
and away from other wires.

A wire that is too long cannot be fixed with a wiggle; it has to be redrawn along a shorter path. That is the situation
of ten wires on the current board (see below).

The order that makes this easy: first draw all wires of a group as directly as possible, then read their lengths, then
add wiggles to the shorter ones until they match the longest. Never match to a wire that took a detour; redraw that one
first.

## Why the numbers are what they are

At the planned speed (800 million transfers per second) each data bit lasts 1.25 ns. A signal travels about 1 mm in
6–7 ps on this board, so ±0.5 mm is ±3.5 ps, a small fraction of the bit. The rules are stricter than the physics
strictly needs, which is normal for DDR3; if the memory is run slower (400–600 MT/s is plenty for a hobby computer) the
lane tolerance could be opened to ±2 mm without harm. The pair rules (0.3 mm) should be kept regardless.

## How to check

* KiCad shows a net's length in the status bar when a track of it is selected; the Net Inspector (Inspect → Net
  Inspector) lists every net's length in one table.
* `python3 hw/tools/route_report.py` writes `hw/route-report.md` with the three DDR3 tables (length of every wire
  against its strobe or clock, via count) and the list of open pads. Run it after every session.
* `kicad-cli pcb drc` (or the DRC button) confirms clearances, pair gaps and unconnected items.

## Where the current board stands

Everything is routed except the items in `hw/route-report.md`. For the DDR3 group specifically:

* Open: RAS_N (no path found), and ten power balls on the memory's east edge that need a via to their plane.
* Too long, must be redrawn shorter: DQ2, DQ6 (lane 0); DQ9, DQ11, DQ13, DQ15 (lane 1); A3, BA0, CS_N, ODT.
* Too short but no straight run for a wiggle, redraw with room for one: 19 wires, listed in the report.
* Pairs and clock: within tolerance.

The escapes, the ground planes, the clear corridor between the chips and the design rules are in place, so the manual
work is confined to the 12 mm wide corridor between U2 and U1 and the three groups above. A first-timer should expect
a weekend of careful work; the DRC stops anything illegal, and the report tells you when the lengths are right.
