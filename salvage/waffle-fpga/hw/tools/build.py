#!/usr/bin/env python3
"""Regenerate the library and schematic, run ERC and verify the exported netlist
against hw/design.py.  Usage: python3 hw/tools/build.py"""
import os, subprocess, sys, re, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); HW = os.path.dirname(HERE); ROOT = os.path.dirname(HW)
sys.path.insert(0, HERE)
from sexp import loads, findall, find

def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return r

print("== library"); print(run([sys.executable, os.path.join(HERE, "gen_lib.py")]).stdout.strip())
print("== schematic"); r = run([sys.executable, os.path.join(HW, "design.py")])
print(run([sys.executable, os.path.join(HERE, "gen_report.py")]).stdout.strip())
print(r.stdout.strip()); 
if r.returncode: print(r.stderr); sys.exit(1)
kicad = shutil.which("kicad-cli")
if not kicad:
    print("kicad-cli not found; skipping ERC/netlist"); sys.exit(0)
build = os.path.join(ROOT, "build", "sch"); os.makedirs(build, exist_ok=True)
print("== ERC")
r = run([kicad, "sch", "erc", "--severity-all", "--format", "report", "--output", os.path.join(build, "erc.rpt"), os.path.join(HW, "waffle.kicad_sch")])
rpt = open(os.path.join(build, "erc.rpt")).read()
m = re.search(r"Found (\d+) violations", rpt) or re.search(r"\*\* ERC messages: (\d+)", rpt)
errs = re.findall(r"\[(\w+)\]: (.*)", rpt)
from collections import Counter
print("ERC violations by type:", dict(Counter(k for k, _ in errs)))
print(rpt[-1200:] if "violations" in rpt[-400:] else "\n".join(rpt.splitlines()[-8:]))
print("== netlist")
nl = os.path.join(build, "waffle.net")
r = run([kicad, "sch", "export", "netlist", "--format", "kicadsexpr", "--output", nl, os.path.join(HW, "waffle.kicad_sch")])
if r.returncode: print(r.stdout, r.stderr); sys.exit(1)
doc = loads(open(nl).read())
nets = {}
for n in findall(find(doc, "nets"), "net"):
    name = find(n, "name")[1]
    pins = {(find(x, "ref")[1], find(x, "pin")[1]) for x in findall(n, "node")}
    nets[name] = pins
# compare with design
sys.path.insert(0, HW)
import importlib.util
spec = importlib.util.spec_from_file_location("design", os.path.join(HW, "design.py")); design = importlib.util.module_from_spec(spec)
spec.loader.exec_module(design)
D = design.D
bad = 0
for net, pins in D.nets.items():
    want = set(pins)
    got = nets.get(net)
    if got is None:
        # KiCad may prefix nets; search by pins
        cand = [k for k, v in nets.items() if want <= v]
        if len(cand) == 1: got = nets[cand[0]]; 
    if got is None:
        print(f"MISSING net {net}: {sorted(want)[:6]}"); bad += 1; continue
    extra = {p for p in got - want if not p[0].startswith("#")}
    missing = want - got
    if extra or missing:
        bad += 1
        print(f"NET {net}: missing {sorted(missing)[:8]} extra {sorted(extra)[:8]}")
print(f"netlist check: {len(D.nets)} design nets, {len(nets)} exported nets, {bad} mismatches")
sys.exit(1 if bad else 0)
