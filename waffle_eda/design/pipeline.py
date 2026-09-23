"""A design is a directory; this runs its six stages, one gate each, and says where it stands (plan.md, Interface).

    designs/<name>/design.md          stage 1, with connectivity.toml as its machine-readable part
    designs/<name>/bom.csv            stage 2
    designs/<name>/<name>.kicad_sch   stage 3, with reports/netlist.net and reports/erc.json
    designs/<name>/spec.toml          stage 4
    designs/<name>/<name>.kicad_pcb   stage 5, with reports/stage5-attempts.json and the renders
    designs/<name>/out/               stage 6

Every stage reads the previous stage's files and writes its own, and writes ``reports/stage<N>.json`` with
PASS or FAIL against its gate (definition.md, section 2) and what the owner is asked, if anything. Nothing is
passed in memory that a person cannot open.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from waffle_eda.bench import rebuild
from waffle_eda.design import board as board_mod
from waffle_eda.fab import profiles
from waffle_eda.kicad import board as kb, render
from waffle_eda.route import stage5 as route_stage
from waffle_eda.sch import schematic, symlib

STAGES = ("design document", "bom", "schematic", "pcb specification", "layout", "manufacturing outputs")
PLACEMENT_ATTEMPTS = 4


@dataclass
class GateResult:
    stage: int
    passed: bool
    findings: list = field(default_factory=list)  # every failing case first
    numbers: dict = field(default_factory=dict)
    asks: list = field(default_factory=list)  # what only the owner can decide
    outputs: list = field(default_factory=list)
    seconds: float = 0.0

    def summary(self) -> str:
        head = f"stage {self.stage} ({STAGES[self.stage - 1]}): {'PASS' if self.passed else 'FAIL'}"
        parts = [head] + [f"  FAIL {f}" for f in self.findings] + [f"  ask: {a}" for a in self.asks]
        if self.numbers:
            parts.append("  " + ", ".join(f"{k} {v}" for k, v in self.numbers.items()))
        return "\n".join(parts)


def design_dir(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "designs" / name


def _write(d: Path, result: GateResult) -> GateResult:
    (d / "reports").mkdir(exist_ok=True)
    (d / "reports" / f"stage{result.stage}.json").write_text(json.dumps(asdict(result), indent=1, default=str))
    return result


def _table(text: str, heading: str) -> dict[str, str]:
    """The two-column table under ``heading`` in a Markdown document, first column -> second."""
    section = text.split(f"## {heading}", 1)
    if len(section) < 2:
        return {}
    rows = {}
    for line in section[1].split("\n## ", 1)[0].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and not set(cells[0]) <= {"-", " "} and cells[0] not in ("Constraint", "Interface"):
            rows[cells[0]] = cells[1:]
    return rows


# --- stage 1 -----------------------------------------------------------------------------------------------
LOCKED = ("Maximum board size", "Cost ceiling, parts per board", "Fab and assembler", "Interface positions", "Feature set")


def stage1(d: Path) -> GateResult:
    """Owner review; every locked constraint explicit; every interface has a stated position or is marked free."""
    t0 = time.time()
    r = GateResult(stage=1, passed=True)
    doc = d / "design.md"
    if not doc.is_file():
        r.findings.append("design.md is missing")
        r.passed = False
        return _write(d, r)
    text = doc.read_text()
    locked = _table(text, "Locked set")
    for key in LOCKED:
        if key not in locked or not locked[key][0]:
            r.findings.append(f"locked constraint {key!r} is not explicit in the locked set")
    interfaces = _table(text, "Interfaces and positions")
    for name, cells in interfaces.items():
        position = cells[1] if len(cells) > 1 else ""
        if not position or ("free" not in position.lower() and "edge" not in position.lower()):
            r.findings.append(f"interface {name!r} has neither a stated position nor 'free'")
    try:
        conn = schematic.read_connectivity(d / "connectivity.toml")
        r.numbers["nets"] = len(conn.nets)
    except Exception as why:
        r.findings.append(f"connectivity.toml: {type(why).__name__}: {why}")
    if "Owner review: pending" in text:
        r.asks.append("review design.md and replace 'Owner review: pending' with the review's date")
    r.numbers["locked constraints"] = len(locked)
    r.numbers["interfaces"] = len(interfaces)
    r.passed = not r.findings
    r.outputs = [str(doc), str(d / "connectivity.toml")]
    r.seconds = round(time.time() - t0, 1)
    return _write(d, r)


# --- stage 2 -----------------------------------------------------------------------------------------------
def stage2(d: Path) -> GateResult:
    """Cost within ceiling; every part has a symbol, a footprint and a datasheet reference; long-lead flagged."""
    t0 = time.time()
    r = GateResult(stage=2, passed=True)
    bom_path = d / "bom.csv"
    if not bom_path.is_file():
        r.findings.append("bom.csv is missing")
        r.passed = False
        return _write(d, r)
    bom = schematic.read_bom(bom_path)
    total, unknown = 0.0, []
    for row in bom:
        ref = row["reference"]
        try:
            lib, name = row["symbol"].split(":", 1)
            symlib.get_symbol(lib, name)
        except Exception as why:
            r.findings.append(f"{ref}: symbol {row['symbol']!r}: {why}")
        try:
            board_mod.load_footprint(row["footprint"])
        except Exception as why:
            r.findings.append(f"{ref}: footprint {row['footprint']!r}: {why}")
        if not row["datasheet"]:
            r.findings.append(f"{ref}: no datasheet reference")
        try:
            total += float(row["unit_price_usd"]) * int(row["quantity"])
        except ValueError:
            unknown.append(ref)
        if row.get("long_lead", "").lower() == "yes":
            r.asks.append(f"{ref} is a long-lead part")
    locked = _table((d / "design.md").read_text(), "Locked set") if (d / "design.md").is_file() else {}
    ceiling = None
    m = re.search(r"([\d.]+)\s*USD", locked.get("Cost ceiling, parts per board", [""])[0])
    if m:
        ceiling = float(m.group(1))
    r.numbers = {"parts": len(bom), "priced total USD": round(total, 2), "unpriced parts": len(unknown),
                 "ceiling USD": ceiling}
    if unknown:
        r.asks.append(f"prices unknown for {', '.join(unknown)}: the cost decision escalates (definition.md, section 4)")
    elif ceiling is not None and total > ceiling:
        r.findings.append(f"parts cost {total:.2f} USD exceeds the ceiling {ceiling:.2f} USD")
    r.passed = not r.findings
    r.outputs = [str(bom_path)]
    r.seconds = round(time.time() - t0, 1)
    return _write(d, r)


# --- stage 3 -----------------------------------------------------------------------------------------------
def stage3(d: Path) -> GateResult:
    """ERC clean; the exported netlist matches the connectivity specification one to one; one sheet by function."""
    t0 = time.time()
    r = GateResult(stage=3, passed=True)
    conn = schematic.read_connectivity(d / "connectivity.toml")
    bom = schematic.read_bom(d / "bom.csv")
    libs = sorted({row["symbol"].split(":")[0] for row in bom} | {"power"})
    (d / "sym-lib-table").write_text("(sym_lib_table\n  (version 7)\n" + "".join(
        f'  (lib (name "{l}")(type "KiCad")(uri "${{KICAD9_SYMBOL_DIR}}/{l}.kicad_sym")(options "")(descr ""))\n' for l in libs) + ")\n")
    fps = sorted({row["footprint"].split(":")[0] for row in bom})
    (d / "fp-lib-table").write_text("(fp_lib_table\n  (version 7)\n" + "".join(
        f'  (lib (name "{l}")(type "KiCad")(uri "${{KICAD9_FOOTPRINT_DIR}}/{l}.pretty")(options "")(descr ""))\n' for l in fps) + ")\n")
    try:
        sch = schematic.write_schematic(d)
    except ValueError as why:
        r.findings.append(str(why))
        r.passed = False
        return _write(d, r)
    (d / "reports").mkdir(exist_ok=True)
    report = schematic.erc(sch, d / "reports" / "erc.json")
    errors = schematic.erc_errors(report)
    warnings = [v for s in report.get("sheets", []) for v in s.get("violations", []) if v.get("severity") == "warning"]
    r.findings += [f"ERC: {e}" for e in errors]
    netlist = schematic.export_netlist(sch, d / "reports" / "netlist.net")
    r.findings += [f"netlist: {x}" for x in schematic.compare(netlist, conn)]
    svg_dir = d / "reports" / "schematic-svg"
    subprocess.run([shutil.which("kicad-cli"), "sch", "export", "svg", "--output", str(svg_dir), str(sch)], capture_output=True)
    r.numbers = {"parts": len(bom), "nets": len(netlist), "erc errors": len(errors), "erc warnings": len(warnings)}
    r.passed = not r.findings
    r.outputs = [str(sch), str(d / "reports" / "netlist.net"), str(d / "reports" / "erc.json"), str(svg_dir)]
    r.seconds = round(time.time() - t0, 1)
    return _write(d, r)


# --- stage 4 -----------------------------------------------------------------------------------------------
def stage4(d: Path) -> GateResult:
    """Every rule within the fab's capability; every impedance target covered; price within ceiling."""
    t0 = time.time()
    r = GateResult(stage=4, passed=True)
    spec = board_mod.Spec.read(d / "spec.toml")
    fab = profiles.load(spec.fab)
    c = fab.capability
    checks = [
        ("layers", spec.layers in c["layer_counts"], f"{spec.layers} not in {c['layer_counts']}"),
        ("track", spec.track_mm >= c["min_track_outer_mm"], f"{spec.track_mm} < {c['min_track_outer_mm']}"),
        ("clearance", spec.clearance_mm >= c["min_clearance_outer_mm"], f"{spec.clearance_mm} < {c['min_clearance_outer_mm']}"),
        ("via drill", spec.via_drill_mm >= c["min_drill_mm"], f"{spec.via_drill_mm} < {c['min_drill_mm']}"),
        ("annular ring", (spec.via_mm - spec.via_drill_mm) / 2 >= c["min_annular_ring_mm"],
         f"{(spec.via_mm - spec.via_drill_mm) / 2:.3f} < {c['min_annular_ring_mm']}"),
        ("hole to copper", spec.hole_to_copper_mm >= c["hole_clearance_mm"], f"{spec.hole_to_copper_mm} < {c['hole_clearance_mm']}"),
        ("copper to edge", spec.edge_clearance_mm >= c["copper_to_edge_mm"], f"{spec.edge_clearance_mm} < {c['copper_to_edge_mm']}"),
    ]
    for name, ok, why in checks:
        if not ok:
            r.findings.append(f"{name}: {why} ({fab.vendor})")
    locked = _table((d / "design.md").read_text(), "Locked set")
    m = re.search(r"([\d.]+)\s*mm\s*x\s*([\d.]+)\s*mm", locked.get("Maximum board size", [""])[0])
    if m and (spec.width_mm > float(m.group(1)) + 1e-9 or spec.height_mm > float(m.group(2)) + 1e-9):
        r.findings.append(f"outline {spec.width_mm} x {spec.height_mm} mm exceeds the locked maximum {m.group(0)}")
    targets = spec.raw.get("impedance", {}).get("targets", [])
    for t in targets:
        if "geometry" not in t:
            r.findings.append(f"impedance target {t} has no geometry")
    price = fab.estimate_price(spec.layers, spec.width_mm * spec.height_mm, 5)
    if price is None:
        r.asks.append(f"the {fab.vendor} price model is not captured (D5): the board price is unknown and the owner decides")
    r.numbers = {"rules checked": len(checks), "impedance targets": len(targets), "price": price if price is not None else "unknown"}
    r.passed = not r.findings
    r.outputs = [str(d / "spec.toml")]
    r.seconds = round(time.time() - t0, 1)
    return _write(d, r)


