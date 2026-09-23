"""Read KiCad 9 symbol libraries, flatten derived symbols and expose pin geometry. From
`salvage/waffle-fpga/hw/tools/symlib.py` (D4), reduced to what the stock libraries need; the box and power symbol
builders stayed behind with the custom library they served."""
import os, copy

from waffle_eda.sch.sexp import loads, find, findall, Sym

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
