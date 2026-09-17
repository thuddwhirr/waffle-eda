#!/usr/bin/env python3
"""Impedance geometry for PCBWay's published 6-layer 1.6 mm build (structure #1, 1 oz/1 oz, ≥60 % inner copper).
Closed-form estimates (IPC-2141-style microstrip/stripline, Wadell-based
differential coupling) — good to ~10 %; the fab's field-solver numbers win.
Usage: python3 hw/tools/impedance.py   (prints the table used in stackup.md; gen_pcb.py imports geometry())"""
import math

def z0_microstrip(w, h, t, er):
    """Surface microstrip (IPC-2141), w/h/t in mm."""
    weff = w + (t / math.pi) * (1 + math.log(2 * h / t)) * 0.5   # Wheeler-style thickness correction
    if weff / h <= 1:
        ere = (er + 1) / 2 + (er - 1) / 2 * ((1 + 12 * h / weff) ** -0.5 + 0.04 * (1 - weff / h) ** 2)
        z = 60 / math.sqrt(ere) * math.log(8 * h / weff + weff / (4 * h))
    else:
        ere = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 * h / weff) ** -0.5
        z = 120 * math.pi / (math.sqrt(ere) * (weff / h + 1.393 + 0.667 * math.log(weff / h + 1.444)))
    return z, ere

def zdiff_microstrip(w, s, h, t, er):
    z0, _ = z0_microstrip(w, h, t, er)
    return 2 * z0 * (1 - 0.48 * math.exp(-0.96 * s / h))

def z0_stripline(w, h1, h2, t, er):
    """Asymmetric stripline approximated as symmetric with b = h1+h2+t (IPC-2141 symmetric formula)."""
    b = h1 + h2 + t
    weff = w
    if w / b < 0.35:
        weff = w + (0.35 - w / b) ** 2 * b * 0  # small-w correction negligible here
    z = 60 / math.sqrt(er) * math.log(1.9 * b / (0.8 * weff + t))
    return z

def zdiff_stripline(w, s, h1, h2, t, er):
    z0 = z0_stripline(w, h1, h2, t, er)
    b = h1 + h2 + t
    return 2 * z0 * (1 - 0.347 * math.exp(-2.9 * s / b))

def solve(fn, target, lo, hi, *args):
    for _ in range(60):
        mid = (lo + hi) / 2
        if fn(mid, *args) > target: lo = mid
        else: hi = mid
    return (lo + hi) / 2

# PCBWay "6-layers PCB Regular, 1.6 mm, outer 1 oz, inner 1 oz, inner residual copper 70 %" (multi-layer-laminated-structure page,
# fetched 2026-09-11). Thickness after lamination; Dk as quoted by PCBWay (1 MHz values, so the estimates err slightly high in Z).
PCBWAY_6L = {
    "L1": 0.035,            # 0.5 oz base plated to 1 oz
    "pp12": 0.1195, "dk12": 4.45,   # 2116 RC58 %
    "core23": 0.43, "dk23": 4.6,
    "pp34": 0.175, "dk34": 4.74,    # 7628 RC46 %
    "core45": 0.43, "dk45": 4.6,
    "pp56": 0.1195, "dk56": 4.45,
    "L6": 0.035, "inner_cu": 0.035,
    "total": 1.55,          # finished, ±10 %
}

# PCBWay "8-layers PCB Regular, 1.6 mm, outer 1 oz, inner 1 oz, inner residual copper 70 %" (same page, structure #1).
# Layer use: L1 SIG | L2 GND | L3 SIG | L4 PWR | L5 GND | L6 SIG | L7 GND | L8 SIG  (every signal layer has a ground reference).
PCBWAY_8L = {
    "L1": 0.035, "pp12": 0.1195, "dk12": 4.45,      # 2116
    "core23": 0.23, "dk23": 4.6,
    "pp34": 0.175, "dk34": 4.74,                    # 7628
    "core45": 0.23, "dk45": 4.6,
    "pp56": 0.175, "dk56": 4.74,
    "core67": 0.23, "dk67": 4.6,
    "pp78": 0.1195, "dk78": 4.45,
    "L8": 0.035, "inner_cu": 0.035,
    "total": 1.62,
}

