# ECP5 power and programming pod

The class B synthetic design of milestone B (`docs/plan.md`, D153): the power and programming section of the
owner's class C target, the ECP5 + DDR3L board (`docs/lessons/tooling-project-brief.md` section 2), as a board of
its own. It takes 5 V from USB-C, makes the four ECP5 supply rails in the order `docs/lessons/power-tree.md` sets,
and gives the FPGA JTAG and a UART through an FT2232H, all on one header to an FPGA board. It is a module for
bringing up an ECP5 board (the owner's, or a bought one), and its blocks come back in the class C board. Drafted
from the owner's choice of 2026-09-30 and the target's own notes (`power-tree.md`, `block-diagram.md`,
`bom-notes.md`); the owner's edits to this file are the design's input (`docs/definition.md`, sections 4 and 7).

## Purpose

A four-layer board, parts on one side: USB-C in (5 V, USB 2.0 data), an FT2232H as JTAG programmer (channel A,
MPSSE) and UART (channel B), three synchronous bucks for 3.3 V, 1.35 V and 1.1 V, an LDO for 2.5 V, supervisors
that chain the enables, and a 2x12 header carrying the rails, JTAG, the ECP5 configuration pins and the UART to
the FPGA board. The routing problem is class B's: a 0.5 mm pitch QFN, a USB 2.0 pair, switching regulators with
their current loops, a ground plane.

## Capabilities

| Capability | Detail |
|---|---|
| input | 5 V from a USB-C source, sink only, 5.1 kOhm Rd on CC1 and CC2; no power delivery negotiation (D153; PD later) |
| rails | 3V3 (FPGA VCCIO 0/1/6/7/8, FT2232H, the FPGA board's 3.3 V loads), 1V35 (VCCIO 2/3 and the DDR3L), 1V1 (FPGA core), 2V5 (VCCAUX); peaks after `power-tree.md`: 1V1 2.0 A, 1V35 1.2 A, 2V5 0.3 A, 3V3 as the FPGA board draws, up to 2.5 A |
| sequencing | 3V3 first, 2V5 with it; 1V35 enabled when 3V3 is good; 1V1 when 1V35 is good (`power-tree.md`, "Sequencing") |
| programming | FT2232H channel A as MPSSE JTAG (TCK, TDI, TDO, TMS on ADBUS0 to 3, the layout openFPGALoader and OpenOCD expect), PROGRAMN, INITN and DONE on ADBUS4 to 6; 93LC56B EEPROM for the FT2232H's configuration |
| serial | FT2232H channel B as UART: TXD out on BDBUS0, RXD in on BDBUS1, 3.3 V levels |
| USB | USB 2.0 high speed between the connector and the FT2232H, ESD protected at the connector |
| indicator | one power LED on 3V3 |
| supply to the FPGA board | every rail on two header pins but 2V5 (one), eight ground pins |

Current: at the peaks above the input draws about 9 W, 1.8 A at 5 V: the pod needs a USB-C source that offers
3 A at 5 V (a 1.5 A source covers the typical load only). Unknown until the owner's FPGA design runs through the
Lattice power calculator (`power-tree.md`).

## Blocks

Every block is a part stage 2 chooses (`bom.csv`, one line per block). The pin names are the block's own, as the
KiCad symbol stage 2 picks names them (checked against KiCad 9.0.9's libraries: `Interface_USB:FT2232HQ`,
`Regulator_Switching:TPS563201`, `Power_Supervisor:TPS3808DBV`, `Regulator_Linear:AP2112K-2.5`,
`Power_Protection:USBLC6-2SC6`, `Connector:USB_C_Receptacle_USB2.0_16P`, `Memory_EEPROM:93LCxxB`,
`Device:Crystal_GND24`, `Connector_Generic:Conn_02x12_Odd_Even`); a name the symbol carries on several pins is
written as the pin number. Values marked *(confirm)* are the parts' typical application values, whose datasheets
are not in the repository: stage 2 confirms each against its datasheet.

| Block | Function | Notes |
|---|---|---|
| usb | USB-C receptacle, USB 2.0 (16 pins) | 5 V sink; SBU1 and SBU2 unused |
| cc1_res, cc2_res | CC pull-downs, 5.1 kOhm 1 % | Rd, a sink's advertisement |
| esd | USB ESD protection, USBLC6-2SC6 | at the connector, on D+ and D- |
| vbus_cap | input bulk capacitor, 22 uF 10 V | at the connector |
| buck_3v3, buck_1v35, buck_1v1 | synchronous buck, TPS563201 (3 A, SOT-23-6) | one part number for three rails (`bom-notes.md`); feedback reference 0.768 V *(confirm)* |
| l_3v3, l_1v35, l_1v1 | buck inductors: 3.3 uH, 2.2 uH, 1.5 uH, 3 A or more saturation | *(confirm)* |
| bst_3v3, bst_1v35, bst_1v1 | bootstrap capacitors, 100 nF | SW to VBST *(confirm)* |
| fbt_3v3, fbb_3v3 | feedback divider 33 kOhm over 10 kOhm, 1 % | 3.30 V at 0.768 V *(confirm)* |
| fbt_1v35, fbb_1v35 | feedback divider 7.68 kOhm over 10 kOhm, 1 % | 1.36 V |
| fbt_1v1, fbb_1v1 | feedback divider 4.32 kOhm over 10 kOhm, 1 % | 1.10 V |
| cin_3v3, cin_1v35, cin_1v1 | buck input capacitors, 10 uF 10 V | at each VIN pin |
| cout_3v3a, cout_3v3b, cout_1v35a, cout_1v35b, cout_1v1a, cout_1v1b | buck output capacitors, 22 uF 6.3 V | two a rail *(confirm)* |
| en_3v3 | enable pull-up, 100 kOhm | the 3V3 buck starts with VBUS |
| sup_3v3, sup_1v35 | voltage supervisors, TPS3808 adjustable (SOT-23-6) | powered from 3V3, SENSE through a divider, open-drain RESET as the next rail's enable; SENSE threshold 0.405 V *(confirm)* |
| sns_3v3t, sns_3v3b | 3V3 sense divider, 63.4 kOhm over 10 kOhm | good above 2.97 V, 90 % |
| sns_1v35t, sns_1v35b | 1V35 sense divider, 20 kOhm over 10 kOhm | good above 1.22 V, 90 % |
| ct_3v3, ct_1v35 | supervisor delay capacitors, 10 nF | tens of milliseconds *(confirm)* |
| pu_3v3, pu_1v35 | pull-ups on the supervisors' RESET, 10 kOhm to 3V3 | the enables of the 1V35 and 1V1 bucks |
| dec_sup_3v3, dec_sup_1v35 | supervisor decoupling, 100 nF | |
| ldo_2v5 | LDO 2.5 V, AP2112K-2.5 (600 mA) | from 3V3, enabled with it (`bom-notes.md`) |
| cin_2v5, cout_2v5 | LDO capacitors, 1 uF | *(confirm)* |
| ft | USB to JTAG and UART, FT2232HQ (QFN-64, 0.5 mm pitch) | the class's fine-pitch QFN; its 1.8 V core from its own regulator (VREGOUT to VCORE) |
| x1 | 12 MHz crystal, 3.2 x 2.5 mm, 4 pads | pads 2 and 4 to ground |
| cx1, cx2 | crystal load capacitors, 18 pF C0G | for the crystal's load capacitance *(confirm)* |
| ref_res | FT2232H REF resistor, 12 kOhm 1 % | *(confirm)* |
| rst_res | FT2232H reset pull-up, 10 kOhm | |
| vreg_cin | FT2232H VREGIN decoupling, 4.7 uF | |
| vreg_cout | FT2232H VREGOUT capacitor, 3.3 uF | *(confirm)* |
| dcore1, dcore2, dcore3 | VCORE decoupling, 100 nF | one a VCORE pin |
| dio1, dio2, dio3, dio4 | VCCIO decoupling, 100 nF | one a VCCIO pin |
| dio_bulk | VCCIO bulk, 4.7 uF | |
| fb_phy | ferrite bead, 600 Ohm at 100 MHz | 3V3 to the FT2232H's VPHY and VPLL |
| dphy, dpll | VPHY and VPLL decoupling, 100 nF | |
| eeprom | 93LC56B microwire EEPROM (SOIC-8), 16-bit organisation | the FT2232H's configuration |
| ee_cs_pu, ee_clk_pu, ee_data_pu | EEPROM line pull-ups, 10 kOhm | |
| ee_do_res | EEPROM DO to DI resistor, 2.2 kOhm | DI and DO share the FT2232H's EEDATA *(confirm)* |
| ee_dec | EEPROM decoupling, 100 nF | |
| rs_tck, rs_tdi, rs_tms | JTAG series resistors, 33 Ohm | at the FT2232H, the lines it drives |
| fpga | 2x12 pin header, 2.54 mm, the FPGA board interface | pin map in Interfaces |
| led, led_res | power LED and its resistor, 1 kOhm | on 3V3 |
| hole1, hole2 | mounting holes, M3 | two opposite corners, no copper |

## Interfaces

A position is `free`, or an edge (`left edge, centred`; `bottom edge, 5 mm from left`). A positioned interface is
a locked constraint.

| Interface | Block | Signals | Position |
|---|---|---|---|
| usb | usb | VBUS, GND, D+, D-, CC1, CC2 | left edge, centred |
| fpga | fpga | 3V3, 2V5, 1V35, 1V1, GND, TCK, TDI, TDO, TMS, PROGRAMN, INITN, DONE, UART_TX, UART_RX | right edge, centred |
| indicator | led | | free |
| mounting | hole1, hole2 | | free |

The fpga header's pins (odd along one row, even along the other): 1, 2 3V3; 3, 4 GND; 5, 6 1V35; 7, 8 GND;
9, 10 1V1; 11, 12 GND; 13 2V5; 14 GND; 15 TCK; 16 GND; 17 TDI; 18 TMS; 19 TDO; 20 PROGRAMN; 21 INITN; 22 DONE;
23 UART_TX (pod to FPGA); 24 UART_RX (FPGA to pod). Each rail pair sits beside its ground pair; the JTAG and
configuration lines at the end, TCK beside a ground.

## Connectivity

The design's connectivity specification, which the schematic's netlist has to match one to one (stage 3's gate):
every net with its pins as `block.pin`.

| Net | Pins |
|---|---|
| VBUS | usb.A4 usb.A9 usb.B4 usb.B9 esd.VBUS vbus_cap.1 buck_3v3.VIN cin_3v3.1 buck_1v35.VIN cin_1v35.1 buck_1v1.VIN cin_1v1.1 en_3v3.1 |
| GND | usb.A1 usb.A12 usb.B1 usb.B12 usb.S1 cc1_res.2 cc2_res.2 esd.GND vbus_cap.2 buck_3v3.GND cin_3v3.2 fbb_3v3.2 cout_3v3a.2 cout_3v3b.2 buck_1v35.GND cin_1v35.2 fbb_1v35.2 cout_1v35a.2 cout_1v35b.2 buck_1v1.GND cin_1v1.2 fbb_1v1.2 cout_1v1a.2 cout_1v1b.2 sup_3v3.GND sns_3v3b.2 ct_3v3.2 dec_sup_3v3.2 sup_1v35.GND sns_1v35b.2 ct_1v35.2 dec_sup_1v35.2 ldo_2v5.GND cin_2v5.2 cout_2v5.2 ft.1 ft.5 ft.10 ft.11 ft.15 ft.25 ft.35 ft.47 ft.51 ft.65 ft.TEST x1.2 x1.4 cx1.2 cx2.2 ref_res.2 vreg_cin.2 vreg_cout.2 dcore1.2 dcore2.2 dcore3.2 dio1.2 dio2.2 dio3.2 dio4.2 dio_bulk.2 dphy.2 dpll.2 eeprom.GND ee_dec.2 fpga.3 fpga.4 fpga.7 fpga.8 fpga.11 fpga.12 fpga.14 fpga.16 led.K |
| CC1 | usb.A5 cc1_res.1 |
| CC2 | usb.B5 cc2_res.1 |
| USB_DP | usb.A6 usb.B6 esd.1 esd.6 ft.DP |
| USB_DM | usb.A7 usb.B7 esd.3 esd.4 ft.DM |
| EN_3V3 | buck_3v3.EN en_3v3.2 |
| SW_3V3 | buck_3v3.SW l_3v3.1 bst_3v3.1 |
| BST_3V3 | buck_3v3.VBST bst_3v3.2 |
| FB_3V3 | buck_3v3.VFB fbt_3v3.2 fbb_3v3.1 |
| 3V3 | l_3v3.2 fbt_3v3.1 cout_3v3a.1 cout_3v3b.1 sup_3v3.VDD sup_3v3.~{MR} sns_3v3t.1 pu_3v3.1 dec_sup_3v3.1 sup_1v35.VDD sup_1v35.~{MR} pu_1v35.1 dec_sup_1v35.1 ldo_2v5.VIN ldo_2v5.EN cin_2v5.1 ft.VREGIN vreg_cin.1 ft.20 ft.31 ft.42 ft.56 dio1.1 dio2.1 dio3.1 dio4.1 dio_bulk.1 fb_phy.1 rst_res.1 ee_cs_pu.1 ee_clk_pu.1 ee_data_pu.1 eeprom.VCC ee_dec.1 fpga.1 fpga.2 led_res.1 |
| SNS_3V3 | sup_3v3.SENSE sns_3v3t.2 sns_3v3b.1 |
| CT_3V3 | sup_3v3.CT ct_3v3.1 |
| PG_3V3 | sup_3v3.~{RESET} pu_3v3.2 buck_1v35.EN |
| SW_1V35 | buck_1v35.SW l_1v35.1 bst_1v35.1 |
| BST_1V35 | buck_1v35.VBST bst_1v35.2 |
| FB_1V35 | buck_1v35.VFB fbt_1v35.2 fbb_1v35.1 |
| 1V35 | l_1v35.2 fbt_1v35.1 cout_1v35a.1 cout_1v35b.1 sns_1v35t.1 fpga.5 fpga.6 |
| SNS_1V35 | sup_1v35.SENSE sns_1v35t.2 sns_1v35b.1 |
| CT_1V35 | sup_1v35.CT ct_1v35.1 |
| PG_1V35 | sup_1v35.~{RESET} pu_1v35.2 buck_1v1.EN |
| SW_1V1 | buck_1v1.SW l_1v1.1 bst_1v1.1 |
| BST_1V1 | buck_1v1.VBST bst_1v1.2 |
| FB_1V1 | buck_1v1.VFB fbt_1v1.2 fbb_1v1.1 |
| 1V1 | l_1v1.2 fbt_1v1.1 cout_1v1a.1 cout_1v1b.1 fpga.9 fpga.10 |
| 2V5 | ldo_2v5.VOUT cout_2v5.1 fpga.13 |
| 1V8_CORE | ft.VREGOUT ft.12 ft.37 ft.64 vreg_cout.1 dcore1.1 dcore2.1 dcore3.1 |
| VPHY | fb_phy.2 ft.VPHY ft.VPLL dphy.1 dpll.1 |
| OSCI | ft.OSCI x1.1 cx1.1 |
| OSCO | ft.OSCO x1.3 cx2.1 |
| REF | ft.REF ref_res.1 |
| FT_RESET | ft.~{RESET} rst_res.2 |
| EECS | ft.EECS eeprom.CS ee_cs_pu.2 |
| EECLK | ft.EECLK eeprom.SCLK ee_clk_pu.2 |
| EEDATA | ft.EEDATA eeprom.DI ee_data_pu.2 ee_do_res.1 |
| EE_DO | eeprom.DO ee_do_res.2 |
| TCK_FT | ft.ADBUS0 rs_tck.1 |
| TCK | rs_tck.2 fpga.15 |
| TDI_FT | ft.ADBUS1 rs_tdi.1 |
| TDI | rs_tdi.2 fpga.17 |
| TDO | ft.ADBUS2 fpga.19 |
| TMS_FT | ft.ADBUS3 rs_tms.1 |
| TMS | rs_tms.2 fpga.18 |
| PROGRAMN | ft.ADBUS4 fpga.20 |
| INITN | ft.ADBUS5 fpga.21 |
| DONE | ft.ADBUS6 fpga.22 |
| UART_TX | ft.BDBUS0 fpga.23 |
| UART_RX | ft.BDBUS1 fpga.24 |
| LED_A | led_res.2 led.A |

Unconnected: usb.A8, usb.B8, ft.ADBUS7, ft.ACBUS0, ft.ACBUS1, ft.ACBUS2, ft.ACBUS3, ft.ACBUS4, ft.ACBUS5, ft.ACBUS6, ft.ACBUS7, ft.BDBUS2, ft.BDBUS3, ft.BDBUS4, ft.BDBUS5, ft.BDBUS6, ft.BDBUS7, ft.BCBUS0, ft.BCBUS1, ft.BCBUS2, ft.BCBUS3, ft.BCBUS4, ft.BCBUS5, ft.BCBUS6, ft.BCBUS7, ft.~{SUSPEND}, ft.~{PWREN}, ldo_2v5.NC, eeprom.6, eeprom.7.

## Locked

Only the owner changes these (`docs/definition.md`, section 4). The tool asks about them only with evidence that
the best solution it found needs one crossed.

| Constraint | Value |
|---|---|
| size | at most 50 x 50 mm |
| cost | unknown: no price captured; every cost decision escalates to the owner |
| interfaces | usb on the left edge, fpga on the right edge |
| features | the capabilities above; USB power delivery left out (D153) |

## Free

Placement, rotation and side of every part (one side expected); the layer count (four expected for this class: a
ground plane under the USB pair and the bucks' loops); track width and spacing within the fab's capability; via
type; board size within the maximum; the FT2232H's package (FT2232HQ or FT2232HL, one pinout) and the pins its
channels use, within MPSSE's fixed JTAG pins.

## Fab and assembly

| Item | Choice |
|---|---|
| fab profile | pcbway |
| assembler | PCBWay, turnkey |
| quantity | 5 |

## Review

| Item | State |
|---|---|
| owner review | pending |
