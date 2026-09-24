"""Stage 6: the manufacturing outputs, under `out/`.

Input: the routed board and the BOM. Output: gerbers, drill files, the pick-and-place file, the BOM in the
vendor's columns, the assembly drawing, the stack-up and impedance note, and an IPC-D-356 netlist. Gate: the
vendor's checklist satisfied (`[deliverables]` of the fab profile); every file re-parsed after export
(`docs/definition.md`; `docs/plan.md`: "stage 6 is kicad-cli pcb export plus a re-parse of every file").

Re-parsing means reading each file back as its consumer would and checking it against the board: every
Gerber has its format header, apertures and its end mark; the drill files' hole counts equal the board's
plated and non-plated holes; the position file lists every placed part; the vendor BOM lists every fitted
part; the IPC-D-356 netlist groups the board's pins as the schematic's netlist does; and the board on disk
passes DRC under the specification's rules once more.
"""
from __future__ import annotations

import csv
import re
import shutil
import subprocess
import time
from pathlib import Path

import pcbnew

from waffle_eda.bench import rebuild
from waffle_eda.design import stage2_bom as s2, stage3_schematic as s3, stage4_spec as s4, stage5_layout as s5
from waffle_eda.design.directory import Design
from waffle_eda.design.gate import GateResult, write_report
from waffle_eda.fab import profiles
from waffle_eda.kicad import board as kb

GERBER_LAYERS = ["F.Cu", "B.Cu", "F.Paste", "F.Mask", "B.Mask", "F.SilkS", "B.SilkS", "F.Fab", "Edge.Cuts"]
BOM_COLUMNS = ["Item", "Designator", "Quantity", "Manufacturer", "MPN", "Description", "Package", "DNP"]


