# Comparación ciclo a ciclo — Simulación vs Realidad (post-fix feeding_rules)

Corrida real: `20260706_133931_RRRRRRBBBBBBGGGGGG`  |  Orden simulado: `['BLUE', 'BLUE', 'BLUE', 'BLUE', 'BLUE', 'BLUE', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'RED', 'RED', 'RED', 'RED', 'RED', 'RED']`


## xarm2

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | FEED_TO_C1S1 | 0.00 | 13.39 | FEED_TO_C1S1 | 0.00 | 13.55 | +0.00 | +0.16 |
| 2 | FEED_TO_C1S1 | 13.39 | 13.49 | FEED_TO_C1S1 | 13.55 | 13.55 | +0.16 | +0.06 |
| 3 | FEED_TO_C1S1 | 26.89 | 13.49 | FEED_TO_C1S1 | 27.10 | 13.55 | +0.21 | +0.06 |
| 4 | FEED_TO_C1S1 | 40.38 | 13.98 | FEED_TO_C1S1 | 40.65 | 13.55 | +0.27 | -0.43 |
| 5 | FEED_TO_C1S1 | 61.23 | 13.95 | FEED_TO_C1S1 | 65.30 | 13.55 | +4.07 | -0.40 |
| 6 | FEED_TO_C1S1 | 95.62 | 13.89 | FEED_TO_C1S1 | 95.15 | 13.55 | -0.47 | -0.35 |
| 7 | FEED_GREEN_TO_C3 | 109.52 | 15.51 | FEED_GREEN_TO_C3 | 108.70 | 15.43 | -0.82 | -0.08 |
| 8 | FEED_GREEN_TO_C3 | 144.13 | 15.45 | FEED_GREEN_TO_C3 | 144.23 | 15.43 | +0.10 | -0.02 |
| 9 | FEED_GREEN_TO_C3 | 184.54 | 15.57 | FEED_GREEN_TO_C3 | 182.76 | 15.43 | -1.78 | -0.14 |
| 10 | FEED_GREEN_TO_C3 | 225.03 | 15.57 | FEED_GREEN_TO_C3 | 221.29 | 15.43 | -3.74 | -0.14 |
| 11 | FEED_GREEN_TO_C3 | 265.76 | 15.49 | FEED_GREEN_TO_C3 | 261.22 | 15.43 | -4.54 | -0.06 |
| 12 | FEED_GREEN_TO_C3 | 343.83 | 15.57 | FEED_GREEN_TO_C3 | 339.45 | 15.43 | -4.38 | -0.14 |
| 13 | FEED_TO_C1S1 | 359.41 | 13.38 | FEED_TO_C1S1 | 354.88 | 13.55 | -4.53 | +0.17 |
| 14 | FEED_TO_C1S1 | 372.79 | 13.42 | FEED_TO_C1S1 | 368.43 | 13.55 | -4.36 | +0.13 |
| 15 | FEED_TO_C1S1 | 386.21 | 13.42 | FEED_TO_C1S1 | 381.98 | 13.55 | -4.23 | +0.13 |
| 16 | FEED_TO_C1S1 | 433.21 | 13.82 | FEED_TO_C1S1 | 428.33 | 13.55 | -4.88 | -0.27 |
| 17 | FEED_TO_C1S1 | 486.46 | 13.81 | FEED_TO_C1S1 | 479.48 | 13.55 | -6.98 | -0.26 |
| 18 | FEED_TO_C1S1 | 539.21 | 13.76 | FEED_TO_C1S1 | 530.73 | 13.55 | -8.48 | -0.21 |

