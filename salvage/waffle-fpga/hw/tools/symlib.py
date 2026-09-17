"""Read KiCad 9 symbol libraries, flatten derived symbols, expose pin geometry,
and build simple box symbols / power symbols from pin lists."""
import os, copy, uuid
from sexp import loads, dumps, find, findall, Sym

STOCK = "/usr/share/kicad/symbols"
_cache = {}

def load_lib(path):
    if path not in _cache:
        with open(path) as f:
            _cache[path] = loads(f.read())
    return _cache[path]

def _sym_by_name(lib, name):
    for s in findall(lib, "symbol"):
        if s[1] == name:
            return s
    return None

def get_symbol(libname, name):
    """Return a flattened copy of symbol `name` from library `libname`
    (stock library name or path)."""
    path = libname if libname.endswith(".kicad_sym") else os.path.join(STOCK, libname + ".kicad_sym")
    lib = load_lib(path)
    s = _sym_by_name(lib, name)
    if s is None:
        raise KeyError(f"{name} not in {path}")
    s = copy.deepcopy(s)
    ext = find(s, "extends")
    if ext:
        parent = get_symbol(libname, ext[1])
        # child properties override parent's; parent graphics/pins are kept
        props = {p[1]: p for p in findall(s, "property")}
        merged = [x for x in parent if not (isinstance(x, list) and x and x[0] == "property")]
        pprops = {p[1]: p for p in findall(parent, "property")}
        pprops.update(props)
        merged = [merged[0], name] + list(pprops.values()) + [x for x in merged[2:] if not (isinstance(x, list) and x and x[0] == "extends")]
        # rename unit sub-symbols to the child name
        for u in findall(merged, "symbol"):
            u[1] = name + u[1][len(ext[1]):]
        s = merged
    s[1] = name
    return s

def pins(sym):
    """List of dicts: number, name, type, unit, x, y, angle, length (symbol coords)."""
    out = []
    def walk(node, unit):
        for p in findall(node, "pin"):
            at = find(p, "at"); ln = find(p, "length")
            out.append(dict(number=find(p, "number")[1], name=find(p, "name")[1], type=str(p[1]),
                            unit=unit, x=float(at[1]), y=float(at[2]), angle=float(at[3]) if len(at) > 3 else 0.0,
                            length=float(ln[1]) if ln else 2.54))
    walk(sym, 1)
    for u in findall(sym, "symbol"):
        parts = u[1].rsplit("_", 2)
        if len(parts) == 3 and parts[2] not in ("0", "1"):
            continue          # body style 2+ = De Morgan alternate: skip
        unit = int(parts[1]) if len(parts) == 3 else 1
        walk(u, unit)
    return out

def property_value(sym, key, default=""):
    p = [x for x in findall(sym, "property") if x[1] == key]
    return p[0][2] if p else default

def set_property(sym, key, value):
    for p in findall(sym, "property"):
        if p[1] == key:
            p[2] = value
            return
    sym.append([Sym("property"), key, value, [Sym("at"), 0, 0, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("hide"), Sym("yes")]]])

# ----------------------------------------------------------------------------
# Symbol construction
# ----------------------------------------------------------------------------
def _prop(key, val, x=0, y=0, hide=False, idx=None):
    eff = [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]
    if hide:
        eff.append([Sym("hide"), Sym("yes")])
    return [Sym("property"), key, val, [Sym("at"), x, y, 0], eff]

