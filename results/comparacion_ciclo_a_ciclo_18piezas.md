# Comparación ciclo a ciclo — Simulación vs Realidad

Corrida real: `20260704_120002_RRRRRRBBBBBBGGGGGG`  |  Orden simulado: `['BLUE', 'BLUE', 'BLUE', 'BLUE', 'BLUE', 'BLUE', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'RED', 'RED', 'RED', 'RED', 'RED', 'RED']`


## xarm2

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | FEED_TO_C1S1 | 0.00 | 13.58 | FEED_TO_C1S1 | 0.00 | 11.55 | +0.00 | -2.03 |
| 2 | FEED_TO_C1S1 | 13.58 | 13.48 | FEED_TO_C1S1 | 13.55 | 11.55 | -0.03 | -1.93 |
| 3 | FEED_TO_C1S1 | 27.07 | 13.51 | FEED_TO_C1S1 | 27.10 | 11.55 | +0.03 | -1.96 |
| 4 | FEED_TO_C1S1 | 40.58 | 13.53 | FEED_TO_C1S1 | 40.65 | 11.55 | +0.07 | -1.98 |
| 5 | FEED_TO_C1S1 | 61.97 | 13.51 | FEED_TO_C1S1 | 65.30 | 11.55 | +3.33 | -1.96 |
| 6 | FEED_TO_C1S1 | 96.10 | 13.55 | FEED_TO_C1S1 | 95.15 | 11.55 | -0.95 | -2.00 |
| 7 | FEED_GREEN_TO_C3 | 126.43 | 15.53 | FEED_GREEN_TO_C3 | 108.70 | 11.50 | -17.73 | -4.03 |
| 8 | FEED_GREEN_TO_C3 | 160.86 | 15.44 | FEED_GREEN_TO_C3 | 144.23 | 11.50 | -16.63 | -3.94 |
| 9 | FEED_GREEN_TO_C3 | 201.34 | 15.47 | FEED_GREEN_TO_C3 | 182.76 | 11.50 | -18.58 | -3.97 |
| 10 | FEED_GREEN_TO_C3 | 241.46 | 15.40 | FEED_GREEN_TO_C3 | 221.29 | 11.50 | -20.17 | -3.90 |
| 11 | FEED_GREEN_TO_C3 | 321.93 | 15.90 | FEED_GREEN_TO_C3 | 261.22 | 11.50 | -60.71 | -4.40 |
| 12 | FEED_GREEN_TO_C3 | 362.02 | 15.71 | FEED_GREEN_TO_C3 | 339.45 | 11.50 | -22.57 | -4.21 |
| 13 | FEED_TO_C1S1 | 377.74 | 13.39 | FEED_TO_C1S1 | 354.88 | 11.55 | -22.86 | -1.84 |
| 14 | FEED_TO_C1S1 | 391.13 | 13.53 | FEED_TO_C1S1 | 368.43 | 11.55 | -22.70 | -1.98 |
| 15 | FEED_TO_C1S1 | 404.66 | 13.80 | FEED_TO_C1S1 | 381.98 | 11.55 | -22.68 | -2.25 |
| 16 | FEED_TO_C1S1 | 451.52 | 13.85 | FEED_TO_C1S1 | 414.93 | 11.55 | -36.59 | -2.30 |
| 17 | FEED_TO_C1S1 | 504.69 | 13.90 | FEED_TO_C1S1 | 452.68 | 11.55 | -52.01 | -2.35 |
| 18 | FEED_TO_C1S1 | 556.85 | 13.84 | FEED_TO_C1S1 | 490.53 | 11.55 | -66.32 | -2.29 |

