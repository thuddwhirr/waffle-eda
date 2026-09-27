#!/usr/bin/env python3
"""Where the router's trace insertion stopped (D90): for every "insert trace failed" line the jar logs at DEBUG
in a run's `freerouting.log`, the nearest copper of another net on that layer at the stop point, by kind (a
pad, a feed via or stub, the router's own track or via), read off the run's routed board, and the corridor
between the two nearest items there against the 2 * (half width + clearance) a trace needs.

    python3 scripts/insertion_stops.py build/fr/<run dir> [feeds]

The run directory holds `freerouting.log` and `<key>-routed.kicad_pcb` (a `scripts/rung.py` run); `feeds`
says the run laid plane feeds, so their vias and stubs are told apart from the router's copper. The jar's
points are in 0.1 um with y negated. The fixed items are the same throughout the run; the router's own copper
is its final state, a proxy for the state at the failure.
"""
import math, re, sys
from pathlib import Path
import _path  # noqa: F401
import pcbnew
from waffle_eda.bench import rebuild, references as refs
from waffle_eda.kicad import board as kb
from waffle_eda.route import freerouting as fr, planes as feedlib

run = Path(sys.argv[1])
feeds_on = len(sys.argv) > 2 and sys.argv[2] == "feeds"
key = run.name.split("-gnd")[0].split("-none")[0]
ref = refs.REFERENCES[key]
rules = rebuild.measure_rules(ref)
routed = kb.load_board(run / f"{ref.key}-routed.kicad_pcb")
layers = [lid for lid, _ in kb.copper_layers(routed)]  # DSN layer index -> KiCad layer id, in stack order
names = {lid: routed.GetLayerName(lid) for lid in layers}
feed_vias, feed_stubs = set(), set()
if feeds_on:
    bare, info = rebuild.strip_all(ref)
    b0 = kb.load_board(bare)
    outer = {kb.copper_layers(b0)[0][1], kb.copper_layers(b0)[-1][1]}
    nets = {p["net"] for p in info["pours"] if p["layer"] not in outer}
    for f in feedlib.plane_feeds(b0, rules, nets, copper=True):
        feed_vias.add((round(f.via[0], 3), round(f.via[1], 3)))
        if not f.in_pad:
            feed_stubs.add((round(f.start[0], 3), round(f.start[1], 3), round(f.via[0], 3), round(f.via[1], 3)))
pads = []  # (pad, "REF-N", rect)
rects = {r.name: r for r in feedlib._rects(routed)}
for fp in routed.GetFootprints():
    for pad in fp.Pads():
        if pad.GetLayerSet().CuStack():
            name = f"{fp.GetReference()}-{pad.GetNumber()}"
            pads.append((pad, name, rects[name]))
tracks = list(kb.track_segments(routed))
vias = list(kb.vias(routed))

def seg_dist(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    L2 = (bx - ax) ** 2 + (by - ay) ** 2 or 1e-12
    t = max(0.0, min(1.0, ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / L2))
    return math.hypot(p[0] - (ax + t * (bx - ax)), p[1] - (ay + t * (by - ay)))

rows = []
for line in (run / "freerouting.log").read_text().splitlines():
    m = re.search(r"insert trace failed for net #(\d+) at corner (\d+)/(\d+) on layer (\d+), trace width: (\d+), from corner: (\d+), okPoint: (\(([-\d]+),([-\d]+)\)|null), target: \(([-\d]+),([-\d]+)\)", line)
    if not m:
        continue
    net, ci, cn, layer_i, half, fc = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6))
    if m.group(7) == "null":
        rows.append((net, layer_i, None, None)); continue
    ok = (int(m.group(8)) / 10000.0, -int(m.group(9)) / 10000.0)
    tgt = (int(m.group(10)) / 10000.0, -int(m.group(11)) / 10000.0)
    rows.append((net, layer_i, ok, tgt))

