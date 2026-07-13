# Dynamic Map BRRBRB Validation Notes

Date: 2026-07-10

## Hallazgo principal

El resultado importante no es que el stack `BRRBRB` sea mejor por si solo. De
hecho, si `BRRBRB` se ejecuta con las prioridades fixed, la simulacion empeora
mucho. La mejora aparece solo cuando ese stack se ejecuta con el mapa dinamico
`dynamic_3b3r_brrbrb_v1`, porque el mapa cambia tres decisiones de prioridad
que fixed no tomaria.

Criterion for real production duration in all real comparisons:

- `t0`: start of the first `xarm2` cycle, including `WAITING_GLOBALVISION`.
- `t_fin`: end of `RETURNING_HOME` in the last `robot1` cycle.

### Comparacion de los cuatro escenarios

| Scenario | Stack inicial | Politica / mapa | Sim time | Real run | Real time |
|---|---:|---|---:|---|---:|
| Fixed sin optimizar | `RBRBRB` | fixed priorities | `626.6 s` | no ejecutado | n/a |
| Fixed con stack optimizado | `BRRRBB` | fixed priorities | `560.2 s` | `20260710_183624_RBRBRB` | `552.962 s` |
| Fixed con stack del mapa dinamico | `BRRBRB` | fixed priorities | `622.9 s` | no ejecutado | n/a |
| Mapa dinamico | `BRRBRB` | `dynamic_3b3r_brrbrb_v1` | `497.3 s` | `20260710_190550_RBRBRB` | `486.651 s` |

Quantified deltas:

- Fixed optimizer vs fixed sin optimizar: `626.6 -> 560.2 s`, saving sim
  `66.4 s` (`10.6%`).
- `BRRBRB` under fixed is not the improvement: `622.9 s`, which is `62.7 s`
  slower than the fixed optimized `BRRRBB` simulation.
- Dynamic map vs fixed optimized: `560.2 -> 497.3 s`, saving sim `62.9 s`
  (`11.2%`).
- Dynamic real vs fixed optimized real: `552.962 -> 486.651 s`, saving real
  `66.311 s` (`12.0%`).
- Dynamic map vs fixed priorities on the same `BRRBRB` stack: `622.9 -> 497.3 s`,
  saving sim `125.6 s` (`20.2%`).
- Fixed optimized real fidelity: `552.962 s` real vs `560.2 s` sim, diff
  `-7.238 s` (`-1.3%`).
- Dynamic real fidelity: `486.651 s` real vs `497.3 s` sim, diff `-10.649 s`
  (`-2.1%`).

### Dynamic run validation

Latest dynamic run:

```text
run_id:          20260710_190550_RBRBRB
original stack:  RBRBRB
applied stack:   BRRBRB
map_mode:        dynamic
map_id:          dynamic_3b3r_brrbrb_v1
t0:              2026-07-10 19:06:26.226768-04
t_fin:           2026-07-10 19:14:32.878081-04
real:            486.651 s
sim:             497.3 s
```

Map execution check:

```text
expected cycles: 36
real cycles:     36
matched:         33
followed map:     3
mismatches:       0
color mismatch:   0
status failures:  0
completed pieces: 6/6
```

`Load Map Dynamic` was confirmed as applied:

```text
operator_event: APPLY_ORDER
description:    order=['BLUE', 'RED', 'RED', 'BLUE', 'RED', 'BLUE'];
                map_mode=dynamic; map_id=dynamic_3b3r_brrbrb_v1
ts:             2026-07-10 19:06:25.978518-04
optimizer_run:  applied=true, best_time_s=497.3, saving_s=62.9
```

### Dynamic decisions that fixed would not take

The dynamic map differs from fixed at exactly three multi-ready decision
points in the `BRRBRB` simulation. `robot1` does not change in this 3B/3R run;
there are no green pieces, so there is no C3/C4 conflict.