## xarm1

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | C1S2_TO_C2S1 | 15.34 | 15.82 | C1S2_TO_C2S1 | 17.50 | 13.95 | +2.16 | -1.87 |
| 2 | C1S2_TO_C2S1 | 31.16 | 15.79 | C1S2_TO_C2S1 | 33.25 | 13.95 | +2.09 | -1.85 |
| 3 | C1S2_TO_C2S1 | 55.88 | 15.71 | C1S2_TO_C2S1 | 60.60 | 13.95 | +4.72 | -1.76 |
| 4 | C1S2_TO_C2S1 | 90.38 | 15.83 | C1S2_TO_C2S1 | 90.45 | 13.95 | +0.07 | -1.88 |
| 5 | C1S2_TO_C2S1 | 120.77 | 15.82 | C1S2_TO_C2S1 | 121.20 | 13.95 | +0.43 | -1.87 |
| 6 | C1S2_TO_C2S1 | 151.11 | 15.79 | C1S2_TO_C2S1 | 152.05 | 13.95 | +0.94 | -1.84 |
| 7 | C1S2_TO_LASER | 392.77 | 15.29 | C1S2_TO_LASER | 372.40 | 13.45 | -20.37 | -1.84 |
| 8 | LASER_TO_C2S1 | 430.84 | 15.01 | LASER_TO_C2S1 | 395.25 | 13.15 | -35.59 | -1.86 |
| 9 | C1S2_TO_LASER | 445.86 | 15.37 | C1S2_TO_LASER | 410.20 | 13.45 | -35.66 | -1.92 |
| 10 | LASER_TO_C2S1 | 483.94 | 15.02 | LASER_TO_C2S1 | 433.05 | 13.15 | -50.89 | -1.87 |
| 11 | C1S2_TO_LASER | 498.97 | 15.21 | C1S2_TO_LASER | 448.00 | 13.45 | -50.97 | -1.76 |
| 12 | LASER_TO_C2S1 | 536.23 | 14.94 | LASER_TO_C2S1 | 470.85 | 13.15 | -65.38 | -1.79 |
| 13 | C1S2_TO_LASER | 551.17 | 15.33 | C1S2_TO_LASER | 485.80 | 13.45 | -65.37 | -1.88 |
| 14 | LASER_TO_C2S1 | 589.67 | 15.01 | LASER_TO_C2S1 | 508.65 | 13.15 | -81.02 | -1.86 |
| 15 | C1S2_TO_LASER | 604.69 | 15.29 | C1S2_TO_LASER | 523.60 | 13.45 | -81.09 | -1.84 |
| 16 | LASER_TO_C2S1 | 642.26 | 14.95 | LASER_TO_C2S1 | 546.45 | 13.15 | -95.81 | -1.80 |
| 17 | C1S2_TO_LASER | 657.22 | 15.26 | C1S2_TO_LASER | 561.40 | 13.45 | -95.82 | -1.81 |
| 18 | LASER_TO_C2S1 | 694.86 | 14.97 | LASER_TO_C2S1 | 593.65 | 13.15 | -101.21 | -1.82 |

## laser

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | PROCESS_RED | 408.07 | 22.77 | PROCESS_RED | 372.40 | 22.80 | -35.67 | +0.03 |
| 2 | PROCESS_RED | 461.23 | 22.70 | PROCESS_RED | 410.20 | 22.80 | -51.03 | +0.10 |
| 3 | PROCESS_RED | 514.18 | 22.05 | PROCESS_RED | 448.00 | 22.80 | -66.18 | +0.75 |
| 4 | PROCESS_RED | 566.50 | 21.92 | PROCESS_RED | 485.80 | 22.80 | -80.70 | +0.88 |
| 5 | PROCESS_RED | 619.98 | 22.28 | PROCESS_RED | 523.60 | 22.80 | -96.38 | +0.52 |
| 6 | PROCESS_RED | 672.48 | 22.37 | PROCESS_RED | 561.40 | 22.80 | -111.08 | +0.43 |

