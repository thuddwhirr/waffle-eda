"""Draw a bus plan dumped by ``scripts/replay_bus.py`` (``REPLAY_PLAN_DUMP=path``): the planner's runs per layer
coloured by bundle, the reference's runs in grey, the crossings as red dots, the packages as boxes; one SVG and PNG
per layer in the output directory, and a breakdown of the crossings by bundle on stdout.

    python3 scripts/draw_plan.py build/plan-ref-layers.json build/plan-draw
"""
import json
import sys
from collections import Counter
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.kicad import render
d = json.load(open(sys.argv[1]))
out = Path(sys.argv[2])
c = d["cell_mm"]; ox, oy = d["origin"]
runs = d["runs"]
layers = sorted({r["layer"] for r in runs if r["layer"]})
same = Counter()
for a, b, L, xy in d["crossings"]:
    ra, rb = runs[a], runs[b]
    key = "same net" if ra["net"] == rb["net"] else ("same bundle" if ra["group"] == rb["group"] else
           ("same group" if ra["group"][0] == rb["group"][0] else "different groups"))
    same[key] += 1
print("crossings by kind:", dict(same))
pairs = Counter()
for a, b, L, xy in d["crossings"]:
    ra, rb = runs[a], runs[b]
    pairs[(tuple(ra["group"]), tuple(rb["group"]))] += 1
for k, v in pairs.most_common(10):
    print("   ", k, v)
xs = [p[0] for r in runs for p in r["reference_points"]] + [b for bb in d["packages"].values() for b in (bb[0], bb[2])]
ys = [p[1] for r in runs for p in r["reference_points"]] + [b for bb in d["packages"].values() for b in (bb[1], bb[3])]
x0, x1, y0, y1 = min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1
px = 40.0
W, H = int((x1 - x0) * px), int((y1 - y0) * px)
def X(x): return (x - x0) * px
def Y(y): return (y - y0) * px
colours = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#17becf"]
groups = sorted({tuple(r["group"]) for r in runs})
gcol = {g: colours[i % len(colours)] for i, g in enumerate(groups)}
for L in layers:
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           f'<rect width="{W}" height="{H}" fill="white"/>',
           f'<text x="10" y="20" font-size="16">{L}: planner runs coloured by bundle, reference runs grey, crossings red</text>']
    for name, bb in d["packages"].items():
        svg.append(f'<rect x="{X(bb[0])}" y="{Y(bb[1])}" width="{(bb[2]-bb[0])*px}" height="{(bb[3]-bb[1])*px}" fill="none" stroke="#999" stroke-dasharray="4"/>')
        svg.append(f'<text x="{X(bb[0])+4}" y="{Y(bb[1])+14}" font-size="12" fill="#999">{name}</text>')
    for r in runs:
        if r["reference_layer"] == L:
            pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in r["reference_points"])
            svg.append(f'<polyline points="{pts}" fill="none" stroke="#bbb" stroke-width="1.5"/>')
    for r in runs:
        if r["layer"] == L and r["cells"]:
            pts = " ".join(f"{X(ox + (i + 0.5) * c):.1f},{Y(oy + (j + 0.5) * c):.1f}" for i, j in r["cells"])
            svg.append(f'<polyline points="{pts}" fill="none" stroke="{gcol[tuple(r["group"])]}" stroke-width="1.2" opacity="0.9"/>')
            i, j = r["cells"][0]
            svg.append(f'<text x="{X(ox + (i + 0.5) * c):.1f}" y="{Y(oy + (j + 0.5) * c):.1f}" font-size="7" fill="{gcol[tuple(r["group"])]}">{r["net"]}</text>')
    for a, b, LL, (x, y) in d["crossings"]:
        if LL == L:
            svg.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3" fill="red" opacity="0.7"/>')
    ly = 40
    for g in groups:
        svg.append(f'<text x="10" y="{ly}" font-size="11" fill="{gcol[g]}">{" ".join(g)}</text>'); ly += 13
    svg.append("</svg>")
    path = out / f"plan-{L.replace('.', '')}.svg"
    path.write_text("\n".join(svg))
    render.svg_to_png(path, path.with_suffix(".png"), 1600, int(1600 * H / W))
    print("wrote", path.with_suffix(".png"))
