# Dynamic Map 6B/6R/6G Validation Notes

Date: 2026-07-13

## Hallazgo principal

La prueba `6B/6R/6G` valida una politica dinamica distinta: el mapa `BBGBGBRGGGGRRBRRRB` redujo el makespan real en `161.280 s` (`14.33%`) frente a la referencia fixed `BBGBGBRGGGGRRBRRRB`.

Both runs passed the cycle-level validation.

Criterion for real production duration in all real comparisons:

- `t0`: start of the first `xarm2` cycle, including `WAITING_GLOBALVISION`.
- `t_fin`: end of `RETURNING_HOME` in the last `robot1` cycle.

## Comparacion real

| Scenario | Input stack | Applied stack | Politica / mapa | Sim time | Real run | Real time |
|---|---:|---:|---|---:|---|---:|
| Fixed reference | `BBGBGBRGGGGRRBRRRB` | `BBGBGBRGGGGRRBRRRB` | fixed priorities | `1137.8 s` | `20260713_193554_BBGBGBRGGGGRRBRRRB` | `1125.103 s` |
| Mapa dinamico | `BBGBGBRGGGGRRBRRRB` | `BBGBGBRGGGGRRBRRRB` | `dynamic_6b6r6g_BBGBGBRGGGGRRBRRRB_v1` | `978.0 s` | `20260713_195721_BBGBGBRGGGGRRBRRRB` | `963.823 s` |

Quantified deltas:

- Dynamic real vs fixed real: `1125.103 -> 963.823 s`, saving real `+161.280 s` (`+14.33%`).
- Dynamic sim vs fixed sim: `1137.8 -> 978.0 s`, saving sim `+159.8 s` (`+14.04%`).
- Fixed real fidelity: `1125.103 s` real vs `1137.8 s` sim, diff `-12.697 s` (`-1.12%`).
- Dynamic real fidelity: `963.823 s` real vs `978.0 s` sim, diff `-14.177 s` (`-1.45%`).
- Real saving vs predicted saving: `+161.280 s` real vs `+159.8 s` simulated, delta `+1.480 s` (`+0.29 pp`).

## Fixed run validation

```text
run_id:          20260713_193554_BBGBGBRGGGGRRBRRRB
original stack:  BBGBGBRGGGGRRBRRRB
applied stack:   BBGBGBRGGGGRRBRRRB
map_mode:        fixed
schedule source: computed fixed schedule
t0:              2026-07-13T19:36:35.006774-04:00
t_fin:           2026-07-13T19:55:20.109983-04:00
real:            1125.103 s
sim:             1137.8 s
diff:            -12.697 s (-1.12%)
```

Cycle execution check:

```text
expected cycles: 89
real cycles:     89
matched:         85
followed map:    4
timeout:         0
no_sim:          0
intruder:        0
discarded:       0
task mismatch:   0
color mismatch:  0
completed pieces: 18/18
```

Per-entity cycle order:

```text
xarm2   OK
xarm1   OK
laser   OK
robot2  OK
bantam  OK
robot1  OK
```

Task counts:

```text
bantam  PROCESS_BLUE                  6
laser   PROCESS_RED                   6
robot1  UNLOAD_C3                     6
robot1  UNLOAD_C4                    12
robot2  BANTAM_TO_C4                  6
robot2  CLASSIFY_C2S2_TO_BANTAM       1
robot2  CLASSIFY_C2S2_TO_C4           6
robot2  CLASSIFY_C2S2_TO_IBS          5
robot2  IBS_TO_BANTAM                 5
xarm1   C1S2_TO_C2S1                  6
xarm1   C1S2_TO_LASER                 6
xarm1   LASER_TO_C2S1                 6
xarm2   FEED_GREEN_TO_C3              6
xarm2   FEED_TO_C1S1                 12
```

Controlled map waits:

```text
xarm1 LASER_TO_C2S1 #2 piece-012 RED waited 6.98 s
xarm1 LASER_TO_C2S1 #3 piece-013 RED waited 8.84 s
xarm1 LASER_TO_C2S1 #4 piece-015 RED waited 7.05 s
xarm1 LASER_TO_C2S1 #5 piece-016 RED waited 6.39 s
```

`Confirm & Apply` event:

```text
order=['BLUE', 'BLUE', 'GREEN', 'BLUE', 'GREEN', 'BLUE', 'RED', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'RED', 'RED', 'BLUE', 'RED', 'RED', 'RED', 'BLUE']; map_mode=fixed
```

## Dynamic run validation

Important validation detail: for dynamic-map runs, this report uses the
`expected_schedule` stored in `production_run.config_snapshot` when present.

```text
run_id:          20260713_195721_BBGBGBRGGGGRRBRRRB
original stack:  BBGBGBRGGGGRRBRRRB
applied stack:   BBGBGBRGGGGRRBRRRB
map_mode:        dynamic
map_id:          dynamic_6b6r6g_BBGBGBRGGGGRRBRRRB_v1
schedule source: stored dynamic map
t0:              2026-07-13T19:57:55.651135-04:00
t_fin:           2026-07-13T20:13:59.474528-04:00
real:            963.823 s
sim:             978.0 s
diff:            -14.177 s (-1.45%)
```

Cycle execution check:

```text
expected cycles: 88
real cycles:     88
matched:         83
followed map:    5
timeout:         0
no_sim:          0
intruder:        0
discarded:       0
task mismatch:   0
color mismatch:  0
completed pieces: 18/18
```

Per-entity cycle order:

```text
xarm2   OK
xarm1   OK
laser   OK
robot2  OK
bantam  OK
robot1  OK
```

Task counts:

```text
bantam  PROCESS_BLUE                  6
laser   PROCESS_RED                   6
robot1  UNLOAD_C3                     6
robot1  UNLOAD_C4                    12
robot2  BANTAM_TO_C4                  6
robot2  CLASSIFY_C2S2_TO_BANTAM       2
robot2  CLASSIFY_C2S2_TO_C4           6
robot2  CLASSIFY_C2S2_TO_IBS          4
robot2  IBS_TO_BANTAM                 4
xarm1   C1S2_TO_C2S1                  6
xarm1   C1S2_TO_LASER                 6
xarm1   LASER_TO_C2S1                 6
xarm2   FEED_GREEN_TO_C3              6
xarm2   FEED_TO_C1S1                 12
```

Controlled map waits:

```text
xarm1 LASER_TO_C2S1 #2 piece-012 RED waited 6.58 s
xarm1 LASER_TO_C2S1 #3 piece-013 RED waited 9.70 s
xarm1 LASER_TO_C2S1 #4 piece-015 RED waited 7.02 s
xarm1 LASER_TO_C2S1 #5 piece-016 RED waited 6.61 s
robot2 BANTAM_TO_C4 #4 piece-006 BLUE waited 0.46 s
```

`Confirm & Apply` event:

```text
order=['BLUE', 'BLUE', 'GREEN', 'BLUE', 'GREEN', 'BLUE', 'RED', 'GREEN', 'GREEN', 'GREEN', 'GREEN', 'RED', 'RED', 'BLUE', 'RED', 'RED', 'RED', 'BLUE']; map_mode=dynamic; map_id=dynamic_6b6r6g_BBGBGBRGGGGRRBRRRB_v1
```

## Final piece outcomes

Fixed final destinations:

```text
BLUE   final_blue_circle=6
GREEN  final_green_circle=3, final_green_stack=3
RED    final_red_circle=2, final_red_stack=4
```

Dynamic final destinations:

```text
BLUE   final_blue_circle=6
GREEN  final_green_circle=6
RED    final_red_circle=2, final_red_stack=4
```

## Conclusion

The `6B/6R/6G` dynamic map executed correctly and produced a real makespan reduction of `161.280 s` (`14.33%`). All expected cycles were checked against the stored map/fixed schedule; see the validation blocks above for any warnings.
