# temperature-sensor: design document (stage 1)

The class A synthetic design of milestone A (plan.md): an I2C temperature sensor breakout, the same kind of board
as the `tinkerforge-temperature` reference. Owner's feature description, 2026-09-23: "a small board with an I2C
temperature sensor on a four-pin header, a power LED, two layers, as cheap as possible from PCBWay."

## Capabilities

* Measures temperature over I2C (7-bit address 0x48, ADD0 tied to ground), 3.3 V supply.
* Power indicator LED.
* Solder-in four-pin 2.54 mm header carrying 3V3, GND, SDA, SCL; the sensor's alert output is not brought out.

## Interfaces and positions

| Interface | Part | Position | Locked |
|---|---|---|---|
| I2C and power header | J1, 1x4 2.54 mm, vertical | west edge, pins running north to south, pin 1 north | yes |
| Power LED | D1 with R1 | east half, free | no |

Every other part position is free (definition.md, section 4).

## Locked set

| Constraint | Value |
|---|---|
| Maximum board size | 20 mm x 15 mm |
| Cost ceiling, parts per board | 5.00 USD (price: unknown until quotes are captured, D5) |
| Cost ceiling, bare board, 5 pieces | 20.00 USD (unknown, as above) |
| Fab and assembler | PCBWay, standard 2-layer 1.6 mm FR-4, HASL, `waffle_eda/fab/profiles/pcbway.toml` |
| Interface positions | the header on the west edge as in the table above |
| Feature set | the three capabilities above |

## Connectivity

The nets and pins are in [`connectivity.toml`](connectivity.toml), which stage 3 must match one to one. Pull-ups
of 4.7 kOhm on SDA and SCL, 100 nF decoupling at the sensor, the LED in series with 1 kOhm from 3V3 to ground.

## Free variables the tool may set

Part placement and rotation (within the locked header position), board size within the maximum, track width
and spacing within the fab's capability, via size within the fab's capability, and the pour outlines.

## Review

Owner review: pending. Every locked constraint above is explicit; every interface has a stated position or is
marked free.
