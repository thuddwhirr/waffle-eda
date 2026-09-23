"""Stage 3: a KiCad 9 schematic from the BOM and the connectivity specification, and the checks on it.

Adapted from `salvage/waffle-fpga/hw/tools/gen_sch.py` (D4) to the stock libraries and one sheet per design:
every symbol sits on the grid, every connected pin gets a short wire stub ending in a global label (signals)
or a power symbol (the supply and ground nets), every unconnected pin a no-connect flag. The nets are therefore
defined by label names alone, which is what makes the netlist `kicad-cli` exports comparable, pin by pin, with
the specification the design document carries. A human reads it as one sheet titled by function, with the
parts in BOM order.

The checks are the gate of stage 3 (definition.md): ERC clean, and the exported netlist equal to the
specification one to one.
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import tomllib
import uuid
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from waffle_eda.sch import symlib
from waffle_eda.sch.sexp import Sym, dumps, find, findall, loads

GRID = 2.54
PAPERS = [("A4", 297, 210), ("A3", 420, 297), ("A2", 594, 420)]
GENERATOR = "waffle_eda"


def _u() -> str:
    return str(uuid.uuid4())


@dataclass
class Part:
    reference: str
    lib_id: str
    value: str
    footprint: str
    datasheet: str
    sym: list = field(repr=False)
    pins: list = field(default_factory=list, repr=False)

    @property
    def is_power(self) -> bool:
        return bool(find(self.sym, "power"))


@dataclass
class Connectivity:
    name: str
    supply: str
    ground: str
    nets: dict[str, list[tuple[str, str]]]  # net -> [(reference, pin number)]
    no_connect: set[tuple[str, str]]

    @property
    def power_nets(self) -> set[str]:
        return {self.supply, self.ground}


def read_connectivity(path: Path) -> Connectivity:
    data = tomllib.loads(path.read_text())
    nets = {net: [tuple(p.rsplit(".", 1)) for p in pins] for net, pins in data["nets"].items()}
    nc = {tuple(p.rsplit(".", 1)) for p in data.get("no_connect", {}).get("pins", [])}
    return Connectivity(name=data["design"]["name"], supply=data["design"]["supply"], ground=data["design"]["ground"],
                        nets=nets, no_connect=nc)


def read_bom(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_parts(bom: list[dict]) -> "OrderedDict[str, Part]":
    parts: OrderedDict[str, Part] = OrderedDict()
    for row in bom:
        lib, name = row["symbol"].split(":", 1)
        sym = symlib.get_symbol(lib, name)
        parts[row["reference"]] = Part(reference=row["reference"], lib_id=row["symbol"], value=row["value"],
                                       footprint=row["footprint"] or symlib.property_value(sym, "Footprint"),
                                       datasheet=row["datasheet"] if row["datasheet"].startswith("http") else symlib.property_value(sym, "Datasheet"),
                                       sym=sym, pins=symlib.pins(sym))
    return parts


def check_specification(parts: "OrderedDict[str, Part]", conn: Connectivity) -> list[str]:
    """What the generator cannot draw: a pin on two nets, an unknown part or pin, a net with one pin."""
    errors = []
    used: dict[tuple[str, str], list[str]] = defaultdict(list)
    for net, pins in conn.nets.items():
        if len(pins) < 2:
            errors.append(f"net {net} has one pin")
        for ref, num in pins:
            used[(ref, num)].append(net)
            if ref not in parts:
                errors.append(f"net {net}: {ref} is not in the BOM")
            elif num not in {p["number"] for p in parts[ref].pins}:
                errors.append(f"net {net}: {ref} has no pin {num}")
    for (ref, num), nets in used.items():
        if len(set(nets)) > 1:
            errors.append(f"{ref}.{num} is on several nets: {sorted(set(nets))}")
        if (ref, num) in conn.no_connect:
            errors.append(f"{ref}.{num} is both on net {nets[0]} and a no-connect")
    return errors


# --- drawing ------------------------------------------------------------------------------------------------
def _prop(key, value, x, y, hide=False, justify="left"):
    eff = [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("justify"), Sym(justify)]]
    if hide:
        eff.append([Sym("hide"), Sym("yes")])
    return [Sym("property"), key, value, [Sym("at"), x, y, 0], eff]


def _wire(x1, y1, x2, y2):
    return [Sym("wire"), [Sym("pts"), [Sym("xy"), x1, y1], [Sym("xy"), x2, y2]],
            [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]], [Sym("uuid"), _u()]]


def _glabel(net, x, y, angle):
    just = "left" if angle in (0, 90) else "right"
    return [Sym("global_label"), net, [Sym("shape"), Sym("passive")], [Sym("at"), x, y, angle],
            [Sym("fields_autoplaced"), Sym("yes")],
            [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("justify"), Sym(just)]],
            [Sym("uuid"), _u()],
            [Sym("property"), "Intersheetrefs", "${INTERSHEET_REFS}", [Sym("at"), x, y, 0],
             [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("hide"), Sym("yes")]]]]


class Sheet:
    """One sheet: the parts in BOM order, shelf-packed on the grid."""

    def __init__(self, project: str, title: str, parts: "OrderedDict[str, Part]", conn: Connectivity):
        self.project, self.title, self.parts, self.conn = project, title, parts, conn
        self.items: list = []
        self.lib_symbols: OrderedDict[str, list] = OrderedDict()
        self.sheet_uuid = _u()
        self.power_count = 0

    def _use(self, key: str, sym: list) -> None:
        if key not in self.lib_symbols:
            self.lib_symbols[key] = [Sym("symbol"), key] + sym[2:]

    def _power_symbol(self, net: str, x: float, y: float) -> None:
        """A `power:<net>` symbol with its pin end at (x, y)."""
        sym = symlib.get_symbol("power", net)
        key = f"power:{net}"
        self._use(key, sym)
        pin = symlib.pins(sym)[0]
        X, Y = x - pin["x"], y + pin["y"]
        self.power_count += 1
        ref = f"#PWR{self.power_count:04d}"
        value_y = Y + 5.08 if net == self.conn.ground else Y - 5.08
        self.items.append([Sym("symbol"), [Sym("lib_id"), key], [Sym("at"), X, Y, 0], [Sym("unit"), 1],
                           [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("no")], [Sym("on_board"), Sym("no")],
                           [Sym("dnp"), Sym("no")], [Sym("uuid"), _u()],
                           _prop("Reference", ref, X, Y, hide=True), _prop("Value", net, X, value_y),
                           _prop("Footprint", "", X, Y, hide=True), _prop("Datasheet", "", X, Y, hide=True),
                           [Sym("pin"), "1", [Sym("uuid"), _u()]],
                           [Sym("instances"), [Sym("project"), self.project,
                                               [Sym("path"), f"/{self.sheet_uuid}", [Sym("reference"), ref], [Sym("unit"), 1]]]]])

    def _symbol(self, part: Part, X: float, Y: float) -> None:
        self._use(part.lib_id, part.sym)
        xs = [q["x"] for q in part.pins] or [0]
        ys = [q["y"] for q in part.pins] or [0]
        inst = [Sym("symbol"), [Sym("lib_id"), part.lib_id], [Sym("at"), X, Y, 0], [Sym("unit"), 1],
                [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("yes")], [Sym("on_board"), Sym("yes")],
                [Sym("dnp"), Sym("no")], [Sym("uuid"), _u()],
                _prop("Reference", part.reference, X + min(xs) + 2.54, Y - max(ys) - 3.81),
                _prop("Value", part.value, X + min(xs) + 2.54, Y - min(ys) + 3.81),
                _prop("Footprint", part.footprint, X, Y, hide=True),
                _prop("Datasheet", part.datasheet, X, Y, hide=True)]
        for q in part.pins:
            inst.append([Sym("pin"), q["number"], [Sym("uuid"), _u()]])
        inst.append([Sym("instances"), [Sym("project"), self.project,
                                        [Sym("path"), f"/{self.sheet_uuid}", [Sym("reference"), part.reference], [Sym("unit"), 1]]]])
        self.items.append(inst)

    def render(self) -> str:
        pin_net = {rp: net for net, pins in self.conn.nets.items() for rp in pins}
        boxes = []
        for part in self.parts.values():
            xs = [q["x"] for q in part.pins] or [0]
            ys = [q["y"] for q in part.pins] or [0]
            angles = {q["angle"] for q in part.pins}
            mx_l, mx_r = (32 if 0 in angles else 8), (32 if 180 in angles else 8)
            my_t, my_b = (12 if 270 in angles else 6), (12 if 90 in angles else 6)
            boxes.append(dict(p=part, w=(max(xs) - min(xs)) + mx_l + mx_r, h=(max(ys) - min(ys)) + my_t + my_b,
                              ox=-min(xs) + mx_l, oy=max(ys) + my_t))
        area = sum(b["w"] * b["h"] for b in boxes) * 1.6 + 8000
        pname, pw, ph = next(((n, w, h) for n, w, h in PAPERS if w * h >= area), PAPERS[-1])
        x, y, rowh = 20.0, 25.0, 0.0
        placed = []
        for b in boxes:
            if x + b["w"] > pw - 15 and x > 20.0:
                x, y, rowh = 20.0, y + rowh + 6, 0.0
            X = round((x + b["ox"]) / GRID) * GRID
            Y = round((y + b["oy"]) / GRID) * GRID
            placed.append((b, X, Y))
            x += b["w"] + 6
            rowh = max(rowh, b["h"])
        DIRS = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}  # outward, in sheet coordinates
        LABEL_ANGLE = {0: 180, 180: 0, 90: 270, 270: 90}
        for b, X, Y in placed:
            part = b["p"]
            self._symbol(part, X, Y)
            for q in part.pins:
                ex, ey = X + q["x"], Y - q["y"]
                dx, dy = DIRS.get(q["angle"], (-1, 0))
                net = pin_net.get((part.reference, q["number"]))
                if net is None:
                    if q["type"] != "no_connect":
                        self.items.append([Sym("no_connect"), [Sym("at"), ex, ey], [Sym("uuid"), _u()]])
                    continue
                sx, sy = ex + dx * 2 * GRID, ey + dy * 2 * GRID
                self.items.append(_wire(ex, ey, sx, sy))
                if net in self.conn.power_nets:
                    self._power_symbol(net, sx, sy)
                else:
                    self.items.append(_glabel(net, sx, sy, LABEL_ANGLE.get(q["angle"], 0)))
        # a power flag on each power net, so ERC knows the header drives them
        fx, fy = 20.0, y + rowh + 14
        for net in sorted(self.conn.power_nets):
            sym = symlib.get_symbol("power", "PWR_FLAG")
            self._use("power:PWR_FLAG", sym)
            self.power_count += 1
            ref = f"#FLG{self.power_count:04d}"
            X, Y = round(fx / GRID) * GRID, round(fy / GRID) * GRID
            self.items.append([Sym("symbol"), [Sym("lib_id"), "power:PWR_FLAG"], [Sym("at"), X, Y, 0], [Sym("unit"), 1],
                               [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("no")], [Sym("on_board"), Sym("no")],
                               [Sym("dnp"), Sym("no")], [Sym("uuid"), _u()],
                               _prop("Reference", ref, X, Y, hide=True), _prop("Value", "PWR_FLAG", X, Y - 3, hide=True),
                               _prop("Footprint", "", X, Y, hide=True), _prop("Datasheet", "", X, Y, hide=True),
                               [Sym("pin"), "1", [Sym("uuid"), _u()]],
                               [Sym("instances"), [Sym("project"), self.project,
                                                   [Sym("path"), f"/{self.sheet_uuid}", [Sym("reference"), ref], [Sym("unit"), 1]]]]])
            self.items.append(_wire(X, Y, X, Y + 2 * GRID))
            self._power_symbol(net, X, Y + 2 * GRID)
            fx += 24
        self.items.append([Sym("text"), self.title, [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), 20.0, 12.0, 0],
                           [Sym("effects"), [Sym("font"), [Sym("size"), 2.0, 2.0]], [Sym("justify"), Sym("left")]], [Sym("uuid"), _u()]])
        doc = [Sym("kicad_sch"), [Sym("version"), 20250114], [Sym("generator"), GENERATOR], [Sym("generator_version"), "9.0"],
               [Sym("uuid"), self.sheet_uuid], [Sym("paper"), pname],
               [Sym("title_block"), [Sym("title"), self.title],
                [Sym("comment"), 1, "generated by waffle_eda.sch.schematic from bom.csv and connectivity.toml; edit those, not this"]],
               [Sym("lib_symbols")] + list(self.lib_symbols.values())] + self.items + \
              [[Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]]]
        return dumps(doc) + "\n"


def write_schematic(design_dir: Path, title: str | None = None) -> Path:
    """`<name>.kicad_sch` and `<name>.kicad_pro` in ``design_dir`` from its `bom.csv` and `connectivity.toml`."""
    conn = read_connectivity(design_dir / "connectivity.toml")
    parts = load_parts(read_bom(design_dir / "bom.csv"))
    errors = check_specification(parts, conn)
    if errors:
        raise ValueError("connectivity specification: " + "; ".join(errors))
    sheet = Sheet(conn.name, title or f"{conn.name}: sensor, header, power indicator", parts, conn)
    sch = design_dir / f"{conn.name}.kicad_sch"
    sch.write_text(sheet.render())
    pro = design_dir / f"{conn.name}.kicad_pro"
    if not pro.is_file():
        pro.write_text(json.dumps({"meta": {"filename": pro.name, "version": 3}, "board": {}, "schematic": {},
                                   "sheets": [], "text_variables": {}}, indent=2))
    return sch


# --- the checks ------------------------------------------------------------------------------------------------
def _cli() -> str:
    cli = shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("kicad-cli not found")
    return cli


def erc(sch: Path, report: Path) -> dict:
    """KiCad's ERC as JSON. Returns the parsed report; `violations` holds every error and warning."""
    r = subprocess.run([_cli(), "sch", "erc", "--severity-all", "--format", "json", "--output", str(report), str(sch)],
                       capture_output=True, text=True)
    if not report.is_file():
        raise RuntimeError(f"kicad-cli sch erc failed ({r.returncode}): {r.stderr[-400:]}")
    return json.loads(report.read_text())


