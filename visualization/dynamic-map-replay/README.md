# Shipyard PnP Cell Flow

Static 2D web visualization for presenting the Shipyard PnP cell as a physical material-flow story.

## Run

```bash
cd ~/shipyard_pnp_ws/visualization/dynamic-map-replay
npm start
```

Open:

```text
http://127.0.0.1:8767/
```

If port `8767` is already in use:

```bash
PORT=8768 npm start
```

## What It Shows

- Physical cell layout with robots, conveyors, machines, stacks, sensors, buffers, and output modules.
- Moving pieces from one physical location to the next.
- Compact resource status labels placed beside each resource.
- Active decision cards that explain condition, decision, and action in human language.
- Relevant physical conditions such as sensor occupancy, conveyor availability, machine processing, and stack occupancy.
- A `Routes` tab for material-flow paths and pickup/dropoff points.

## Editing Geometry

Edit `data/layout.js`.

- Move a resource with `x` and `y`.
- Resize a resource with `w` and `h`.
- Change visible text with `label`.
- Move status labels with `statusBadge`.
- Keep existing resource IDs because the generated data uses them.
- Initial Stack capacity is represented as 3 rows x 6 positions.

## Replay Catalog

The browser loads `data/runs.js`, which contains the four physical MES runs
plus their four calibrated SimPy simulated counterparts. The selector groups
them as `Physical cell runs` and `Simulated runs`.

Physical MES runs:

- `3B/3R - Fixed Optimizer`: `20260710_183624_RBRBRB`
- `3B/3R - Dynamic Map`: `20260710_190550_RBRBRB`
- `5B/5R/5G - Fixed Reference`: `20260712_202104_RBBGGGGBGBRRRRB`
- `5B/5R/5G - Dynamic Map`: `20260712_203824_RBBGGGGBGBRRRRB`

Simulated counterparts:

- `simulated_20260710_183624_RBRBRB`: fixed-priority SimPy replay, 560.2 s.
- `simulated_20260710_190550_RBRBRB`: dynamic-map SimPy replay, 497.3 s.
- `simulated_20260712_202104_RBBGGGGBGBRRRRB`: fixed-priority SimPy replay, 963.8 s.
- `simulated_20260712_203824_RBBGGGGBGBRRRRB`: dynamic-map SimPy replay, 811.7 s.

Regenerate the full catalog from Postgres with:

```bash
PGPASSWORD=postgres python3 visualization/dynamic-map-replay/tools/build_replay_catalog.py
```

Then append/update the simulated counterparts from the local calibrated SimPy
model:

```bash
python3 visualization/dynamic-map-replay/tools/add_simulated_replays.py
```

Append another completed MES run to the catalog with:

```bash
PGPASSWORD=postgres python3 visualization/dynamic-map-replay/tools/build_replay_catalog.py --run-id RUN_ID
```

You can also cache the raw exported MES JSON files:

```bash
PGPASSWORD=postgres python3 visualization/dynamic-map-replay/tools/build_replay_catalog.py --raw-dir /tmp/shipyard_replay_raw
```

`data/sample_run.js` is still generated as a fallback from the default dynamic
`3B/3R` run.
