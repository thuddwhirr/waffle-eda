#!/usr/bin/env python3
"""Check the STM32 pin-mux in hw/design.py against ST's open pin data (STM32H743ZITx.xml):
every peripheral signal must be an alternate function of the pin it is assigned to.
Usage: python3 hw/tools/check_stm32_af.py build/stm/STM32H743ZITx.xml"""
import re, sys, xml.etree.ElementTree as ET
xml = sys.argv[1] if len(sys.argv) > 1 else "build/stm/STM32H743ZITx.xml"
root = ET.parse(xml).getroot(); ns = {"m": root.tag.split("}")[0].strip("{")}
pins = {}
for p in root.findall("m:Pin", ns):
    name = re.split(r"[ (/\-]", p.get("Name"))[0]
    if name.endswith("_C"): name = name[:-2]           # PC2_C / PC3_C: the analog-switch side of the same GPIO
    pins[name] = {s.get("Name") for s in p.findall("m:Signal", ns)}, p.get("Type")
# required peripheral signal per design.py net (GPIO/EXTI/ADC-only pins are checked for type only)
WANT = {
    **{f"FMC_D{i}": f"FMC_D{i}" for i in range(16)}, **{f"FMC_A{i}": f"FMC_A{i}" for i in range(8)},
    "FMC_NOE": "FMC_NOE", "FMC_NWE": "FMC_NWE", "FMC_NE": "FMC_NE1",
    **{f"ULPI_D{i}": f"USB_OTG_HS_ULPI_D{i}" for i in range(8)},
    "ULPI_CLK": "USB_OTG_HS_ULPI_CK", "ULPI_DIR": "USB_OTG_HS_ULPI_DIR", "ULPI_NXT": "USB_OTG_HS_ULPI_NXT", "ULPI_STP": "USB_OTG_HS_ULPI_STP",
    "FT_RXD": "USART1_TX", "FT_TXD": "USART1_RX", "ESP_RXD": "USART6_TX", "ESP_TXD": "USART6_RX",
    "HDMI_SCL_A": "I2C1_SCL", "HDMI_SDA_A": "I2C1_SDA", "HDMI_CEC_A": "CEC",
    "VIN_SENSE": "ADC1_INP16", "SWDIO": "DEBUG_JTMS-SWDIO", "SWCLK": "DEBUG_JTCK-SWCLK", "SWO": "DEBUG_JTDO-SWO",
    "BTN_PWR_N": "PWR_WKUP4",   # PC13 wake-up pin (XML index; RM0433 calls it WKUP3)
}
src = open("hw/design.py").read()
body = src[src.index("stm = {"):src.index("def stm_pin")]
assign = dict(re.findall(r'"(P[A-H]\d+)":\s*"([A-Z0-9_]+)"', body))
bad = 0
for pin, net in sorted(assign.items(), key=lambda kv: (kv[0][1], int(kv[0][2:]))):
    if pin not in pins: print(f"{pin:5} {net:16} NOT IN PACKAGE"); bad += 1; continue
    sigs, typ = pins[pin]
    want = WANT.get(net)
    if want is None:
        ok = typ == "I/O"; print(f"{pin:5} {net:16} GPIO ({typ}){'' if ok else '  <-- not an I/O pin'}"); bad += 0 if ok else 1
    else:
        ok = want in sigs
        alt = [s for s in sigs if s.split("_")[0] == want.split("_")[0]]
        print(f"{pin:5} {net:16} needs {want:22} {'OK' if ok else 'MISSING; pin offers ' + ', '.join(sorted(alt))}"); bad += 0 if ok else 1
print("errors:", bad)
