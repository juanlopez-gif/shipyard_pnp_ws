#!/usr/bin/env python3
"""
MES analytics worker.

Reads the current Shipyard PnP production database, maps the live cycle names
to MES work-centers, and writes wc_metrics_history/mes_alarms.
Production events remain in shipyard_pnp_ws and are read directly by the MES.
"""

from __future__ import annotations

import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
import psycopg2.extras


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

TEL_HOST = os.environ.get("PGHOST", "100.115.213.16")
TEL_PORT = int(os.environ.get("PGPORT", "5432"))
TEL_DB = os.environ.get("PGDATABASE", "twin_mes_db")
TEL_USER = os.environ.get("PGUSER", "twin_mes_db")
TEL_PASSWORD = os.environ.get("PGPASSWORD", "postgres")
TEL_SCHEMA = os.environ.get("MES_PGSCHEMA", os.environ.get("PGSCHEMA", "mes_pnp_v2"))

SRC_HOST = os.environ.get("MES_SRC_PGHOST", TEL_HOST)
SRC_PORT = int(os.environ.get("MES_SRC_PGPORT", str(TEL_PORT)))
SRC_DB = os.environ.get("MES_SRC_PGDATABASE", TEL_DB)
SRC_USER = os.environ.get("MES_SRC_PGUSER", TEL_USER)
SRC_PASSWORD = os.environ.get("MES_SRC_PGPASSWORD", TEL_PASSWORD)
SRC_SCHEMA = os.environ.get("MES_SRC_PGSCHEMA", "shipyard_pnp_ws")

LIVE_INTERVAL_S = float(os.environ.get("MES_ANALYTICS_INTERVAL_S", "30"))
LIVE_WINDOW_H = float(os.environ.get("MES_ANALYTICS_WINDOW_H", "1.0"))
MIN_CYCLES_PER_WC = int(os.environ.get("MES_MIN_CYCLES_PER_WC", "1"))

SOURCE_DB_LABEL = f"{SRC_HOST}:{SRC_PORT}/{SRC_DB}"


TASK_TO_WC = {
    # Current Shipyard PnP cycle names.
    ("xarm2", "FEED_GREEN_TO_C3"): "xArm2 feed to C3",
    ("xarm2", "FEED_TO_C1S1"): "xArm2 feed to C1S1",
    ("xarm1", "C1S2_TO_C2S1"): "xArm1 C1S2 to C2S1",
    ("xarm1", "C1S2_TO_LASER"): "xArm1 C1S2 to Laser",
    ("xarm1", "LASER_TO_C2S1"): "xArm1 Laser to C2S1",
    ("laser", "PROCESS_RED"): "Laser process red",
    ("robot2", "CLASSIFY_C2S2_TO_C4"): "Robot2 C2S2 to C4",
    ("robot2", "CLASSIFY_C2S2_TO_BANTAM"): "Robot2 C2S2 to Bantam",
    ("robot2", "CLASSIFY_C2S2_TO_IBS"): "Robot2 C2S2 to IBS",
    ("robot2", "IBS_TO_BANTAM"): "Robot2 IBS to Bantam",
    ("robot2", "BANTAM_TO_C4"): "Robot2 Bantam to C4",
    ("bantam", "PROCESS_BLUE"): "Bantam process blue",
    ("robot1", "UNLOAD_C3"): "Robot1 unload C3",
    ("robot1", "UNLOAD_C4"): "Robot1 unload C4",
}