def erc_errors(report: dict) -> list[str]:
    out = []
    for sheet in report.get("sheets", []):
        for v in sheet.get("violations", []):
            if v.get("severity") == "error":
                out.append(f"{v.get('type')}: {v.get('description')}")
    return out


def export_netlist(sch: Path, out: Path) -> dict[str, set[tuple[str, str]]]:
    """The netlist as KiCad exports it: net name -> {(reference, pin)}. Unnamed single-pin nets are dropped."""
    r = subprocess.run([_cli(), "sch", "export", "netlist", "--format", "kicadsexpr", "--output", str(out), str(sch)],
                       capture_output=True, text=True)
    if not out.is_file():
        raise RuntimeError(f"kicad-cli sch export netlist failed ({r.returncode}): {r.stderr[-400:]}")
    return parse_netlist(out.read_text())


def parse_netlist(text: str) -> dict[str, set[tuple[str, str]]]:
    doc = loads(text)
    nets: dict[str, set[tuple[str, str]]] = {}
    for net in findall(find(doc, "nets"), "net"):
        name = find(net, "name")[1]
        nodes = {(find(n, "ref")[1], find(n, "pin")[1]) for n in findall(net, "node")}
        if len(nodes) >= 2 or not name.startswith("unconnected-"):
            nets[name] = nodes
    return nets


def compare(netlist: dict[str, set[tuple[str, str]]], conn: Connectivity) -> list[str]:
    """Every difference between the exported netlist and the specification; empty when they match one to one."""
    spec = {net: set(pins) for net, pins in conn.nets.items()}
    out = []
    for name in sorted(set(spec) | set(netlist)):
        a, b = spec.get(name), netlist.get(name)
        if a is None:
            if b:
                out.append(f"net {name} is in the netlist and not in the specification: {sorted(b)}")
        elif b is None:
            out.append(f"net {name} is in the specification and not in the netlist")
        elif a != b:
            out.append(f"net {name}: specification has {sorted(a - b)} more, netlist has {sorted(b - a)} more")
    return out
