#!/usr/bin/env python3
"""
Cross-machine registry for dynamic-map generation status.

Purpose: multiple computers can each run a batch of compositions (see
run_*_dynamic_maps*.sh) against the SAME shared Postgres DB
(PGHOST, same one db_writer.py uses) and check this table first to avoid
two machines generating the same composition. One row per composition
(n_blue, n_red, n_green), status one of:

    PENDING      -- known about but not started anywhere (not used by sync,
                    only if you pre-register a work plan)
    IN_PROGRESS  -- some machine is currently running generate_dynamic_map.py
                    for it (see mark_in_progress / generate_dynamic_map.py's
                    own --registry hook)
    COMPLETED    -- finished, JSON saved locally on SOME machine, sim-only
    VALIDATED    -- COMPLETED and also confirmed on real hardware (see
                    docs/dynamic_map_*/README.md)

No ROS dependency -- pure psycopg2, same connection convention as
db_writer.py (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE, defaults to the
shared twin_mes_db server).

CLI usage:
    python3 scripts/dynamic_map_registry.py ensure-table
    python3 scripts/dynamic_map_registry.py sync          # scan local dynamic_maps/*.json
                                                            # + docs/dynamic_map_*/ for
                                                            # hardware validation, upsert all
    python3 scripts/dynamic_map_registry.py list          # print full registry table
    python3 scripts/dynamic_map_registry.py list --status PENDING
    python3 scripts/dynamic_map_registry.py mark-in-progress 6 4 2
"""
import argparse
import json
import os
import socket
from datetime import datetime, timezone

_SCHEMA = "shipyard_pnp_ws"
_TABLE = "dynamic_map_registry"

_CONN_DEFAULTS = dict(
    host=os.environ.get("PGHOST", "100.115.213.16"),
    port=int(os.environ.get("PGPORT", "5432")),
    user=os.environ.get("PGUSER", "twin_mes_db"),
    password=os.environ.get("PGPASSWORD", "postgres"),
    dbname=os.environ.get("PGDATABASE", "twin_mes_db"),
)

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_MAPS_DIR = os.path.join(_REPO_ROOT, "src", "shipyard_pnp", "config", "dynamic_maps")
_DOCS_DIR = os.path.join(_REPO_ROOT, "docs")

# Doc folders that don't follow the dynamic_map_{b}b{r}r{g}g naming pattern.
_DOC_FOLDER_OVERRIDES = {
    "dynamic_map_brrbrb": (3, 3, 0),
    "dynamic_map_b6_4b4r3g": (4, 4, 3),
}


def _connect():
    import psycopg2
    return psycopg2.connect(**_CONN_DEFAULTS)


def ensure_table() -> None:
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {_SCHEMA}.{_TABLE} (
        id                     BIGSERIAL   PRIMARY KEY,
        composition_key        TEXT        NOT NULL UNIQUE,
        n_blue                 INT         NOT NULL,
        n_red                  INT         NOT NULL,
        n_green                INT         NOT NULL,
        n_total                INT         NOT NULL,
        status                 TEXT        NOT NULL DEFAULT 'PENDING',
        hostname               TEXT,
        started_at             TIMESTAMPTZ,
        completed_at           TIMESTAMPTZ,
        map_id                 TEXT,
        fixed_best_order       TEXT,
        fixed_best_time_s      FLOAT,
        dynamic_best_order     TEXT,
        dynamic_best_time_s    FLOAT,
        saving_s               FLOAT,
        saving_pct             FLOAT,
        sampled                BOOLEAN,
        permutations_total     BIGINT,
        permutations_searched  INT,
        validated_hw           BOOLEAN     NOT NULL DEFAULT FALSE,
        hw_doc_path            TEXT,
        map_json_path          TEXT,
        created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """
    idx = f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_status ON {_SCHEMA}.{_TABLE}(status)"
    conn = _connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(ddl)
            cur.execute(idx)
        print(f"Table {_SCHEMA}.{_TABLE} ready.")
    finally:
        conn.close()


def _comp_key(n_blue: int, n_red: int, n_green: int) -> str:
    return f"{n_blue}b{n_red}r{n_green}g"


def mark_in_progress(n_blue: int, n_red: int, n_green: int, hostname: str = None) -> None:
    hostname = hostname or socket.gethostname()
    key = _comp_key(n_blue, n_red, n_green)
    conn = _connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.{_TABLE}
                    (composition_key, n_blue, n_red, n_green, n_total,
                     status, hostname, started_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'IN_PROGRESS', %s, NOW(), NOW())
                ON CONFLICT (composition_key) DO UPDATE SET
                    status = 'IN_PROGRESS',
                    hostname = EXCLUDED.hostname,
                    started_at = NOW(),
                    updated_at = NOW()
                """,
                (key, n_blue, n_red, n_green, n_blue + n_red + n_green, hostname),
            )
    finally:
        conn.close()


