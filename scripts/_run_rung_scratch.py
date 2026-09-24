"""One class B gate row with the plane handling selectable, for iterating on a rung (D77 budgets).

    python3 run_rung.py <key> <mode> <passes> <timeout_s>
    mode: none    - no planes in the DSN, every recorded pour laid after the import (class A's way)
          signal  - the inner-layer pours laid before the export on signal layers (D80; Freerouting then calls
                    the layer a dedicated power plane and writes an empty session)
          power   - the inner pours before the export and their layers typed power in the DSN
          gnd     - only the ground plane's layer before the export, typed power; the rest after
"""
import re, sys, time
from pathlib import Path
import _path  # noqa
from waffle_eda.bench import rebuild, references as refs
from waffle_eda.kicad import board as kb, refill
from waffle_eda.route import freerouting as fr

key, mode, passes, timeout_s = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
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
work = refs.repo_root() / "build" / "fr" / f"{key}-{mode}"
if mode == "signal":  # the broken mode, kept for the record: undo the wrapper's typing
    fr.type_layers_power = lambda text, layers: text
t0 = time.time()
result = fr.route_board(board, rules, work, passes=passes, timeout_s=timeout_s, pours=after, planes=planes, say=print)
print("ROUTER:", result.summary())
out = work / f"{key}-routed.kicad_pcb"
kb.save_board(board, out)
print("fill:", refill.refill_file(out))
s = rebuild.score(ref, out, work_dir=work / "score")
print("SCORE:", s.summary())
open_pieces = kb.open_nets(kb.load_board(out))
print("OPEN:", sorted(open_pieces.items(), key=lambda kv: -kv[1])[:25])
print(f"total {time.time() - t0:.0f} s")