## robot2

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | CLASSIFY_C2S2_TO_BANTAM | 35.43 | 41.99 | CLASSIFY_C2S2_TO_BANTAM | 40.70 | 33.80 | +5.27 | -8.19 |
| 2 | CLASSIFY_C2S2_TO_IBS | 77.43 | 30.50 | CLASSIFY_C2S2_TO_IBS | 77.00 | 25.20 | -0.43 | -5.30 |
| 3 | CLASSIFY_C2S2_TO_IBS | 107.93 | 30.23 | CLASSIFY_C2S2_TO_IBS | 108.85 | 24.20 | +0.92 | -6.02 |
| 4 | CLASSIFY_C2S2_TO_IBS | 138.16 | 30.55 | CLASSIFY_C2S2_TO_IBS | 139.70 | 24.20 | +1.54 | -6.35 |
| 5 | CLASSIFY_C2S2_TO_IBS | 168.71 | 30.68 | CLASSIFY_C2S2_TO_IBS | 170.55 | 24.20 | +1.84 | -6.48 |
| 6 | CLASSIFY_C2S2_TO_IBS | 199.39 | 30.58 | CLASSIFY_C2S2_TO_IBS | 201.40 | 24.20 | +2.01 | -6.38 |
| 7 | BANTAM_TO_C4 | 229.98 | 36.42 | BANTAM_TO_C4 | 232.25 | 26.90 | +2.27 | -9.52 |
| 8 | IBS_TO_BANTAM | 266.41 | 36.72 | IBS_TO_BANTAM | 268.65 | 27.30 | +2.24 | -9.42 |
| 9 | BANTAM_TO_C4 | 351.82 | 36.43 | BANTAM_TO_C4 | 354.05 | 26.90 | +2.23 | -9.53 |
| 10 | IBS_TO_BANTAM | 388.25 | 36.83 | IBS_TO_BANTAM | 390.45 | 27.30 | +2.20 | -9.53 |
| 11 | CLASSIFY_C2S2_TO_C4 | 450.16 | 34.19 | CLASSIFY_C2S2_TO_C4 | 427.35 | 24.10 | -22.81 | -10.09 |
| 12 | BANTAM_TO_C4 | 501.79 | 36.51 | CLASSIFY_C2S2_TO_C4 | 478.65 | 24.10 | -23.14 | -12.41 |
| 13 | IBS_TO_BANTAM | 538.31 | 36.88 | CLASSIFY_C2S2_TO_C4 | 529.95 | 24.10 | -8.36 | -12.78 |
| 14 | CLASSIFY_C2S2_TO_C4 | 575.20 | 34.59 | CLASSIFY_C2S2_TO_C4 | 581.25 | 24.10 | +6.05 | -10.49 |
| 15 | CLASSIFY_C2S2_TO_C4 | 627.17 | 34.50 | CLASSIFY_C2S2_TO_C4 | 632.55 | 24.10 | +5.38 | -10.40 |
| 16 | CLASSIFY_C2S2_TO_C4 | 679.15 | 34.03 | CLASSIFY_C2S2_TO_C4 | 683.85 | 24.10 | +4.70 | -9.93 |
| 17 | CLASSIFY_C2S2_TO_C4 | 730.81 | 34.12 | BANTAM_TO_C4 | 735.15 | 26.90 | +4.34 | -7.22 |
| 18 | CLASSIFY_C2S2_TO_C4 | 782.06 | 33.98 | IBS_TO_BANTAM | 771.55 | 27.30 | -10.51 | -6.68 |
| 19 | BANTAM_TO_C4 | 833.49 | 36.55 | BANTAM_TO_C4 | 856.95 | 26.90 | +23.46 | -9.65 |
| 20 | IBS_TO_BANTAM | 870.04 | 37.09 | IBS_TO_BANTAM | 893.35 | 27.30 | +23.31 | -9.79 |
| 21 | BANTAM_TO_C4 | 955.42 | 36.59 | BANTAM_TO_C4 | 978.75 | 26.90 | +23.33 | -9.69 |
| 22 | IBS_TO_BANTAM | 992.01 | 37.18 | IBS_TO_BANTAM | 1015.15 | 27.30 | +23.14 | -9.88 |
| 23 | BANTAM_TO_C4 | 1077.68 | 36.60 | BANTAM_TO_C4 | 1100.65 | 26.90 | +22.97 | -9.70 |