## xarm1

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | C1S2_TO_C2S1 | 15.21 | 15.75 | C1S2_TO_C2S1 | 17.50 | 15.75 | +2.29 | +0.00 |
| 2 | C1S2_TO_C2S1 | 30.96 | 15.71 | C1S2_TO_C2S1 | 33.25 | 15.75 | +2.29 | +0.04 |
| 3 | C1S2_TO_C2S1 | 55.06 | 15.74 | C1S2_TO_C2S1 | 60.60 | 15.75 | +5.54 | +0.01 |
| 4 | C1S2_TO_C2S1 | 90.11 | 15.80 | C1S2_TO_C2S1 | 90.45 | 15.75 | +0.34 | -0.05 |
| 5 | C1S2_TO_C2S1 | 120.51 | 15.72 | C1S2_TO_C2S1 | 121.20 | 15.75 | +0.69 | +0.03 |
| 6 | C1S2_TO_C2S1 | 150.04 | 15.77 | C1S2_TO_C2S1 | 152.05 | 15.75 | +2.01 | -0.02 |
| 7 | C1S2_TO_LASER | 374.53 | 15.27 | C1S2_TO_LASER | 372.40 | 15.25 | -2.13 | -0.02 |
| 8 | LASER_TO_C2S1 | 412.87 | 14.91 | LASER_TO_C2S1 | 408.65 | 14.95 | -4.22 | +0.04 |
| 9 | C1S2_TO_LASER | 427.79 | 15.24 | C1S2_TO_LASER | 423.60 | 15.25 | -4.19 | +0.01 |
| 10 | LASER_TO_C2S1 | 465.68 | 14.96 | LASER_TO_C2S1 | 459.85 | 14.95 | -5.83 | -0.00 |
| 11 | C1S2_TO_LASER | 480.64 | 15.26 | C1S2_TO_LASER | 474.80 | 15.25 | -5.84 | -0.01 |
| 12 | LASER_TO_C2S1 | 518.24 | 14.99 | LASER_TO_C2S1 | 511.05 | 14.95 | -7.19 | -0.04 |
| 13 | C1S2_TO_LASER | 533.24 | 15.21 | C1S2_TO_LASER | 526.00 | 15.25 | -7.24 | +0.03 |
| 14 | LASER_TO_C2S1 | 570.97 | 15.02 | LASER_TO_C2S1 | 562.25 | 14.95 | -8.72 | -0.07 |
| 15 | C1S2_TO_LASER | 586.00 | 15.22 | C1S2_TO_LASER | 577.20 | 15.25 | -8.80 | +0.03 |
| 16 | LASER_TO_C2S1 | 623.76 | 14.96 | LASER_TO_C2S1 | 613.45 | 14.95 | -10.31 | -0.01 |
| 17 | C1S2_TO_LASER | 638.73 | 15.25 | C1S2_TO_LASER | 628.40 | 15.25 | -10.33 | -0.00 |
| 18 | LASER_TO_C2S1 | 676.58 | 15.06 | LASER_TO_C2S1 | 664.65 | 14.95 | -11.93 | -0.11 |

## laser

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | PROCESS_RED | 389.80 | 23.07 | PROCESS_RED | 385.85 | 22.80 | -3.95 | -0.26 |
| 2 | PROCESS_RED | 443.03 | 22.64 | PROCESS_RED | 437.05 | 22.80 | -5.98 | +0.16 |
| 3 | PROCESS_RED | 495.90 | 22.34 | PROCESS_RED | 488.25 | 22.80 | -7.65 | +0.46 |
| 4 | PROCESS_RED | 548.46 | 22.51 | PROCESS_RED | 539.45 | 22.80 | -9.01 | +0.29 |
| 5 | PROCESS_RED | 601.22 | 22.54 | PROCESS_RED | 590.65 | 22.80 | -10.57 | +0.26 |
| 6 | PROCESS_RED | 653.98 | 22.59 | PROCESS_RED | 641.85 | 22.80 | -12.13 | +0.21 |

