#!/usr/bin/env python3
"""A gate row up to the router and no further (D147): the export under the class's configuration, the plane-reach
check (`route.planes.unreached`), and whether the DSN is still the one the row's frozen session was routed from.
Seconds a board; what a change to the export does, before any router time is spent on it.

    python3 scripts/preflight.py [<key> ...] [a|b]      # every frozen row of class b when none named
"""
import sys

import _path  # noqa: F401
import gate
from waffle_eda.bench import rebuild, references as refs, replay
from waffle_eda.kicad import board as kb
from waffle_eda.route import freerouting as fr


class _Stop(Exception):
    pass


def main(argv: list[str]) -> int:
    klass = argv.pop() if argv and argv[-1] in ("a", "b") else "b"
    keys = argv or [k for k in replay.frozen_keys() if replay.manifest(k)["row"]["gate"] == klass]
    cfg = gate.configuration(gate.CLASS_B if klass == "b" else gate.CLASS_A)
    seen: dict = {}

    def stop(dsn, *_a, **_k):  # the DSN as the gate's row would write it: its header names the board's path
        import hashlib
        text = dsn.read_bytes().replace(f"{dsn.parent.name}/board.dsn".encode(),
                                         f"{dsn.parent.name.removesuffix('-preflight')}/board.dsn".encode(), 1)
        seen["dsn"] = hashlib.md5(text).hexdigest()
        raise _Stop()

    fr.run_jar = stop
    for key in keys:
        ref = refs.REFERENCES[key]
        bare, info = rebuild.strip_all(ref)
        rules = rebuild.measure_rules(ref)
        board = kb.load_board(bare)
        planes, pours = gate.plane_split(board, info["pours"], cfg["planes"])
        outer = {kb.copper_layers(board)[0][1], kb.copper_layers(board)[-1][1]}
        plane_nets = {p["net"] for p in info["pours"] if p["layer"] not in outer} if cfg["feeds"] else None
        extra = {}
        if "plane_type" in cfg:
            extra = {"plane_type": cfg["plane_type"], "via_costs": cfg["via_costs"],
                     "plane_via_costs": cfg["plane_via_costs"], "ripup_costs": cfg["ripup_costs"],
                     "via_bands": cfg["via_bands"], "slack_mm": cfg["slack_mm"], "ring_per_axis": cfg["ring_per_axis"],
                     "via_at_smd": cfg["via_at_smd"],
                     "layer_trace_costs": {p["layer"]: cfg["layer_costs"] for p in planes} if planes else None}
        said: list[str] = []
        try:
            fr.route_board(board, rules, refs.repo_root() / "build" / "fr" / f"{key}-preflight", pours=pours,
                           planes=planes, feeds=plane_nets, stubs=cfg["stubs"], gui=False, feeds_mode=cfg["feeds_mode"],
                           via_in_pad=cfg["via_in_pad"], pour_pins_rule=cfg["pour_pins"], say=said.append, **extra)
        except _Stop:
            pass
        frozen = replay.manifest(key)["dsn_md5"] if key in replay.frozen_keys() else None
        dsn = "same DSN as frozen" if seen.get("dsn") == frozen else f"DSN changed ({seen.get('dsn', '?')[:10]})"
        notes = [s for s in said if s.startswith(("plated pads", "no-pour areas carved"))]
        print(f"{key:<24} {dsn}; " + "; ".join(notes))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
