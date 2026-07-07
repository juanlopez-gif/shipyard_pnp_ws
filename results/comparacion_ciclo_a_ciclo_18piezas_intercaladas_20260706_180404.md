# Comparación ciclo a ciclo — 12G/3R/3B intercaladas

Corrida real: `20260706_180404_GGRGBGGGGBGGBGGRRG`  |  Orden dispatch simulado: `['GREEN', 'RED', 'BLUE', 'GREEN', 'RED', 'BLUE', 'GREEN', 'RED', 'BLUE', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN']`


## xarm2

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-001/FEED_GREEN_TO_C3 | 0.00 | 15.61 | P01/FEED_GREEN_TO_C3 | 0.00 | 15.43 | +0.00 | -0.18 |
| 2 | piece-003/FEED_TO_C1S1 | 15.61 | 13.29 | P02/FEED_TO_C1S1 | 15.43 | 13.55 | -0.18 | +0.26 |
| 3 | piece-005/FEED_TO_C1S1 | 28.90 | 13.64 | P03/FEED_TO_C1S1 | 28.98 | 13.55 | +0.08 | -0.09 |
| 4 | piece-002/FEED_GREEN_TO_C3 | 42.54 | 15.51 | P04/FEED_GREEN_TO_C3 | 42.53 | 15.43 | -0.01 | -0.08 |
| 5 | piece-016/FEED_TO_C1S1 | 58.06 | 13.54 | P05/FEED_TO_C1S1 | 57.96 | 13.55 | -0.10 | +0.01 |
| 6 | piece-010/FEED_TO_C1S1 | 71.62 | 13.48 | P06/FEED_TO_C1S1 | 71.51 | 13.55 | -0.11 | +0.07 |
| 7 | piece-004/FEED_GREEN_TO_C3 | 85.10 | 15.53 | P07/FEED_GREEN_TO_C3 | 85.06 | 15.43 | -0.04 | -0.10 |
| 8 | piece-017/FEED_TO_C1S1 | 100.63 | 13.60 | P08/FEED_TO_C1S1 | 100.49 | 13.55 | -0.14 | -0.05 |
| 9 | piece-013/FEED_TO_C1S1 | 114.23 | 13.40 | P09/FEED_TO_C1S1 | 114.04 | 13.55 | -0.19 | +0.15 |
| 10 | piece-006/FEED_GREEN_TO_C3 | 127.64 | 15.47 | P10/FEED_GREEN_TO_C3 | 127.59 | 15.43 | -0.05 | -0.04 |
| 11 | piece-007/FEED_GREEN_TO_C3 | 201.90 | 15.37 | P11/FEED_GREEN_TO_C3 | 200.92 | 15.43 | -0.98 | +0.06 |
| 12 | piece-008/FEED_GREEN_TO_C3 | 242.45 | 15.44 | P12/FEED_GREEN_TO_C3 | 242.05 | 15.43 | -0.40 | -0.01 |
| 13 | piece-009/FEED_GREEN_TO_C3 | 322.56 | 15.41 | P13/FEED_GREEN_TO_C3 | 321.38 | 15.43 | -1.18 | +0.02 |
| 14 | piece-011/FEED_GREEN_TO_C3 | 403.71 | 15.47 | P14/FEED_GREEN_TO_C3 | 400.61 | 15.43 | -3.10 | -0.04 |
| 15 | piece-012/FEED_GREEN_TO_C3 | 445.06 | 15.68 | P15/FEED_GREEN_TO_C3 | 441.74 | 15.43 | -3.32 | -0.24 |
| 16 | piece-014/FEED_GREEN_TO_C3 | 523.01 | 15.78 | P16/FEED_GREEN_TO_C3 | 521.07 | 15.43 | -1.94 | -0.35 |
| 17 | piece-015/FEED_GREEN_TO_C3 | 565.99 | 15.86 | P17/FEED_GREEN_TO_C3 | 562.10 | 15.43 | -3.89 | -0.43 |
| 18 | piece-018/FEED_GREEN_TO_C3 | 644.47 | 15.83 | P18/FEED_GREEN_TO_C3 | 641.43 | 15.43 | -3.04 | -0.40 |

