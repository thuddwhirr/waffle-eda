#!/usr/bin/env python3
"""Does the router's version of a reference admit the reference's own routing? The board goes through the gate's
own export (`route_board` under the class's configuration: the planes, the rules and slack, the keepouts, the
DSN blocks), except that the reference's tracks and vias are laid back on the stripped board first and typed
fixed, as D106's `answer=` did for twelve nets; the run stops before the jar starts. `tools/DsnDrc.java` then
loads that DSN into Freerouting and prints its own clearance violations and incomplete connections: every one is
a place where the problem we hand the router is harder than the one the designer solved.

    python3 scripts/translation_check.py <key> [a|b]      # the class whose configuration to export under (b)

Writes build/fr/<key>-translation/board.dsn and prints the checker's report.
"""
import subprocess
import sys
from pathlib import Path

import _path  # noqa: F401
import gate
from waffle_eda.bench import rebuild, references as refs
from waffle_eda.kicad import board as kb
from waffle_eda.route import freerouting as fr


class _Stop(Exception):
    pass


def export(key: str, klass: str) -> Path:
    ref = refs.REFERENCES[key]
    cfg = gate.configuration(gate.CLASS_B if klass == "b" else gate.CLASS_A)
    bare, info = rebuild.strip_all(ref)
    rules = rebuild.measure_rules(ref)
    board = kb.load_board(bare)
    planes, pours = gate.plane_split(board, info["pours"], cfg["planes"])
    outer = {kb.copper_layers(board)[0][1], kb.copper_layers(board)[-1][1]}
    plane_nets = {p["net"] for p in info["pours"] if p["layer"] not in outer} if cfg["feeds"] else None
    answer = kb.load_board(refs.board_path(ref))
    nets = {t.GetNetname() for t in kb.track_segments(answer)} | {v.GetNetname() for v in kb.vias(answer)}
    copied = fr.copy_tracks(answer, board, nets - {""})
    arcs = sum(1 for t in answer.GetTracks() if t.GetClass() == "PCB_ARC")
    print(f"{key}: the reference's copper laid back fixed: {copied} tracks and vias of {len(nets)} nets; "
          f"{arcs} arcs not carried")
    extra = {}
    if "plane_type" in cfg:
        extra = {"plane_type": cfg["plane_type"], "via_costs": cfg["via_costs"],
                 "plane_via_costs": cfg["plane_via_costs"], "ripup_costs": cfg["ripup_costs"],
                 "via_bands": cfg["via_bands"], "slack_mm": cfg["slack_mm"], "ring_per_axis": cfg["ring_per_axis"],
                 "layer_trace_costs": {p["layer"]: cfg["layer_costs"] for p in planes} if planes else None}
    work = refs.repo_root() / "build" / "fr" / f"{key}-translation"

    def stop(dsn, *_a, **_k):
        raise _Stop()

    fr.run_jar = stop  # everything up to the jar, nothing after it
    try:
        fr.route_board(board, rules, work, pours=pours, planes=planes, feeds=plane_nets, stubs=cfg["stubs"],
                       gui=False, feeds_mode=cfg["feeds_mode"], via_in_pad=cfg["via_in_pad"],
                       pour_pins_rule=cfg["pour_pins"], fix_existing=True, say=print, **extra)
    except _Stop:
        pass
    return work / "board.dsn"


def main() -> int:
    key = sys.argv[1]
    klass = sys.argv[2] if len(sys.argv) > 2 else "b"
    dsn = export(key, klass)
    tools = refs.repo_root() / "tools"
    out = refs.repo_root() / "build" / "tools" / "dsndrc"
    out.mkdir(parents=True, exist_ok=True)
    jar, jdk = fr.jar_path(), fr.java_path().parent
    env = {"PATH": "/usr/bin:/bin"}  # JAVA_TOOL_OPTIONS (the proxy settings) only add noise
    subprocess.run([str(jdk / "javac"), "-nowarn", "-cp", str(jar), "-d", str(out), str(tools / "DsnDrc.java")],
                   check=True, env=env)
    return subprocess.run([str(jdk / "java"), "-cp", f"{jar}:{out}", "DsnDrc", str(dsn)], env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
