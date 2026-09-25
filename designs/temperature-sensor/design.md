# Temperature-sensor breakout

The class A synthetic design of milestone A (`docs/plan.md`): the smallest board the pipeline takes from a
feature description to fab outputs. Drafted from the owner's one-line description in the plan ("a
temperature-sensor breakout: an I2C sensor, a four-pin header, decoupling, one LED, two layers"). The owner's
edits to this file are the design's input (`docs/definition.md`, sections 4 and 7): only the owner changes the
locked set below, and a review is recorded in the last section.

## Purpose

A breakout board carrying one digital temperature sensor on an I2C bus, for a host microcontroller on a
four-pin header. Two copper layers, parts on one side.

## Capabilities

| Capability | Detail |
|---|---|
| temperature | one I2C digital temperature sensor, 12-bit, 0.0625 degC resolution, 3.3 V supply |
| bus | I2C at up to 400 kHz; the sensor's address pin tied to ground; 10 kOhm pull-ups on the board |
| indicator | one power LED |
| supply | 3.3 V from the host through the header; 100 nF decoupling at the sensor's supply pin |

## Blocks

Every block is a part stage 2 chooses (`bom.csv`, one line per block). The pin names are the block's own;
stage 2's symbol must carry them, and stage 3 resolves each to a pin number on that symbol.

| Block | Function | Notes |
|---|---|---|
| sensor | I2C temperature sensor | pins SDA, SCL, ADD0, V+, GND, ALERT; ALERT is not used |
| header | 1x4 pin header, 2.54 mm, the host interface | pins 1 to 4: VCC, GND, SDA, SCL |
| cap | decoupling capacitor, 100 nF | at the sensor's supply pin |
| pullup_sda | 10 kOhm pull-up on SDA | |
| pullup_scl | 10 kOhm pull-up on SCL | |
| led | power indicator LED | |
| led_res | LED series resistor, 1 kOhm | about 1.5 mA at 3.3 V |
| hole1, hole2 | mounting holes, M2 | two opposite corners, no copper |

## Interfaces

A position is `free`, or an edge (`left edge, centred`; `bottom edge, 5 mm from left`). A positioned
interface is a locked constraint.

| Interface | Block | Signals | Position |
|---|---|---|---|
| host | header | VCC, GND, SDA, SCL | left edge, centred |
| indicator | led | | free |
| mounting | hole1, hole2 | | free |

## Connectivity

The design's connectivity specification, which the schematic's netlist has to match one to one (stage 3's
gate): every net with its pins as `block.pin`.

| Net | Pins |
|---|---|
| VCC | header.1 sensor.V+ cap.1 pullup_sda.1 pullup_scl.1 led_res.1 |
| GND | header.2 sensor.GND sensor.ADD0 cap.2 led.K |
| SDA | header.3 sensor.SDA pullup_sda.2 |
| SCL | header.4 sensor.SCL pullup_scl.2 |
| LED_A | led_res.2 led.A |

Unconnected: sensor.ALERT.

## Locked

Only the owner changes these (`docs/definition.md`, section 4). The tool asks about them only with evidence
that the best solution it found needs one crossed.

| Constraint | Value |
|---|---|
| size | at most 25 x 15 mm |
| cost | unknown: no price captured; every cost decision escalates to the owner |
| interfaces | host on the left edge |
| features | the capabilities above |

## Free

Placement, rotation and side of every part; the layer count (two layers expected for this class); track
width and spacing within the fab's capability; via type; board size within the maximum.

## Fab and assembly

| Item | Choice |
|---|---|
| fab profile | pcbway |
| assembler | PCBWay, turnkey |
| quantity | 5 |

## Review

| Item | State |
|---|---|
| owner review | accepted 2026-09-24, provisional: the fab outputs under out/ are still to be checked with the manufacturer (D75) |
