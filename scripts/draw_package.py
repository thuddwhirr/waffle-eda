#!/usr/bin/env python3
"""Draw the region of one BGA package on a board, bus nets highlighted, as SVG and PNG.

    python3 scripts/draw_package.py <board.kicad_pcb> <reference> <out.png> [--margin 2] [--bus REGEX] [--layers F.Cu,In2.Cu]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.kicad import board as kb, render
from waffle_eda.route.lattice import Lattice


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("reference")
    ap.add_argument("out")
    ap.add_argument("--margin", type=float, default=2.0, help="pitches around the array")
    ap.add_argument("--bus", default=r"(?i)ram_|ddr|sdram", help="regex of the nets to highlight")
    ap.add_argument("--layers", default=None, help="comma-separated copper layers to draw (default all)")
    ap.add_argument("--px", type=float, default=110.0, help="pixels per mm")
    a = ap.parse_args()
    board = kb.load_board(a.board)
    lat = Lattice(kb.footprint(board, a.reference))
    region = lat.array_bbox_mm(a.margin)
    nets = kb.nets_matching(board, re.compile(a.bus))
    labels = {(b.x_mm, b.y_mm): b.number for b in lat.balls.values()}
    layers = tuple(a.layers.split(",")) if a.layers else None
    out = Path(a.out)
    svg = render.draw_region_svg(board, region, out.with_suffix(".svg"), nets, a.px, labels, layers,
                                 title=f"{Path(a.board).name} {a.reference} {a.layers or 'all layers'}")
    w = int((region[2] - region[0]) * a.px) + 1
    h = int((region[3] - region[1]) * a.px) + 25
    render.svg_to_png(svg, out, w, h)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
