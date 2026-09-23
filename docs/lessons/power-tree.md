# Power tree

Session 3 deliverable. Rails, budget, regulator topology and sequencing. Regulator part numbers are candidates to be fixed in the BOM session.

## Input

USB-C on the back edge with a **USB PD sink controller** (candidate: CH224K, JLC-stocked; alternative STUSB4500 with I2C) requesting **12 V, fallback 9 V, fallback 5 V**. A 5 V/3 A source (15 W) cannot cover the worst case below, so the board runs with reduced USB-host port budget when only 5 V is negotiated; the STM32 measures VIN with an ADC divider and limits the port power switches accordingly (D29). On a 5 V contract the 5V_SYS buck would sit at 100 % duty and sag to ≈ 4.7 V, so an ideal-diode bypass (LM66100, U31) is switched in instead and the buck is disabled; the STM32 drives both from the CH224K contract status and never enables both at once (D38). Input protection: TVS on VBUS, reverse/over-current eFuse (candidate TPS25947 or a P-FET + polyfuse), bulk 2x 22 µF.

## Rails

| Rail | Voltage | Source | Loads | Est. typical | Est. peak | Regulator sizing (candidate) |
|---|---:|---|---|---:|---:|---|
| 5V_SYS | 5.0 V (≈ VIN − 0.3 V on a 5 V-only contract) | TPS54560B buck from VIN on every contract; at 5 V it runs at ~100 % duty (dropout), no bypass part (D50) | USB host port switches, HDMI 5 V, header 5 V, all downstream regulators | 1.5 A | 4 A | 4–5 A sync buck (TPS54531 / MP2315-class) |
| 3V3_STBY | 3.3 V | LDO from 5V_SYS, always on | STM32H743 VDD (Standby ≈ µA, run ≤ 300 mA), RV-3028, PD controller, power button | 5 mA (standby) | 300 mA | 500 mA LDO (AP2112K / TLV758) |
| 3V3 | 3.3 V | buck from 5V_SYS, MAIN_EN | FPGA VCCIO0/1/6/7/8, ESP32-C6, FT2232H, USB3320, USB2514B, codec (int. LDOs), OLED, Si5351A, flash, 2x SD, PMODs, header, 2V5 LDO input | 1.2 A | 2.6 A | 3 A sync buck (AP63203 / TPS563201-class) |
| 1V35 | 1.35 V | buck from 5V_SYS, EN from PG_3V3 | FPGA VCCIO2/3 (SSTL135 I/O, on-die terminations), DRAM VDD/VDDQ, VTT regulator input | 0.5 A | 1.2 A | 2 A sync buck |
| VTT | 0.675 V | DDR termination regulator from 1V35 (TPS51200) | address/command parallel terminations (if fitted), ±0.15 A | 0.05 A | ±0.3 A | TPS51200 (sink/source) |
| VREF (DDR + FPGA VREF1_3) | 0.675 V | TPS51200 REFOUT (or 1 % divider from 1V35) | DRAM VREFDQ/VREFCA, FPGA P16 | µA | — | RC-filtered, 0.1 µF at each load |
| 2V5 | 2.5 V | LDO from 3V3 | FPGA VCCAUX (PLLs, DDR/DIFF input buffers, pre-drivers) | 0.1 A | 0.3 A | 500 mA LDO, ±5 % per datasheet (2.375–2.625 V) |
| 1V1 | 1.1 V | buck from 5V_SYS, EN from PG_1V35 | FPGA VCC core (1.045–1.155 V) | 0.8 A | 2.0 A | 3 A sync buck, 1 % feedback, remote sense at the BGA |
| 5V_USB1..3 | 5.0 V | current-limited switches from 5V_SYS | three downstream USB host ports | — | 3x 0.5 A (1.5 A one port when VIN ≥ 9 V) | TPS2553 / AP22811 per port, ILIM set by STM32 |
| 5V_HDMI | 5.0 V | 5V_SYS via 55 mA limiter | HDMI pin 18 | — | 55 mA | small load switch or polyfuse |

