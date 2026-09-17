# BOM notes — part selection rationale

Companion to `bom.csv` (session 4). Part numbers are proposals with alternates; "extended part" / "basic" refers to the JLCPCB assembly parts model, to be re-checked against the chosen assembler's stock at order time. KiCad column: symbols/footprints found in the stock 9.0 libraries, otherwise **CUSTOM** (list at the end).

## Major components

| Block | Choice | Why | Watch-outs |
|---|---|---|---|
| FPGA | LFE5U-85F-8BG381C | fixed by spec; -8 per D16 | 0.8 mm pitch BGA: 8-layer (D55), via-in-pad not required (dog-bone escape works at 0.8 mm; see stack-up session) |
| DDR3L | Micron MT41K512M16HA-107:A (8 Gbit x16, DDR3L-1866) | proven with LiteDRAM on ECP5 boards; JEDEC-standard FBGA-96 x16 ball map so Alliance/ISSI/Nanya are drop-ins | order the 7.5x13.5 or 8x14 body variant to match the chosen footprint; all alternates are 1.35 V parts |
| QSPI flash | W25Q256JVEIQ (WSON-8 8x6) | 32 MB as specified, quad-read for fast boot | ECP5 issues 3-byte addresses: bitstream(s) must live in the lower 16 MB; upper half for user data via 4-byte commands |
| System controller | STM32H743ZIT6 (LQFP-144) | FMC (27) + ULPI (12) + two UARTs + I2C + CEC + ~20 GPIO ≈ 70 pins; LQFP-100 has too few 5 V-tolerant/FMC pins free | pin-mux proposal below must be confirmed in CubeMX |
| USB host | USB3320C (ULPI) + USB2514B | both have KiCad/reference-design coverage, internal LDOs, 24 MHz crystals; the H743 OTG_HS needs an external ULPI PHY for 480 Mb/s | route ULPI as a 60 MHz bus (length-match ±5 mm) |
| PC uplink | FT2232HL | standard JTAG (openFPGALoader/OpenOCD MPSSE) + UART; channel B DTR/RTS to STM32 BOOT0/NRST | needs 93LC56B EEPROM to set channel A to MPSSE by default (optional) |
| Wi-Fi | ESP32-C6-WROOM-1U-N8 | as specified; SDIO 2.0 slave + external antenna | keep antenna connector on the back edge; module footprint is custom |
| Codec | TLV320AIC3204 | as specified; internal LDOs mean a single 3.3 V supply; MCLK from Si5351A | analog ground island under the codec and jacks |
| Clock generator | Si5351A-B-GT | as specified; 3 outputs | CLK0 to FPGA PCLKT7_1, CLK1 = MCLK, CLK2 spare |
| RTC | RV-3028-C7 | integrated 32.768 kHz, 45 nA; on 3V3_STBY | CR1220 backup with the RV-3028's own switchover |
| OLED | SSD1306 128x64 module on a 1x4 header | mechanical freedom for the enclosure | header pin order (GND VCC SCL SDA) differs between vendors: check |
| Board ID | 24AA02E48 | 2 kbit EEPROM plus a factory-unique EUI-48 usable as a MAC/serial | |
| LED register | 74HC595PW | D18 | /OE tied low; RTL refreshes after configuration |
| HDMI companion | TPD12S016 | ESD on TMDS, DDC/CEC level shifting to 3.3 V, HPD buffering, current-limited 5 V — removes the 5 V-tolerance requirement on the STM32 pins noted in `stm32-pin-plan.md` | LS_OE and CT_HPD from STM32 GPIO |

## Power parts