def geometry8(st=PCBWAY_8L):
    """Trace geometry for the 8-layer build: name -> (width, gap or None, layer, estimated Z)."""
    t_out, t_in = st["L1"], st["inner_cu"]; h12, er12 = st["pp12"], st["dk12"]
    g = 0.15; gs = 0.20
    def strip(h1, h2, dk1, dk2):
        er = (dk1 * h1 + dk2 * h2) / (h1 + h2)
        w50 = solve(lambda w: z0_stripline(w, h1, h2, t_in, er), 50, 0.05, 1.0)
        w100 = solve(lambda w: zdiff_stripline(w, gs, h1, h2, t_in, er), 100, 0.05, 1.0)
        return w50, w100, er
    w50 = solve(lambda w: z0_microstrip(w, h12, t_out, er12)[0], 50, 0.05, 1.0)
    w100 = solve(lambda w: zdiff_microstrip(w, g, h12, t_out, er12), 100, 0.05, 1.0)
    w90 = solve(lambda w: zdiff_microstrip(w, g, h12, t_out, er12), 90, 0.05, 1.0)
    w50_3, w100_3, er3 = strip(st["core23"], st["pp34"], st["dk23"], st["dk34"])     # L3 between GND2 and PWR4
    w50_6, w100_6, er6 = strip(st["pp56"], st["core67"], st["dk56"], st["dk67"])     # L6 between GND5 and GND7
    r = lambda x: round(x, 3)
    return {
        "SE50_L1": (r(w50), None, "L1/L8 microstrip", z0_microstrip(w50, h12, t_out, er12)[0]),
        "DIFF100_L1": (r(w100), g, "L1/L8 microstrip", zdiff_microstrip(w100, g, h12, t_out, er12)),
        "DIFF90_L1": (r(w90), g, "L1/L8 microstrip", zdiff_microstrip(w90, g, h12, t_out, er12)),
        "SE50_L3": (r(w50_3), None, "L3 stripline (GND L2 / PWR L4)", z0_stripline(w50_3, st["core23"], st["pp34"], t_in, er3)),
        "DIFF100_L3": (r(w100_3), gs, "L3 stripline", zdiff_stripline(w100_3, gs, st["core23"], st["pp34"], t_in, er3)),
        "SE50_L6": (r(w50_6), None, "L6 stripline (GND L5 / GND L7)", z0_stripline(w50_6, st["pp56"], st["core67"], t_in, er6)),
        "DIFF100_L6": (r(w100_6), gs, "L6 stripline", zdiff_stripline(w100_6, gs, st["pp56"], st["core67"], t_in, er6)),
    }

def geometry(st=PCBWAY_6L):
    """Trace geometry (mm) for each net class on this stack-up: dict name -> (width, gap or None, layer, estimated Z)."""
    t_out, t_in = st["L1"], st["inner_cu"]; h12, er12 = st["pp12"], st["dk12"]
    h23, h34 = st["core23"], st["pp34"]; er3 = (st["dk23"] * h23 + st["dk34"] * h34) / (h23 + h34)   # weighted Dk for L3 stripline
    g = 0.15; gs = 0.20
    w50 = solve(lambda w: z0_microstrip(w, h12, t_out, er12)[0], 50, 0.05, 1.0)
    w100 = solve(lambda w: zdiff_microstrip(w, g, h12, t_out, er12), 100, 0.05, 1.0)
    w90 = solve(lambda w: zdiff_microstrip(w, g, h12, t_out, er12), 90, 0.05, 1.0)
    w50s = solve(lambda w: z0_stripline(w, h23, h34, t_in, er3), 50, 0.05, 1.0)
    w100s = solve(lambda w: zdiff_stripline(w, gs, h23, h34, t_in, er3), 100, 0.05, 1.0)
    r = lambda x: round(x, 3)
    return {
        "SE50_L1": (r(w50), None, "L1/L6 microstrip", z0_microstrip(w50, h12, t_out, er12)[0]),
        "DIFF100_L1": (r(w100), g, "L1/L6 microstrip", zdiff_microstrip(w100, g, h12, t_out, er12)),
        "DIFF90_L1": (r(w90), g, "L1/L6 microstrip", zdiff_microstrip(w90, g, h12, t_out, er12)),
        "SE50_L3": (r(w50s), None, "L3 stripline (GND L2 / PWR L4)", z0_stripline(w50s, h23, h34, t_in, er3)),
        "DIFF100_L3": (r(w100s), gs, "L3 stripline", zdiff_stripline(w100s, gs, h23, h34, t_in, er3)),
    }

