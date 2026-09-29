# Residue of `olimex-esp32-poe-m1`

The router's board: `/home/user/waffle-eda/build/bench/olimex-esp32-poe-m1-routed.kicad_pcb`. 81 of 101 nets routed; 20 open, 1 clearances left, 0 shorts.

## Open nets

- `+5V`: 3 pieces
  - C1-1 at (96.393, 163.195), CHRG1-2 at (96.139, 163.322), EXT1-1 at (91.44, 123.22), FET1-2 at (99.477, 138.748), FET2-1 at (92.649, 149.479), PWR1-2 at (92.202, 163.322), R1-1 at (90.932, 121.158), R4-1 at (91.821, 105.283), U3-4 at (94.899, 163.007)
  - D1-1 at (95.25, 126.278)
  - D3-2 at (91.734, 151.765)
- `+5VP`: 2 pieces
  - C23-1 at (99.695, 134.493), C25-1 at (95.758, 135.87), FET1-1 at (99.477, 136.845), L4-2 at (96.377, 144.272), R38-1 at (99.695, 135.509)
  - D1-2 at (95.25, 131.151)
- `/GPI35`: 3 pieces
  - BAT_SENS_E1-1 at (90.932, 165.608)
  - EXT2-3 at (116.84, 128.3)
  - U6-7 at (95.64, 98.928)
- `/GPIO14\HS2_CLK`: 2 pieces
  - EXT2-9 at (116.84, 143.54), UEXT1-9 at (109.22, 127.458)
  - R40-1 at (111.633, 106.68), U6-13 at (95.64, 106.548)
- `/GPIO17\EMAC_CLK_OUT_180`: 2 pieces
  - U6-28 at (112.64, 104.008), U8-4 at (115.981, 105.222)
  - U4-5 at (108.294, 148.594)
- `/GPIO19\EMAC_TXD0(RMII)`: 2 pieces
  - U4-22 at (113.194, 149.594)
  - U6-31 at (112.64, 100.198)
- `/GPIO21\EMAC_TX_EN(RMII)`: 2 pieces
  - U4-21 at (113.194, 149.094)
  - U6-33 at (112.64, 97.658)
- `/GPIO23\MDC(RMII)`: 2 pieces
  - U4-17 at (113.194, 147.094)
  - U6-37 at (112.64, 92.578)
- `/GPIO26\EMAC_RXD1(RMII)`: 2 pieces
  - RM2-1.2 at (98.933, 112.395), U6-11 at (95.64, 104.008)
  - U4-10 at (109.494, 146.394)
- `Net-(ACT1-A)`: 2 pieces
  - ACT1-2 at (114.427, 152.4)
  - U4-3 at (108.294, 149.594)
- `Net-(Class4_EN1-Pad1)`: 2 pieces
  - Class4_EN1-1 at (111.633, 111.379)
  - R54-2 at (114.046, 110.49)
- `Net-(D3-K)`: 2 pieces
  - C6-1 at (98.806, 150.241), FET2-2 at (94.552, 149.479), U7-3 at (102.985, 150.63), U7-4 at (101.485, 150.63)
  - D3-1 at (96.607, 151.765)
- `Net-(LNK1-A)`: 2 pieces
  - LNK1-2 at (114.427, 150.876)
  - R14-2 at (115.443, 152.146)
- `Net-(LNK1-K)`: 2 pieces
  - LNK1-1 at (115.951, 150.876)
  - U4-2 at (108.294, 150.094)
- `Net-(MICRO_SD1-DAT0{slash}DO)`: 2 pieces
  - MICRO_SD1-7 at (101.39, 102.237)
  - R46-2 at (92.583, 104.267)
- `Net-(U3-CHRGb)`: 2 pieces
  - R8-2 at (97.282, 164.338)
  - U3-1 at (92.299, 164.907)
- `Net-(U9-CLS)`: 2 pieces
  - R53-1 at (110.998, 114.173), U9-3 at (108.585, 115.437)
  - Class4_EN1-2 at (111.633, 112.395)
- `Spare1`: 2 pieces
  - C24-1 at (113.462, 136.144), C27-1 at (110.891, 132.334), LAN_CON1-9 at (112.776, 155.806), R28-2 at (111.125, 133.858), R42-1 at (112.141, 130.505), R52-1 at (106.934, 113.919), R7-1 at (113.513, 161.29), U5-3 at (107.829, 133.35), U9-1 at (106.045, 115.437)
  - D8-1 at (116.205, 154.091)
- `Spare2`: 2 pieces
  - C24-2 at (115.24, 136.144), LAN_CON1-10 at (114.046, 158.346), R53-2 at (112.014, 114.173), R54-1 at (114.046, 112.522), U9-4 at (109.855, 115.437), U9-9 at (107.95, 118.237)
  - D8-2 at (116.205, 158.964)
- `unconnected-(U6-NC-Pad21)`: 2 pieces
  - U6-21 at (112.64, 112.898)
  - U6-21 at (112.64, 112.898)

## Clearances the repair left

- short by 0.1015 mm at (95.505, 150.649): Track [/D-] on F.Cu, length 2.2522 mm ; Pad 1 [Net-(D3-K)] of D3 on F.Cu

## Planes

Plane nets open: Spare2.
Tracks on the plane layers: In1.Cu 50, In2.Cu 16.
