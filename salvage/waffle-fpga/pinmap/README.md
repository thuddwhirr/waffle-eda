# pinmap/ — FPGA pin budget & bank map tooling

| File | Purpose |
|---|---|
| `assignment.toml` | **Single source of truth.** Bank voltages, package orientation, every signal → ball, dedicated pins, explicit spares. Edit this. |
| `gen_pinmap.py` | Validates `assignment.toml` against the prjtrellis database and regenerates `../pinmap.csv`, `../board.lpf`, `../bank-summary.md`. |
| `check_nextpnr.py` | Builds a stub design with every port and runs yosys + nextpnr-ecp5 (85F/45F/25F, caBGA381) with `board.lpf` as an independent check. |
| `db/` | Vendored prjtrellis-db `iodb.json` files (see `db/README.md`). |

## Regenerate

```sh
python3 pinmap/gen_pinmap.py            # validate + write pinmap.csv / board.lpf / bank-summary.md
python3 pinmap/gen_pinmap.py --check    # validate only (exit 1 on any violation)
pip install yowasp-yosys yowasp-nextpnr-ecp5   # once (WebAssembly toolchain), or use native tools
python3 pinmap/check_nextpnr.py         # place & route the stub on 85F, 45F and 25F (speed grade from the TOML)
```

Only Python 3.11+ standard library is needed for the generator.

## What the generator checks

* every ball exists on the 85F **and** is bonded on the 45F and 25F (unless the
  signal is marked `only85 = true`); the 8 balls missing on smaller parts are
  documented and kept unconnected;
* each ball is used once, each signal name once, and every PIO ball of the
  package is either assigned, a documented spare, or the reserved VREF;
* IO_TYPE of every signal matches the VCCIO declared for its bank;
* differential signals sit on a real A/B or C/D pad pair with the positive side
  on A or C; C/D pairs and differential inputs only on left/right banks; top
  banks only pseudo-differential outputs;
* `pair =` hints on single-ended pins (PMOD/header) are real pad pairs;
* clock inputs (`clk =`) are on PCLK / GR_PCLK / GPLL pads and get a
  `FREQUENCY` constraint;
* DDR3: DQS+ on a DQS pad with DQS− on its DQSN pad; every DQ/DM of a lane is
  in that lane's DQS group and bank; CK is differential; VREF1 of a bank with
  DQ/DQS is not used as I/O; no non-DDR signal in a DDR bank;
* per-interface pin counts against the fixed specification (32 PMOD, ≥8 of
  them on true pairs, 4 HDMI pairs, 50 DDR3 balls, 29 FMC, 27 header pins,
  3-pin LED shift register, …);
* `reserved = true` signals are documented (CSV, LPF comment, bank summary)
  but not assigned; DDR3 role `pseudo` marks Lattice pseudo-power pads.

`fit-report.md` and `decisions.md` at the repo root are hand-written.
