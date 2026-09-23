#!/usr/bin/env python3
"""Deterministic BGA fan-out / escape pre-route for the 0.8 mm BGAs (U1 ECP5 caBGA-381, U2 DDR3 FBGA-96).

Geometry (pitch p = 0.8 mm, pads 0.40 mm, vias 0.45/0.20 mm, tracks 0.10 mm at 0.10 mm clearance), the standard fan-out (D59):
- every ball owns its outward diagonal gap (across + 1/2, along - 1/2); the other outward diagonal is the fallback;
- power/ground balls, all rings, are placed first: a dog-bone via at their site is their whole connection (inward
  diagonals as a last resort); a power ball that gets no via is reported as an error, not left to the router;
- ring 1 signals: F.Cu track straight out of the array;
- ring 2 signals: F.Cu, short diagonal into the channel between two ring-1 pads and straight out, only where no via sits
  in that channel; otherwise a dog-bone like the inner rings;
- ring >= 3 signals: dog-bone via at the site, short diagonal onto a ball column line (which runs between the via columns
  with 0.35 mm gaps), then straight out on In2.Cu, In5.Cu or B.Cu; one track per (layer, column line, side) slot;
  ring 3 may fall back to a free F.Cu channel.
All escapes end 1.2 mm outside the ball array where the router picks them up. hw/tools/fix_open_pads.py --dry-run is
the gate afterwards: it must report no open plane-net pad on the two BGAs.
Usage: python3 hw/tools/bga_escape.py [U1 U2 ...]   (edits hw/waffle.kicad_pcb in place; run before export_dsn.py)"""
import os, sys, collections, pcbnew
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(HW, "waffle.kicad_pcb")
mm = pcbnew.FromMM
W = mm(0.10); VIA_D = mm(0.45); VIA_DRILL = mm(0.20)
INNER = (pcbnew.In2_Cu, pcbnew.In5_Cu, pcbnew.B_Cu)   # D55: three inner escape layers
OUT = 1.5      # escape end, in pitches beyond ring 1
# Parts whose balls all escape towards one edge: the DRAM (FBGA-96, 3 + 3 ball columns with an empty middle) faces the FPGA
# with its east edge, so its west-half balls dog-bone into the empty middle / between-column sites and run east under the
# package on the inner layers instead of leaving west and having to go round the part (D57).
EXIT_SIDE = {"U2": "E"}
# nets matching a prefix leave a part on a fixed side: the FPGA's DDR3 balls go west, into the corridor (D59)
EXIT_NET = {"U1": ("DDR3_", "W")}
# nets with these prefixes get ring-1 stubs of the normal length (not one pitch longer), so every escape of the bus ends
# on the same line and the band beside the comb stays free for the bus's layer-change vias (D59)
BAND_FREE = ("DDR3_",)

