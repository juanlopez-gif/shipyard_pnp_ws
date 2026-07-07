# Comparación ciclo a ciclo — 10 piezas (7G/1R/2B)

Corrida real: `20260706_184436_GGRGBGGGGB`  |  Orden dispatch simulado: `['GREEN', 'BLUE', 'RED', 'GREEN', 'BLUE', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN']`


## xarm2

| Ciclo | Pieza/Tarea (real) | t_ini real (s) | dur real (s) | Pieza/Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-001/FEED_GREEN_TO_C3 | 0.00 | 16.96 | P01/FEED_GREEN_TO_C3 | 0.00 | 15.43 | +0.00 | -1.53 |
| 2 | piece-005/FEED_TO_C1S1 | 16.97 | 14.71 | P02/FEED_TO_C1S1 | 15.43 | 13.55 | -1.54 | -1.15 |
| 3 | piece-003/FEED_TO_C1S1 | 31.67 | 14.62 | P03/FEED_TO_C1S1 | 28.98 | 13.55 | -2.69 | -1.07 |
| 4 | piece-002/FEED_GREEN_TO_C3 | 46.29 | 16.26 | P04/FEED_GREEN_TO_C3 | 42.53 | 15.43 | -3.76 | -0.83 |
| 5 | piece-010/FEED_TO_C1S1 | 62.55 | 14.79 | P05/FEED_TO_C1S1 | 57.96 | 13.55 | -4.59 | -1.24 |
| 6 | piece-004/FEED_GREEN_TO_C3 | 80.01 | 16.69 | P06/FEED_GREEN_TO_C3 | 78.01 | 15.43 | -2.00 | -1.26 |
| 7 | piece-006/FEED_GREEN_TO_C3 | 118.95 | 16.48 | P07/FEED_GREEN_TO_C3 | 117.64 | 15.43 | -1.31 | -1.05 |
| 8 | piece-007/FEED_GREEN_TO_C3 | 158.07 | 16.52 | P08/FEED_GREEN_TO_C3 | 158.77 | 15.43 | +0.70 | -1.09 |
| 9 | piece-008/FEED_GREEN_TO_C3 | 233.35 | 16.41 | P09/FEED_GREEN_TO_C3 | 238.10 | 15.43 | +4.75 | -0.98 |
| 10 | piece-009/FEED_GREEN_TO_C3 | 307.20 | 16.40 | P10/FEED_GREEN_TO_C3 | 317.33 | 15.43 | +10.13 | -0.97 |

## xarm1

| Ciclo | Pieza/Tarea (real) | t_ini real (s) | dur real (s) | Pieza/Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-005/C1S2_TO_C2S1 | 33.43 | 15.63 | P02/C1S2_TO_C2S1 | 32.90 | 15.75 | -0.53 | +0.12 |
| 2 | piece-003/C1S2_TO_LASER | 49.06 | 15.16 | P03/C1S2_TO_LASER | 48.65 | 15.25 | -0.41 | +0.09 |
| 3 | piece-003/LASER_TO_C2S1 | 86.63 | 8.20 | P05/C1S2_TO_C2S1 | 75.40 | 15.75 | -11.23 | +7.55 |
| 4 | piece-003/LASER_TO_C2S1 | 94.83 | 14.91 | P03/LASER_TO_C2S1 | 91.15 | 14.95 | -3.68 | +0.04 |

## laser

| Ciclo | Pieza/Tarea (real) | t_ini real (s) | dur real (s) | Pieza/Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-003/PROCESS_RED | 64.23 | 22.39 | P03/PROCESS_RED | 62.10 | 22.80 | -2.13 | +0.41 |

## robot2

| Ciclo | Pieza/Tarea (real) | t_ini real (s) | dur real (s) | Pieza/Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-005/CLASSIFY_C2S2_TO_BANTAM | 53.80 | 34.26 | P02/CLASSIFY_C2S2_TO_BANTAM | 56.10 | 36.30 | +2.30 | +2.04 |
| 2 | piece-010/CLASSIFY_C2S2_TO_IBS | 99.16 | 29.42 | P05/CLASSIFY_C2S2_TO_IBS | 98.60 | 31.85 | -0.56 | +2.43 |
| 3 | piece-003/CLASSIFY_C2S2_TO_C4 | 128.59 | 31.88 | P03/CLASSIFY_C2S2_TO_C4 | 130.45 | 33.60 | +1.86 | +1.72 |
| 4 | piece-005/BANTAM_TO_C4 | 196.02 | 36.57 | P02/BANTAM_TO_C4 | 197.05 | 36.40 | +1.03 | -0.17 |
| 5 | piece-010/IBS_TO_BANTAM | 232.60 | 37.10 | P05/IBS_TO_BANTAM | 233.45 | 36.90 | +0.85 | -0.20 |
| 6 | piece-010/BANTAM_TO_C4 | 318.60 | 36.87 | P05/BANTAM_TO_C4 | 318.85 | 36.40 | +0.25 | -0.47 |

## bantam

| Ciclo | Pieza/Tarea (real) | t_ini real (s) | dur real (s) | Pieza/Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-005/PROCESS_BLUE | 88.06 | 48.37 | P02/PROCESS_BLUE | 92.40 | 48.50 | +4.34 | +0.13 |
| 2 | piece-010/PROCESS_BLUE | 269.71 | 48.88 | P05/PROCESS_BLUE | 270.35 | 48.50 | +0.64 | -0.38 |

## robot1

| Ciclo | Pieza/Tarea (real) | t_ini real (s) | dur real (s) | Pieza/Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | piece-001/UNLOAD_C3 | 22.94 | 44.05 | P01/UNLOAD_C3 | 21.50 | 39.60 | -1.44 | -4.45 |
| 2 | piece-002/UNLOAD_C3 | 68.66 | 39.26 | P04/UNLOAD_C3 | 64.10 | 39.60 | -4.56 | +0.34 |
| 3 | piece-004/UNLOAD_C3 | 107.92 | 39.05 | P06/UNLOAD_C3 | 103.70 | 39.60 | -4.22 | +0.55 |
| 4 | piece-006/UNLOAD_C3 | 146.97 | 38.69 | P07/UNLOAD_C3 | 143.30 | 41.10 | -3.67 | +2.41 |
| 5 | piece-003/UNLOAD_C4 | 185.66 | 36.34 | P03/UNLOAD_C4 | 184.40 | 38.20 | -1.26 | +1.86 |
| 6 | piece-007/UNLOAD_C3 | 222.01 | 39.38 | P08/UNLOAD_C3 | 222.60 | 41.10 | +0.59 | +1.72 |
| 7 | piece-005/UNLOAD_C4 | 261.39 | 34.60 | P02/UNLOAD_C4 | 263.70 | 38.20 | +2.31 | +3.60 |
| 8 | piece-008/UNLOAD_C3 | 296.00 | 39.06 | P09/UNLOAD_C3 | 301.90 | 41.10 | +5.90 | +2.04 |
| 9 | piece-009/UNLOAD_C3 | 335.06 | 38.89 | P10/UNLOAD_C3 | 343.00 | 41.10 | +7.94 | +2.21 |
| 10 | piece-010/UNLOAD_C4 | 373.95 | 34.34 | P05/UNLOAD_C4 | 384.10 | 38.20 | +10.15 | +3.86 |