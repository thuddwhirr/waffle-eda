# Stage 1, design: PASS

2026-09-24 19:45 UTC, 0.0 s.

## Waiting on the owner

- **the cost ceiling**: unknown: no price captured; every cost decision escalates to the owner: until a ceiling and prices are captured, every cost decision escalates (definition.md section 4)
- **owner review**: 'pending': the owner reads design.md and sets 'owner review' to 'accepted <date>' (an edit to the file is the owner's input)

## Criteria met

- the document parses: 'Temperature-sensor breakout'
- every locked constraint is explicit (size, cost, interfaces, features): size: at most 25 x 15 mm, cost: unknown: no price captured; every cost decision escalates to the owner, interfaces: host on the left edge, features: the capabilities above
- the size limit is a number: at most 25 x 15 mm
- every interface has a stated position or is marked free: host: left edge, centred; indicator: free; mounting: free
- every positioned interface is named in the locked set: host
- every block the interfaces and nets name is in Blocks, and every block is used: 9 blocks
- every net joins at least two pins: 5 nets, 19 pins
- no pin is on two nets
- a pin marked unconnected is on no net
- the fab profile exists: 'pcbway'; available ['pcbway']

## Numbers

- blocks: 9
- interfaces: 3
- nets: 5
- pins: 19
- max size mm: (25.0, 15.0)

## Files

- `design.md`

## Next

stage 2: bom.csv, one part per block
