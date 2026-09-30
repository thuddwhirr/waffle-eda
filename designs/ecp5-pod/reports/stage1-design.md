# Stage 1, design: PASS

2026-09-30 05:22 UTC, 0.0 s.

## Waiting on the owner

- **the cost ceiling**: unknown: no price captured; every cost decision escalates to the owner: until a ceiling and prices are captured, every cost decision escalates (definition.md section 4)
- **owner review**: 'pending': the owner reads design.md and sets 'owner review' to 'accepted <date>' (an edit to the file is the owner's input)

## Criteria met

- the document parses: 'ECP5 power and programming pod'
- every locked constraint is explicit (size, cost, interfaces, features): size: at most 50 x 50 mm, cost: unknown: no price captured; every cost decision escalates to the owner, interfaces: usb on the left edge, fpga on the right edge, features: the capabilities above; USB power delivery left out (D153)
- the size limit is a number: at most 50 x 50 mm
- every interface has a stated position or is marked free: usb: left edge, centred; fpga: right edge, centred; indicator: free; mounting: free
- every positioned interface is named in the locked set: usb, fpga
- every block the interfaces and nets name is in Blocks, and every block is used: 78 blocks
- every net joins at least two pins: 49 nets, 257 pins
- no pin is on two nets
- a pin marked unconnected is on no net
- the fab profile exists: 'pcbway'; available ['pcbway']

## Numbers

- blocks: 78
- interfaces: 4
- nets: 49
- pins: 257
- max size mm: (50.0, 50.0)

## Files

- `design.md`

## Next

stage 2: bom.csv, one part per block