## robot2

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | CLASSIFY_C2S2_TO_BANTAM | 35.10 | 41.90 | CLASSIFY_C2S2_TO_BANTAM | 40.70 | 36.30 | +5.60 | -5.60 |
| 2 | CLASSIFY_C2S2_TO_IBS | 77.01 | 30.46 | CLASSIFY_C2S2_TO_IBS | 77.00 | 31.85 | -0.01 | +1.39 |
| 3 | CLASSIFY_C2S2_TO_IBS | 107.48 | 30.48 | CLASSIFY_C2S2_TO_IBS | 108.85 | 30.85 | +1.37 | +0.37 |
| 4 | CLASSIFY_C2S2_TO_IBS | 137.96 | 29.56 | CLASSIFY_C2S2_TO_IBS | 139.70 | 30.85 | +1.74 | +1.29 |
| 5 | CLASSIFY_C2S2_TO_IBS | 167.53 | 30.47 | CLASSIFY_C2S2_TO_IBS | 170.55 | 30.85 | +3.02 | +0.38 |
| 6 | CLASSIFY_C2S2_TO_IBS | 198.00 | 30.53 | CLASSIFY_C2S2_TO_IBS | 201.40 | 30.85 | +3.40 | +0.32 |
| 7 | BANTAM_TO_C4 | 228.54 | 36.22 | BANTAM_TO_C4 | 232.25 | 36.40 | +3.71 | +0.18 |
| 8 | IBS_TO_BANTAM | 264.77 | 36.93 | IBS_TO_BANTAM | 268.65 | 36.90 | +3.88 | -0.03 |
| 9 | BANTAM_TO_C4 | 350.18 | 36.45 | BANTAM_TO_C4 | 354.05 | 36.40 | +3.87 | -0.06 |
| 10 | IBS_TO_BANTAM | 386.64 | 37.11 | IBS_TO_BANTAM | 390.45 | 36.90 | +3.81 | -0.21 |
| 11 | CLASSIFY_C2S2_TO_C4 | 432.06 | 33.26 | CLASSIFY_C2S2_TO_C4 | 431.15 | 33.60 | -0.91 | +0.34 |
| 12 | BANTAM_TO_C4 | 481.72 | 36.65 | CLASSIFY_C2S2_TO_C4 | 482.45 | 33.60 | +0.73 | -3.05 |
| 13 | IBS_TO_BANTAM | 518.37 | 36.86 | CLASSIFY_C2S2_TO_C4 | 533.75 | 33.60 | +15.38 | -3.26 |
| 14 | CLASSIFY_C2S2_TO_C4 | 555.24 | 33.45 | CLASSIFY_C2S2_TO_C4 | 585.05 | 33.60 | +29.81 | +0.15 |
| 15 | CLASSIFY_C2S2_TO_C4 | 605.66 | 33.62 | CLASSIFY_C2S2_TO_C4 | 636.35 | 33.60 | +30.69 | -0.02 |
| 16 | CLASSIFY_C2S2_TO_C4 | 656.25 | 33.48 | CLASSIFY_C2S2_TO_C4 | 687.65 | 33.60 | +31.40 | +0.12 |
| 17 | CLASSIFY_C2S2_TO_C4 | 706.30 | 33.38 | BANTAM_TO_C4 | 738.95 | 36.40 | +32.65 | +3.02 |
| 18 | CLASSIFY_C2S2_TO_C4 | 756.56 | 33.24 | IBS_TO_BANTAM | 775.35 | 36.90 | +18.79 | +3.66 |
| 19 | BANTAM_TO_C4 | 806.54 | 36.73 | BANTAM_TO_C4 | 860.75 | 36.40 | +54.21 | -0.34 |
| 20 | IBS_TO_BANTAM | 843.27 | 37.10 | IBS_TO_BANTAM | 897.15 | 36.90 | +53.88 | -0.20 |
| 21 | BANTAM_TO_C4 | 929.06 | 36.48 | BANTAM_TO_C4 | 982.55 | 36.40 | +53.49 | -0.08 |
| 22 | IBS_TO_BANTAM | 965.54 | 37.00 | IBS_TO_BANTAM | 1018.95 | 36.90 | +53.41 | -0.10 |
| 23 | BANTAM_TO_C4 | 1051.03 | 36.41 | BANTAM_TO_C4 | 1104.45 | 36.40 | +53.42 | -0.00 |

