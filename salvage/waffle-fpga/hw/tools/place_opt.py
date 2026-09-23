#!/usr/bin/env python3
"""Orientation check for the anchored parts: for each candidate reference, score the four rotations
(and optionally position offsets) by the summed Manhattan ratsnest length of its signal nets
(each pad to the nearest pad of the same net on another footprint). Power/GND nets are ignored.
Usage: python3 hw/tools/place_opt.py [REF ...]   (default: the big parts)"""
import sys, os, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_PREFIX = ("GND", "1V", "2V5", "3V3", "5V", "VTT", "VREF", "VBUS", "PHY_1V8", "FT_1V8", "FT_3V3", "CH224_VBUS", "PHY_VBUS", "DDR3_PSEUDO", "PG_")

def net_ok(n):
    return n and not n.startswith("unconnected") and not any(n.startswith(p) for p in SKIP_PREFIX)

def score(b, fp, others_by_net):
    tot = 0.0
    for p in fp.Pads():
        n = p.GetNetname()
        if not net_ok(n) or n not in others_by_net: continue
        px, py = p.GetPosition().x, p.GetPosition().y
        tot += min(abs(px - x) + abs(py - y) for x, y in others_by_net[n])
    return pcbnew.ToMM(int(tot))

def main(refs):
    b = pcbnew.LoadBoard(os.path.join(HW, "waffle.kicad_pcb"))
    for ref in refs:
        fp = b.FindFootprintByReference(ref)
        if fp is None: print(ref, "missing"); continue
        others = {}
        for f in b.GetFootprints():
            if f.GetReference() == ref: continue
            for p in f.Pads():
                n = p.GetNetname()
                if net_ok(n): others.setdefault(n, []).append((p.GetPosition().x, p.GetPosition().y))
        pos0, rot0 = fp.GetPosition(), fp.GetOrientationDegrees()
        res = []
        for rot in (0, 90, 180, 270):
            fp.SetOrientationDegrees(rot); fp.SetPosition(pos0)
            res.append((score(b, fp, others), rot))
        fp.SetOrientationDegrees(rot0); fp.SetPosition(pos0)
        best = min(res)
        print(f"{ref:4} now {rot0:5.0f}: " + "  ".join(f"{r:3d}->{s:7.1f}mm" for s, r in res) + f"   best {best[1]} ({'same' if best[1] == rot0 else 'CHANGE'})")

if __name__ == "__main__":
    main(sys.argv[1:] or ["U1", "U2", "U4", "U5", "U6", "U7", "U8", "U9", "U10", "U3", "U14", "U15", "U17", "U18", "U22", "U16", "U31"])
