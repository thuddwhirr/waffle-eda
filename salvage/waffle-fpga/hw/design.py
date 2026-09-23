#!/usr/bin/env python3
"""
waffle-fpga schematic connectivity — SOURCE OF TRUTH for the KiCad schematic.

FPGA nets come from ../pinmap.csv (generated from pinmap/assignment.toml);
STM32 pin-mux from bom-notes.md (D40); everything else is written here per
block-diagram.md / power-tree.md / bom.csv.  Run  python3 hw/tools/build.py
to regenerate the sheets and run ERC + netlist verification.
"""
import csv, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
from gen_sch import Design

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C0402 = "Capacitor_SMD:C_0402_1005Metric"; C0603 = "Capacitor_SMD:C_0603_1608Metric"; C0805 = "Capacitor_SMD:C_0805_2012Metric"; C1206 = "Capacitor_SMD:C_1206_3216Metric"
R0402 = "Resistor_SMD:R_0402_1005Metric"; R0603 = "Resistor_SMD:R_0603_1608Metric"

D = Design("waffle")
D.power("GND", "VIN", "VBUS_IN", "5V_SYS", "3V3_STBY", "3V3", "3V3A", "1V35", "VTT", "2V5", "1V1",
        "5V_USB1", "5V_USB2", "5V_USB3", "5V_HDMI", "VBUS_UPLINK")

D.sheet("power", "Power: USB-C PD input, eFuse, 5V_SYS buck + bypass, 3V3/1V35/1V1 bucks, LDOs, VTT/VREF, sequencing")
D.sheet("fpga_io", "ECP5 LFE5U-85F-8BG381C — I/O banks (nets from pinmap.csv)")
D.sheet("fpga_pwr", "ECP5 — core/aux/bank power and decoupling")
D.sheet("config", "Configuration: QSPI flash, JTAG via FT2232H, PROGRAMN/DONE/INITN, PC uplink USB-C")
D.sheet("ddr3", "DDR3L SDRAM x16 (1.35 V)")
D.sheet("stm32", "STM32H743ZIT6 system controller")
D.sheet("usb", "USB host: USB3320 ULPI PHY, USB2514B hub, port power switches, front ports")
D.sheet("clocks_audio", "Clocks (27 MHz XO, Si5351A), audio codec + jacks, RTC, EEPROM, OLED, I2C")
D.sheet("expansion", "HDMI (TPD12S016), microSD x2, ESP32-C6, PMODs, 2x20 header, LEDs")


def netname(sig):
    """FPGA signal name from pinmap.csv -> schematic net name."""
    return re.sub(r"\[(\d+)\]", r"\1", sig).upper()

# =============================================================================
# FPGA
# =============================================================================
U1 = D.part("U1", "FPGA_Lattice:LFE5U-85F-8BG381x", "LFE5U-85F-8BG381C", "fpga_io",
            units={1: "fpga_pwr", 9: "config"})
fpga_nets = {}
with open(os.path.join(ROOT, "pinmap.csv")) as f:
    for r in csv.DictReader(f):
        ball, sig, iface, io = r["ball"], r["signal"], r["interface"], r["io_type"]
        if iface == "config":
            fpga_nets[ball] = {"TCK": "JTAG_TCK", "TMS": "JTAG_TMS", "TDI": "JTAG_TDI", "TDO": "JTAG_TDO", "PROGRAMN": "FPGA_PROGRAMN",
                               "INITN": "FPGA_INITN", "DONE": "FPGA_DONE", "CCLK": "FLASH_SCK", "CFG0": "GND", "CFG1": "FPGA_CFG1", "CFG2": "GND"}[sig]
        elif iface == "spare" or r["direction"] == "reserved":
            fpga_nets[ball] = None
        elif io == "VREF1_DRIVER":
            fpga_nets[ball] = "VREF_DDR"
        elif "pseudo_" in sig:
            fpga_nets[ball] = netname(sig)      # tied to the rail through a 0R link (fpga_pwr sheet)
        else:
            fpga_nets[ball] = netname(sig)
for ball, net in fpga_nets.items():
    if net is None:
        D.no_connect("U1", ball)
    else:
        D.connect(net, ("U1", ball))
D.connect_all_named("1V1", "U1", "VCC")
D.connect_all_named("2V5", "U1", "VCCAUX")
D.connect_all_named("GND", "U1", "GND")
for b in (0, 1, 6, 7, 8):
    D.connect_all_named("3V3", "U1", f"VCCIO{b}")
for b in (2, 3):
    D.connect_all_named("1V35", "U1", f"VCCIO{b}")
for num in U1.by_name["RESERVED"]:
    D.no_connect("U1", num)
D.note("fpga_io", "Every I/O ball is driven from pinmap.csv; spare and reserved balls carry no-connect flags.")
# FPGA decoupling (power-tree.md decoupling plan)
for _ in range(8): D.cap("fpga_pwr", "100nF", "1V1")
for _ in range(2): D.cap("fpga_pwr", "4.7uF", "1V1", fp=C0603)
D.cap("fpga_pwr", "47uF", "1V1", fp=C1206)
for _ in range(4): D.cap("fpga_pwr", "100nF", "2V5")
D.cap("fpga_pwr", "4.7uF", "2V5", fp=C0603)
for _ in range(10): D.cap("fpga_pwr", "100nF", "3V3")
for _ in range(5): D.cap("fpga_pwr", "4.7uF", "3V3", fp=C0603)
for _ in range(4): D.cap("fpga_pwr", "100nF", "1V35")
for _ in range(2): D.cap("fpga_pwr", "4.7uF", "1V35", fp=C0603)
D.cap("fpga_pwr", "100nF", "VREF_DDR"); D.cap("fpga_pwr", "1uF", "VREF_DDR", fp=C0603)
D.res("fpga_pwr", "0R", "DDR3_PSEUDO_VCCIO0", "1V35"); D.res("fpga_pwr", "0R", "DDR3_PSEUDO_VCCIO1", "1V35"); D.res("fpga_pwr", "0R", "DDR3_PSEUDO_GND0", "GND")
D.note("fpga_pwr", "VCC=1V1 (20 balls), VCCAUX=2V5 (4), VCCIO0/1/6/7/8=3V3, VCCIO2/3=1V35, VREF1_3 (P16)=VREF_DDR, RESERVED balls open.")

