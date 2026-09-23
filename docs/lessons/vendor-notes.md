# Vendor notes — PCBWay (decision D39 of `waffle-fpga-decisions.md`, the carried project's log, not D39 of `docs/decisions.md`)

Board is 8 layers, 100 × 160 mm Eurocard (D55/D56). Fabrication and turnkey assembly at PCBWay (owner has prior experience with them). Numbers below are from PCBWay's published capability pages (fetched 2026-09-10); confirm on the instant-quote page when ordering, since impedance control and via-in-pad are quoted under "Advanced PCB".

## Fabrication rules used for this design

| Rule | PCBWay standard capability | Value used in the design rules |
|---|---|---|
| Layers | 1–14 standard | 6 |
| Thickness | 0.2–3.2 mm | 1.6 mm |
| Outer trace / space, 1 oz | 0.1 mm / 0.1 mm (4/4 mil) | 0.125 mm / 0.125 mm (5/5 mil) general; 0.1 mm allowed only in the BGA escape region |
| Inner trace / space, 1 oz | 4 / 5 mil | 0.125 / 0.15 mm |
| Min drill | 0.15 mm | 0.25 mm (BGA dog-bone vias 0.25 mm drill / 0.5 mm pad) |
| Annular ring | 0.15 mm | 0.125 mm on BGA vias, 0.15 mm elsewhere |
| Via-in-pad, blind/buried | advanced (extra cost) | **not used**: 0.8 mm BGA escapes with dog-bones between pads |
| Controlled impedance | advanced, coupon per panel | **ordered**: 50 Ω SE and 90 Ω diff (USB), 100 Ω diff (TMDS, DDR3 CK/DQS); PCBWay provides the stack-up and target widths at quote time |
| Copper | 1 oz outer standard | 1 oz outer, 1 oz inner (0.5 oz inner acceptable if their 6-layer stack uses it; only affects trace widths) |
| Surface finish | HASL, ENIG, ENEPIG, … | ENIG (0.8 mm BGA, 0.5 mm QFN) |
| Solder mask | many colours | any; matte black or green |
| Material | FR-4 | FR-4 Tg ≥ 150 (TG150/170) for the BGA reflow |

## Stack-up

PCBWay's public stack-up page lists 298 standard builds but only details the 4-layer ones (1.6 mm: 0.5 oz outer plated to 1 oz, 7628 prepreg 0.196 mm Dk 4.74, 1.03 mm core Dk 4.6, 1 oz inner). The 6-layer 1.6 mm regular build and its impedance widths must be taken from PCBWay's online impedance calculator / quote page at order time; the stack-up session designs to a generic 6-layer 1.6 mm build (thin prepreg L1–L2 and L5–L6 for tight coupling to the ground planes) and re-tunes trace widths once PCBWay's numbers are in.

## Assembly

| Item | PCBWay capability | Use |
|---|---|---|
| Sourcing | turnkey from Digi-Key, Mouser, Arrow, Avnet; kitted parts accepted | turnkey; long-lead parts (ECP5, DDR3L, STM32H743ZIT6, USB3320C) to be confirmed in stock before ordering |
| Smallest passive | 0201 | 0402 used |
| BGA | supported, X-ray inspection available | request X-ray on the ECP5 and the DDR3L |
| Fine pitch | 8 mil | 0.4 mm SON (RV-3028) and 0.5 mm QFN fine |
| MOQ | 5 boards | 5 |
| Standard | IPC-610 Class 2 | Class 2 |
| Lead time | fab ≈ 1 week (6-layer + impedance), PCBA 3–5 days after parts | plan 3–4 weeks door to door including sourcing |

## Files to deliver at order time

Gerbers (RS-274X) + Excellon drill, IPC-356 netlist (optional), BOM in PCBWay's template (MPN, manufacturer, quantity, designators, DNP column), centroid/pick-and-place (mm, top/bottom), assembly drawing PDF, impedance requirement note (layers + target Ω + line widths), stack-up request (6-layer, 1.6 mm, 1 oz, ENIG, TG150+).

The `bom.csv` "stock_note" column uses JLCPCB's basic/extended wording from the earlier draft; for PCBWay it only matters whether Digi-Key/Mouser have stock.