def mark_completed(
    n_blue: int, n_red: int, n_green: int, *,
    fixed_order: str, fixed_time_s: float,
    dynamic_order: str, dynamic_time_s: float,
    saving_s: float = None, saving_pct: float = None,
    sampled: bool = None, permutations_total: int = None,
    permutations_searched: int = None, map_id: str = None,
    map_json_path: str = None, hostname: str = None,
) -> None:
    hostname = hostname or socket.gethostname()
    key = _comp_key(n_blue, n_red, n_green)
    if saving_pct is None and saving_s is not None and fixed_time_s:
        saving_pct = 100.0 * saving_s / fixed_time_s
    conn = _connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.{_TABLE}
                    (composition_key, n_blue, n_red, n_green, n_total, status,
                     hostname, completed_at, map_id, fixed_best_order,
                     fixed_best_time_s, dynamic_best_order, dynamic_best_time_s,
                     saving_s, saving_pct, sampled, permutations_total,
                     permutations_searched, map_json_path, updated_at)
                VALUES (%s,%s,%s,%s,%s,'COMPLETED',
                        %s, NOW(), %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, NOW())
                ON CONFLICT (composition_key) DO UPDATE SET
                    status = 'COMPLETED',
                    hostname = EXCLUDED.hostname,
                    completed_at = NOW(),
                    map_id = EXCLUDED.map_id,
                    fixed_best_order = EXCLUDED.fixed_best_order,
                    fixed_best_time_s = EXCLUDED.fixed_best_time_s,
                    dynamic_best_order = EXCLUDED.dynamic_best_order,
                    dynamic_best_time_s = EXCLUDED.dynamic_best_time_s,
                    saving_s = EXCLUDED.saving_s,
                    saving_pct = EXCLUDED.saving_pct,
                    sampled = EXCLUDED.sampled,
                    permutations_total = EXCLUDED.permutations_total,
                    permutations_searched = EXCLUDED.permutations_searched,
                    map_json_path = EXCLUDED.map_json_path,
                    updated_at = NOW()
                """,
                (key, n_blue, n_red, n_green, n_blue + n_red + n_green,
                 hostname, map_id, fixed_order,
                 fixed_time_s, dynamic_order, dynamic_time_s,
                 saving_s, saving_pct, sampled, permutations_total,
                 permutations_searched, map_json_path),
            )
    finally:
        conn.close()


def mark_validated(n_blue: int, n_red: int, n_green: int, hw_doc_path: str) -> None:
    key = _comp_key(n_blue, n_red, n_green)
    conn = _connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_SCHEMA}.{_TABLE}
                SET status = 'VALIDATED', validated_hw = TRUE,
                    hw_doc_path = %s, updated_at = NOW()
                WHERE composition_key = %s
                """,
                (hw_doc_path, key),
            )
    finally:
        conn.close()


