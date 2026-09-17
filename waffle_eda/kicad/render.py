"""Images of a board for a look by eye, through kicad-cli (the SWIG bindings have no rasteriser)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def render_png(board_path: Path, out_png: Path, side: str = "top", width: int = 1600, height: int = 900,
               zoom: float = 1.0) -> Path:
    """Raytraced render of one side of the board."""
    cli = shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("kicad-cli not found")
    cmd = [cli, "pcb", "render", "--output", str(out_png), "--width", str(width), "--height", str(height),
           "--side", side, "--zoom", str(zoom), "--background", "opaque", str(board_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode or not Path(out_png).is_file():
        raise RuntimeError(f"kicad-cli render failed: {r.stderr[-400:]}")
    return Path(out_png)


def export_svg(board_path: Path, out_svg: Path, layers: str = "F.Cu,B.Cu,Edge.Cuts") -> Path:
    """Vector export of the chosen layers, board area only."""
    cli = shutil.which("kicad-cli")
    cmd = [cli, "pcb", "export", "svg", "--layers", layers, "--page-size-mode", "2", "--exclude-drawing-sheet",
           "--output", str(out_svg), str(board_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode or not Path(out_svg).is_file():
        raise RuntimeError(f"kicad-cli export svg failed: {r.stderr[-400:]}")
    return Path(out_svg)