# =============================================================================
# Configuration: flash, FT2232H, PROGRAMN/DONE/INITN, uplink USB-C
# =============================================================================
D.part("U3", "waffle:W25Q256JVEIQ", "W25Q256JVEIQ", "config")
D.connect("FLASH_CS_N", ("U3", "1")); D.connect("FLASH_SCK", ("U3", "6")); D.connect("FLASH_MOSI", ("U3", "5"))
D.connect("FLASH_MISO", ("U3", "2")); D.connect("FLASH_IO2", ("U3", "3")); D.connect("FLASH_IO3", ("U3", "7"))
D.connect("3V3", ("U3", "8")); D.connect("GND", ("U3", "4"), ("U3", "9"))
D.cap("config", "100nF", "3V3")
D.res("config", "4.7k", "FLASH_CS_N", "3V3")
for n in ("FLASH_MOSI", "FLASH_MISO", "FLASH_IO2", "FLASH_IO3"): D.res("config", "10k", n, "3V3")
D.res("config", "1k", "FLASH_SCK", "3V3")
# CFG1 pull-up (Master SPI: CFG[2:0] = 010, CFG0/CFG2 tied to GND at the FPGA symbol)
D.res("config", "4.7k", "FPGA_CFG1", "3V3")
# PROGRAMN: button + pull-up + STM32 open-drain
D.res("config", "4.7k", "FPGA_PROGRAMN", "3V3")
D.part("SW1", "Switch:SW_Push", "PROGRAMN", "config", "Button_Switch_SMD:SW_SPST_PTS645Sx43SMTR92")
D.connect("FPGA_PROGRAMN", ("SW1", "1")); D.connect("GND", ("SW1", "2"))
# DONE / INITN: pull-ups, LEDs (lit while low = configuring / init error), STM32 senses DONE
D.res("config", "4.7k", "FPGA_DONE", "3V3"); D.res("config", "4.7k", "FPGA_INITN", "3V3")
D.res("config", "1k", "3V3", "LED_DONE_A"); D.led("config", "LED CFG busy", "FPGA_DONE", "LED_DONE_A")
D.res("config", "1k", "3V3", "LED_INIT_A"); D.led("config", "LED INIT err", "FPGA_INITN", "LED_INIT_A")
# FT2232H
U7 = D.part("U7", "Interface_USB:FT2232HL", "FT2232HL", "config")
D.connect("JTAG_TCK", ("U7", "ADBUS0")); D.connect("JTAG_TDI", ("U7", "ADBUS1")); D.connect("JTAG_TDO", ("U7", "ADBUS2")); D.connect("JTAG_TMS", ("U7", "ADBUS3"))
D.connect("FT_TXD", ("U7", "BDBUS0")); D.connect("FT_RXD", ("U7", "BDBUS1")); D.connect("FT_RTS_N", ("U7", "BDBUS2")); D.connect("FT_DTR_N", ("U7", "BDBUS4"))
for n in ("ADBUS4", "ADBUS5", "ADBUS6", "ADBUS7", "ACBUS0", "ACBUS1", "ACBUS2", "ACBUS3", "ACBUS4", "ACBUS5", "ACBUS6", "ACBUS7",
          "BDBUS3", "BDBUS5", "BDBUS6", "BDBUS7", "BCBUS0", "BCBUS1", "BCBUS2", "BCBUS3", "BCBUS4", "BCBUS5", "BCBUS6", "BCBUS7", "~{PWREN}", "~{SUSPEND}"):
    D.no_connect("U7", n)
