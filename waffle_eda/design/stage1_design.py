"""Stage 1: the design document, `design.md`.

Input: the owner's feature description, cost ceiling, fab and assembler choice. Output: the document with the
capabilities, the interfaces with a position each (an edge, or free), the size limit, the connectivity by block
and pin name, and the locked set (`docs/definition.md` sections 2 and 4). Gate: owner review; every locked
constraint explicit; every interface has a stated position or is marked free.

The document is Markdown a person reads and edits; the tool reads its pipe tables (`markdown.py`). The
sections it reads: **Blocks** (block, function, notes), **Interfaces** (interface, block, signals, position),
**Connectivity** (net, pins as ``block.pin``) with an ``Unconnected:`` line, **Locked** (size, cost,
interfaces, features), **Fab and assembly** (fab profile, assembler, quantity) and **Review** (owner review:
pending or accepted). Stage 2 maps each block to a part; stage 3 resolves the pin names on that part's symbol.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from waffle_eda.design import markdown as md
from waffle_eda.design.directory import Design
from waffle_eda.design.gate import GateResult, write_report
from waffle_eda.fab import profiles

EDGES = ("left", "right", "top", "bottom")
LOCKED = ("size", "cost", "interfaces", "features")  # definition.md section 4: only the owner changes these


@dataclass(frozen=True)
class Block:
    name: str
    function: str
    notes: str = ""


@dataclass(frozen=True)
class Position:
    """Where an interface sits: ``free``, or an edge, centred along it or offset from one of its ends."""
    edge: str | None = None  # None: free
    along: str = "centred"  # "centred" or "<n> mm from <end>"

    @property
    def free(self) -> bool:
        return self.edge is None

    def __str__(self) -> str:
        return "free" if self.free else f"{self.edge} edge, {self.along}"


def parse_position(text: str) -> Position:
    t = text.strip().lower()
    if t in ("", "free", "-"):
        return Position()
    m = re.match(r"(left|right|top|bottom)\s+edge(?:\s*,\s*(.*))?$", t)
    if not m:
        raise ValueError(f"position {text!r}: say 'free' or '<left|right|top|bottom> edge[, centred | <n> mm from <end>]'")
    along = (m.group(2) or "centred").strip()
    if along != "centred" and not re.match(r"[\d.]+\s*mm\s+from\s+(left|right|top|bottom)$", along):
        raise ValueError(f"position {text!r}: after the edge say 'centred' or '<n> mm from <end>'")
    return Position(m.group(1), along)


@dataclass(frozen=True)
class Interface:
    name: str
    blocks: tuple[str, ...]
    signals: tuple[str, ...]
    position: Position


@dataclass(frozen=True)
class Net:
    name: str
    pins: tuple[tuple[str, str], ...]  # (block, pin name or number)


@dataclass
class DesignDoc:
    title: str
    blocks: dict[str, Block]
    interfaces: dict[str, Interface]
    nets: dict[str, Net]
    unconnected: tuple[tuple[str, str], ...]
    locked: dict[str, str]
    fab: dict[str, str]
    review: str
    capabilities: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # what could not be parsed; the gate fails on any

    @property
    def max_size_mm(self) -> tuple[float, float] | None:
        m = re.search(r"([\d.]+)\s*x\s*([\d.]+)\s*mm", self.locked.get("size", ""))
        return (float(m.group(1)), float(m.group(2))) if m else None

    @property
    def cost_ceiling(self) -> float | None:
        """The ceiling as a number, or None when it is unknown or not a number."""
        m = re.search(r"([\d.]+)", self.locked.get("cost", ""))
        return float(m.group(1)) if m and "unknown" not in self.locked.get("cost", "").lower() else None

    @property
    def fab_profile(self) -> str:
        return self.fab.get("fab profile", "")

    @property
    def quantity(self) -> int:
        m = re.search(r"\d+", self.fab.get("quantity", ""))
        return int(m.group(0)) if m else 1

    @property
    def reviewed(self) -> bool:
        return self.review.lower().startswith("accepted")

    def pin_refs(self) -> set[tuple[str, str]]:
        return {p for n in self.nets.values() for p in n.pins}


def _pin(token: str) -> tuple[str, str]:
    if "." not in token:
        raise ValueError(f"pin {token!r}: write block.pin")
    block, pin = token.split(".", 1)
    return block, pin


def parse(text: str) -> DesignDoc:
    secs = md.sections(text)
    problems: list[str] = []

    def section(name: str) -> str:
        for k, v in secs.items():
            if k.lower() == name:
                return v
        problems.append(f"no '## {name.title()}' section")
        return ""

    blocks: dict[str, Block] = {}
    for row in md.first_table(section("blocks")):
        for name in md.split_list(row.get("block", "")):
            blocks[name] = Block(name, row.get("function", ""), row.get("notes", ""))
    interfaces: dict[str, Interface] = {}
    for row in md.first_table(section("interfaces")):
        name = row.get("interface", "")
        try:
            pos = parse_position(row.get("position", ""))
        except ValueError as why:
            problems.append(f"interface {name}: {why}")
            pos = Position()
        interfaces[name] = Interface(name, tuple(md.split_list(row.get("block", ""))),
                                     tuple(md.split_list(row.get("signals", ""))), pos)
    nets: dict[str, Net] = {}
    conn = section("connectivity")
    for row in md.first_table(conn):
        name = row.get("net", "")
        try:
            nets[name] = Net(name, tuple(_pin(t) for t in md.split_list(row.get("pins", ""))))
        except ValueError as why:
            problems.append(f"net {name}: {why}")
    unconnected: list[tuple[str, str]] = []
    for line in conn.splitlines():
        if line.lower().startswith("unconnected:"):
            try:
                unconnected += [_pin(t) for t in md.split_list(line.split(":", 1)[1].rstrip("."))]
            except ValueError as why:
                problems.append(str(why))
    caps = md.first_table(section("capabilities"))
    return DesignDoc(title=md.title(text), blocks=blocks, interfaces=interfaces, nets=nets,
                     unconnected=tuple(unconnected), locked=md.key_values(section("locked")),
                     fab=md.key_values(section("fab and assembly")), review=md.key_values(section("review")).get("owner review", ""),
                     capabilities=caps, problems=problems)


def load(design: Design) -> DesignDoc:
    return parse(design.design_md.read_text())


def run(design: Design) -> GateResult:
    """Stage 1's gate on `design.md`; writes `reports/stage1-design.md`."""
    t0 = time.time()
    r = GateResult(1, "design")
    if not design.design_md.is_file():
        r.fail("the design document exists", f"{design.design_md} is missing")
        r.seconds = round(time.time() - t0, 1)
        write_report(r, design.reports)
        return r
    doc = load(design)
    r.check("the document parses", not doc.problems, "; ".join(doc.problems) or f"{doc.title!r}")
    # every locked constraint explicit
    missing = [k for k in LOCKED if not doc.locked.get(k)]
    r.check("every locked constraint is explicit (size, cost, interfaces, features)", not missing,
            f"missing: {missing}" if missing else ", ".join(f"{k}: {doc.locked[k]}" for k in LOCKED))
    r.check("the size limit is a number", doc.max_size_mm is not None, doc.locked.get("size", ""))
    if doc.cost_ceiling is None:
        r.escalate("the cost ceiling", f"{doc.locked.get('cost', '') or 'not stated'}: until a ceiling and prices are "
                                       "captured, every cost decision escalates (definition.md section 4)")
    else:
        r.ok("the cost ceiling is a number", doc.locked["cost"])
    # every interface has a stated position or is marked free
    r.check("every interface has a stated position or is marked free", bool(doc.interfaces) and
            all(i.position is not None for i in doc.interfaces.values()),
            "; ".join(f"{i.name}: {i.position}" for i in doc.interfaces.values()) or "no interfaces")
    fixed = [i.name for i in doc.interfaces.values() if not i.position.free]
    unnamed = [n for n in fixed if n not in doc.locked.get("interfaces", "")]
    r.check("every positioned interface is named in the locked set", not unnamed,
            f"not named under 'interfaces' in Locked: {unnamed}" if unnamed else ", ".join(fixed) or "none positioned")
    # blocks, interfaces and connectivity agree
    used = {b for i in doc.interfaces.values() for b in i.blocks} | {b for b, _p in doc.pin_refs()} | {b for b, _p in doc.unconnected}
    unknown = sorted(used - set(doc.blocks))
    idle = sorted(set(doc.blocks) - used)
    r.check("every block the interfaces and nets name is in Blocks, and every block is used", not unknown and not idle,
            (f"not in Blocks: {unknown}; " if unknown else "") + (f"unused: {idle}" if idle else "") or f"{len(doc.blocks)} blocks")
    short = [n.name for n in doc.nets.values() if len(n.pins) < 2]
    r.check("every net joins at least two pins", bool(doc.nets) and not short, f"single-pin nets: {short}" if short else f"{len(doc.nets)} nets, {len(doc.pin_refs())} pins")
    twice = sorted({p for n in doc.nets.values() for p in n.pins if sum(p in m.pins for m in doc.nets.values()) > 1})
    r.check("no pin is on two nets", not twice, f"{twice}" if twice else "")
    both = sorted(set(doc.unconnected) & doc.pin_refs())
    r.check("a pin marked unconnected is on no net", not both, f"{both}" if both else "")
    r.check("the fab profile exists", doc.fab_profile in profiles.available(), f"{doc.fab_profile!r}; available {profiles.available()}")
    if doc.reviewed:
        r.ok("owner review", doc.review)
    else:
        r.escalate("owner review", f"'{doc.review or 'pending'}': the owner reads design.md and sets 'owner review' to "
                                   "'accepted <date>' (an edit to the file is the owner's input)")
    r.numbers = {"blocks": len(doc.blocks), "interfaces": len(doc.interfaces), "nets": len(doc.nets),
                 "pins": len(doc.pin_refs()), "max size mm": doc.max_size_mm}
    r.outputs = [design.relative(design.design_md)]
    r.next = "stage 2: bom.csv, one part per block" if r.passed else "fix design.md and run stage 1 again"
    r.seconds = round(time.time() - t0, 1)
    write_report(r, design.reports)
    return r
