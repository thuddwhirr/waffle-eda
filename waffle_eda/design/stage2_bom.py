"""Stage 2: the bill of materials, `bom.csv`.

Input: the design document, the cost ceiling, the fab and assembler. Output: one line per block of the design
with the part's value, symbol and footprint (KiCad's libraries, `kicad/libs.py`), manufacturer part number,
alternates, price, stock, lead time and datasheet reference. Gate: cost within the ceiling; every part has a
symbol, a footprint and a datasheet reference; long-lead parts flagged (`docs/definition.md` section 2).

Facts from outside the repository (a price, a stock figure, a lead time, a part number no datasheet on disk
confirms) come from the owner or are marked ``unknown`` (CLAUDE.md); an unknown escalates the criterion that
needs it rather than failing the gate. A ``generic`` part (a 0603 resistor) is specified by its value column
and any manufacturer's part meets it; a ``specific`` part names its manufacturer part number and datasheet.
"""
from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from waffle_eda.design import stage1_design as s1
from waffle_eda.design.directory import Design
from waffle_eda.design.gate import GateResult, write_report
from waffle_eda.kicad import libs, symbols

COLUMNS = ("block", "reference", "value", "kind", "symbol", "footprint", "mpn", "manufacturer", "alternates",
           "datasheet", "price", "stock", "lead_time", "sheet", "dnp", "notes")
KINDS = ("specific", "generic")
LONG_LEAD_WEEKS = 8  # a stated lead time at or over this is flagged


@dataclass(frozen=True)
class BomLine:
    block: str
    reference: str
    value: str
    kind: str
    symbol: str
    footprint: str
    mpn: str = ""
    manufacturer: str = ""
    alternates: str = ""
    datasheet: str = ""
    price: str = ""
    stock: str = ""
    lead_time: str = ""
    sheet: str = ""
    dnp: str = "no"
    notes: str = ""

    @property
    def price_each(self) -> float | None:
        m = re.match(r"\s*([\d.]+)", self.price)
        return float(m.group(1)) if m and "unknown" not in self.price.lower() else None

    @property
    def lead_weeks(self) -> float | None:
        m = re.search(r"([\d.]+)\s*(week|wk|w)", self.lead_time.lower())
        if m:
            return float(m.group(1))
        m = re.search(r"([\d.]+)\s*(day|d)\b", self.lead_time.lower())
        return float(m.group(1)) / 7 if m else None

    @property
    def is_dnp(self) -> bool:
        return self.dnp.strip().lower() in ("yes", "y", "true", "1", "dnp")

    @property
    def alternate_symbols(self) -> list[str]:
        """``Lib:Name`` ids named in the alternates column, in parentheses or bare."""
        return re.findall(r"([A-Za-z0-9_.-]+:[A-Za-z0-9_.+-]+)", self.alternates)


@dataclass
class Bom:
    lines: list[BomLine]
    problems: list[str] = field(default_factory=list)

    def by_block(self) -> dict[str, BomLine]:
        return {l.block: l for l in self.lines}

    def by_reference(self) -> dict[str, BomLine]:
        return {l.reference: l for l in self.lines}