def sync_from_disk() -> None:
    """Scan dynamic_maps/*.json + docs/dynamic_map_*/ and upsert everything
    found as COMPLETED (or VALIDATED where a hardware doc exists). Safe to
    re-run any time from any machine -- idempotent upserts."""
    ensure_table()

    validated_keys = {}
    for name in os.listdir(_DOCS_DIR):
        full = os.path.join(_DOCS_DIR, name)
        if not os.path.isdir(full) or not name.startswith("dynamic_map_"):
            continue
        if name in _DOC_FOLDER_OVERRIDES:
            b, r, g = _DOC_FOLDER_OVERRIDES[name]
        else:
            comp = name[len("dynamic_map_"):]
            try:
                import re
                m = re.match(r"(\d+)b(\d+)r(\d+)g", comp)
                if not m:
                    continue
                b, r, g = (int(x) for x in m.groups())
            except Exception:
                continue
        validated_keys[_comp_key(b, r, g)] = os.path.join("docs", name, "README.md")

    if not os.path.isdir(_MAPS_DIR):
        print(f"No maps directory at {_MAPS_DIR}, nothing to sync.")
        return

    n_synced = 0
    for fname in sorted(os.listdir(_MAPS_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(_MAPS_DIR, fname)
        with open(path) as fh:
            d = json.load(fh)
        comp = d.get("composition", {})
        b, r, g = comp.get("BLUE", 0), comp.get("RED", 0), comp.get("GREEN", 0)
        key = _comp_key(b, r, g)
        stats = d.get("search_stats", {})
        mark_completed(
            b, r, g,
            fixed_order=d.get("fixed_reference_order"),
            fixed_time_s=d.get("fixed_reference_time_s"),
            dynamic_order=d.get("best_order"),
            dynamic_time_s=d.get("best_time_s"),
            saving_s=d.get("saving_s"),
            sampled=stats.get("sampled"),
            permutations_total=stats.get("permutations_total"),
            permutations_searched=stats.get("permutations_searched"),
            map_id=d.get("map_id"),
            map_json_path=os.path.relpath(path, _REPO_ROOT),
        )
        n_synced += 1
        if key in validated_keys:
            mark_validated(b, r, g, validated_keys[key])
            print(f"  {key}: COMPLETED + VALIDATED ({validated_keys[key]})")
        else:
            print(f"  {key}: COMPLETED")

    print(f"\nSynced {n_synced} maps from {_MAPS_DIR}"
          f" ({len(validated_keys)} have hardware validation docs).")


def list_registry(status_filter: str = None) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if status_filter:
                cur.execute(
                    f"""SELECT composition_key, n_total, status, hostname,
                               dynamic_best_time_s, saving_pct, validated_hw
                        FROM {_SCHEMA}.{_TABLE}
                        WHERE status = %s
                        ORDER BY n_total, composition_key""",
                    (status_filter,),
                )
            else:
                cur.execute(
                    f"""SELECT composition_key, n_total, status, hostname,
                               dynamic_best_time_s, saving_pct, validated_hw
                        FROM {_SCHEMA}.{_TABLE}
                        ORDER BY n_total, composition_key"""
                )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print("(vacío)")
        return
    print(f"{'composition':<14} {'n':>3}  {'status':<12} {'hostname':<15} "
          f"{'dyn_time_s':>10} {'saving%':>8}  hw")
    for key, n, status, hostname, dyn_t, pct, hw in rows:
        dyn_s = f"{dyn_t:.1f}" if dyn_t is not None else "—"
        pct_s = f"{pct:+.1f}" if pct is not None else "—"
        print(f"{key:<14} {n:>3}  {status:<12} {(hostname or '—'):<15} "
              f"{dyn_s:>10} {pct_s:>8}  {'YES' if hw else ''}")
    print(f"\n{len(rows)} rows.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ensure-table")
    sub.add_parser("sync")

    p_list = sub.add_parser("list")
    p_list.add_argument("--status", choices=["PENDING", "IN_PROGRESS", "COMPLETED", "VALIDATED"])

    p_prog = sub.add_parser("mark-in-progress")
    p_prog.add_argument("n_blue", type=int)
    p_prog.add_argument("n_red", type=int)
    p_prog.add_argument("n_green", type=int)
    p_prog.add_argument("--hostname", default=None)

    args = parser.parse_args()
    if args.cmd == "ensure-table":
        ensure_table()
    elif args.cmd == "sync":
        sync_from_disk()
    elif args.cmd == "list":
        list_registry(args.status)
    elif args.cmd == "mark-in-progress":
        mark_in_progress(args.n_blue, args.n_red, args.n_green, args.hostname)
        print(f"Marked {_comp_key(args.n_blue, args.n_red, args.n_green)} IN_PROGRESS on "
              f"{args.hostname or socket.gethostname()}.")


if __name__ == "__main__":
    main()
