#!/usr/bin/env python3
"""Verify the tools this project depends on. Exit 1 if a required one is missing.

Required: Python >= 3.11, KiCad 9 (`kicad-cli`) and its `pcbnew` bindings on this interpreter, z3, numpy, shapely,
pytest, Xvfb, stage 5's router: Freerouting 2.4.1 with a Java 25 to run it (D56), and KiCad's symbol and
footprint libraries (D74); `scripts/fetch_tools.py` puts all of them under build/tools/. Optional: git
(fetching references).
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys

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

    from waffle_eda.route import freerouting as fr
    java = fr.java_path()
    major = fr.java_major(java) if java else None
    rows.append(("java", major is not None and major >= fr.JAVA_MAJOR,
                 f"{major} at {java}" if major else "not found", True))
    rows.append(("freerouting", fr.jar_path().is_file(), str(fr.jar_path()) if fr.jar_path().is_file()
                 else f"not found at {fr.jar_path()} (python3 scripts/fetch_tools.py)", True))
    rows.append(("xvfb-run", shutil.which("xvfb-run") is not None, shutil.which("xvfb-run") or "not found", True))
    from waffle_eda.kicad import libs
    for name, d in (("kicad symbols", libs.symbols_dir()), ("kicad footprints", libs.footprints_dir())):
        rows.append((name, d is not None, str(d) if d else "not found (python3 scripts/fetch_tools.py)", True))
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