1. `robot2` at sim `t=140.8 s`

   ```text
   ready:        P1 + P2
   dynamic:      P2 = BANTAM_TO_C4 #1, BLUE
   fixed would:  P1 = classify the waiting C2S2 piece first
   real match:   robot2 BANTAM_TO_C4 piece-002 at real t=138.1 s
   ```

   Effect: fixed would classify the waiting blue while Bantam is still occupied,
   sending that blue through `CLASSIFY_C2S2_TO_IBS` and later
   `IBS_TO_BANTAM`. Dynamic clears the finished Bantam piece first and avoids
   that IBS detour.

2. `xarm1` at sim `t=203.7 s`

   ```text
   ready:        LASER + C1
   dynamic:      C1 = C1S2_TO_C2S1 #3, BLUE
   fixed would:  LASER = retrieve the finished red laser piece first
   real match:   xarm1 C1S2_TO_C2S1 piece-006 at real t=203.3 s
   ```

   Effect: dynamic intentionally leaves the finished red laser piece waiting
   until `LASER_TO_C2S1 #3` (`t=239.5 s` sim, `t=237.3 s` real) so the last
   blue can enter the robot2 flow at the right moment.

3. `robot2` at sim `t=278.4 s`

   ```text
   ready:        P1 + P2
   dynamic:      P2 = BANTAM_TO_C4 #2, BLUE
   fixed would:  P1 = classify the waiting C2S2 piece first
   real match:   robot2 BANTAM_TO_C4 piece-004 at real t=273.7 s
   ```

   Effect: fixed would again classify a waiting blue before clearing Bantam,
   creating a second IBS detour. Dynamic clears Bantam first, then continues
   classification.

The cycle-count consequence is visible in simulation:

```text
Fixed BRRBRB robot2 cycles:   11
Dynamic BRRBRB robot2 cycles:  9
Fixed BRRBRB IBS cycles:       2 CLASSIFY_C2S2_TO_IBS + 2 IBS_TO_BANTAM
Dynamic BRRBRB IBS cycles:     0
```

## Baseline real run

Run analyzed before changing the dynamic-map flow:

- `run_id`: `20260710_183624_RBRBRB`
- Original stack in DB: `RBRBRB`
- Fixed optimizer order actually applied: `BRRRBB`
- Criterion for production duration: `run_report.py` standard criterion.
  - `t0`: start of first `xarm2` cycle, including `WAITING_GLOBALVISION`.
  - `t_fin`: end of `RETURNING_HOME` in the last `robot1` cycle.

Baseline result:

```text
t0:    2026-07-10 18:37:01.406005-04
t_fin: 2026-07-10 18:46:14.368064-04
real:  552.962 s
sim:   560.2 s
diff:   -7.238 s (-1.3%)
```

Cycle validation:

```text
cycle_event rows: 37
matched:          34
followed map:      3
timeout:           0
no_sim:            0
intruder:          0
discarded:         0
status failures:   0
completed pieces:  6/6
```

The three `followed` rows were all expected `xarm1 LASER_TO_C2S1` waits:

```text
piece-001 LASER_TO_C2S1 #1 waited 6.51s -> followed
piece-003 LASER_TO_C2S1 #2 waited 7.21s -> followed
piece-005 LASER_TO_C2S1 #3 waited 5.31s -> followed
```

All final destinations were correct:

```text
piece-001 RED  -> final_red_stack
piece-002 BLUE -> final_blue_circle
piece-003 RED  -> final_red_stack
piece-004 BLUE -> final_blue_circle
piece-005 RED  -> final_red_stack
piece-006 BLUE -> final_blue_circle
```

## Dynamic map prepared

Preset id:

```text
dynamic_3b3r_brrbrb_v1
```

The preset is for exactly `3 BLUE + 3 RED`.

Reference fixed order:

```text
BRRRBB = BLUE, RED, RED, RED, BLUE, BLUE
fixed sim time: 560.2 s
```

