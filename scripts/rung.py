#!/usr/bin/env python3
"""One class B gate row on one reference, with the plane handling and the escape stubs selectable: the tool
for iterating on a rung under a short budget (D77), where `gate.py b <key>` is the verdict.

    python3 scripts/rung.py <key> <mode> <passes> <timeout_s> [stubs] [fanout] [feeds] [loose|after|reserved|vias|stitch] [inpad] [pourpins] [costs=L:C,...] [band=REF:IN:OUT,...] [first=NET,...] [answer=NET,...] [rounds=N] [open=<board>]

    mode: none    no planes in the DSN, every recorded pour laid after the import (class A's way; the gate's default)
          signal  the inner-layer pours before the export on signal layers (broken: the router calls the layer a
                  dedicated power plane and writes an empty session, D81; kept for the record)
          power   the inner pours before the export, their layers typed power (D81: costs the routing layers)
          gnd     only the ground plane before the export, typed power (D81: worse still)
    stubs: the fine-pitch exits laid as fixed wires (D51/D52; D83: worse on pico-ice)
    fanout: the router's own fanout stage first, a via beside every SMD pad (off since D57)
    feeds: the inner pours' nets leave the router: a fixed via and stub beside every SMD pad of theirs before
           the export, their pins out of the DSN's network, their pours and feeds connecting them (D85)
    loose: the feeds handed to the router as its own wires, not fixed: it may shove or rip them (D91)
    after: the feeds laid after the import around the router's copper, the plane nets' pins out of the
           router's network altogether (D91)
    reserved: the feed sites as keepouts in the DSN, the pins out of the network, the feeds laid after the
           import where the keepouts held their room (D91)
    vias: the feed vias alone fixed in the DSN, the fed pads out of the network and the pads with no feed
           left in it, the stubs laid after the import (D91)
    stitch: no feed before the router and no pin dropped: the router connects the plane nets itself (mode
           signal, D96), the stitching feeds what it leaves
    costs=In1.Cu:30,...: the router's trace costs on the named layers, both directions, through an
           autoroute_settings block in the DSN (D96: tracks kept off a plane's layer that stays signal)
    band=U3:0:1.0,...: no via of the router's within the strip from IN to OUT mm outside the named footprint's
           pads, on every signal layer (D104: the reference's escape pattern round a QFN, forced)
    first=/FLASH_MISO,...: the named nets routed first, alone on the bare board, and fixed for a second stage
           that routes everything else round them (D106: the hard nets first, the standard practice)
    answer=/FLASH_MISO,...: the reference's own copper for the named nets laid on the bare board and fixed, the
           router routing everything else round it (D106: the answer key as the first stage, an upper bound)
    inpad: a feed's via in any pad it fits (D93: the fab's filled-and-capped option), not only a thermal pad
    pourpins: a fine-pitch pin of a plane net left to the pour of its own layer, no feed, its pin out of the
           router's network (D95: the reference's way at U3's GND pins)
    rounds=N: the closure loop (D86, `route.freerouting.route_rounds`): a round that leaves a fine-pitch pad
           open is followed by one with a fixed exit stub out of that pad, N rounds at most
    open=<routed board>: the first round starts with the exit stubs an earlier run's board asks for (its open
           nets' untouched pads), so a second run is measured without repeating the first
    exits=REF-N,...: pads whose exit stubs the first round starts with as well (an earlier round's, since the
           loop accumulates them)

Writes build/fr/<key>-<mode>[-stubs][-fanout][-feeds]/ with the DSN, the session, the router's log, the imported and the routed
board (an earlier round's under round-<k>/); prints the router's summary, the score and the nets left open with their pieces.
"""
import os, re, sys, time
from pathlib import Path
import _path  # noqa
from waffle_eda.bench import rebuild, references as refs
from waffle_eda.kicad import board as kb
from waffle_eda.route import freerouting as fr

key, mode, passes, timeout_s = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
options = {a.split("=", 1)[0]: (a.split("=", 1)[1] if "=" in a else True) for a in sys.argv[5:]}
unknown = set(options) - {"stubs", "fanout", "feeds", "loose", "after", "reserved", "vias", "stitch", "inpad", "pourpins", "costs", "band", "first", "answer", "rounds", "open", "exits"}
if unknown:
    raise SystemExit(f"unknown option {sorted(unknown)}")
stubs = "stubs" in options  # the fine-pitch exits laid as fixed wires (D51/D52)
fanout = "fanout" in options  # the router's own fanout stage (D57)
feeds = "feeds" in options or "stitch" in options  # plane feeds (D85); `stitch`: the stitching alone (D96)
feeds_mode = ("routable" if "loose" in options else "after" if "after" in options else "reserved" if "reserved" in options
              else "vias" if "vias" in options else "none" if "stitch" in options else "fixed")
layer_costs = {kv.split(":")[0]: float(kv.split(":")[1]) for kv in options["costs"].split(",")} if "costs" in options else None
via_bands = ([(b.split(":")[0], float(b.split(":")[1]), float(b.split(":")[2])) for b in options["band"].split(",")]
             if "band" in options else None)
first_nets = set(options["first"].split(",")) if "first" in options else None
answer_nets = set(options["answer"].split(",")) if "answer" in options else None
via_in_pad = "inpad" in options  # D93
pour_pins_rule = "pourpins" in options  # D95
rounds = int(options.get("rounds", 1))  # the closure loop's rounds (D86)
ref = refs.REFERENCES[key]
bare, info = rebuild.strip_all(ref)
rules = rebuild.measure_rules(ref)
board = kb.load_board(bare)
outer = {kb.copper_layers(board)[0][1], kb.copper_layers(board)[-1][1]}
inner = [p for p in info["pours"] if p["layer"] not in outer]
if mode == "none":
    planes, pours_after = [], info["pours"]
