"""The few Markdown conventions a design document uses: ``##`` sections and pipe tables (`stage1_design.py`)."""
from __future__ import annotations

import re


def sections(text: str) -> dict[str, str]:
    """``## Heading`` sections of the document, in order; the text before the first is under ``""``."""
    out: dict[str, str] = {}
    current = ""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            out[current] = "\n".join(lines)
            current, lines = line[3:].strip(), []
        else:
            lines.append(line)
    out[current] = "\n".join(lines)
    return out


def title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def tables(text: str) -> list[list[dict[str, str]]]:
    """Every pipe table in the text as rows keyed by their lower-cased header cells."""
    out: list[list[dict[str, str]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[i + 1]):
            header = [h.lower() for h in _cells(lines[i])]
            rows = []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = _cells(lines[i])
                cells += [""] * (len(header) - len(cells))
                rows.append(dict(zip(header, cells)))
                i += 1
            out.append(rows)
        else:
            i += 1
    return out


def first_table(text: str) -> list[dict[str, str]]:
    t = tables(text)
    return t[0] if t else []


def key_values(text: str) -> dict[str, str]:
    """A two-column table (with any header) read as key -> value, keys lower-cased."""
    out = {}
    for row in first_table(text):
        cells = list(row.values())
        if len(cells) >= 2 and cells[0]:
            out[cells[0].lower()] = cells[1]
    return out


def split_list(text: str) -> list[str]:
    """``a, b  c`` -> ``["a", "b", "c"]``; an empty or ``-``/``none`` cell is empty."""
    text = text.strip()
    if not text or text.lower() in ("-", "none", "n/a"):
        return []
    return [p for p in re.split(r"[,\s]+", text) if p]
