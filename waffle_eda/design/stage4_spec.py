"""Stage 4: the PCB specification, `spec.toml`.

Input: `design.md`, `bom.csv` and the fab profile. Output: layer count, stack-up, impedance geometry, via
type, design rules, outline and price estimate. Gate: every rule within the fab's capability; every impedance
target covered; price within the ceiling (`docs/definition.md`).

The rules are the class A defaults below, held within the fab's minimums and within what the chosen parts
allow: the clearance stays under the smallest gap between two pads of a footprint (the SOT-563's 0.20 mm), or
the placement itself would fail DRC (D57). The outline is a first size from the parts' courtyards, within the
locked maximum; stage 5 may grow it within that maximum when a route fails (the closure loop). A price is a
number from a captured quote or it is unknown, and unknown escalates (definition.md section 4).
"""
from __future__ import annotations

import math
import time
import tomllib
from pathlib import Path

from waffle_eda.design import stage1_design as s1, stage2_bom as s2
from waffle_eda.design.directory import Design
from waffle_eda.design.gate import GateResult, write_report
from waffle_eda.fab import profiles
from waffle_eda.kicad import board as kb, libs

# Class A defaults, mm: generous against a standard fab's 0.1016 mm, with a 0.6/0.3 via (0.15 mm ring).
DEFAULT_RULES = {"track_width": 0.25, "clearance": 0.20, "via_diameter": 0.6, "via_drill": 0.3,
                 "hole_clearance": 0.25, "edge_clearance": 0.30}
PAD_GAP_MARGIN_MM = 0.01  # the clearance stays this far under the tightest pad gap of any footprint
ROUTING_ROOM = 1.5  # first outline: this many times the parts' boxes grown by the placer's keep-apart; stage 5 pulls it in
EDGE_PART_MARGIN_MM = 1.0  # beyond the edge clearance, around a part that sits on an edge


def pad_gaps(bom: s2.Bom) -> dict[str, tuple[float, str, str]]:
    """Per part, the smallest gap between two pads with different numbers, from the footprint's pad boxes."""
    out = {}
    for line in bom.lines:
        fp = libs.load_footprint(line.footprint)
        pads = [(p.GetNumber(), p.GetBoundingBox()) for p in fp.Pads() if p.GetNumber()]
        best = None
        for i, (na, a) in enumerate(pads):
            for nb, b in pads[i + 1:]:
                if na == nb:
                    continue
                dx = max(kb.mm(b.GetLeft() - a.GetRight()), kb.mm(a.GetLeft() - b.GetRight()))
                dy = max(kb.mm(b.GetTop() - a.GetBottom()), kb.mm(a.GetTop() - b.GetBottom()))
                gap = max(dx, dy)
                if best is None or gap < best[0]:
                    best = (round(gap, 4), na, nb)
        if best:
            out[line.reference] = best
    return out


def courtyard_boxes(bom: s2.Bom) -> dict[str, tuple[float, float]]:
    """Per part, the footprint's bounding box without text (courtyard, pads, silk), as width and height."""
    out = {}
    for line in bom.lines:
        fp = libs.load_footprint(line.footprint)
        bb = fp.GetBoundingBox(False, False)
        out[line.reference] = (round(kb.mm(bb.GetWidth()), 3), round(kb.mm(bb.GetHeight()), 3))
    return out


def first_outline(doc: s1.DesignDoc, bom: s2.Bom, boxes: dict, rules: dict) -> tuple[float, float]:
    """A first board size: the courtyard area times the routing room, in the locked maximum's proportions, and
    no shorter along an edge than the parts that edge carries."""
    from waffle_eda.design.placer import KEEP_APART_MM as k
    max_w, max_h = doc.max_size_mm or (50.0, 50.0)
    area = ROUTING_ROOM * sum((w + k) * (h + k) for w, h in boxes.values())
    aspect = max_w / max_h
    w, h = math.sqrt(area * aspect), math.sqrt(area / aspect)
    by_block = bom.by_block()
    margin = rules["edge_clearance"] + EDGE_PART_MARGIN_MM
    for interface in doc.interfaces.values():
        if interface.position.free:
            continue
        for block in interface.blocks:
            bw, bh = boxes[by_block[block].reference]
            along = max(bw, bh)  # the part lies along the edge
            if interface.position.edge in ("left", "right"):
                h = max(h, along + 2 * margin)
            else:
                w = max(w, along + 2 * margin)
    w, h = min(math.ceil(w * 2) / 2, max_w), min(math.ceil(h * 2) / 2, max_h)
    return w, h


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_toml(data: dict, path: Path, header: str = "") -> None:
    """Tables of scalars and lists, one level deep (what the spec needs), written by hand: nothing on disk
    writes TOML and the reader is the standard library."""
    lines = [header] if header else []
    for table, values in data.items():
        lines.append(f"[{table}]")
        for k, v in values.items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    path.write_text("\n".join(lines))


def load(design: Design) -> dict:
    return tomllib.loads(design.spec_toml.read_text())


