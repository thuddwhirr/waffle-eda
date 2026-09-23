#!/usr/bin/env python3
"""
Schematic generator: turns the connectivity description in hw/design.py into a
KiCad 9 hierarchical schematic (hw/waffle.kicad_sch + hw/sheets/*.kicad_sch).

Style: every symbol is placed on a grid; each connected pin gets a short wire
stub ending in a global label (signals) or a power symbol (rails / GND);
unconnected pins get no-connect flags.  Nets are therefore defined entirely by
label names, which makes the sheets easy to regenerate and to verify with
`kicad-cli sch export netlist`.
"""
import os, sys, uuid, json, math
from collections import OrderedDict, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexp import Sym, dumps, find, findall
import symlib

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
LIBFILE = os.path.join(HW, "lib", "waffle.kicad_sym")
GRID = 2.54
PAPERS = [("A4", 297, 210), ("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594), ("A0", 1189, 841)]


def U():
    return str(uuid.uuid4())


def libpath(lib):
    return LIBFILE if lib == "waffle" else lib


class Part:
    def __init__(self, ref, lib_id, value, footprint, sheet, unit_sheets, fields, dnp):
        self.ref, self.lib_id, self.value = ref, lib_id, value
        lib, name = lib_id.split(":", 1)
        self.lib, self.name = lib, name
        self.sym = symlib.get_symbol(libpath(lib), name)
        self.footprint = footprint if footprint is not None else symlib.property_value(self.sym, "Footprint")
        self.datasheet = symlib.property_value(self.sym, "Datasheet")
        self.pins = symlib.pins(self.sym)
        self.units = sorted({p["unit"] for p in self.pins if p["unit"] != 0}) or [1]
        self.unit_sheets = {u: (unit_sheets or {}).get(u, sheet) for u in self.units}
        self.fields = fields or {}
        self.dnp = dnp
        self.is_power = bool(find(self.sym, "power"))
        self.by_number = {}
        for p in self.pins:
            self.by_number.setdefault(p["number"], p)
        self.by_name = defaultdict(list)
        for p in self.pins:
            self.by_name[p["name"]].append(p["number"])

    def resolve(self, pin):
        """pin may be a number or a unique name."""
        pin = str(pin)
        if pin in self.by_number:
            return pin
        if pin in self.by_name:
            nums = self.by_name[pin]
            if len(nums) == 1:
                return nums[0]
            raise KeyError(f"{self.ref}: pin name {pin} is not unique ({nums}); use pins_named()")
        raise KeyError(f"{self.ref} ({self.lib_id}): no pin {pin!r}")


class Design:
    def __init__(self, project):
        self.project = project
        self.parts = OrderedDict()
        self.nets = defaultdict(list)        # net -> [(ref, pinnumber)]
        self.sheets = OrderedDict()          # name -> title
        self.sheet_notes = defaultdict(list)
        self.nc = set()                      # (ref, pin) explicit no-connects
        self.power_nets = set()
        self.counters = defaultdict(int)
        self.pwrflags = defaultdict(list)    # sheet -> [net]

    # ---- declaration -------------------------------------------------------
    def sheet(self, name, title):
        self.sheets[name] = title

    def part(self, ref, lib_id, value, sheet, footprint=None, units=None, fields=None, dnp=False):
        if ref in self.parts:
            raise KeyError(f"duplicate ref {ref}")
        p = Part(ref, lib_id, value, footprint, sheet, units, fields, dnp)
        self.parts[ref] = p
        return p

    def autoref(self, prefix):
        self.counters[prefix] += 1
        return f"{prefix}{self.counters[prefix]}"

    def passive(self, prefix, lib_id, value, sheet, footprint, net1, net2, fields=None, dnp=False):
        ref = self.autoref(prefix)
        p = self.part(ref, lib_id, value, sheet, footprint, fields=fields, dnp=dnp)
        pins = [q["number"] for q in p.pins]
        self.connect(net1, (ref, pins[0]))
        self.connect(net2, (ref, pins[1]))
        return ref

    def cap(self, sheet, value, net1, net2="GND", fp="Capacitor_SMD:C_0402_1005Metric", **kw):
        return self.passive("C", "Device:C", value, sheet, fp, net1, net2, **kw)

    def res(self, sheet, value, net1, net2, fp="Resistor_SMD:R_0402_1005Metric", **kw):
        return self.passive("R", "Device:R", value, sheet, fp, net1, net2, **kw)

    def ind(self, sheet, value, net1, net2, fp="Inductor_SMD:L_1210_3225Metric", **kw):
        return self.passive("L", "Device:L", value, sheet, fp, net1, net2, **kw)

    def led(self, sheet, value, net_k, net_a, fp="LED_SMD:LED_0603_1608Metric"):
        # Device:LED pin 1 = K, pin 2 = A
        return self.passive("LED", "Device:LED", value, sheet, fp, net_k, net_a)

    def pwrflag(self, sheet, net):
        self.pwrflags[sheet].append(net)

    def power(self, *nets):
        self.power_nets.update(nets)

    def connect(self, net, *pins):
        for ref, pin in pins:
            num = self.parts[ref].resolve(pin)
            if (ref, num) in self.nc:
                raise KeyError(f"{ref}.{num} both NC and on net {net}")
            self.nets[net].append((ref, num))

    def connect_all_named(self, net, ref, name):
        for num in self.parts[ref].by_name[name]:
            self.nets[net].append((ref, num))

    def no_connect(self, ref, *pins):
        for pin in pins:
            self.nc.add((ref, self.parts[ref].resolve(pin)))

    def note(self, sheet, text):
        self.sheet_notes[sheet].append(text)

    # ---- checks ---------------------------------------------------------------
    def check(self):
        errors = []
        used = defaultdict(list)
        for net, pins in self.nets.items():
            for rp in pins:
                used[rp].append(net)
        for rp, nets in used.items():
            if len(set(nets)) > 1:
                errors.append(f"{rp[0]}.{rp[1]} on several nets: {sorted(set(nets))}")
        for net, pins in self.nets.items():
            if len(set(pins)) < 2 and net not in self.power_nets:
                errors.append(f"net {net} has a single pin {pins}")
        # pins neither connected nor NC
        self.unconnected = defaultdict(list)
        for ref, p in self.parts.items():
            if p.is_power:
                continue
            for q in p.pins:
                if (ref, q["number"]) not in used and (ref, q["number"]) not in self.nc:
                    self.unconnected[ref].append(q["number"])
        return errors

    # ---- rendering ------------------------------------------------------------
    def render(self, outdir):
        errors = self.check()
        if errors:
            for e in errors:
                print("ERROR:", e)
            raise SystemExit(f"{len(errors)} design error(s)")
        os.makedirs(os.path.join(outdir, "sheets"), exist_ok=True)
        root_uuid = U()
        pin_net = {}
        for net, pins in self.nets.items():
            for rp in pins:
                pin_net[rp] = net
        sheet_uuids = {s: U() for s in self.sheets}
        pages = {}
        for i, (sname, title) in enumerate(self.sheets.items()):
            text = self._render_sheet(sname, title, root_uuid, sheet_uuids[sname], pin_net, i + 2)
            with open(os.path.join(outdir, "sheets", f"{sname}.kicad_sch"), "w") as f:
                f.write(text)
        self._render_root(outdir, root_uuid, sheet_uuids)
        self._write_project(outdir)
        # unconnected report
        n = sum(len(v) for v in self.unconnected.values())
        print(f"rendered {len(self.sheets)} sheets, {len(self.parts)} parts, {len(self.nets)} nets; {n} pins auto no-connected")

    def _instances(self, sname):
        out = []
        for ref, p in self.parts.items():
            for u in p.units:
                if p.unit_sheets[u] == sname:
                    out.append((p, u))
        return out

    def _render_sheet(self, sname, title, root_uuid, sheet_uuid, pin_net, page):
        items = []
        lib_symbols = OrderedDict()
        power_syms_needed = set()
        insts = self._instances(sname)
        # --- geometry of each instance
        boxes = []
        for p, u in insts:
            pins = [q for q in p.pins if q["unit"] in (u, 0)]
            xs = [q["x"] for q in pins] or [0]; ys = [q["y"] for q in pins] or [0]
            # body extents from graphics are unknown here; use pin extents (pins sit at the body edge)
            left = any(q["angle"] == 0 for q in pins); right = any(q["angle"] == 180 for q in pins)
            top = any(q["angle"] == 270 for q in pins); bottom = any(q["angle"] == 90 for q in pins)
            mx_l = 32 if left else 8; mx_r = 32 if right else 8
            my_t = 12 if top else 6; my_b = 12 if bottom else 6
            if p.is_power:
                mx_l = mx_r = 4; my_t = my_b = 4
            w = (max(xs) - min(xs)) + mx_l + mx_r
            h = (max(ys) - min(ys)) + my_t + my_b
            boxes.append(dict(p=p, u=u, pins=pins, w=w, h=h, ox=-min(xs) + mx_l, oy=max(ys) + my_t))
        # --- shelf packing
        total_area = sum(b["w"] * b["h"] for b in boxes) * 1.6 + 8000
        paper = None
        for name, pw, ph in PAPERS:
            if pw * ph >= total_area and (pw - 40) >= max((b["w"] for b in boxes), default=0):
                paper = (name, pw, ph); break
        if paper is None:
            paper = PAPERS[-1]
        pname, pw, ph = paper
        x, y, rowh = 20.0, 25.0, 0.0
        placed = []
        for b in boxes:
            if x + b["w"] > pw - 15 and x > 20.0:
                x = 20.0; y += rowh + 6; rowh = 0.0
            X = round((x + b["ox"]) / GRID) * GRID
            Y = round((y + b["oy"]) / GRID) * GRID
            placed.append((b, X, Y))
            x += b["w"] + 6; rowh = max(rowh, b["h"])
        flag_y = y + rowh + 14
        needed_h = flag_y + 20
        # --- emit
        pwr_n = [0]
        def emit_symbol(p, u, X, Y, unit_pins, ref_text=None):
            key = f"{p.lib}:{p.name}"
            if key not in lib_symbols:
                s = [Sym("symbol"), key] + p.sym[2:]
                lib_symbols[key] = s
            inst = [Sym("symbol"), [Sym("lib_id"), key], [Sym("at"), X, Y, 0], [Sym("unit"), u],
                    [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("no" if p.is_power else "yes")],
                    [Sym("on_board"), Sym("no" if p.is_power else "yes")], [Sym("dnp"), Sym("yes" if p.dnp else "no")],
                    [Sym("uuid"), U()]]
            def prop(k, v, dx, dy, hide=False):
                eff = [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("justify"), Sym("left")]]
                if hide: eff.append([Sym("hide"), Sym("yes")])
                return [Sym("property"), k, v, [Sym("at"), X + dx, Y + dy, 0], eff]
            xs = [q["x"] for q in unit_pins] or [0]; ys = [q["y"] for q in unit_pins] or [0]
            inst.append(prop("Reference", ref_text or p.ref, min(xs) + 2.54, -max(ys) - 3.81, hide=p.is_power))
            inst.append(prop("Value", p.value, min(xs) + 2.54, -min(ys) + 3.81, hide=p.is_power))
            inst.append(prop("Footprint", p.footprint, 0, 0, hide=True))
            inst.append(prop("Datasheet", p.datasheet, 0, 0, hide=True))
            for k, v in p.fields.items():
                inst.append(prop(k, v, 0, 0, hide=True))
            for q in p.pins:
                inst.append([Sym("pin"), q["number"], [Sym("uuid"), U()]])
            inst.append([Sym("instances"), [Sym("project"), self.project,
                         [Sym("path"), f"/{root_uuid}/{sheet_uuid}", [Sym("reference"), ref_text or p.ref], [Sym("unit"), u]]]])
            items.append(inst)

        def wire(x1, y1, x2, y2):
            items.append([Sym("wire"), [Sym("pts"), [Sym("xy"), x1, y1], [Sym("xy"), x2, y2]],
                          [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]], [Sym("uuid"), U()]])

        def glabel(net, x, y, angle):
            just = "left" if angle in (0, 90) else "right"
            items.append([Sym("global_label"), net, [Sym("shape"), Sym("passive")], [Sym("at"), x, y, angle],
                          [Sym("fields_autoplaced"), Sym("yes")],
                          [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("justify"), Sym(just)]],
                          [Sym("uuid"), U()],
                          [Sym("property"), "Intersheetrefs", "${INTERSHEET_REFS}", [Sym("at"), x, y, 0],
                           [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("hide"), Sym("yes")]]]])

        def power_symbol(net, x, y):
            """Place the power symbol `net` with its pin end at (x, y)."""
            key = f"waffle:{net}"
            if key not in lib_symbols:
                s = symlib.get_symbol(LIBFILE, net)
                lib_symbols[key] = [Sym("symbol"), key] + s[2:]
            ps = symlib.pins(symlib.get_symbol(LIBFILE, net))[0]
            X, Y = x - ps["x"], y + ps["y"]
            pwr_n[0] += 1
            ref = f"#PWR{pwr_n[0]:04d}"
            inst = [Sym("symbol"), [Sym("lib_id"), key], [Sym("at"), X, Y, 0], [Sym("unit"), 1],
                    [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("no")], [Sym("on_board"), Sym("no")], [Sym("dnp"), Sym("no")],
                    [Sym("uuid"), U()],
                    [Sym("property"), "Reference", ref, [Sym("at"), X, Y, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("hide"), Sym("yes")]]],
                    [Sym("property"), "Value", net, [Sym("at"), X, Y - 5.08 if net not in ("GND", "GNDA") else Y + 5.08, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]],
                    [Sym("property"), "Footprint", "", [Sym("at"), X, Y, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("hide"), Sym("yes")]]],
                    [Sym("property"), "Datasheet", "", [Sym("at"), X, Y, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("hide"), Sym("yes")]]],
                    [Sym("pin"), "1", [Sym("uuid"), U()]],
                    [Sym("instances"), [Sym("project"), self.project, [Sym("path"), f"/{root_uuid}/{sheet_uuid}", [Sym("reference"), ref], [Sym("unit"), 1]]]]]
            items.append(inst)

        def no_connect(x, y):
            items.append([Sym("no_connect"), [Sym("at"), x, y], [Sym("uuid"), U()]])

        DIRS = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}   # outward direction in sheet coords
        LABEL_ANGLE = {0: 180, 180: 0, 90: 270, 270: 90}
        for b, X, Y in placed:
            p, u, unit_pins = b["p"], b["u"], b["pins"]
            emit_symbol(p, u, X, Y, unit_pins)
            for q in unit_pins:
                ex, ey = X + q["x"], Y - q["y"]
                dx, dy = DIRS.get(q["angle"], (-1, 0))
                net = pin_net.get((p.ref, q["number"]))
                if net is None:
                    if q["type"] != "no_connect":      # pins typed no_connect need no flag
                        no_connect(ex, ey)
                    continue
                sx, sy = ex + dx * 2 * GRID, ey + dy * 2 * GRID
                wire(ex, ey, sx, sy)
                if net in self.power_nets:
                    power_symbol(net, sx, sy)
                else:
                    glabel(net, sx, sy, LABEL_ANGLE.get(q["angle"], 0))
        # power flags
        fx, fy = 20.0, flag_y
        for net in self.pwrflags.get(sname, []):
            key = "power:PWR_FLAG"
            if key not in lib_symbols:
                s = symlib.get_symbol("power", "PWR_FLAG"); lib_symbols[key] = [Sym("symbol"), key] + s[2:]
            pwr_n[0] += 1
            ref = f"#FLG{pwr_n[0]:04d}"
            X, Y = round(fx / GRID) * GRID, round(fy / GRID) * GRID
            needed_h = max(needed_h, fy + 30)
            inst = [Sym("symbol"), [Sym("lib_id"), key], [Sym("at"), X, Y, 0], [Sym("unit"), 1],
                    [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("no")], [Sym("on_board"), Sym("no")], [Sym("dnp"), Sym("no")], [Sym("uuid"), U()],
                    [Sym("property"), "Reference", ref, [Sym("at"), X, Y, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("hide"), Sym("yes")]]],
                    [Sym("property"), "Value", "PWR_FLAG", [Sym("at"), X, Y - 3, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("hide"), Sym("yes")]]],
                    [Sym("property"), "Footprint", "", [Sym("at"), X, Y, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("hide"), Sym("yes")]]],
                    [Sym("property"), "Datasheet", "", [Sym("at"), X, Y, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("hide"), Sym("yes")]]],
                    [Sym("pin"), "1", [Sym("uuid"), U()]],
                    [Sym("instances"), [Sym("project"), self.project, [Sym("path"), f"/{root_uuid}/{sheet_uuid}", [Sym("reference"), ref], [Sym("unit"), 1]]]]]
            items.append(inst)
            # PWR_FLAG pin is at (0,0) pointing down: wire down 2 grids to label/power symbol
            wire(X, Y, X, Y + 2 * GRID)
            if net in self.power_nets:
                power_symbol(net, X, Y + 2 * GRID)
            else:
                glabel(net, X, Y + 2 * GRID, 270)
            fx += 24
            if fx > pw - 30:
                fx = 20.0; fy += 16
        if needed_h > ph - 10:
            for name, pw2, ph2 in PAPERS:
                if ph2 >= needed_h + 10 and pw2 >= pw:
                    pname, pw, ph = name, pw2, ph2; break
        # notes
        ty = 12.0
        for i, text in enumerate([f"{title}"] + self.sheet_notes.get(sname, [])):
            items.append([Sym("text"), text, [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), 20.0, ty + i * 4, 0],
                          [Sym("effects"), [Sym("font"), [Sym("size"), 2.0 if i == 0 else 1.5, 2.0 if i == 0 else 1.5]], [Sym("justify"), Sym("left")]], [Sym("uuid"), U()]])
        doc = [Sym("kicad_sch"), [Sym("version"), 20250114], [Sym("generator"), "waffle_gen_sch"], [Sym("generator_version"), "9.0"],
               [Sym("uuid"), sheet_uuid], [Sym("paper"), pname],
               [Sym("title_block"), [Sym("title"), title], [Sym("company"), "waffle-fpga"], [Sym("comment"), 1, "GENERATED by hw/tools/gen_sch.py from hw/design.py — edit the source, not this file"]],
               [Sym("lib_symbols")] + list(lib_symbols.values())] + items
        return dumps(doc) + "\n"

    def _render_root(self, outdir, root_uuid, sheet_uuids):
        items = []
        x, y = 20.0, 30.0
        for i, (sname, title) in enumerate(self.sheets.items()):
            X, Y = round(x / GRID) * GRID, round(y / GRID) * GRID
            items.append([Sym("sheet"), [Sym("at"), X, Y], [Sym("size"), 45.72, 15.24], [Sym("exclude_from_sim"), Sym("no")],
                          [Sym("in_bom"), Sym("yes")], [Sym("on_board"), Sym("yes")], [Sym("dnp"), Sym("no")], [Sym("fields_autoplaced"), Sym("yes")],
                          [Sym("stroke"), [Sym("width"), 0.1524], [Sym("type"), Sym("solid")]], [Sym("fill"), [Sym("color"), 0, 0, 0, 0.0]],
                          [Sym("uuid"), sheet_uuids[sname]],
                          [Sym("property"), "Sheetname", sname, [Sym("at"), X, Y - 0.7, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("justify"), Sym("left"), Sym("bottom")]]],
                          [Sym("property"), "Sheetfile", f"sheets/{sname}.kicad_sch", [Sym("at"), X, Y + 15.24 + 0.6, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("justify"), Sym("left"), Sym("top")]]],
                          [Sym("instances"), [Sym("project"), self.project, [Sym("path"), f"/{root_uuid}", [Sym("page"), str(i + 2)]]]]])
            x += 60
            if x > 230:
                x = 20.0; y += 30
        items.append([Sym("text"), "waffle-fpga — root sheet (GENERATED by hw/tools/gen_sch.py)", [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), 20.0, 15.0, 0],
                      [Sym("effects"), [Sym("font"), [Sym("size"), 2.5, 2.5]], [Sym("justify"), Sym("left")]], [Sym("uuid"), U()]])
        doc = [Sym("kicad_sch"), [Sym("version"), 20250114], [Sym("generator"), "waffle_gen_sch"], [Sym("generator_version"), "9.0"],
               [Sym("uuid"), root_uuid], [Sym("paper"), "A4"], [Sym("title_block"), [Sym("title"), "waffle-fpga"], [Sym("company"), "waffle-fpga"]],
               [Sym("lib_symbols")]] + items + [[Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]]]
        with open(os.path.join(outdir, f"{self.project}.kicad_sch"), "w") as f:
            f.write(dumps(doc) + "\n")

    def _write_project(self, outdir):
        pro = os.path.join(outdir, f"{self.project}.kicad_pro")
        if not os.path.exists(pro):
            with open(pro, "w") as f:
                json.dump({"meta": {"filename": f"{self.project}.kicad_pro", "version": 3}, "board": {}, "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
                           "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []}, "sheets": [], "text_variables": {}}, f, indent=2)
        with open(os.path.join(outdir, "sym-lib-table"), "w") as f:
            f.write('(sym_lib_table\n  (version 7)\n  (lib (name "waffle")(type "KiCad")(uri "${KIPRJMOD}/lib/waffle.kicad_sym")(options "")(descr "waffle-fpga custom symbols"))\n)\n')
        with open(os.path.join(outdir, "fp-lib-table"), "w") as f:
            f.write('(fp_lib_table\n  (version 7)\n  (lib (name "waffle")(type "KiCad")(uri "${KIPRJMOD}/lib/waffle.pretty")(options "")(descr "waffle-fpga custom footprints"))\n)\n')
