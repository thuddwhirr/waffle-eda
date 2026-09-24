"""Where KiCad's symbol and footprint libraries are, and how a ``Library:Name`` id resolves to a file.

The container has KiCad 9's binaries and not its libraries (`kicad-symbols`, `kicad-footprints` are separate
packages, absent on 2026-09-24), so `scripts/fetch_tools.py` clones both from KiCad's GitLab at the tag of the
installed release into ``build/tools/`` (D74). A library installed with KiCad (``/usr/share/kicad``) is used when
nothing is fetched; ``WAFFLE_KICAD_SYMBOLS`` and ``WAFFLE_KICAD_FOOTPRINTS`` override both.

Stage 2 checks every BOM line's symbol and footprint against these files, stage 3 writes flattened copies of the
symbols into the schematic (so `kicad-cli` needs no library table to run ERC or export the netlist), and stage 5
loads the footprints into the board through ``pcbnew.FootprintLoad``.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

INSTALLED = Path("/usr/share/kicad")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def tools_dir() -> Path:
    return repo_root() / "build" / "tools"


def kicad_release() -> str:
    """The installed KiCad's release, ``9.0.9``, which is also the libraries' tag."""
    import pcbnew
    m = re.match(r"(\d+\.\d+\.\d+)", pcbnew.GetBuildVersion())
    if not m:
        raise RuntimeError(f"cannot read the KiCad release from {pcbnew.GetBuildVersion()!r}")
    return m.group(1)


def _dir(env: str, fetched: Path, installed: Path) -> Path | None:
    override = os.environ.get(env)
    if override:
        return Path(override)
    if fetched.is_dir():
        return fetched
    if installed.is_dir():
        return installed
    return None


def symbols_dir() -> Path | None:
    return _dir("WAFFLE_KICAD_SYMBOLS", tools_dir() / "kicad-symbols", INSTALLED / "symbols")


def footprints_dir() -> Path | None:
    return _dir("WAFFLE_KICAD_FOOTPRINTS", tools_dir() / "kicad-footprints", INSTALLED / "footprints")


def available() -> str | None:
    """None when both libraries are on disk, else the reason (what check_env and the stage gates print)."""
    missing = [name for name, d in (("symbols", symbols_dir()), ("footprints", footprints_dir())) if d is None]
    if missing:
        return f"KiCad {' and '.join(missing)} libraries not found (python3 scripts/fetch_tools.py)"
    return None


def split_id(lib_id: str) -> tuple[str, str]:
    """``Device:C`` -> ``("Device", "C")``."""
    if ":" not in lib_id:
        raise ValueError(f"{lib_id!r} is not a Library:Name id")
    lib, name = lib_id.split(":", 1)
    return lib, name


def symbol_file(lib: str) -> Path:
    d = symbols_dir()
    if d is None:
        raise FileNotFoundError(available())
    path = d / f"{lib}.kicad_sym"
    if not path.is_file():
        raise FileNotFoundError(f"no symbol library {lib!r} under {d}")
    return path


def footprint_dir(lib: str) -> Path:
    d = footprints_dir()
    if d is None:
        raise FileNotFoundError(available())
    path = d / f"{lib}.pretty"
    if not path.is_dir():
        raise FileNotFoundError(f"no footprint library {lib!r} under {d}")
    return path


def footprint_file(lib_id: str) -> Path:
    lib, name = split_id(lib_id)
    path = footprint_dir(lib) / f"{name}.kicad_mod"
    if not path.is_file():
        raise FileNotFoundError(f"no footprint {name!r} in {footprint_dir(lib)}")
    return path


def has_footprint(lib_id: str) -> bool:
    try:
        footprint_file(lib_id)
    except (FileNotFoundError, ValueError):
        return False
    return True


def has_symbol(lib_id: str) -> bool:
    try:
        from waffle_eda.kicad import symbols
        symbols.get_symbol(lib_id)
    except (FileNotFoundError, KeyError, ValueError):
        return False
    return True


def load_footprint(lib_id: str):
    """The footprint as a ``pcbnew.FOOTPRINT``, ready to add to a board (the caller sets reference and position)."""
    import pcbnew
    lib, name = split_id(lib_id)
    path = footprint_file(lib_id)  # a missing file makes FootprintLoad return None; say which instead
    fp = pcbnew.FootprintLoad(str(path.parent), name)
    if fp is None:
        raise OSError(f"pcbnew could not load footprint {lib_id} from {path}")
    return fp
