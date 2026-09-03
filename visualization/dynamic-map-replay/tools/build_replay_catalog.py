#!/usr/bin/env python3
"""Build a browser replay catalog from real MES production runs."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

from build_replay_from_run import build_replay


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "runs.js"
DEFAULT_SAMPLE_OUTPUT = ROOT / "data" / "sample_run.js"
SCHEMA = "shipyard_pnp_ws"

CONN_DEFAULTS = {
    "host": os.environ.get("PGHOST", "100.115.213.16"),
    "port": int(os.environ.get("PGPORT", "5432")),
    "user": os.environ.get("PGUSER", "twin_mes_db"),
    "password": os.environ.get("PGPASSWORD", "postgres"),
    "dbname": os.environ.get("PGDATABASE", "twin_mes_db"),
}

DEFAULT_RUNS = [
    {
        "key": "3b3r_fixed",
        "run_id": "20260710_183624_RBRBRB",
        "group": "3B/3R",
        "mode": "fixed",
        "title": "3B/3R - Fixed Optimizer",
        "summary": "Fixed optimized reference, 552.962 s real.",
        "comparison": "Reference for the 3B/3R dynamic-map run.",
    },
    {
        "key": "3b3r_dynamic",
        "run_id": "20260710_190550_RBRBRB",
        "group": "3B/3R",
        "mode": "dynamic",
        "title": "3B/3R - Dynamic Map",
        "summary": "Dynamic map, 486.651 s real; saves 66.311 s (12.0%) vs fixed optimized.",
        "comparison": "dynamic_3b3r_brrbrb_v1",
    },
    {
        "key": "5b5r5g_fixed",
        "run_id": "20260712_202104_RBBGGGGBGBRRRRB",
        "group": "5B/5R/5G",
        "mode": "fixed",
        "title": "5B/5R/5G - Fixed Reference",
        "summary": "Fixed reference with green flow, 952.436 s real.",
        "comparison": "Reference for the 5B/5R/5G dynamic-map run.",
    },
    {
        "key": "5b5r5g_dynamic",
        "run_id": "20260712_203824_RBBGGGGBGBRRRRB",
        "group": "5B/5R/5G",
        "mode": "dynamic",
        "title": "5B/5R/5G - Dynamic Map",
        "summary": "Dynamic map with green flow, 800.218 s real; saves 152.218 s (15.98%) vs fixed.",
        "comparison": "dynamic_5b5r5g_BGRBGGGRRBRBRGB_v1",
    },
]


def compact_order(order: Any) -> str:
    if not order:
        return ""
    if isinstance(order, str):
        try:
            order = json.loads(order)
        except json.JSONDecodeError:
            return order
    return "".join(str(color)[0].upper() for color in order)


def color_counts(order: Any) -> dict[str, int]:
    counts = {"BLUE": 0, "RED": 0, "GREEN": 0}
    if isinstance(order, str):
        try:
            order = json.loads(order)
        except json.JSONDecodeError:
            letters = {"B": "BLUE", "R": "RED", "G": "GREEN"}
            order = [letters[ch.upper()] for ch in order if ch.upper() in letters]
    for color in order or []:
        key = str(color).upper()
        if key in counts:
            counts[key] += 1
    return counts


def composition_label(order: Any) -> str:
    counts = color_counts(order)
    return f"{counts['BLUE']}B/{counts['RED']}R/{counts['GREEN']}G"


def auto_preset(raw: dict, run_id: str) -> dict:
    run = raw["run"]
    config = run.get("config_snapshot") or {}
    mode = config.get("map_mode") or "fixed"
    group = composition_label(run.get("original_order"))
    mode_title = "Dynamic Map" if mode == "dynamic" else "Fixed Run"
    applied = compact_order(run.get("optimized_order") or run.get("original_order"))
    completed = run.get("pieces_completed")
    total = run.get("total_pieces")
    return {
        "key": run_id.lower(),
        "run_id": run_id,
        "group": group,
        "mode": mode,
        "title": f"{group} - {mode_title}",
        "summary": f"{mode_title}, applied stack {applied}, completed {completed}/{total} pieces.",
        "comparison": config.get("map_id") or "Ad hoc run from MES.",
    }


def connect():
    return psycopg2.connect(**CONN_DEFAULTS)


def seconds_since(reference: datetime, value: datetime | None) -> float:
    if value is None:
        return 0.0
    return round((value - reference).total_seconds(), 3)


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def fetch_one(cur, query: str, params: tuple[Any, ...]) -> dict:
    cur.execute(query, params)
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"No row returned for query with params={params!r}")
    return dict(row)


def fetch_all(cur, query: str, params: tuple[Any, ...]) -> list[dict]:
    cur.execute(query, params)
    return [dict(row) for row in cur.fetchall()]


def duration_for_cycle(row: dict) -> float:
    if row.get("total_duration_s") is not None:
        return round(float(row["total_duration_s"]), 3)
    started = row.get("started_at")
    completed = row.get("completed_at")
    if started and completed:
        return round((completed - started).total_seconds(), 3)
    return 0.0


def export_run(conn, run_id: str) -> dict:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    run = fetch_one(
        cur,
        f"""SELECT run_id, status, started_at, finished_at, total_pieces,
                   pieces_completed, original_order, optimized_order,
                   config_snapshot
            FROM {SCHEMA}.production_run
            WHERE run_id = %s""",
        (run_id,),
    )
    reference = run["started_at"]

    pieces = fetch_all(
        cur,
        f"""SELECT color, shape, piece_id, initial_position
            FROM {SCHEMA}.piece
            WHERE run_id = %s
            ORDER BY initial_position ASC NULLS LAST, piece_id ASC""",
        (run_id,),
    )

    cycle_rows = fetch_all(
        cur,
        f"""SELECT id, entity, task_name, piece_id, color, cycle_number,
                   started_at, completed_at, total_duration_s,
                   metadata, is_discarded, discarded_reason
            FROM {SCHEMA}.cycle_event
            WHERE run_id = %s
            ORDER BY started_at ASC, id ASC""",
        (run_id,),
    )
    cycles = [
        {
            "t": seconds_since(reference, row["started_at"]),
            "id": row["id"],
            "color": row.get("color"),
            "entity": row["entity"],
            "duration": duration_for_cycle(row),
            "metadata": row.get("metadata") or {},
            "piece_id": row.get("piece_id"),
            "task_name": row["task_name"],
            "cycle_number": row.get("cycle_number"),
            "is_discarded": bool(row.get("is_discarded")),
            "discarded_reason": row.get("discarded_reason"),
        }
        for row in cycle_rows
        if row.get("started_at") is not None
    ]

    transfer_rows = fetch_all(
        cur,
        f"""SELECT id, piece_id, from_loc, to_loc, moved_by, ts,
                   piece_age_s, history_json
            FROM {SCHEMA}.piece_transfer
            WHERE run_id = %s
            ORDER BY ts ASC, id ASC""",
        (run_id,),
    )
    transfers = [
        {
            "t": seconds_since(reference, row["ts"]),
            "id": row["id"],
            "piece_id": row["piece_id"],
            "from_loc": row.get("from_loc"),
            "to_loc": row.get("to_loc"),
            "moved_by": row.get("moved_by"),
            "piece_age_s": row.get("piece_age_s"),
            "history_json": row.get("history_json") or [],
        }
        for row in transfer_rows
        if row.get("ts") is not None
    ]

    resource_rows = fetch_all(
        cur,
        f"""SELECT id, resource_id, resource_type, from_state, to_state,
                   ts, duration_in_prev_s
            FROM {SCHEMA}.resource_state_change
            WHERE run_id = %s
            ORDER BY ts ASC, id ASC""",
        (run_id,),
    )
    resource_changes = [
        {
            "t": seconds_since(reference, row["ts"]),
            "id": row["id"],
            "resource_id": row.get("resource_id"),
            "resource_type": row.get("resource_type"),
            "from_state": row.get("from_state"),
            "to_state": row.get("to_state"),
            "duration_in_prev_s": row.get("duration_in_prev_s"),
        }
        for row in resource_rows
        if row.get("ts") is not None
    ]

    operator_rows = fetch_all(
        cur,
        f"""SELECT id, event_type, description, ts
            FROM {SCHEMA}.operator_event
            WHERE run_id = %s
            ORDER BY ts ASC, id ASC""",
        (run_id,),
    )
    operator_events = [
        {
            "t": seconds_since(reference, row["ts"]),
            "id": row["id"],
            "event_type": row.get("event_type"),
            "description": row.get("description"),
        }
        for row in operator_rows
        if row.get("ts") is not None
    ]

    return {
        "run": json_safe(run),
        "pieces": json_safe(pieces),
        "cycles": json_safe(cycles),
        "transfers": json_safe(transfers),
        "resource_changes": json_safe(resource_changes),
        "operator_events": json_safe(operator_events),
    }


def attach_preset_metadata(replay: dict, preset: dict) -> dict:
    config = replay.get("runConfig") or {}
    replay["label"] = preset["title"]
    replay["meta"] = {
        "key": preset["key"],
        "group": preset["group"],
        "mode": preset["mode"],
        "title": preset["title"],
        "summary": preset["summary"],
        "comparison": preset["comparison"],
        "runId": preset["run_id"],
        "mapMode": config.get("map_mode") or preset["mode"],
        "mapId": config.get("map_id") or "",
    }
    return replay


def build_catalog(output: Path, sample_output: Path, raw_dir: Path | None, extra_run_ids: list[str]) -> None:
    presets = list(DEFAULT_RUNS)
    seen = {preset["run_id"] for preset in presets}
    for run_id in extra_run_ids:
        if run_id in seen:
            continue
        presets.append({"run_id": run_id})
        seen.add(run_id)

    with connect() as conn:
        replays = []
        for preset in presets:
            raw = export_run(conn, preset["run_id"])
            if "key" not in preset:
                preset = auto_preset(raw, preset["run_id"])
            if raw_dir:
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{preset['key']}.json").write_text(
                    json.dumps(raw, indent=2, ensure_ascii=True),
                    encoding="utf-8",
                )
            replay = attach_preset_metadata(build_replay(raw), preset)
            replays.append(replay)

    catalog = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "defaultRunId": "20260710_190550_RBRBRB",
        "runs": replays,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "window.ShipyardRunCatalog = "
        + json.dumps(catalog, indent=2, ensure_ascii=True)
        + ";\nwindow.ShipyardRuns = window.ShipyardRunCatalog.runs;\n",
        encoding="utf-8",
    )

    default_run = next((run for run in replays if run["id"] == catalog["defaultRunId"]), replays[0])
    sample_output.write_text(
        "window.ShipyardSampleRun = "
        + json.dumps(default_run, indent=2, ensure_ascii=True)
        + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {output} with {len(replays)} runs.")
    print(f"Wrote {sample_output} fallback from {default_run['id']}.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-output", type=Path, default=DEFAULT_SAMPLE_OUTPUT)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="Optional directory to cache the exported raw MES JSON files.",
    )
    parser.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Extra MES production_run.run_id to append to the default catalog.",
    )
    args = parser.parse_args()
    build_catalog(args.output, args.sample_output, args.raw_dir, args.run_id)


if __name__ == "__main__":
    main()
