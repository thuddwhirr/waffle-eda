"""Stage 3: the schematic and its netlist.

Input: `bom.csv` and `design.md`. Output: a KiCad schematic under `kicad/` (one sheet per function group, the
BOM's ``sheet`` column) and `netlist.net`, exported from it by `kicad-cli`. Gate: ERC clean; the netlist
matches the design's connectivity specification one to one; sheets grouped by function (`docs/definition.md`).

The connectivity in `design.md` names blocks and pin names; the BOM maps each block to a reference and a
symbol; the symbol maps each pin name to a number (`kicad/symbols.py`). That resolved table is the
expectation, and the netlist `kicad-cli` exports from the written schematic is what is compared to it, pin by
pin, so the check covers the generator and the files as KiCad reads them.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from waffle_eda.design import stage1_design as s1, stage2_bom as s2
from waffle_eda.design.directory import Design
from waffle_eda.design.gate import GateResult, write_report
from waffle_eda.design.schematic import Schematic
from waffle_eda.kicad import libs
from waffle_eda.kicad.sexp import find, findall, loads, value


def build(design: Design) -> tuple[Schematic, dict[str, set[tuple[str, str]]], set[tuple[str, str]]]:
    """The schematic description from design.md and bom.csv, with the expected netlist (net -> {(ref, pin)})."""
    doc = s1.load(design)
    bom = s2.load(design)
    sch = Schematic(design.name, doc.title)
    by_block = bom.by_block()
    for line in bom.lines:
        sch.part(line.reference, line.symbol, line.value, line.footprint, line.sheet,
                 fields={"MPN": line.mpn, "Manufacturer": line.manufacturer, "Block": line.block}, dnp=line.is_dnp)
    expected: dict[str, set[tuple[str, str]]] = {}
    for net in doc.nets.values():
        expected[net.name] = set()
        for block, pin in net.pins:
            ref = by_block[block].reference
            sch.connect(net.name, ref, pin)
            expected[net.name].add((ref, sch.parts[ref].resolve(pin)))
    unconnected = set()
    for block, pin in doc.unconnected:
        ref = by_block[block].reference
        sch.no_connect(ref, pin)
        unconnected.add((ref, sch.parts[ref].resolve(pin)))
    for interface in doc.interfaces.values():
        for block in interface.blocks:
            sch.note(by_block[block].sheet, f"{interface.name}: {', '.join(interface.signals) or 'no signal'}; position {interface.position}")
    return sch, expected, unconnected


def _cli(*args: str) -> subprocess.CompletedProcess:
    cli = shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("kicad-cli not found")
    return subprocess.run([cli, *args], capture_output=True, text=True, timeout=300)


def export_netlist(schematic: Path, out: Path) -> Path:
    r = _cli("sch", "export", "netlist", "--format", "kicadsexpr", "--output", str(out), str(schematic))
    if r.returncode or not out.is_file():
        raise RuntimeError(f"kicad-cli netlist export failed ({r.returncode}): {r.stderr[-500:] or r.stdout[-500:]}")
    from waffle_eda.design.directory import repo_root
    root = str(repo_root().resolve()) + "/"  # the export names its source files absolutely; the file is committed
    out.write_text(out.read_text().replace(root, ""))
    return out


def run_erc(schematic: Path, out: Path) -> dict:
    r = _cli("sch", "erc", "--format", "json", "--severity-all", "--output", str(out), str(schematic))
    if not out.is_file():
        raise RuntimeError(f"kicad-cli erc failed ({r.returncode}): {r.stderr[-500:] or r.stdout[-500:]}")
    return json.loads(out.read_text())


def erc_violations(report: dict) -> list[dict]:
    out = []
    for sheet in report.get("sheets", []):
        for v in sheet.get("violations", []):
            out.append({"sheet": sheet.get("path", ""), "type": v.get("type"), "severity": v.get("severity"),
                        "description": v.get("description"), "items": [i.get("description") for i in v.get("items", [])]})
    return out


def read_netlist(path: Path) -> dict[str, set[tuple[str, str]]]:
    """Every net of a `kicadsexpr` netlist as {name: {(ref, pin)}}, power symbols and flags left out."""
    doc = loads(path.read_text())
    nets: dict[str, set[tuple[str, str]]] = {}
    for net in findall(find(doc, "nets"), "net"):
        name = str(value(net, "name"))
        nodes = {(str(value(n, "ref")), str(value(n, "pin"))) for n in findall(net, "node")}
        nets[name] = {(r, p) for r, p in nodes if not r.startswith("#")}
    return nets


def netlist_components(path: Path) -> dict[str, dict]:
    doc = loads(path.read_text())
    out = {}
    for comp in findall(find(doc, "components"), "comp"):
        ref = str(value(comp, "ref"))
        out[ref] = {"value": str(value(comp, "value", "")), "footprint": str(value(comp, "footprint", "")),
                    "sheet": str(value(find(comp, "sheetpath") or [], "names", "/")).strip("/")}
    return out


def basename(net: str) -> str:
    """The label's own name: a local label on a sheet is exported as ``/sheet/NAME``."""
    return net.rsplit("/", 1)[-1] if net.startswith("/") else net