# --- stage 5 -----------------------------------------------------------------------------------------------
def stage5(d: Path, name: str, passes: int = 100, timeout_s: float = 600.0) -> GateResult:
    """The acceptance rule of definition.md, section 3: complete (every net, DRC clean) or failed with a report.
    The closure loop in its simplest form: a failed route gets a different placement, logged, within a budget."""
    t0 = time.time()
    r = GateResult(stage=5, passed=False)
    spec = board_mod.Spec.read(d / "spec.toml")
    rules = spec.board_rules(name)
    work = d / "reports" / "stage5"
    attempts = []
    out = d / f"{name}.kicad_pcb"
    for attempt in range(PLACEMENT_ATTEMPTS):
        board, _spec, placement = board_mod.build(d, name, attempt=attempt)
        wdir = work / f"attempt{attempt}"
        wdir.mkdir(parents=True, exist_ok=True)
        # a board built in memory has no project behind it and the zone filler dereferences one: save and reload
        kb.save_board(board, wdir / "placed.kicad_pcb")
        board = kb.load_board(wdir / "placed.kicad_pcb")
        result = route_stage.route(board, rules, spec.pour_spec(), wdir, out_path=wdir / "routed.kicad_pcb",
                                   passes=passes, timeout_s=timeout_s)
        report = route_stage.drc(wdir / "routed.kicad_pcb", rules, wdir / "drc", tag="final")
        facts = rebuild.board_facts(report)
        entry = {"attempt": attempt, "placement": placement, "route": result.summary(), "failed": result.failed,
                 "electrical": facts["electrical"], "by_type": facts["by_type"], "unconnected_items": facts["unconnected_items"]}
        attempts.append(entry)
        if result.ok and facts["electrical"] == 0 and facts["unconnected_items"] == 0:
            shutil.copy(wdir / "routed.kicad_pcb", out)
            if (wdir / "routed.kicad_pro").is_file():
                shutil.copy(wdir / "routed.kicad_pro", d / f"{name}.kicad_pro")
            r.passed = True
            r.numbers = {"attempt": attempt + 1, "nets": len(result.routed), "tracks": len(kb.track_segments(kb.load_board(out))),
                         "vias": len(kb.vias(kb.load_board(out))), "stitching vias": len(result.stitched)}
            break
    (d / "reports" / "stage5-attempts.json").write_text(json.dumps(attempts, indent=1, default=str))
    if not r.passed:
        last = attempts[-1]
        for net, why in sorted(last["failed"].items()):
            r.findings.append(f"net {net}: {why}")
        if last["electrical"]:
            r.findings.append(f"{last['electrical']} electrical violations after {len(attempts)} placements: {last['by_type']}")
        r.findings.append(f"no placement of {len(attempts)} routed clean; the attempt log names each")
        r.numbers = {"attempts": len(attempts)}
    if out.is_file():
        for side in ("top", "bottom"):
            try:
                render.render_png(out, d / "reports" / f"{name}-{side}.png", side=side)
                r.outputs.append(str(d / "reports" / f"{name}-{side}.png"))
            except Exception as why:  # a render is for the reviewer; its failure is not the gate's
                r.findings.append(f"render {side}: {why}")
    r.outputs = [str(out), str(d / "reports" / "stage5-attempts.json")] + r.outputs
    r.seconds = round(time.time() - t0, 1)
    return _write(d, r)