WC_META = {
    "xArm2 feed to C3": {"part_colors": ["GREEN"]},
    "xArm2 feed to C1S1": {"part_colors": ["RED", "BLUE"]},
    "xArm1 C1S2 to C2S1": {"part_colors": ["GREEN", "BLUE"]},
    "xArm1 C1S2 to Laser": {"part_colors": ["RED"]},
    "xArm1 Laser to C2S1": {"part_colors": ["RED"]},
    "Laser process red": {"part_colors": ["RED"]},
    "Robot2 C2S2 to C4": {"part_colors": ["RED", "GREEN"]},
    "Robot2 C2S2 to Bantam": {"part_colors": ["BLUE"]},
    "Robot2 C2S2 to IBS": {"part_colors": ["BLUE"]},
    "Robot2 IBS to Bantam": {"part_colors": ["BLUE"]},
    "Robot2 Bantam to C4": {"part_colors": ["BLUE"]},
    "Bantam process blue": {"part_colors": ["BLUE"]},
    "Robot1 unload C3": {"part_colors": ["GREEN", "RED", "BLUE"]},
    "Robot1 unload C4": {"part_colors": ["RED", "BLUE", "GREEN"]},
}


def qident(value: str) -> str:
    if not IDENT_RE.match(value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return value


def qname(schema: str, table: str) -> str:
    return f"{qident(schema)}.{qident(table)}"


def tel_connect():
    return psycopg2.connect(
        host=TEL_HOST,
        port=TEL_PORT,
        dbname=TEL_DB,
        user=TEL_USER,
        password=TEL_PASSWORD,
        connect_timeout=5,
    )


def src_connect():
    return psycopg2.connect(
        host=SRC_HOST,
        port=SRC_PORT,
        dbname=SRC_DB,
        user=SRC_USER,
        password=SRC_PASSWORD,
        connect_timeout=5,
    )


def ensure_tel_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {qident(TEL_SCHEMA)}")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {qname(TEL_SCHEMA, "wc_metrics_history")} (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                window_start TIMESTAMPTZ NOT NULL,
                window_end TIMESTAMPTZ NOT NULL,
                wc_name TEXT NOT NULL,
                run_id TEXT NOT NULL DEFAULT 'UNKNOWN',
                rho DOUBLE PRECISION,
                lq DOUBLE PRECISION,
                wq DOUBLE PRECISION,
                avg_s DOUBLE PRECISION,
                sigma_s DOUBLE PRECISION,
                lambda_s DOUBLE PRECISION,
                n_samples INTEGER DEFAULT 0,
                is_bottleneck BOOLEAN DEFAULT FALSE
            );
            ALTER TABLE {qname(TEL_SCHEMA, "wc_metrics_history")}
                ADD COLUMN IF NOT EXISTS ts TIMESTAMPTZ NOT NULL DEFAULT NOW();
            ALTER TABLE {qname(TEL_SCHEMA, "wc_metrics_history")}
                ADD COLUMN IF NOT EXISTS run_id TEXT NOT NULL DEFAULT 'UNKNOWN';
            CREATE INDEX IF NOT EXISTS idx_wch_ts
                ON {qname(TEL_SCHEMA, "wc_metrics_history")} (ts DESC);
            CREATE INDEX IF NOT EXISTS idx_wch_wc_ts
                ON {qname(TEL_SCHEMA, "wc_metrics_history")} (wc_name, ts DESC);

            CREATE TABLE IF NOT EXISTS {qname(TEL_SCHEMA, "mes_alarms")} (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                severity TEXT NOT NULL,
                alarm_type TEXT NOT NULL,
                entity TEXT,
                message TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                run_id TEXT NOT NULL DEFAULT 'UNKNOWN'
            );
            ALTER TABLE {qname(TEL_SCHEMA, "mes_alarms")}
                ADD COLUMN IF NOT EXISTS run_id TEXT NOT NULL DEFAULT 'UNKNOWN';
        """)
    conn.commit()


def window_run_id(src_conn, window_start, window_end) -> str:
    with src_conn.cursor() as cur:
        cur.execute(f"""
            SELECT run_id
            FROM {qname(SRC_SCHEMA, "cycle_event")}
            WHERE ts >= %s AND ts <= %s
            GROUP BY run_id
            ORDER BY MAX(ts) DESC
            LIMIT 1
        """, (window_start, window_end))
        row = cur.fetchone()
    return row[0] if row else "UNKNOWN"


def compute_window(src_conn, window_start, window_end):
    window_s = max((window_end - window_start).total_seconds(), 1.0)
    with src_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""
            SELECT entity, task_name, COALESCE(color, 'UNKNOWN') AS color,
                   COUNT(*) AS n,
                   AVG(total_duration_s) AS avg_s,
                   STDDEV(total_duration_s) AS sigma_s
            FROM {qname(SRC_SCHEMA, "cycle_event")}
            WHERE is_discarded = false
              AND total_duration_s > 0
              AND ts >= %s AND ts <= %s
            GROUP BY entity, task_name, COALESCE(color, 'UNKNOWN')
        """, (window_start, window_end))
        cycle_rows = cur.fetchall()

    wc_raw = {}
    for row in cycle_rows:
        entity = row["entity"]
        task_name = row["task_name"]
        wc = TASK_TO_WC.get((entity, task_name), f"{entity}:{task_name}")
        n = int(row["n"])
        avg = float(row["avg_s"]) if row["avg_s"] is not None else 0.0
        sig = float(row["sigma_s"]) if row["sigma_s"] is not None else 0.0
        if wc not in wc_raw:
            wc_raw[wc] = {
                "n": 0,
                "weighted_avg": 0.0,
                "samples": [],
                "colors": set(),
            }
        wc_raw[wc]["n"] += n
        wc_raw[wc]["weighted_avg"] += n * avg
        wc_raw[wc]["samples"].append({"n": n, "avg": avg, "sig": sig})
        if row["color"] and row["color"] != "UNKNOWN":
            wc_raw[wc]["colors"].add(row["color"])

    metrics = {}
    for wc, raw in wc_raw.items():
        n = raw["n"]
        if n < MIN_CYCLES_PER_WC:
            continue
        avg_s = raw["weighted_avg"] / n
        pooled_var = sum(
            s["n"] * (s["sig"] ** 2 + (s["avg"] - avg_s) ** 2)
            for s in raw["samples"]
        ) / n
        sigma_s = math.sqrt(max(pooled_var, 0.0))
        lam = n / window_s
        rho = lam * avg_s if avg_s > 0 else None
        wq = lq = None
        if rho is not None and 0.0 < rho < 1.0:
            cv2 = (sigma_s / avg_s) ** 2 if sigma_s else 0.0
            wq = (rho / (1.0 - rho)) * avg_s * (1.0 + cv2) / 2.0
            lq = lam * wq

        metrics[wc] = {
            "avg_s": round(avg_s, 3),
            "sigma_s": round(sigma_s, 3),
            "lambda_s": round(lam, 8),
            "rho": round(rho, 4) if rho is not None else None,
            "lq": round(lq, 4) if lq is not None else None,
            "wq": round(wq, 2) if wq is not None else None,
            "n_samples": n,
            "is_bottleneck": False,
            "part_colors": sorted(raw["colors"] or set(WC_META.get(wc, {}).get("part_colors", []))),
        }

    bn = None
    if metrics:
        rho_map = {wc: m["rho"] for wc, m in metrics.items() if m["rho"] is not None}
        if rho_map:
            bn = max(rho_map, key=rho_map.get)
        else:
            bn = max(metrics, key=lambda wc: metrics[wc]["avg_s"])
        metrics[bn]["is_bottleneck"] = True
    return metrics, bn


