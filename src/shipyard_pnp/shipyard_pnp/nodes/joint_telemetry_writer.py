#!/usr/bin/env python3
"""
Joint telemetry writer.

Merges two read-only ROS2 sources per robot and writes the result into
mes_pnp_v2.{robot}_joint_telemetry, the tables MES_dashboard.py reads for the
live robot viewer and history pages:

  - sensor_msgs/JointState on the robot's real /joint_states topic
    (position / velocity / effort)
  - the factory status topic for that robot's vendor
    (/ufactory_factory/status for xarm1/xarm2, /niryo_factory/status for
    robot1/robot2), whose "resource_state" field becomes robot_status —
    the same fine-grained task-state strings (e.g. "PICKING_C3",
    "APPROACHING_BANTAM") used throughout the factory state machine.

Never publishes to any P&P or digital-twin topic — read-only bridge to the DB.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone

import psycopg2
import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

DB_HOST     = os.environ.get("PGHOST",     "100.115.213.16")
DB_PORT     = int(os.environ.get("PGPORT", "5432"))
DB_USER     = os.environ.get("PGUSER",     "twin_mes_db")
DB_PASSWORD = os.environ.get("PGPASSWORD", "postgres")
DB_NAME     = os.environ.get("PGDATABASE", "twin_mes_db")
DB_SCHEMA   = os.environ.get("MES_PGSCHEMA", os.environ.get("PGSCHEMA", "mes_pnp_v2"))

WRITE_HZ = float(os.environ.get("MES_JOINT_WRITE_HZ", "10"))

ROBOT_JOINT_TOPICS = {
    "robot1": "/robot1/joint_states",
    "robot2": "/robot2/joint_states",
    "xarm1":  "/xarm1/joint_states",
    "xarm2":  "/xarm2/joint_states",
}

# resource_id values on each status topic that map 1:1 onto our robot keys.
STATUS_TOPIC_ROBOTS = {
    "/ufactory_factory/status": {"xarm1", "xarm2"},
    "/niryo_factory/status":    {"robot1", "robot2"},
}


def qident(value: str) -> str:
    if not IDENT_RE.match(value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return value


def qname(schema: str, table: str) -> str:
    return f"{qident(schema)}.{qident(table)}"


def _pad6(values) -> list:
    values = list(values)[:6]
    values += [None] * (6 - len(values))
    return values


def _parse(msg: String):
    try:
        return json.loads(msg.data)
    except Exception:
        return None


def _stamp_to_dt(stamp) -> datetime:
    if stamp.sec == 0 and stamp.nanosec == 0:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(stamp.sec + stamp.nanosec * 1e-9, tz=timezone.utc)


class JointTelemetryWriter(Node):
    def __init__(self):
        super().__init__("joint_telemetry_writer")
        self._lock = threading.Lock()
        self._conn = None
        self._latest: dict[str, tuple[str, JointState]] = {}
        self._status: dict[str, str] = {r: "UNKNOWN" for r in ROBOT_JOINT_TOPICS}

        self._connect()
        self._ensure_tables()

        for robot, topic in ROBOT_JOINT_TOPICS.items():
            self.create_subscription(
                JointState, topic,
                lambda msg, r=robot, t=topic: self._on_joint_state(r, t, msg),
                10,
            )
        for topic, robots in STATUS_TOPIC_ROBOTS.items():
            self.create_subscription(
                String, topic,
                lambda msg, allowed=robots: self._on_status(allowed, msg),
                10,
            )

        self.create_timer(1.0 / WRITE_HZ, self._flush)
        self.get_logger().info(
            f"joint_telemetry_writer ready — writing {list(ROBOT_JOINT_TOPICS)} "
            f"into {DB_SCHEMA} @ {WRITE_HZ} Hz"
        )

    # ── DB setup ─────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        try:
            self._conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=DB_USER, password=DB_PASSWORD, connect_timeout=5,
            )
            self._conn.autocommit = True
        except Exception as e:
            self.get_logger().error(f"DB connect failed: {e}")
            self._conn = None

    def _reconnect_if_needed(self) -> None:
        try:
            if self._conn is None or self._conn.closed:
                self._connect()
            else:
                with self._conn.cursor() as c:
                    c.execute("SELECT 1")
        except Exception:
            self._connect()

    def _ensure_tables(self) -> None:
        if not self._conn:
            return
        joint_cols = ",\n".join(
            f"joint{j}_{kind} DOUBLE PRECISION"
            for j in range(1, 7) for kind in ("position", "velocity", "effort")
        )
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {qident(DB_SCHEMA)}")
                for robot in ROBOT_JOINT_TOPICS:
                    table = qname(DB_SCHEMA, f"{robot}_joint_telemetry")
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {table} (
                            id BIGSERIAL PRIMARY KEY,
                            ts TIMESTAMPTZ NOT NULL,
                            robot_name TEXT NOT NULL,
                            robot_status TEXT NOT NULL,
                            {joint_cols},
                            source_topic TEXT NOT NULL,
                            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute(f"""
                        CREATE INDEX IF NOT EXISTS idx_{robot}_joint_telemetry_ts
                            ON {table} (ts DESC)
                    """)
        except Exception as e:
            self.get_logger().error(f"ensure_tables failed: {e}")

    # ── ROS callbacks ────────────────────────────────────────────────────────

    def _on_joint_state(self, robot: str, topic: str, msg: JointState) -> None:
        with self._lock:
            self._latest[robot] = (topic, msg)

    def _on_status(self, allowed_robots: set, msg: String) -> None:
        data = _parse(msg)
        if data is None:
            return
        rid = data.get("resource_id", "")
        state = data.get("resource_state", "")
        if rid in allowed_robots and state:
            with self._lock:
                self._status[rid] = state

    # ── periodic DB flush ────────────────────────────────────────────────────

    def _flush(self) -> None:
        with self._lock:
            pending = self._latest
            self._latest = {}
            status_snapshot = dict(self._status)
        if not pending:
            return

        self._reconnect_if_needed()
        if not self._conn:
            return

        for robot, (topic, msg) in pending.items():
            positions  = _pad6(msg.position)
            velocities = _pad6(msg.velocity)
            efforts    = _pad6(msg.effort)

            cols = ["ts", "robot_name", "robot_status", "source_topic"]
            vals: list = [
                _stamp_to_dt(msg.header.stamp), robot,
                status_snapshot.get(robot, "UNKNOWN"), topic,
            ]
            for j in range(1, 7):
                cols += [f"joint{j}_position", f"joint{j}_velocity", f"joint{j}_effort"]
                vals += [positions[j - 1], velocities[j - 1], efforts[j - 1]]

            table = qname(DB_SCHEMA, f"{robot}_joint_telemetry")
            placeholders = ", ".join(["%s"] * len(vals))
            try:
                with self._conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                        vals,
                    )
            except Exception as e:
                self.get_logger().warn(f"insert failed for {robot}: {e}")


def main(args=None):
    rclpy.init(args=args)
    node = JointTelemetryWriter()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.remove_node(node)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