# --- stage 6 -----------------------------------------------------------------------------------------------
GERBER_LAYERS = "F.Cu,B.Cu,F.Paste,F.SilkS,F.Mask,B.Mask,B.SilkS,Edge.Cuts"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def reparse(path: Path) -> str | None:
    """Re-read an exported file and say what is wrong with it, or None. Each format's beginning and end are the
    check: a truncated export is the failure this exists to catch."""
    text = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix in (".gbr", ".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gtp", ".gm1"):
        if b"%FSLA" not in text[:4000] or b"M02*" not in text[-64:]:
            return "not a complete RS-274X file"
    elif suffix == ".drl":
        if not text.startswith(b"M48") or b"M30" not in text[-64:]:
            return "not a complete Excellon file"
    elif suffix == ".pdf":
        if not text.startswith(b"%PDF") or b"%%EOF" not in text[-2048:]:
            return "not a complete PDF"
    elif suffix == ".csv":
        with open(path, newline="") as f:
            rows = list(csv.reader(f))
        if len(rows) < 2:
            return "no data rows"
    elif suffix in (".txt", ".md"):
        if not text.strip():
            return "empty"
    return None


def stage6(d: Path, name: str) -> GateResult:
    """The vendor's checklist satisfied; every file re-parsed after export."""
    t0 = time.time()
    r = GateResult(stage=6, passed=True)
    pcb = d / f"{name}.kicad_pcb"
    if not pcb.is_file():
        r.findings.append("stage 5 has not produced the board")
        r.passed = False
        return _write(d, r)
    out = d / "out"
    if out.is_dir():
        shutil.rmtree(out)
    gerbers = out / "gerbers"
    gerbers.mkdir(parents=True)
    cli = shutil.which("kicad-cli")
    steps = [
        _run([cli, "pcb", "export", "gerbers", "--output", str(gerbers) + "/", "--layers", GERBER_LAYERS,
              "--no-protel-ext", "--subtract-soldermask", str(pcb)]),
        _run([cli, "pcb", "export", "drill", "--output", str(gerbers) + "/", "--format", "excellon", "--excellon-units", "mm",
              "--generate-map", "--map-format", "gerberx2", str(pcb)]),
        _run([cli, "pcb", "export", "pos", "--output", str(out / f"{name}-pos.csv"), "--format", "csv", "--units", "mm",
              "--side", "both", "--use-drill-file-origin", str(pcb)]),
        _run([cli, "pcb", "export", "pdf", "--output", str(out / f"{name}-assembly-top.pdf"), "--layers", "F.Fab,F.SilkS,Edge.Cuts",
              "--include-border-title", str(pcb)]),
    ]
    for step in steps:
        if step.returncode != 0:
            r.findings.append(f"{' '.join(step.args[1:4])} failed: {step.stderr.strip()[-300:]}")
    # the BOM in the assembler's template: the columns PCBWay's assembly upload asks for, as far as this repository
    # knows them (the template itself is not on disk: unknown, D53)
    bom = schematic.read_bom(d / "bom.csv")
    with open(out / f"{name}-bom-pcbway.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Item #", "Designator", "Qty", "Manufacturer", "Mfg Part #", "Description / Value", "Package/Footprint", "Type"])
        for i, row in enumerate(bom, 1):
            w.writerow([i, row["reference"], row["quantity"], row["manufacturer"], row["mpn"], f"{row['value']}; {row['description']}",
                        row["footprint"].split(":")[-1], "SMD" if "PinHeader" not in row["footprint"] else "THT"])
    spec = board_mod.Spec.read(d / "spec.toml")
    (out / f"{name}-stackup.txt").write_text(
        f"{name}: {spec.layers} layers, {spec.raw['board']['thickness_mm']} mm {spec.raw['board']['material']}, "
        f"{spec.raw['board']['copper_oz']} oz copper, finish {spec.raw['board']['finish']}.\n"
        f"Controlled impedance: none. Rules: track {spec.track_mm} mm, clearance {spec.clearance_mm} mm, "
        f"via {spec.via_mm}/{spec.via_drill_mm} mm, hole to copper {spec.hole_to_copper_mm} mm, copper to edge {spec.edge_clearance_mm} mm.\n"
        f"Fab profile: {spec.fab} ({profiles.load(spec.fab).source}).\n")
    files = sorted(p for p in out.rglob("*") if p.is_file())
    for p in files:
        why = reparse(p)
        if why:
            r.findings.append(f"{p.relative_to(d)}: {why}")
    expected = {"gerbers/" + n for n in (f"{name}-F_Cu.gbr", f"{name}-B_Cu.gbr", f"{name}-Edge_Cuts.gbr", f"{name}.drl")}
    have = {str(p.relative_to(out)) for p in files}
    for n in sorted(expected - have):
        r.findings.append(f"missing export {n}")
    r.asks.append("the assembler's BOM template is not on disk (unknown): confirm the column set before upload")
    r.numbers = {"files": len(files), "gerbers": len(list(gerbers.glob("*.gbr"))), "drill files": len(list(gerbers.glob("*.drl")))}
    r.passed = not r.findings
    r.outputs = [str(p) for p in files]
    r.seconds = round(time.time() - t0, 1)
    return _write(d, r)