elif mode in ("signal", "power"):
    planes, pours_after = inner, [p for p in info["pours"] if p["layer"] in outer]
elif mode == "gnd":
    planes = [p for p in inner if p["net"] == "GND"]
    pours_after = [p for p in info["pours"] if p not in planes]
else:
    raise SystemExit(mode)
work = refs.repo_root() / "build" / "fr" / (f"{key}-{mode}{'-stubs' if stubs else ''}{'-fanout' if fanout else ''}"
                                             f"{'-feeds' if feeds else ''}{'-' + feeds_mode if feeds_mode != 'fixed' else ''}"
                                             f"{'-inpad' if via_in_pad else ''}{'-pourpins' if pour_pins_rule else ''}"
                                             f"{'-costs' if layer_costs else ''}{'-band' if via_bands else ''}{'-first' if first_nets else ''}{'-answer' if answer_nets else ''}"
                                             f"{'-via' + os.environ['WAFFLE_VIA_COSTS'] if os.environ.get('WAFFLE_VIA_COSTS') else ''}"
                                             f"{'-pv' + os.environ['WAFFLE_PLANE_VIA_COSTS'] if os.environ.get('WAFFLE_PLANE_VIA_COSTS') else ''}"
                                             f"{'-ripup' + os.environ['WAFFLE_RIPUP_COSTS'] if os.environ.get('WAFFLE_RIPUP_COSTS') else ''}"
                                             f"{'-neck' if os.environ.get('WAFFLE_NECKDOWN') == '1' else ''}")
if mode == "signal":  # the broken mode, kept for the record: undo the wrapper's typing
    fr.type_layers_power = lambda text, layers: text
t0 = time.time()
plane_nets = {p["net"] for p in inner} if feeds else set()
stub_pads: set[str] = set()
if "open" in options:  # the exit stubs an earlier run's board asks for (D86)
    earlier = kb.load_board(Path(options["open"]))
    stub_pads = {x.pad for x in fr.exit_stubs(earlier, rules, fr.untouched_pads(earlier, set(kb.open_nets(earlier))))}
    print(f"exit stubs from {options['open']}: {sorted(stub_pads)}")
if "exits" in options:  # an earlier round's stubs, kept: the loop accumulates them
    stub_pads |= set(options["exits"].split(","))
out = work / f"{key}-routed.kicad_pcb"


def finish(routed, _work):  # the gate's finishing: the child-process fill, then the stitching (D85) and a refill
    from waffle_eda.route import planes as feedlib
    done = feedlib.finish(routed, out, rules, plane_nets)
    print("fill:", done["fill"])
    if feeds:
        print(f"stitched: {len(done['stitched'])} feeds at {[x.pad for x in done['stitched']]}")
    return out


common = dict(passes=passes, timeout_s=timeout_s, pours=pours_after, planes=planes, stubs=stubs, fanout=fanout,
              feeds=plane_nets or None, feeds_mode=feeds_mode, via_in_pad=via_in_pad, pour_pins_rule=pour_pins_rule,
              layer_trace_costs=layer_costs, via_bands=via_bands)
problem, staged = bare, {}
if first_nets:  # the hard nets first (D106): stage 1 routes them alone, stage 2 everything else round them
    work1 = work.with_name(work.name + "-stage1")
    out1 = work1 / f"{key}-stage1.kicad_pcb"

    def finish1(routed, _work):
        kb.save_board(routed, out1)
        return out1

    _o1, r1 = fr.route_rounds(bare, rules, work1, finish1, rounds=1, say=print, only_nets=first_nets, **common)
    print(f"STAGE 1 ({len(first_nets)} nets alone): {r1[0].summary()}")
    print("STAGE 1 OPEN:", sorted(kb.open_nets(kb.load_board(out1)).items()))
    staged_board = kb.load_board(bare)
    copied = fr.copy_tracks(kb.load_board(out1), staged_board, first_nets)
    problem = work1 / f"{key}-staged.kicad_pcb"
    kb.save_board(staged_board, problem)
    print(f"stage 2 starts from {copied} tracks and vias of the {len(first_nets)} nets, fixed")
    staged = {"fix_existing": True}
if answer_nets:  # the answer key (D106): the reference's routes of the named nets, fixed, as the first stage
    work1 = work.with_name(work.name + "-answer")
    work1.mkdir(parents=True, exist_ok=True)
    staged_board = kb.load_board(bare)
    copied = fr.copy_tracks(kb.load_board(refs.board_path(ref)), staged_board, answer_nets)
    problem = work1 / f"{key}-answered.kicad_pcb"
    kb.save_board(staged_board, problem)
    print(f"stage 2 starts from the reference's {copied} tracks and vias of the {len(answer_nets)} nets, fixed")
    staged = {"fix_existing": True}
_final, results = fr.route_rounds(problem, rules, work, finish, rounds=rounds, say=print, stub_pads=stub_pads or None,
                                  **common, **staged)
for k, result in enumerate(results, 1):
    print(f"ROUTER round {k}: exits {list(result.exits)}, feeds {result.feeds_mode}{' via-in-pad' if via_in_pad else ''}; {result.summary()}")
s = rebuild.score(ref, out, work_dir=work / "score")
print("SCORE:", s.summary())
open_pieces = kb.open_nets(kb.load_board(out))
print("OPEN:", sorted(open_pieces.items(), key=lambda kv: -kv[1])[:25])
print(f"total {time.time() - t0:.0f} s")