## xarm1

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-003/C1S2_TO_LASER | 30.69 | 15.29 | P02/C1S2_TO_LASER | 32.90 | 15.25 | +2.21 | -0.04 |
| 2 | piece-005/C1S2_TO_C2S1 | 45.99 | 15.79 | P03/C1S2_TO_C2S1 | 48.15 | 15.75 | +2.16 | -0.04 |
| 3 | piece-003/LASER_TO_C2S1 | 68.82 | 14.99 | P02/LASER_TO_C2S1 | 69.20 | 14.95 | +0.38 | -0.04 |
| 4 | piece-016/C1S2_TO_LASER | 83.82 | 15.14 | P05/C1S2_TO_LASER | 84.15 | 15.25 | +0.33 | +0.11 |
| 5 | piece-010/C1S2_TO_C2S1 | 98.98 | 15.70 | P06/C1S2_TO_C2S1 | 99.40 | 15.75 | +0.42 | +0.05 |
| 6 | piece-016/LASER_TO_C2S1 | 121.53 | 14.89 | P05/LASER_TO_C2S1 | 121.05 | 14.95 | -0.48 | +0.06 |
| 7 | piece-017/C1S2_TO_LASER | 136.42 | 15.27 | P08/C1S2_TO_LASER | 136.00 | 15.25 | -0.42 | -0.02 |
| 8 | piece-017/LASER_TO_C2S1 | 175.20 | 14.95 | P08/LASER_TO_C2S1 | 172.35 | 14.95 | -2.85 | -0.00 |
| 9 | piece-013/C1S2_TO_C2S1 | 205.52 | 15.71 | P09/C1S2_TO_C2S1 | 203.20 | 15.75 | -2.32 | +0.04 |

## laser

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-003/PROCESS_RED | 45.99 | 22.83 | P02/PROCESS_RED | 46.35 | 22.80 | +0.36 | -0.03 |
| 2 | piece-016/PROCESS_RED | 98.97 | 22.56 | P05/PROCESS_RED | 97.60 | 22.80 | -1.37 | +0.24 |
| 3 | piece-017/PROCESS_RED | 151.70 | 22.34 | P08/PROCESS_RED | 149.45 | 22.80 | -2.25 | +0.46 |

## robot2

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-005/CLASSIFY_C2S2_TO_BANTAM | 66.17 | 35.84 | P03/CLASSIFY_C2S2_TO_BANTAM | 71.30 | 36.30 | +5.13 | +0.46 |
| 2 | piece-003/CLASSIFY_C2S2_TO_C4 | 102.02 | 33.65 | P02/CLASSIFY_C2S2_TO_C4 | 107.60 | 34.60 | +5.58 | +0.95 |
| 3 | piece-010/CLASSIFY_C2S2_TO_IBS | 161.98 | 30.91 | P06/CLASSIFY_C2S2_TO_IBS | 160.00 | 30.85 | -1.98 | -0.06 |
| 4 | piece-016/CLASSIFY_C2S2_TO_C4 | 192.90 | 32.53 | P05/CLASSIFY_C2S2_TO_C4 | 190.85 | 33.60 | -2.05 | +1.07 |
| 5 | piece-017/CLASSIFY_C2S2_TO_C4 | 282.29 | 34.80 | P08/CLASSIFY_C2S2_TO_C4 | 280.35 | 33.60 | -1.94 | -1.20 |
| 6 | piece-013/CLASSIFY_C2S2_TO_IBS | 363.17 | 31.50 | P09/CLASSIFY_C2S2_TO_IBS | 359.65 | 30.85 | -3.52 | -0.65 |
| 7 | piece-005/BANTAM_TO_C4 | 394.67 | 36.30 | P03/BANTAM_TO_C4 | 390.50 | 36.40 | -4.17 | +0.09 |
| 8 | piece-010/IBS_TO_BANTAM | 430.98 | 36.90 | P06/IBS_TO_BANTAM | 426.90 | 36.90 | -4.08 | +0.00 |
| 9 | piece-010/BANTAM_TO_C4 | 517.00 | 36.78 | P06/BANTAM_TO_C4 | 512.30 | 36.40 | -4.70 | -0.38 |
| 10 | piece-013/IBS_TO_BANTAM | 553.78 | 37.13 | P09/IBS_TO_BANTAM | 548.70 | 36.90 | -5.08 | -0.23 |
| 11 | piece-013/BANTAM_TO_C4 | 639.23 | 36.55 | P09/BANTAM_TO_C4 | 634.10 | 36.40 | -5.13 | -0.15 |

