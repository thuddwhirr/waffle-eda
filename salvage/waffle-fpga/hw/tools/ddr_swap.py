#!/usr/bin/env python3
"""DDR3 bit/line swap at the FPGA (D57). Within a byte lane the DQ bits and DM may sit on any pin of the lane's DQS
group, and the address/command/control lines on any pin of their bank, so the FPGA-side assignment can be permuted
freely. This script reads the pre-route board, orders the DRAM balls and the FPGA balls of each group by board y and
pairs them in order, which makes every group a non-crossing bus across the DRAM-FPGA corridor (140 crossings -> 0 for
the address/command group on the first run). It rewrites the `b="..."` fields in pinmap/assignment.toml; regenerate
pinmap.csv (pinmap/gen_pinmap.py), the schematic (hw/tools/build.py) and the board afterwards.
Usage: python3 hw/tools/ddr_swap.py [--dry-run]"""
import os, re, sys, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); ROOT = os.path.dirname(HW)
BOARD = os.path.join(HW, "waffle.kicad_pcb"); TOML = os.path.join(ROOT, "pinmap", "assignment.toml")
GROUPS = {"lane0": [f"DDR3_DQ{i}" for i in range(8)] + ["DDR3_DM0"],
          "lane1": [f"DDR3_DQ{i}" for i in range(8, 16)] + ["DDR3_DM1"],
          "ac": [f"DDR3_A{i}" for i in range(16)] + ["DDR3_BA0", "DDR3_BA1", "DDR3_BA2", "DDR3_RAS_N", "DDR3_CAS_N",
                 "DDR3_WE_N", "DDR3_CS_N", "DDR3_CKE", "DDR3_ODT", "DDR3_RESET_N"]}

def toml_name(net):
    """DDR3_DQ5 -> ddr3_dq[5], DDR3_RAS_N -> ddr3_ras_n"""
    m = re.match(r"DDR3_([A-Z_]+?)(\d+)$", net)
    return f"ddr3_{m.group(1).lower()}[{int(m.group(2))}]" if m else net.lower()

def crossings(pairs):
    return sum(1 for i in range(len(pairs)) for j in range(i + 1, len(pairs)) if (pairs[i][0] - pairs[j][0]) * (pairs[i][1] - pairs[j][1]) < 0)

def main(dry):
    b = pcbnew.LoadBoard(BOARD); mm = pcbnew.ToMM
    def balls(ref):
        fp = b.FindFootprintByReference(ref)
        return {p.GetNetname(): (p.GetNumber(), mm(p.GetPosition().y)) for p in fp.Pads() if p.GetNetname().startswith("DDR3_")}
    U1, U2 = balls("U1"), balls("U2")
    # order by the escape stub ends rather than the balls where the board has escapes: a ring-2 channel stub or a ring>=3
    # line sits on the row next to its ball, so only the stub order makes the corridor lines strictly non-crossing
    cnt = {}; anch = set()
    for t in b.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T: anch.add((t.GetNetname(), t.GetPosition().x, t.GetPosition().y)); continue
        for q in (t.GetStart(), t.GetEnd()): cnt[(t.GetNetname(), q.x, q.y)] = cnt.get((t.GetNetname(), q.x, q.y), 0) + 1
    for f in b.GetFootprints():
        for p in f.Pads(): anch.add((p.GetNetname(), p.GetPosition().x, p.GetPosition().y))
    n_stub = 0
    if os.environ.get("SWAP_BY_BALLS"): cnt = {}                     # D59: order by ball rows (the plan's straight lines start on them)
    for (n, x, y), k in cnt.items():
        if k != 1 or (n, x, y) in anch or not n.startswith("DDR3_"): continue
        side = U2 if mm(x) < 35 else U1
        if n in side: side[n] = (side[n][0], mm(y)); n_stub += 1
    print(f"{n_stub} stub ends used for ordering")
    new_ball = {}
    # byte lanes are interchangeable as a whole (the soft PHY treats them alike): if lane 0 sits above lane 1 at the DRAM
    # but below it at the FPGA, exchange the two lanes' FPGA pins, DQS pairs included, before ordering inside each lane
    lane_nets = {g: [n for n in GROUPS[g] if n in U1 and n in U2] for g in ("lane0", "lane1")}
    mean = lambda side, ns: sum(side[n][1] for n in ns) / len(ns)
    if (mean(U2, lane_nets["lane0"]) - mean(U2, lane_nets["lane1"])) * (mean(U1, lane_nets["lane0"]) - mean(U1, lane_nets["lane1"])) < 0:
        print("lanes cross as a whole: exchanging the two byte lanes' FPGA pins")
        pairs = [(f"DDR3_DQ{i}", f"DDR3_DQ{i + 8}") for i in range(8)] + [("DDR3_DM0", "DDR3_DM1"), ("DDR3_DQS_P0", "DDR3_DQS_P1"), ("DDR3_DQS_N0", "DDR3_DQS_N1")]
        for a, c in pairs:
            if a in U1 and c in U1:
                new_ball[a], new_ball[c] = U1[c][0], U1[a][0]
                U1[a], U1[c] = (U1[c][0], U1[c][1]), (U1[a][0], U1[a][1])
    for g, names in GROUPS.items():
        ns = [n for n in names if n in U1 and n in U2]
        before = crossings([(U2[n][1], U1[n][1]) for n in ns])
        if before == 0: print(f"{g}: {len(ns)} nets, already crossing-free"); continue
        dram = sorted(ns, key=lambda n: (U2[n][1], U1[n][1]))           # ties: keep the current pairing where possible
        fpga = sorted(ns, key=lambda n: (U1[n][1], U2[n][1]))
        m = {dram[i]: U1[fpga[i]][0] for i in range(len(ns))}
        inv = {v: k for k, v in {n: U1[n][0] for n in ns}.items()}
        after = crossings([(U2[n][1], U1[inv[m[n]]][1]) for n in ns])
        changed = {n: m[n] for n in ns if m[n] != U1[n][0]}
        print(f"{g}: {len(ns)} nets, crossings {before} -> {after}, {len(changed)} balls change")
        new_ball.update(changed)
    if not new_ball: print("nothing to swap"); return
    txt = open(TOML).read(); n_done = 0
    for net, ball in new_ball.items():
        if net.startswith("DDR3_DQS_N"): continue                        # the N ball is the nb= of the P entry
        pat = re.compile(r'(\{ n="' + re.escape(toml_name(net)) + r'",\s*b=")([A-Z]+\d+)(")')
        txt, k = pat.subn(lambda mo: mo.group(1) + ball + mo.group(3), txt)
        if k != 1: print("  !! no unique entry for", net, toml_name(net)); continue
        if net.startswith("DDR3_DQS_P"):
            nb = new_ball[net.replace("_P", "_N")]
            pat = re.compile(r'(\{ n="' + re.escape(toml_name(net)) + r'",\s*b="[A-Z]+\d+",\s*nb=")([A-Z]+\d+)(")')
            txt, k = pat.subn(lambda mo: mo.group(1) + nb + mo.group(3), txt)
            if k != 1: print("  !! no nb entry for", net)
        n_done += 1
    print(f"{n_done} entries rewritten{' (dry run, not saved)' if dry else ''}")
    if not dry: open(TOML, "w").write(txt)

if __name__ == "__main__":
    main("--dry-run" in sys.argv)
