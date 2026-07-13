# Dynamic Map 2B/2R/6G Validation Notes

Date: 2026-07-12

## Hallazgo principal

La prueba `2B/2R/6G` funciona como caso de control: el generador dinamico no
encontro una politica mejor que la referencia fixed correcta. Ambos modos
aplicaron el mismo stack `BGRBGGRGGG`, ambos tienen `421.5 s` de makespan
simulado, y la diferencia real entre corridas fue pequena (`3.140 s`, `0.73%`)
a favor del fixed.

Esto es una validacion importante: cuando el mapa dinamico no encuentra una
ventaja real, el sistema no fabrica una mejora artificial. El mapa cargado se
cumplio correctamente y todos los ciclos ocurrieron en el orden esperado.

Criterion for real production duration in all real comparisons:

- `t0`: start of the first `xarm2` cycle, including `WAITING_GLOBALVISION`.
- `t_fin`: end of `RETURNING_HOME` in the last `robot1` cycle.

## Comparacion real

| Scenario | Input stack | Applied stack | Politica / mapa | Sim time | Real run | Real time |
|---|---:|---:|---|---:|---|---:|
| Fixed reference | `BGRBGGRGGG` | `BGRBGGRGGG` | fixed priorities | `421.5 s` | `20260712_205819_BGRBGGRGGG` | `430.423 s` |
| Mapa dinamico | `BGRBGGRGGG` | `BGRBGGRGGG` | `dynamic_2b2r6g_BGRBGGRGGG_v1` | `421.5 s` | `20260712_210633_BGRBGGRGGG` | `433.563 s` |

Quantified deltas:

- Dynamic real vs fixed real: `430.423 -> 433.563 s`, saving real
  `-3.140 s` (`-0.73%`). In practice, the dynamic run was `3.140 s` slower.
- Dynamic sim vs fixed sim: `421.5 -> 421.5 s`, saving sim `0.0 s`
  (`0.00%`).
- Fixed real fidelity: `430.423 s` real vs `421.5 s` sim, diff
  `+8.923 s` (`+2.12%`).
- Dynamic real fidelity: `433.563 s` real vs `421.5 s` sim, diff
  `+12.063 s` (`+2.86%`).
- Real saving vs predicted saving: `-3.140 s` real vs `0.0 s` simulated,
  i.e. a small hardware-variance loss rather than a policy effect.

## Fixed run validation

```text
run_id:          20260712_205819_BGRBGGRGGG
original stack:  BGRBGGRGGG
applied stack:   BGRBGGRGGG
map_mode:        fixed
t0:              2026-07-12T20:58:43.898574-04:00
t_fin:           2026-07-12T21:05:54.321318-04:00
real:            430.423 s
sim:             421.5 s
diff:            +8.923 s (+2.12%)
```

Cycle execution check:

```text
expected cycles: 37
real cycles:     37
matched:         37
followed map:     0
timeout:          0
no_sim:           0
intruder:         0
discarded:        0
color mismatch:   0
completed pieces: 10/10
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
xarm2   FEED_TO_C1S1               4
xarm2   FEED_GREEN_TO_C3           6
xarm1   C1S2_TO_C2S1               2
xarm1   C1S2_TO_LASER              2
xarm1   LASER_TO_C2S1              2
laser   PROCESS_RED                2
robot2  CLASSIFY_C2S2_TO_BANTAM    1
robot2  CLASSIFY_C2S2_TO_IBS       1
robot2  IBS_TO_BANTAM              1
robot2  BANTAM_TO_C4               2
robot2  CLASSIFY_C2S2_TO_C4        2
bantam  PROCESS_BLUE               2
robot1  UNLOAD_C3                  6
robot1  UNLOAD_C4                  4
```

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['BLUE', 'GREEN', 'RED', 'BLUE', 'GREEN', 'GREEN',
                   'RED', 'GREEN', 'GREEN', 'GREEN']; map_mode=fixed
```

## Dynamic run validation

Important validation detail: for this run the executed map is the
`expected_schedule` stored in `production_run.config_snapshot`. Running
`run_report.py` directly is not enough for dynamic-map validation, because the
current report tool reconstructs a fixed schedule from `optimized_order`.

```text
run_id:          20260712_210633_BGRBGGRGGG
original stack:  BGRBGGRGGG
applied stack:   BGRBGGRGGG
map_mode:        dynamic
map_id:          dynamic_2b2r6g_BGRBGGRGGG_v1
t0:              2026-07-12T21:06:57.232787-04:00
t_fin:           2026-07-12T21:14:10.795572-04:00
real:            433.563 s
sim:             421.5 s
diff:            +12.063 s (+2.86%)
```

Cycle execution check:

```text
expected cycles: 37
real cycles:     37
matched:         37
followed map:     0
timeout:          0
no_sim:           0
intruder:         0
discarded:        0
color mismatch:   0
completed pieces: 10/10
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
xarm2   FEED_TO_C1S1               4
xarm2   FEED_GREEN_TO_C3           6
xarm1   C1S2_TO_C2S1               2
xarm1   C1S2_TO_LASER              2
xarm1   LASER_TO_C2S1              2
laser   PROCESS_RED                2
robot2  CLASSIFY_C2S2_TO_BANTAM    1
robot2  CLASSIFY_C2S2_TO_IBS       1
robot2  IBS_TO_BANTAM              1
robot2  BANTAM_TO_C4               2
robot2  CLASSIFY_C2S2_TO_C4        2
bantam  PROCESS_BLUE               2
robot1  UNLOAD_C3                  6
robot1  UNLOAD_C4                  4
```

No rows needed controlled map waits in this case (`followed map = 0`), which
is expected because the dynamic schedule is identical to the fixed schedule
for this composition.

`Confirm & Apply` was confirmed in `operator_event`:

```text
event_type:  APPLY_ORDER
description: order=['BLUE', 'GREEN', 'RED', 'BLUE', 'GREEN', 'GREEN',
                   'RED', 'GREEN', 'GREEN', 'GREEN'];
             map_mode=dynamic; map_id=dynamic_2b2r6g_BGRBGGRGGG_v1
```

## Final piece outcomes

Both runs completed all 10 pieces.

Fixed final destinations:

```text
BLUE:  final_blue_circle=2
GREEN: final_green_stack=5, final_green_circle=1
RED:   final_red_stack=1, final_red_circle=1
```

Dynamic final destinations:

```text
BLUE:  final_blue_circle=2
GREEN: final_green_stack=6
RED:   final_red_stack=2
```

## Conclusion

The `2B/2R/6G` dynamic map executed correctly and produced the expected
control result: no meaningful improvement over fixed, because the dynamic map
and the fixed reference are the same schedule. The dynamic run was `3.140 s`
slower in reality (`-0.73%` saving), while simulation predicted equal
makespan. All `37/37` cycles matched the stored dynamic map, with no timeout,
no intruder, no discard, no missing simulated cycle, and no color mismatch.
