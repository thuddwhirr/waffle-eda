#!/usr/bin/env python3
"""
waffle-fpga pin-map generator / checker.

Reads   pinmap/assignment.toml            (single source of truth, hand edited)
        pinmap/db/LFE5U-{85,45,25}F.iodb.json  (prjtrellis-db ECP5 I/O database)
Writes  pinmap.csv, board.lpf, bank-summary.md   (repo root)

Every pin attribute used in the outputs (bank, pad pair, DQS group, PCLK /
PLL function, availability on the 45F/25F) is looked up in the database, not
typed by hand.  Run with --check to validate without writing (exit 1 on error).

    python3 pinmap/gen_pinmap.py            # regenerate + validate
    python3 pinmap/gen_pinmap.py --check    # validate only
    python3 pinmap/gen_pinmap.py --refresh-db   # re-download the database
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import tomllib
import urllib.request
from collections import Counter, OrderedDict, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_DIR = os.path.join(HERE, "db")
PARTS = ["LFE5U-85F", "LFE5U-45F", "LFE5U-25F"]
DB_URL = "https://raw.githubusercontent.com/YosysHQ/prjtrellis-db/master/ECP5/{part}/iodb.json"

# IO_TYPE -> required bank VCCIO (volts).  Differential/referenced *inputs*
# are VCCIO-independent on ECP5 but we still require the bank voltage to
# match the output side of the interface, which is the conservative rule.
IOTYPE_VCCIO = {
    "LVCMOS33": 3.3, "LVTTL33": 3.3, "LVCMOS33D": 3.3,
    "LVCMOS25": 2.5, "LVCMOS25D": 2.5, "LVDS": 2.5, "LVDS25E": 2.5,
    "LVCMOS18": 1.8, "LVCMOS18D": 1.8, "SSTL18_I": 1.8, "SSTL18_II": 1.8, "SSTL18D_I": 1.8, "SSTL18D_II": 1.8,
    "LVCMOS15": 1.5, "SSTL15_I": 1.5, "SSTL15_II": 1.5, "SSTL15D_I": 1.5, "SSTL15D_II": 1.5,
    "SSTL135_I": 1.35, "SSTL135_II": 1.35, "SSTL135D_I": 1.35, "SSTL135D_II": 1.35,
    "LVCMOS12": 1.2, "HSUL12": 1.2, "HSUL12D": 1.2,
}
DIFF_TYPES = {t for t in IOTYPE_VCCIO if t.endswith("D") or t.endswith("D_I") or t.endswith("D_II") or t == "LVDS" or t == "LVDS25E"}
PAIR_MATE = {"A": "B", "B": "A", "C": "D", "D": "C"}
SIDE_BANKS = {"L": (6, 7), "R": (2, 3), "T": (0, 1), "B": (8,)}


class Fail(Exception):
    pass


# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------
def refresh_db():
    os.makedirs(DB_DIR, exist_ok=True)
    for part in PARTS:
        url = DB_URL.format(part=part)
        dst = os.path.join(DB_DIR, f"{part}.iodb.json")
        print(f"fetching {url}")
        with urllib.request.urlopen(url) as r, open(dst, "wb") as f:
            f.write(r.read())


def load_db(package):
    """Return (balls, avail) where balls[ball] = attributes on the 85F and
    avail[ball] = set of parts on which the ball is a bonded I/O."""
    per_part = {}
    for part in PARTS:
        with open(os.path.join(DB_DIR, f"{part}.iodb.json")) as f:
            d = json.load(f)
        pk = d["packages"][package]
        meta = {(m["row"], m["col"], m["pio"]): m for m in d["pio_metadata"]}
        tab = {}
        for ball, b in pk.items():
            m = meta[(b["row"], b["col"], b["pio"])]
            tab[ball] = dict(ball=ball, row=b["row"], col=b["col"], pio=b["pio"], bank=m["bank"],
                             func=m.get("function", ""), dqs=m.get("dqs", ""))
        per_part[part] = tab
    balls = per_part["LFE5U-85F"]
    maxcol = max(b["col"] for b in balls.values())
    maxrow = max(b["row"] for b in balls.values())
    for b in balls.values():
        if b["col"] == 0:
            side, pad = "L", f"PL{b['row']}{b['pio']}"
        elif b["col"] == maxcol:
            side, pad = "R", f"PR{b['row']}{b['pio']}"
        elif b["row"] == 0:
            side, pad = "T", f"PT{b['col']}{b['pio']}"
        else:
            side, pad = "B", f"PB{b['col']}{b['pio']}"
        b["side"], b["pad"] = side, pad
    avail = {ball: {p for p in PARTS if ball in per_part[p]} for ball in balls}
    # sanity: bank/function must agree across parts where the ball exists
    for p in PARTS[1:]:
        for ball, m in per_part[p].items():
            if m["bank"] != balls[ball]["bank"] or m["pio"] != balls[ball]["pio"]:
                raise Fail(f"database inconsistency on {ball} between 85F and {p}")
    return balls, avail


def pair_mate(balls, ball):
    b = balls[ball]
    for other, o in balls.items():
        if o["row"] == b["row"] and o["col"] == b["col"] and o["pio"] == PAIR_MATE[b["pio"]]:
            return other
    return None


# ----------------------------------------------------------------------------
# Assignment expansion + validation
# ----------------------------------------------------------------------------
def expand(cfg, balls, avail):
    """Turn the TOML into a list of per-ball rows and a list of problems."""
    errors, warnings = [], []
    rows = OrderedDict()          # ball -> row dict
    bank_v = {int(k): v["vccio"] for k, v in cfg["banks"].items()}
    names = Counter()

    def use(ball, row):
        if ball not in balls:
            errors.append(f"{row['signal']}: ball {ball} is not a user I/O of {cfg['package']['device']} ({cfg['package']['package']})")
            return
        if ball in rows:
            errors.append(f"ball {ball} assigned twice: {rows[ball]['signal']} and {row['signal']}")
            return
        b = balls[ball]
        row.update(ball=ball, bank=b["bank"], vccio=bank_v.get(b["bank"]), pad=b["pad"], func=b["func"],
                   dqs_pad=b["dqs"], side=b["side"], pio=b["pio"], tile=(b["row"], b["col"]))
        missing = [p for p in PARTS if p not in avail[ball]]
        row["avail"] = "all (85F/45F/25F)" if not missing else "NC on " + "/".join(p.replace("LFE5U-", "") for p in missing)
        if missing and row["interface"] not in ("spare",) and not row.get("only85"):
            errors.append(f"{row['signal']}: ball {ball} is not bonded on {missing}; not allowed without only85=true")
        rows[ball] = row

    for iname, iface in cfg["interfaces"].items():
        for s in iface["signals"]:
            name = s["n"]
            names[name] += 1
            io_type = s.get("t", iface.get("io_type", "LVCMOS33"))
            attrs = s.get("a", iface.get("attrs", ""))
            row = dict(signal=name, interface=iname, dir=s["d"], io_type=io_type, attrs=attrs,
                       note=s.get("note", ""), clk=s.get("clk"), ddr_role=s.get("dqs", ""), lane=s.get("lane"),
                       diff_partner=s.get("nb", ""), polarity="+" if s.get("nb") else "", pair_hint=s.get("pair", ""),
                       only85=s.get("only85", False), reserved=s.get("reserved", False))
            use(s["b"], row)
            if s.get("nb"):
                nrow = dict(signal=name.replace("_p", "_n") if "_p" in name else name + "_n",
                            interface=iname, dir=s["d"], io_type=io_type, attrs=attrs,
                            note="complement of " + name + (" (auto-placed by the tools; do not LOCATE)"), clk=None,
                            ddr_role=s.get("dqs", ""), lane=s.get("lane"), diff_partner=s["b"], polarity="-",
                            pair_hint="", only85=s.get("only85", False), complement=True, reserved=s.get("reserved", False))
                use(s["nb"], nrow)
    for name, c in names.items():
        if c > 1:
            errors.append(f"signal name {name} used {c} times")

    # spares
    for ball, note in cfg.get("spares", {}).items():
        row = dict(signal="", interface="spare", dir="", io_type="", attrs="", note=note, clk=None, ddr_role="",
                   lane=None, diff_partner="", polarity="", pair_hint="", only85=True)
        use(ball, row)

    # ---- per-signal checks --------------------------------------------------
    for ball, r in rows.items():
        if r["interface"] == "spare":
            continue
        req = IOTYPE_VCCIO.get(r["io_type"])
        if req is None:
            errors.append(f"{r['signal']}: unknown IO_TYPE {r['io_type']}")
        elif abs(req - r["vccio"]) > 0.01:
            errors.append(f"{r['signal']} on {ball}: IO_TYPE {r['io_type']} needs VCCIO {req} V but bank {r['bank']} is {r['vccio']} V")
        # differential pairs
        if r["diff_partner"] and r["polarity"] == "+":
            mate = pair_mate(balls, ball)
            if mate != r["diff_partner"]:
                errors.append(f"{r['signal']}: {ball}/{r['diff_partner']} is not a pad pair (mate of {ball} is {mate})")
            if r["pio"] not in ("A", "C"):
                errors.append(f"{r['signal']}: positive side must be on pad A or C, {ball} is {r['pad']}")
            if r["side"] in ("T", "B"):
                if r["pio"] != "A":
                    errors.append(f"{r['signal']}: top/bottom banks only pair A/B, {ball} is {r['pad']}")
                if r["dir"] != "out":
                    errors.append(f"{r['signal']}: top/bottom banks support pseudo-differential OUTPUT only")
                warnings.append(f"{r['signal']}: differential on top-side bank {r['bank']} = emulated output, 1x gearing only (no ECLK)")
            if r["io_type"] not in DIFF_TYPES:
                errors.append(f"{r['signal']}: has a complement ball but IO_TYPE {r['io_type']} is single ended")
        elif r["io_type"] in DIFF_TYPES and not r.get("complement"):
            errors.append(f"{r['signal']}: differential IO_TYPE without nb= complement ball")
        # pad-pair hints for single-ended pairs (PMOD / header)
        if r["pair_hint"]:
            mate = pair_mate(balls, ball)
            if mate != r["pair_hint"]:
                errors.append(f"{r['signal']}: pair={r['pair_hint']} but the pad mate of {ball} is {mate}")
            if r["side"] in ("T", "B"):
                warnings.append(f"{r['signal']}: pair on top-side bank: differential input NOT supported there")
        # clocks
        if r["clk"]:
            if not re.search(r"PCLK|GPLL", r["func"]):
                errors.append(f"{r['signal']}: clock input on {ball} ({r['pad']}) is not a PCLK/GR_PCLK/GPLL pad (function='{r['func']}')")
        # directions
        if r["dir"] not in ("in", "out", "bidir"):
            errors.append(f"{r['signal']}: bad direction {r['dir']}")

    # ---- DDR3 checks -----------------------------------------------------------
    ddr = [r for r in rows.values() if r["ddr_role"]]
    if ddr:
        dqs_group = {}      # lane -> group number string
        for r in ddr:
            if r["ddr_role"] == "dqs" and r["polarity"] == "+":
                m = re.fullmatch(r"([LR])DQS(\d+)", r["dqs_pad"])
                if not m:
                    errors.append(f"{r['signal']}: {r['ball']} is not a DQS (true) pad (db says '{r['dqs_pad']}')")
                    continue
                dqs_group[r["lane"]] = (m.group(1), m.group(2), r["bank"])
                mate = rows.get(r["diff_partner"])
                if not mate or mate["dqs_pad"] != f"{m.group(1)}DQSN{m.group(2)}":
                    errors.append(f"{r['signal']}: complement {r['diff_partner']} is not the DQSN pad of group {r['dqs_pad']}")
        data_banks = set()
        for r in ddr:
            if r["ddr_role"] in ("dq", "dm"):
                g = dqs_group.get(r["lane"])
                if g is None:
                    errors.append(f"{r['signal']}: lane {r['lane']} has no DQS pair")
                    continue
                want = f"{g[0]}DQ{g[1]}"
                if r["dqs_pad"] != want:
                    errors.append(f"{r['signal']}: {r['ball']} belongs to DQS group '{r['dqs_pad']}', lane {r['lane']} uses {want}")
                if r["bank"] != g[2]:
                    errors.append(f"{r['signal']}: not in the bank of its DQS pair")
                data_banks.add(r["bank"])
        for lane, g in dqs_group.items():
            data_banks.add(g[2])
            rows[[k for k, v in rows.items() if v["ddr_role"] == "dqs" and v["lane"] == lane and v["polarity"] == "+"][0]]["dqs_group"] = f"{g[0]}DQS{g[1]}"
        for r in ddr:
            if r["ddr_role"] in ("dq", "dm", "dqs"):
                g = dqs_group.get(r["lane"])
                if g:
                    r["dqs_group"] = f"{g[0]}DQS{g[1]}"
        # VREF1 of every data bank must be free
        for bank in data_banks:
            vref = [b for b, v in balls.items() if v["func"] == f"VREF1_{bank}"]
            for vb in vref:
                if vb in rows and rows[vb]["interface"] != "spare":
                    errors.append(f"VREF1_{bank} ball {vb} is used by {rows[vb]['signal']} but bank {bank} carries DDR3 DQ/DQS inputs")
                elif vb in rows:
                    rows[vb]["note"] = "RESERVED as VREF1_%d for SSTL135 inputs in this bank. " % bank + rows[vb]["note"]
                    rows[vb]["signal"] = f"VREF1_{bank}"
                    rows[vb]["interface"] = "ddr3"
                    rows[vb]["dir"] = "in"
                    rows[vb]["io_type"] = "VREF1_DRIVER"
                else:
                    rows[vb] = dict(signal=f"VREF1_{bank}", interface="ddr3", dir="in", io_type="VREF1_DRIVER", attrs="",
                                    note=f"RESERVED: VREF1 input (0.675 V) for the SSTL135 inputs of bank {bank}; do not use as I/O",
                                    clk=None, ddr_role="vref", lane=None, diff_partner="", polarity="", pair_hint="", only85=False,
                                    ball=vb, bank=bank, vccio=bank_v[bank], pad=balls[vb]["pad"], func=balls[vb]["func"],
                                    dqs_pad=balls[vb]["dqs"], side=balls[vb]["side"], pio=balls[vb]["pio"], tile=None, avail="all (85F/45F/25F)")
        sides = {r["side"] for r in ddr if r["ddr_role"] in ("dq", "dm", "dqs")}
        for r in ddr:
            if r["ddr_role"] in ("addr", "cmd", "ctrl", "ck", "reset") and r["side"] not in sides:
                warnings.append(f"{r['signal']}: DDR3 addr/cmd on side {r['side']} while data is on {sides} (allowed on top, but same side recommended)")
            if r["ddr_role"] == "ck" and not r["diff_partner"]:
                errors.append(f"{r['signal']}: DDR3 CK must be a differential pair")
        for bank in {r["bank"] for r in ddr}:
            others = [v["signal"] for v in rows.values() if v["bank"] == bank and v["interface"] not in ("ddr3", "spare")]
            if others:
                errors.append(f"bank {bank} mixes DDR3 with non-DDR3 signals: {others}")

    # ---- every ball accounted for --------------------------------------------
    unassigned = [b for b in balls if b not in rows]
    if unassigned:
        errors.append("balls neither assigned nor listed under [spares]: " + " ".join(sorted(unassigned)))
    for ball, r in rows.items():
        if r["interface"] == "spare":
            r["signal"] = r["signal"] or ""

    # ---- interface expectations (from the fixed specification) ---------------
    cnt = Counter(r["interface"] for r in rows.values() if not r.get("complement"))
    pm = sum(cnt[k] for k in ("pmod_a", "pmod_b", "pmod_c", "pmod_d"))
    pm_pairs = sum(1 for r in rows.values() if r["interface"].startswith("pmod") and r["pair_hint"] and r["side"] in ("L", "R"))
    expect = [
        (pm == 32, f"PMOD GPIO count {pm} != 32"),
        (pm_pairs >= 8, f"only {pm_pairs} PMOD pins on true pad pairs (need >= 8)"),
        (sum(1 for r in rows.values() if r["interface"] == "hdmi" and r["polarity"] == "+") == 4, "HDMI needs 4 pairs"),
        (sum(1 for r in rows.values() if r["interface"] == "ddr3" and r["ddr_role"] in ("dq", "dm", "dqs", "addr", "cmd", "ctrl", "ck", "reset") and not r.get("reserved")) == 50,
         "DDR3 x16 needs exactly 50 signal balls + VREF"),
        (cnt["fmc"] >= 29, f"FMC has {cnt['fmc']} < 29"),
        (cnt["sd1"] == 6 and cnt["sd2"] == 6, "each microSD needs 6 pins (no card-detect)"),
        (cnt["esp32"] >= 8, "ESP32 link needs 8 pins"),
        (cnt["i2c"] == 2 and cnt["i2s"] == 5, "I2C=2 / I2S=5 pins"),
        (cnt["leds"] == 3, "LED shift register needs 3 pins (SCLK, MOSI, LATCH)"),
        (cnt["ext"] == 27, f"expansion header expected 27 pins, have {cnt['ext']}"),
        (cnt["clocks"] == 2, "two primary clock inputs"),
        (cnt["flash"] == 5, "QSPI flash uses 5 PIO balls (+ dedicated CCLK)"),
    ]
    for ok, msg in expect:
        if not ok:
            errors.append("spec: " + msg)
    return rows, errors, warnings


# ----------------------------------------------------------------------------
# Outputs
# ----------------------------------------------------------------------------
def is_used(r):
    return r["interface"] != "spare" and r["io_type"] != "VREF1_DRIVER" and not r.get("reserved")


def ball_sort_key(ball):
    m = re.fullmatch(r"([A-Z]+)(\d+)", ball)
    return (m.group(1), int(m.group(2)))


def write_csv(path, cfg, rows, balls):
    cols = ["ball", "bank", "vccio", "signal", "interface", "direction", "io_type", "lpf_attrs",
            "diff_partner", "diff_polarity", "dqs_group", "ddr3_role", "pad", "dual_function", "availability", "notes"]
    order = list(cfg["interfaces"].keys()) + ["spare"]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(cols)
    def natural(sig):
        return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", sig)]
    items = sorted(rows.values(), key=lambda r: (order.index(r["interface"]) if r["interface"] in order else 99,
                                                 natural(r["diff_partner"] and rows[r["diff_partner"]]["signal"] if r.get("complement") else r["signal"]) if r["interface"] != "spare" else [],
                                                 1 if r.get("complement") else 0,
                                                 r["bank"], ball_sort_key(r["ball"])))
    for r in items:
        w.writerow([r["ball"], r["bank"], f"{r['vccio']:.2f}", ("(reserved) " if r.get("reserved") else "") + r["signal"], r["interface"],
                    "reserved" if r.get("reserved") else r["dir"], r["io_type"], r["attrs"],
                    r["diff_partner"], r["polarity"], r.get("dqs_group", ""), r["ddr_role"], r["pad"], r["func"], r["avail"], r["note"]])
    # dedicated pins at the end
    for d in cfg["dedicated_pins"]["pins"]:
        w.writerow([d["ball"], 8, "3.30", d["name"], d["iface"], d["d"], "dedicated", "", "", "", "", "", "", d["name"],
                    "all (85F/45F/25F)", d["note"]])
    with open(path, "w") as f:
        f.write(out.getvalue())


def write_lpf(path, cfg, rows):
    L = []
    L.append("# board.lpf — waffle-fpga FPGA constraints for %s (%s, speed grade %s)" % (cfg["package"]["device"], cfg["package"]["package"], cfg["package"]["speed_grade"]))
    L.append("# Drop-in alternates: %s" % ", ".join(cfg["package"]["alternates"]))
    L.append("# GENERATED by pinmap/gen_pinmap.py from pinmap/assignment.toml — do not edit by hand.")
    L.append("# Compatible with nextpnr-ecp5 (--lpf) and Lattice Diamond.")
    L.append("# Differential signals: only the positive (A/C) pad is LOCATEd; the complement pad is")
    L.append("# implied by the differential IO_TYPE (nextpnr/Diamond place it automatically).")
    L.append("BLOCK RESETPATHS;")
    L.append("BLOCK ASYNCPATHS;")
    L.append("SYSCONFIG MASTER_SPI_PORT=ENABLE SLAVE_SPI_PORT=DISABLE SLAVE_PARALLEL_PORT=DISABLE CONFIG_IOVOLTAGE=3.3 COMPRESS_CONFIG=ON MCCLK_FREQ=38.8;")
    L.append("")
    L.append("# Bank supply voltages (informational; Diamond syntax, uncomment for Diamond):")
    for b, v in cfg["banks"].items():
        L.append(f"#BANK {b} VCCIO {v['vccio']}V;   # {v['role']}")
    L.append("")
    for iname, iface in cfg["interfaces"].items():
        L.append("#" + "-" * 78)
        L.append(f"# {iname}: {iface['title']}")
        if iface.get("note"):
            L.append(f"#   {iface['note']}")
        L.append("#" + "-" * 78)
        for r in sorted([r for r in rows.values() if r["interface"] == iname and not r.get("complement")],
                        key=lambda r: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", r["signal"])]):
            if r["io_type"] == "VREF1_DRIVER":
                L.append(f"# {r['ball']} = VREF1_{r['bank']} reserved for bank {r['bank']} (SSTL135 reference) — not a user I/O")
                continue
            if r.get("reserved"):
                comp = f" (complement {r['diff_partner']})" if r["diff_partner"] else ""
                L.append(f"# RESERVED, not connected on this revision: {r['signal']} would be SITE {r['ball']}{comp} IO_TYPE={r['io_type']} — {r['note']}")
                continue
            extra = f"   # complement on {r['diff_partner']}" if r["diff_partner"] else ""
            L.append(f'LOCATE COMP "{r["signal"]}" SITE "{r["ball"]}";{extra}')
            attrs = (" " + r["attrs"]) if r["attrs"] else ""
            L.append(f'IOBUF  PORT "{r["signal"]}" IO_TYPE={r["io_type"]}{attrs};')
            if r["clk"]:
                L.append(f'FREQUENCY PORT "{r["signal"]}" {r["clk"]/1e6:g} MHZ;')
        L.append("")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


def write_bank_summary(path, cfg, rows, balls, avail, warnings):
    L = []
    L.append("# Bank summary — %s (%s), alternates %s" % (cfg["package"]["device"], cfg["package"]["package"], ", ".join(cfg["package"]["alternates"])))
    L.append("")
    L.append("GENERATED by `pinmap/gen_pinmap.py` from `pinmap/assignment.toml` and the prjtrellis ECP5 I/O database. Do not edit by hand.")
    L.append("")
    L.append("Package orientation assumed: " + cfg["package"]["orientation"] + ".")
    L.append("")
    L.append("Ball counts are for the 85F. \"Common\" = balls bonded on all three parts (85F/45F/25F); only those carry signals. \"NC on smaller\" balls are left unconnected.")
    L.append("")
    banks = sorted(int(b) for b in cfg["banks"])
    L.append("| Bank | VCCIO | Board side | Balls | Common | Used | VREF reserved | Reserved (2nd rank) | Spare (common) | NC on smaller parts | Role |")
    L.append("|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|")
    tot = Counter()
    per_bank_iface = {}
    for bank in banks:
        bb = [b for b, v in balls.items() if v["bank"] == bank]
        common = [b for b in bb if len(avail[b]) == 3]
        rs = [rows[b] for b in bb]
        used = [r for r in rs if is_used(r)]
        vref = [r for r in rs if r["io_type"] == "VREF1_DRIVER"]
        resv = [r for r in rs if r.get("reserved")]
        spare_common = [r for r in rs if r["interface"] == "spare" and len(avail[r["ball"]]) == 3]
        nc = [b for b in bb if len(avail[b]) < 3]
        cfgb = cfg["banks"][str(bank)]
        L.append(f"| {bank} | {cfgb['vccio']} V | {cfgb['board_side']} | {len(bb)} | {len(common)} | {len(used)} | {len(vref)} | {len(resv)} | {len(spare_common)} | {len(nc)} | {cfgb['role']} |")
        tot.update(balls=len(bb), common=len(common), used=len(used), vref=len(vref), resv=len(resv), spare=len(spare_common), nc=len(nc))
        c = Counter(r["interface"] for r in used)
        per_bank_iface[bank] = (c, spare_common, nc, vref, resv)
    L.append(f"| **all** | | | **{tot['balls']}** | **{tot['common']}** | **{tot['used']}** | **{tot['vref']}** | **{tot['resv']}** | **{tot['spare']}** | **{tot['nc']}** | |")
    L.append("")
    L.append("## Per-bank usage by interface")
    L.append("")
    for bank in banks:
        c, spare_common, nc, vref, resv = per_bank_iface[bank]
        cfgb = cfg["banks"][str(bank)]
        L.append(f"### Bank {bank} — {cfgb['vccio']} V — {cfgb['board_side']}")
        L.append("")
        L.append("| Interface | Balls |")
        L.append("|---|---:|")
        for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
            L.append(f"| {k} | {v} |")
        if vref:
            L.append(f"| VREF1_{bank} reserved | {len(vref)} |")
        if resv:
            L.append(f"| reserved for 2nd DDR3 rank (not connected) | {len(resv)} |")
        L.append(f"| spare (common to all parts) | {len(spare_common)} |")
        L.append(f"| NC on smaller parts | {len(nc)} |")
        L.append("")
        if resv:
            L.append("Reserved balls: " + ", ".join(f"{r['ball']} = {r['signal']}" for r in sorted(resv, key=lambda r: ball_sort_key(r["ball"]))))
            L.append("")
        if spare_common:
            L.append("Spare balls: " + ", ".join(f"{r['ball']} ({r['pad']}{', ' + r['func'] if r['func'] else ''})" for r in sorted(spare_common, key=lambda r: ball_sort_key(r["ball"]))))
            L.append("")
        if nc:
            L.append("Not bonded on smaller parts (leave unconnected): " + ", ".join(f"{b} ({balls[b]['pad']}; NC on {'/'.join(p.replace('LFE5U-','') for p in PARTS if p not in avail[b])})" for b in sorted(nc, key=ball_sort_key)))
            L.append("")
    # interface totals
    L.append("## Totals by interface")
    L.append("")
    L.append("| Interface | Balls used | Banks |")
    L.append("|---|---:|---|")
    c = Counter(); bk = defaultdict(set)
    for r in rows.values():
        if is_used(r):
            c[r["interface"]] += 1
            bk[r["interface"]].add(r["bank"])
    for k in cfg["interfaces"]:
        L.append(f"| {k} | {c[k]} | {', '.join(str(b) for b in sorted(bk[k]))} |")
    L.append(f"| **total user I/O used** | **{sum(c.values())}** | |")
    L.append(f"| dedicated config/JTAG pins (not PIO) | {len(cfg['dedicated_pins']['pins'])} | 8 |")
    L.append("")
    ext = c["ext"]
    ext_rows = sorted([r for r in rows.values() if r["interface"] == "ext"], key=lambda r: int(re.search(r"\[(\d+)\]", r["signal"]).group(1)))
    L.append(f"**Pins on the 2x20 expansion header: {ext}** ({sum(1 for r in ext_rows if r['pair_hint'])//2} pad pairs + {sum(1 for r in ext_rows if not r['pair_hint'])} singles; banks {', '.join(str(b) for b in sorted(bk['ext']))}).")
    L.append("")
    L.append("| Header signal | Ball | Bank | Pad | Pad-pair partner | Dual function | Note |")
    L.append("|---|---|---:|---|---|---|---|")
    for r in ext_rows:
        partner = f"{r['pair_hint']} ({rows[r['pair_hint']]['signal'] or 'spare'})" if r["pair_hint"] else "—"
        L.append(f"| {r['signal']} | {r['ball']} | {r['bank']} | {r['pad']} | {partner} | {r['func']} | {r['note']} |")
    L.append("")
    # clocks
    L.append("## Primary clock inputs")
    L.append("")
    L.append("| Signal | Ball | Pad function | Bank | PLL reach |")
    L.append("|---|---|---|---:|---|")
    for r in rows.values():
        if r["clk"]:
            L.append(f"| {r['signal']} | {r['ball']} | {r['func']} | {r['bank']} | primary clock network -> any PLL (UL, UR, LL, LR on 85F/45F; LL, LR on 25F); ECLK of the right side (banks 6/7) directly |")
    L.append("")
    # DDR3 lanes
    L.append("## DDR3L DQS lanes")
    L.append("")
    L.append("| Lane | DQS+ / DQS- | Group | DQ balls | DM |")
    L.append("|---:|---|---|---|---|")
    lanes = sorted({r["lane"] for r in rows.values() if r["ddr_role"] in ("dq", "dm", "dqs")})
    for ln in lanes:
        dqs = [r for r in rows.values() if r["ddr_role"] == "dqs" and r["lane"] == ln and r["polarity"] == "+"][0]
        dq = [r for r in rows.values() if r["ddr_role"] == "dq" and r["lane"] == ln]
        dq.sort(key=lambda r: int(re.search(r"\[(\d+)\]", r["signal"]).group(1)))
        dm = [r for r in rows.values() if r["ddr_role"] == "dm" and r["lane"] == ln]
        L.append(f"| {ln} | {dqs['ball']} / {dqs['diff_partner']} | {dqs['dqs_group']} | {' '.join(r['ball'] for r in dq)} | {' '.join(r['ball'] for r in dm)} |")
    L.append("")
    if warnings:
        L.append("## Generator warnings")
        L.append("")
        for w_ in warnings:
            L.append(f"- {w_}")
        L.append("")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    ap.add_argument("--refresh-db", action="store_true", help="re-download prjtrellis-db iodb.json files")
    ap.add_argument("--toml", default=os.path.join(HERE, "assignment.toml"))
    args = ap.parse_args()
    if args.refresh_db:
        refresh_db()
    with open(args.toml, "rb") as f:
        cfg = tomllib.load(f)
    balls, avail = load_db(cfg["package"]["package"])
    rows, errors, warnings = expand(cfg, balls, avail)
    for w_ in warnings:
        print("WARNING:", w_)
    for e in errors:
        print("ERROR:", e)
    if errors:
        print(f"{len(errors)} error(s)")
        sys.exit(1)
    used = sum(1 for r in rows.values() if is_used(r))
    print(f"OK: {len(balls)} balls in DB, {used} used, {sum(1 for r in rows.values() if r.get('reserved'))} reserved (2nd rank), "
          f"{sum(1 for r in rows.values() if r['interface']=='spare')} spare/NC, "
          f"{sum(1 for r in rows.values() if r['io_type']=='VREF1_DRIVER')} VREF reserved; {len(warnings)} warning(s)")
    if not args.check:
        write_csv(os.path.join(ROOT, "pinmap.csv"), cfg, rows, balls)
        write_lpf(os.path.join(ROOT, "board.lpf"), cfg, rows)
        write_bank_summary(os.path.join(ROOT, "bank-summary.md"), cfg, rows, balls, avail, warnings)
        print("wrote pinmap.csv, board.lpf, bank-summary.md")


if __name__ == "__main__":
    main()
