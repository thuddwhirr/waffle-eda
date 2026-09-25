# Stage 3, schematic: PASS

2026-09-24 20:15 UTC, 2.5 s.

## Criteria met

- every pin is on a net or marked unconnected, and every net joins two pins
- ERC clean: no error: 0 errors
- ERC clean: no warning: 0 warnings
- the netlist matches the design's connectivity one to one: 5 nets, 19 pins
- every part of the BOM is in the netlist with its footprint: C1 Capacitor_SMD:C_0603_1608Metric, D1 LED_SMD:LED_0603_1608Metric, H1 MountingHole:MountingHole_2.2mm_M2, H2 MountingHole:MountingHole_2.2mm_M2, J1 Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical, R1 Resistor_SMD:R_0603_1608Metric, R2 Resistor_SMD:R_0603_1608Metric, R3 Resistor_SMD:R_0603_1608Metric, U1 Package_TO_SOT_SMD:SOT-563
- sheets grouped by function, one sheet per group of the BOM: sensor: 4 parts, host: 1 parts, indicator: 2 parts, mechanical: 2 parts

## Numbers

- sheets: 4
- parts: 9
- nets: 5
- pins: 19
- unconnected pins: 1
- erc errors: 0
- erc warnings: 0

## Files

- `kicad/sheets/sensor.kicad_sch`
- `kicad/sheets/host.kicad_sch`
- `kicad/sheets/indicator.kicad_sch`
- `kicad/sheets/mechanical.kicad_sch`
- `kicad/temperature-sensor.kicad_sch`
- `kicad/temperature-sensor.kicad_pro`
- `kicad/sym-lib-table`
- `kicad/fp-lib-table`
- `netlist.net`
- `kicad/temperature-sensor-schematic.pdf`

## Next

stage 4: spec.toml
