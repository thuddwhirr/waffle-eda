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


# --- a drawing of one package region, for a look at fan-outs by eye ------------------------------------------------
LAYER_COLOURS = {"F.Cu": "#d62828", "B.Cu": "#1d4ed8", "In1.Cu": "#7c3aed", "In2.Cu": "#15803d", "In3.Cu": "#c2410c",
                 "In4.Cu": "#0e7490", "In5.Cu": "#a21caf", "In6.Cu": "#4d7c0f"}


def draw_region_svg(board, region_mm: tuple[float, float, float, float], out_svg: Path, highlight_nets=(),
                    px_per_mm: float = 110.0, labels: dict | None = None, layers: tuple[str, ...] | None = None,
                    title: str = "") -> Path:
    """Draw the copper of ``board`` inside ``region_mm`` (x0, y0, x1, y1) as an SVG: pads, tracks and vias by layer,
    nets in ``highlight_nets`` saturated and the rest faint. ``labels`` maps (x_mm, y_mm) to a text."""
    import html

    from waffle_eda.kicad import board as kb

    x0, y0, x1, y1 = region_mm
    w, h = (x1 - x0) * px_per_mm, (y1 - y0) * px_per_mm
    hi = set(highlight_nets)
    names = {lid: name for lid, name in kb.copper_layers(board)}
    wanted = set(layers) if layers else set(names.values())

    def P(x, y):
        return (x - x0) * px_per_mm, (y - y0) * px_per_mm

    def inside(x, y):
        return x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h + 24:.0f}" viewBox="0 -24 {w:.0f} {h + 24:.0f}">',
           f'<rect x="0" y="-24" width="{w:.0f}" height="{h + 24:.0f}" fill="white"/>',
           f'<text x="4" y="-8" font-size="14" font-family="sans-serif">{html.escape(title)}</text>']
    # pads
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            p = pad.GetPosition()
            x, y = kb.mm(p.x), kb.mm(p.y)
            if not inside(x, y):
                continue
            sx, sy = kb.mm(pad.GetSize().x), kb.mm(pad.GetSize().y)
            net = pad.GetNetname()
            fill = "#f59e0b" if net in hi else ("#9ca3af" if net else "#e5e7eb")
            cx, cy = P(x, y)
            out.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{sx / 2 * px_per_mm:.1f}" ry="{sy / 2 * px_per_mm:.1f}" '
                       f'fill="{fill}" fill-opacity="0.9"><title>{html.escape(fp.GetReference() + "." + pad.GetNumber() + " " + net)}</title></ellipse>')
    # tracks, faint first then highlighted on top
    for pass_hi in (False, True):
        for t in board.GetTracks():
            cls = t.GetClass()
            net = t.GetNetname()
            if (net in hi) != pass_hi:
                continue
            if cls == "PCB_VIA":
                p = t.GetPosition()
                x, y = kb.mm(p.x), kb.mm(p.y)
                if not inside(x, y):
                    continue
                cx, cy = P(x, y)
                r = kb.via_diameter_mm(t) / 2 * px_per_mm
                rd = kb.via_drill_mm(t) / 2 * px_per_mm
                colour = "#111827" if pass_hi else "#6b7280"
                out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{colour}" fill-opacity="{0.95 if pass_hi else 0.45}"/>'
                           f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rd:.1f}" fill="white"/>')
                continue
            layer = names.get(t.GetLayer())
            if layer not in wanted:
                continue
            a, b = t.GetStart(), t.GetEnd()
            ax, ay, bx, by = kb.mm(a.x), kb.mm(a.y), kb.mm(b.x), kb.mm(b.y)
            if not (inside(ax, ay) or inside(bx, by)):
                continue
            (pax, pay), (pbx, pby) = P(ax, ay), P(bx, by)
            colour = LAYER_COLOURS.get(layer, "#374151")
            out.append(f'<line x1="{pax:.1f}" y1="{pay:.1f}" x2="{pbx:.1f}" y2="{pby:.1f}" stroke="{colour}" '
                       f'stroke-width="{kb.mm(t.GetWidth()) * px_per_mm:.1f}" stroke-linecap="round" '
                       f'stroke-opacity="{0.95 if pass_hi else 0.35}"><title>{html.escape(net + " " + layer)}</title></line>')
    for (x, y), text in (labels or {}).items():
        cx, cy = P(x, y)
        out.append(f'<text x="{cx:.1f}" y="{cy + 3:.1f}" font-size="9" font-family="sans-serif" text-anchor="middle" fill="#111">{html.escape(text)}</text>')
    out.append("</svg>")
    out_svg.parent.mkdir(parents=True, exist_ok=True)
    out_svg.write_text("\n".join(out))
    return out_svg


def svg_to_png(svg: Path, png: Path, width: int, height: int) -> Path:
    """Rasterise an SVG with the headless Chromium that Playwright installs (there is no other rasteriser here)."""
    import glob
    import subprocess

    candidates = glob.glob("/opt/pw-browsers/chromium*/chrome-linux/chrome") + glob.glob("/opt/pw-browsers/chromium*/chrome-linux/headless_shell")
    if not candidates:
        raise RuntimeError("no headless chromium under /opt/pw-browsers")
    cmd = [candidates[0], "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
           f"--screenshot={png}", f"--window-size={width},{height}", f"file://{svg.resolve()}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not png.is_file():
        raise RuntimeError(f"chromium screenshot failed: {r.stderr[-400:]}")
    return png
