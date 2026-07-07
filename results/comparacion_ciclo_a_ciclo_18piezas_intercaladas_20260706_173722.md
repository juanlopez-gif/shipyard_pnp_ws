# Comparación ciclo a ciclo — 12G/3R/3B intercaladas

Corrida real: `20260706_173722_GGRGBGGGGBGGBGGRRG`  |  Orden dispatch simulado: `['GREEN', 'RED', 'BLUE', 'GREEN', 'RED', 'BLUE', 'GREEN', 'RED', 'BLUE', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN']`


## xarm2

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-001/FEED_GREEN_TO_C3 | 0.00 | 15.53 | P01/FEED_GREEN_TO_C3 | 0.00 | 15.43 | +0.00 | -0.10 |
| 2 | piece-003/FEED_TO_C1S1 | 15.53 | 13.49 | P02/FEED_TO_C1S1 | 15.43 | 13.55 | -0.10 | +0.06 |
| 3 | piece-005/FEED_TO_C1S1 | 29.03 | 13.58 | P03/FEED_TO_C1S1 | 28.98 | 13.55 | -0.05 | -0.03 |
| 4 | piece-002/FEED_GREEN_TO_C3 | 42.61 | 15.56 | P04/FEED_GREEN_TO_C3 | 42.53 | 15.43 | -0.08 | -0.14 |
| 5 | piece-016/FEED_TO_C1S1 | 58.18 | 13.56 | P05/FEED_TO_C1S1 | 57.96 | 13.55 | -0.22 | -0.01 |
| 6 | piece-010/FEED_TO_C1S1 | 71.75 | 13.62 | P06/FEED_TO_C1S1 | 71.51 | 13.55 | -0.24 | -0.07 |
| 7 | piece-004/FEED_GREEN_TO_C3 | 85.37 | 15.47 | P07/FEED_GREEN_TO_C3 | 85.06 | 15.43 | -0.31 | -0.04 |
| 8 | piece-017/FEED_TO_C1S1 | 100.84 | 13.96 | P08/FEED_TO_C1S1 | 100.49 | 13.55 | -0.35 | -0.41 |
| 9 | piece-013/FEED_TO_C1S1 | 114.80 | 14.06 | P09/FEED_TO_C1S1 | 114.04 | 13.55 | -0.76 | -0.51 |
| 10 | piece-006/FEED_GREEN_TO_C3 | 128.87 | 15.45 | P10/FEED_GREEN_TO_C3 | 127.59 | 15.43 | -1.28 | -0.02 |
| 11 | piece-007/FEED_GREEN_TO_C3 | 202.82 | 15.56 | P11/FEED_GREEN_TO_C3 | 200.92 | 15.43 | -1.90 | -0.13 |
| 12 | piece-008/FEED_GREEN_TO_C3 | 282.80 | 15.47 | P12/FEED_GREEN_TO_C3 | 240.95 | 15.43 | -41.85 | -0.04 |
| 13 | piece-009/FEED_GREEN_TO_C3 | 415.72 | 15.42 | P13/FEED_GREEN_TO_C3 | 319.18 | 15.43 | -96.54 | +0.01 |
| 14 | piece-011/FEED_GREEN_TO_C3 | 456.49 | 15.31 | P14/FEED_GREEN_TO_C3 | 397.31 | 15.43 | -59.18 | +0.12 |
| 15 | piece-012/FEED_GREEN_TO_C3 | 534.73 | 15.39 | P15/FEED_GREEN_TO_C3 | 437.34 | 15.43 | -97.39 | +0.04 |
| 16 | piece-014/FEED_GREEN_TO_C3 | 575.03 | 15.76 | P16/FEED_GREEN_TO_C3 | 515.57 | 15.43 | -59.46 | -0.33 |
| 17 | piece-015/FEED_GREEN_TO_C3 | 656.81 | 15.84 | P17/FEED_GREEN_TO_C3 | 555.50 | 15.43 | -101.31 | -0.41 |
| 18 | piece-018/FEED_GREEN_TO_C3 | 697.14 | 15.78 | P18/FEED_GREEN_TO_C3 | 633.73 | 15.43 | -63.41 | -0.35 |