def write_metrics(tel_conn, window_start, window_end, metrics, run_id: str, ts=None) -> int:
    if not metrics:
        return 0
    ts = ts or datetime.now(timezone.utc)
    with tel_conn.cursor() as cur:
        for wc, m in metrics.items():
            cur.execute(f"""
                INSERT INTO {qname(TEL_SCHEMA, "wc_metrics_history")}
                    (ts, window_start, window_end, wc_name, run_id,
                     rho, lq, wq, avg_s, sigma_s, lambda_s, n_samples, is_bottleneck)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                ts,
                window_start,
                window_end,
                wc,
                run_id,
                m.get("rho"),
                m.get("lq"),
                m.get("wq"),
                m.get("avg_s"),
                m.get("sigma_s"),
                m.get("lambda_s"),
                m.get("n_samples", 0),
                m.get("is_bottleneck", False),
            ))
    tel_conn.commit()
    return len(metrics)


def write_alarms(tel_conn, window_end, metrics, bn, prev_bn, run_id: str) -> int:
    alarms = []
    if bn and prev_bn and bn != prev_bn:
        bn_rho = (metrics.get(bn) or {}).get("rho")
        alarms.append({
            "severity": "WARNING",
            "alarm_type": "BOTTLENECK_CHANGE",
            "entity": bn,
            "message": f"Bottleneck shifted: {prev_bn} -> {bn}"
            + (f" (rho={bn_rho:.3f})" if bn_rho is not None else ""),
            "old_value": prev_bn,
            "new_value": bn,
        })

    for wc, m in metrics.items():
        rho = m.get("rho")
        lq = m.get("lq")
        wq = m.get("wq")
        n = m.get("n_samples", 0)
        avg_s = m.get("avg_s") or 0.0
        if rho is not None:
            rho_s = f"{rho:.3f}"
            if rho >= 1.0:
                alarms.append({
                    "severity": "CRITICAL",
                    "alarm_type": "RHO_UNSTABLE",
                    "entity": wc,
                    "message": f"{wc} unstable utilization: rho={rho_s} (avg={avg_s:.1f}s, n={n})",
                    "new_value": rho_s,
                })
            elif rho >= 0.8:
                alarms.append({
                    "severity": "WARNING",
                    "alarm_type": "RHO_HIGH",
                    "entity": wc,
                    "message": f"{wc} high utilization: rho={rho_s} (avg={avg_s:.1f}s, n={n})",
                    "new_value": rho_s,
                })
        if lq is not None and lq > 1.0:
            alarms.append({
                "severity": "CRITICAL" if lq > 5.0 else "WARNING",
                "alarm_type": "LQ_CRITICAL" if lq > 5.0 else "LQ_HIGH",
                "entity": wc,
                "message": f"{wc} queue: Lq={lq:.2f} jobs, Wq={wq:.0f}s",
                "new_value": f"{lq:.2f}",
            })

    with tel_conn.cursor() as cur:
        for alarm in alarms:
            cur.execute(f"""
                INSERT INTO {qname(TEL_SCHEMA, "mes_alarms")}
                    (ts, severity, alarm_type, entity, message, old_value, new_value, run_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                window_end,
                alarm["severity"],
                alarm["alarm_type"],
                alarm["entity"],
                alarm["message"],
                alarm.get("old_value"),
                alarm.get("new_value"),
                run_id,
            ))
    tel_conn.commit()
    return len(alarms)


