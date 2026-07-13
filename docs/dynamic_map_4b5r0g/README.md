# Dynamic Map 4B/5R/0G Validation Notes

Date: 2026-07-12

## Hallazgo principal

La prueba `4B/5R/0G` confirma otra mejora fisica del mapa dinamico. La
corrida fixed `BRRRRRBBB` ya estaba bien calibrada contra simulacion, y la
corrida dinamica `BRRRBBRRB` redujo el makespan real en mas de dos minutos.

Criterion for real production duration in all real comparisons:

- `t0`: start of the first `xarm2` cycle, including `WAITING_GLOBALVISION`.
- `t_fin`: end of `RETURNING_HOME` in the last `robot1` cycle.

## Comparacion real

| Scenario | Input stack | Applied stack | Politica / mapa | Sim time | Real run | Real time |
|---|---:|---:|---|---:|---|---:|
| Fixed reference | `BRRRRRBBB` | `BRRRRRBBB` | fixed priorities | `815.2 s` | `20260712_184914_BRRRRRBBB` | `797.620 s` |
| Mapa dinamico | `BRRRRRBBB` | `BRRRBBRRB` | `dynamic_4b5r0g_BRRRBBRRB_v1` | `689.7 s` | `20260712_191153_BRRRRRBBB` | `668.900 s` |

Quantified deltas:

- Dynamic real vs fixed real: `797.620 -> 668.900 s`, saving real
  `128.720 s` (`16.14%`).
- Dynamic sim vs fixed sim: `815.2 -> 689.7 s`, saving sim `125.5 s`
  (`15.39%`).
- Fixed real fidelity: `797.620 s` real vs `815.2 s` sim, diff
  `-17.580 s` (`-2.16%`).
- Dynamic real fidelity: `668.900 s` real vs `689.7 s` sim, diff
  `-20.800 s` (`-3.02%`).
- Real saving vs predicted saving: `128.720 s` real vs `125.5 s` simulated,
  extra `+3.220 s` (`+2.57%` relative to the predicted saving).

## Fixed run validation

```text
run_id:          20260712_184914_BRRRRRBBB
original stack:  BRRRRRBBB
applied stack:   BRRRRRBBB
map_mode:        fixed
t0:              2026-07-12T18:49:37.965461-04:00
t_fin:           2026-07-12T19:02:55.585540-04:00
real:            797.620 s
sim:             815.2 s
diff:            -17.580 s (-2.16%)
```

Cycle execution check:

```text
expected cycles: 56
real cycles:     56
matched:         51
followed map:     5
timeout:          0
no_sim:           0
intruder:         0
discarded:        0
color mismatch:   0
completed pieces: 9/9
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
xarm2   FEED_TO_C1S1              9
xarm1   C1S2_TO_C2S1              4
xarm1   C1S2_TO_LASER             5
xarm1   LASER_TO_C2S1             5
laser   PROCESS_RED               5
robot2  CLASSIFY_C2S2_TO_BANTAM   2
robot2  CLASSIFY_C2S2_TO_IBS      2
robot2  IBS_TO_BANTAM             2
robot2  BANTAM_TO_C4              4
robot2  CLASSIFY_C2S2_TO_C4       5
bantam  PROCESS_BLUE              4
robot1  UNLOAD_C4                 9
```

The five `followed` rows were controlled map waits, not failures:

```text
xarm1 LASER_TO_C2S1 #1 piece-002 RED waited 6.95 s
xarm1 LASER_TO_C2S1 #2 piece-003 RED waited 6.78 s
xarm1 LASER_TO_C2S1 #3 piece-004 RED waited 7.02 s
xarm1 LASER_TO_C2S1 #4 piece-005 RED waited 6.81 s
xarm1 LASER_TO_C2S1 #5 piece-006 RED waited 4.59 s
```

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['BLUE', 'RED', 'RED', 'RED', 'RED', 'RED',
                   'BLUE', 'BLUE', 'BLUE']; map_mode=fixed
```

## Dynamic run validation

Important validation detail: for this run the executed map is the
`expected_schedule` stored in `production_run.config_snapshot`. Running
`run_report.py` directly is not enough for dynamic-map validation, because the
current report tool reconstructs a fixed schedule from `optimized_order`.

```text
run_id:          20260712_191153_BRRRRRBBB
original stack:  BRRRRRBBB
applied stack:   BRRRBBRRB
map_mode:        dynamic
map_id:          dynamic_4b5r0g_BRRRBBRRB_v1
t0:              2026-07-12T19:12:16.812950-04:00
t_fin:           2026-07-12T19:23:25.713424-04:00
real:            668.900 s
sim:             689.7 s
diff:            -20.800 s (-3.02%)
```

Cycle execution check:

```text
expected cycles: 54
real cycles:     54
matched:         48
followed map:     6
timeout:          0
no_sim:           0
intruder:         0
discarded:        0
color mismatch:   0
completed pieces: 9/9
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
xarm2   FEED_TO_C1S1              9
xarm1   C1S2_TO_C2S1              4
xarm1   C1S2_TO_LASER             5
xarm1   LASER_TO_C2S1             5
laser   PROCESS_RED               5
robot2  CLASSIFY_C2S2_TO_BANTAM   4
robot2  BANTAM_TO_C4              4
robot2  CLASSIFY_C2S2_TO_C4       5
bantam  PROCESS_BLUE              4
robot1  UNLOAD_C4                 9
```

The six `followed` rows were controlled map waits, not failures:

```text
xarm1  LASER_TO_C2S1 #1 piece-002 RED  waited 6.66 s
xarm1  LASER_TO_C2S1 #2 piece-003 RED  waited 6.18 s
xarm1  LASER_TO_C2S1 #3 piece-004 RED  waited 0.49 s
xarm1  LASER_TO_C2S1 #4 piece-005 RED  waited 6.49 s
robot2 BANTAM_TO_C4 #2 piece-007 BLUE  waited 0.66 s
robot2 BANTAM_TO_C4 #3 piece-008 BLUE  waited 1.21 s
```

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['BLUE', 'RED', 'RED', 'RED', 'BLUE', 'BLUE',
                   'RED', 'RED', 'BLUE'];
             map_mode=dynamic; map_id=dynamic_4b5r0g_BRRRBBRRB_v1
```

## Final piece outcomes

Both runs completed all 9 pieces.

Fixed and dynamic final destination counts were identical:

```text
BLUE: final_blue_circle=4
RED:  final_red_stack=2, final_red_circle=3
```

## Conclusion

The `4B/5R/0G` dynamic map executed correctly and produced a real makespan
reduction of `128.720 s` (`16.14%`) against the fixed physical run. The
simulation fidelity stayed within `3.02%`, and every expected cycle occurred
with the expected entity/task/cycle number and color.
