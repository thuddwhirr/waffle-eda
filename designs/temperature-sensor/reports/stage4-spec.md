# Stage 4, spec: PASS

2026-09-24 20:15 UTC, 0.8 s.

## Waiting on the owner

- **price within the ceiling**: estimate unknown (the fab profile has no price model (D5); a quote comes from the owner or the vendor's order page); ceiling unknown: no price captured; every cost decision escalates to the owner

## Criteria met

- the layer count is one the fab offers: 2 of [1, 2, 4, 6, 8, 10, 12, 14]
- every rule within the fab's capability: track_width 0.25 (fab 0.1016), clearance 0.14 (fab 0.1016), via_drill 0.3 (fab 0.15), annular_ring 0.15 (fab 0.15), hole_clearance 0.25 (fab 0.229), edge_clearance 0.3 (fab 0.3)
- the clearance fits between the tightest pads of every footprint: clearance 0.14, tightest gap 0.15 on U1
- the via is a standard through via: 0.6 / 0.3 mm
- the outline is within the locked maximum: 24.5 x 14.5 mm of (25.0, 15.0)
- every part fits the outline with the edge clearance: U1 2.45x2.185, J1 3.59x11.21, C1 3.01x1.51, R1 3.01x1.51, R2 3.01x1.51, D1 3.05x1.59, R3 3.01x1.51, H1 4.95x4.95, H2 4.95x4.95
- every impedance target covered: no controlled-impedance net: I2C at 400 kHz and DC supply
- a stack-up for the layer count is in the fab profile: two_layer_1p6mm: core thickness and Dk unknown, not captured from the vendor; needed only for an impedance target

## Numbers

- layers: 2
- outline mm: [24.5, 14.5]
- rules: {'track_width': 0.25, 'clearance': 0.14, 'via_diameter': 0.6, 'via_drill': 0.3, 'hole_clearance': 0.25, 'edge_clearance': 0.3}
- tightest pad gap mm: 0.15
- courtyard area mm2: 117.6

## Files

- `spec.toml`

## Next

stage 5: placement and routing