| Rail | Part | Why | Watch-outs |
|---|---|---|---|
| PD sink | CH224K | cheap, no firmware, CFG pins select 12 V with automatic fallback; PG output | STM32 senses VIN via ADC to learn the contract; STUSB4500 if NVM/I2C control is wanted |
| Input protection | TPS25947 eFuse | reverse-current blocking + current limit + inrush control on a 12 V rail | QFN-10 2x2 footprint is custom; simpler P-FET + polyfuse alternative listed |
| 5V_SYS | TPS54560B (60 V, 5 A), 400 kHz, 6.8 µH, 3 × 47 µF | margin for 4 A; KiCad symbol exists. Runs on every contract (EN 4.6 V / 4.1 V); on a 5 V-only source it is in dropout and 5V_SYS ≈ VIN − 0.3 V (D50; the LM66100 bypass of D38 was a 5.5 V part and is gone) | firmware must never enable buck and bypass together; bypass is the power-up default |
| 3V3 / 1V35 / 1V1 | 3x TPS563201 (3 A, SOT-23-6) | one part number, adjustable, KiCad symbol present; enough for 2.6 A / 1.2 A / 2.0 A peaks | no PG pin: TPS3839 supervisors build the enable chain (or swap to TPS62130-class parts with PG and drop the supervisors) |
| VTT/VREF | TPS51200 | standard DDR3 termination regulator; REFOUT for DRAM VREF and FPGA VREF1_3 | terminations optional (DNP) on a single-device point-to-point bus |
| 2V5 | AP2112K-2.5 | 600 mA LDO from 3V3, ±1.5 % meets VCCAUX ±5 % | |
| 3V3_STBY | AP2112K-3.3 from 5V_SYS | always-on, 600 mA covers the STM32 at full speed if it is ever run outside standby | |
| USB ports | 3x TPS2553 | adjustable limit via ILIM resistor + STM32 GPIO (0.5 A / 1.5 A), fault flag | |

## STM32H743ZIT6 pin-mux proposal (verify in STM32CubeMX before the schematic)

| Function | Pins (AF) |
|---|---|
| FMC_D[15:0] | PD14 PD15 PD0 PD1 PE7 PE8 PE9 PE10 PE11 PE12 PE13 PE14 PE15 PD8 PD9 PD10 (AF12) |
| FMC_A[7:0] | PF0 PF1 PF2 PF3 PF4 PF5 PF12 PF13 (AF12) |
| FMC_NOE / NWE / NE1 | PD4 / PD5 / PD7 (AF12) |
| ULPI (OTG_HS) | D0 PA3, D1 PB0, D2 PB1, D3 PB10, D4 PB11, D5 PB12, D6 PB13, D7 PB5, CK PA5, DIR PC2, NXT PC3, STP PC0 (AF10) |
| USART1 ↔ FT2232H ch B | PA9 TX, PA10 RX (AF7); BOOT0 pin driven by DTR through a transistor; NRST by RTS |
| USART6 ↔ ESP32-C6 | PC6 TX, PC7 RX (AF7); ESP BOOT strap PG2 |
| I2C1 ↔ TPD12S016 DDC | PB8 SCL, PB9 SDA (AF4) |
| HDMI CEC | PA15 (AF4, HDMI_CEC peripheral); HPD in from TPD12S016 on PG3 |
| Buttons | power PC13 (WKUP1), reset PE2, user PE3 PE4 PE5 |
| Power control | MAIN_EN PG4; PG_3V3 PG5, PG_1V35 PG6, PG_1V1 PG7; PD_PG (CH224K) PG8; VIN_SENSE PA0 (ADC1_INP16, divider 1/6) |
| USB switches | EN1..3 PG9 PG10 PG11; FAULT1..3 PG12 PG13 PG14; ILIM select PG15 |
| FPGA aux | DONE sense PE6, PROGRAMN drive (open-drain) PE1, FMC_IRQ PE0 (EXTI0), FMC_NRST out PB4 |
| ESP / misc | RTC INT PE15? (taken) → PB14; OLED not on STM32 |
| Debug | SWD PA13/PA14, SWO PB3; HSE 25 MHz PH0/PH1 |

Total ≈ 68 pins of 114 GPIO; no conflicts between FMC (PD/PE/PF), ULPI (PA/PB/PC) and USART1 at the alternate-function level as far as the H743 datasheet tables go — CubeMX must confirm.

## Custom KiCad symbols / footprints to draw

Symbols: DDR3L x16 FBGA-96 (generic JEDEC), W25Q256JVEIQ (derive from W25Q128JVE), USB3320C, TLV320AIC3204, TPD12S016, TPS25947, TPS2553, TPS3839, ESP32-C6-WROOM-1U, SSD1306 module header, 27 MHz XO (generic 4-pin).
Footprints: ESP32-C6-WROOM-1U, ESSOP-10 (CH224K), QFN-10 2x2 (TPS25947), SOT-23-5 24AA02E48 exists, WSON-8 8x6 exists.
