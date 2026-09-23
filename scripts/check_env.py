#!/usr/bin/env python3
"""Verify the tools this project depends on. Exit 1 if a required one is missing.

Required: Python >= 3.11, KiCad 9 (`kicad-cli`) and its `pcbnew` bindings on this interpreter, z3, numpy, shapely,
pytest, and for stage 5 a Java that runs the pinned Freerouting jar (25 or newer; `waffle_eda/route/freerouting.py`)
plus the jar itself (`scripts/fetch_freerouting.py`) and KiCad's symbol and footprint libraries (stages 2 to 5 of a
design). Optional: Xvfb, git (fetching references). `.claude/hooks/session-start.sh` installs all of it on the web.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import _path  # noqa: F401


def run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip().splitlines()
    text = [line for line in text if not line.startswith("Picked up JAVA_TOOL_OPTIONS")]
    return text[0] if text else ""


def module_version(name: str) -> str | None:
    try:
        mod = importlib.import_module(name)
    except Exception:
        return None
    if name == "pcbnew":
        return mod.GetBuildVersion()
    if name == "z3":
        return mod.get_version_string()
    return getattr(mod, "__version__", "present")


def main() -> int:
    rows: list[tuple[str, bool, str, bool]] = []  # name, ok, detail, required

    py_ok = sys.version_info >= (3, 11)
    rows.append(("python", py_ok, sys.version.split()[0] + f" ({sys.executable})", True))

    kicad_cli = shutil.which("kicad-cli")
    ver = run([kicad_cli, "version"]) if kicad_cli else None
    rows.append(("kicad-cli", bool(ver) and ver.startswith("9."), ver or "not found", True))

    for mod in ("pcbnew", "z3", "numpy", "shapely", "pytest"):
        v = module_version(mod)
        rows.append((mod, v is not None and (mod != "pcbnew" or v.startswith("9.")), v or "import failed", True))

    try:
        from waffle_eda.route import freerouting  # noqa: E402
        java = freerouting.java_path()
        rows.append(("java", True, f"{run([java, '-version'])} ({java})", True))
        jar = freerouting.jar_path()
        rows.append(("freerouting", jar.is_file(), str(jar) if jar.is_file() else f"{jar} missing: run scripts/fetch_freerouting.py", True))
    except Exception as why:
        rows.append(("java", False, str(why), True))
        rows.append(("freerouting", False, "needs Java 25+", True))
    libs = Path("/usr/share/kicad/symbols"), Path("/usr/share/kicad/footprints")
    rows.append(("kicad-libs", all(any(p.iterdir()) for p in libs if p.is_dir()) and all(p.is_dir() for p in libs),
                 "symbols and footprints present" if all(p.is_dir() for p in libs) else "apt install kicad-symbols kicad-footprints", True))
    rows.append(("xvfb-run", shutil.which("xvfb-run") is not None, shutil.which("xvfb-run") or "not found", False))
    git = run(["git", "--version"]) if shutil.which("git") else None
    rows.append(("git", git is not None, git or "not found", False))

    width = max(len(r[0]) for r in rows)
    failed = False
    for name, ok, detail, required in rows:
        mark = "ok  " if ok else ("MISSING" if required else "absent ")
        print(f"{mark:8} {name:<{width}}  {detail}")
        failed |= required and not ok
    print("environment:", "FAIL" if failed else "ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
