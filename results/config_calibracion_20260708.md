# Snapshot de calibración — `shipyard_sim.py::Config` — 2026-07-08

Copia literal de la clase `Config` de `src/shipyard_pnp/shipyard_pnp/nodes/shipyard_sim.py`
en el momento de empezar la revisión de calibración de 2026-07-08 — **antes** de
tocar ninguna constante. Sirve de punto de restauración si la revisión de hoy
lleva a cambiar algo y hace falta comparar o deshacer.

Última calibración registrada antes de esta fecha: `results/calibracion_ciclos_20260706.md`
(2026-07-06, 5 corridas, una tarea en estado `REVISAR`: `CLASSIFY_C2S2_TO_BANTAM` +8.5%).

```python
class Config:
    # Calibrated from shipyard_pnp_ws DB medians on 2026-06-27 runs.
    # xArm2
    XARM2_MOVE_TO_STACK             = 3.8
    XARM2_VISION                    = 0.05
    XARM2_PICK_STACK                = 2.5
    XARM2_PLACE_C1S1                = 5.2
    XARM2_PLACE_C3                  = 5.15
    XARM2_RETURN_HOME_FROM_C3       = 3.93
    XARM2_RETURN_HOME_FROM_C1S1     = 2.0

    # Conveyor 1
    CONVEYOR1_TRANSPORT             = 5.86

    # Conveyor 2
    CONVEYOR2_TRANSPORT             = 9.18

    # xArm1
    XARM1_MOVE_TO_C1S2              = 4.0
    XARM1_PICK_C1S2                 = 0.55
    XARM1_PLACE_LASER               = 8.9
    XARM1_PLACE_C2S1                = 9.4
    XARM1_RETURN_HOME_C2S1          = 1.8
    XARM1_MOVE_TO_LASER             = 4.0
    XARM1_PICK_LASER                = 0.55
    XARM1_LASER_TO_C2S1             = 8.6
    XARM1_RETURN_HOME_LASER         = 1.8

    # Laser
    LASER_HEATING                   = 0.0
    LASER_PROCESSING                = 22.8

    # Robot2
    ROBOT2_MOVE_TO_C2S2             = 2.5
    ROBOT2_VISION_1                 = 13.8
    ROBOT2_VISION_2                 = 7.2
    ROBOT2_VISION_3                 = 6.2
    ROBOT2_VISION                   = 6.2
    ROBOT2_PICK_C2S2                = 3.5
    ROBOT2_PLACE_C4                 = 11.9
    ROBOT2_RETURN_C4                = 9.5
    ROBOT2_PLACE_IBS                = 12.0
    ROBOT2_RETURN_IBS               = 6.65
    ROBOT2_PLACE_BANTAM             = 14.0
    # NOTE (2026-07-06, 3rd attempt): real MOVE_PIECE C2S2->BANTAM_BED is
    # rock-solid at ~29.0s across 16 samples spanning 2026-06-27 to 07-06
    # (28.6-29.3s, zero drift — this is a real, reproducible gap, not noise).
    # Nominal PICK_C2S2(3.5)+PLACE_BANTAM(14.0)+CLEAR_BANTAM(2.5)=20.0 is
    # ~9s short. Tried raising PLACE_BANTAM to 19.8 to close it (reasoning:
    # ROBOT2_MOVE_TO_C2S2+VISION *also* over-estimates real CAPTURE_LOCAL_
    # VISION by ~2.6-3.4s from the same double-counted-travel cause, so only
    # ~5.2s of the 9s actually needs adding once that's netted out). Measured
    # effect: blue_single error grew from 1.16% to 4.02% high, bggbgr from
    # 0.18% to 1.94% high, AND the 18pc run's real bantam-vs-RED priority race
    # (bantam interrupts RED classification exactly once, right after RED
    # piece 1, in all 3 real 18pc runs so far — sim currently shows zero
    # interruptions) got marginally WORSE, not better. Reverted. This gap is
    # real but not closeable via this constant in isolation — the RED feed
    # pipeline (laser+xarm1+conveyor2) timing relative to bantam's own
    # schedule decides which side of a <3s margin wins that race, and it's
    # sensitive to ~15 compounding upstream constants at once. Needs a
    # coordinated multi-constant recalibration pass, not another point-fix.
    ROBOT2_CLEAR_BANTAM             = 2.5
    ROBOT2_MOVE_TO_BANTAM           = 8.9
    ROBOT2_PICK_BANTAM              = 3.1
    ROBOT2_BANTAM_TO_C4             = 14.9
    ROBOT2_RETURN_C4_BLUE           = 9.5
    ROBOT2_MOVE_TO_IBS              = 9.0
    ROBOT2_PICK_IBS                 = 3.0
    ROBOT2_IBS_TO_BANTAM            = 15.3
    # Real IBS->Bantam MOVE_PIECE clears/returns before Bantam RUN_JOB starts.
    ROBOT2_CLEAR_BANTAM_FROM_IBS    = 9.6

    # Bantam
    BANTAM_CLOSE_DOOR               = 11.4
    BANTAM_PROCESSING               = 25.0
    BANTAM_OPEN_DOOR                = 12.1

    # C3 / C4
    C3_PROCESSING                   = 10.0
    C4_PROCESSING                   = 14.5

    # Robot1
    # Vision recalibrated from shipyard_pnp_ws DB run 20260704_112132_RRRRRRBBBBBB
    # (12 real VISION_C4 samples, all from a fresh process start): mean 5.33s,
    # min 4.95s, max 6.06s, NO cold-start pattern visible across the run. The
    # 2026-07-03 "cold start" curve (13.0/7.0/6.4) was fit to only 2 samples
    # and turned out to be an artifact, not a real per-call effect — flattened
    # here.
    ROBOT1_MOVE_TO_C4               = 2.2
    ROBOT1_VISION_1                 = 5.3
    ROBOT1_VISION_2                 = 5.3
    ROBOT1_VISION_3                 = 5.3
    ROBOT1_VISION_C4                = 5.3
    # ROBOT1_VISION_C3 recalibrated from run 20260704_120002 (6 real VISION_C3
    # samples, mean 6.76s, 6.42-7.32). PLACE_FINAL_C3 recalibrated in the same
    # run: real UNLOAD_C3 total avg was 40.49s (6 samples) vs old nominal
    # 44.20s (+3.70s over) even though VISION_C3 was UNDER the real value —
    # PLACE_FINAL_C3=19.8 alone accounted for the rest of the gap once vision
    # is fixed (it had never been touched since the original 2026-06-27
    # calibration, unlike PLACE_FINAL_C4 which was already revalidated).
    # Re-checked against run 20260706_180404 (12G/3R/3B interleaved, 11
    # UNLOAD_C3 samples excl. the first-of-run outlier): real averaged 41.12s
    # vs nominal 40.0s (+1.12s / +2.8%). Bumped PLACE_FINAL_C3 by +1.1s to
    # 15.9 on that basis -- then re-checked against run 20260706_191425 (18
    # pure-GREEN pieces, 17 clean UNLOAD_C3 samples, much larger and more
    # homogeneous): real averaged only 39.32s, i.e. LOWER than the original
    # 40.0s nominal. Combined across both real runs (28 samples): 40.02s --
    # essentially exactly the original value. The 180404 run's 41.12s was
    # run-to-run noise, not a systematic bias; reverted to 14.8.
    ROBOT1_VISION_C3                = 6.8
    # Cold-start effect confirmed across 16 historical runs: robot1's FIRST
    # C3 unload of a run is reliably slower than every subsequent one, and
    # phase breakdown (run 20260706_184436) shows the entire excess sits in
    # VISION_C3 alone (10.33s vs ~5.3-6.8s later) -- every other sub-phase
    # (move/pick/place/return) is normal. Two regimes seen: when C3 is
    # robot1's literal first action of the run, avg +11.5% (9 samples,
    # 20260627/20260703/20260706 runs); when robot1 already did C4 jobs
    # first, avg +6.5% (4 samples, the 6R+6B+6G runs). Combined 13-sample
    # average: +10.0% (~+4.0s on the ~40s nominal). Modeled as a flat
    # one-time addition to VISION_C3 on the run's first C3 visit only.
    ROBOT1_VISION_C3_COLD_START_EXTRA = 4.0
    ROBOT1_PICK_C4                  = 5.1
    ROBOT1_PLACE_FINAL_C4           = 15.8
    ROBOT1_MOVE_TO_C3               = 3.0
    ROBOT1_PICK_C3                  = 5.6
    ROBOT1_PLACE_FINAL_C3           = 14.8
    ROBOT1_RETURN_HOME              = 9.8
```