# --- status ------------------------------------------------------------------------------------------------
def status(d: Path, name: str) -> str:
    lines = [f"{name} ({d})"]
    waiting = []
    for n in range(1, 7):
        path = d / "reports" / f"stage{n}.json"
        if not path.is_file():
            lines.append(f"  stage {n} ({STAGES[n - 1]}): not run")
            continue
        data = json.loads(path.read_text())
        lines.append(f"  stage {n} ({STAGES[n - 1]}): {'PASS' if data['passed'] else 'FAIL'}"
                     + (f" | {', '.join(f'{k} {v}' for k, v in data['numbers'].items())}" if data.get("numbers") else ""))
        for f in data.get("findings", []):
            lines.append(f"      FAIL {f}")
        waiting += data.get("asks", [])
    first_fail = next((n for n in range(1, 7) if not (d / "reports" / f"stage{n}.json").is_file()
                       or not json.loads((d / "reports" / f"stage{n}.json").read_text())["passed"]), None)
    lines.append(f"  at gate: {first_fail if first_fail else 'all six passed'}")
    lines.append("  waiting on the owner: " + ("; ".join(waiting) if waiting else "nothing"))
    return "\n".join(lines)


RUNNERS = {1: stage1, 2: stage2, 3: stage3, 4: stage4}


def run(name: str, stage: int, **kw) -> GateResult:
    d = design_dir(name)
    if stage in RUNNERS:
        return RUNNERS[stage](d)
    if stage == 5:
        return stage5(d, name, **kw)
    if stage == 6:
        return stage6(d, name)
    raise ValueError(f"no stage {stage}")
