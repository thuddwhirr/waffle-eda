"""A KiCad 9 schematic written from a parts-and-nets description, one sheet per function group.

Ported from `salvage/waffle-fpga/hw/tools/gen_sch.py` (D4; tested in `tests/test_design.py`). The style is the
old project's, which KiCad reads and a person can follow: every symbol on a grid, each connected pin with a
short stub ending in a label or a power symbol, every unused pin flagged no-connect. A net whose pins sit on
one sheet gets local labels; one spanning sheets gets global labels; a net on a ``power_in`` pin gets the
matching ``power:`` symbol (``power:GND``, ``power:VCC``) where the library has one, and one ``PWR_FLAG`` so
ERC sees it driven. The symbols are written flattened into each sheet's ``lib_symbols``, so ERC and the
netlist export need no library table.
"""
from __future__ import annotations

import json
import uuid
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from waffle_eda.kicad import libs, symbols
from waffle_eda.kicad.sexp import Sym, dumps, find

GRID = 2.54
PAPERS = [("A4", 297, 210), ("A3", 420, 297), ("A2", 594, 420)]
FONT = [Sym("font"), [Sym("size"), 1.27, 1.27]]
SCH_VERSION = 20250114  # KiCad 9.0's schematic format


def U() -> str:
    return str(uuid.uuid4())


@dataclass
class Part:
    ref: str
    lib_id: str
    value: str
    footprint: str
    sheet: str
    fields: dict = field(default_factory=dict)
    dnp: bool = False

    def __post_init__(self):
        self.sym = symbols.get_symbol(self.lib_id)
        self.pins = symbols.pins(self.sym)
        self.units = sorted({p["unit"] for p in self.pins if p["unit"] != 0}) or [1]
        self.datasheet = symbols.property_value(self.sym, "Datasheet")
        self.description = symbols.property_value(self.sym, "Description")
        if not self.footprint:
            self.footprint = symbols.property_value(self.sym, "Footprint")

    def resolve(self, pin: str) -> str:
        return symbols.resolve_pin(self.sym, str(pin))


