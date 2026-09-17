"""Zone refill in a child process, with fallbacks, because KiCad's filler can hang on some boards.

``ZONE_FILLER.Fill`` on all zones of the OrangeCrab board never returns, although every zone fills alone in 0.3 s
and every layer group but the top one fills in about a second (decisions D14). A hang inside a C++ call cannot be
interrupted from Python, so the fill runs in a child process on a saved board file: first all zones together, then,
where that times out, layer by layer, then zone by zone. The result is written back to the file.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_CHILD = r'''
import sys, pcbnew
path, mode, arg = sys.argv[1], sys.argv[2], sys.argv[3]
b = pcbnew.LoadBoard(path)
ids = {b.GetLayerName(l): l for l in b.GetEnabledLayers().CuStack()}
zones = pcbnew.ZONES()
if mode == "all":
    for z in b.Zones(): zones.append(z)
elif mode == "layer":
    for z in b.Zones():
        if z.IsOnLayer(ids[arg]): zones.append(z)
elif mode == "zone":
    zones.append(list(b.Zones())[int(arg)])
pcbnew.ZONE_FILLER(b).Fill(zones)
pcbnew.SaveBoard(path, b)
print("filled", zones.size() if hasattr(zones, "size") else len(list(zones)))
'''


def _run(path: Path, mode: str, arg: str, timeout: float) -> bool:
    try:
        r = subprocess.run([sys.executable, "-c", _CHILD, str(path), mode, arg], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return r.returncode == 0


def refill_file(path: Path, timeout: float = 90.0, layer_timeout: float = 45.0, zone_timeout: float = 20.0) -> dict:
    """Refill every zone of the board file in place. Returns what had to fall back and what could not be filled."""
    report = {"mode": "all", "fallback_layers": [], "unfilled_zones": []}
    if _run(path, "all", "", timeout):
        return report
    import pcbnew  # local import: the parent may not have loaded pcbnew yet
    b = pcbnew.LoadBoard(str(path))
    layers = [b.GetLayerName(l) for l in b.GetEnabledLayers().CuStack()]
    zone_layers = [(k, [b.GetLayerName(l) for l in z.GetLayerSet().CuStack()]) for k, z in enumerate(b.Zones())]
    report["mode"] = "per-layer"
    for layer in layers:
        if not any(layer in ls for _, ls in zone_layers):
            continue
        if _run(path, "layer", layer, layer_timeout):
            continue
        report["fallback_layers"].append(layer)
        for k, ls in zone_layers:
            if layer in ls and not _run(path, "zone", str(k), zone_timeout):
                report["unfilled_zones"].append(k)
    return report
