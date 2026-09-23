"""Minimal S-expression reader/writer for KiCad files. From `salvage/waffle-fpga/hw/tools/sexp.py` (D4), with
its round trip asserted in `tests/test_schematic.py`."""
import re

class Sym(str):
    """Bare symbol token (unquoted)."""
    __slots__ = ()

_tok = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)

def loads(text):
    pos, stack, root = 0, [], []
    cur = root
    n = len(text)
    while pos < n:
        m = _tok.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"bad token at {pos}: {text[pos:pos+30]!r}")
        pos = m.end()
        if m.group(1):
            new = []
            cur.append(new); stack.append(cur); cur = new
        elif m.group(2):
            cur = stack.pop()
        elif m.group(3) is not None:
            cur.append(m.group(3).replace('\\"', '"').replace("\\\\", "\\"))
        elif m.group(4) is not None:
            cur.append(Sym(m.group(4)))
    return root[0] if len(root) == 1 else root

def _q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

def dumps(node, indent=0):
    if isinstance(node, Sym):
        return str(node)
    if isinstance(node, str):
        return _q(node)
    if isinstance(node, (int, float)):
        return repr(node)
    parts = [dumps(x, indent + 1) for x in node]
    simple = all(not isinstance(x, list) for x in node)
    if simple:
        return "(" + " ".join(parts) + ")"
    out = "(" + " ".join(p for p, x in zip(parts, node) if not isinstance(x, list))
    for p, x in zip(parts, node):
        if isinstance(x, list):
            out += "\n" + "\t" * (indent + 1) + p
    return out + "\n" + "\t" * indent + ")"

def find(node, key):
    """First child list whose head is key."""
    for x in node:
        if isinstance(x, list) and x and x[0] == key:
            return x
    return None

def findall(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]
