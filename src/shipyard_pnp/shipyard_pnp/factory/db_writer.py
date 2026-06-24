"""
Shipyard 4.0 — PostgreSQL writer

Two implementations behind a common interface:

  StubDBWriter  — log-only, no DB required (default during development).
  RealDBWriter  — live PostgreSQL.

RealDBWriter behaviour:
  • On first call creates database `shipyard_pnp_db` (or falls back to the
    existing DB if CREATE DATABASE is refused) then schema `shipyard_pnp_ws`
    and all tables (CREATE … IF NOT EXISTS — idempotent).
  • Generates a human-readable run_id once at __init__ and stamps it on
    every row it writes.  Callers never need to know the run_id.
  • All DB calls are wrapped in try/except — a network hiccup never crashes
    the factory; the error is logged and the call is silently skipped.
  • Thread-safe: one Lock guards all cursor use.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Optional

_log = logging.getLogger(__name__)

# ── Target schema (inside the configured database) ───────────────────────────
_SCHEMA = "shipyard_pnp_ws"

# ── Connection defaults (overridden by environment variables) ─────────────────
import os
_CONN_DEFAULTS = dict(
    host     = os.environ.get("PGHOST",     "100.115.213.16"),
    port     = int(os.environ.get("PGPORT", "5432")),
    user     = os.environ.get("PGUSER",     "twin_mes_db"),
    password = os.environ.get("PGPASSWORD", "postgres"),
    dbname   = os.environ.get("PGDATABASE", "twin_mes_db"),
)


# ─────────────────────────────────────────────────────────────────────────────
# DDL — all tables in one place
# ─────────────────────────────────────────────────────────────────────────────

def _ddl(schema: str) -> list[str]:
    S = schema
    return [
        # ── Meta ──────────────────────────────────────────────────────────────
        f"""
        CREATE TABLE IF NOT EXISTS {S}.production_run (
            run_id              TEXT        PRIMARY KEY,
            started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at         TIMESTAMPTZ,
            status              TEXT        NOT NULL DEFAULT 'RUNNING',
            original_order      JSONB,
            optimized_order     JSONB,
            optimizer_savings_s FLOAT,
            total_pieces        INT,
            pieces_completed    INT         NOT NULL DEFAULT 0,
            git_commit          TEXT,
            config_snapshot     JSONB
        )""",

        # ── Pieces ────────────────────────────────────────────────────────────
        f"""
        CREATE TABLE IF NOT EXISTS {S}.piece (
            piece_id         TEXT        NOT NULL,
            run_id           TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            color            TEXT,
            shape            TEXT,
            initial_position INT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (piece_id, run_id)
        )""",

        f"""
        CREATE TABLE IF NOT EXISTS {S}.piece_transfer (
            id           BIGSERIAL   PRIMARY KEY,
            run_id       TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            piece_id     TEXT,
            from_loc     TEXT        NOT NULL,
            to_loc       TEXT        NOT NULL,
            moved_by     TEXT,
            ts           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            piece_age_s  FLOAT,
            history_json JSONB
        )""",

        f"""
        CREATE TABLE IF NOT EXISTS {S}.piece_outcome (
            piece_id       TEXT        NOT NULL,
            run_id         TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            route_taken    TEXT,
            final_location TEXT,
            total_time_s   FLOAT,
            completed      BOOLEAN     NOT NULL DEFAULT FALSE,
            completed_at   TIMESTAMPTZ,
            PRIMARY KEY (piece_id, run_id)
        )""",

        f"""
        CREATE TABLE IF NOT EXISTS {S}.cycle_event (
            id               BIGSERIAL   PRIMARY KEY,
            run_id           TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            ts               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            entity           TEXT        NOT NULL,
            task_name        TEXT        NOT NULL,
            cycle_number     INT,
            piece_id         TEXT,
            color            TEXT,
            route            TEXT,
            started_at       TIMESTAMPTZ,
            completed_at     TIMESTAMPTZ,
            total_duration_s FLOAT,
            is_discarded     BOOLEAN     NOT NULL DEFAULT FALSE,
            discarded_reason TEXT,
            phases           JSONB,
            metadata         JSONB
        )""",

        # ── Robot / Machine ───────────────────────────────────────────────────
        f"""
        CREATE TABLE IF NOT EXISTS {S}.robot_task (
            id           BIGSERIAL   PRIMARY KEY,
            run_id       TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            command_id   TEXT,
            robot_id     TEXT        NOT NULL,
            task_name    TEXT        NOT NULL,
            piece_id     TEXT,
            source       TEXT,
            target       TEXT,
            started_at   TIMESTAMPTZ,
            finished_at  TIMESTAMPTZ,
            duration_s   FLOAT,
            result       TEXT,
            error_detail TEXT
        )""",

        f"""
        CREATE TABLE IF NOT EXISTS {S}.machine_job (
            id             BIGSERIAL   PRIMARY KEY,
            run_id         TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            command_id     TEXT,
            machine_id     TEXT        NOT NULL,
            piece_id       TEXT,
            started_at     TIMESTAMPTZ,
            finished_at    TIMESTAMPTZ,
            duration_s     FLOAT,
            door_open_at   TIMESTAMPTZ,
            door_close_at  TIMESTAMPTZ,
            door_duration_s FLOAT,
            result         TEXT
        )""",

        # ── Vision ────────────────────────────────────────────────────────────
        f"""
        CREATE TABLE IF NOT EXISTS {S}.vision_detection (
            id              BIGSERIAL   PRIMARY KEY,
            run_id          TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            vision_system   TEXT        NOT NULL,
            piece_id        TEXT,
            detected_color  TEXT,
            detected_shape  TEXT,
            slot_id         TEXT,
            started_at      TIMESTAMPTZ,
            duration_s      FLOAT,
            success         BOOLEAN
        )""",

        # ── Resource telemetry ────────────────────────────────────────────────
        f"""
        CREATE TABLE IF NOT EXISTS {S}.resource_state_change (
            id                 BIGSERIAL   PRIMARY KEY,
            run_id             TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            resource_id        TEXT        NOT NULL,
            resource_type      TEXT        NOT NULL,
            from_state         TEXT,
            to_state           TEXT        NOT NULL,
            ts                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            duration_in_prev_s FLOAT
        )""",

        f"""
        CREATE TABLE IF NOT EXISTS {S}.queue_depth_sample (
            id          BIGSERIAL   PRIMARY KEY,
            run_id      TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            sampled_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            location    TEXT        NOT NULL,
            depth       INT         NOT NULL
        )""",

        # ── Topic messages ────────────────────────────────────────────────────
        f"""
        CREATE TABLE IF NOT EXISTS {S}.command_log (
            id             BIGSERIAL   PRIMARY KEY,
            run_id         TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            command_id     TEXT        UNIQUE NOT NULL,
            domain_id      TEXT        NOT NULL,
            resource_id    TEXT        NOT NULL,
            task_name      TEXT        NOT NULL,
            piece_id       TEXT,
            source         TEXT,
            target         TEXT,
            route          TEXT,
            parameters     JSONB,
            sent_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            correlation_id TEXT
        )""",

        f"""
        CREATE TABLE IF NOT EXISTS {S}.ack_log (
            id             BIGSERIAL   PRIMARY KEY,
            run_id         TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            command_id     TEXT,
            domain_id      TEXT        NOT NULL,
            resource_id    TEXT,
            task_state     TEXT,
            resource_state TEXT,
            result         JSONB,
            received_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            latency_ms     INT
        )""",

        f"""
        CREATE TABLE IF NOT EXISTS {S}.status_log (
            id             BIGSERIAL   PRIMARY KEY,
            run_id         TEXT        NOT NULL REFERENCES {S}.production_run(run_id),
            domain_id      TEXT        NOT NULL,
            resource_id    TEXT,
            topic          TEXT,
            resource_state TEXT,
            task_state     TEXT,
            code           TEXT,
            result         JSONB,
            command_id     TEXT,
            published_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",

        # ── Optimizer & Operators ─────────────────────────────────────────────
        f"""
        CREATE TABLE IF NOT EXISTS {S}.optimizer_run (
            id                    BIGSERIAL   PRIMARY KEY,
            run_id                TEXT        REFERENCES {S}.production_run(run_id),
            original_order        JSONB,
            best_order            JSONB,
            original_time_s       FLOAT,
            best_time_s           FLOAT,
            saving_s              FLOAT,
            saving_pct            FLOAT,
            method                TEXT,
            permutations_evaluated INT,
            optimizer_runtime_s   FLOAT,
            applied               BOOLEAN     NOT NULL DEFAULT FALSE,
            applied_at            TIMESTAMPTZ,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",

        f"""
        CREATE TABLE IF NOT EXISTS {S}.operator_event (
            id          BIGSERIAL   PRIMARY KEY,
            run_id      TEXT        REFERENCES {S}.production_run(run_id),
            event_type  TEXT        NOT NULL,
            description TEXT,
            ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",

        f"""
        CREATE TABLE IF NOT EXISTS {S}.alarm_event (
            id               BIGSERIAL   PRIMARY KEY,
            run_id           TEXT        REFERENCES {S}.production_run(run_id),
            severity         TEXT        NOT NULL,
            resource_id      TEXT,
            description      TEXT        NOT NULL,
            context_snapshot JSONB,
            triggered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at      TIMESTAMPTZ
        )""",

        # ── Indexes ───────────────────────────────────────────────────────────
        f"CREATE INDEX IF NOT EXISTS idx_piece_transfer_run    ON {S}.piece_transfer(run_id)",
        f"CREATE INDEX IF NOT EXISTS idx_piece_transfer_piece  ON {S}.piece_transfer(piece_id)",
        f"CREATE INDEX IF NOT EXISTS idx_cycle_event_run       ON {S}.cycle_event(run_id)",
        f"CREATE INDEX IF NOT EXISTS idx_robot_task_run        ON {S}.robot_task(run_id)",
        f"CREATE INDEX IF NOT EXISTS idx_robot_task_cmd        ON {S}.robot_task(command_id)",
        f"CREATE INDEX IF NOT EXISTS idx_machine_job_run       ON {S}.machine_job(run_id)",
        f"CREATE INDEX IF NOT EXISTS idx_resource_state_run    ON {S}.resource_state_change(run_id)",
        f"CREATE INDEX IF NOT EXISTS idx_resource_state_res    ON {S}.resource_state_change(resource_id)",
        f"CREATE INDEX IF NOT EXISTS idx_command_log_run       ON {S}.command_log(run_id)",
        f"CREATE INDEX IF NOT EXISTS idx_ack_log_cmd           ON {S}.ack_log(command_id)",
        f"CREATE INDEX IF NOT EXISTS idx_status_log_run        ON {S}.status_log(run_id)",
        f"CREATE INDEX IF NOT EXISTS idx_status_log_cmd        ON {S}.status_log(command_id)",
        f"CREATE INDEX IF NOT EXISTS idx_queue_depth_run       ON {S}.queue_depth_sample(run_id, sampled_at)",
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _generate_run_id(initial_stack_order: list) -> str:
    initials = "".join(
        (e.get("color") if isinstance(e, dict) else e)[0].upper()
        for e in initial_stack_order
        if (e.get("color") if isinstance(e, dict) else e)
    )
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{initials}"


def _git_commit() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# StubDBWriter
# ─────────────────────────────────────────────────────────────────────────────

class StubDBWriter:
    """Log-only writer used during development and unit tests. No DB needed."""

    run_id: str = "stub"

    # kept for backward compatibility ─────────────────────────────────────────
    def insert_piece_transfer(self, piece: dict, from_loc: str, to_loc: str) -> None:
        _log.debug("DB(stub) piece_transfer: %s %s→%s", piece.get("id"), from_loc, to_loc)

    def insert_cycle_complete(self, record: Any) -> None:
        _log.debug("DB(stub) cycle_complete: %s %.1fs %s",
                   record.piece_id, record.cycle_time_sec, record.route)

    def insert_entity_cycle(self, cycle: Any) -> None:
        status = "DISCARDED" if cycle.is_discarded else "OK"
        _log.debug("DB(stub) entity_cycle: %s/%s #%d %s dur=%.3fs",
                   cycle.entity, cycle.task_name, cycle.cycle_number,
                   status, cycle.total_duration_s or 0)

    # new methods ─────────────────────────────────────────────────────────────
    def insert_piece(self, piece: dict, position: int) -> None: pass
    def insert_piece_outcome(self, piece_id, route, final_location, completed, completed_at=None, total_time_s=None) -> None: pass
    def insert_robot_task(self, command_id, robot_id, task_name, piece_id=None, source=None, target=None, started_at=None, finished_at=None, duration_s=None, result=None, error_detail=None) -> None: pass
    def insert_machine_job(self, command_id, machine_id, piece_id=None, started_at=None, finished_at=None, duration_s=None, door_open_at=None, door_close_at=None, result=None) -> None: pass
    def insert_vision_detection(self, vision_system, piece_id=None, detected_color=None, detected_shape=None, slot_id=None, started_at=None, duration_s=None, success=None) -> None: pass
    def insert_resource_state_change(self, resource_id, resource_type, from_state, to_state, duration_in_prev_s=None) -> None: pass
    def insert_queue_depth_sample(self, samples: dict) -> None: pass
    def insert_command(self, command_id, domain_id, resource_id, task_name, piece_id=None, source=None, target=None, route=None, parameters=None, correlation_id=None) -> None: pass
    def insert_ack(self, command_id, domain_id, resource_id, task_state, resource_state=None, result=None, sent_at=None) -> None: pass
    def insert_status(self, domain_id, resource_id, topic, resource_state=None, task_state=None, code=None, result=None, command_id=None) -> None: pass
    def insert_optimizer_result(self, original_order, best_order, original_time_s, best_time_s, saving_s, saving_pct, method, permutations_evaluated, optimizer_runtime_s) -> Optional[int]: return None
    def update_optimizer_applied(self, optimizer_id: int) -> None: pass
    def insert_operator_event(self, event_type: str, description: str = "") -> None: pass
    def insert_alarm(self, severity, resource_id, description, context_snapshot=None) -> Optional[int]: return None
    def resolve_alarm(self, alarm_id: int) -> None: pass
    def update_production_run_finished(self, status: str = "COMPLETED") -> None: pass
    def update_production_run_optimized_order(self, optimized_order: list, saving_s: float) -> None: pass
    def close(self) -> None: pass


# ─────────────────────────────────────────────────────────────────────────────
# RealDBWriter
# ─────────────────────────────────────────────────────────────────────────────

class RealDBWriter:
    """
    Live PostgreSQL writer.

    Creates `shipyard_pnp_db` + schema `shipyard_pnp_ws` and all tables on
    first run.  Every insert method silently swallows DB errors so the factory
    never crashes due to a persistence failure.
    """

    def __init__(self, initial_stack_order: list, config_snapshot: Optional[dict] = None):
        self.run_id: str = _generate_run_id(initial_stack_order)
        self._lock   = threading.Lock()
        self._conn   = None
        self._schema = _SCHEMA

        self._initial_stack_order = list(initial_stack_order)
        self._config_snapshot     = config_snapshot or {}

        # ── State for duration tracking ───────────────────────────────────────
        self._resource_last_state: dict[str, tuple[str, float]] = {}
        # command_id → sent_at (unix timestamp)
        self._command_sent_at: dict[str, float] = {}
        # command_id → command metadata (for auto robot_task / machine_job logging)
        self._pending_commands: dict[str, dict] = {}

        try:
            self._bootstrap()
            self._create_production_run()
            _log.info("[db] run_id=%s  schema=%s.%s", self.run_id, _CONN_DEFAULTS["dbname"], _SCHEMA)
        except Exception as exc:
            _log.error("[db] Startup failed — running without DB: %s", exc)

    # ── Bootstrap: create DB + schema + tables ────────────────────────────────

    def _bootstrap(self) -> None:
        import psycopg2

        # Connect directly to the configured database
        self._conn = psycopg2.connect(**_CONN_DEFAULTS)
        self._conn.autocommit = False

        # Create schema + all tables (idempotent).
        # _pre_migrate drops tables whose schema changed before DDL recreates them.
        with self._conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
            self._pre_migrate(cur)
            for stmt in _ddl(_SCHEMA):
                cur.execute(stmt)
        self._conn.commit()
        self._migrate()
        _log.info("[db] Schema %s.%s ready", _CONN_DEFAULTS["dbname"], _SCHEMA)

    def _pre_migrate(self, cur) -> None:
        """Drop tables whose schema changed before DDL recreates them.
        Called inside _bootstrap with an open cursor (no commit here)."""
        # cycle_event v1 had cycle_time_s and no entity column — drop it so
        # DDL recreates it with the entity-level schema.
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'cycle_event'
        """, (_SCHEMA,))
        cols = {row[0] for row in cur.fetchall()}
        if cols and "entity" not in cols:
            _log.info("[db] dropping legacy cycle_event for entity-level schema upgrade")
            cur.execute(f"DROP TABLE IF EXISTS {_SCHEMA}.cycle_event")

    def _migrate(self) -> None:
        """Column-level migrations that run after DDL."""
        with self._conn.cursor() as cur:
            # Upgrade piece and piece_outcome from single-column PK to composite (piece_id, run_id).
            for table in ("piece", "piece_outcome"):
                cur.execute("""
                    SELECT COUNT(*) FROM information_schema.key_column_usage kcu
                    JOIN information_schema.table_constraints tc
                      ON kcu.constraint_name = tc.constraint_name
                     AND kcu.constraint_schema = tc.constraint_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND kcu.table_schema = %s AND kcu.table_name = %s
                """, (_SCHEMA, table))
                row = cur.fetchone()
                if row and row[0] == 1:
                    cur.execute("""
                        SELECT tc.constraint_name FROM information_schema.table_constraints tc
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.constraint_schema = %s AND tc.table_name = %s
                    """, (_SCHEMA, table))
                    name_row = cur.fetchone()
                    if name_row:
                        _log.info("[db] migrating %s.%s → composite PK (piece_id, run_id)", _SCHEMA, table)
                        cur.execute(f'ALTER TABLE {_SCHEMA}.{table} DROP CONSTRAINT "{name_row[0]}"')
                        cur.execute(f"ALTER TABLE {_SCHEMA}.{table} ADD PRIMARY KEY (piece_id, run_id)")
        self._conn.commit()

    def _create_production_run(self) -> None:
        colors = [
            (e.get("color") if isinstance(e, dict) else e)
            for e in self._initial_stack_order
        ]
        sql = f"""
            INSERT INTO {_SCHEMA}.production_run
                (run_id, started_at, status, original_order, total_pieces, git_commit, config_snapshot)
            VALUES (%s, NOW(), 'RUNNING', %s, %s, %s, %s)
            ON CONFLICT (run_id) DO NOTHING
        """
        self._exec(sql, (
            self.run_id,
            json.dumps(colors),
            len(colors),
            _git_commit(),
            json.dumps(self._config_snapshot),
        ))

        # Insert one row per piece
        for i, entry in enumerate(self._initial_stack_order, start=1):
            pid   = entry.get("id")   if isinstance(entry, dict) else f"piece-{i:03d}"
            color = entry.get("color") if isinstance(entry, dict) else entry
            shape = entry.get("shape") if isinstance(entry, dict) else None
            self._exec(
                f"""INSERT INTO {_SCHEMA}.piece
                        (piece_id, run_id, color, shape, initial_position, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (piece_id, run_id) DO NOTHING""",
                (pid, self.run_id, color, shape, i),
            )

    # ── Internal DB helper ────────────────────────────────────────────────────

    def _exec(self, sql: str, params: tuple = ()) -> None:
        if self._conn is None:
            return
        try:
            with self._lock:
                with self._conn.cursor() as cur:
                    cur.execute(sql, params)
                self._conn.commit()
        except Exception as exc:
            _log.warning("[db] exec failed: %s | sql=%.120s", exc, sql.strip())
            try:
                self._conn.rollback()
            except Exception:
                pass

    def _fetchone(self, sql: str, params: tuple = ()) -> Optional[tuple]:
        if self._conn is None:
            return None
        try:
            with self._lock:
                with self._conn.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchone()
        except Exception as exc:
            _log.warning("[db] fetchone failed: %s", exc)
            try:
                self._conn.rollback()
            except Exception:
                pass
            return None

    # ── Backward-compatible methods ───────────────────────────────────────────

    def insert_piece_transfer(self, piece: dict, from_loc: str, to_loc: str) -> None:
        now = time.time()
        created = piece.get("timestamp_created") or now
        self._exec(
            f"""INSERT INTO {_SCHEMA}.piece_transfer
                    (run_id, piece_id, from_loc, to_loc, moved_by, ts, piece_age_s, history_json)
                VALUES (%s,%s,%s,%s,%s,NOW(),%s,%s)""",
            (
                self.run_id,
                piece.get("id"),
                from_loc,
                to_loc,
                None,  # moved_by filled in via insert_robot_task if available
                round(now - created, 2),
                json.dumps(piece.get("history", [])),
            ),
        )

    def insert_cycle_complete(self, record: Any) -> None:
        """Update piece_outcome and increment pieces_completed for a finished piece.
        Entity-level cycle details are written separately via insert_entity_cycle()."""
        import datetime as _dt
        finished = _dt.datetime.fromtimestamp(record.completed_at, tz=_dt.timezone.utc)
        self._exec(
            f"""INSERT INTO {_SCHEMA}.piece_outcome
                    (piece_id, run_id, route_taken, final_location, total_time_s, completed, completed_at)
                VALUES (%s,%s,%s,%s,%s,TRUE,%s)
                ON CONFLICT (piece_id, run_id) DO UPDATE
                    SET route_taken=EXCLUDED.route_taken,
                        final_location=EXCLUDED.final_location,
                        total_time_s=EXCLUDED.total_time_s,
                        completed=TRUE,
                        completed_at=EXCLUDED.completed_at""",
            (
                record.piece_id,
                self.run_id,
                record.route,
                getattr(record, "final_location", None),
                round(record.cycle_time_sec, 3),
                finished,
            ),
        )
        self._exec(
            f"UPDATE {_SCHEMA}.production_run SET pieces_completed=pieces_completed+1 WHERE run_id=%s",
            (self.run_id,),
        )

    def insert_entity_cycle(self, cycle: Any) -> None:
        """Insert one entity-level cycle (with phases) into cycle_event."""
        import datetime as _dt
        def _ts(t):
            return _dt.datetime.fromtimestamp(t, tz=_dt.timezone.utc) if t else None
        self._exec(
            f"""INSERT INTO {_SCHEMA}.cycle_event
                    (run_id, ts, entity, task_name, cycle_number, piece_id, color, route,
                     started_at, completed_at, total_duration_s,
                     is_discarded, discarded_reason, phases, metadata)
                VALUES (%s,NOW(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                self.run_id,
                cycle.entity,
                cycle.task_name,
                cycle.cycle_number,
                cycle.piece_id,
                cycle.color,
                cycle.route,
                _ts(cycle.started_at),
                _ts(cycle.completed_at),
                cycle.total_duration_s,
                cycle.is_discarded,
                cycle.discarded_reason,
                json.dumps(cycle.phases_as_list()),
                json.dumps(cycle.metadata),
            ),
        )

    # ── Piece ─────────────────────────────────────────────────────────────────

    def insert_piece(self, piece: dict, position: int) -> None:
        self._exec(
            f"""INSERT INTO {_SCHEMA}.piece
                    (piece_id, run_id, color, shape, initial_position, created_at)
                VALUES (%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (piece_id, run_id) DO NOTHING""",
            (piece.get("id"), self.run_id, piece.get("color"), piece.get("shape"), position),
        )

    def insert_piece_outcome(
        self,
        piece_id: str,
        route: str,
        final_location: str,
        completed: bool,
        completed_at=None,
        total_time_s: Optional[float] = None,
    ) -> None:
        import datetime as _dt
        ts = completed_at or _dt.datetime.now(_dt.timezone.utc)
        self._exec(
            f"""INSERT INTO {_SCHEMA}.piece_outcome
                    (piece_id, run_id, route_taken, final_location, total_time_s, completed, completed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (piece_id, run_id) DO UPDATE
                    SET route_taken=EXCLUDED.route_taken,
                        final_location=EXCLUDED.final_location,
                        total_time_s=EXCLUDED.total_time_s,
                        completed=EXCLUDED.completed,
                        completed_at=EXCLUDED.completed_at""",
            (piece_id, self.run_id, route, final_location, total_time_s, completed, ts),
        )

    # ── Robot tasks ───────────────────────────────────────────────────────────

    def insert_robot_task(
        self,
        command_id: str,
        robot_id: str,
        task_name: str,
        piece_id:    Optional[str]   = None,
        source:      Optional[str]   = None,
        target:      Optional[str]   = None,
        started_at:  Optional[float] = None,
        finished_at: Optional[float] = None,
        duration_s:  Optional[float] = None,
        result:      Optional[str]   = None,
        error_detail:Optional[str]   = None,
    ) -> None:
        import datetime as _dt
        def _ts(t): return _dt.datetime.fromtimestamp(t, tz=_dt.timezone.utc) if t else None
        dur = duration_s
        if dur is None and started_at and finished_at:
            dur = round(finished_at - started_at, 3)
        self._exec(
            f"""INSERT INTO {_SCHEMA}.robot_task
                    (run_id,command_id,robot_id,task_name,piece_id,source,target,
                     started_at,finished_at,duration_s,result,error_detail)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (self.run_id, command_id, robot_id, task_name, piece_id, source, target,
             _ts(started_at), _ts(finished_at), dur, result, error_detail),
        )

    # ── Machine jobs ──────────────────────────────────────────────────────────

    def insert_machine_job(
        self,
        command_id:   str,
        machine_id:   str,
        piece_id:     Optional[str]   = None,
        started_at:   Optional[float] = None,
        finished_at:  Optional[float] = None,
        duration_s:   Optional[float] = None,
        door_open_at: Optional[float] = None,
        door_close_at:Optional[float] = None,
        result:       Optional[str]   = None,
    ) -> None:
        import datetime as _dt
        def _ts(t): return _dt.datetime.fromtimestamp(t, tz=_dt.timezone.utc) if t else None
        dur = duration_s
        if dur is None and started_at and finished_at:
            dur = round(finished_at - started_at, 3)
        door_dur = None
        if door_open_at and door_close_at:
            door_dur = round(door_close_at - door_open_at, 3)
        self._exec(
            f"""INSERT INTO {_SCHEMA}.machine_job
                    (run_id,command_id,machine_id,piece_id,started_at,finished_at,
                     duration_s,door_open_at,door_close_at,door_duration_s,result)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (self.run_id, command_id, machine_id, piece_id,
             _ts(started_at), _ts(finished_at), dur,
             _ts(door_open_at), _ts(door_close_at), door_dur, result),
        )

    # ── Vision ────────────────────────────────────────────────────────────────

    def insert_vision_detection(
        self,
        vision_system:   str,
        piece_id:        Optional[str]   = None,
        detected_color:  Optional[str]   = None,
        detected_shape:  Optional[str]   = None,
        slot_id:         Optional[str]   = None,
        started_at:      Optional[float] = None,
        duration_s:      Optional[float] = None,
        success:         Optional[bool]  = None,
    ) -> None:
        import datetime as _dt
        ts = (_dt.datetime.fromtimestamp(started_at, tz=_dt.timezone.utc)
              if started_at else _dt.datetime.now(_dt.timezone.utc))
        self._exec(
            f"""INSERT INTO {_SCHEMA}.vision_detection
                    (run_id,vision_system,piece_id,detected_color,detected_shape,
                     slot_id,started_at,duration_s,success)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (self.run_id, vision_system, piece_id, detected_color, detected_shape,
             slot_id, ts, duration_s, success),
        )

    # ── Resource state ────────────────────────────────────────────────────────

    def insert_resource_state_change(
        self,
        resource_id:   str,
        resource_type: str,
        from_state:    Optional[str],
        to_state:      str,
        duration_in_prev_s: Optional[float] = None,
    ) -> None:
        # Auto-compute duration from last recorded state if not provided
        dur = duration_in_prev_s
        if dur is None:
            prev = self._resource_last_state.get(resource_id)
            if prev:
                dur = round(time.time() - prev[1], 3)
        self._resource_last_state[resource_id] = (to_state, time.time())
        self._exec(
            f"""INSERT INTO {_SCHEMA}.resource_state_change
                    (run_id,resource_id,resource_type,from_state,to_state,ts,duration_in_prev_s)
                VALUES (%s,%s,%s,%s,%s,NOW(),%s)""",
            (self.run_id, resource_id, resource_type, from_state, to_state, dur),
        )

    # ── Queue depth ───────────────────────────────────────────────────────────

    def insert_queue_depth_sample(self, samples: dict) -> None:
        """
        samples: {"initial_stack": 4, "conveyor1": 1, "laser_bed": 0, ...}
        Inserts one row per location.
        """
        for location, depth in samples.items():
            self._exec(
                f"""INSERT INTO {_SCHEMA}.queue_depth_sample
                        (run_id, sampled_at, location, depth)
                    VALUES (%s, NOW(), %s, %s)""",
                (self.run_id, location, depth),
            )

    # ── Topic messages ────────────────────────────────────────────────────────

    def insert_command(
        self,
        command_id:    str,
        domain_id:     str,
        resource_id:   str,
        task_name:     str,
        piece_id:      Optional[str]  = None,
        source:        Optional[str]  = None,
        target:        Optional[str]  = None,
        route:         Optional[str]  = None,
        parameters:    Optional[dict] = None,
        correlation_id:Optional[str]  = None,
    ) -> None:
        now = time.time()
        self._command_sent_at[command_id] = now
        self._pending_commands[command_id] = {
            "domain_id": domain_id, "resource_id": resource_id,
            "task_name": task_name, "piece_id": piece_id,
            "source": source, "target": target, "sent_at": now,
        }
        self._exec(
            f"""INSERT INTO {_SCHEMA}.command_log
                    (run_id,command_id,domain_id,resource_id,task_name,
                     piece_id,source,target,route,parameters,sent_at,correlation_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s)
                ON CONFLICT (command_id) DO NOTHING""",
            (self.run_id, command_id, domain_id, resource_id, task_name,
             piece_id, source, target, route,
             json.dumps(parameters or {}), correlation_id),
        )

    def insert_ack(
        self,
        command_id:    str,
        domain_id:     str,
        resource_id:   Optional[str] = None,
        task_state:    Optional[str] = None,
        resource_state:Optional[str] = None,
        result:        Optional[dict] = None,
        sent_at:       Optional[float] = None,
    ) -> None:
        # Compute latency from when the matching command was sent
        latency_ms = None
        ref = sent_at or self._command_sent_at.get(command_id)
        if ref:
            latency_ms = round((time.time() - ref) * 1000)
        self._exec(
            f"""INSERT INTO {_SCHEMA}.ack_log
                    (run_id,command_id,domain_id,resource_id,task_state,
                     resource_state,result,received_at,latency_ms)
                VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),%s)""",
            (self.run_id, command_id, domain_id, resource_id, task_state,
             resource_state, json.dumps(result or {}), latency_ms),
        )
        if task_state in ("COMPLETED", "FAILED", "TIMEOUT", "CANCELED", "REJECTED"):
            cmd = self._pending_commands.pop(command_id, None)
            if cmd:
                self._auto_log_task(command_id, cmd, task_state, time.time())

    _MACHINE_RESOURCES = frozenset({"laser", "bantam"})

    def _auto_log_task(self, command_id: str, cmd: dict, result: str, finished_at: float) -> None:
        rid = cmd.get("resource_id", "")
        if rid in self._MACHINE_RESOURCES:
            self.insert_machine_job(
                command_id=command_id,
                machine_id=rid,
                piece_id=cmd.get("piece_id"),
                started_at=cmd["sent_at"],
                finished_at=finished_at,
                result=result,
            )
        else:
            self.insert_robot_task(
                command_id=command_id,
                robot_id=rid,
                task_name=cmd.get("task_name", ""),
                piece_id=cmd.get("piece_id"),
                source=cmd.get("source"),
                target=cmd.get("target"),
                started_at=cmd["sent_at"],
                finished_at=finished_at,
                result=result,
            )

    def insert_status(
        self,
        domain_id:     str,
        resource_id:   Optional[str] = None,
        topic:         Optional[str] = None,
        resource_state:Optional[str] = None,
        task_state:    Optional[str] = None,
        code:          Optional[str] = None,
        result:        Optional[dict] = None,
        command_id:    Optional[str] = None,
    ) -> None:
        self._exec(
            f"""INSERT INTO {_SCHEMA}.status_log
                    (run_id,domain_id,resource_id,topic,resource_state,
                     task_state,code,result,command_id,published_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())""",
            (self.run_id, domain_id, resource_id, topic, resource_state,
             task_state, code, json.dumps(result or {}), command_id),
        )

    # ── Optimizer ─────────────────────────────────────────────────────────────

    def insert_optimizer_result(
        self,
        original_order:         list,
        best_order:             list,
        original_time_s:        float,
        best_time_s:            float,
        saving_s:               float,
        saving_pct:             float,
        method:                 str,
        permutations_evaluated: int,
        optimizer_runtime_s:    float,
    ) -> Optional[int]:
        row = self._fetchone(
            f"""INSERT INTO {_SCHEMA}.optimizer_run
                    (run_id,original_order,best_order,original_time_s,best_time_s,
                     saving_s,saving_pct,method,permutations_evaluated,
                     optimizer_runtime_s,applied,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE,NOW())
                RETURNING id""",
            (self.run_id, json.dumps(original_order), json.dumps(best_order),
             original_time_s, best_time_s, saving_s, saving_pct, method,
             permutations_evaluated, optimizer_runtime_s),
        )
        return row[0] if row else None

    def update_optimizer_applied(self, optimizer_id: int) -> None:
        self._exec(
            f"UPDATE {_SCHEMA}.optimizer_run SET applied=TRUE, applied_at=NOW() WHERE id=%s",
            (optimizer_id,),
        )

    def update_production_run_optimized_order(self, optimized_order: list, saving_s: float) -> None:
        self._exec(
            f"""UPDATE {_SCHEMA}.production_run
                SET optimized_order=%s, optimizer_savings_s=%s WHERE run_id=%s""",
            (json.dumps(optimized_order), saving_s, self.run_id),
        )

    # ── Operator events ───────────────────────────────────────────────────────

    def insert_operator_event(self, event_type: str, description: str = "") -> None:
        self._exec(
            f"""INSERT INTO {_SCHEMA}.operator_event (run_id, event_type, description, ts)
                VALUES (%s,%s,%s,NOW())""",
            (self.run_id, event_type, description),
        )

    # ── Alarms ───────────────────────────────────────────────────────────────

    def insert_alarm(
        self,
        severity:         str,
        resource_id:      Optional[str],
        description:      str,
        context_snapshot: Optional[dict] = None,
    ) -> Optional[int]:
        row = self._fetchone(
            f"""INSERT INTO {_SCHEMA}.alarm_event
                    (run_id, severity, resource_id, description, context_snapshot, triggered_at)
                VALUES (%s,%s,%s,%s,%s,NOW()) RETURNING id""",
            (self.run_id, severity, resource_id, description,
             json.dumps(context_snapshot or {})),
        )
        return row[0] if row else None

    def resolve_alarm(self, alarm_id: int) -> None:
        self._exec(
            f"UPDATE {_SCHEMA}.alarm_event SET resolved_at=NOW() WHERE id=%s",
            (alarm_id,),
        )

    # ── Production run lifecycle ──────────────────────────────────────────────

    def update_production_run_finished(self, status: str = "COMPLETED") -> None:
        self._exec(
            f"UPDATE {_SCHEMA}.production_run SET finished_at=NOW(), status=%s WHERE run_id=%s",
            (status, self.run_id),
        )

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            try:
                self._conn.close()
            except Exception:
                pass
