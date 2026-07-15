# Codex Notes for Shipyard Dynamic-Map Validation

Use these rules when validating real fixed-vs-dynamic production runs.

## Real makespan convention

- Start time (`t0`): start of the first `xarm2` cycle, including
  `WAITING_GLOBALVISION`.
- End time (`t_fin`): end of `RETURNING_HOME` in the last `robot1` cycle,
  after the last piece has been placed in its final location.
- Do not use `production_run.started_at` / `production_run.finished_at` as
  production makespan; those include run setup/teardown time.

## Dynamic-map validation

- For dynamic runs, validate against
  `production_run.config_snapshot.expected_schedule`.
- Do not rebuild a dynamic schedule only from `optimized_order`; that turns
  the dynamic dispatch map back into a fixed-priority reconstruction.
- For fixed runs, use the stored snapshot if present, otherwise
  `compute_expected_schedule(optimized_order)`.
- Match cycles by `(entity, task, cycle_number)`, with robot2
  `CLASSIFY_C2S2_TO_*` sharing the counter key `CLASSIFY_C2S2`.
- Treat `map_outcome=followed` as a controlled wait, not a failure.
- Treat `timeout`, `no_sim`, intruders, discarded cycles, task mismatch, and
  color mismatch as validation warnings/failures for clean fixed-vs-dynamic
  comparisons.

## Report generator

Generate a fixed-vs-dynamic Markdown report with:

```bash
PYTHONPATH=src/shipyard_pnp PGPASSWORD=postgres \
python3 scripts/generate_run_validation_report.py \
  --fixed-run FIXED_RUN_ID \
  --dynamic-run DYNAMIC_RUN_ID \
  --out docs/dynamic_map_XbYrZg
```

For the latest completed dynamic run, let the script infer the closest prior
fixed reference with the same original stack/composition:

```bash
PYTHONPATH=src/shipyard_pnp PGPASSWORD=postgres \
python3 scripts/generate_run_validation_report.py \
  --latest-dynamic \
  --out /tmp/latest_dynamic_report.md
```

Use `--fail-on-issues` in checks/automation when a nonzero exit code should
mean that the cycle-level validation did not pass.