class Schematic:
    def __init__(self, project: str, title: str):
        self.project, self.title = project, title
        self.parts: "OrderedDict[str, Part]" = OrderedDict()
        self.nets: dict[str, list[tuple[str, str]]] = defaultdict(list)  # net -> [(ref, pin number)]
        self.nc: set[tuple[str, str]] = set()
        self.sheets: "OrderedDict[str, str]" = OrderedDict()  # name -> title
        self.notes: dict[str, list[str]] = defaultdict(list)

    # --- declaration ---------------------------------------------------------------------------------------
    def sheet(self, name: str, title: str = "") -> None:
        self.sheets[name] = title or name

    def part(self, ref: str, lib_id: str, value: str, footprint: str, sheet: str, fields=None, dnp=False) -> Part:
        if ref in self.parts:
            raise KeyError(f"duplicate reference {ref}")
        if sheet not in self.sheets:
            self.sheet(sheet)
        p = Part(ref, lib_id, value, footprint, sheet, dict(fields or {}), dnp)
        self.parts[ref] = p
        return p

    def connect(self, net: str, ref: str, pin: str) -> None:
        num = self.parts[ref].resolve(pin)
        if (ref, num) in self.nc:
            raise ValueError(f"{ref}.{num} is marked unconnected and on net {net}")
        self.nets[net].append((ref, num))

    def no_connect(self, ref: str, pin: str) -> None:
        self.nc.add((ref, self.parts[ref].resolve(pin)))

    def note(self, sheet: str, text: str) -> None:
        self.notes[sheet].append(text)

    # --- what the description says, checked before anything is drawn ----------------------------------------
    def problems(self) -> list[str]:
        out = []
        on: dict[tuple[str, str], list[str]] = defaultdict(list)
        for net, pins in self.nets.items():
            for rp in pins:
                on[rp].append(net)
        for rp, nets in on.items():
            if len(set(nets)) > 1:
                out.append(f"{rp[0]}.{rp[1]} is on several nets: {sorted(set(nets))}")
        for net, pins in self.nets.items():
            if len(set(pins)) < 2:
                out.append(f"net {net} reaches one pin: {pins}")
        for ref, p in self.parts.items():
            for q in p.pins:
                if (ref, q["number"]) not in on and (ref, q["number"]) not in self.nc and q["type"] != "no_connect":
                    out.append(f"{ref}.{q['number']} ({q['name']}) is neither on a net nor marked unconnected")
        return out

    # --- nets: power, local or global -----------------------------------------------------------------------
    def pin_type(self, ref: str, num: str) -> str:
        return next(q["type"] for q in self.parts[ref].pins if q["number"] == num)

    def is_power_net(self, net: str) -> bool:
        return any(self.pin_type(r, n) in ("power_in", "power_out") for r, n in self.nets[net])

    def power_symbol_id(self, net: str) -> str | None:
        lid = f"power:{net}"
        return lid if libs.has_symbol(lid) else None

    def net_sheets(self, net: str) -> list[str]:
        return sorted({self.parts[r].sheet for r, _n in self.nets[net]})

    def is_global(self, net: str) -> bool:
        return len(self.net_sheets(net)) > 1

    # --- rendering -----------------------------------------------------------------------------------------
    def render(self, out_dir: Path) -> list[Path]:
        """Write ``<project>.kicad_sch``, ``sheets/<name>.kicad_sch`` and ``<project>.kicad_pro``."""
        problems = self.problems()
        if problems:
            raise ValueError("; ".join(problems))
        out_dir = Path(out_dir)
        (out_dir / "sheets").mkdir(parents=True, exist_ok=True)
        root_uuid = U()
        self._counter = [0]  # power symbols and flags are numbered across the whole schematic
        sheet_uuids = {s: U() for s in self.sheets}
        pin_net: dict[tuple[str, str], str] = {}
        for net, pins in self.nets.items():
            for rp in pins:
                pin_net[rp] = net
        flags: dict[str, list[str]] = defaultdict(list)  # sheet -> power nets needing a PWR_FLAG there
        for net in self.nets:
            if self.is_power_net(net):
                flags[self.net_sheets(net)[0]].append(net)
        written = []
        for i, (name, title) in enumerate(self.sheets.items()):
            text = self._render_sheet(name, title, root_uuid, sheet_uuids[name], pin_net, flags.get(name, []))
            path = out_dir / "sheets" / f"{name}.kicad_sch"
            path.write_text(text)
            written.append(path)
        written.append(self._render_root(out_dir, root_uuid, sheet_uuids))
        written.append(self._write_project(out_dir))
        written += self._write_lib_tables(out_dir)
        return written

    def libraries(self) -> tuple[set[str], set[str]]:
        """The symbol libraries and footprint libraries the schematic refers to."""
        syms = {p.lib_id.split(":", 1)[0] for p in self.parts.values()} | {"power"}
        fps = {p.footprint.split(":", 1)[0] for p in self.parts.values() if ":" in p.footprint}
        return syms, fps

    def _write_lib_tables(self, out_dir: Path) -> list[Path]:
        """Project-local library tables naming the libraries in use, so ERC and a person opening the project
        find them: without a table `kicad-cli sch erc` warns `lib_symbol_issues` and `footprint_link_issues`
        on every symbol (33 on the temperature sensor). The paths are relative to the project through
        ``${KIPRJMOD}`` when the library sits inside this repository, else absolute."""
        syms, fps = self.libraries()

        def uri(path: Path) -> str:
            try:
                rel = Path(path).resolve().relative_to(out_dir.resolve())
                return "${KIPRJMOD}/" + rel.as_posix()
            except ValueError:
                pass
            for up in range(1, 6):
                base = out_dir.resolve().parents[up - 1]
                try:
                    rel = Path(path).resolve().relative_to(base)
                    return "${KIPRJMOD}/" + "../" * up + rel.as_posix()
                except ValueError:
                    continue
            return str(Path(path).resolve())

        sym_rows = "".join(f'  (lib (name "{lib}")(type "KiCad")(uri "{uri(libs.symbol_file(lib))}")(options "")(descr ""))\n'
                           for lib in sorted(syms))
        fp_rows = "".join(f'  (lib (name "{lib}")(type "KiCad")(uri "{uri(libs.footprint_dir(lib))}")(options "")(descr ""))\n'
                          for lib in sorted(fps))
        sym_table = out_dir / "sym-lib-table"
        fp_table = out_dir / "fp-lib-table"
        sym_table.write_text(f"(sym_lib_table\n  (version 7)\n{sym_rows})\n")
        fp_table.write_text(f"(fp_lib_table\n  (version 7)\n{fp_rows})\n")
        return [sym_table, fp_table]

    def _instances(self, sheet: str) -> list[tuple[Part, int]]:
        return [(p, u) for p in self.parts.values() for u in p.units if p.sheet == sheet]

    def _render_sheet(self, sname, title, root_uuid, sheet_uuid, pin_net, flag_nets) -> str:
        items: list = []
        lib_symbols: "OrderedDict[str, list]" = OrderedDict()
        insts = self._instances(sname)
        boxes = []
        for p, u in insts:
            pins = [q for q in p.pins if q["unit"] in (u, 0)]
            xs = [q["x"] for q in pins] or [0.0]
            ys = [q["y"] for q in pins] or [0.0]
            left = any(q["angle"] == 0 for q in pins)
            right = any(q["angle"] == 180 for q in pins)
            top = any(q["angle"] == 270 for q in pins)
            bottom = any(q["angle"] == 90 for q in pins)
            mx_l, mx_r = (30 if left else 8), (30 if right else 8)
            mx_r = max(mx_r, 4 + 1.15 * max(len(p.value), len(p.ref)) + 4)  # the value text sits to the right
            my_t, my_b = (14 if top else 6), (14 if bottom else 6)
            w = (max(xs) - min(xs)) + mx_l + mx_r
            h = (max(ys) - min(ys)) + my_t + my_b
            boxes.append(dict(p=p, u=u, pins=pins, w=w, h=h, ox=-min(xs) + mx_l, oy=max(ys) + my_t))
        area = sum(b["w"] * b["h"] for b in boxes) * 1.6 + 8000
        pname, pw, ph = next(((n, w, h) for n, w, h in PAPERS if w * h >= area), PAPERS[-1])
        x, y, rowh = 20.0, 28.0, 0.0
        placed = []
        for b in boxes:
            if x + b["w"] > pw - 15 and x > 20.0:
                x, y, rowh = 20.0, y + rowh + 6, 0.0
            X = round((x + b["ox"]) / GRID) * GRID
            Y = round((y + b["oy"]) / GRID) * GRID
            placed.append((b, X, Y))
            x += b["w"] + 6
            rowh = max(rowh, b["h"])
        flag_y = y + rowh + 16
        counter = self._counter

        def prop(key, val, X, Y, hide=False, justify="left"):
            eff = [Sym("effects"), FONT, [Sym("justify"), Sym(justify)]]
            if hide:
                eff.append([Sym("hide"), Sym("yes")])
            return [Sym("property"), key, val, [Sym("at"), X, Y, 0], eff]

        def lib_symbol(lib_id):
            if lib_id not in lib_symbols:
                sym = symbols.get_symbol(lib_id)
                lib_symbols[lib_id] = [Sym("symbol"), lib_id] + sym[2:]

        def instance(lib_id, ref, value, X, Y, footprint="", datasheet="", fields=None, in_bom=True, on_board=True,
                     dnp=False, pins=(), hide_ref=False, value_at=None):
            lib_symbol(lib_id)
            inst = [Sym("symbol"), [Sym("lib_id"), lib_id], [Sym("at"), X, Y, 0], [Sym("unit"), 1],
                    [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("yes" if in_bom else "no")],
                    [Sym("on_board"), Sym("yes" if on_board else "no")], [Sym("dnp"), Sym("yes" if dnp else "no")],
                    [Sym("uuid"), U()]]
            vx, vy = value_at or (X, Y)
            inst.append(prop("Reference", ref, vx if value_at else X + 2.54, (vy - 2.54) if value_at else Y - 3.81, hide=hide_ref))
            inst.append(prop("Value", value, vx, vy, hide=hide_ref))
            inst.append(prop("Footprint", footprint, X, Y, hide=True))
            inst.append(prop("Datasheet", datasheet, X, Y, hide=True))
            for k, v in (fields or {}).items():
                inst.append(prop(k, v, X, Y, hide=True))
            for num in pins:
                inst.append([Sym("pin"), num, [Sym("uuid"), U()]])
            inst.append([Sym("instances"), [Sym("project"), self.project,
                         [Sym("path"), f"/{root_uuid}/{sheet_uuid}", [Sym("reference"), ref], [Sym("unit"), 1]]]])
            items.append(inst)

        def wire(x1, y1, x2, y2):
            items.append([Sym("wire"), [Sym("pts"), [Sym("xy"), x1, y1], [Sym("xy"), x2, y2]],
                          [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]], [Sym("uuid"), U()]])

        def label(net, x, y, angle, global_):
            just = "left" if angle in (0, 90) else "right"
            kind = "global_label" if global_ else "label"
            node = [Sym(kind), net]
            if global_:
                node.append([Sym("shape"), Sym("passive")])
            node += [[Sym("at"), x, y, angle], [Sym("fields_autoplaced"), Sym("yes")],
                     [Sym("effects"), FONT, [Sym("justify"), Sym(just), Sym("bottom")]], [Sym("uuid"), U()]]
            if global_:
                node.append([Sym("property"), "Intersheetrefs", "${INTERSHEET_REFS}", [Sym("at"), x, y, 0],
                             [Sym("effects"), FONT, [Sym("hide"), Sym("yes")]]])
            items.append(node)

        def power_symbol(net, x, y):
            """The ``power:<net>`` symbol with its pin's connection point at (x, y)."""
            lid = self.power_symbol_id(net)
            ps = symbols.pins(symbols.get_symbol(lid))[0]
            X, Y = x - ps["x"], y + ps["y"]
            counter[0] += 1
            up = ps["angle"] == 90  # the body sits above the pin (a rail) or below it (ground)
            instance(lid, f"#PWR{counter[0]:03d}", net, X, Y, in_bom=False, on_board=False, pins=("1",),
                     hide_ref=True, value_at=(X, Y - 5.08 if up else Y + 5.08))

        def pwr_flag(net, x, y):
            counter[0] += 1
            instance("power:PWR_FLAG", f"#FLG{counter[0]:03d}", "PWR_FLAG", x, y, in_bom=False, on_board=False,
                     pins=("1",), hide_ref=True, value_at=(x, y - 5.08))

        def no_connect(x, y):
            items.append([Sym("no_connect"), [Sym("at"), x, y], [Sym("uuid"), U()]])

        OUT = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}  # a pin's outward direction on the sheet
        LABEL_ANGLE = {0: 180, 180: 0, 90: 270, 270: 90}
        for b, X, Y in placed:
            p, u, unit_pins = b["p"], b["u"], b["pins"]
            right_x = X + (max(q["x"] for q in unit_pins) if unit_pins else 0.0) + 2.54
            instance(p.lib_id, p.ref, p.value, X, Y, p.footprint, p.datasheet, p.fields, dnp=p.dnp,
                     pins=[q["number"] for q in p.pins], value_at=(right_x, Y + 1.27))
            for q in unit_pins:
                ex, ey = X + q["x"], Y - q["y"]
                dx, dy = OUT.get(q["angle"], (-1, 0))
                net = pin_net.get((p.ref, q["number"]))
                if net is None:
                    if q["type"] != "no_connect":
                        no_connect(ex, ey)
                    continue
                sx, sy = ex + dx * 2 * GRID, ey + dy * 2 * GRID
                wire(ex, ey, sx, sy)
                if self.is_power_net(net) and self.power_symbol_id(net):
                    power_symbol(net, sx, sy)
                else:
                    label(net, sx, sy, LABEL_ANGLE.get(q["angle"], 0), self.is_global(net) or self.is_power_net(net))
        # one PWR_FLAG per power net, beside its power symbol or label
        fx = 20.0
        for net in flag_nets:
            X, Y = round(fx / GRID) * GRID, round(flag_y / GRID) * GRID
            pwr_flag(net, X, Y)
            wire(X, Y, X + 2 * GRID, Y)
            if self.power_symbol_id(net):
                power_symbol(net, X + 2 * GRID, Y)
            else:
                label(net, X + 2 * GRID, Y, 0, True)
            fx += 30
        needed_h = flag_y + 20
        if needed_h > ph - 10:
            pname, pw, ph = next(((n, w, h) for n, w, h in PAPERS if h >= needed_h + 10 and w >= pw), PAPERS[-1])
        for i, text in enumerate([title] + self.notes.get(sname, [])):
            size = 2.0 if i == 0 else 1.5
            items.append([Sym("text"), text, [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), 20.0, 16.0 + i * 4, 0],
                          [Sym("effects"), [Sym("font"), [Sym("size"), size, size]], [Sym("justify"), Sym("left")]],
                          [Sym("uuid"), U()]])
        doc = [Sym("kicad_sch"), [Sym("version"), SCH_VERSION], [Sym("generator"), "waffle_eda"],
               [Sym("generator_version"), "9.0"], [Sym("uuid"), sheet_uuid], [Sym("paper"), pname],
               [Sym("title_block"), [Sym("title"), title], [Sym("company"), self.project],
                [Sym("comment"), 1, "generated by waffle_eda.design.stage3_schematic from design.md and bom.csv; edit those, not this file"]],
               [Sym("lib_symbols")] + list(lib_symbols.values())] + items
        return dumps(doc) + "\n"

    def _render_root(self, out_dir: Path, root_uuid: str, sheet_uuids: dict) -> Path:
        items: list = []
        x, y = 20.0, 30.0
        for i, (name, title) in enumerate(self.sheets.items()):
            X, Y = round(x / GRID) * GRID, round(y / GRID) * GRID
            items.append([Sym("sheet"), [Sym("at"), X, Y], [Sym("size"), 45.72, 15.24], [Sym("exclude_from_sim"), Sym("no")],
                          [Sym("in_bom"), Sym("yes")], [Sym("on_board"), Sym("yes")], [Sym("dnp"), Sym("no")],
                          [Sym("fields_autoplaced"), Sym("yes")],
                          [Sym("stroke"), [Sym("width"), 0.1524], [Sym("type"), Sym("solid")]],
                          [Sym("fill"), [Sym("color"), 0, 0, 0, 0.0]], [Sym("uuid"), sheet_uuids[name]],
                          [Sym("property"), "Sheetname", name, [Sym("at"), X, Y - 0.7, 0],
                           [Sym("effects"), FONT, [Sym("justify"), Sym("left"), Sym("bottom")]]],
                          [Sym("property"), "Sheetfile", f"sheets/{name}.kicad_sch", [Sym("at"), X, Y + 15.24 + 0.6, 0],
                           [Sym("effects"), FONT, [Sym("justify"), Sym("left"), Sym("top")]]],
                          [Sym("instances"), [Sym("project"), self.project, [Sym("path"), f"/{root_uuid}", [Sym("page"), str(i + 2)]]]]])
            x += 60
            if x > 230:
                x, y = 20.0, y + 30
        items.append([Sym("text"), f"{self.title}: root sheet, one sheet per function group (generated; edit design.md and bom.csv)",
                      [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), 20.0, 15.0, 0],
                      [Sym("effects"), [Sym("font"), [Sym("size"), 2.0, 2.0]], [Sym("justify"), Sym("left")]], [Sym("uuid"), U()]])
        doc = [Sym("kicad_sch"), [Sym("version"), SCH_VERSION], [Sym("generator"), "waffle_eda"], [Sym("generator_version"), "9.0"],
               [Sym("uuid"), root_uuid], [Sym("paper"), "A4"],
               [Sym("title_block"), [Sym("title"), self.title], [Sym("company"), self.project]],
               [Sym("lib_symbols")]] + items + [[Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]]]
        path = out_dir / f"{self.project}.kicad_sch"
        path.write_text(dumps(doc) + "\n")
        return path

    def _write_project(self, out_dir: Path) -> Path:
        pro = out_dir / f"{self.project}.kicad_pro"
        if not pro.is_file():
            pro.write_text(json.dumps({"meta": {"filename": pro.name, "version": 3},
                                       "board": {"design_settings": {"defaults": {}, "rules": {}}},
                                       "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
                                       "net_settings": {"classes": [], "meta": {"version": 4}},
                                       "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
                                       "sheets": [], "text_variables": {}}, indent=2) + "\n")
        return pro