Current basis: FPGA static currents from the ECP5 datasheet Table 3.8 (ICC 212 mA, ICCAUX 26 mA for the 85F) plus dynamic estimates for a LiteDRAM + soft-CPU + video design; DRAM from typical DDR3L x16 IDD (to be checked against the chosen part); STM32H743 at 480 MHz ≈ 250 mA; ESP32-C6 peaks ≈ 350 mA during Wi-Fi TX; SD cards 150 mA each; PMOD/header 100 mA per PMOD, 300 mA on the header. Run the Lattice Power Calculator once the RTL exists and revisit the 1V1 and 3V3 numbers.

Worst-case input power: 5 V loads ≈ 10 W (three ports at 0.5 A, HDMI, header) + 3V3 8.6 W + 1V35 1.6 W + 1V1 2.2 W ≈ 22 W before converter losses, ≈ 25 W at the input. Typical ≈ 9 W. Hence 12 V/9 V PD with 5 V fallback.

## Sequencing

Requirements taken from the Lattice documents:
- ECP5 POR monitors VCC (0.9–1.0 V), VCCAUX (2.0–2.2 V) and VCCIO8 (0.95–1.06 V) (datasheet Table 3.4); all other VCCIO must be valid before configuration; the datasheet recommends VCCIO before or together with VCC and VCCAUX (2.14.2); all supplies monotonic, 0.01–10 V/ms (Table 3.3).
- DDR3L: VDD/VDDQ before VTT and VREF; VREF tracks VDD/2; RESET# held low until power is stable (LiteDRAM handles the reset timing).

Sequence (enables chained by power-good outputs so it works without firmware, the STM32 only starts it):

1. VIN → 5V_SYS (always on: the buck starts at VIN 4.6 V on any contract, so 3V3_STBY comes up from any source; on a 5 V-only contract the STM32 keeps the USB host ports off because 5V_SYS is below the USB 4.75 V minimum) → 3V3_STBY (always on). STM32 boots, stays in Standby until the power button.
2. STM32 asserts MAIN_EN → **3V3** ramps (VCCIO 0/1/6/7/8, VCCIO8 for POR). 2V5 LDO follows 3V3 (VCCAUX).
3. PG_3V3 → **1V35** enable (VCCIO2/3 + DRAM). TPS51200 VTT/VREF follow 1V35.
4. PG_1V35 → **1V1** enable (FPGA core). FPGA POR releases when 1V1 and 2V5 are valid, configuration starts.
5. STM32 sees PG_1V1 and DONE, releases `fmc_nrst`.

Power-off: STM32 de-asserts MAIN_EN; all main rails discharge (bucks with output discharge or bleed resistors); 3V3_STBY stays up. Brown-out: STM32 monitors VIN and the PG lines, and can drop MAIN_EN cleanly.

## Decoupling plan (per rail, to be placed in the schematic session)

| Rail | At the ECP5 | Elsewhere |
|---|---|---|
| 1V1 (20 VCC balls) | 8x 100 nF 0402 under/next to the BGA, 2x 4.7 µF, 1x 47 µF bulk near the buck | — |
| 2V5 (4 VCCAUX balls) | 4x 100 nF, 1x 4.7 µF | — |
| 3V3 (2 VCCIO balls per bank 0/1/6/7/8 = 10) | 1x 100 nF per ball + 1x 4.7 µF per bank | 100 nF per chip supply pin, 10 µF per chip |
| 1V35 (4 VCCIO balls, banks 2/3) | 4x 100 nF, 2x 4.7 µF | DRAM: 100 nF per VDD/VDDQ ball group (≈ 10), 2x 10 µF; VTT: 2x 10 µF + 100 nF at each termination cluster |
| VREF | 100 nF + 1 µF at P16 | 100 nF at DRAM VREFDQ and VREFCA |

Reference: Lattice TN1068 (power decoupling) and the ECP5 hardware checklist FPGA-TN-02038 items 1.1–1.6.

## Layer stack implication (for the stack-up session)

Six layers: L1 signal, L2 GND, L3 signal (DDR3 addr / TMDS), L4 power planes (1V1 / 3V3 / 1V35 split), L5 GND, L6 signal. 1V1 and 1V35 need solid plane areas under the FPGA and DRAM respectively; the 3V3 plane covers the rest.