def compare(expected: dict[str, set], actual: dict[str, set], unconnected: set) -> list[str]:
    """Every difference between the design's connectivity and the exported netlist, as text; empty when they
    match one to one. A single-pin ``unconnected-...`` net of a flagged pin is the flag, not a difference."""
    out = []
    act = {}
    for name, pins in actual.items():
        if name.startswith("unconnected-") and len(pins) <= 1:
            if pins and next(iter(pins)) not in unconnected:
                out.append(f"pin {next(iter(pins))} is unconnected on the schematic but not in the design")
            continue
        base = basename(name)
        if base in act:
            out.append(f"net {base} appears twice in the netlist ({name})")
        act[base] = pins
    for name in sorted(set(expected) | set(act)):
        e, a = expected.get(name), act.get(name)
        if e is None:
            out.append(f"net {name} is in the netlist and not in the design: {sorted(a)}")
        elif a is None:
            out.append(f"net {name} is in the design and not in the netlist: {sorted(e)}")
        elif e != a:
            out.append(f"net {name}: design {sorted(e)}, netlist {sorted(a)}")
    return out


def render_svg(schematic: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.svg"):
        old.unlink()
    r = _cli("sch", "export", "svg", "--output", str(out_dir), "--no-background-color", str(schematic))
    if r.returncode:
        raise RuntimeError(f"kicad-cli sch export svg failed: {r.stderr[-400:]}")
    return sorted(out_dir.glob("*.svg"))


def export_pdf(schematic: Path, out: Path) -> Path:
    r = _cli("sch", "export", "pdf", "--output", str(out), str(schematic))
    if r.returncode or not out.is_file():
        raise RuntimeError(f"kicad-cli sch export pdf failed: {r.stderr[-400:]}")
    return out


def run(design: Design) -> GateResult:
    t0 = time.time()
    r = GateResult(3, "schematic")
    if libs.available():
        r.fail("KiCad's libraries are on disk", libs.available())
        write_report(r, design.reports)
        return r
    try:
        sch, expected, unconnected = build(design)
    except (KeyError, ValueError) as why:
        r.fail("the design's connectivity resolves on the BOM's symbols", f"{type(why).__name__}: {why}")
        r.seconds = round(time.time() - t0, 1)
        write_report(r, design.reports)
        return r
    problems = sch.problems()
    if not r.check("every pin is on a net or marked unconnected, and every net joins two pins", not problems, "; ".join(problems)):
        r.seconds = round(time.time() - t0, 1)
        write_report(r, design.reports)
        return r
    design.kicad_dir.mkdir(parents=True, exist_ok=True)
    written = sch.render(design.kicad_dir)
    outputs = [design.relative(p) for p in written]
    # ERC clean
    erc = run_erc(design.schematic, design.work / "erc.json") if design.work.mkdir(parents=True, exist_ok=True) is None else {}
    violations = erc_violations(erc)
    errors = [v for v in violations if v["severity"] == "error"]
    warnings = [v for v in violations if v["severity"] != "error"]
    r.check("ERC clean: no error", not errors, "; ".join(f"{v['type']}: {v['description']} {v['items']}" for v in errors) or "0 errors")
    r.check("ERC clean: no warning", not warnings, "; ".join(f"{v['type']}: {v['description']} {v['items']}" for v in warnings) or "0 warnings")
    # the netlist matches the design one to one
    export_netlist(design.schematic, design.netlist)
    outputs.append(design.relative(design.netlist))
    actual = read_netlist(design.netlist)
    diffs = compare(expected, actual, unconnected)
    r.check("the netlist matches the design's connectivity one to one", not diffs, "; ".join(diffs) or
            f"{len(expected)} nets, {sum(len(p) for p in expected.values())} pins")
    comps = netlist_components(design.netlist)
    missing = sorted(set(sch.parts) - set(comps))
    r.check("every part of the BOM is in the netlist with its footprint", not missing and all(comps[p].get("footprint") == sch.parts[p].footprint for p in sch.parts if p in comps),
            f"missing: {missing}" if missing else ", ".join(f"{p} {c['footprint']}" for p, c in sorted(comps.items())))
    # sheets grouped by function
    groups = {p.sheet for p in sch.parts.values()}
    r.check("sheets grouped by function, one sheet per group of the BOM", set(sch.sheets) == groups,
            ", ".join(f"{s}: {sum(p.sheet == s for p in sch.parts.values())} parts" for s in sch.sheets))
    # the render: one PDF of every sheet (the per-sheet SVGs KiCad also exports weigh a megabyte and change with
    # every regeneration, so they are not kept in the design directory)
    pdf = export_pdf(design.schematic, design.kicad_dir / f"{design.name}-schematic.pdf")
    outputs.append(design.relative(pdf))
    r.numbers = {"sheets": len(sch.sheets), "parts": len(sch.parts), "nets": len(expected),
                 "pins": sum(len(p) for p in expected.values()), "unconnected pins": len(unconnected),
                 "erc errors": len(errors), "erc warnings": len(warnings)}
    r.outputs = outputs
    r.next = "stage 4: spec.toml" if r.passed else "fix design.md, bom.csv or the generator and run stage 3 again"
    r.seconds = round(time.time() - t0, 1)
    write_report(r, design.reports)
    return r
