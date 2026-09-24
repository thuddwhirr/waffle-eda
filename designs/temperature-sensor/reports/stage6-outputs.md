# Stage 6, outputs: PASS

2026-09-24 20:21 UTC, 2.7 s.

## Criteria met

- the shipped board is DRC clean under the specification's rules: electrical 0 , unconnected items 0
- every Gerber re-parsed: format, units, apertures, end mark; copper and outline draw something: temperature-sensor-B_Cu.gbr (1140 draws), temperature-sensor-B_Mask.gbr (6 draws), temperature-sensor-B_Silkscreen.gbr (6 draws), temperature-sensor-Edge_Cuts.gbr (8 draws), temperature-sensor-F_Cu.gbr (1731 draws), temperature-sensor-F_Fab.gbr (2028 draws), temperature-sensor-F_Mask.gbr (22 draws), temperature-sensor-F_Paste.gbr (16 draws), temperature-sensor-F_Silkscreen.gbr (166 draws)
- the drill files re-parsed: Excellon headers, and hole counts equal the board's: plated 14 of 14, non-plated 2 of 2; files ['temperature-sensor-NPTH.drl', 'temperature-sensor-PTH.drl']
- the position file lists every placed part with its side and rotation: ['C1', 'D1', 'J1', 'R1', 'R2', 'R3', 'U1'] against the board's ['C1', 'D1', 'J1', 'R1', 'R2', 'R3', 'U1']
- the vendor BOM re-parsed: every fitted part listed once, the vendor's columns: 6 lines for 7 parts: ['C1', 'D1', 'J1', 'R1', 'R2', 'R3', 'U1']
- the assembly drawing re-parsed as a PDF: temperature-sensor-assembly.pdf, 40873 bytes
- the stack-up note carries the layer count, thickness, copper, finish and impedance: temperature-sensor-stackup.md
- the IPC-D-356 netlist groups the board's pins exactly as the schematic's netlist does: 5 board nets against 5 schematic nets
- the vendor's checklist satisfied: every deliverable of the fab profile present and non-empty: gerbers: RS-274X, one file per layer, X2 attributes; drill: Excellon, plated and non-plated holes; position: pick-and-place: reference, value, package, x, y, rotation, side; mm; bom: manufacturer part number, manufacturer, quantity, designators, DNP; assembly_drawing: PDF: fab layer with references, and the outline; stackup_note: layer count, thickness, copper weight, finish, material; impedance targets when there are any; netlist: IPC-D-356, optional

## Numbers

- gerber layers: 9
- plated holes: 14
- non-plated holes: 2
- placed parts: 7
- bom lines: 6
- board nets: 5

## Files

- `out/gerbers/temperature-sensor-B_Cu.gbr`
- `out/gerbers/temperature-sensor-B_Mask.gbr`
- `out/gerbers/temperature-sensor-B_Silkscreen.gbr`
- `out/gerbers/temperature-sensor-Edge_Cuts.gbr`
- `out/gerbers/temperature-sensor-F_Cu.gbr`
- `out/gerbers/temperature-sensor-F_Fab.gbr`
- `out/gerbers/temperature-sensor-F_Mask.gbr`
- `out/gerbers/temperature-sensor-F_Paste.gbr`
- `out/gerbers/temperature-sensor-F_Silkscreen.gbr`
- `out/drill/temperature-sensor-NPTH.drl`
- `out/drill/temperature-sensor-PTH.drl`
- `out/temperature-sensor-positions.csv`
- `out/temperature-sensor-bom-pcbway.csv`
- `out/temperature-sensor-assembly.pdf`
- `out/temperature-sensor-stackup.md`
- `out/temperature-sensor.d356`

## Next

the owner reviews out/ (the assembly drawing, the layout render under reports/, the BOM) and the escalations of stages 1, 2 and 4; a fab order needs the prices
