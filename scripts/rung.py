#!/usr/bin/env python3
"""One class B gate row on one reference, with the plane handling and the escape stubs selectable: the tool
for iterating on a rung under a short budget (D77), where `gate.py b <key>` is the verdict.

    python3 scripts/rung.py <key> <mode> <passes> <timeout_s> [stubs]

    mode: none    no planes in the DSN, every recorded pour laid after the import (class A's way; the gate's default)
          signal  the inner-layer pours before the export on signal layers (broken: the router calls the layer a
                  dedicated power plane and writes an empty session, D81; kept for the record)
          power   the inner pours before the export, their layers typed power (D81: costs the routing layers)
          gnd     only the ground plane before the export, typed power (D81: worse still)
    stubs: the fine-pitch exits laid as fixed wires (D51/D52; D83: worse on pico-ice)

Writes build/fr/<key>-<mode>[-stubs]/ with the DSN, the session, the router's log, the imported and the routed
board; prints the router's summary, the score and the nets left open with their pieces.
"""
import re, sys, time
from pathlib import Path
import _path  # noqa
from waffle_eda.bench import rebuild, references as refs
from waffle_eda.kicad import board as kb, refill
from waffle_eda.route import freerouting as fr

key, mode, passes, timeout_s = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
stubs = len(sys.argv) > 5 and sys.argv[5] == "stubs"  # the fine-pitch exits laid as fixed wires (D51/D52)
ref = refs.REFERENCES[key]
bare, info = rebuild.strip_all(ref)
rules = rebuild.measure_rules(ref)
board = kb.load_board(bare)
outer = {kb.copper_layers(board)[0][1], kb.copper_layers(board)[-1][1]}
inner = [p for p in info["pours"] if p["layer"] not in outer]
if mode == "none":
    planes, after = [], info["pours"]
elif mode in ("signal", "power"):
    planes, after = inner, [p for p in info["pours"] if p["layer"] in outer]
elif mode == "gnd":
    planes = [p for p in inner if p["net"] == "GND"]
    after = [p for p in info["pours"] if p not in planes]
else:
    raise SystemExit(mode)
work = refs.repo_root() / "build" / "fr" / f"{key}-{mode}{'-stubs' if stubs else ''}"
if mode == "signal":  # the broken mode, kept for the record: undo the wrapper's typing
    fr.type_layers_power = lambda text, layers: text
t0 = time.time()
result = fr.route_board(board, rules, work, passes=passes, timeout_s=timeout_s, pours=after, planes=planes, say=print, stubs=stubs)
print("ROUTER:", result.summary())
out = work / f"{key}-routed.kicad_pcb"
kb.save_board(board, out)
print("fill:", refill.refill_file(out))
s = rebuild.score(ref, out, work_dir=work / "score")
print("SCORE:", s.summary())
open_pieces = kb.open_nets(kb.load_board(out))
print("OPEN:", sorted(open_pieces.items(), key=lambda kv: -kv[1])[:25])
print(f"total {time.time() - t0:.0f} s")
