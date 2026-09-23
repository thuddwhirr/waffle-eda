# ECP5 I/O database (vendored)

`LFE5U-85F.iodb.json`, `LFE5U-45F.iodb.json`, `LFE5U-25F.iodb.json` are verbatim
copies of `ECP5/<part>/iodb.json` from the open-source
[prjtrellis-db](https://github.com/YosysHQ/prjtrellis-db) repository
(fetched 2026-09-10 from the `master` branch; licence: CC0 1.0, see
`LICENSE.prjtrellis-db`).

Each file lists, for every package of the part, the ball → PIO tile mapping, and
for every PIO: its bank, dual function (PCLK / GR_PCLK / GPLL inputs, VREF,
sysCONFIG names) and DQS-group membership (`LDQ17`, `RDQS89`, `RDQSN89`, …).
Differential pad pairs are implicit: PIO **A/B** and **C/D** of one tile form a
pair (A and C are the true/positive pads); top-side tiles only have A/B.

`python3 pinmap/gen_pinmap.py --refresh-db` re-downloads the three files.
