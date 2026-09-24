"""Stage 5: placement, routing and checks, under the acceptance rule of `docs/definition.md` section 3.

Input: `spec.toml`, `netlist.net` and the footprints. Output: a routed board under `kicad/`, DRC clean under
the specification's rules, with the gate's renders and the attempt log under `reports/`. A run ends in one of
two states: complete (every net routed, zero electrical violations under the rules, every part inside the
outline), or failed with a report that names what could not be met, the evidence and the design changes that
would resolve it. A partially routed board is not an outcome.

The closure loop in its simplest form (milestone A): an attempt is a placement (`placer.py`, seeded by the
attempt number), a route by stage 5's baseline (`route/freerouting.route_board`, the class A gate's router,
with the repairs it carries), the ground pours on both layers, a refill and KiCad's DRC under the rules; a
failed attempt is logged to `reports/attempts.log` and the next one places again with the next seed and, when
the failure was room (nets left open or clearances the repair could not settle), an outline grown by a step
within the locked maximum. The budget is `ATTEMPTS`.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from waffle_eda.bench import rebuild
from waffle_eda.design import stage1_design as s1, stage2_bom as s2, stage4_spec as s4, board_build, placer
from waffle_eda.design.directory import Design
from waffle_eda.design.gate import GateResult, write_report
from waffle_eda.kicad import board as kb, render
from waffle_eda.route import freerouting

ATTEMPTS = 4
GROW_STEP = 0.10  # the outline grows by this fraction of the maximum after an attempt that failed for room


def rules_for(spec: dict, name: str, nets: int) -> rebuild.BoardRules:
    r = spec["rules"]
    return rebuild.BoardRules(reference=name, board_mtime=0.0, clearance_mm=r["clearance"],
                              hole_to_copper_mm=r["hole_clearance"], edge_clearance_mm=r["edge_clearance"],
                              min_track_mm=r["track_width"], min_via_mm=r["via_diameter"], min_drill_mm=r["via_drill"],
                              min_annular_mm=r["annular_ring"], layers=tuple(spec["board"]["copper_layers"]), nets=nets)


def pours_for(spec: dict, board, net: str = "GND") -> list[dict]:
    """The supply pours every class A reference lays: the ground net on every copper layer, over the whole
    outline (the filler keeps the edge clearance), with the rules' clearance and width, thermal reliefs."""
    if net not in kb.net_names(board):
        return []
    x0, y0, x1, y1 = board_build.outline_rect(spec)
    outline = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [{"net": net, "layer": layer, "clearance_mm": spec["rules"]["clearance"],
             "min_thickness_mm": spec["rules"]["track_width"], "pad_connection": 1, "outline_mm": outline}
            for layer in spec["board"]["copper_layers"]]


def fixed_edges(doc: s1.DesignDoc, bom: s2.Bom) -> dict[str, tuple[str, str]]:
    out = {}
    by_block = bom.by_block()
    for interface in doc.interfaces.values():
        if interface.position.free:
            continue
        for block in interface.blocks:
            out[by_block[block].reference] = (interface.position.edge, interface.position.along)
    return out


@dataclass
class Attempt:
    number: int
    seed: int
    outline_mm: tuple[float, float]
    placement: dict = field(default_factory=dict)
    router: str = ""
    router_unrouted: int | None = None
    facts: dict = field(default_factory=dict)
    connected: int = 0
    nets: int = 0
    passed: bool = False
    digest: str = ""
    seconds: float = 0.0
    error: str = ""
    warnings: dict = field(default_factory=dict)  # KiCad's non-electrical findings, for the owner's eye

    def line(self) -> str:
        return (f"attempt {self.number} seed {self.seed} outline {self.outline_mm[0]}x{self.outline_mm[1]} mm: "
                f"placement cost {self.placement.get('cost')} overlaps {self.placement.get('overlaps')} "
                f"compaction '{self.placement.get('compaction', '')}'; "
                f"router {self.router_unrouted} unrouted; DRC electrical {self.facts.get('electrical')} "
                f"{self.facts.get('by_type') or ''} unconnected items {self.facts.get('unconnected_items')}; "
                f"nets {self.connected}/{self.nets}; {'PASS' if self.passed else 'fail'}; digest {self.digest}; "
                f"{self.seconds:.0f} s" + (f"; error {self.error}" if self.error else ""))


def score(board_path: Path, rules: rebuild.BoardRules, work: Path) -> tuple[dict, int, int]:
    """DRC facts under the rules, and the nets connected of the nets to route (what the class A gate scores)."""
    facts = rebuild.drc_under_rules(board_path, rules.values(), work, tag="candidate")
    board = kb.load_board(board_path)
    nets = sorted(rebuild.routable_nets(board))
    open_nets = set(facts["unconnected_nets"])
    connected = sum(1 for n in nets if kb.unescape_net(n) not in open_nets)
    return facts, connected, len(nets)


