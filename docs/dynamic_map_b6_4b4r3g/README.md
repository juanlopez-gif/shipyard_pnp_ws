# Dynamic Map B6 4B/4R/3G Validation Notes

Date: 2026-07-12

## Hallazgo principal

La prueba B6 confirma el mismo patron que la prueba `BRRBRB`, pero en una
corrida mas grande: el mapa dinamico no solo mejora el makespan real, tambien
se mantiene muy cerca de la simulacion que lo genero.

Criterion for real production duration in all real comparisons:

- `t0`: start of the first `xarm2` cycle, including `WAITING_GLOBALVISION`.
- `t_fin`: end of `RETURNING_HOME` in the last `robot1` cycle.

## Comparacion real

| Scenario | Input stack | Applied stack | Politica / mapa | Sim time | Real run | Real time |
|---|---:|---:|---|---:|---|---:|
| Fixed optimizado | `BBBBRRRRGGG` | `BBBBGGGRRRR` | fixed priorities | `767.0 s` | `20260712_145644_BBBBRRRRGGG` | `758.330 s` |
| Mapa dinamico B6 | `BBBBRRRRGGG` | `BBGBGRRRGRB` | `dynamic_4b4r3g_BBGBGRRRGRB_v1` | `655.5 s` | `20260712_151058_BBBBRRRRGGG` | `645.673 s` |

Quantified deltas:

- Dynamic real vs fixed optimized real: `758.330 -> 645.673 s`, saving real
  `112.657 s` (`14.9%`).
- Dynamic sim vs fixed optimized sim: `767.0 -> 655.5 s`, saving sim
  `111.5 s` (`14.5%`).
- Fixed optimized real fidelity: `758.330 s` real vs `767.0 s` sim, diff
  `-8.670 s` (`-1.1%`).
- Dynamic real fidelity: `645.673 s` real vs `655.5 s` sim, diff
  `-9.827 s` (`-1.5%`).

The dynamic run also stores the offline generator reference in
`production_run.config_snapshot`. The applied dynamic order comes from
`production_run.optimized_order`, and the dynamic time comes from the stored
`expected_schedule`:

```text
reference_order:  BBBBRRRRGGG
reference_time_s: 899.0 s
dynamic_order:    BBGBGRRRGRB
dynamic_time_s:   655.5 s
offline saving:   243.5 s (27.1%)
```

That `899.0 s` number is useful as the generator's original reference, but the
fair physical comparison in this report is against the fixed optimized real
run above, because the fixed dashboard optimizer applied `BBBBGGGRRRR`.

## Fixed run validation

```text
run_id:          20260712_145644_BBBBRRRRGGG
original stack:  BBBBRRRRGGG
applied stack:   BBBBGGGRRRR
map_mode:        fixed
t0:              2026-07-12T14:57:45.701209-04:00
t_fin:           2026-07-12T15:10:24.031346-04:00
real:            758.330 s
sim:             767.0 s
diff:            -8.670 s (-1.1%)
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
completed pieces: 11/11
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
xarm2   FEED_TO_C1S1              8
xarm2   FEED_GREEN_TO_C3          3
xarm1   C1S2_TO_C2S1              4
xarm1   C1S2_TO_LASER             4
xarm1   LASER_TO_C2S1             4
laser   PROCESS_RED               4
robot2  CLASSIFY_C2S2_TO_BANTAM   1
robot2  CLASSIFY_C2S2_TO_IBS      3
robot2  IBS_TO_BANTAM             3
robot2  BANTAM_TO_C4              4
robot2  CLASSIFY_C2S2_TO_C4       4
bantam  PROCESS_BLUE              4
robot1  UNLOAD_C3                 3
robot1  UNLOAD_C4                 8
```

The four `followed` rows were controlled map waits, not failures:

```text
xarm1  LASER_TO_C2S1 #1 piece-005 RED  waited 6.31 s
xarm1  LASER_TO_C2S1 #2 piece-006 RED  waited 6.62 s
xarm1  LASER_TO_C2S1 #3 piece-007 RED  waited 6.66 s
robot2 CLASSIFY_C2S2_TO_C4 #8 piece-008 RED waited 4.96 s
```

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['BLUE', 'BLUE', 'BLUE', 'BLUE', 'GREEN', 'GREEN',
                   'GREEN', 'RED', 'RED', 'RED', 'RED']; map_mode=fixed
```

## Dynamic run validation

Important validation detail: for this run the executed map is the
`expected_schedule` stored in `production_run.config_snapshot`. Running
`run_report.py` directly is not enough for this dynamic case, because the
current report tool reconstructs a fixed schedule from `optimized_order`.

```text
run_id:          20260712_151058_BBBBRRRRGGG
original stack:  BBBBRRRRGGG
applied stack:   BBGBGRRRGRB
map_mode:        dynamic
map_id:          dynamic_4b4r3g_BBGBGRRRGRB_v1
t0:              2026-07-12T15:11:29.158724-04:00
t_fin:           2026-07-12T15:22:14.831982-04:00
real:            645.673 s
sim:             655.5 s
diff:            -9.827 s (-1.5%)
```

Cycle execution check:

```text
expected cycles: 56
real cycles:     56
matched:         52
followed map:     4
timeout:          0
no_sim:           0
intruder:         0
discarded:        0
color mismatch:   0
completed pieces: 11/11
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
xarm2   FEED_TO_C1S1              8
xarm2   FEED_GREEN_TO_C3          3
xarm1   C1S2_TO_C2S1              4
xarm1   C1S2_TO_LASER             4
xarm1   LASER_TO_C2S1             4
laser   PROCESS_RED               4
robot2  CLASSIFY_C2S2_TO_BANTAM   2
robot2  CLASSIFY_C2S2_TO_IBS      2
robot2  IBS_TO_BANTAM             2
robot2  BANTAM_TO_C4              4
robot2  CLASSIFY_C2S2_TO_C4       4
bantam  PROCESS_BLUE              4
robot1  UNLOAD_C3                 3
robot1  UNLOAD_C4                 8
```

The four `followed` rows were controlled map waits, not failures:

```text
xarm1  LASER_TO_C2S1 #1 piece-005 RED   waited 6.49 s
xarm1  LASER_TO_C2S1 #2 piece-006 RED   waited 6.93 s
xarm1  LASER_TO_C2S1 #3 piece-007 RED   waited 6.35 s
robot2 BANTAM_TO_C4 #3 piece-003 BLUE   waited 0.66 s
```

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['BLUE', 'BLUE', 'GREEN', 'BLUE', 'GREEN', 'RED',
                   'RED', 'RED', 'GREEN', 'RED', 'BLUE'];
             map_mode=dynamic; map_id=dynamic_4b4r3g_BBGBGRRRGRB_v1
```

## Final piece outcomes

Both runs completed all 11 pieces.

Fixed optimized final destinations:

```text
BLUE:  final_blue_stack=1, final_blue_circle=3
RED:   final_red_stack=2,  final_red_circle=2
GREEN: final_green_stack=1, final_green_circle=2
```

Dynamic final destinations:

```text
BLUE:  final_blue_stack=1, final_blue_circle=3
RED:   final_red_stack=4
GREEN: final_green_stack=1, final_green_circle=2
```

## Conclusion

The B6 dynamic map executed correctly and produced a real makespan reduction
of `112.657 s` (`14.9%`) against the fixed optimized physical run. The
simulation fidelity stayed within `1.5%`, and every expected cycle occurred
with the expected entity/task/cycle number and color.