## bantam

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-005/PROCESS_BLUE | 102.02 | 48.47 | P03/PROCESS_BLUE | 107.60 | 48.50 | +5.58 | +0.03 |
| 2 | piece-010/PROCESS_BLUE | 467.89 | 49.10 | P06/PROCESS_BLUE | 463.80 | 48.50 | -4.09 | -0.60 |
| 3 | piece-013/PROCESS_BLUE | 590.92 | 48.30 | P09/PROCESS_BLUE | 585.60 | 48.50 | -5.32 | +0.20 |

## robot1

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-001/UNLOAD_C3 | 21.70 | 47.75 | P01/UNLOAD_C3 | 21.50 | 39.60 | -0.20 | -8.15 |
| 2 | piece-002/UNLOAD_C3 | 69.45 | 40.45 | P04/UNLOAD_C3 | 64.10 | 39.60 | -5.35 | -0.85 |
| 3 | piece-004/UNLOAD_C3 | 109.90 | 40.49 | P07/UNLOAD_C3 | 106.60 | 39.60 | -3.30 | -0.89 |
| 4 | piece-003/UNLOAD_C4 | 150.40 | 39.03 | P02/UNLOAD_C4 | 147.30 | 38.20 | -3.10 | -0.83 |
| 5 | piece-006/UNLOAD_C3 | 189.43 | 40.48 | P10/UNLOAD_C3 | 185.50 | 41.10 | -3.93 | +0.62 |
| 6 | piece-007/UNLOAD_C3 | 229.92 | 40.74 | P11/UNLOAD_C3 | 226.60 | 41.10 | -3.32 | +0.36 |
| 7 | piece-016/UNLOAD_C4 | 270.67 | 38.97 | P05/UNLOAD_C4 | 267.70 | 38.20 | -2.97 | -0.77 |
| 8 | piece-008/UNLOAD_C3 | 309.64 | 41.17 | P12/UNLOAD_C3 | 305.90 | 41.10 | -3.74 | -0.07 |
| 9 | piece-017/UNLOAD_C4 | 350.81 | 39.91 | P08/UNLOAD_C4 | 347.00 | 38.20 | -3.81 | -1.70 |
| 10 | piece-009/UNLOAD_C3 | 390.72 | 41.26 | P13/UNLOAD_C3 | 385.20 | 41.10 | -5.52 | -0.16 |
| 11 | piece-011/UNLOAD_C3 | 431.99 | 40.96 | P14/UNLOAD_C3 | 426.30 | 41.10 | -5.69 | +0.14 |
| 12 | piece-005/UNLOAD_C4 | 472.96 | 36.84 | P03/UNLOAD_C4 | 467.40 | 38.20 | -5.56 | +1.36 |
| 13 | piece-012/UNLOAD_C3 | 509.81 | 41.76 | P15/UNLOAD_C3 | 505.60 | 41.10 | -4.21 | -0.66 |
| 14 | piece-014/UNLOAD_C3 | 551.57 | 42.43 | P16/UNLOAD_C3 | 546.70 | 41.10 | -4.87 | -1.33 |
| 15 | piece-010/UNLOAD_C4 | 594.00 | 37.19 | P06/UNLOAD_C4 | 587.80 | 38.20 | -6.20 | +1.01 |
| 16 | piece-015/UNLOAD_C3 | 631.20 | 41.25 | P17/UNLOAD_C3 | 626.00 | 41.10 | -5.20 | -0.15 |
| 17 | piece-018/UNLOAD_C3 | 672.45 | 41.35 | P18/UNLOAD_C3 | 667.10 | 41.10 | -5.35 | -0.25 |
| 18 | piece-013/UNLOAD_C4 | 713.81 | 37.51 | P09/UNLOAD_C4 | 708.20 | 38.20 | -5.61 | +0.69 |