D.connect("USB_UP_DP", ("U7", "DP")); D.connect("USB_UP_DM", ("U7", "DM"))
D.connect("FT_OSCI", ("U7", "OSCI")); D.connect("FT_OSCO", ("U7", "OSCO"))
D.part("Y6", "Device:Crystal_GND24", "12MHz", "config", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm")
D.connect("FT_OSCI", ("Y6", "1")); D.connect("FT_OSCO", ("Y6", "3")); D.connect("GND", ("Y6", "2"), ("Y6", "4"))
D.cap("config", "27pF", "FT_OSCI"); D.cap("config", "27pF", "FT_OSCO")
D.res("config", "12k", "FT_REF", "GND"); D.connect("FT_REF", ("U7", "REF"))
D.connect("FT_RESET_N", ("U7", "~{RESET}")); D.res("config", "4.7k", "VBUS_UPLINK", "FT_RESET_N"); D.res("config", "10k", "FT_RESET_N", "GND")
D.connect("GND", ("U7", "TEST"))
D.connect("EE_CS", ("U7", "EECS")); D.connect("EE_CLK", ("U7", "EECLK")); D.connect("EE_DATA", ("U7", "EEDATA"))
D.part("U32", "Memory_EEPROM:93LCxxB", "93LC56B", "config", "Package_SO:TSSOP-8_3x3mm_P0.65mm")
D.connect("EE_CS", ("U32", "CS")); D.connect("EE_CLK", ("U32", "SCLK")); D.connect("EE_DATA", ("U32", "DI")); D.connect("EE_DO", ("U32", "DO"))
D.res("config", "2.2k", "EE_DO", "EE_DATA")
D.connect("3V3", ("U32", "VCC")); D.connect("GND", ("U32", "GND")); D.no_connect("U32", "6", "7")
D.res("config", "10k", "EE_CS", "GND"); D.res("config", "10k", "EE_CLK", "GND"); D.res("config", "10k", "EE_DATA", "3V3")
D.connect("3V3", ("U7", "VREGIN")); D.connect_all_named("3V3", "U7", "VCCIO")
D.connect("FT_1V8", ("U7", "VREGOUT")); D.connect_all_named("FT_1V8", "U7", "VCORE")
D.connect("FT_3V3_PHY", ("U7", "VPHY"), ("U7", "VPLL")); D.part("FB1", "Device:FerriteBead", "600R@100MHz", "config", "Inductor_SMD:L_0603_1608Metric")
D.connect("3V3", ("FB1", "1")); D.connect("FT_3V3_PHY", ("FB1", "2"))
D.connect_all_named("GND", "U7", "GND"); D.connect("GND", ("U7", "AGND"))
for _ in range(4): D.cap("config", "100nF", "3V3")
D.cap("config", "3.3uF", "FT_1V8", fp=C0603); D.cap("config", "100nF", "FT_1V8"); D.cap("config", "100nF", "FT_3V3_PHY"); D.cap("config", "4.7uF", "FT_3V3_PHY", fp=C0603)
D.pwrflag("config", "FT_3V3_PHY")
# uplink USB-C
J2 = D.part("J2", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C uplink", "config", "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal")
D.connect("VBUS_UPLINK", ("J2", "A4"), ("J2", "A9"), ("J2", "B4"), ("J2", "B9"))
D.connect("GND", ("J2", "A1"), ("J2", "A12"), ("J2", "B1"), ("J2", "B12"), ("J2", "S1"))
D.connect("J2_CC1", ("J2", "A5")); D.connect("J2_CC2", ("J2", "B5")); D.res("config", "5.1k", "J2_CC1", "GND"); D.res("config", "5.1k", "J2_CC2", "GND")
D.connect("USB_UP_DP_C", ("J2", "A6"), ("J2", "B6")); D.connect("USB_UP_DM_C", ("J2", "A7"), ("J2", "B7")); D.no_connect("J2", "A8", "B8")
D.part("D2", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "config", "Package_TO_SOT_SMD:SOT-23-6")
D.connect("USB_UP_DP_C", ("D2", "1")); D.connect("USB_UP_DP", ("D2", "6")); D.connect("USB_UP_DM_C", ("D2", "3")); D.connect("USB_UP_DM", ("D2", "4"))
D.connect("VBUS_UPLINK", ("D2", "5")); D.connect("GND", ("D2", "2"))
D.pwrflag("config", "VBUS_UPLINK")
# STM32 auto-boot from FT2232H channel B: DTR# -> BOOT0 (inverting NPN), RTS# -> NRST through a Schottky diode
D.part("Q1", "Transistor_BJT:MMBT3904", "MMBT3904", "config", "Package_TO_SOT_SMD:SOT-23")
D.res("config", "10k", "FT_DTR_N", "Q1_B"); D.connect("Q1_B", ("Q1", "B")); D.connect("GND", ("Q1", "E")); D.connect("STM32_BOOT0_PULL", ("Q1", "C"))
D.res("config", "10k", "3V3_STBY", "STM32_BOOT0_PULL"); D.res("config", "10k", "STM32_BOOT0_PULL", "STM32_BOOT0")
D.part("D3", "Device:D_Schottky", "BAT54", "config", "Diode_SMD:D_SOD-123")
D.connect("FT_RTS_N", ("D3", "2")); D.connect("STM32_NRST", ("D3", "1"))
D.note("config", "FT2232H ch A = MPSSE JTAG (AD0 TCK, AD1 TDI, AD2 TDO, AD3 TMS); ch B = UART to STM32 (BD0 TXD, BD1 RXD, BD2 RTS#, BD4 DTR#).")
D.note("config", "Self-powered FT2232H: RESET# follows the uplink VBUS via 4.7k/10k divider. Flash: W25Q256 in Master SPI quad mode, CFG[2:0]=010.")

# =============================================================================
# DDR3L
# =============================================================================
U2 = D.part("U2", "waffle:DDR3L_x16_FBGA96", "MT41K512M16HA-107:A", "ddr3")
ddr_pin_net = {}
for num, name in [(p["number"], p["name"]) for p in U2.pins]:
    n = name[2:-1] + "#" if name.startswith("~{") else name
    if n.startswith("DQ") and n[2:].isdigit(): ddr_pin_net[num] = f"DDR3_DQ{n[2:]}"
    elif n == "LDQS": ddr_pin_net[num] = "DDR3_DQS_P0"
    elif n == "LDQS#": ddr_pin_net[num] = "DDR3_DQS_N0"
    elif n == "UDQS": ddr_pin_net[num] = "DDR3_DQS_P1"
    elif n == "UDQS#": ddr_pin_net[num] = "DDR3_DQS_N1"
    elif n == "LDM": ddr_pin_net[num] = "DDR3_DM0"
    elif n == "UDM": ddr_pin_net[num] = "DDR3_DM1"
    elif n.startswith("A") and n[1].isdigit(): ddr_pin_net[num] = "DDR3_A" + n[1:].split("/")[0]
    elif n.startswith("BA"): ddr_pin_net[num] = "DDR3_" + n
    elif n in ("RAS#", "CAS#", "WE#", "CS#"): ddr_pin_net[num] = "DDR3_" + n[:-1] + "_N"
    elif n == "CKE": ddr_pin_net[num] = "DDR3_CKE"
    elif n == "ODT": ddr_pin_net[num] = "DDR3_ODT"
    elif n == "CK": ddr_pin_net[num] = "DDR3_CLK_P"
    elif n == "CK#": ddr_pin_net[num] = "DDR3_CLK_N"
    elif n == "RESET#": ddr_pin_net[num] = "DDR3_RESET_N"
    elif n in ("VDD", "VDDQ"): ddr_pin_net[num] = "1V35"
    elif n in ("VSS", "VSSQ"): ddr_pin_net[num] = "GND"
    elif n in ("VREFDQ", "VREFCA"): ddr_pin_net[num] = "VREF_DDR"
    elif n == "ZQ": ddr_pin_net[num] = "DDR3_ZQ"
    elif n == "NC": ddr_pin_net[num] = None
    else: raise KeyError(n)
for num, net in ddr_pin_net.items():
    if net is None: D.no_connect("U2", num)
    else: D.connect(net, ("U2", num))
D.res("ddr3", "240R 1%", "DDR3_ZQ", "GND")
D.res("ddr3", "100R", "DDR3_CLK_P", "DDR3_CLK_N")
for _ in range(10): D.cap("ddr3", "100nF", "1V35")
for _ in range(2): D.cap("ddr3", "10uF", "1V35", fp=C0805)
D.cap("ddr3", "100nF", "VREF_DDR"); D.cap("ddr3", "1uF", "VREF_DDR", fp=C0603)
for _ in range(2): D.cap("ddr3", "10uF", "VTT", fp=C0805)
D.note("ddr3", "Address/command VTT terminations (22 x 50R) are a layout-time option (DNP by default); CK/CK# 100R at the DRAM. VREF_DDR from TPS51200 REFOUT.")

# =============================================================================
# STM32H743ZIT6
# =============================================================================
U4 = D.part("U4", "MCU_ST_STM32H7:STM32H743ZITx", "STM32H743ZIT6", "stm32")
stm = {
    # FMC (AF12)
    "PD14": "FMC_D0", "PD15": "FMC_D1", "PD0": "FMC_D2", "PD1": "FMC_D3", "PE7": "FMC_D4", "PE8": "FMC_D5", "PE9": "FMC_D6", "PE10": "FMC_D7",
    "PE11": "FMC_D8", "PE12": "FMC_D9", "PE13": "FMC_D10", "PE14": "FMC_D11", "PE15": "FMC_D12", "PD8": "FMC_D13", "PD9": "FMC_D14", "PD10": "FMC_D15",
    "PF0": "FMC_A0", "PF1": "FMC_A1", "PF2": "FMC_A2", "PF3": "FMC_A3", "PF4": "FMC_A4", "PF5": "FMC_A5", "PF12": "FMC_A6", "PF13": "FMC_A7",
    "PD4": "FMC_NOE", "PD5": "FMC_NWE", "PD7": "FMC_NE",
    # ULPI (AF10)
    "PA3": "ULPI_D0", "PB0": "ULPI_D1", "PB1": "ULPI_D2", "PB10": "ULPI_D3", "PB11": "ULPI_D4", "PB12": "ULPI_D5", "PB13": "ULPI_D6", "PB5": "ULPI_D7",
    "PA5": "ULPI_CLK", "PC2": "ULPI_DIR", "PC3": "ULPI_NXT", "PC0": "ULPI_STP",
    # UARTs
    "PA9": "FT_RXD", "PA10": "FT_TXD",          # USART1 TX -> FT2232H RXD, RX <- FT TXD
    "PC6": "ESP_RXD", "PC7": "ESP_TXD",         # USART6 TX -> ESP U0RXD, RX <- ESP U0TXD
    "PG2": "ESP_BOOT",
    # HDMI aux via TPD12S016
    "PB8": "HDMI_SCL_A", "PB9": "HDMI_SDA_A", "PA15": "HDMI_CEC_A", "PG3": "HDMI_HPD_A", "PB14": "HDMI_LS_OE", "PB15": "HDMI_CT_HPD",
    # buttons
    "PC13": "BTN_PWR_N", "PE2": "BTN_RST_N", "PE3": "BTN0_N", "PE4": "BTN1_N", "PE5": "BTN2_N",
    # power control / sensing
    "PG4": "MAIN_EN", "PG5": "PG_3V3", "PG6": "PG_1V35", "PG7": "PG_1V1", "PG8": "PD_PG_N", "PA0": "VIN_SENSE", "PG15": "HUB_RST_N",
    # FPGA aux
    "PE6": "FPGA_DONE", "PE1": "FPGA_PROGRAMN", "PE0": "FMC_IRQ", "PB4": "FMC_NRST",
    # misc
    "PC4": "RTC_INT_N",
    # debug
    "PA13": "SWDIO", "PA14": "SWCLK", "PB3": "SWO",
}
def stm_pin(name):
    for cand in (name, name + "_C", name.replace("PC2", "PC2_C")):
        if cand in U4.by_name:
            return cand
    raise KeyError(name)
stm = {stm_pin(k): v for k, v in stm.items()}
for pin, net in stm.items():
    D.connect(net, ("U4", pin))
D.connect_all_named("3V3_STBY", "U4", "VDD"); D.connect("3V3_STBY", ("U4", "VBAT"), ("U4", "VDD33_USB"), ("U4", "PDR_ON"))
D.connect("STM32_VDDA", ("U4", "VDDA"), ("U4", "VREF+"))
D.part("FB2", "Device:FerriteBead", "600R@100MHz", "stm32", "Inductor_SMD:L_0603_1608Metric"); D.connect("3V3_STBY", ("FB2", "1")); D.connect("STM32_VDDA", ("FB2", "2"))
D.cap("stm32", "1uF", "STM32_VDDA", fp=C0603); D.cap("stm32", "100nF", "STM32_VDDA"); D.pwrflag("stm32", "STM32_VDDA")
D.connect_all_named("GND", "U4", "VSS"); D.connect("GND", ("U4", "VSSA"))
vcaps = U4.by_name["VCAP"]
D.connect("STM32_VCAP1", ("U4", vcaps[0])); D.connect("STM32_VCAP2", ("U4", vcaps[1]))
D.cap("stm32", "2.2uF", "STM32_VCAP1", fp=C0603); D.cap("stm32", "2.2uF", "STM32_VCAP2", fp=C0603)
D.connect("STM32_NRST", ("U4", "NRST")); D.cap("stm32", "100nF", "STM32_NRST"); D.res("stm32", "10k", "STM32_NRST", "3V3_STBY")
D.connect("STM32_BOOT0", ("U4", "BOOT0")); D.res("stm32", "10k", "STM32_BOOT0", "GND")
D.connect("STM32_OSC_IN", ("U4", "PH0")); D.connect("STM32_OSC_OUT", ("U4", "PH1"))
D.part("Y2", "Device:Crystal_GND24", "25MHz", "stm32", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm")
D.connect("STM32_OSC_IN", ("Y2", "1")); D.connect("STM32_OSC_OUT", ("Y2", "3")); D.connect("GND", ("Y2", "2"), ("Y2", "4"))
D.cap("stm32", "10pF", "STM32_OSC_IN"); D.cap("stm32", "10pF", "STM32_OSC_OUT")
for _ in range(len(U4.by_name["VDD"])): D.cap("stm32", "100nF", "3V3_STBY")
for _ in range(2): D.cap("stm32", "4.7uF", "3V3_STBY", fp=C0603)
# SWD header
D.part("J16", "Connector_Generic:Conn_02x05_Odd_Even", "SWD", "stm32", "Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical")
D.connect("3V3_STBY", ("J16", "1")); D.connect("SWDIO", ("J16", "2")); D.connect("GND", ("J16", "3"), ("J16", "5"), ("J16", "9"))
D.connect("SWCLK", ("J16", "4")); D.connect("SWO", ("J16", "6")); D.no_connect("J16", "7"); D.no_connect("J16", "8"); D.connect("STM32_NRST", ("J16", "10"))
# buttons (STM32 internal pull-ups; power button has an external pull-up on the standby rail for WKUP)
for ref, net in (("SW2", "BTN_PWR_N"), ("SW3", "BTN_RST_N"), ("SW4", "BTN0_N"), ("SW5", "BTN1_N"), ("SW6", "BTN2_N")):
    # right-angle 6 mm tactile on the front edge, actuator through the case wall (PTS645Vx58: 5.8 mm actuator; Vx39/Vx83 share the pads)
    D.part(ref, "Switch:SW_Push", ref.replace("SW", "BTN"), "stm32", "Button_Switch_THT:SW_Tactile_SPST_Angled_PTS645Vx58-2LFS")
    D.connect(net, (ref, "1")); D.connect("GND", (ref, "2"))
D.res("stm32", "10k", "BTN_PWR_N", "3V3_STBY")
D.res("stm32", "10k", "PD_PG_N", "3V3_STBY")
D.res("stm32", "10k", "RTC_INT_N", "3V3_STBY")
D.res("stm32", "100k", "VIN", "VIN_SENSE"); D.res("stm32", "20k", "VIN_SENSE", "GND"); D.cap("stm32", "100nF", "VIN_SENSE")
# unused STM32 pins -> no-connect (everything not listed above)
for p in U4.pins:
    if p["name"].startswith("P") and p["name"] not in stm and p["name"] not in ("PH0", "PH1", "PDR_ON"):
        D.no_connect("U4", p["number"])
D.note("stm32", "Pin-mux per bom-notes.md (D40): FMC on PD/PE/PF, ULPI on PA/PB/PC, USART1 <-> FT2232H, USART6 <-> ESP32-C6, I2C1/CEC to TPD12S016. Confirm in CubeMX.")

# =============================================================================
# USB host: PHY, hub, switches, ports
# =============================================================================
U5 = D.part("U5", "waffle:USB3320C-EZK", "USB3320C-EZK", "usb")
for num, net in {"3": "ULPI_D0", "4": "ULPI_D1", "5": "ULPI_D2", "6": "ULPI_D3", "7": "ULPI_D4", "9": "ULPI_D5", "10": "ULPI_D6", "13": "ULPI_D7",
                 "1": "ULPI_CLK", "31": "ULPI_DIR", "2": "ULPI_NXT", "29": "ULPI_STP", "27": "ULPI_RST_N",
                 "18": "HUB_UP_DP", "19": "HUB_UP_DM", "24": "PHY_RBIAS", "26": "PHY_XI", "25": "PHY_XO", "22": "PHY_VBUS",
                 "20": "3V3", "21": "3V3", "32": "3V3", "28": "PHY_1V8A", "30": "PHY_1V8B", "33": "GND", "23": "GND",
                 "8": "3V3", "11": "3V3", "14": "3V3"}.items():
    D.connect(net, ("U5", num))
D.no_connect("U5", "12", "15", "16", "17")
D.res("usb", "8.06k 1%", "PHY_RBIAS", "GND")
D.res("usb", "1k", "5V_SYS", "PHY_VBUS")
D.res("usb", "10k", "ULPI_RST_N", "3V3")
D.part("Y4", "Device:Crystal_GND24", "24MHz", "usb", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm")
D.connect("PHY_XI", ("Y4", "1")); D.connect("PHY_XO", ("Y4", "3")); D.connect("GND", ("Y4", "2"), ("Y4", "4"))
D.cap("usb", "18pF", "PHY_XI"); D.cap("usb", "18pF", "PHY_XO")
D.cap("usb", "1uF", "PHY_1V8A", fp=C0603); D.cap("usb", "1uF", "PHY_1V8B", fp=C0603)
for _ in range(3): D.cap("usb", "100nF", "3V3")
D.cap("usb", "4.7uF", "3V3", fp=C0603)
D.pwrflag("usb", "PHY_1V8A"); D.pwrflag("usb", "PHY_1V8B")
D.note("usb", "USB3320: REFSEL[2:0]=111 selects the 24 MHz crystal (Table 5-10); ID grounded (host); VBUS sensed from 5V_SYS through 1k; internal 1.8 V regulators (VDD18 decoupled only).")
# hub
U6 = D.part("U6", "Interface_USB:USB2514B_Bi", "USB2514B-AEZG", "usb")
D.connect("HUB_UP_DP", ("U6", "USBDP_UP")); D.connect("HUB_UP_DM", ("U6", "USBDM_UP"))
D.connect("HUB_DN1_DP", ("U6", "USBDP_DN1/PRT_DIS_P1")); D.connect("HUB_DN1_DM", ("U6", "USBDM_DN1/PRT_DIS_M1"))
D.connect("HUB_DN2_DP", ("U6", "USBDP_DN2/PRT_DIS_P2")); D.connect("HUB_DN2_DM", ("U6", "USBDM_DN2/PRT_DIS_M2"))
D.connect("HUB_DN3_DP", ("U6", "USBDP_DN3/PRT_DIS_P3")); D.connect("HUB_DN3_DM", ("U6", "USBDM_DN3/PRT_DIS_M3"))
D.connect("HUB_DN4_DP", ("U6", "USBDP_DN4/PRT_DIS_P4")); D.connect("HUB_DN4_DM", ("U6", "USBDM_DN4/PRT_DIS_M4"))
D.connect("USB_PWR_EN1", ("U6", "PRTPWR1/BC_EN1")); D.connect("USB_PWR_EN2", ("U6", "PRTPWR2/BC_EN2")); D.connect("USB_PWR_EN3", ("U6", "PRTPWR3/BC_EN3")); D.no_connect("U6", "PRTPWR4/BC_EN4")
D.connect("USB_FLT1_N", ("U6", "OCS_N1")); D.connect("USB_FLT2_N", ("U6", "OCS_N2")); D.connect("USB_FLT3_N", ("U6", "OCS_N3")); D.connect("USB_FLT4_N", ("U6", "OCS_N4"))
D.res("usb", "10k", "USB_FLT4_N", "3V3")
D.connect("HUB_RST_N", ("U6", "RESET_N")); D.res("usb", "100k", "HUB_RST_N", "3V3"); D.cap("usb", "1uF", "HUB_RST_N", fp=C0603)
D.connect("HUB_CFG_SEL0", ("U6", "SCL/SMBCLK/CFG_SEL0")); D.connect("HUB_CFG_SEL1", ("U6", "HS_IND/CFG_SEL1"))
D.connect("HUB_NON_REM1", ("U6", "SDA/SMBDATA/NON_REM1")); D.connect("HUB_NON_REM0", ("U6", "SUSP_IND/LOCAL_PWR/NON_REM0"))
for n in ("HUB_CFG_SEL0", "HUB_CFG_SEL1", "HUB_NON_REM1", "HUB_NON_REM0"): D.res("usb", "100k", n, "GND")
D.connect("GND", ("U6", "TEST"), ("U6", "VSS"))
D.connect("3V3", ("U6", "VBUS_DET"))
D.connect("HUB_RBIAS", ("U6", "RBIAS")); D.res("usb", "12.0k 1%", "HUB_RBIAS", "GND")
D.connect("HUB_CRFILT", ("U6", "CRFILT")); D.cap("usb", "100nF", "HUB_CRFILT"); D.connect("HUB_PLLFILT", ("U6", "PLLFILT")); D.cap("usb", "100nF", "HUB_PLLFILT")
D.connect("HUB_XI", ("U6", "XTALIN/CLKIN")); D.connect("HUB_XO", ("U6", "XTALOUT"))
D.part("Y5", "Device:Crystal_GND24", "24MHz", "usb", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm")
D.connect("HUB_XI", ("Y5", "1")); D.connect("HUB_XO", ("Y5", "3")); D.connect("GND", ("Y5", "2"), ("Y5", "4"))
D.cap("usb", "18pF", "HUB_XI"); D.cap("usb", "18pF", "HUB_XO")
D.connect_all_named("3V3", "U6", "VDDA33"); D.connect_all_named("3V3", "U6", "VDD33")
for _ in range(6): D.cap("usb", "100nF", "3V3")
D.note("usb", "USB2514B straps: CFG_SEL[1:0]=00 (default config, self-powered, individual port power/OC), NON_REM=00, TEST=GND, VBUS_DET=3V3 (permanently attached host).")
# port power switches (hub controlled)
for i in (1, 2, 3):
    ref = f"U{24 + i}"
    D.part(ref, "waffle:TPS2553DBV", "TPS2553DBVR", "usb")
    D.connect("5V_SYS", (ref, "1")); D.connect("GND", (ref, "2")); D.connect(f"USB_PWR_EN{i}", (ref, "3")); D.connect(f"USB_FLT{i}_N", (ref, "4"))
    D.connect(f"USB_ILIM{i}", (ref, "5")); D.res("usb", "20k (1.1A)", f"USB_ILIM{i}", "GND")
    D.connect(f"5V_USB{i}", (ref, "6")); D.res("usb", "10k", f"USB_FLT{i}_N", "3V3")
    D.cap("usb", "100nF", "5V_SYS"); D.cap("usb", "10uF", f"5V_USB{i}", fp=C0805)
# front ports
# stacked dual USB-A (one connector, two hub ports) on the left edge: port 1 = pins 1-4, port 2 = pins 5-8, shield = 9
D.part("J4", "Connector:USB_A_Stacked", "USB-A host 1+2", "usb", "Connector_USB:USB_A_Wuerth_61400826021_Horizontal_Stacked")
D.connect("GND", ("J4", "4"), ("J4", "8"), ("J4", "9"))
for i, vb, dm, dp in ((1, "1", "2", "3"), (2, "5", "6", "7")):
    D.connect(f"5V_USB{i}", ("J4", vb)); D.connect(f"USB{i}_DP", ("J4", dp)); D.connect(f"USB{i}_DM", ("J4", dm))
    dref = f"D{3 + i}"
    D.part(dref, "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "usb", "Package_TO_SOT_SMD:SOT-23-6")
    D.connect(f"USB{i}_DP", (dref, "1")); D.connect(f"HUB_DN{i}_DP", (dref, "6")); D.connect(f"USB{i}_DM", (dref, "3")); D.connect(f"HUB_DN{i}_DM", (dref, "4"))
    D.connect(f"5V_USB{i}", (dref, "5")); D.connect("GND", (dref, "2"))
D.part("J3", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C host", "usb", "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal")
D.connect("5V_USB3", ("J3", "A4"), ("J3", "A9"), ("J3", "B4"), ("J3", "B9")); D.connect("GND", ("J3", "A1"), ("J3", "A12"), ("J3", "B1"), ("J3", "B12"), ("J3", "S1"))
D.connect("J3_CC1", ("J3", "A5")); D.connect("J3_CC2", ("J3", "B5")); D.res("usb", "56k", "5V_USB3", "J3_CC1"); D.res("usb", "56k", "5V_USB3", "J3_CC2")
D.connect("USB3_DP", ("J3", "A6"), ("J3", "B6")); D.connect("USB3_DM", ("J3", "A7"), ("J3", "B7")); D.no_connect("J3", "A8", "B8")
D.part("D6", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "usb", "Package_TO_SOT_SMD:SOT-23-6")
D.connect("USB3_DP", ("D6", "1")); D.connect("HUB_DN3_DP", ("D6", "6")); D.connect("USB3_DM", ("D6", "3")); D.connect("HUB_DN3_DM", ("D6", "4")); D.connect("5V_USB3", ("D6", "5")); D.connect("GND", ("D6", "2"))
D.part("J17", "Connector_Generic:Conn_01x04", "USB hub port 4", "usb", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical")
D.connect("5V_SYS", ("J17", "1")); D.connect("HUB_DN4_DM", ("J17", "2")); D.connect("HUB_DN4_DP", ("J17", "3")); D.connect("GND", ("J17", "4"))

# =============================================================================
# Clocks, audio, I2C peripherals
# =============================================================================
D.part("Y1", "Oscillator:ECS-2520MV-xxx-xx", "ECS-2520MV-270", "clocks_audio")
D.connect("3V3", ("Y1", "4"), ("Y1", "1")); D.connect("GND", ("Y1", "2")); D.connect("CLK27_XO", ("Y1", "3")); D.res("clocks_audio", "33R", "CLK27_XO", "CLK27")
D.cap("clocks_audio", "100nF", "3V3")
U10 = D.part("U10", "Oscillator:Si5351A-B-GT", "Si5351A-B-GT", "clocks_audio")
D.connect("3V3", ("U10", "VDD"), ("U10", "VDDO")); D.connect("GND", ("U10", "GND")); D.connect("I2C_SCL", ("U10", "SCL")); D.connect("I2C_SDA", ("U10", "SDA"))
D.connect("SI_XA", ("U10", "XA")); D.connect("SI_XB", ("U10", "XB"))
D.part("Y3", "Device:Crystal_GND24", "25MHz", "clocks_audio", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm")
D.connect("SI_XA", ("Y3", "1")); D.connect("SI_XB", ("Y3", "3")); D.connect("GND", ("Y3", "2"), ("Y3", "4"))
D.connect("SI_CLK0", ("U10", "CLK0")); D.res("clocks_audio", "33R", "SI_CLK0", "CLK_SI5351")
D.connect("SI_CLK1", ("U10", "CLK1")); D.res("clocks_audio", "33R", "SI_CLK1", "I2S_MCLK")
D.no_connect("U10", "CLK2")
D.cap("clocks_audio", "100nF", "3V3"); D.cap("clocks_audio", "1uF", "3V3", fp=C0603)
# codec
U9 = D.part("U9", "waffle:TLV320AIC3204IRHB", "TLV320AIC3204IRHBR", "clocks_audio")
for num, net in {"1": "I2S_MCLK", "2": "I2S_BCLK", "3": "I2S_LRCLK", "4": "I2S_DOUT", "5": "I2S_DIN", "9": "I2C_SCL", "10": "I2C_SDA",
                 "12": "GND", "8": "GND", "6": "3V3", "7": "GND", "17": "GND", "28": "GND", "33": "GND", "26": "3V3A", "30": "3V3A",
                 "24": "CODEC_AVDD", "29": "CODEC_DVDD", "18": "CODEC_REF", "31": "CODEC_RST_N", "25": "HP_L", "27": "HP_R", "13": "LINE_IN_L", "14": "LINE_IN_R", "19": "CODEC_MICBIAS"}.items():
    D.connect(net, ("U9", num))
D.no_connect("U9", "11", "15", "16", "20", "21", "22", "23", "32")
D.cap("clocks_audio", "1uF", "CODEC_AVDD", fp=C0603); D.cap("clocks_audio", "1uF", "CODEC_DVDD", fp=C0603); D.cap("clocks_audio", "10uF", "CODEC_REF", fp=C0805)
D.pwrflag("clocks_audio", "CODEC_AVDD"); D.pwrflag("clocks_audio", "CODEC_DVDD")
D.res("clocks_audio", "100k", "CODEC_RST_N", "3V3"); D.cap("clocks_audio", "1uF", "CODEC_RST_N", fp=C0603)
D.part("FB3", "Device:FerriteBead", "600R@100MHz", "clocks_audio", "Inductor_SMD:L_0603_1608Metric"); D.connect("3V3", ("FB3", "1")); D.connect("3V3A", ("FB3", "2"))
D.cap("clocks_audio", "10uF", "3V3A", fp=C0805); D.cap("clocks_audio", "100nF", "3V3A"); D.cap("clocks_audio", "100nF", "3V3"); D.pwrflag("clocks_audio", "3V3A")
D.part("J9", "Connector_Audio:AudioJack3", "HP/line out", "clocks_audio", "Connector_Audio:Jack_3.5mm_CUI_SJ-3523-SMT_Horizontal")
D.cap("clocks_audio", "100uF", "HP_L", "J9_T", fp=C1206); D.cap("clocks_audio", "100uF", "HP_R", "J9_R", fp=C1206)
D.connect("J9_T", ("J9", "T")); D.connect("J9_R", ("J9", "R")); D.connect("GND", ("J9", "S"))
D.part("J10", "Connector_Audio:AudioJack3", "line/mic in", "clocks_audio", "Connector_Audio:Jack_3.5mm_CUI_SJ-3523-SMT_Horizontal")
D.cap("clocks_audio", "1uF", "J10_T", "LINE_IN_L", fp=C0603); D.cap("clocks_audio", "1uF", "J10_R", "LINE_IN_R", fp=C0603)
D.connect("J10_T", ("J10", "T")); D.connect("J10_R", ("J10", "R")); D.connect("GND", ("J10", "S"))
D.res("clocks_audio", "2.2k (DNP: electret mic bias)", "CODEC_MICBIAS", "J10_R", dnp=True)
# I2C peripherals
D.res("clocks_audio", "2.2k", "I2C_SCL", "3V3"); D.res("clocks_audio", "2.2k", "I2C_SDA", "3V3")
U11 = D.part("U11", "Timer_RTC:RV-3028-C7", "RV-3028-C7", "clocks_audio")
D.connect("I2C_SCL", ("U11", "SCL")); D.connect("I2C_SDA", ("U11", "SDA")); D.connect("3V3_STBY", ("U11", "VDD")); D.connect("GND", ("U11", "VSS"), ("U11", "EVI"))
D.connect("RTC_INT_N", ("U11", "~{INT}")); D.no_connect("U11", "CLKOUT"); D.connect("RTC_VBACKUP", ("U11", "VBACKUP"))
D.part("BT1", "Device:Battery_Cell", "CR1220", "clocks_audio", "Battery:BatteryHolder_Keystone_3034_1x20mm"); D.connect("RTC_VBACKUP", ("BT1", "1")); D.connect("GND", ("BT1", "2")); D.pwrflag("clocks_audio", "RTC_VBACKUP")
D.cap("clocks_audio", "100nF", "3V3_STBY")
D.part("U13", "Memory_EEPROM:24AA02E-OT", "24AA02E48T-I/OT", "clocks_audio")
D.connect("I2C_SCL", ("U13", "SCL")); D.connect("I2C_SDA", ("U13", "SDA")); D.connect("3V3", ("U13", "V_{CC}")); D.connect("GND", ("U13", "V_{SS}")); D.no_connect("U13", "NC")
D.part("J18", "Connector_Generic:Conn_01x04", "OLED SSD1306", "clocks_audio", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical")
D.connect("GND", ("J18", "1")); D.connect("3V3", ("J18", "2")); D.connect("I2C_SCL", ("J18", "3")); D.connect("I2C_SDA", ("J18", "4"))
D.note("clocks_audio", "I2C bus (3.3 V, FPGA master): Si5351A, TLV320AIC3204, RV-3028 (on 3V3_STBY), 24AA02E48, OLED header. Codec LDO_SELECT=1: internal AVDD/DVDD LDOs from LDOIN=3V3A.")

# =============================================================================
# Expansion: HDMI, SD, ESP32, PMODs, header, LEDs
# =============================================================================
U15 = D.part("U15", "waffle:TPD12S016PW", "TPD12S016PWR", "expansion")
tmds = {"23": "HDMI_D2_P", "22": "HDMI_D2_N", "21": "HDMI_D1_P", "20": "HDMI_D1_N", "18": "HDMI_D0_P", "17": "HDMI_D0_N", "16": "HDMI_CLK_P", "15": "HDMI_CLK_N"}
for num, net in tmds.items():
    D.connect(net + "_C", ("U15", num))
    D.res("expansion", "270R", net, net + "_C")
for num, net in {"1": "HDMI_CEC_A", "2": "HDMI_SCL_A", "3": "HDMI_SDA_A", "4": "HDMI_HPD_A", "5": "HDMI_LS_OE", "12": "HDMI_CT_HPD",
                 "7": "HDMI_CEC_B", "8": "HDMI_SCL_B", "9": "HDMI_SDA_B", "10": "HDMI_HPD_B", "11": "5V_SYS", "13": "5V_HDMI", "24": "3V3", "6": "GND", "14": "GND", "19": "GND"}.items():
    D.connect(net, ("U15", num))
D.res("expansion", "4.7k", "HDMI_SCL_A", "3V3"); D.res("expansion", "4.7k", "HDMI_SDA_A", "3V3"); D.res("expansion", "27k", "HDMI_CEC_A", "3V3")
D.cap("expansion", "100nF", "5V_SYS"); D.cap("expansion", "100nF", "3V3"); D.cap("expansion", "100nF", "5V_HDMI")
J6 = D.part("J6", "Connector:HDMI_A", "HDMI", "expansion", "Connector_Video:HDMI_A_Amphenol_10029449-x01xLF_Horizontal")
for num, net in {"1": "HDMI_D2_P_C", "3": "HDMI_D2_N_C", "4": "HDMI_D1_P_C", "6": "HDMI_D1_N_C", "7": "HDMI_D0_P_C", "9": "HDMI_D0_N_C", "10": "HDMI_CLK_P_C", "12": "HDMI_CLK_N_C",
                 "13": "HDMI_CEC_B", "15": "HDMI_SCL_B", "16": "HDMI_SDA_B", "19": "HDMI_HPD_B", "18": "5V_HDMI",
                 "2": "GND", "5": "GND", "8": "GND", "11": "GND", "17": "GND", "SH": "GND"}.items():
    D.connect(net, ("J6", num))
D.no_connect("J6", "14")
D.note("expansion", "TMDS: FPGA LVCMOS33D pairs -> 270R series (ULX3S GPDI style; verify value) -> TPD12S016 ESD -> HDMI. DDC/CEC/HPD level-shifted to the STM32 by the TPD12S016.")
# microSD
for i, ref in ((1, "J7"), (2, "J8")):
    D.part(ref, "Connector:Micro_SD_Card", f"microSD {i}", "expansion", "Connector_Card:microSD_HC_Hirose_DM3AT-SF-PEJM5")
    D.connect(f"SD{i}_D2", (ref, "1")); D.connect(f"SD{i}_D3", (ref, "2")); D.connect(f"SD{i}_CMD", (ref, "3")); D.connect("3V3", (ref, "4"))
    D.connect(f"SD{i}_CLK", (ref, "5")); D.connect("GND", (ref, "6"), (ref, "9")); D.connect(f"SD{i}_D0", (ref, "7")); D.connect(f"SD{i}_D1", (ref, "8"))
    D.cap("expansion", "10uF", "3V3", fp=C0805); D.cap("expansion", "100nF", "3V3")
# ESP32-C6
U8 = D.part("U8", "waffle:ESP32-C6-WROOM-1U", "ESP32-C6-WROOM-1U-N8", "expansion")
for num, net in {"1": "GND", "28": "GND", "29": "GND", "2": "3V3", "3": "ESP_EN", "15": "ESP_BOOT", "25": "ESP_TXD", "24": "ESP_RXD",
                 "17": "ESP_SDIO_CLK", "16": "ESP_SDIO_CMD", "18": "ESP_SDIO_D0", "19": "ESP_SDIO_D1", "20": "ESP_SDIO_D2", "21": "ESP_SDIO_D3", "23": "ESP_HS"}.items():
    D.connect(net, ("U8", num))
for num in ("4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "22", "26", "27"): D.no_connect("U8", num)
D.res("expansion", "10k", "ESP_EN", "3V3"); D.cap("expansion", "1uF", "ESP_EN", fp=C0603); D.res("expansion", "10k", "ESP_BOOT", "3V3")
for n in ("ESP_SDIO_CMD", "ESP_SDIO_D0", "ESP_SDIO_D1", "ESP_SDIO_D2", "ESP_SDIO_D3"): D.res("expansion", "10k", n, "3V3")
D.cap("expansion", "10uF", "3V3", fp=C0805); D.cap("expansion", "100nF", "3V3")
# PMODs: pins 1-4, 7-10 = signals, 5/11 GND, 6/12 VCC
for ref, name in (("J11", "PMOD_A"), ("J12", "PMOD_B"), ("J13", "PMOD_C"), ("J14", "PMOD_D")):
    D.part(ref, "Connector_Generic:Conn_02x06_Odd_Even", name, "expansion", "Connector_PinSocket_2.54mm:PinSocket_2x06_P2.54mm_Horizontal")
    for k in range(4):
        D.connect(f"{name}{k}", (ref, str(k + 1))); D.connect(f"{name}{k + 4}", (ref, str(k + 7)))
    D.connect("GND", (ref, "5"), (ref, "11")); D.connect("3V3", (ref, "6"), (ref, "12"))
# 2x20 header: odd pins 1..39, even 2..40. 1=3V3, 2=5V_SYS, 27 GPIO, rest GND
D.part("J15", "Connector_Generic:Conn_02x20_Odd_Even", "EXT 2x20", "expansion", "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical")
D.connect("3V3", ("J15", "1")); D.connect("5V_SYS", ("J15", "2"))
gpio_pins = [3, 4, 5, 7, 8, 10, 11, 12, 13, 15, 16, 18, 19, 21, 22, 23, 24, 26, 27, 28, 29, 31, 32, 33, 35, 36, 37]
gnd_pins = [p for p in range(3, 41) if p not in gpio_pins]
for k, pnum in enumerate(gpio_pins): D.connect(f"EXT{k}", ("J15", str(pnum)))
D.connect("GND", *[("J15", str(p)) for p in gnd_pins])
D.note("expansion", "2x20: pin1 3V3, pin2 5V_SYS, EXT0..EXT26 on the numbered pins (see bank-summary.md for FPGA balls), remaining pins GND.")
# LEDs via 74HC595
D.part("U14", "74xx:74HC595", "74HC595PW", "expansion", "Package_SO:TSSOP-16_4.4x5mm_P0.65mm")
D.connect("LED_SR_MOSI", ("U14", "SER")); D.connect("LED_SR_SCLK", ("U14", "SRCLK")); D.connect("LED_SR_LATCH", ("U14", "RCLK"))
D.connect("3V3", ("U14", "VCC"), ("U14", "~{SRCLR}")); D.connect("GND", ("U14", "GND"), ("U14", "~{OE}")); D.no_connect("U14", "QH'")
for k, q in enumerate(("QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH")):
    D.connect(f"LED{k}_Q", ("U14", q)); D.res("expansion", "1k", f"LED{k}_Q", f"LED{k}_A"); D.led("expansion", f"LED{k}", "GND", f"LED{k}_A")
D.cap("expansion", "100nF", "3V3")
D.res("expansion", "1k", "3V3", "LED_PWR_A"); D.led("expansion", "LED PWR", "GND", "LED_PWR_A")

# =============================================================================
# Power tree
# =============================================================================
J1 = D.part("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C power (PD)", "power", "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal")
D.connect("VBUS_IN", ("J1", "A4"), ("J1", "A9"), ("J1", "B4"), ("J1", "B9")); D.connect("GND", ("J1", "A1"), ("J1", "A12"), ("J1", "B1"), ("J1", "B12"), ("J1", "S1"))
D.connect("J1_CC1", ("J1", "A5")); D.connect("J1_CC2", ("J1", "B5")); D.connect("J1_DP", ("J1", "A6"), ("J1", "B6")); D.connect("J1_DM", ("J1", "A7"), ("J1", "B7")); D.no_connect("J1", "A8", "B8")
D.part("D7", "Device:D_TVS", "SMBJ20A", "power", "Diode_SMD:D_SMB"); D.connect("VBUS_IN", ("D7", "1")); D.connect("GND", ("D7", "2"))
D.pwrflag("power", "VBUS_IN")
U16 = D.part("U16", "Interface_USB:CH224K", "CH224K", "power")
D.connect("J1_CC1", ("U16", "CC1")); D.connect("J1_CC2", ("U16", "CC2")); D.connect("J1_DP", ("U16", "DP")); D.connect("J1_DM", ("U16", "DM"))
D.res("power", "10k", "VBUS_IN", "CH224_VBUS"); D.connect("CH224_VBUS", ("U16", "VBUS"))
D.connect("3V3_STBY", ("U16", "VDD"), ("U16", "CFG3")); D.cap("power", "1uF", "3V3_STBY", fp=C0603)
D.connect("GND", ("U16", "GND"), ("U16", "CFG1"), ("U16", "CFG2"))
D.connect("PD_PG_N", ("U16", "PG"))
D.note("power", "CH224K: VDD from 3V3_STBY, VBUS sensed through 10k; CFG1=0 CFG2=0 CFG3=1 requests 12 V (source falls back to 9 V / 5 V); PG open-drain, low when the contract is reached -> STM32 PD_PG_N (pull-up on the STM32 sheet).")
# eFuse
U17 = D.part("U17", "waffle:TPS259474ARPW", "TPS259474ARPWR", "power")
D.connect("VBUS_IN", ("U17", "5")); D.connect("VIN", ("U17", "6")); D.connect("GND", ("U17", "8"))
D.connect("EFUSE_EN", ("U17", "1")); D.res("power", "1M", "VBUS_IN", "EFUSE_EN"); D.res("power", "383k", "EFUSE_EN", "GND")            # UVLO 1.20 V rising -> VBUS 4.33 V on / 3.93 V off
D.connect("EFUSE_OVLO", ("U17", "2")); D.res("power", "1M", "VBUS_IN", "EFUSE_OVLO"); D.res("power", "90.9k", "EFUSE_OVLO", "GND")       # OVLO 1.20 V -> 14.4 V rising / 13.1 V falling (12 V + 5 % = 12.6 V passes)
D.connect("EFUSE_PG", ("U17", "3")); D.res("power", "100k", "EFUSE_PG", "3V3_STBY"); D.connect("EFUSE_PGTH", ("U17", "4")); D.res("power", "1M", "VIN", "EFUSE_PGTH"); D.res("power", "383k", "EFUSE_PGTH", "GND")   # PG asserts once VIN > 4.33 V
D.connect("EFUSE_ILM", ("U17", "9")); D.res("power", "953 (ILIM 3.5A)", "EFUSE_ILM", "GND")   # ILIM ~= 3.34 kOhm.A / RILM (DS table: 750 R -> 4.45 A, 6.65k -> 0.5 A); D.connect("EFUSE_ITIMER", ("U17", "10")); D.cap("power", "100nF", "EFUSE_ITIMER")
D.connect("EFUSE_DVDT", ("U17", "7")); D.cap("power", "10nF", "EFUSE_DVDT")
D.cap("power", "22uF 25V", "VBUS_IN", fp=C1206); D.cap("power", "22uF 25V", "VIN", fp=C1206)
# 5V_SYS buck: runs from any VBUS contract (EN divider 4.6 V on / 4.1 V off); on a 5 V-only source it sits at ~100 % duty and 5V_SYS
# tracks VIN minus ~0.3 V (D50: the LM66100 bypass of D38/D41 is a 5.5 V part and was removed)
U18 = D.part("U18", "Regulator_Switching:TPS54560BDDA", "TPS54560BDDAR", "power")
D.connect("VIN", ("U18", "VIN")); D.connect_all_named("GND", "U18", "GND")
D.connect("BUCK5_EN", ("U18", "EN")); D.res("power", "147k", "VIN", "BUCK5_EN"); D.res("power", "49.9k", "BUCK5_EN", "GND")   # DS eq. 4/5 with Ip 1.2 uA, Ihys 3.4 uA: start 4.6 V, stop 4.1 V
D.connect("BUCK5_SW", ("U18", "SW")); D.connect("BUCK5_BOOT", ("U18", "BOOT")); D.cap("power", "100nF", "BUCK5_BOOT", "BUCK5_SW")
D.ind("power", "6.8uH 6.5A", "BUCK5_SW", "5V_SYS", fp="Inductor_SMD:L_Bourns_SRP7028A_7.3x6.6mm")   # DS 5 V / 5 A / 400 kHz example: ~7 uH, Isat > 6 A
D.connect("BUCK5_FB", ("U18", "FB")); D.res("power", "53.6k", "5V_SYS", "BUCK5_FB"); D.res("power", "10.2k", "BUCK5_FB", "GND")
D.connect("BUCK5_COMP", ("U18", "COMP")); D.res("power", "17.4k", "BUCK5_COMP", "BUCK5_COMPC"); D.cap("power", "5.6nF", "BUCK5_COMPC")   # type 2A for 3 x 47 uF (87 uF derated), fco ~30 kHz: R = 2.pi.fco.Cout.Vout/(gmps 17 A/V . 0.8 V . gmea 350 uA/V); confirm in WEBENCH
D.connect("BUCK5_RT", ("U18", "RT/CLK")); D.res("power", "243k (400kHz)", "BUCK5_RT", "GND")   # RT = 101756 x f^-1.008 (DS example)
for _ in range(2): D.cap("power", "10uF 25V", "VIN", fp=C1206)
for _ in range(3): D.cap("power", "47uF 10V", "5V_SYS", fp=C1206)
D.pwrflag("power", "5V_SYS")   # the rail is driven through the inductor (passive), so ERC needs the flag   # DS example output filter (ceramic only; compensation above assumes it)
D.note("power", "5V_SYS: TPS54560B runs on every contract (EN 4.6 V on / 4.1 V off). At 12/9 V it regulates 5.0 V; on a 5 V-only source it runs at ~100 % duty and 5V_SYS = VIN - ~0.3 V (USB host ports are then below the 4.75 V spec, so the STM32 keeps them off until CH224K reports >= 9 V). No bypass part (D50).")
# 3V3_STBY LDO
D.part("U24", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3TRG1", "power")
D.connect("5V_SYS", ("U24", "VIN"), ("U24", "EN")); D.connect("3V3_STBY", ("U24", "VOUT")); D.connect("GND", ("U24", "GND")); D.no_connect("U24", "NC")
D.cap("power", "1uF", "5V_SYS", fp=C0603); D.cap("power", "10uF", "3V3_STBY", fp=C0805)
# 3V3 / 1V35 / 1V1 bucks with supervisors
def buck(ref, rail, en_net, l_val, rtop, rbot, sup_ref, sup_val, pg_net):
    D.part(ref, "Regulator_Switching:TPS563201", "TPS563201DDCR", "power")
    D.connect("5V_SYS", (ref, "VIN")); D.connect("GND", (ref, "GND")); D.connect(en_net, (ref, "EN"))
    D.connect(f"{rail}_SW", (ref, "SW")); D.connect(f"{rail}_BST", (ref, "VBST")); D.cap("power", "100nF", f"{rail}_BST", f"{rail}_SW")
    D.ind("power", l_val, f"{rail}_SW", rail, fp="Inductor_SMD:L_1210_3225Metric")
    D.connect(f"{rail}_FB", (ref, "VFB")); D.res("power", rtop, rail, f"{rail}_FB"); D.res("power", rbot, f"{rail}_FB", "GND")
    D.cap("power", "10uF", "5V_SYS", fp=C0805); D.cap("power", "22uF", rail, fp=C0805); D.cap("power", "22uF", rail, fp=C0805)
    D.pwrflag("power", rail)
    D.part(sup_ref, "waffle:TPS3839DBZ", sup_val, "power")
    D.connect(rail, (sup_ref, "3")); D.connect("GND", (sup_ref, "1")); D.connect(pg_net, (sup_ref, "2"))
    D.cap("power", "100nF", rail)
buck("U19", "3V3", "MAIN_EN", "2.2uH 4A", "33k", "10k", "U28", "TPS3839G33", "PG_3V3")          # 0.768 V x (1 + 33/10) = 3.30 V; G33 threshold 3.08 V
buck("U20", "1V35", "PG_3V3", "2.2uH 4A", "10.0k", "13.3k", "U29", "TPS3839G12", "PG_1V35")     # 1.345 V; G12 threshold 1.10 V
buck("U21", "1V1", "PG_1V35", "2.2uH 4A", "5.76k", "13.3k", "U30", "TPS3839A09", "PG_1V1")      # 1.100 V; A09 threshold 0.90 V
D.res("power", "100k", "MAIN_EN", "GND")
# 2V5 LDO for VCCAUX
D.part("U23", "Regulator_Linear:AP2112K-2.5", "AP2112K-2.5TRG1", "power")
D.connect("3V3", ("U23", "VIN"), ("U23", "EN")); D.connect("2V5", ("U23", "VOUT")); D.connect("GND", ("U23", "GND")); D.no_connect("U23", "NC")
D.cap("power", "1uF", "3V3", fp=C0603); D.cap("power", "10uF", "2V5", fp=C0805)
# VTT / VREF
D.part("U22", "Regulator_Linear:TPS51200DRC", "TPS51200DRCR", "power")
D.connect("3V3", ("U22", "VIN")); D.connect("1V35", ("U22", "VLDOIN")); D.connect("VTT", ("U22", "VO"), ("U22", "VOSNS"))
D.connect_all_named("GND", "U22", "GND"); D.connect("PG_1V35", ("U22", "EN")); D.no_connect("U22", "PGOOD")
D.connect("VTT_REFIN", ("U22", "REFIN")); D.res("power", "10k 1%", "1V35", "VTT_REFIN"); D.res("power", "10k 1%", "VTT_REFIN", "GND"); D.cap("power", "100nF", "VTT_REFIN")
D.connect("VREF_DDR", ("U22", "REFOUT")); D.cap("power", "100nF", "VREF_DDR")
D.cap("power", "10uF", "1V35", fp=C0805); D.cap("power", "10uF", "VTT", fp=C0805); D.cap("power", "1uF", "3V3", fp=C0603)
D.pwrflag("power", "GND")
# bring-up test points, one per rail plus GND (D57)
for i, rail in enumerate(("VBUS_IN", "VIN", "5V_SYS", "3V3_STBY", "3V3", "1V35", "1V1", "2V5", "VTT", "VREF_DDR", "GND"), start=1):
    D.part(f"TP{i}", "Connector:TestPoint", rail, "power", "TestPoint:TestPoint_Pad_D1.5mm")
    D.connect(rail, (f"TP{i}", "1"))
D.note("power", "Sequence: MAIN_EN -> 3V3 (+2V5 LDO) -> PG_3V3 -> 1V35 (+VTT/VREF) -> PG_1V35 -> 1V1 -> PG_1V1. Divider/threshold values checked against the TI datasheets (D50): TPS563201 VFB 0.768 V, TPS54560B FB 0.8 V, TPS3839 VIT- per variant.")

if __name__ == "__main__":
    D.render(os.path.dirname(os.path.abspath(__file__)))
