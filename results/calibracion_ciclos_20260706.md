# Calibración de ciclos — comparación real vs modelo

Corridas usadas (5):

- `20260706_115456_RRRRRRBBBBBBGGGGGG`
- `20260704_120002_RRRRRRBBBBBBGGGGGG`
- `20260704_112132_RRRRRRBBBBBB`
- `20260703_184708_RRRRRRBBBBBB`
- `20260703_180733_GGGBGR`

| Entidad | Tarea | n | Real avg (s) | min | max | std | Nominal (s) | Diff (s) | Diff % | Estado |
|---|---|---|---|---|---|---|---|---|---|---|
| bantam | PROCESS_BLUE | 25 | 48.75 | 48.27 | 49.12 | 0.24 | 48.50 | +0.25 | +0.5% | OK |
| laser | PROCESS_RED | 25 | 22.71 | 21.92 | 24.56 | 0.71 | 22.80 | -0.09 | -0.4% | OK |
| robot1 | UNLOAD_C3 | 16 | 40.63 | 39.47 | 45.52 | 1.35 | 40.00 | +0.63 | +1.6% | OK |
| robot1 | UNLOAD_C4 | 50 | 37.54 | 35.06 | 40.34 | 1.53 | 38.20 | -0.66 | -1.7% | OK |
| robot2 | BANTAM_TO_C4 | 25 | 36.5 | 36.26 | 36.8 | 0.14 | 36.40 | +0.10 | +0.3% | OK |
| robot2 | CLASSIFY_C2S2_TO_BANTAM | 6 | 39.4 | 34.9 | 42.42 | 3.2 | 36.30 | +3.10 | +8.5% | REVISAR |
| robot2 | CLASSIFY_C2S2_TO_C4 | 25 | 33.55 | 32.86 | 34.59 | 0.45 | 33.60 | -0.05 | -0.1% | OK |
| robot2 | CLASSIFY_C2S2_TO_IBS | 19 | 30.52 | 30.19 | 30.82 | 0.17 | 30.85 | -0.33 | -1.1% | OK |
| robot2 | IBS_TO_BANTAM | 19 | 37.06 | 36.72 | 37.51 | 0.18 | 36.90 | +0.16 | +0.4% | OK |
| xarm1 | C1S2_TO_C2S1 | 25 | 15.78 | 15.67 | 15.87 | 0.05 | 15.75 | +0.03 | +0.2% | OK |
| xarm1 | C1S2_TO_LASER | 25 | 15.27 | 15.18 | 15.37 | 0.05 | 15.25 | +0.02 | +0.1% | OK |
| xarm1 | LASER_TO_C2S1 | 25 | 14.97 | 14.89 | 15.06 | 0.04 | 14.95 | +0.02 | +0.1% | OK |
| xarm2 | FEED_GREEN_TO_C3 | 16 | 15.53 | 15.38 | 15.9 | 0.14 | 15.43 | +0.10 | +0.7% | OK |
| xarm2 | FEED_TO_C1S1 | 50 | 13.61 | 13.36 | 13.92 | 0.15 | 13.55 | +0.06 | +0.4% | OK |

**Estado**: OK = <5% diff · REVISAR = 5-15% · DESCALIBRADO = >15% · SIN_MODELO = tarea sin fórmula nominal definida arriba.