def load(design: Design) -> Bom:
    problems: list[str] = []
    lines: list[BomLine] = []
    with design.bom_csv.open(newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            problems.append(f"bom.csv lacks the columns {missing}")
        for row in reader:
            row = {k: (v or "").strip() for k, v in row.items() if k}
            try:
                lines.append(BomLine(**{c: row.get(c, "") for c in COLUMNS}))
            except TypeError as why:
                problems.append(f"row {row}: {why}")
    return Bom(lines, problems)


def _short(path) -> str:
    """A path inside this repository, relative to it (the report is committed)."""
    from waffle_eda.design.directory import repo_root
    try:
        return str(Path(path).resolve().relative_to(repo_root().resolve()))
    except ValueError:
        return str(path)


def _pins_named(sym) -> set[str]:
    return {p["name"] for p in symbols.pins(sym)} | {p["number"] for p in symbols.pins(sym)}


def _pin_set(sym) -> set[tuple[str, str]]:
    return {(p["number"], p["name"]) for p in symbols.pins(sym)}


def run(design: Design) -> GateResult:
    """Stage 2's gate on `bom.csv` against `design.md` and the libraries; writes `reports/stage2-bom.md`."""
    t0 = time.time()
    r = GateResult(2, "bom")
    doc = s1.load(design)
    if not design.bom_csv.is_file():
        r.fail("the BOM exists", f"{design.bom_csv} is missing")
        r.seconds = round(time.time() - t0, 1)
        write_report(r, design.reports)
        return r
    bom = load(design)
    r.check("the BOM parses", not bom.problems, "; ".join(bom.problems) or f"{len(bom.lines)} lines")
    blocks = bom.by_block()
    missing = sorted(set(doc.blocks) - set(blocks))
    extra = sorted(set(blocks) - set(doc.blocks))
    dup = sorted({l.block for l in bom.lines if sum(m.block == l.block for m in bom.lines) > 1})
    r.check("one part per block of the design", not missing and not extra and not dup,
            (f"blocks without a part: {missing}; " if missing else "") + (f"parts for no block: {extra}; " if extra else "")
            + (f"blocks listed twice: {dup}" if dup else "") or f"{len(blocks)} blocks")
    refs = [l.reference for l in bom.lines]
    bad = [x for x in refs if not re.fullmatch(r"[A-Z]+[0-9]+", x)]
    r.check("references are unique and well formed", len(set(refs)) == len(refs) and not bad,
            f"malformed: {bad}; duplicates: {sorted({x for x in refs if refs.count(x) > 1})}" if bad or len(set(refs)) != len(refs) else ", ".join(refs))
    kinds = [l.reference for l in bom.lines if l.kind not in KINDS]
    r.check("every part is 'specific' or 'generic'", not kinds, f"{kinds}" if kinds else "")
    if libs.available():
        r.fail("every part has a symbol and a footprint in KiCad's libraries", libs.available())
    else:
        no_sym = [f"{l.reference} {l.symbol}" for l in bom.lines if not libs.has_symbol(l.symbol)]
        no_fp = [f"{l.reference} {l.footprint}" for l in bom.lines if not libs.has_footprint(l.footprint)]
        r.check("every part has a symbol in KiCad's libraries", not no_sym, "; ".join(no_sym) or f"{len(bom.lines)} symbols found under {_short(libs.symbols_dir())}")
        r.check("every part has a footprint in KiCad's libraries", not no_fp, "; ".join(no_fp) or f"{len(bom.lines)} footprints found under {_short(libs.footprints_dir())}")
        # the symbol carries the pins the design names on the block, so stage 3 can resolve them
        unresolved = []
        for block, line in blocks.items():
            if not libs.has_symbol(line.symbol):
                continue
            names = _pins_named(symbols.get_symbol(line.symbol))
            for b, pin in list(doc.pin_refs()) + list(doc.unconnected):
                if b == block and pin not in names:
                    unresolved.append(f"{block}.{pin} not on {line.symbol} (pins {sorted(names)})")
        r.check("every pin the design names is on the block's symbol", not unresolved, "; ".join(unresolved))
        # an alternate named by symbol has the same pins and footprint as the part it replaces
        alt_bad = []
        for line in bom.lines:
            if not libs.has_symbol(line.symbol):
                continue  # already failed above
            for alt in line.alternate_symbols:
                if not libs.has_symbol(alt):
                    alt_bad.append(f"{line.reference}: alternate {alt} not in the library")
                    continue
                a, b = symbols.get_symbol(alt), symbols.get_symbol(line.symbol)
                if _pin_set(a) != _pin_set(b):
                    alt_bad.append(f"{line.reference}: alternate {alt} has different pins")
                alt_fp = symbols.property_value(a, "Footprint")
                if alt_fp and alt_fp != line.footprint:
                    alt_bad.append(f"{line.reference}: alternate {alt} wants footprint {alt_fp}, not {line.footprint}")
        r.check("every alternate named by symbol has the same pins and footprint", not alt_bad, "; ".join(alt_bad))
    no_ds = [l.reference for l in bom.lines if l.kind == "specific" and not (l.datasheet.startswith("http") or Path(l.datasheet).suffix)]
    no_spec = [l.reference for l in bom.lines if l.kind == "generic" and not l.value]
    r.check("every specific part has a datasheet reference and every generic part a specification", not no_ds and not no_spec,
            (f"no datasheet: {no_ds}; " if no_ds else "") + (f"no value: {no_spec}" if no_spec else "") or "")
    no_mpn = [l.reference for l in bom.lines if l.kind == "specific" and (not l.mpn or "unknown" in l.mpn.lower())]
    if no_mpn:
        r.escalate("every specific part has a manufacturer part number", f"unknown for {no_mpn}: the owner supplies it or the part changes")
    else:
        r.ok("every specific part has a manufacturer part number", ", ".join(l.mpn for l in bom.lines if l.kind == "specific"))
    # cost within the ceiling
    unknown_price = [l.reference for l in bom.lines if l.price_each is None and not l.is_dnp]
    known = sum((l.price_each or 0.0) for l in bom.lines if not l.is_dnp)
    if unknown_price or doc.cost_ceiling is None:
        r.escalate("cost within the ceiling", (f"no price for {unknown_price}; " if unknown_price else "") +
                   (f"known parts {known:.2f}; " if known else "") + (f"ceiling {doc.locked.get('cost', '')}" if doc.cost_ceiling is None else f"ceiling {doc.cost_ceiling}")
                   + ": prices come from the owner or a captured quote (definition.md section 4)")
    else:
        r.check("cost within the ceiling", known <= doc.cost_ceiling, f"parts {known:.2f} of {doc.cost_ceiling:.2f}")
    # long-lead parts flagged
    unknown_lead = [l.reference for l in bom.lines if l.lead_weeks is None and not l.is_dnp]
    long_lead = [l.reference for l in bom.lines if (l.lead_weeks or 0) >= LONG_LEAD_WEEKS]
    if unknown_lead:
        r.escalate("long-lead parts flagged", f"lead time unknown for {unknown_lead}" + (f"; long lead: {long_lead}" if long_lead else "")
                   + ": stock and lead time come from the assembler's quote")
    else:
        r.ok("long-lead parts flagged", f"long lead ({LONG_LEAD_WEEKS} weeks or more): {long_lead or 'none'}")
    no_sheet = [l.reference for l in bom.lines if not l.sheet]
    r.check("every part names its schematic sheet (function group)", not no_sheet, f"{no_sheet}" if no_sheet else ", ".join(sorted({l.sheet for l in bom.lines})))
    r.numbers = {"parts": len(bom.lines), "specific": sum(l.kind == "specific" for l in bom.lines),
                 "generic": sum(l.kind == "generic" for l in bom.lines), "dnp": sum(l.is_dnp for l in bom.lines),
                 "known cost": round(known, 2)}
    r.outputs = [design.relative(design.bom_csv)]
    r.next = "stage 3: the schematic and its netlist" if r.passed else "fix bom.csv and run stage 2 again"
    r.seconds = round(time.time() - t0, 1)
    write_report(r, design.reports)
    return r
