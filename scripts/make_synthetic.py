#!/usr/bin/env python3
"""Write every synthetic BGA-pair case to build/synthetic/<name>.kicad_pcb with its manifest."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.bench import synthetic


def main() -> int:
    out_dir = Path("build/synthetic")
    for name, case in synthetic.CASES.items():
        manifest = synthetic.make_bga_pair(case, out_dir / f"{name}.kicad_pcb")
        (out_dir / f"{name}.json").write_text(json.dumps(manifest, indent=1))
        print(f"{name:<22} {case.rows}x{case.cols} balls, {case.layers} layers, bus {case.bus_nets} nets ({case.order}), power balls {case.power_balls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