def run(design: Design) -> GateResult:
    t0 = time.time()
    r = GateResult(4, "spec")
    doc = s1.load(design)
    bom = s2.load(design)
    fab = profiles.load(doc.fab_profile)
    cap = fab.capability
    gaps = pad_gaps(bom)
    boxes = courtyard_boxes(bom)
    tightest = min(gaps.values(), default=(1.0, "", ""))
    tightest_ref = next((ref for ref, g in gaps.items() if g == tightest), "")
    rules = dict(DEFAULT_RULES)
    rules["clearance"] = min(rules["clearance"], round(tightest[0] - PAD_GAP_MARGIN_MM, 4))
    rules["annular_ring"] = round((rules["via_diameter"] - rules["via_drill"]) / 2, 4)
    layers = 2
    stackup = next((name for name, s in fab.stackups.items() if s.get("layers") == layers), None)
    width, height = first_outline(doc, bom, boxes, rules)
    spec = {
        "design": {"name": design.name, "fab": fab.name, "assembler": doc.fab.get("assembler", ""),
                   "quantity": doc.quantity, "written": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())},
        "board": {"layers": layers, "copper_layers": ["F.Cu", "B.Cu"], "thickness_mm": 1.6, "outer_copper_oz": 1.0,
                  "material": "FR-4", "surface_finish": "HASL", "assembly_sides": 1,
                  "why": "two layers and one assembled side: a breakout with no fine-pitch package or impedance target; HASL is the cheapest finish offered"},
        "stackup": {"name": stackup or "none", **{k: v for k, v in (fab.stackups.get(stackup) or {}).items()}},
        "outline": {"width_mm": width, "height_mm": height, "corner_radius_mm": 1.0,
                    "max_mm": list(doc.max_size_mm or ()), "origin_mm": [100.0, 100.0],
                    "why": f"{ROUTING_ROOM} times the parts' boxes (grown by the placer's keep-apart) in the maximum's proportions, not shorter than the parts on an edge; stage 5 grows it for room or pulls it in to the parts"},
        "rules": {**rules, "min_pad_gap_mm": tightest[0], "min_pad_gap_part": f"{tightest_ref} pads {tightest[1]} and {tightest[2]}",
                  "why": f"class A defaults; the clearance stays {PAD_GAP_MARGIN_MM} mm under the tightest pad gap ({tightest[0]} mm on {tightest_ref})"},
        "vias": {"type": "through", "via_in_pad": False, "filled_capped": False},
        "impedance": {"targets": [], "note": "no controlled-impedance net: I2C at 400 kHz and DC supply"},
        "price": {"status": "unknown", "estimate": "unknown",
                  "note": "the fab profile has no price model (D5); a quote comes from the owner or the vendor's order page"},
    }
    for ref, (w, h) in boxes.items():
        spec.setdefault("parts", {})[ref] = [w, h]
    write_toml(spec, design.spec_toml, "# The PCB specification, written by waffle_eda.design.stage4_spec from design.md, bom.csv and the fab\n"
                                        "# profile; stage 5 reads it. Regenerated each run: edit design.md or the profile, not this file.\n")
    # the gate
    r.check("the layer count is one the fab offers", fab.supports_layers(layers), f"{layers} of {cap['layer_counts']}")
    within = [("track_width", "min_track_outer_mm"), ("clearance", "min_clearance_outer_mm"), ("via_drill", "min_drill_mm"),
              ("annular_ring", "min_annular_ring_mm"), ("hole_clearance", "hole_clearance_mm"), ("edge_clearance", "copper_to_edge_mm")]
    short = [f"{k} {rules[k]} under the fab's {cap[fk]}" for k, fk in within if rules[k] < cap[fk] - 1e-9]
    r.check("every rule within the fab's capability", not short, "; ".join(short) or
            ", ".join(f"{k} {rules[k]} (fab {cap[fk]})" for k, fk in within))
    r.check("the clearance fits between the tightest pads of every footprint", rules["clearance"] < tightest[0],
            f"clearance {rules['clearance']}, tightest gap {tightest[0]} on {tightest_ref}")
    r.check("the via is a standard through via", spec["vias"]["type"] == "through" and not spec["vias"]["via_in_pad"], "0.6 / 0.3 mm")
    mx = doc.max_size_mm
    r.check("the outline is within the locked maximum", mx is not None and width <= mx[0] and height <= mx[1],
            f"{width} x {height} mm of {mx}")
    r.check("every part fits the outline with the edge clearance", all(w < width - 2 * rules["edge_clearance"] and h < height - 2 * rules["edge_clearance"] for w, h in boxes.values()),
            ", ".join(f"{ref} {w}x{h}" for ref, (w, h) in boxes.items()))
    r.check("every impedance target covered", not spec["impedance"]["targets"], spec["impedance"]["note"])
    if stackup is None:
        r.fail("a stack-up for the layer count is in the fab profile", f"no {layers}-layer stack-up in {fab.name}")
    else:
        r.ok("a stack-up for the layer count is in the fab profile", f"{stackup}: {fab.stackups[stackup].get('note', '')}")
    r.escalate("price within the ceiling", f"estimate unknown ({spec['price']['note']}); ceiling {doc.locked.get('cost', 'unknown')}")
    r.numbers = {"layers": layers, "outline mm": [width, height], "rules": {k: rules[k] for k in DEFAULT_RULES},
                 "tightest pad gap mm": tightest[0], "courtyard area mm2": round(sum(w * h for w, h in boxes.values()), 1)}
    r.outputs = [design.relative(design.spec_toml)]
    r.next = "stage 5: placement and routing" if r.passed else "fix the rules or the profile and run stage 4 again"
    r.seconds = round(time.time() - t0, 1)
    write_report(r, design.reports)
    return r
