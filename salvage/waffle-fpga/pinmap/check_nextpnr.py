#!/usr/bin/env python3
"""
Prove board.lpf against the real toolchain: build a stub top-level that has
every port of pinmap.csv, synthesise it with yosys and place it with
nextpnr-ecp5 for the 85F, 45F and 25F in caBGA381.  nextpnr independently
checks bank-voltage conflicts, differential pad placement, VREF availability
and that every ball exists on the chosen device.

Uses native yosys/nextpnr-ecp5 if on PATH, otherwise the WebAssembly builds
(pip install yowasp-yosys yowasp-nextpnr-ecp5).

    python3 pinmap/check_nextpnr.py            # all three devices
    python3 pinmap/check_nextpnr.py --devices 85k
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tool(name):
    for cand in (name, "yowasp-" + name):
        if shutil.which(cand):
            return cand
    sys.exit(f"neither {name} nor yowasp-{name} found on PATH")


def build_stub(csv_path):
    buses = OrderedDict()   # base -> dict(dir, width)
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            if r["interface"] in ("spare", "config") or r["io_type"] in ("VREF1_DRIVER", "dedicated", "") or r["direction"] == "reserved":
                continue
            if r["diff_polarity"] == "-":
                continue        # complement pad is implied by the differential IO_TYPE
            m = re.fullmatch(r"(.+)\[(\d+)\]", r["signal"])
            base, idx = (m.group(1), int(m.group(2))) if m else (r["signal"], None)
            b = buses.setdefault(base, dict(dir=r["direction"], idx=set(), clk=False))
            assert b["dir"] == r["direction"], f"mixed directions on bus {base}"
            if idx is not None:
                b["idx"].add(idx)
            if base in ("clk27",):
                b["clk"] = True
    ports, ins, outs, ios = [], [], [], []
    for base, b in buses.items():
        if b["idx"]:
            assert b["idx"] == set(range(max(b["idx"]) + 1)), f"bus {base} has holes"
            w = f"[{max(b['idx'])}:0] "
            if max(b["idx"]) == 0:
                # a 1-bit vector loses its [0] in yosys' port name and would no longer
                # match the LPF; use an escaped identifier that keeps the bracket
                w, base = "", f"\\{base}[0] "
        else:
            w = ""
        kind = {"in": "input", "out": "output", "bidir": "inout"}[b["dir"]]
        ports.append(f"    {kind} {w}{base}")
        (ins if b["dir"] == "in" else outs if b["dir"] == "out" else ios).append(base)
    v = ["module top(", ",\n".join(ports), ");"]
    v.append("    wire clk = clk27;")
    v.append("    reg [31:0] cnt = 0; always @(posedge clk) cnt <= cnt + 1;")
    v.append("    wire allin = " + " ^ ".join([f"^{n}" for n in ins if n != "clk27"] + [f"^{n}" for n in ios]) + ";")
    v.append("    reg r = 0; always @(posedge clk) r <= allin;")
    for n in outs:
        v.append(f"    assign {n} = {{$bits({n}){{r ^ cnt[3]}}}};")
    for n in ios:
        v.append(f"    assign {n} = cnt[5] ? {{$bits({n}){{r ^ cnt[4]}}}} : {{$bits({n}){{1'bz}}}};")
    v.append("endmodule")
    return "\n".join(v) + "\n", len(ports)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--devices", default="85k,45k,25k")
    ap.add_argument("--keep", action="store_true", help="keep the temporary build directory")
    ap.add_argument("--speed", default=None, help="speed grade (default: from pinmap/assignment.toml)")
    args = ap.parse_args()
    if args.speed is None:
        with open(os.path.join(ROOT, "pinmap", "assignment.toml"), "rb") as f:
            args.speed = tomllib.load(f)["package"]["speed_grade"].lstrip("-")
    yosys, nextpnr = tool("yosys"), tool("nextpnr-ecp5")
    # The WebAssembly (yowasp) tools can only see the current directory tree,
    # so build inside the repo (build/ is git-ignored) and use relative paths.
    tmp = os.path.join("build", "pnr")
    os.makedirs(os.path.join(ROOT, tmp), exist_ok=True)
    os.chdir(ROOT)
    top = os.path.join(tmp, "top.v")
    stub, nports = build_stub("pinmap.csv")
    with open(top, "w") as f:
        f.write(stub)
    js = os.path.join(tmp, "top.json")
    log = os.path.join(tmp, "yosys.log")
    r = subprocess.run([yosys, "-q", "-l", log, "-p", f"read_verilog {top}; synth_ecp5 -top top -json {js}"], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        sys.exit("yosys failed")
    ok = True
    for dev in args.devices.split(","):
        cmd = [nextpnr, f"--{dev}", "--package", "CABGA381", "--speed", args.speed, "--json", js,
               "--lpf", "board.lpf", "--textcfg", os.path.join(tmp, f"{dev}.config"),
               "--log", os.path.join(tmp, f"{dev}.log"), "--placer", "heap", "--seed", "1"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        warn = [l for l in (r.stdout + r.stderr).splitlines() if "WARNING" in l and "unconstrained" not in l]
        if r.returncode:
            ok = False
            print(f"[FAIL] {dev}:")
            print("\n".join([l for l in (r.stdout + r.stderr).splitlines() if "ERROR" in l or "error" in l][-20:]))
        else:
            with open(os.path.join(tmp, f"{dev}.log")) as f:
                logtxt = f.read()
            ncon = len(re.findall(r"constrained to Bel", logtxt))
            if ncon < nports:
                ok = False
                print(f"[FAIL] {dev}: only {ncon} of {nports} ports were constrained by board.lpf")
                continue
            vref = [l for l in (r.stdout + r.stderr).splitlines() if "VREF" in l]
            print(f"[ OK ] LFE5U-{dev.upper()[:-1]}F-{args.speed} CABGA381: placed + routed with board.lpf; {len(warn)} warning(s)" + ("; " + "; ".join(l.strip() for l in vref) if vref else ""))
            for l in warn:
                print("       ", l.strip())
    if not args.keep:
        shutil.rmtree(tmp)
    else:
        print("build dir:", os.path.join(ROOT, tmp))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