def _cli(*args: str) -> subprocess.CompletedProcess:
    cli = shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("kicad-cli not found")
    r = subprocess.run([cli, *args], capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(f"kicad-cli {' '.join(args[:3])} failed ({r.returncode}): {r.stderr[-400:] or r.stdout[-400:]}")
    return r


# --- exports -----------------------------------------------------------------------------------------------
def export_gerbers(board: Path, out_dir: Path, layers: list[str]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.iterdir():  # nothing stale ships: a run before this one used other extensions
        if old.is_file():
            old.unlink()
    _cli("pcb", "export", "gerbers", "--output", str(out_dir) + "/", "--layers", ",".join(layers),
         "--subtract-soldermask", "--use-drill-file-origin", "--no-protel-ext", str(board))
    return sorted(out_dir.glob("*.gbr"))


def export_drill(board: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.iterdir():
        if old.is_file():
            old.unlink()
    _cli("pcb", "export", "drill", "--output", str(out_dir) + "/", "--format", "excellon", "--excellon-separate-th",
         "--excellon-units", "mm", "--drill-origin", "absolute", "--generate-map", "--map-format", "pdf", str(board))
    return sorted(out_dir.glob("*.drl"))


def export_position(board: Path, out: Path) -> Path:
    _cli("pcb", "export", "pos", "--output", str(out), "--format", "csv", "--units", "mm", "--side", "both",
         "--exclude-dnp", str(board))
    return out


def export_assembly_drawing(board: Path, out: Path) -> Path:
    _cli("pcb", "export", "pdf", "--output", str(out), "--layers", "F.Fab,F.SilkS,Edge.Cuts,F.CrtYd",
         "--include-border-title", str(board))
    return out


def export_ipc356(board: Path, out: Path) -> Path:
    _cli("pcb", "export", "ipcd356", "--output", str(out), str(board))
    return out


def write_vendor_bom(bom: s2.Bom, components: dict[str, dict], out: Path) -> list[dict]:
    """One line per fitted part, the vendor's columns (fab profile `deliverables.bom`), grouped by part."""
    groups: dict[tuple, list[str]] = {}
    for line in sorted(bom.lines, key=lambda l: l.reference):
        if line.reference not in components or line.mpn.strip().lower() in ("none", ""):
            continue
        key = (line.mpn, line.manufacturer, line.value, line.footprint, "yes" if line.is_dnp else "no")
        groups.setdefault(key, []).append(line.reference)
    rows = []
    for i, ((mpn, mfr, value, fp, dnp), refs) in enumerate(groups.items(), 1):
        rows.append({"Item": i, "Designator": ",".join(refs), "Quantity": len(refs), "Manufacturer": mfr, "MPN": mpn,
                     "Description": value, "Package": fp.split(":", 1)[-1], "DNP": dnp})
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=BOM_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return rows


def write_stackup_note(spec: dict, fab: profiles.FabProfile, out: Path) -> Path:
    b, st = spec["board"], spec["stackup"]
    lines = [f"# Stack-up and impedance note: {spec['design']['name']}", "",
             f"Fab: {fab.vendor} ({fab.name}); quantity {spec['design']['quantity']}; assembler {spec['design'].get('assembler', '')}.", "",
             "| Item | Value |", "|---|---|",
             f"| copper layers | {b['layers']} ({', '.join(b['copper_layers'])}) |",
             f"| finished thickness | {b['thickness_mm']} mm |",
             f"| outer copper | {b['outer_copper_oz']} oz |",
             f"| material | {b['material']} |",
             f"| surface finish | {b['surface_finish']} |",
             f"| stack-up | {st.get('name')}: {st.get('note', '')} |",
             f"| vias | {spec['vias']['type']}, {spec['rules']['via_diameter']} / {spec['rules']['via_drill']} mm |",
             f"| smallest track / clearance | {spec['rules']['track_width']} / {spec['rules']['clearance']} mm |",
             f"| outline | {spec['outline']['width_mm']} x {spec['outline']['height_mm']} mm |",
             "", "## Impedance", "",
             (", ".join(str(t) for t in spec["impedance"]["targets"]) or spec["impedance"]["note"]) + ".", ""]
    out.write_text("\n".join(lines))
    return out


# --- re-parsing --------------------------------------------------------------------------------------------
def parse_gerber(path: Path) -> dict:
    text = path.read_text(errors="replace")
    return {"format": bool(re.search(r"%FSLAX\d\dY\d\d\*%", text)), "units": bool(re.search(r"%MO(MM|IN)\*%", text)),
            "apertures": len(re.findall(r"%ADD\d+", text)), "draws": len(re.findall(r"D0[13]\*", text)),  # strokes and flashes
            "end": text.rstrip().endswith("M02*")}


def parse_excellon(path: Path) -> dict:
    text = path.read_text(errors="replace")
    return {"header": text.startswith("M48"), "metric": "METRIC" in text, "tools": len(re.findall(r"^T\d+C", text, re.M)),
            "hits": len(re.findall(r"^X-?[\d.]+Y-?[\d.]+$", text, re.M)), "end": text.rstrip().endswith("M30")}


def parse_position(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def parse_ipc356(path: Path) -> dict[str, set[tuple[str, str]]]:
    """Net -> {(ref, pin)} from the 317 (through) and 327 (surface) records."""
    nets: dict[str, set[tuple[str, str]]] = {}
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith(("317", "327")):
            continue
        net = line[3:17].strip()
        ref = line[20:26].strip()
        pin = line[27:31].strip()
        if net and ref and not ref.startswith("VIA"):
            nets.setdefault(net, set()).add((ref, pin))
    return {n: pins for n, pins in nets.items() if len(pins) > 1}  # a lone pad is an unconnected pin, not a net


def board_holes(board) -> tuple[int, int]:
    """Plated holes (pads with a drill and copper, plus vias) and non-plated ones."""
    plated = len(kb.vias(board))
    non_plated = 0
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            d = pad.GetDrillSize()
            if d.x <= 0:
                continue
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                non_plated += 1
            else:
                plated += 1
    return plated, non_plated


def run(design: Design) -> GateResult:
    t0 = time.time()
    r = GateResult(6, "outputs")
    if not design.board.is_file():
        r.fail("the routed board exists", f"{design.board} is missing")
        r.seconds = round(time.time() - t0, 1)
        write_report(r, design.reports)
        return r
    spec = s4.load(design)
    bom = s2.load(design)
    fab = profiles.load(spec["design"]["fab"])
    board = kb.load_board(design.board)
    out = design.out
    out.mkdir(parents=True, exist_ok=True)
    name = design.name
    produced: dict[str, list[Path]] = {}
    # the board on disk passes DRC under the rules once more: what ships is what was checked
    rules = s5.rules_for(spec, name, len(rebuild.routable_nets(board)))
    facts = rebuild.drc_under_rules(design.board, rules.values(), design.work / "ship", tag="ship")
    r.check("the shipped board is DRC clean under the specification's rules", facts["electrical"] == 0 and facts["unconnected_items"] == 0,
            f"electrical {facts['electrical']} {facts['by_type'] or ''}, unconnected items {facts['unconnected_items']}")
    # gerbers
    gerbers = export_gerbers(design.board, out / "gerbers", GERBER_LAYERS)
    produced["gerbers"] = gerbers
    parsed = {g.name: parse_gerber(g) for g in gerbers}
    bad = [n for n, p in parsed.items() if not (p["format"] and p["units"] and p["end"] and p["apertures"] > 0)]
    copper = [g for g in gerbers if g.name.endswith(("F_Cu.gbr", "B_Cu.gbr", "Edge_Cuts.gbr"))]
    empty = [g.name for g in copper if parsed[g.name]["draws"] == 0]
    r.check("every Gerber re-parsed: format, units, apertures, end mark; copper and outline draw something",
            len(gerbers) == len(GERBER_LAYERS) and not bad and not empty,
            f"{len(gerbers)} of {len(GERBER_LAYERS)} layers; bad {bad}; empty {empty}" if (bad or empty or len(gerbers) != len(GERBER_LAYERS))
            else ", ".join(f"{g.name} ({parsed[g.name]['draws']} draws)" for g in gerbers))
    # drill
    drills = export_drill(design.board, out / "drill")
    produced["drill"] = drills
    plated, non_plated = board_holes(board)
    hits = {d.name: parse_excellon(d) for d in drills}
    pth = sum(h["hits"] for n, h in hits.items() if "NPTH" not in n)
    npth = sum(h["hits"] for n, h in hits.items() if "NPTH" in n)
    ok_drill = all(h["header"] and h["metric"] and h["end"] for h in hits.values()) and pth == plated and npth == non_plated
    r.check("the drill files re-parsed: Excellon headers, and hole counts equal the board's",
            ok_drill, f"plated {pth} of {plated}, non-plated {npth} of {non_plated}; files {[d.name for d in drills]}")
    # position
    pos = export_position(design.board, out / f"{name}-positions.csv")
    produced["position"] = [pos]
    rows = parse_position(pos)
    expected_pos = sorted(fp.GetReference() for fp in board.GetFootprints()
                          if not (fp.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_POS_FILES) and not (fp.GetAttributes() & pcbnew.FP_DNP))
    got_pos = sorted(row.get("Ref", "") for row in rows)
    r.check("the position file lists every placed part with its side and rotation", got_pos == expected_pos and
            all(row.get("Side") in ("top", "bottom") and row.get("Rot") not in (None, "") for row in rows),
            f"{got_pos} against the board's {expected_pos}")
    # vendor BOM
    comps = s3.netlist_components(design.netlist)
    vendor_bom = out / f"{name}-bom-{fab.name}.csv"
    bom_rows = write_vendor_bom(bom, comps, vendor_bom)
    produced["bom"] = [vendor_bom]
    listed = sorted(ref for row in bom_rows for ref in row["Designator"].split(","))
    fitted = sorted(l.reference for l in bom.lines if l.mpn.strip().lower() not in ("none", "") and l.reference in comps)
    with vendor_bom.open(newline="") as f:
        back = list(csv.DictReader(f))
    r.check("the vendor BOM re-parsed: every fitted part listed once, the vendor's columns", listed == fitted and
            [row["Designator"] for row in back] == [row["Designator"] for row in bom_rows] and list(back[0].keys()) == BOM_COLUMNS if back else False,
            f"{len(bom_rows)} lines for {len(fitted)} parts: {fitted}")
    # assembly drawing
    drawing = export_assembly_drawing(design.board, out / f"{name}-assembly.pdf")
    produced["assembly_drawing"] = [drawing]
    head = drawing.read_bytes()[:8]
    tail = drawing.read_bytes()[-64:]
    r.check("the assembly drawing re-parsed as a PDF", head.startswith(b"%PDF") and b"%%EOF" in tail, f"{drawing.name}, {drawing.stat().st_size} bytes")
    # stack-up note
    note = write_stackup_note(spec, fab, out / f"{name}-stackup.md")
    produced["stackup_note"] = [note]
    text = note.read_text()
    r.check("the stack-up note carries the layer count, thickness, copper, finish and impedance", all(k in text for k in
            (str(spec["board"]["layers"]), str(spec["board"]["thickness_mm"]), spec["board"]["surface_finish"], "Impedance")), note.name)
    # IPC-D-356 netlist against the schematic's
    ipc = export_ipc356(design.board, out / f"{name}.d356")
    produced["netlist"] = [ipc]
    board_nets = parse_ipc356(ipc)
    sch_nets = {n: pins for n, pins in s3.read_netlist(design.netlist).items() if not (n.startswith("unconnected-") and len(pins) <= 1)}
    pins_by_net_sch = {frozenset(p) for p in sch_nets.values()}
    pins_by_net_board = {frozenset(p) for p in board_nets.values()}
    r.check("the IPC-D-356 netlist groups the board's pins exactly as the schematic's netlist does",
            pins_by_net_sch == pins_by_net_board,
            f"{len(board_nets)} board nets against {len(sch_nets)} schematic nets" + ("" if pins_by_net_sch == pins_by_net_board else
            f"; only on the board {[sorted(p) for p in pins_by_net_board - pins_by_net_sch]}; only in the schematic {[sorted(p) for p in pins_by_net_sch - pins_by_net_board]}"))
    # the vendor's checklist
    missing = [k for k in fab.__dict__.get("deliverables", {}) or {} if k not in produced]
    deliverables = _deliverables(fab)
    missing = [k for k in deliverables if not produced.get(k) or not all(p.is_file() and p.stat().st_size > 0 for p in produced[k])]
    r.check("the vendor's checklist satisfied: every deliverable of the fab profile present and non-empty", not missing,
            f"missing {missing}" if missing else "; ".join(f"{k}: {deliverables[k]}" for k in deliverables))
    r.numbers = {"gerber layers": len(gerbers), "plated holes": plated, "non-plated holes": non_plated,
                 "placed parts": len(rows), "bom lines": len(bom_rows), "board nets": len(board_nets)}
    r.outputs = [design.relative(p) for ps in produced.values() for p in ps]
    r.next = ("the owner reviews out/ (the assembly drawing, the layout render under reports/, the BOM) and the "
              "escalations of stages 1, 2 and 4; a fab order needs the prices") if r.passed else "fix the failing export and run stage 6 again"
    r.seconds = round(time.time() - t0, 1)
    write_report(r, design.reports)
    return r


def _deliverables(fab: profiles.FabProfile) -> dict:
    import tomllib
    data = tomllib.loads((profiles.PROFILES_DIR / f"{fab.name}.toml").read_text())
    return data.get("deliverables", {})