kinds = {}
detail = []
for net, layer_i, ok, tgt in rows:
    if ok is None:
        kinds["okPoint null"] = kinds.get("okPoint null", 0) + 1
        continue
    lid = layers[layer_i]
    near = []  # (distance from the stop point to the item's copper edge, kind, net)
    for pad, name, rect in pads:
        if lid not in pad.GetLayerSet().CuStack():
            continue
        d = rect.distance(ok)
        kind = "PTH pad" if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH else "SMD pad"
        near.append((d, kind, pad.GetNetname(), name))
    for v in vias:
        p = (kb.mm(v.GetPosition().x), kb.mm(v.GetPosition().y))
        d = math.hypot(p[0] - ok[0], p[1] - ok[1]) - kb.via_diameter_mm(v) / 2
        kind = "feed via" if (round(p[0], 3), round(p[1], 3)) in feed_vias else "router via"
        near.append((d, kind, v.GetNetname(), ""))
    for t in tracks:
        if t.GetLayer() != lid:
            continue
        a, b = (kb.mm(t.GetStart().x), kb.mm(t.GetStart().y)), (kb.mm(t.GetEnd().x), kb.mm(t.GetEnd().y))
        d = seg_dist(ok, a, b) - kb.mm(t.GetWidth()) / 2
        key = (round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3))
        key2 = (round(b[0], 3), round(b[1], 3), round(a[0], 3), round(a[1], 3))
        kind = "feed stub" if key in feed_stubs or key2 in feed_stubs else "router track"
        near.append((d, kind, t.GetNetname(), ""))
    near.sort()
    # the closest item of any net, and the closest fixed item (pad, feed) within 0.3 mm
    closest = near[0] if near else None
    fixed = [n for n in near if n[1] in ("PTH pad", "SMD pad", "feed via", "feed stub") and n[0] < 0.3]
    label = f"{closest[1]}" if closest else "nothing"
    if fixed:
        label += f" | fixed within 0.3: {fixed[0][1]} ({fixed[0][2]}, {fixed[0][0]:.3f})"
    kinds[closest[1] if closest else "nothing"] = kinds.get(closest[1] if closest else "nothing", 0) + 1
    detail.append((net, names[lid], ok, closest, fixed[:2]))
print(f"{run.name}: {len(rows)} failed insertions; the nearest copper at the stop point, by kind:")
for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]):
    print(f"  {v:3d} {k}")
fixed_close = sum(1 for d in detail if d[4])
print(f"  {fixed_close} of {len(detail)} stop within 0.3 mm of a fixed item (pad or feed)")
for net, lname, ok, closest, fixed in detail[:14]:
    print(f"   net#{net:<3} {lname:<6} at ({ok[0]:.3f},{ok[1]:.3f}) closest {closest[1]} {closest[2]} {closest[0]:+.3f} mm{'  fixed: ' + ', '.join(f'{f[1]} {f[2]} {f[3]} {f[0]:+.3f}' for f in fixed) if fixed else ''}")

# the corridor at the stop point: the two nearest items of other nets on opposite sides, fixed items only and
# any items; a trace needs 2 * (half width + clearance) = 0.4314 mm of corridor
need = 2 * (rules.min_track_mm / 2 + rules.clearance_mm - fr.clearance_slack_mm())
def corridor(items):
    if len(items) < 2:
        return None
    return items[0][0] + items[1][0]
fixed_c, any_c = [], []
for net, lname, ok, closest, fixed in detail:
    pass
# recompute with full lists (detail kept only the closest): redo the loop briefly
for net, layer_i, ok, tgt in rows:
    if ok is None:
        continue
    lid = layers[layer_i]
    allc, fixc = [], []
    for pad, name, rect in pads:
        if lid in pad.GetLayerSet().CuStack():
            d = rect.distance(ok); allc.append(d); fixc.append(d)
    for v in vias:
        p = (kb.mm(v.GetPosition().x), kb.mm(v.GetPosition().y))
        d = math.hypot(p[0] - ok[0], p[1] - ok[1]) - kb.via_diameter_mm(v) / 2
        allc.append(d)
        if (round(p[0], 3), round(p[1], 3)) in feed_vias: fixc.append(d)
    for t in tracks:
        if t.GetLayer() == lid:
            a, b = (kb.mm(t.GetStart().x), kb.mm(t.GetStart().y)), (kb.mm(t.GetEnd().x), kb.mm(t.GetEnd().y))
            allc.append(seg_dist(ok, a, b) - kb.mm(t.GetWidth()) / 2)
    allc.sort(); fixc.sort()
    any_c.append(allc[0] + allc[1] if len(allc) > 1 else None)
    fixed_c.append(fixc[0] + fixc[1] if len(fixc) > 1 else None)
import statistics
def summ(name, xs):
    xs = [x for x in xs if x is not None]
    under = sum(1 for x in xs if x < need)
    tight = sum(1 for x in xs if need <= x < need + 0.03)
    print(f"  corridor by {name}: {len(xs)} points, median {statistics.median(xs):.3f} mm; under the need ({need:.4f}) {under}, within 0.03 over it {tight}, wider {len(xs) - under - tight}")
summ("nearest two items of any kind", any_c)
summ("nearest two fixed items", fixed_c)
