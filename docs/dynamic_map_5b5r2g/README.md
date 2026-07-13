# Dynamic Map 5B/5R/2G Validation Notes

Date: 2026-07-12

## Hallazgo principal

La prueba `5B/5R/2G` confirma que el mapa dinamico mantiene fidelidad de
simulacion en una corrida de 12 piezas y mejora claramente el makespan real.

Criterion for real production duration in all real comparisons:

- `t0`: start of the first `xarm2` cycle, including `WAITING_GLOBALVISION`.
- `t_fin`: end of `RETURNING_HOME` in the last `robot1` cycle.

## Comparacion real

| Scenario | Input stack | Applied stack | Politica / mapa | Sim time | Real run | Real time |
|---|---:|---:|---|---:|---|---:|
| Fixed reference | `BRRRRBBBBRGG` | `BRRRRBBBBRGG` | fixed priorities | `968.0 s` | `20260712_154351_BRRRRBBBBRGG` | `949.410 s` |
| Mapa dinamico | `BRRRRBBBBRGG` | `BBRGRRBRBRGB` | `dynamic_5b5r2g_BBRGRRBRBRGB_v1` | `796.7 s` | `20260712_160056_BRRRRBBBBRGG` | `775.495 s` |

Quantified deltas:

- Dynamic real vs fixed real: `949.410 -> 775.495 s`, saving real
  `173.915 s` (`18.32%`).
- Dynamic sim vs fixed sim: `968.0 -> 796.7 s`, saving sim `171.3 s`
  (`17.70%`).
- Fixed real fidelity: `949.410 s` real vs `968.0 s` sim, diff
  `-18.590 s` (`-1.92%`).
- Dynamic real fidelity: `775.495 s` real vs `796.7 s` sim, diff
  `-21.205 s` (`-2.66%`).
- Real saving vs predicted saving: `173.915 s` real vs `171.3 s` simulated,
  extra `+2.615 s` (`+1.53%` relative to the predicted saving).

## Fixed run validation

```text
run_id:          20260712_154351_BRRRRBBBBRGG
original stack:  BRRRRBBBBRGG
applied stack:   BRRRRBBBBRGG
map_mode:        fixed
t0:              2026-07-12T15:44:25.078777-04:00
t_fin:           2026-07-12T16:00:14.489024-04:00
real:            949.410 s
sim:             968.0 s
diff:            -18.590 s (-1.92%)
```

Cycle execution check:

```text
expected cycles: 67
real cycles:     67
matched:         63
followed map:     4
timeout:          0
no_sim:           0
intruder:         0
discarded:        0
color mismatch:   0
completed pieces: 12/12
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
xarm2   FEED_GREEN_TO_C3           2
xarm1   C1S2_TO_C2S1               5
xarm1   C1S2_TO_LASER              5
xarm1   LASER_TO_C2S1              5
laser   PROCESS_RED                5
robot2  CLASSIFY_C2S2_TO_BANTAM    2
robot2  CLASSIFY_C2S2_TO_IBS       3
robot2  IBS_TO_BANTAM              3
robot2  BANTAM_TO_C4               5
robot2  CLASSIFY_C2S2_TO_C4        5
bantam  PROCESS_BLUE               5
robot1  UNLOAD_C3                  2
robot1  UNLOAD_C4                 10
```

The four `followed` rows were controlled map waits, not failures:

```text
xarm1 LASER_TO_C2S1 #1 piece-002 RED waited 6.52 s
xarm1 LASER_TO_C2S1 #2 piece-003 RED waited 7.04 s
xarm1 LASER_TO_C2S1 #3 piece-004 RED waited 6.85 s
xarm1 LASER_TO_C2S1 #4 piece-005 RED waited 10.47 s
```

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['BLUE', 'RED', 'RED', 'RED', 'RED', 'BLUE',
                   'BLUE', 'BLUE', 'BLUE', 'RED', 'GREEN', 'GREEN'];
             map_mode=fixed
```

## Dynamic run validation

Important validation detail: for this run the executed map is the
`expected_schedule` stored in `production_run.config_snapshot`. Running
`run_report.py` directly is not enough for dynamic-map validation, because the
current report tool reconstructs a fixed schedule from `optimized_order`.

```text
run_id:          20260712_160056_BRRRRBBBBRGG
original stack:  BRRRRBBBBRGG
applied stack:   BBRGRRBRBRGB
map_mode:        dynamic
map_id:          dynamic_5b5r2g_BBRGRRBRBRGB_v1
t0:              2026-07-12T16:01:32.459957-04:00
t_fin:           2026-07-12T16:14:27.955225-04:00
real:            775.495 s
sim:             796.7 s
diff:            -21.205 s (-2.66%)
```

Cycle execution check:

```text
expected cycles: 66
real cycles:     66
matched:         60
followed map:     6
timeout:          0
no_sim:           0
intruder:         0
discarded:        0
color mismatch:   0
completed pieces: 12/12
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
xarm2   FEED_GREEN_TO_C3           2
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
robot1  UNLOAD_C3                  2
robot1  UNLOAD_C4                 10
```

The six `followed` rows were controlled map waits, not failures:

```text
xarm1  LASER_TO_C2S1 #1 piece-002 RED  waited 7.61 s
xarm1  LASER_TO_C2S1 #2 piece-003 RED  waited 6.65 s
xarm1  LASER_TO_C2S1 #3 piece-004 RED  waited 5.64 s
xarm1  LASER_TO_C2S1 #4 piece-005 RED  waited 7.77 s
robot2 BANTAM_TO_C4 #3 piece-007 BLUE  waited 0.21 s
robot2 BANTAM_TO_C4 #4 piece-008 BLUE  waited 0.63 s
```

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['BLUE', 'BLUE', 'RED', 'GREEN', 'RED', 'RED',
                   'BLUE', 'RED', 'BLUE', 'RED', 'GREEN', 'BLUE'];
             map_mode=dynamic; map_id=dynamic_5b5r2g_BBRGRRBRBRGB_v1
```

## Final piece outcomes

Both runs completed all 12 pieces.

Fixed final destinations:

```text
BLUE:  final_blue_stack=1, final_blue_circle=4
RED:   final_red_stack=5
GREEN: final_green_stack=1, final_green_circle=1
```

Dynamic final destinations:

```text
BLUE:  final_blue_stack=1, final_blue_circle=4
RED:   final_red_stack=3, final_red_circle=2
GREEN: final_green_circle=2
```

## Conclusion

The `5B/5R/2G` dynamic map executed correctly and produced a real makespan
reduction of `173.915 s` (`18.32%`) against the fixed physical run. The
simulation fidelity stayed within `2.66%`, and every expected cycle occurred
with the expected entity/task/cycle number and color.
