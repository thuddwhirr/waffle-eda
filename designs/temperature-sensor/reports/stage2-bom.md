# Stage 2, bom: PASS

2026-09-24 20:15 UTC, 2.4 s.

## Waiting on the owner

- **cost within the ceiling**: no price for ['U1', 'J1', 'C1', 'R1', 'R2', 'D1', 'R3']; ceiling unknown: no price captured; every cost decision escalates to the owner: prices come from the owner or a captured quote (definition.md section 4)
- **long-lead parts flagged**: lead time unknown for ['U1', 'J1', 'C1', 'R1', 'R2', 'D1', 'R3']: stock and lead time come from the assembler's quote

## Criteria met

- the BOM parses: 9 lines
- one part per block of the design: 9 blocks
- references are unique and well formed: U1, J1, C1, R1, R2, D1, R3, H1, H2
- every part is 'specific' or 'generic'
- every part has a symbol in KiCad's libraries: 9 symbols found under build/tools/kicad-symbols
- every part has a footprint in KiCad's libraries: 9 footprints found under build/tools/kicad-footprints
- every pin the design names is on the block's symbol
- every alternate named by symbol has the same pins and footprint
- every specific part has a datasheet reference and every generic part a specification
- every specific part has a manufacturer part number: TMP102AIDRLR (from the symbol's part name; confirm at order)
- every part names its schematic sheet (function group): host, indicator, mechanical, sensor

## Numbers

- parts: 9
- specific: 1
- generic: 8
- dnp: 0
- known cost: 0.0

## Files

- `bom.csv`

## Next

stage 3: the schematic and its netlist