def warnings(board_path: Path, work: Path) -> dict:
    """KiCad's own DRC at warning level on the shipped board, in place (its project and library tables beside
    it): silkscreen over pads, courtyards, and the like. Not the gate's criterion (the acceptance rule is
    electrical) but part of what the owner reviews."""
    from waffle_eda.bench import harness
    work.mkdir(parents=True, exist_ok=True)
    report = harness.run_drc(board_path, work / "warnings.json", severity="--severity-warning")
    out: dict = {}
    for v in report.get("violations", []):
        out[v.get("type")] = out.get(v.get("type"), 0) + 1
    return dict(sorted(out.items()))


def attempt(design: Design, spec: dict, doc: s1.DesignDoc, bom: s2.Bom, number: int, say=lambda _m: None) -> Attempt:
    t0 = time.time()
    a = Attempt(number, number - 1, (spec["outline"]["width_mm"], spec["outline"]["height_mm"]))
    work = design.work / f"attempt-{number}"
    work.mkdir(parents=True, exist_ok=True)
    board, fps = board_build.build(spec, design.netlist)
    try:
        p = placer.Placer(board, fps, board_build.outline_rect(spec), spec["rules"]["edge_clearance"], fixed_edges(doc, bom), seed=a.seed)
        a.placement = p.run()
    except RuntimeError as why:
        a.error = str(why)
        a.seconds = round(time.time() - t0, 1)
        return a
    if a.placement["compacted"]:  # the placer pulled the outline in: the board and the record follow it
        x0, y0, x1, y1 = a.placement["outline"]
        spec["outline"]["origin_mm"] = [x0, y0]
        spec["outline"]["width_mm"], spec["outline"]["height_mm"] = round(x1 - x0, 2), round(y1 - y0, 2)
        board_build.draw_outline(board, spec)
        a.outline_mm = (spec["outline"]["width_mm"], spec["outline"]["height_mm"])
    placed = work / "placed.kicad_pcb"
    kb.save_board(board, placed)
    say(f"placed: {a.placement}")
    board = kb.load_board(placed)  # the router and the filler get a board read from its file, as the gate's
    # reference boards are: a board built in memory and handed straight on segfaulted inside pcbnew (2026-09-24)
    rules = rules_for(spec, design.name, len(rebuild.routable_nets(board)))
    pours = pours_for(spec, board)
    try:
        result = freerouting.route_board(board, rules, work, pours=pours, say=say)
    except Exception as why:  # a router that cannot run is a failed attempt with its reason, not a crash
        a.error = f"{type(why).__name__}: {why}"
        a.seconds = round(time.time() - t0, 1)
        return a
    a.router, a.router_unrouted = result.summary(), result.unrouted
    kb.refill_zones(board)
    routed = work / "routed.kicad_pcb"
    kb.save_board(board, routed)
    a.facts, a.connected, a.nets = score(routed, rules, work / "score")
    a.digest = freerouting.geometry_digest(board)
    a.passed = (a.connected == a.nets and a.facts["unconnected_items"] == 0 and a.facts["electrical"] == 0
                and not a.placement["overlaps"])
    a.seconds = round(time.time() - t0, 1)
    return a


def grow(spec: dict, doc: s1.DesignDoc) -> bool:
    """Grow the outline one step towards the locked maximum; False when it is already there."""
    mx = doc.max_size_mm
    if mx is None:
        return False
    w, h = spec["outline"]["width_mm"], spec["outline"]["height_mm"]
    nw, nh = min(w + GROW_STEP * mx[0], mx[0]), min(h + GROW_STEP * mx[1], mx[1])
    nw, nh = round(nw * 2) / 2, round(nh * 2) / 2
    if (nw, nh) == (w, h):
        return False
    spec["outline"]["width_mm"], spec["outline"]["height_mm"] = nw, nh
    return True


def diagnosis(attempts: list[Attempt], spec: dict, doc: s1.DesignDoc) -> str:
    """The failure report the acceptance rule asks for: the constraint, the evidence, the changes that resolve it."""
    last = attempts[-1]
    lines = []
    if last.error:
        lines.append(f"The run could not complete: {last.error}.")
    open_nets = last.facts.get("unconnected_nets", [])
    if open_nets:
        lines.append(f"Nets left open after {len(attempts)} attempts: {open_nets} (the router reported "
                     f"{last.router_unrouted} unrouted).")
    if last.facts.get("electrical"):
        lines.append(f"Electrical violations the repair could not settle: {last.facts.get('by_type')}.")
    if last.placement.get("overlaps"):
        lines.append(f"Parts whose courtyards overlap: {last.placement['overlaps']}.")
    mx = doc.max_size_mm
    at_max = mx is not None and (spec["outline"]["width_mm"], spec["outline"]["height_mm"]) == tuple(mx)
    lines.append("Tried: " + "; ".join(f"attempt {a.number} at {a.outline_mm[0]}x{a.outline_mm[1]} mm, seed {a.seed}, "
                                       f"{a.connected}/{a.nets} nets, {a.facts.get('electrical')} violations" for a in attempts) + ".")
    changes = []
    if at_max:
        changes.append(f"a larger maximum board size than the locked {mx[0]} x {mx[1]} mm")
    fixed = [i.name for i in doc.interfaces.values() if not i.position.free]
    if fixed:
        changes.append(f"freeing the position of {', '.join(fixed)}")
    changes.append("fewer parts, or a coarser rule set from a different fab tier")
    lines.append("Design changes that would resolve it, for the owner: " + "; ".join(changes) + ".")
    return " ".join(lines)


