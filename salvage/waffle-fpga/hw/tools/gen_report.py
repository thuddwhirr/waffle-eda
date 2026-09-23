#!/usr/bin/env python3
"""Human-readable connection report (hw/connection-report.md) from hw/design.py:
one table per IC/connector (pin, name, type, net), passives summarised per net."""
import os, sys, importlib.util, re
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); HW = os.path.dirname(HERE)
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("design", os.path.join(HW, "design.py")); design = importlib.util.module_from_spec(spec); spec.loader.exec_module(design)
D = design.D
pin_net = {}
for net, pins in D.nets.items():
    for rp in pins: pin_net[rp] = net
def natural(s): return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)]
L = ["# Connection report — generated from hw/design.py", "",
     "One table per IC / connector: pin number, symbol pin name, electrical type, net. Passives (R, C, L, LED, FB) are summarised by net at the end of each sheet. Regenerate with `python3 hw/tools/build.py`.", ""]
for sheet, title in D.sheets.items():
    L += [f"## Sheet `{sheet}` — {title}", ""]
    parts = [p for p in D.parts.values() if not p.is_power and (sheet in p.unit_sheets.values())]
    ics = [p for p in parts if not re.match(r"^(R|C|L|LED|FB)\d+$", p.ref)]
    passives = [p for p in parts if re.match(r"^(R|C|L|LED|FB)\d+$", p.ref)]
    for p in sorted(ics, key=lambda p: natural(p.ref)):
        L += [f"### {p.ref} — {p.value} (`{p.lib_id}`)", "", "| Pin | Name | Type | Net |", "|---|---|---|---|"]
        for q in sorted(p.pins, key=lambda q: natural(q["number"])):
            if p.ref == "U1" and p.unit_sheets.get(q["unit"] if q["unit"] else 1, sheet) != sheet and q["unit"] != 0:
                continue
            net = pin_net.get((p.ref, q["number"]))
            L.append(f"| {q['number']} | {q['name']} | {q['type']} | {net if net else '*NC*'} |")
        L.append("")
    if passives:
        by_net = defaultdict(list)
        for p in passives:
            nets = [pin_net.get((p.ref, q["number"]), "NC") for q in p.pins]
            by_net[" — ".join(nets)].append(f"{p.ref} {p.value}")
        L += ["### Passives", "", "| Nets | Parts |", "|---|---|"]
        for k in sorted(by_net):
            L.append(f"| {k} | {', '.join(by_net[k])} |")
        L.append("")
    if D.sheet_notes.get(sheet):
        L += ["Notes: " + " ".join(D.sheet_notes[sheet]), ""]
with open(os.path.join(HW, "connection-report.md"), "w") as f:
    f.write("\n".join(L))
print("wrote hw/connection-report.md", len(L), "lines")