## bantam

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | PROCESS_BLUE | 77.01 | 48.88 | PROCESS_BLUE | 77.00 | 48.50 | -0.01 | -0.38 |
| 2 | PROCESS_BLUE | 301.70 | 48.47 | PROCESS_BLUE | 305.55 | 48.50 | +3.85 | +0.03 |
| 3 | PROCESS_BLUE | 423.75 | 48.68 | PROCESS_BLUE | 427.35 | 48.50 | +3.60 | -0.18 |
| 4 | PROCESS_BLUE | 555.24 | 48.30 | PROCESS_BLUE | 812.25 | 48.50 | +257.01 | +0.20 |
| 5 | PROCESS_BLUE | 880.38 | 48.67 | PROCESS_BLUE | 934.05 | 48.50 | +53.67 | -0.17 |
| 6 | PROCESS_BLUE | 1002.55 | 48.48 | PROCESS_BLUE | 1055.85 | 48.50 | +53.30 | +0.02 |

## robot1

| Ciclo | Tarea (real) | t_ini real (s) | dur real (s) | Tarea (sim) | t_ini sim (s) | dur sim (s) | Δ inicio (s) | Δ dur (s) |
|---|---|---|---|---|---|---|---|---|
| 1 | UNLOAD_C3 | 131.12 | 41.04 | UNLOAD_C3 | 130.30 | 38.50 | -0.82 | -2.54 |
| 2 | UNLOAD_C3 | 172.17 | 40.22 | UNLOAD_C3 | 168.80 | 38.50 | -3.37 | -1.72 |
| 3 | UNLOAD_C3 | 212.39 | 41.20 | UNLOAD_C3 | 207.30 | 38.50 | -5.09 | -2.70 |
| 4 | UNLOAD_C3 | 253.59 | 40.07 | UNLOAD_C3 | 245.80 | 40.00 | -7.79 | -0.07 |
| 5 | UNLOAD_C4 | 293.67 | 37.96 | UNLOAD_C4 | 285.80 | 38.20 | -7.87 | +0.24 |
| 6 | UNLOAD_C3 | 331.63 | 40.04 | UNLOAD_C3 | 324.00 | 40.00 | -7.63 | -0.04 |
| 7 | UNLOAD_C3 | 371.67 | 40.69 | UNLOAD_C3 | 364.00 | 40.00 | -7.67 | -0.69 |
| 8 | UNLOAD_C4 | 412.36 | 35.89 | UNLOAD_C4 | 404.00 | 38.20 | -8.36 | +2.31 |
| 9 | UNLOAD_C4 | 470.38 | 37.57 | UNLOAD_C4 | 469.80 | 38.20 | -0.58 | +0.63 |
| 10 | UNLOAD_C4 | 523.50 | 35.88 | UNLOAD_C4 | 521.10 | 38.20 | -2.40 | +2.32 |
| 11 | UNLOAD_C4 | 594.00 | 37.75 | UNLOAD_C4 | 572.40 | 38.20 | -21.60 | +0.45 |
| 12 | UNLOAD_C4 | 644.30 | 38.07 | UNLOAD_C4 | 623.70 | 38.20 | -20.60 | +0.13 |
| 13 | UNLOAD_C4 | 694.79 | 38.98 | UNLOAD_C4 | 675.00 | 38.20 | -19.79 | -0.78 |
| 14 | UNLOAD_C4 | 744.78 | 39.20 | UNLOAD_C4 | 726.30 | 38.20 | -18.48 | -1.00 |
| 15 | UNLOAD_C4 | 794.95 | 39.18 | UNLOAD_C4 | 780.40 | 38.20 | -14.55 | -0.98 |
| 16 | UNLOAD_C4 | 848.27 | 35.66 | UNLOAD_C4 | 902.20 | 38.20 | +53.93 | +2.53 |
| 17 | UNLOAD_C4 | 970.50 | 36.26 | UNLOAD_C4 | 1024.00 | 38.20 | +53.50 | +1.94 |
| 18 | UNLOAD_C4 | 1092.50 | 35.68 | UNLOAD_C4 | 1145.90 | 38.20 | +53.40 | +2.52 |