def box_symbol(name, left, right, top=(), bottom=(), footprint="", datasheet="", value=None, ref="U",
               description="", keywords="", width=None, pitch=2.54):
    """Build a rectangular symbol. left/right/top/bottom are lists of
    (number, name, type) tuples ordered top-to-bottom (left/right) or
    left-to-right (top/bottom). Use None as a spacer."""
    n_side = max(len(left), len(right))
    h = (n_side + 1) * pitch
    n_tb = max(len(top), len(bottom))
    if width is None:
        longest = max([len(p[1]) for p in list(left) + list(right) if p] + [4])
        width = max(2 * pitch * ((longest * 0.9 + 6) // 2), (n_tb + 1) * pitch, 15.24)
        width = round(width / pitch) * pitch
    x0, x1 = -width / 2, width / 2
    y_top = round(h / 2 / pitch) * pitch
    y_bot = -y_top
    body = [Sym("symbol"), f"{name}_0_1",
            [Sym("rectangle"), [Sym("start"), x0, y_top], [Sym("end"), x1, y_bot],
             [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]],
             [Sym("fill"), [Sym("type"), Sym("background")]]]]
    unit = [Sym("symbol"), f"{name}_1_1"]
    L = 2.54
    def pin(num, nm, typ, x, y, ang):
        return [Sym("pin"), Sym(typ), Sym("line"), [Sym("at"), x, y, ang], [Sym("length"), L],
                [Sym("name"), nm, [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]],
                [Sym("number"), num, [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]]]
    for i, p in enumerate(left):
        if p: unit.append(pin(p[0], p[1], p[2], x0 - L, y_top - pitch * (i + 1), 0))
    for i, p in enumerate(right):
        if p: unit.append(pin(p[0], p[1], p[2], x1 + L, y_top - pitch * (i + 1), 180))
    xs = lambda k, n: x0 + pitch * (k + 1) + (width - pitch * (n + 1)) / 2
    for i, p in enumerate(top):
        if p: unit.append(pin(p[0], p[1], p[2], round(xs(i, len(top)) / pitch) * pitch, y_top + L, 270))
    for i, p in enumerate(bottom):
        if p: unit.append(pin(p[0], p[1], p[2], round(xs(i, len(bottom)) / pitch) * pitch, y_bot - L, 90))
    sym = [Sym("symbol"), name, [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("yes")], [Sym("on_board"), Sym("yes")],
           _prop("Reference", ref, x0, y_top + 2.54), _prop("Value", value or name, x0, y_bot - 2.54),
           _prop("Footprint", footprint, hide=True), _prop("Datasheet", datasheet, hide=True),
           _prop("Description", description, hide=True), _prop("ki_keywords", keywords, hide=True),
           body, unit]
    return sym

def power_symbol(net, style="rail"):
    """Global power symbol named `net` (GND drawn as ground, others as a bar)."""
    name = net
    g = [Sym("symbol"), f"{name}_0_1"]
    if style == "gnd":
        g += [[Sym("polyline"), [Sym("pts"), [Sym("xy"), -1.27, 0], [Sym("xy"), 1.27, 0]], [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]], [Sym("fill"), [Sym("type"), Sym("none")]]],
              [Sym("polyline"), [Sym("pts"), [Sym("xy"), -0.635, -0.635], [Sym("xy"), 0.635, -0.635]], [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]], [Sym("fill"), [Sym("type"), Sym("none")]]],
              [Sym("polyline"), [Sym("pts"), [Sym("xy"), 0, 1.27], [Sym("xy"), 0, 0]], [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]], [Sym("fill"), [Sym("type"), Sym("none")]]]]
        pin = [Sym("pin"), Sym("power_in"), Sym("line"), [Sym("at"), 0, 2.54, 270], [Sym("length"), 1.27],
               [Sym("name"), net, [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]], [Sym("number"), "1", [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]]]
        vpos = (0, -2.54)
    else:
        g += [[Sym("polyline"), [Sym("pts"), [Sym("xy"), -1.27, 2.54], [Sym("xy"), 1.27, 2.54]], [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]], [Sym("fill"), [Sym("type"), Sym("none")]]],
              [Sym("polyline"), [Sym("pts"), [Sym("xy"), 0, 0], [Sym("xy"), 0, 2.54]], [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]], [Sym("fill"), [Sym("type"), Sym("none")]]]]
        pin = [Sym("pin"), Sym("power_in"), Sym("line"), [Sym("at"), 0, 0, 90], [Sym("length"), 0],
               [Sym("name"), net, [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]], [Sym("number"), "1", [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]]]
        vpos = (0, 4.445)
    u = [Sym("symbol"), f"{name}_1_1", pin]
    sym = [Sym("symbol"), name, [Sym("power")], [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("no")], [Sym("on_board"), Sym("no")],
           _prop("Reference", "#PWR", 0, -2.54 if style != "gnd" else 3.81, hide=True), _prop("Value", net, vpos[0], vpos[1]),
           _prop("Footprint", "", hide=True), _prop("Datasheet", "", hide=True), _prop("Description", f"Power symbol {net}", hide=True),
           g, u]
    return sym

def write_lib(path, symbols):
    lib = [Sym("kicad_symbol_lib"), [Sym("version"), 20241209], [Sym("generator"), "waffle_gen_lib"], [Sym("generator_version"), "9.0"]] + symbols
    with open(path, "w") as f:
        f.write(dumps(lib) + "\n")
