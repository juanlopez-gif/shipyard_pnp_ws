# Dynamic Map 5B/4R/0G Validation Notes

Date: 2026-07-12

## Hallazgo principal

La prueba `5B/4R/0G` valida otra mejora fisica importante del mapa dinamico.
La corrida dynamic `BBBBRRRBR` redujo el makespan real en `152.422 s`
respecto a la corrida fixed `BRRRRBBBB`.

Criterion for real production duration in all real comparisons:

- `t0`: start of the first `xarm2` cycle, including `WAITING_GLOBALVISION`.
- `t_fin`: end of `RETURNING_HOME` in the last `robot1` cycle.

## Comparacion real

| Scenario | Input stack | Applied stack | Politica / mapa | Sim time | Real run | Real time |
|---|---:|---:|---|---:|---|---:|
| Fixed reference | `BRRRRBBBB` | `BRRRRBBBB` | fixed priorities | `916.7 s` | `20260712_193110_BRRRRBBBB` | `899.789 s` |
| Mapa dinamico | `BRRRRBBBB` | `BBBBRRRBR` | `dynamic_5b4r0g_BBBBRRRBR_v1` | `759.8 s` | `20260712_194812_BRRRRBBBB` | `747.367 s` |

Quantified deltas:

- Dynamic real vs fixed real: `899.789 -> 747.367 s`, saving real
  `152.422 s` (`16.94%`).
- Dynamic sim vs fixed sim: `916.7 -> 759.8 s`, saving sim `156.9 s`
  (`17.12%`).
- Fixed real fidelity: `899.789 s` real vs `916.7 s` sim, diff
  `-16.911 s` (`-1.84%`).
- Dynamic real fidelity: `747.367 s` real vs `759.8 s` sim, diff
  `-12.433 s` (`-1.64%`).
- Real saving vs predicted saving: `152.422 s` real vs `156.9 s` simulated,
  `-4.478 s` (`-2.85%` relative to the predicted saving).

## Fixed run validation

```text
run_id:          20260712_193110_BRRRRBBBB
original stack:  BRRRRBBBB
applied stack:   BRRRRBBBB
map_mode:        fixed
t0:              2026-07-12T19:31:36.211531-04:00
t_fin:           2026-07-12T19:46:36.000545-04:00
real:            899.789 s
sim:             916.7 s
diff:            -16.911 s (-1.84%)
```

Cycle execution check:

```text
expected cycles: 57
real cycles:     57
matched:         53
followed map:     4
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
xarm1   C1S2_TO_C2S1              5
xarm1   C1S2_TO_LASER             4
xarm1   LASER_TO_C2S1             4
laser   PROCESS_RED               4
robot2  CLASSIFY_C2S2_TO_BANTAM   2
robot2  CLASSIFY_C2S2_TO_IBS      3
robot2  IBS_TO_BANTAM             3
robot2  BANTAM_TO_C4              5
robot2  CLASSIFY_C2S2_TO_C4       4
bantam  PROCESS_BLUE              5
robot1  UNLOAD_C4                 9
```

The four `followed` rows were controlled map waits, not failures:

```text
xarm1 LASER_TO_C2S1 #1 piece-002 RED waited 6.82 s
xarm1 LASER_TO_C2S1 #2 piece-003 RED waited 6.73 s
xarm1 LASER_TO_C2S1 #3 piece-004 RED waited 6.36 s
xarm1 LASER_TO_C2S1 #4 piece-005 RED waited 10.38 s
```

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['BLUE', 'RED', 'RED', 'RED', 'RED',
                   'BLUE', 'BLUE', 'BLUE', 'BLUE']; map_mode=fixed
```

## Dynamic run validation

Important validation detail: for this run the executed map is the
`expected_schedule` stored in `production_run.config_snapshot`. Running
`run_report.py` directly is not enough for dynamic-map validation, because the
current report tool reconstructs a fixed schedule from `optimized_order`.

```text
run_id:          20260712_194812_BRRRRBBBB
original stack:  BRRRRBBBB
applied stack:   BBBBRRRBR
map_mode:        dynamic
map_id:          dynamic_5b4r0g_BBBBRRRBR_v1
t0:              2026-07-12T19:48:37.188626-04:00
t_fin:           2026-07-12T20:01:04.555808-04:00
real:            747.367 s
sim:             759.8 s
diff:            -12.433 s (-1.64%)
```

Cycle execution check:

```text
expected cycles: 57
real cycles:     57
matched:         52
followed map:     5
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
xarm1   C1S2_TO_C2S1              5
xarm1   C1S2_TO_LASER             4
xarm1   LASER_TO_C2S1             4
laser   PROCESS_RED               4
robot2  CLASSIFY_C2S2_TO_BANTAM   2
robot2  CLASSIFY_C2S2_TO_IBS      3
robot2  IBS_TO_BANTAM             3
robot2  BANTAM_TO_C4              5
robot2  CLASSIFY_C2S2_TO_C4       4
bantam  PROCESS_BLUE              5
robot1  UNLOAD_C4                 9
```

The five `followed` rows were controlled map waits, not failures:

```text
xarm1  LASER_TO_C2S1 #1 piece-002 RED  waited 7.18 s
xarm1  LASER_TO_C2S1 #2 piece-003 RED  waited 6.71 s
xarm1  LASER_TO_C2S1 #3 piece-004 RED  waited 8.70 s
robot2 BANTAM_TO_C4 #2 piece-006 BLUE  waited 0.22 s
robot2 BANTAM_TO_C4 #3 piece-007 BLUE  waited 0.01 s
```

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['BLUE', 'BLUE', 'BLUE', 'BLUE', 'RED',
                   'RED', 'RED', 'BLUE', 'RED'];
             map_mode=dynamic; map_id=dynamic_5b4r0g_BBBBRRRBR_v1
```

## Final piece outcomes

Both runs completed all 9 pieces.

Fixed final destinations:

```text
BLUE: final_blue_circle=5
RED:  final_red_stack=3, final_red_circle=1
```

Dynamic final destinations:

```text
BLUE: final_blue_stack=1, final_blue_circle=4
RED:  final_red_stack=3, final_red_circle=1
```

## Conclusion

The `5B/4R/0G` dynamic map executed correctly and produced a real makespan
reduction of `152.422 s` (`16.94%`) against the fixed physical run. The
simulation fidelity stayed within `1.84%` for fixed and `1.64%` for dynamic,
and every expected cycle occurred with the expected entity/task/cycle number
and color.