if __name__ == "__main__":
    st = PCBWAY_8L; G = geometry8(st)
    print(f"PCBWay 8-layer 1.6 mm structure #1 (D55): L1 | pp {st['pp12']} (Dk {st['dk12']}) | L2 GND | core {st['core23']} | L3 SIG | pp {st['pp34']} | L4 PWR | core {st['core45']} | L5 GND | pp {st['pp56']} | L6 SIG | core {st['core67']} | L7 GND | pp {st['pp78']} | L8; finished {st['total']} mm")
    print()
    print("| Net class | Layer | Target | Trace width | Gap (diff) | Estimated Z |")
    print("|---|---|---:|---:|---:|---:|")
    for k, name, tgt in [("SE50_L1", "50 Ω single-ended (clocks, SD, SDIO, FMC)", 50), ("DIFF100_L1", "100 Ω diff (TMDS, DDR3 DQS/CK)", 100), ("DIFF90_L1", "90 Ω diff (USB 2.0)", 90),
                         ("SE50_L3", "50 Ω single-ended (DDR3 addr/cmd)", 50), ("DIFF100_L3", "100 Ω diff (DDR3 CK on L3)", 100), ("SE50_L6", "50 Ω single-ended (L6)", 50), ("DIFF100_L6", "100 Ω diff (L6)", 100)]:
        w, gap, layer, z = G[k]
        print(f"| {name} | {layer} | {tgt} Ω | {w:.3f} mm | {'—' if gap is None else f'{gap:.3f} mm'} | {z:.1f} Ω |")
    print()
    print("Previous 6-layer build for reference:")
    st = PCBWAY_6L; G = geometry(st)
    print(f"PCBWay 6-layer 1.6 mm structure #1: L1 {st['L1']} | pp {st['pp12']} (Dk {st['dk12']}) | L2 GND | core {st['core23']} (Dk {st['dk23']}) | L3 | pp {st['pp34']} (Dk {st['dk34']}) | L4 PWR | core {st['core45']} | L5 GND | pp {st['pp56']} | L6; finished {st['total']} mm ±10 %")
    print()
    print("| Net class | Layer | Target | Trace width | Gap (diff) | Estimated Z |")
    print("|---|---|---:|---:|---:|---:|")
    rows = [("SE50_L1", "50 Ω single-ended (clocks, SD, SDIO, FMC)", 50), ("DIFF100_L1", "100 Ω diff (TMDS, DDR3 DQS/CK)", 100), ("DIFF90_L1", "90 Ω diff (USB 2.0)", 90),
            ("SE50_L3", "50 Ω single-ended (DDR3 addr/cmd)", 50), ("DIFF100_L3", "100 Ω diff (DDR3 CK on L3)", 100)]
    for k, name, tgt in rows:
        w, gap, layer, z = G[k]
        print(f"| {name} | {layer} | {tgt} Ω | {w:.3f} mm | {'—' if gap is None else f'{gap:.3f} mm'} | {z:.1f} Ω |")
    print()
    print("Closed-form (IPC-2141-style) estimates, ±10 %; PCBWay's field-solver numbers at quote time win. Dk values are PCBWay's 1 MHz figures, so real Z at GHz is a few % higher than shown.")
