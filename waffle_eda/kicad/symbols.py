"""Read KiCad 9 symbol libraries: a symbol flattened over its ``extends`` parent, its pins with their geometry,
and its properties. Ported from `salvage/waffle-fpga/hw/tools/symlib.py` (D4: tested in `tests/test_sexp.py`).

The libraries come from :mod:`waffle_eda.kicad.libs`; ``get_symbol("Device:C")`` names one by its lib id.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path

from waffle_eda.kicad import libs
from waffle_eda.kicad.sexp import Sym, find, findall, loads


@lru_cache(maxsize=64)
def load_library(path: Path):
    return loads(Path(path).read_text())


def _by_name(lib, name: str):
    for s in findall(lib, "symbol"):
        if s[1] == name:
            return s
    return None


def get_symbol(lib_id: str):
    """A deep copy of the symbol, flattened: a derived symbol (``extends``) takes its parent's graphics and pins
    and keeps its own properties. Raises KeyError when the library has no such symbol."""
    lib_name, name = libs.split_id(lib_id)
    lib = load_library(libs.symbol_file(lib_name))
    s = _by_name(lib, name)
    if s is None:
        raise KeyError(f"no symbol {name!r} in {libs.symbol_file(lib_name)}")
    s = copy.deepcopy(s)
    ext = find(s, "extends")
    if ext:
        parent = get_symbol(f"{lib_name}:{ext[1]}")
        own = {p[1]: p for p in findall(s, "property")}
        props = {p[1]: p for p in findall(parent, "property")}
        props.update(own)
        rest = [x for x in parent[2:] if not (isinstance(x, list) and x and x[0] in ("property", "extends"))]
        merged = [parent[0], name] + list(props.values()) + rest
        for unit in findall(merged, "symbol"):  # unit sub-symbols are named after the symbol
            unit[1] = name + unit[1][len(ext[1]):]
        s = merged
    s[1] = name
    return s


def pins(sym) -> list[dict]:
    """Every pin of the symbol: number, name, type, unit, x, y (symbol coordinates, mm), angle, length."""
    out = []

    def walk(node, unit):
        for p in findall(node, "pin"):
            at, ln = find(p, "at"), find(p, "length")
            out.append(dict(number=str(find(p, "number")[1]), name=str(find(p, "name")[1]), type=str(p[1]),
                            unit=unit, x=float(at[1]), y=float(at[2]), angle=float(at[3]) if len(at) > 3 else 0.0,
                            length=float(ln[1]) if ln else 2.54))

    walk(sym, 1)
    for u in findall(sym, "symbol"):
        parts = u[1].rsplit("_", 2)
        if len(parts) == 3 and parts[2] not in ("0", "1"):
            continue  # a De Morgan alternate body
        walk(u, int(parts[1]) if len(parts) == 3 else 1)
    return out


def property_value(sym, key: str, default: str = "") -> str:
    for p in findall(sym, "property"):
        if p[1] == key:
            return str(p[2])
    return default


def is_power(sym) -> bool:
    return find(sym, "power") is not None


def pin_by_name(sym, name: str) -> list[str]:
    """The pin numbers carrying ``name`` (several on a symbol with, say, four GND pins)."""
    return [p["number"] for p in pins(sym) if p["name"] == name]


def resolve_pin(sym, pin: str) -> str:
    """A pin named by number or by a unique name, as its number."""
    ps = pins(sym)
    numbers = {p["number"] for p in ps}
    if pin in numbers:
        return pin
    named = pin_by_name(sym, pin)
    if len(named) == 1:
        return named[0]
    if named:
        raise KeyError(f"pin name {pin!r} is on several pins {named}; name one by number")
    raise KeyError(f"no pin {pin!r}; the pins are " + ", ".join(f"{p['number']} ({p['name']})" for p in ps))
