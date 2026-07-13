# Dynamic Map 5B/5R/5G Validation Notes

Date: 2026-07-12

## Hallazgo principal

La prueba `5B/5R/5G` valida el mapa dinamico en una corrida de 15 piezas. El
mapa `BGRBGGGRRBRBRGB` redujo el makespan real en `152.218 s` frente a la
corrida fixed `RBBGGGGBGBRRRRB`, y la mejora real quedo practicamente clavada
a la prediccion simulada.

Criterion for real production duration in all real comparisons:

- `t0`: start of the first `xarm2` cycle, including `WAITING_GLOBALVISION`.
- `t_fin`: end of `RETURNING_HOME` in the last `robot1` cycle.

## Comparacion real

| Scenario | Input stack | Applied stack | Politica / mapa | Sim time | Real run | Real time |
|---|---:|---:|---|---:|---|---:|
| Fixed reference | `RBBGGGGBGBRRRRB` | `RBBGGGGBGBRRRRB` | fixed priorities | `963.8 s` | `20260712_202104_RBBGGGGBGBRRRRB` | `952.436 s` |
| Mapa dinamico | `RBBGGGGBGBRRRRB` | `BGRBGGGRRBRBRGB` | `dynamic_5b5r5g_BGRBGGGRRBRBRGB_v1` | `811.7 s` | `20260712_203824_RBBGGGGBGBRRRRB` | `800.218 s` |

Quantified deltas:

- Dynamic real vs fixed real: `952.436 -> 800.218 s`, saving real
  `152.218 s` (`15.98%`).
- Dynamic sim vs fixed sim: `963.8 -> 811.7 s`, saving sim `152.1 s`
  (`15.78%`).
- Fixed real fidelity: `952.436 s` real vs `963.8 s` sim, diff
  `-11.364 s` (`-1.18%`).
- Dynamic real fidelity: `800.218 s` real vs `811.7 s` sim, diff
  `-11.482 s` (`-1.41%`).
- Real saving vs predicted saving: `152.218 s` real vs `152.1 s` simulated,
  extra `+0.118 s` (`+0.08%` relative to the predicted saving).

## Fixed run validation

```text
run_id:          20260712_202104_RBBGGGGBGBRRRRB
original stack:  RBBGGGGBGBRRRRB
applied stack:   RBBGGGGBGBRRRRB
map_mode:        fixed
t0:              2026-07-12T20:21:26.874103-04:00
t_fin:           2026-07-12T20:37:19.310252-04:00
real:            952.436 s
sim:             963.8 s
diff:            -11.364 s (-1.18%)
```

Cycle execution check:

```text
expected cycles: 74
real cycles:     74
matched:         71
followed map:     3
timeout:          0
no_sim:           0
intruder:         0
discarded:        0
color mismatch:   0
completed pieces: 15/15
```

Per-entity cycle order matched the expected schedule:

```text
xarm2:  OK
xarm1:  OK
laser:  OK
robot2: OK
bantam: OK
robot1: OK
```

Task counts:

```text
xarm2   FEED_TO_C1S1              10
xarm2   FEED_GREEN_TO_C3           5
xarm1   C1S2_TO_C2S1               5
xarm1   C1S2_TO_LASER              5
xarm1   LASER_TO_C2S1              5
laser   PROCESS_RED                5
robot2  CLASSIFY_C2S2_TO_BANTAM    1
robot2  CLASSIFY_C2S2_TO_IBS       4
robot2  IBS_TO_BANTAM              4
robot2  BANTAM_TO_C4               5
robot2  CLASSIFY_C2S2_TO_C4        5
bantam  PROCESS_BLUE               5
robot1  UNLOAD_C3                  5
robot1  UNLOAD_C4                 10
```

The three `followed` rows were controlled map waits, not failures:

```text
xarm1 LASER_TO_C2S1 #2 piece-011 RED waited 6.69 s
xarm1 LASER_TO_C2S1 #3 piece-012 RED waited 6.61 s
xarm1 LASER_TO_C2S1 #4 piece-013 RED waited 6.95 s
```

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['RED', 'BLUE', 'BLUE', 'GREEN', 'GREEN', 'GREEN',
                   'GREEN', 'BLUE', 'GREEN', 'BLUE', 'RED', 'RED',
                   'RED', 'RED', 'BLUE']; map_mode=fixed
```

## Dynamic run validation

Important validation detail: for this run the executed map is the
`expected_schedule` stored in `production_run.config_snapshot`. Running
`run_report.py` directly is not enough for dynamic-map validation, because the
current report tool reconstructs a fixed schedule from `optimized_order`.

```text
run_id:          20260712_203824_RBBGGGGBGBRRRRB
original stack:  RBBGGGGBGBRRRRB
applied stack:   BGRBGGGRRBRBRGB
map_mode:        dynamic
map_id:          dynamic_5b5r5g_BGRBGGGRRBRBRGB_v1
t0:              2026-07-12T20:38:57.008987-04:00
t_fin:           2026-07-12T20:52:17.226541-04:00
real:            800.218 s
sim:             811.7 s
diff:            -11.482 s (-1.41%)
```

Cycle execution check:

```text
expected cycles: 72
real cycles:     72
matched:         67
followed map:     5
timeout:          0
no_sim:           0
intruder:         0
discarded:        0
color mismatch:   0
completed pieces: 15/15
```

Per-entity cycle order matched the stored dynamic map:

```text
xarm2:  OK
xarm1:  OK
laser:  OK
robot2: OK
bantam: OK
robot1: OK
```

Task counts:

```text
xarm2   FEED_TO_C1S1              10
xarm2   FEED_GREEN_TO_C3           5
xarm1   C1S2_TO_C2S1               5
xarm1   C1S2_TO_LASER              5
xarm1   LASER_TO_C2S1              5
laser   PROCESS_RED                5
robot2  CLASSIFY_C2S2_TO_BANTAM    3
robot2  CLASSIFY_C2S2_TO_IBS       2
robot2  IBS_TO_BANTAM              2
robot2  BANTAM_TO_C4               5
robot2  CLASSIFY_C2S2_TO_C4        5
bantam  PROCESS_BLUE               5
robot1  UNLOAD_C3                  5
robot1  UNLOAD_C4                 10
```

The five `followed` rows were controlled map waits, not failures:

```text
xarm1  LASER_TO_C2S1 #2 piece-011 RED  waited 7.12 s
xarm1  LASER_TO_C2S1 #3 piece-012 RED  waited 8.25 s
xarm1  LASER_TO_C2S1 #4 piece-013 RED  waited 7.84 s
robot2 BANTAM_TO_C4 #3 piece-008 BLUE  waited 0.32 s
robot2 BANTAM_TO_C4 #4 piece-010 BLUE  waited 0.90 s
```

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['BLUE', 'GREEN', 'RED', 'BLUE', 'GREEN', 'GREEN',
                   'GREEN', 'RED', 'RED', 'BLUE', 'RED', 'BLUE',
                   'RED', 'GREEN', 'BLUE'];
             map_mode=dynamic; map_id=dynamic_5b5r5g_BGRBGGGRRBRBRGB_v1
```

## Final piece outcomes

Both runs completed all 15 pieces.

Fixed final destinations:

```text
BLUE:  final_blue_circle=5
GREEN: final_green_circle=5
RED:   final_red_stack=3, final_red_circle=2
```

Dynamic final destinations:

```text
BLUE:  final_blue_circle=5
GREEN: final_green_circle=5
RED:   final_red_stack=4, final_red_circle=1
```

## Conclusion

The `5B/5R/5G` dynamic map executed correctly and produced a real makespan
reduction of `152.218 s` (`15.98%`) against the fixed physical run. The
simulation fidelity stayed within `1.41%`, and every expected cycle occurred
with the expected entity/task/cycle number and color.
