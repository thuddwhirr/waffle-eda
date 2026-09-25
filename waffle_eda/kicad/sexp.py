"""A small S-expression reader and writer for KiCad's files (symbol libraries, schematics, netlists).

Ported from `salvage/waffle-fpga/hw/tools/sexp.py` (D4: with a test here, `tests/test_sexp.py`). A bare token
reads as :class:`Sym`, a quoted string as ``str``, and everything else is kept as text; nothing is converted to
a number on the way in, so what is written back is what was read. The writer's layout is KiCad's own: one child
list per line, tab-indented, which keeps the generated schematic diffable.
"""
from __future__ import annotations

import re


class Sym(str):
    """A bare (unquoted) token."""
    __slots__ = ()


_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def loads(text: str):
    """Parse one expression (or a list of them when the text holds several at the top level)."""
    pos, stack, root = 0, [], []
    cur = root
    n = len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"bad token at {pos}: {text[pos:pos + 30]!r}")
        pos = m.end()
        if m.group(1):
            new: list = []
            cur.append(new)
            stack.append(cur)
            cur = new
        elif m.group(2):
            if not stack:
                raise ValueError(f"unbalanced ')' at {pos}")
            cur = stack.pop()
        elif m.group(3) is not None:
            cur.append(m.group(3).replace('\\"', '"').replace("\\\\", "\\"))
        elif m.group(4) is not None:
            cur.append(Sym(m.group(4)))
    if stack:
        raise ValueError("unbalanced '(': the text ends inside a list")
    return root[0] if len(root) == 1 else root


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dumps(node, indent: int = 0) -> str:
    if isinstance(node, Sym):
        return str(node)
    if isinstance(node, str):
        return _quote(node)
    if isinstance(node, bool):
        return "yes" if node else "no"
    if isinstance(node, int):
        return str(node)
    if isinstance(node, float):
        return f"{node:.6f}".rstrip("0").rstrip(".") if node != int(node) else str(int(node))
    parts = [dumps(x, indent + 1) for x in node]
    if all(not isinstance(x, list) for x in node):
        return "(" + " ".join(parts) + ")"
    out = "(" + " ".join(p for p, x in zip(parts, node) if not isinstance(x, list))
    for p, x in zip(parts, node):
        if isinstance(x, list):
            out += "\n" + "\t" * (indent + 1) + p
    return out + "\n" + "\t" * indent + ")"


def find(node, key: str):
    """The first child list whose head is ``key``, or None."""
    for x in node:
        if isinstance(x, list) and x and x[0] == key:
            return x
    return None


def findall(node, key: str) -> list:
    return [x for x in node if isinstance(x, list) and x and x[0] == key]


def value(node, key: str, default=None):
    """The single value of the child ``(key value)``, or ``default``."""
    child = find(node, key)
    return child[1] if child and len(child) > 1 else default