## xarm1

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-003/C1S2_TO_LASER | 31.06 | 15.27 | P02/C1S2_TO_LASER | 32.90 | 15.25 | +1.84 | -0.02 |
| 2 | piece-005/C1S2_TO_C2S1 | 46.34 | 15.75 | P03/C1S2_TO_C2S1 | 48.15 | 15.75 | +1.81 | +0.00 |
| 3 | piece-003/LASER_TO_C2S1 | 68.92 | 15.03 | P02/LASER_TO_C2S1 | 69.20 | 14.95 | +0.28 | -0.08 |
| 4 | piece-016/C1S2_TO_LASER | 83.96 | 15.27 | P05/C1S2_TO_LASER | 84.15 | 15.25 | +0.19 | -0.02 |
| 5 | piece-010/C1S2_TO_C2S1 | 99.24 | 15.80 | P06/C1S2_TO_C2S1 | 99.40 | 15.75 | +0.16 | -0.05 |
| 6 | piece-016/LASER_TO_C2S1 | 128.91 | 14.98 | P05/LASER_TO_C2S1 | 121.05 | 14.95 | -7.86 | -0.03 |
| 7 | piece-017/C1S2_TO_LASER | 143.89 | 15.25 | P08/C1S2_TO_LASER | 136.00 | 15.25 | -7.89 | -0.00 |
| 8 | piece-017/LASER_TO_C2S1 | 181.48 | 10.71 | P08/LASER_TO_C2S1 | 172.35 | 14.95 | -9.13 | +4.24 |
| 9 | piece-017/LASER_TO_C2S1 | 206.33 | 14.93 | P09/C1S2_TO_C2S1 | 203.20 | 15.75 | -3.13 | +0.82 |

## laser

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-003/PROCESS_RED | 46.33 | 22.59 | P02/PROCESS_RED | 46.35 | 22.80 | +0.02 | +0.21 |
| 2 | piece-016/PROCESS_RED | 99.23 | 29.67 | P05/PROCESS_RED | 97.60 | 22.80 | -1.63 | -6.87 |
| 3 | piece-017/PROCESS_RED | 159.15 | 22.32 | P08/PROCESS_RED | 149.45 | 22.80 | -9.70 | +0.48 |

## robot2

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-005/CLASSIFY_C2S2_TO_BANTAM | 66.60 | 35.87 | P03/CLASSIFY_C2S2_TO_BANTAM | 71.30 | 36.30 | +4.70 | +0.43 |
| 2 | piece-003/CLASSIFY_C2S2_TO_C4 | 102.48 | 33.64 | P02/CLASSIFY_C2S2_TO_C4 | 107.60 | 34.60 | +5.12 | +0.96 |
| 3 | piece-010/CLASSIFY_C2S2_TO_IBS | 163.20 | 30.81 | P06/CLASSIFY_C2S2_TO_IBS | 160.00 | 30.85 | -3.20 | +0.04 |
| 4 | piece-016/CLASSIFY_C2S2_TO_C4 | 194.01 | 31.98 | P05/CLASSIFY_C2S2_TO_C4 | 190.85 | 33.60 | -3.16 | +1.62 |
| 5 | piece-013/CLASSIFY_C2S2_TO_IBS | 242.68 | 30.64 | P08/CLASSIFY_C2S2_TO_C4 | 278.15 | 33.60 | +35.47 | +2.96 |
| 6 | piece-017/CLASSIFY_C2S2_TO_C4 | 273.32 | 32.45 | P09/CLASSIFY_C2S2_TO_IBS | 356.35 | 30.85 | +83.03 | -1.60 |
| 7 | piece-005/BANTAM_TO_C4 | 322.64 | 36.46 | P03/BANTAM_TO_C4 | 387.20 | 36.40 | +64.56 | -0.06 |
| 8 | piece-010/IBS_TO_BANTAM | 359.11 | 37.03 | P06/IBS_TO_BANTAM | 423.60 | 36.90 | +64.49 | -0.13 |
| 9 | piece-010/BANTAM_TO_C4 | 444.42 | 36.65 | P06/BANTAM_TO_C4 | 509.00 | 36.40 | +64.58 | -0.25 |
| 10 | piece-013/IBS_TO_BANTAM | 481.08 | 36.97 | P09/IBS_TO_BANTAM | 545.40 | 36.90 | +64.32 | -0.07 |
| 11 | piece-013/BANTAM_TO_C4 | 566.73 | 36.46 | P09/BANTAM_TO_C4 | 630.80 | 36.40 | +64.07 | -0.06 |