def run(design: Design) -> GateResult:
    t0 = time.time()
    r = GateResult(5, "layout")
    missing = freerouting.available()
    if missing:
        r.fail("stage 5's router can run", missing)
        r.seconds = round(time.time() - t0, 1)
        write_report(r, design.reports)
        return r
    doc = s1.load(design)
    bom = s2.load(design)
    spec = s4.load(design)
    log = design.reports / "attempts.log"
    design.reports.mkdir(parents=True, exist_ok=True)
    attempts: list[Attempt] = []
    with log.open("a") as f:
        f.write(f"# {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} stage 5 on {design.name}\n")
        for k in range(1, ATTEMPTS + 1):
            a = attempt(design, spec, doc, bom, k, say=lambda m: None)
            attempts.append(a)
            f.write(a.line() + "\n")
            f.flush()
            if a.passed:
                break
            room = bool(a.facts.get("unconnected_items")) or bool(a.facts.get("electrical")) or bool(a.error)
            if room:
                grow(spec, doc)
    last = attempts[-1]
    work = design.work / f"attempt-{last.number}"
    outputs = [design.relative(log)]
    if last.passed:
        design.kicad_dir.mkdir(parents=True, exist_ok=True)
        board = kb.load_board(work / "routed.kicad_pcb")
        kb.save_board(board, design.board)
        rules = rules_for(spec, design.name, last.nets)
        design.rules.write_text(rules.rules_text())
        if spec["outline"] != s4.load(design)["outline"]:
            s4.write_toml(spec, design.spec_toml, "# The PCB specification, written by waffle_eda.design.stage4_spec from design.md, bom.csv and the fab\n"
                                                  "# profile, with the outline as stage 5 left it (grown for room or pulled in to the parts, within the\n"
                                                  "# locked maximum). Regenerated each run: edit design.md or the profile, not this file.\n")
        last.warnings = warnings(design.board, work / "warnings")
        svg = render.export_svg(design.board, design.reports / "layout.svg")
        outputs += [design.relative(design.board), design.relative(design.rules), design.relative(svg)]
        try:
            png = render.render_png(design.board, design.reports / "layout.png")
            outputs.append(design.relative(png))
        except RuntimeError as why:
            r.numbers["render"] = f"png render failed: {why}"[:200]
    # the acceptance rule
    r.check("every net routed", last.passed or (last.connected == last.nets and not last.facts.get("unconnected_items")),
            f"{last.connected} of {last.nets} nets; unconnected items {last.facts.get('unconnected_items')}" if not last.error else last.error)
    r.check("DRC clean under the specification's rules", not last.error and last.facts.get("electrical") == 0,
            f"electrical {last.facts.get('electrical')} {last.facts.get('by_type') or ''}")
    r.check("every part inside the outline, no courtyards overlapping", bool(last.placement) and not last.placement.get("overlaps"),
            f"overlaps {last.placement.get('overlaps')}" if last.placement else "not placed")
    mx = doc.max_size_mm
    r.check("the outline within the locked maximum", mx is not None and last.outline_mm[0] <= mx[0] and last.outline_mm[1] <= mx[1],
            f"{last.outline_mm[0]} x {last.outline_mm[1]} mm of {mx}")
    r.ok("bus and pair rules", "none in this design (no bus, no differential pair)")
    if not r.passed:
        r.fail("failed, with a report (definition.md section 3)", diagnosis(attempts, spec, doc))
    r.numbers = {**r.numbers, "attempts": len(attempts), "outline mm": list(last.outline_mm), "nets": last.nets,
                 "connected": last.connected, "electrical violations": last.facts.get("electrical"),
                 "placement cost": last.placement.get("cost"), "compacted": last.placement.get("compacted"),
                 "references hidden from the silkscreen": last.placement.get("references_hidden"),
                 "DRC warnings (not scored)": last.warnings, "router": last.router, "digest": last.digest,
                 "seconds": round(sum(a.seconds for a in attempts), 1)}
    r.outputs = outputs
    r.next = "stage 6: fab outputs" if r.passed else "the report names the design change; the owner decides"
    r.seconds = round(time.time() - t0, 1)
    write_report(r, design.reports)
    return r
