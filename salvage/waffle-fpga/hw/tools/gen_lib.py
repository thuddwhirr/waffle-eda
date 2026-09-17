#!/usr/bin/env python3
"""Generate hw/lib/waffle.kicad_sym: custom parts (pin data transcribed from the
manufacturer datasheets listed per part) and global power symbols for every rail."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from symlib import box_symbol, power_symbol, write_lib

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "lib")

def ddr3():
    balls = json.load(open(os.path.join(LIB, "ddr3_x16_balls.json")))   # from Alliance AS4C512M16D3L datasheet Fig. 7 (JEDEC x16 FBGA-96)
    def typ(n):
        if n.startswith("DQ") or n in ("LDQS", "LDQS#", "UDQS", "UDQS#"): return "bidirectional"
        if n.startswith(("VDD", "VSS")): return "power_in"
        if n == "NC": return "no_connect"
        if n == "ZQ": return "passive"
        return "input"
    def nm(n): return n.replace("#", "").join(("~{", "}")) if n.endswith("#") else n
    items = sorted(balls.items())
    dq = [(b, n) for b, n in items if n.startswith("DQ")]
    dq.sort(key=lambda t: int(t[1][2:]))
    strobes = [(b, n) for b, n in items if "DQS" in n or n in ("LDM", "UDM")]
    addr = [(b, n) for b, n in items if n.startswith("A") and n[1].isdigit()]
    addr.sort(key=lambda t: int(t[1][1:].split("/")[0]))
    ba = [(b, n) for b, n in items if n.startswith("BA")]
    cmd = [(b, n) for b, n in items if n in ("RAS#", "CAS#", "WE#", "CS#", "CKE", "ODT", "CK", "CK#", "RESET#", "ZQ")]
    pwr = [(b, n) for b, n in items if n.startswith(("VDD", "VSS", "VREF"))]
    nc = [(b, n) for b, n in items if n == "NC"]
    left = [(b, nm(n), typ(n)) for b, n in addr] + [None] + [(b, nm(n), typ(n)) for b, n in ba] + [None] + [(b, nm(n), typ(n)) for b, n in cmd]
    right = [(b, nm(n), typ(n)) for b, n in dq] + [None] + [(b, nm(n), typ(n)) for b, n in strobes] + [None] + [(b, nm(n), typ(n)) for b, n in nc]
    vdd = [(b, n, "power_in") for b, n in pwr if n in ("VDD", "VDDQ")] + [(b, n, "input") for b, n in pwr if n.startswith("VREF")]
    vss = [(b, n, "power_in") for b, n in pwr if n in ("VSS", "VSSQ")]
    return box_symbol("DDR3L_x16_FBGA96", left, right, top=vdd, bottom=vss,
                      footprint="Package_BGA:Micron_FBGA-96_7.5x13.5mm_Layout9x16_P0.8mm", ref="U", value="MT41K512M16HA-107:A",
                      datasheet="https://www.alliancememory.com/wp-content/uploads/AS4C512M16D3L-12BCN_20160614-8GB_DDR3L_AS4C512M16D3L_AS4C1G8MD3L-revised-v-2.0-June-2016.pdf",
                      description="DDR3L SDRAM 8 Gbit x16, JEDEC 96-ball FBGA (MT41K512M16 / AS4C512M16D3L / IS43TR16512BL)", keywords="DDR3L SDRAM")

def usb3320():
    # Microchip USB3320 DS00001792E Table 2-1
    p = {1:("CLKOUT","output"),2:("NXT","output"),3:("DATA0","bidirectional"),4:("DATA1","bidirectional"),5:("DATA2","bidirectional"),6:("DATA3","bidirectional"),
         7:("DATA4","bidirectional"),8:("REFSEL0","input"),9:("DATA5","bidirectional"),10:("DATA6","bidirectional"),11:("REFSEL1","input"),12:("NC","no_connect"),
         13:("DATA7","bidirectional"),14:("REFSEL2","input"),15:("SPK_L","passive"),16:("SPK_R","passive"),17:("CPEN","output"),18:("DP","bidirectional"),19:("DM","bidirectional"),
         20:("VDD33","power_in"),21:("VBAT","power_in"),22:("VBUS","bidirectional"),23:("ID","input"),24:("RBIAS","passive"),25:("XO","output"),26:("REFCLK","input"),
         27:("~{RESET}","input"),28:("VDD18","power_in"),29:("STP","input"),30:("VDD18","power_in"),31:("DIR","output"),32:("VDDIO","power_in"),33:("GND","power_in")}
    L = [(str(n),)+p[n] for n in (26,25,27,29,3,4,5,6,7,9,10,13,2,31,1)]
    R = [(str(n),)+p[n] for n in (18,19,23,22,17,24,15,16,8,11,14,12)]
    T = [(str(n),)+p[n] for n in (20,21,32,28,30)]
    B = [("33","GND","power_in")]
    return box_symbol("USB3320C-EZK", L, R, T, B, footprint="Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm", value="USB3320C-EZK",
                      datasheet="https://ww1.microchip.com/downloads/en/DeviceDoc/00001792E.pdf", description="USB 2.0 HS ULPI transceiver, QFN-32", keywords="USB ULPI PHY")

def aic3204():
    # TI TLV320AIC3204 SLOS602E pin functions
    p = {1:("MCLK","input"),2:("BCLK","bidirectional"),3:("WCLK","bidirectional"),4:("DIN/MFP1","input"),5:("DOUT/MFP2","output"),6:("IOVDD","power_in"),7:("IOVSS","power_in"),
         8:("SCLK/MFP3","input"),9:("SCL/~{SS}","input"),10:("SDA/MOSI","bidirectional"),11:("MISO/MFP4","output"),12:("SPI_SELECT","input"),13:("IN1_L","input"),14:("IN1_R","input"),
         15:("IN2_L","input"),16:("IN2_R","input"),17:("AVSS","power_in"),18:("REF","passive"),19:("MICBIAS","output"),20:("IN3_L","input"),21:("IN3_R","input"),22:("LOL","output"),
         23:("LOR","output"),24:("AVDD","power_in"),25:("HPL","output"),26:("LDOIN/HPVDD","power_in"),27:("HPR","output"),28:("DVSS","power_in"),29:("DVDD","power_in"),
         30:("LDO_SELECT","input"),31:("~{RESET}","input"),32:("GPIO/MFP5","bidirectional"),33:("EP","passive")}
    L = [(str(n),)+p[n] for n in (1,2,3,4,5,None,9,10,8,11,12,None,31,30,32)] if False else None
    L = [((str(n),)+p[n]) if n else None for n in (1,2,3,4,5,None,9,10,8,11,12,None,31,30,32)]
    R = [((str(n),)+p[n]) if n else None for n in (13,14,15,16,20,21,None,22,23,25,27,None,19,18)]
    T = [((str(n),)+p[n]) for n in (26,24,29,6)]
    B = [((str(n),)+p[n]) for n in (17,28,7,33)]
    return box_symbol("TLV320AIC3204IRHB", L, R, T, B, footprint="Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm", value="TLV320AIC3204IRHBR",
                      datasheet="https://www.ti.com/lit/ds/symlink/tlv320aic3204.pdf", description="Stereo audio codec, VQFN-32", keywords="audio codec I2S")

def tpd12s016():
    # TI TPD12S016 SLLSE96F, PW (TSSOP-24) column of the pin table
    p = {1:("CEC_A","bidirectional"),2:("SCL_A","bidirectional"),3:("SDA_A","bidirectional"),4:("HPD_A","output"),5:("LS_OE","input"),6:("GND","power_in"),
         7:("CEC_B","bidirectional"),8:("SCL_B","bidirectional"),9:("SDA_B","bidirectional"),10:("HPD_B","input"),11:("VCC5V","power_in"),12:("CT_HPD","input"),
         13:("5V_OUT","power_out"),14:("GND","power_in"),15:("CLK-","passive"),16:("CLK+","passive"),17:("D0-","passive"),18:("D0+","passive"),19:("GND","power_in"),
         20:("D1-","passive"),21:("D1+","passive"),22:("D2-","passive"),23:("D2+","passive"),24:("VCCA","power_in")}
    L = [((str(n),)+p[n]) if n else None for n in (1,2,3,4,5,12,None,7,8,9,10,13)]
    R = [((str(n),)+p[n]) if n else None for n in (23,22,21,20,18,17,16,15)]
    T = [((str(n),)+p[n]) for n in (24,11)]
    B = [((str(n),)+p[n]) for n in (6,14,19)]
    return box_symbol("TPD12S016PW", L, R, T, B, footprint="Package_SO:TSSOP-24_4.4x7.8mm_P0.65mm", value="TPD12S016PWR",
                      datasheet="https://www.ti.com/lit/ds/symlink/tpd12s016.pdf", description="HDMI companion: ESD, DDC/CEC level shift, HPD, 5 V switch", keywords="HDMI ESD")

def tps25947():
    # TI TPS25947 SLVSFC9C Table 5-1, TPS259474 variant (PG / PGTH)
    L = [("5","IN","power_in"),("1","EN/UVLO","input"),("2","OVLO","input"),("9","ILM","passive"),("10","ITIMER","passive")]
    R = [("6","OUT","power_out"),("3","PG","open_collector"),("4","PGTH","input"),("7","DVDT","passive")]
    B = [("8","GND","power_in")]
    return box_symbol("TPS259474ARPW", L, R, (), B, footprint="Package_DFN_QFN:Texas_RUN0010A_WQFN-10_2x2mm_P0.5mm", value="TPS259474ARPWR",
                      datasheet="https://www.ti.com/lit/ds/symlink/tps25947.pdf", description="eFuse 2.7-23 V 5.5 A with reverse blocking, QFN-10", keywords="efuse")

def tps2553():
    L = [("1","IN","power_in"),("3","EN","input"),("5","ILIM","passive")]
    R = [("6","OUT","power_out"),("4","~{FAULT}","open_collector")]
    B = [("2","GND","power_in")]
    return box_symbol("TPS2553DBV", L, R, (), B, footprint="Package_TO_SOT_SMD:SOT-23-6", value="TPS2553DBVR",
                      datasheet="https://www.ti.com/lit/ds/symlink/tps2553.pdf", description="USB power switch, adjustable current limit, SOT-23-6", keywords="USB power switch")

def tps3839():
    L = [("3","VDD","power_in")]; R = [("2","~{RESET}","output")]; B = [("1","GND","power_in")]
    return box_symbol("TPS3839DBZ", L, R, (), B, footprint="Package_TO_SOT_SMD:SOT-23-3", value="TPS3839xxDBZR",
                      datasheet="https://www.ti.com/lit/ds/symlink/tps3839.pdf", description="Voltage supervisor, SOT-23-3", keywords="supervisor reset")

def lm66100():
    L = [("1","VIN","power_in"),("3","~{CE}","input")]; R = [("6","VOUT","power_out"),("5","~{ST}","open_collector"),("4","NC","no_connect")]; B = [("2","GND","power_in")]
    return box_symbol("LM66100DCK", L, R, (), B, footprint="Package_TO_SOT_SMD:SOT-363_SC-70-6", value="LM66100DCKR",
                      datasheet="https://www.ti.com/lit/ds/symlink/lm66100.pdf", description="Ideal diode 1.5 A with enable, SC70-6", keywords="ideal diode")

def esp32c6():
    # Espressif ESP32-C6-WROOM-1/1U datasheet pin definitions (module pins 1-29)
    p = {1:("GND","power_in"),2:("3V3","power_in"),3:("EN","input"),4:("IO4","bidirectional"),5:("IO5","bidirectional"),6:("IO6","bidirectional"),7:("IO7","bidirectional"),
         8:("IO0","bidirectional"),9:("IO1","bidirectional"),10:("IO8","bidirectional"),11:("IO10","bidirectional"),12:("IO11","bidirectional"),13:("IO12/USB_D-","bidirectional"),
         14:("IO13/USB_D+","bidirectional"),15:("IO9/BOOT","bidirectional"),16:("IO18/SDIO_CMD","bidirectional"),17:("IO19/SDIO_CLK","bidirectional"),18:("IO20/SDIO_D0","bidirectional"),
         19:("IO21/SDIO_D1","bidirectional"),20:("IO22/SDIO_D2","bidirectional"),21:("IO23/SDIO_D3","bidirectional"),22:("NC","no_connect"),23:("IO15","bidirectional"),
         24:("IO17/U0RXD","bidirectional"),25:("IO16/U0TXD","bidirectional"),26:("IO3","bidirectional"),27:("IO2","bidirectional"),28:("GND","power_in"),29:("GND","power_in")}
    L = [((str(n),)+p[n]) if n else None for n in (3,15,None,25,24,None,17,16,18,19,20,21)]
    R = [((str(n),)+p[n]) if n else None for n in (4,5,6,7,8,9,10,11,12,13,14,23,26,27,22)]
    T = [("2","3V3","power_in")]; B = [("1","GND","power_in"),("28","GND","power_in"),("29","GND","power_in")]
    return box_symbol("ESP32-C6-WROOM-1U", L, R, T, B, footprint="waffle:ESP32-C6-WROOM-1U", value="ESP32-C6-WROOM-1U-N8",
                      datasheet="https://www.espressif.com/sites/default/files/documentation/esp32-c6-wroom-1_wroom-1u_datasheet_en.pdf",
                      description="Wi-Fi 6 / BLE 5 / 802.15.4 module, external antenna", keywords="ESP32 WiFi module")

def w25q256():
    L = [("1","~{CS}","input"),("6","CLK","input"),("5","DI/IO0","bidirectional"),("2","DO/IO1","bidirectional"),("3","~{WP}/IO2","bidirectional"),("7","~{HOLD}/IO3","bidirectional")]
    T = [("8","VCC","power_in")]; B = [("4","GND","power_in"),("9","EP","passive")]
    return box_symbol("W25Q256JVEIQ", L, [], T, B, footprint="Package_SON:WSON-8-1EP_8x6mm_P1.27mm_EP3.4x4.3mm", value="W25Q256JVEIQ",
                      datasheet="https://www.winbond.com/", description="256 Mbit QSPI NOR flash, WSON-8 8x6", keywords="flash QSPI")

RAILS = ["VIN", "VBUS_IN", "5V_SYS", "3V3_STBY", "3V3", "1V35", "VTT", "VREF_DDR", "2V5", "1V1", "5V_USB1", "5V_USB2", "5V_USB3", "5V_HDMI", "VBUS_UPLINK", "3V3A"]

def main():
    syms = [ddr3(), usb3320(), aic3204(), tpd12s016(), tps25947(), tps2553(), tps3839(), lm66100(), esp32c6(), w25q256()]
    syms.append(power_symbol("GND", "gnd"))
    syms.append(power_symbol("GNDA", "gnd"))
    for r in RAILS:
        syms.append(power_symbol(r))
    os.makedirs(LIB, exist_ok=True)
    write_lib(os.path.join(LIB, "waffle.kicad_sym"), syms)
    print("wrote", len(syms), "symbols")

if __name__ == "__main__":
    main()