def main(refs):
    b = pcbnew.LoadBoard(BOARD)
    plane_nets = {z.GetNetname() for z in b.Zones() if not z.GetIsRuleArea()}
    total = collections.Counter()
    for ref in refs:
        fp = b.FindFootprintByReference(ref)
        if fp is None: print(ref, "missing"); continue
        pads = [p for p in fp.Pads()]
        xs = sorted({p.GetPosition().x for p in pads}); ys = sorted({p.GetPosition().y for p in pads})
        # snap to a regular grid (positions are exact multiples in the footprint)
        pitch = min(b2 - a2 for a2, b2 in zip(xs, xs[1:]))
        gx = lambda x: round((x - xs[0]) / pitch); gy = lambda y: round((y - ys[0]) / pitch)
        n = gx(xs[-1]) + 1; m = gy(ys[-1]) + 1
        X = lambda i: int(xs[0] + i * pitch); Y = lambda j: int(ys[0] + j * pitch)   # i, j may be half-integers
        balls = {}
        for p in pads:
            net = p.GetNetname()
            if not net or net.startswith("unconnected"): continue
            balls[(gx(p.GetPosition().x), gy(p.GetPosition().y))] = (p.GetNet(), net in plane_nets)
        used_via = set()          # (i+0.5, j+0.5) diagonal sites
        for t in b.GetTracks():   # sites already holding a via (incremental runs)
            if t.Type() == pcbnew.PCB_VIA_T:
                fi, fj = (t.GetPosition().x - xs[0]) / pitch, (t.GetPosition().y - ys[0]) / pitch
                if -3 <= fi <= n + 2 and -3 <= fj <= m + 2 and abs(fi - round(fi - 0.5) - 0.5) < 0.05 and abs(fj - round(fj - 0.5) - 0.5) < 0.05: used_via.add((round(fi - 0.5) + 0.5, round(fj - 0.5) + 0.5))
        used_slot = set()         # (layer, side, line index)
        used_fchan = set()        # (side, channel index) F.Cu channels for ring-2 escapes
        # escapes are built as pending items and committed only if they clear the copper already on the board (other
        # nets, 0.1 mm); on a fresh board nothing is there, after ddr_bus.py the bus copper is (D59)
        CLR = mm(0.10)
        existing = [(t.GetNetname(), t.GetBoundingBox(), t) for t in b.GetTracks()]
        pending = []
        def add_track(net, layer, a, bpt):
            t = pcbnew.PCB_TRACK(b); t.SetStart(pcbnew.VECTOR2I(*a)); t.SetEnd(pcbnew.VECTOR2I(*bpt)); t.SetWidth(W); t.SetLayer(layer); t.SetNet(net); pending.append(t)
        def add_via(net, pt):
            v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(*pt)); v.SetDrill(VIA_DRILL); v.SetWidth(VIA_D)
            v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(net); pending.append(v)
        def clear(item):
            sh = item.GetEffectiveShape(); bb = item.GetBoundingBox(); bb.Inflate(int(CLR))
            for onet, obb, o in existing:
                if onet == item.GetNetname() or not obb.Intersects(bb): continue
                if o.Type() == pcbnew.PCB_VIA_T or item.Type() == pcbnew.PCB_VIA_T or o.GetLayer() == item.GetLayer():
                    if o.GetEffectiveShape().Collide(sh, int(CLR)): return False
            return True
        def commit():
            """place the pending escape if it clears existing copper; returns True when placed"""
            ok = all(clear(t) for t in pending)
            if ok:
                for t in pending: b.Add(t); existing.append((t.GetNetname(), t.GetBoundingBox(), t))
            pending.clear(); return ok
        # side of a ball: N (j small) S (j large) W (i small) E (i large); ring = distance to edge + 1
        def side_ring(i, j, natural=False, netname=""):
            d = {"N": j, "S": m - 1 - j, "W": i, "E": n - 1 - i}
            if ref in EXIT_SIDE and not natural: s = EXIT_SIDE[ref]; return s, d[s] + 1, d     # every ball leaves towards the same edge
            if ref in EXIT_NET and not natural and netname.startswith(EXIT_NET[ref][0]): s = EXIT_NET[ref][1]; return s, d[s] + 1, d
            s = min(d, key=d.get); return s, d[s] + 1, d
        # generic "outward" coordinate helpers: along = coordinate perpendicular to the edge, across = along the edge
        def pt(side, across, along):
            """across = ball index along the edge (may be half), along = ball index measured from the edge outward (negative = outside)."""
            if side == "N": return (X(across), Y(along))
            if side == "S": return (X(across), Y(m - 1 - along))
            if side == "W": return (X(along), Y(across))
            return (X(n - 1 - along), Y(across))
        def diag_site(side, across_half, along_half):
            """canonical (i+0.5, j+0.5) key for a diagonal via site"""
            if side == "N": return (across_half, along_half)
            if side == "S": return (across_half, m - 1 - along_half)
            if side == "W": return (along_half, across_half)
            return (n - 1 - along_half, across_half)
        # D59, the standard 0.8 mm fan-out: every ball owns its outward diagonal gap (across + 1/2, along - 1/2; the other
        # diagonal is the fallback), power and ground balls take theirs first and unconditionally (a dog-bone via is their
        # whole connection), ring-1 signals leave on F.Cu, ring-2 signals use the F.Cu channel between the ring-1 pads only
        # where no via sits in it and otherwise dog-bone like the inner rings, inner rings dog-bone to their site and run
        # out on an inner layer along a ball column line. Nothing is placed on the assumption that the router will finish it.
        def site_free(side, ah, along_half, edge_len):
            return -0.5 <= ah <= edge_len - 0.5 and diag_site(side, ah, along_half) not in used_via
        def channel_free(side, ch, from_along_half, edge_len):
            """an F.Cu channel stub from from_along_half outward passes every diagonal site down to -0.5"""
            if not (-0.5 <= ch <= edge_len - 0.5) or (side, ch) in used_fchan: return False
            a = from_along_half
            while a >= -0.5:
                if diag_site(side, ch, a) in used_via: return False
                a -= 1
            return True
        def dogbone(net, side, across, along, ah, along_half):
            used_via.add(diag_site(side, ah, along_half))
            add_track(net, pcbnew.F_Cu, pt(side, across, along), pt(side, ah, along_half)); add_via(net, pt(side, ah, along_half))
        def order(ij):
            net, is_plane = balls[ij]; side, ring, _ = side_ring(*ij, netname=net.GetNetname())
            return (0 if is_plane else 1, ring, not net.GetNetname().startswith(("DDR3_", "HDMI_")))
        def escape_signal(i, j, net, natural):
            """one signal ball on its exit side (or its natural side); returns True when an escape was placed"""
            side, ring, dist = side_ring(i, j, natural, net.GetNetname())
            across = i if side in "NS" else j
            along = ring - 1
            edge_len = n if side in "NS" else m
            fcu_ok = True
            if ring == 1:
                # ring-1 stubs one pitch longer than the rest (staggered comb ends, D57) except for the bus nets, whose
                # comb-side band must stay free for the layer-change vias (D59)
                extra = 0 if net.GetNetname().startswith(BAND_FREE) else 1
                add_track(net, pcbnew.F_Cu, pt(side, across, 0), pt(side, across, -OUT - extra))
                if commit(): total["ring1 F.Cu"] += 1; return True
            if ring == 2 and fcu_ok:
                for ch in (across + 0.5, across - 0.5):
                    if channel_free(side, ch, 0.5, edge_len):
                        add_track(net, pcbnew.F_Cu, pt(side, across, 1), pt(side, ch, 0.5)); add_track(net, pcbnew.F_Cu, pt(side, ch, 0.5), pt(side, ch, -OUT))
                        if commit(): used_fchan.add((side, ch)); total["ring2 F.Cu channel"] += 1; return True
            for layer in INNER:
                for ah in (across + 0.5, across - 0.5):
                    if not site_free(side, ah, along - 0.5, edge_len): continue
                    for line in (ah + 0.5, ah - 0.5):          # ball column line next to the via, between the via columns
                        if not (-1 <= line <= edge_len) or (layer, side, line) in used_slot: continue
                        dogbone(net, side, across, along, ah, along - 0.5)
                        add_track(net, layer, pt(side, ah, along - 0.5), pt(side, line, along - 1)); add_track(net, layer, pt(side, line, along - 1), pt(side, line, -OUT))
                        if commit(): used_slot.add((layer, side, line)); total[f"ring{ring} {b.GetLayerName(layer)}"] += 1; return True
                        used_via.discard(diag_site(side, ah, along - 0.5))
            if ring == 3 and fcu_ok:
                for ch in (across + 0.5, across - 0.5):
                    if not channel_free(side, ch, 1.5, edge_len): continue
                    add_track(net, pcbnew.F_Cu, pt(side, across, along), pt(side, ch, along - 0.5)); add_track(net, pcbnew.F_Cu, pt(side, ch, along - 0.5), pt(side, ch, -OUT))
                    if commit(): used_fchan.add((side, ch)); total["ring3 F.Cu channel"] += 1; return True
            return False
        SKIP = tuple(x for x in os.environ.get("SKIP_NETS", "").split(",") if x)   # D59: e.g. SKIP_NETS=DDR3_ leaves the bus balls to ddr_bus.py
        ONLY_OPEN = bool(os.environ.get("ONLY_OPEN"))                              # D59: only balls that have no copper yet (after ddr_bus.py)
        touched = set()
        if ONLY_OPEN:
            for t in b.GetTracks():
                if t.Type() != pcbnew.PCB_VIA_T: touched.add((t.GetStart().x, t.GetStart().y)); touched.add((t.GetEnd().x, t.GetEnd().y))
        for (i, j) in sorted(balls, key=order):
            net, is_plane = balls[(i, j)]
            if SKIP and not is_plane and net.GetNetname().startswith(SKIP): total["skipped (SKIP_NETS)"] += 1; continue
            if ONLY_OPEN and (X(i), Y(j)) in touched: total["already escaped"] += 1; continue
            side, ring, dist = side_ring(i, j)
            across = i if side in "NS" else j
            along = ring - 1
            edge_len = n if side in "NS" else m
            if is_plane:
                # power balls dog-bone toward their own nearest edge, away from the bus exit, so the gaps between the
                # edge column and the signal balls stay free for the signals (D59: P2/T2 of the DRAM were boxed in)
                side, ring, dist = side_ring(i, j, natural=True)
                across = i if side in "NS" else j
                along = ring - 1
                edge_len = n if side in "NS" else m
                for ah, ahalf in ((across + 0.5, along - 0.5), (across - 0.5, along - 0.5), (across + 0.5, along + 0.5), (across - 0.5, along + 0.5)):
                    if site_free(side, ah, ahalf, edge_len):
                        dogbone(net, side, across, along, ah, ahalf)
                        if commit(): total["power dog-bone"] += 1; break
                        used_via.discard(diag_site(side, ah, ahalf))
                else: total["power ball WITHOUT via"] += 1
                continue
            if escape_signal(i, j, net, False): continue
            if (ref in EXIT_SIDE or ref in EXIT_NET) and escape_signal(i, j, net, True): total["escaped on the natural side instead"] += 1; continue
            total[f"ring{ring} WITHOUT escape"] += 1
        print(ref, f"{n}x{m} grid, pitch {pcbnew.ToMM(pitch):.2f} mm, {len(balls)} connected balls")
    pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(BOARD, b)   # fills follow the new vias (stale fills read as clearance errors)
    for k, v in sorted(total.items()): print(f"  {k:28} {v}")

if __name__ == "__main__":
    main(sys.argv[1:] or ["U1", "U2"])