def count_source_events(src_conn, window_start, window_end) -> tuple[int, int]:
    with src_conn.cursor() as cur:
        cur.execute(f"""
            SELECT COUNT(*)
            FROM {qname(SRC_SCHEMA, "cycle_event")}
            WHERE ts >= %s AND ts <= %s
        """, (window_start, window_end))
        cycle_rows = int(cur.fetchone()[0])
        cur.execute(f"""
            SELECT COUNT(*)
            FROM {qname(SRC_SCHEMA, "piece_transfer")}
            WHERE ts >= %s AND ts <= %s
        """, (window_start, window_end))
        transfer_rows = int(cur.fetchone()[0])
    return cycle_rows, transfer_rows


def parse_ts(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {value!r}")


def autodetect_range(src_conn):
    with src_conn.cursor() as cur:
        cur.execute(f"""
            SELECT MIN(ts), MAX(ts)
            FROM {qname(SRC_SCHEMA, "cycle_event")}
            WHERE is_discarded = false
        """)
        row = cur.fetchone()
    if not row or row[0] is None:
        raise ValueError("No source cycle_event rows found")
    return row[0], row[1]


def run_once(window_start: Optional[datetime] = None, window_end: Optional[datetime] = None, prev_bn=None):
    src_conn = src_connect()
    tel_conn = tel_connect()
    try:
        ensure_tel_tables(tel_conn)

        if window_end is None:
            window_end = datetime.now(timezone.utc)
        if window_start is None:
            window_start = window_end - timedelta(hours=LIVE_WINDOW_H)
        run_id = window_run_id(src_conn, window_start, window_end)
        cycle_rows, transfer_rows = count_source_events(src_conn, window_start, window_end)
        metrics, bn = compute_window(src_conn, window_start, window_end)
        metric_rows = write_metrics(tel_conn, window_start, window_end, metrics, run_id, ts=window_end)
        alarm_rows = write_alarms(tel_conn, window_end, metrics, bn, prev_bn, run_id)
        return {
            "window_start": window_start,
            "window_end": window_end,
            "run_id": run_id,
            "metrics": metric_rows,
            "alarms": alarm_rows,
            "cycle_rows": cycle_rows,
            "transfer_rows": transfer_rows,
            "bottleneck": bn,
        }
    finally:
        tel_conn.close()
        src_conn.close()


def backfill(start_arg: Optional[str] = None, end_arg: Optional[str] = None, window_hours: float = 1.0):
    src_conn = src_connect()
    try:
        if start_arg and end_arg:
            start, end = parse_ts(start_arg), parse_ts(end_arg)
        else:
            start, end = autodetect_range(src_conn)
    finally:
        src_conn.close()

    if start >= end:
        raise ValueError("start must be before end")

    total_metrics = total_alarms = total_cycles = total_transfers = 0
    prev_bn = None
    delta = timedelta(hours=window_hours)
    current = start
    windows = 0
    print(f"Backfill source range {start} -> {end}, window_h={window_hours}")
    while current < end:
        win_end = min(current + delta, end)
        result = run_once(current, win_end, prev_bn)
        prev_bn = result["bottleneck"]
        total_metrics += result["metrics"]
        total_alarms += result["alarms"]
        total_cycles += result["cycle_rows"]
        total_transfers += result["transfer_rows"]
        windows += 1
        print(
            f"[{windows}] {current:%Y-%m-%d %H:%M:%S} -> {win_end:%H:%M:%S} "
            f"metrics={result['metrics']} source_cycles={result['cycle_rows']} "
            f"transfers={result['transfer_rows']} bn={result['bottleneck']}"
        )
        current = win_end
    print(
        f"Backfill done: windows={windows}, metrics={total_metrics}, "
        f"alarms={total_alarms}, source_cycles={total_cycles}, "
        f"source_transfers={total_transfers}"
    )


def run_live():
    print(
        "MES analytics worker live "
        f"source={SOURCE_DB_LABEL}.{SRC_SCHEMA} "
        f"interval={LIVE_INTERVAL_S}s window={LIVE_WINDOW_H}h"
    )
    prev_bn = None
    while True:
        try:
            result = run_once(prev_bn=prev_bn)
            prev_bn = result["bottleneck"]
            print(
                f"[{datetime.now(timezone.utc):%H:%M:%S}] "
                f"metrics={result['metrics']} source_cycles={result['cycle_rows']} "
                f"transfers={result['transfer_rows']} bn={result['bottleneck']}"
            )
        except psycopg2.OperationalError as exc:
            print(f"DB connection lost: {exc}")
        except Exception as exc:
            print(f"Worker error: {exc}")
        time.sleep(LIVE_INTERVAL_S)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "backfill":
        if len(argv) >= 3:
            window_h = float(argv[3]) if len(argv) >= 4 else 1.0
            backfill(argv[1], argv[2], window_h)
        else:
            window_h = float(argv[1]) if len(argv) >= 2 else 1.0
            backfill(window_hours=window_h)
    elif argv and argv[0] == "once":
        if len(argv) >= 3:
            result = run_once(parse_ts(argv[1]), parse_ts(argv[2]))
        else:
            result = run_once()
        print(result)
    else:
        run_live()


if __name__ == "__main__":
    main()