Dynamic map order:

```text
BRRBRB = BLUE, RED, RED, BLUE, RED, BLUE
dynamic sim time: 497.3 s
expected simulated saving vs fixed reference: 62.9 s
```

Dynamic policy used to build the map:

```text
robot2: P2 > P1 > P3
robot1: existing fixed fallback
xarm1:  C1 > LASER
```

Generated map cycle counts:

```text
xarm2:  6
xarm1:  9
laser:  3
robot2: 9
bantam: 3
robot1: 6
```

## Dashboard behavior

The dashboard now has two pre-start options:

1. `Optimize Order`
   - Existing fixed SimPy optimizer.
   - Builds/applies the fixed expected schedule.
   - Does not start production until `Confirm & Apply`.

2. `Load Map Dynamic`
   - Loads `dynamic_3b3r_brrbrb_v1`.
   - Prepares `BRRBRB` and its dynamic expected schedule.
   - Does not start production until `Confirm & Apply`.

Both paths publish through `/supervisor/set_optimized_order` only after
`Confirm & Apply`.

When a dynamic map is applied, the supervisor also persists the map metadata
and full `expected_schedule` into `production_run.config_snapshot` for the
active run. `operator_event` stores the applied `map_mode` and `map_id`; the
`optimizer_run.method` is also the dynamic map id.

## Files changed

- `src/shipyard_pnp/shipyard_pnp/factory/expected_schedule.py`
  - Extracted `build_schedule_from_state_changes()` so fixed and dynamic maps
    share the exact same grouping logic.

- `src/shipyard_pnp/shipyard_pnp/factory/dynamic_schedule.py`
  - New preset loader for `dynamic_3b3r_brrbrb_v1`.
  - Validates exactly `3 BLUE + 3 RED`.
  - Returns order, simulated timing, and `expected_schedule`.

- `src/shipyard_pnp/shipyard_pnp/factory/factory_supervisor.py`
  - Accepts optional `expected_schedule` in the apply-order payload.
  - If present, loads it directly as the live map.
  - If absent, preserves previous fixed behavior.
  - Persists dynamic map metadata into `production_run.config_snapshot`.

- `src/shipyard_pnp/shipyard_pnp/factory/db_writer.py`
  - Added `update_production_run_config_snapshot()` to merge JSON metadata into
    the current run row.

- `src/shipyard_pnp/shipyard_pnp/nodes/dashboard_node.py`
  - Added `Load Map Dynamic`.
  - Added `/api/load_dynamic_map`.
  - `Confirm & Apply` sends `map_mode`, `map_id`, and optional dynamic
    `expected_schedule`.

## Revert guide

To revert only this dynamic-map flow:

1. Remove `src/shipyard_pnp/shipyard_pnp/factory/dynamic_schedule.py`.
2. Revert the dashboard changes in `dashboard_node.py`:
   - `Load Map Dynamic` button.
   - `/api/load_dynamic_map`.
   - dynamic `expected_schedule` payload in `/api/start_production`.
3. Revert the supervisor changes in `factory_supervisor.py` that load
   `payload["expected_schedule"]` and persist map metadata.
4. Revert `update_production_run_config_snapshot()` in `db_writer.py` if no
   longer needed.
5. Either keep or revert `build_schedule_from_state_changes()` in
   `expected_schedule.py`; keeping it is behavior-neutral for fixed mode.

Validation command after revert or modification:

```bash
python3 -m py_compile \
  src/shipyard_pnp/shipyard_pnp/factory/expected_schedule.py \
  src/shipyard_pnp/shipyard_pnp/factory/dynamic_schedule.py \
  src/shipyard_pnp/shipyard_pnp/factory/db_writer.py \
  src/shipyard_pnp/shipyard_pnp/factory/factory_supervisor.py \
  src/shipyard_pnp/shipyard_pnp/nodes/dashboard_node.py
```