## bantam

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | PROCESS_BLUE | 77.42 | 49.12 | PROCESS_BLUE | 77.00 | 48.50 | -0.42 | -0.62 |
| 2 | PROCESS_BLUE | 303.13 | 48.69 | PROCESS_BLUE | 305.55 | 48.50 | +2.42 | -0.19 |
| 3 | PROCESS_BLUE | 425.09 | 48.88 | PROCESS_BLUE | 427.35 | 48.50 | +2.26 | -0.38 |
| 4 | PROCESS_BLUE | 575.19 | 48.89 | PROCESS_BLUE | 808.45 | 48.50 | +233.26 | -0.39 |
| 5 | PROCESS_BLUE | 907.14 | 48.27 | PROCESS_BLUE | 930.25 | 48.50 | +23.11 | +0.23 |
| 6 | PROCESS_BLUE | 1029.19 | 48.48 | PROCESS_BLUE | 1052.05 | 48.50 | +22.86 | +0.02 |

## robot1

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | UNLOAD_C3 | 148.11 | 40.88 | UNLOAD_C3 | 130.30 | 28.70 | -17.81 | -12.18 |
| 2 | UNLOAD_C3 | 188.99 | 40.29 | UNLOAD_C3 | 168.80 | 28.70 | -20.19 | -11.59 |
| 3 | UNLOAD_C3 | 229.29 | 40.04 | UNLOAD_C3 | 207.30 | 28.70 | -21.99 | -11.34 |
| 4 | UNLOAD_C4 | 271.50 | 38.07 | UNLOAD_C3 | 245.80 | 30.20 | -25.70 | -7.87 |
| 5 | UNLOAD_C3 | 309.57 | 40.05 | UNLOAD_C4 | 285.80 | 28.40 | -23.77 | -11.65 |
| 6 | UNLOAD_C3 | 349.63 | 40.36 | UNLOAD_C3 | 324.00 | 30.20 | -25.63 | -10.16 |
| 7 | UNLOAD_C4 | 393.23 | 35.75 | UNLOAD_C3 | 364.00 | 30.20 | -29.23 | -5.55 |
| 8 | UNLOAD_C3 | 428.99 | 41.34 | UNLOAD_C4 | 404.00 | 28.40 | -24.99 | -12.94 |
| 9 | UNLOAD_C4 | 489.41 | 39.98 | UNLOAD_C4 | 466.00 | 28.40 | -23.41 | -11.58 |
| 10 | UNLOAD_C4 | 543.27 | 37.21 | UNLOAD_C4 | 517.30 | 28.40 | -25.97 | -8.81 |
| 11 | UNLOAD_C4 | 614.88 | 39.63 | UNLOAD_C4 | 568.60 | 28.40 | -46.28 | -11.23 |
| 12 | UNLOAD_C4 | 666.81 | 40.00 | UNLOAD_C4 | 619.90 | 28.40 | -46.91 | -11.60 |
| 13 | UNLOAD_C4 | 718.25 | 40.34 | UNLOAD_C4 | 671.20 | 28.40 | -47.05 | -11.94 |
| 14 | UNLOAD_C4 | 769.95 | 38.41 | UNLOAD_C4 | 722.50 | 28.40 | -47.45 | -10.01 |
| 15 | UNLOAD_C4 | 821.19 | 39.63 | UNLOAD_C4 | 776.60 | 28.40 | -44.59 | -11.23 |
| 16 | UNLOAD_C4 | 875.26 | 36.59 | UNLOAD_C4 | 898.40 | 28.40 | +23.14 | -8.19 |
| 17 | UNLOAD_C4 | 997.14 | 36.47 | UNLOAD_C4 | 1020.20 | 28.40 | +23.06 | -8.07 |
| 18 | UNLOAD_C4 | 1119.43 | 36.53 | UNLOAD_C4 | 1142.10 | 28.40 | +22.67 | -8.13 |