#!/usr/bin/env python3
"""Post-route report: per-net routed length for the length-sensitive buses, pair skew, unrouted count.
Usage: python3 hw/tools/route_report.py  (writes hw/route-report.md)"""
import os, re, pcbnew
from collections import defaultdict
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def net_lengths(b):
    L = defaultdict(float); vias = defaultdict(int)
    for t in b.GetTracks():
        n = t.GetNetname()
        if t.Type() == pcbnew.PCB_VIA_T: vias[n] += 1
        else: L[n] += pcbnew.ToMM(t.GetLength())
    return L, vias

def main():
    b = pcbnew.LoadBoard(os.path.join(HW, "waffle.kicad_pcb"))
    L, V = net_lengths(b)
    names = [str(n) for n in b.GetNetsByName().keys()]
    out = ["# Route report", "", f"Tracks/vias on the board: {sum(1 for t in b.GetTracks() if t.Type() != pcbnew.PCB_VIA_T)} segments, {sum(V.values())} vias.", ""]
    # DDR3 byte lanes: DQ/DM vs their DQS
    def lane(i):
        dq = [f"DDR3_DQ{k}" for k in range(8 * i, 8 * i + 8)] + [f"DDR3_DM{i}"]
        p, n_ = f"DDR3_DQS_P{i}", f"DDR3_DQS_N{i}"
        ref = (L.get(p, 0) + L.get(n_, 0)) / 2
        rows = [f"| {n} | {L.get(n, 0):.2f} | {L.get(n, 0) - ref:+.2f} | {V.get(n, 0)} |" for n in dq]
        return [f"## DDR3 byte lane {i} (strobe DQS{i}: {ref:.2f} mm avg, P/N skew {L.get(p, 0) - L.get(n_, 0):+.2f} mm; target DQ/DM within ±0.6 mm of DQS)", "", "| Net | Length mm | vs DQS | vias |", "|---|---:|---:|---:|"] + rows + [""]
    for i in (0, 1): out += lane(i)
    ck = ["DDR3_CLK_P", "DDR3_CLK_N"]
    ac = sorted(n for n in names if re.match(r"DDR3_(A\d+|BA\d|RAS_N|CAS_N|WE_N|CS_N|CKE|ODT|RESET_N)$", n))
    ckref = sum(L.get(n, 0) for n in ck) / max(1, len(ck))
    out += [f"## DDR3 address/command (CK {', '.join(ck)}: {ckref:.2f} mm avg)", "", "| Net | Length mm | vs CK | vias |", "|---|---:|---:|---:|"]
    out += [f"| {n} | {L.get(n, 0):.2f} | {L.get(n, 0) - ckref:+.2f} | {V.get(n, 0)} |" for n in ac] + [""]
    out += ["## Differential pairs (P vs N)", "", "| Pair | P mm | N mm | skew mm |", "|---|---:|---:|---:|"]
    pairs = sorted({re.sub(r"_(P|N)(_C)?$", r"\2", n) for n in names if re.search(r"_(P|N)(_C)?$", n) and (n.startswith("HDMI_D") or n.startswith("HDMI_CLK") or n.startswith("DDR3_CLK"))})
    for p in pairs:
        base, suf = (p[:-2], "_C") if p.endswith("_C") else (p, "")
        P, N = L.get(f"{base}_P{suf}", 0), L.get(f"{base}_N{suf}", 0)
        out.append(f"| {base}{suf} | {P:.2f} | {N:.2f} | {P - N:+.2f} |")
    for i in (0, 1):
        P, N = L.get(f"DDR3_DQS_P{i}", 0), L.get(f"DDR3_DQS_N{i}", 0); out.append(f"| DDR3_DQS{i} | {P:.2f} | {N:.2f} | {P - N:+.2f} |")
    usb = sorted({re.sub(r"_D[PM]$", "", n) for n in names if re.search(r"_D[PM]$", n)})
    for p in usb: out.append(f"| {p} | {L.get(p + '_DP', 0):.2f} | {L.get(p + '_DM', 0):.2f} | {L.get(p + '_DP', 0) - L.get(p + '_DM', 0):+.2f} |")
    out.append("")
    # remaining work: pads with no track and no plane on their layer (KiCad's own unconnected count is given too)
    b.BuildConnectivity(); c = b.GetConnectivity()
    zl = {}
    for z in b.Zones():
        if not z.GetIsRuleArea(): zl.setdefault(z.GetNetname(), set()).add(z.GetLayer())
    unr = defaultdict(int); per_ref = defaultdict(int); total_pads = 0
    for f in b.GetFootprints():
        for p in f.Pads():
            n = p.GetNetname()
            if not n or n.startswith("unconnected"): continue
            total_pads += 1
            if len(c.GetConnectedTracks(p)) == 0 and not (n in zl and any(p.IsOnLayer(l) for l in zl[n])):
                unr[n] += 1; per_ref[f.GetReference()] += 1
    PW = ("GND", "3V3", "1V1", "1V35", "5V", "2V5", "VTT", "VREF", "PHY_1V8", "FT_1V8", "FT_3V3")
    plane = sum(v for k, v in unr.items() if any(k.startswith(x) for x in PW))
    sig = sorted((k, v) for k, v in unr.items() if not any(k.startswith(x) for x in PW))
    out += [f"## Remaining work", "", f"KiCad unconnected count: {c.GetUnconnectedCount(True)}. Pads with no copper: {sum(unr.values())} of {total_pads} ({plane} on plane nets, i.e. missing a via to the plane; {sum(v for _, v in sig)} on {len(sig)} signal nets).", "",
            "| Footprint | pads without copper |", "|---|---:|"] + [f"| {r} | {v} |" for r, v in sorted(per_ref.items(), key=lambda kv: -kv[1])[:15]] + ["",
            "Signal nets with an unconnected pad: " + ", ".join(f"{k} ({v})" for k, v in sig), ""]
    open(os.path.join(HW, "route-report.md"), "w").write("\n".join(out))
    print("\n".join(out[:6])); print(f"... pads with no copper: {sum(unr.values())} ({plane} plane-net, {sum(v for _, v in sig)} signal)")

if __name__ == "__main__":
    main()