## bantam

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-005/PROCESS_BLUE | 102.47 | 48.69 | P03/PROCESS_BLUE | 107.60 | 48.50 | +5.13 | -0.19 |
| 2 | piece-010/PROCESS_BLUE | 396.14 | 48.27 | P06/PROCESS_BLUE | 460.50 | 48.50 | +64.36 | +0.23 |
| 3 | piece-013/PROCESS_BLUE | 518.05 | 48.67 | P09/PROCESS_BLUE | 582.30 | 48.50 | +64.25 | -0.17 |

## robot1

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-001/UNLOAD_C3 | 21.66 | 48.24 | P01/UNLOAD_C3 | 21.50 | 38.50 | -0.16 | -9.74 |
| 2 | piece-002/UNLOAD_C3 | 69.90 | 40.60 | P04/UNLOAD_C3 | 64.10 | 38.50 | -5.80 | -2.10 |
| 3 | piece-004/UNLOAD_C3 | 110.51 | 40.94 | P07/UNLOAD_C3 | 106.60 | 38.50 | -3.91 | -2.44 |
| 4 | piece-003/UNLOAD_C4 | 151.45 | 39.05 | P02/UNLOAD_C4 | 147.30 | 38.20 | -4.15 | -0.85 |
| 5 | piece-006/UNLOAD_C3 | 190.51 | 40.60 | P10/UNLOAD_C3 | 185.50 | 40.00 | -5.01 | -0.60 |
| 6 | piece-016/UNLOAD_C4 | 231.11 | 39.34 | P11/UNLOAD_C3 | 225.50 | 40.00 | -5.61 | +0.66 |
| 7 | piece-007/UNLOAD_C3 | 270.46 | 40.49 | P05/UNLOAD_C4 | 265.50 | 38.20 | -4.96 | -2.29 |
| 8 | piece-017/UNLOAD_C4 | 310.95 | 39.19 | P12/UNLOAD_C3 | 303.70 | 40.00 | -7.25 | +0.81 |
| 9 | piece-005/UNLOAD_C4 | 364.34 | 37.94 | P08/UNLOAD_C4 | 343.70 | 38.20 | -20.64 | +0.26 |
| 10 | piece-008/UNLOAD_C3 | 402.28 | 41.66 | P13/UNLOAD_C3 | 381.90 | 40.00 | -20.38 | -1.66 |
| 11 | piece-009/UNLOAD_C3 | 443.94 | 40.45 | P14/UNLOAD_C3 | 421.90 | 40.00 | -22.04 | -0.45 |
| 12 | piece-010/UNLOAD_C4 | 486.28 | 36.12 | P03/UNLOAD_C4 | 461.90 | 38.20 | -24.38 | +2.08 |
| 13 | piece-011/UNLOAD_C3 | 522.40 | 40.27 | P15/UNLOAD_C3 | 500.10 | 40.00 | -22.30 | -0.28 |
| 14 | piece-012/UNLOAD_C3 | 562.68 | 40.72 | P16/UNLOAD_C3 | 540.10 | 40.00 | -22.58 | -0.72 |
| 15 | piece-013/UNLOAD_C4 | 608.37 | 35.86 | P06/UNLOAD_C4 | 580.10 | 38.20 | -28.27 | +2.34 |
| 16 | piece-014/UNLOAD_C3 | 644.24 | 40.64 | P17/UNLOAD_C3 | 618.30 | 40.00 | -25.94 | -0.64 |
| 17 | piece-015/UNLOAD_C3 | 684.88 | 40.26 | P18/UNLOAD_C3 | 658.30 | 40.00 | -26.58 | -0.26 |
| 18 | piece-018/UNLOAD_C3 | 725.14 | 40.38 | P09/UNLOAD_C4 | 698.30 | 38.20 | -26.84 | -2.18 |