# Stack-up and design rules

Vendor: PCBWay (D39 of `waffle-fpga-decisions.md`, not of `docs/decisions.md`), **8 layers** (D55; was 6), 1.6 mm, 1 oz outer/inner copper, ENIG, FR-4 TG ≥ 150, controlled impedance ordered as PCBWay's "advanced" option. The numbers below are for PCBWay's published standard 8-layer 1.6 mm structure (#1 on their laminated-structure page, 1 oz/1 oz, ≥60 % inner residual copper, which our two full ground planes satisfy); PCBWay's field-solver check at quote time may nudge the widths by a few µm and `hw/tools/impedance.py` is the single place to change them (`gen_pcb.py` imports it for the net classes and stack-up block).

## Layer assignment

| Layer | KiCad name | Use |
|---|---|---|
| L1 | F.Cu | components, DDR3 DQ/DQS (short, direct to the DRAM), TMDS, USB pairs, BGA ring-1/2 escapes, general signals |
| L2 | In1.Cu (GND1) | solid ground reference for L1 and L3 |
| L3 | In2.Cu (SIG2) | DDR3 address/command/control, BGA ring-3 escapes, FMC bus, longer routes |
| L4 | In3.Cu (PWR) | power planes: 1V1 island under the FPGA, 1V35 island under DRAM + FPGA banks 2/3, 5V_SYS strip along the back, 3V3 elsewhere (routable outside the islands) |
| L5 | In4.Cu (GND2) | solid ground reference for L4 and L6 |
| L6 | In5.Cu (SIG3) | BGA ring-4/5 escapes, general signals (stripline between two grounds) |
| L7 | In6.Cu (GND3) | solid ground reference for L6 and L8 |
| L8 | B.Cu | BGA ring-4/5 escapes, coin cell, decoupling ring, general signals |

Dielectrics (PCBWay 8-layer structure #1, thickness after lamination): prepreg 2116 0.1195 mm Dk 4.45 (L1–L2, L7–L8), cores 0.23 mm Dk 4.6 (L2–L3, L4–L5, L6–L7), prepreg 7628 0.175 mm Dk 4.74 (L3–L4, L5–L6); outer copper 0.5 oz plated to 1 oz, inner 1 oz. Finished thickness 1.62 mm ±10 %.

## Impedance targets (from `hw/tools/impedance.py`, ±10 % closed-form estimates)

| Net class | Layer | Target | Trace width | Gap (diff) |
|---|---|---:|---:|---:|
| 50 Ω single-ended (clocks, SD, SDIO, FMC) | L1/L8 microstrip | 50 Ω | 0.212 mm | — |
| 100 Ω differential (TMDS, DDR3 DQS) | L1/L8 microstrip | 100 Ω | 0.158 mm | 0.150 mm |
| 90 Ω differential (USB 2.0) | L1/L8 microstrip | 90 Ω | 0.193 mm | 0.150 mm |
| 50 Ω single-ended (DDR3 addr/cmd, FMC) | L3 stripline (GND L2 / PWR L4) | 50 Ω | 0.129 mm | — |
| 100 Ω differential (DDR3 CK on L3) | L3 stripline | 100 Ω | 0.100 mm | 0.200 mm |
| 50 Ω single-ended | L6 stripline (GND L5 / GND L7) | 50 Ω | 0.129 mm | — |
| 100 Ω differential | L6 stripline | 100 Ω | 0.100 mm | 0.200 mm |

Dk values are PCBWay's 1 MHz figures, so the real impedance at signal frequencies is a few percent above the target; that is the conservative side. 0.21 mm 50 Ω lines still escape the 0.8 mm BGA (0.8 mm pitch, 0.4 mm pads leaves 0.4 mm between pads: one 0.10 mm track fits inside the `BGA` rule area, where 50 Ω is not held over the short escape).

## Design rules (PCBWay standard capability, `vendor-notes.md`)

| Rule | Value | Where set |
|---|---|---|
| Minimum clearance | 0.125 mm (5 mil); 0.10 mm inside the `BGA` rule area | project rules + `hw/waffle.kicad_dru` |
| Minimum track | 0.125 mm general; 0.10 mm inside `BGA` | same |
| Vias | 0.45 mm pad / 0.20 mm drill (BGA dog-bones, signal), 0.5/0.25 default, 0.6/0.3 power | project via table |
| Copper-to-edge | 0.30 mm | `.kicad_dru` |
| Hole-to-hole, hole clearance | 0.25 mm | project rules |
| Silk | 0.8 mm text; passive references moved to F.Fab (assembly drawing) | generator |
| Diff pairs | DIFF100 0.158/0.15, USB90 0.193/0.15, DDR3 CK on L3 0.100/0.20 | net classes + `.kicad_dru` |
| DDR3 length | DQ lanes 10–60 mm placeholder window; real matching (±25 mil within a byte lane, DQS to CK ±100 mil) is applied during routing with KiCad's tuning tool | `.kicad_dru` |
| Copper finish | ENIG | stack-up block in the board file |

Net-class membership is by wildcard pattern in `hw/waffle.kicad_pro` (`POWER`, `DIFF100`, `USB90`, `DDR3_DQ0`, `DDR3_DQ1`, `DDR3_AC`, `CLOCK`). The generator rewrites the project's net settings on every run because `kicad-cli` rewrites the project file.

## Board and floorplan (starting point, `hw/tools/gen_pcb.py`)

100 × 160 mm Eurocard 3U (D56), four M3 holes 4 mm from the corners; x across (100), y along (160), y = 0 back end panel, y = 160 front end panel. Front end panel (y = 160): USB-C host, headphone/line-out jack, line/mic-in jack, five right-angle buttons (power, reset, BTN0–2; body flush with the edge, actuator through the case wall) with the 11-LED row just behind them. Back edge (y = 0, the case back): USB-C power, USB-C uplink, 2x20 header, HDMI (TMDS on bank 6, D52) with the TPD12S016 behind it. Left edge: microSD ×2, stacked dual USB-A; hub port-4 and SWD headers inboard. Right edge: PMOD A–D. FPGA at (66, 52) rotated 180° (A1 front-right, D3), DDR3L at (38, 52) to its left, STM32 at the front-left facing FPGA bank 1 (FMC) with the coin cell on the back side under it, USB PHY between the STM32 and the FPGA, hub between the STM32 and the left-edge USB ports, FT2232H behind the uplink connector, power block back-right, codec at the front-left by the jacks, clock generator front-centre, ESP32-C6 module in front of the FPGA (bank 0 side), 74HC595 behind the LED row, TPD12S016 next to the HDMI connector. FPGA decoupling is on the back side in a ring around the ball array; other passives are grid-placed inside their function block.

**Routing status:** both BGAs fanned out deterministically, planes and power copper placed, four autorouter rounds plus scripted finishing; 241 connections (139 pads) still open in the densest regions and need an interactive rip-up pass in KiCad. `hw/route-report.md` lists them. See D51/D53/D54.

DRC on the routed board (`build/drc.rpt`): 2 clearance errors (0.088 mm), 199 narrow power segments, 4 diff-pair-gap warnings, the expected dangling-stub and unconnected items, silk overlaps left for the layout pass.
