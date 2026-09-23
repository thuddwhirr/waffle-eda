# How the references route their bus

Measured from the boards by `python3 scripts/measure_bus_design.py` (`waffle_eda/bench/bus_design.py`); the per-net
detail is in `build/bus-design-<key>.json`. Nothing here is assumed. A "path" is the copper from the controller's
pad to a memory or termination pad; "total length" is the net's whole copper, which is what KiCad reports and what
the designers matched. Meanders are stretches of a path that advance less than half their length over 1.5 mm.

## ButterStick (U4 controller, U11 and U12 memories, dual rank)

**Topology.** Data nets run from U4 to U12 first (12 to 17 mm at the pin) and on to U11 (25 to 31.5 mm); address
and command nets run to U11 first (22 to 24 mm) and on to U12 (31 to 36 mm). Each rank has its own clock pair,
CKE, CS and ODT (CK0, CKE0, CS0, ODT0 to U11; CK1, CKE1, CS1, ODT1 to U12); the clock pairs end on termination
resistors R67, R71, R93, R94 at 31.4 to 32.1 mm.

**Matching the designer achieved.**

| group | nets | total length | spread | at the memory pins | pairs |
| --- | --- | --- | --- | --- | --- |
| lane 0 (DQ0 to 7, LDQS, LDM) | 11 | 31.5 to 32.2 mm | 0.73 mm | U12 15 to 17 (2.0), U11 29 to 31.5 (2.2) | DQS0 0.04 mm |
| lane 1 (DQ8 to 15, UDQS, UDM) | 11 | 29.5 to 30.3 mm | 0.84 mm | U12 12 to 16 (3.7), U11 25 to 29.5 (4.2) | DQS1 0.00 mm |
| address, command, clocks | 32 | 30.6 to 38.6 mm | 7.95 mm | U11 22 to 34 (11.9), U12 31 to 38 (7.5) | CK0 0.00, CK1 0.03 mm |

The data lanes are matched on total net length to under a millimetre, each lane to its own strobe. The address and
command group is matched loosely (7.95 mm on total length, up to 9.6 mm from CK0 at U11's pins); its shortest
members are the per-rank control nets (CKE, CS, ODT at 30.6 to 33.7 mm), lengthened by meanders to about the clock's
length. RST is 43.6 mm and unmatched.

**Structure.** All 55 U4 balls use a via in the pad. The memory balls are escaped on the top layer into the empty
middle columns of the package, where the via sits: 72 of the 149 bus vias are in the hollows of U11 and U12, one is
in an array, 9 in the margins. 43 nets have three vias (U4 pad, one in each memory's hollow), 10 have two, CKE0 and
CKE1 have none (top layer throughout, 33.6 mm each). Between vias a run stays on one layer: lane 0 on B.Cu from U4
to U12 and on In5.Cu from U12 to U11, lane 1 on In2.Cu then In5.Cu, address on In2.Cu, In5.Cu or B.Cu, the clocks,
CS and ODT on B.Cu into U11's in-pad vias. Nets with at least a millimetre on a layer: F.Cu 45, In5.Cu 40,
In2.Cu 28, B.Cu 21.

**Where the routes enter.** U4 is left on its east side by 53 of 55 nets (B.Cu 19, In2.Cu 19, In5.Cu 10,
F.Cu 9). U11 is entered from the north 58 times, the south 31, the west 28 and the east 18: the routes come around
the memory, not straight in from the controller's side. U12 from the north 33 (the gap between the memories), the
west 26, the east 16.

**Where the length is made.** 182 mm of meander in 52 nets: U11's margin 59 mm, between U11's balls on the escape
layer 30 mm, U12's margin 23 mm, U11's hollow 20 mm, U12's hollow 13 mm, outside the packages 15 mm, U4's margin
12 mm. The largest: CKE0 16.6 mm (13.7 of it in U11's margin), DQ0 9.5, CKE1 9.3, CS0 9.2 (6.2 between U11's balls).

## LogicBone (IC1 controller, IC2 and IC3 memories, fly-by)

**Topology.** Address, command and clock run from IC1 to IC3 (19.5 to 26.1 mm), on to IC2 (30.9 to 37 mm) and end
on the termination networks RN1 to RN3 (30 to 37 mm); the clock pair ends on R15 and R16 at 37 mm. Data lane 0
goes to IC2 only, lane 1 to IC3 only.

**Matching the designer achieved.**

| group | nets | total length | spread | notes | pairs |
| --- | --- | --- | --- | --- | --- |
| lane 0 (DQ0 to 7, DQS0, DM0) | 11 | 13.2 to 17.3 mm | 4.15 mm | DQ0 to 7 alone 17.21 to 17.32 (0.11); DQS0 13.8, DM0 13.2 | DQS0 0.00 mm |
| lane 1 (DQ8 to 15, DQS1, DM1) | 11 | 12.4 to 19.5 mm | 7.1 mm | DQ8 to 15 alone 19.07 to 19.45 (0.38); DQS1 15.8, DM1 12.4 | DQS1 0.03 mm |
| address, command, clock | 27 | 32.1 to 43.5 mm | 11.4 mm | at IC3 19.5 to 26.1 (6.6), at IC2 30.9 to 37 (6.1); CK 38.3 | CK 0.15 mm |

The data bits are matched to each other within 0.4 mm; the strobe pairs and masks are 3 to 7 mm shorter than
their data and lie on inner layers. Address and command are within 3.6 mm of the clock at IC3 and 4.3 mm at IC2.

**Structure.** IC1's bus balls are escaped by dog-bones inside its array (27 vias there, 7 in its hollow), the
memories' likewise (29 in IC3's array, 25 in IC2's, 6 in the hollows). 16 nets have no via at all: every data bit
runs on the top layer from ball to ball. 25 nets have three vias, 3 have four (CK, RAS). Nets with at least a
millimetre on a layer: F.Cu 50, Sig2.Cu 22, B.Cu 20, Sig1.Cu 19, Gnd2.Cu 1 (ODT, 12 mm on the ground layer).

**Where the routes enter.** IC1 is left on its south side by 39 nets and its west side by 13. IC3 is entered from
the east 25, the west 15, the north 13, the south 13; IC2 from the west 24, the south 16, the north 7.

**Where the length is made.** 118 mm of meander in 33 nets, 78 mm of it outside the packages, in the space between
them; the rest inside IC3 (array 9, hollow 8, margin 8) and IC1's margin (5). The data bits carry most of it
(DQ9 9.9 mm, DQ13 7.5, DQ1 6.0, DQ11 5.6).

## What the two boards have in common, and where they differ

Common: data lanes matched to well under a millimetre on total length, differential pairs to a few hundredths,
address and command loosely (6 to 12 mm at the pins); every run between vias on one layer; at most three vias on a
data net; the memory's hollow and margins used for vias and meanders; the routes entering a memory from several
sides. Different: ButterStick escapes the memory balls on the top layer into the hollow and puts the via there,
LogicBone dog-bones inside the array; ButterStick makes its length inside and around the memories, LogicBone
between the packages; LogicBone runs every data bit on the top layer without a via.
