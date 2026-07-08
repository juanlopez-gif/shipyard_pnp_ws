#!/usr/bin/env python3
"""
ml_node.py

Nodo ROS2 que combina inferencia YOLO + logica de bloqueo por estado de robot
+ escritura a PostgreSQL + display visual (mosaico igual que multi_camera_inference).

Version STANDALONE SCRIPT -- corre suelto (python3 ml_node.py) en un
ordenador sin el workspace de shipyard_pnp. Necesita, en el MISMO
directorio que este archivo:
  - conveyor_detector.py (tu modulo de deteccion de movimiento de cinta)
  - best.pt, rois.json, conveyor_model_c1/, conveyor_model_c2/
    (o define las variables de entorno ML_MODEL_PATH, ML_ROIS_PATH,
    ML_CONVEYOR1_MODEL, ML_CONVEYOR2_MODEL apuntando donde esten)

Requiere: ROS2 sourceado (rclpy), y estar en el MISMO ROS_DOMAIN_ID /
red DDS que el ordenador que corre factory_supervisor.py -- este nodo
solo hace de "ojos" (vision + verificacion), toda la logica de control
vive en el otro ordenador y se entera de este nodo solo via topics
(/factory/run_id, /factory/system_state que RECIBE; /stack_status y
/factory/conveyor_1|2/status que tambien lee) y via la base de datos
compartida (mismas credenciales que factory/db_writer.py del otro repo).

Grupos de captura (ROIs -> tabla):
 Grupo 1 -- Stack s1.1-s3.6 (cam 6) -> vision_slot_snapshot
 Trigger: xarm2 sin ciclo activo, flanco de subida (snapshot puntual)

 Grupo 2 -- conveyor1 (cam 6) -> vision_conveyor_snapshot
 Bloqueado mientras xarm1 tiene un ciclo activo C1S2_TO_C2S1 / C1S2_TO_LASER

 Grupo 3 -- conveyor2 (cam 4) -> vision_conveyor_snapshot
 Bloqueado mientras robot2 tiene un ciclo activo CLASSIFY_C2S2*

 Grupo 4 -- conveyor3 / C3 (cam 0) -> vision_conveyor_snapshot
 Bloqueado mientras robot1 tiene un ciclo activo UNLOAD_C3

 Grupo 5 -- conveyor4 / C4 (cam 0) -> vision_conveyor_snapshot
 Bloqueado mientras robot1 tiene un ciclo activo UNLOAD_C4

 Grupo 6 -- IBS -> vision_conveyor_snapshot
 Bloqueado mientras robot2 tiene un ciclo activo CLASSIFY_C2S2_TO_IBS / IBS_TO_BANTAM
"""

import json
import os
import time
import threading
import cv2
import numpy as np
import psycopg2
from psycopg2 import sql
from pathlib import Path
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from std_msgs.msg import String

try:
    from ultralytics import YOLO
except ImportError:
    print("ERROR: venv/bin/pip install ultralytics")
    raise SystemExit(1)

# Script suelto: conveyor_detector.py debe estar en el MISMO directorio
# que este archivo (import simple, sin paquete).
from conveyor_detector import ConveyorDetector

# ── DB ─────────────────────────────────────────────────────────────
# Mismas credenciales/host que factory/db_writer.py del repo shipyard_pnp
# -- este nodo escribe en el MISMO esquema que el resto del sistema.
DB_HOST = os.environ.get("PGHOST", "100.115.213.16")
DB_USER = os.environ.get("PGUSER", "twin_mes_db")
DB_PASSWORD = os.environ.get("PGPASSWORD", "postgres")
DB_PORT = int(os.environ.get("PGPORT", "5432"))
DB_NAME = os.environ.get("PGDATABASE", "twin_mes_db")
DB_SCHEMA = os.environ.get("PGSCHEMA", "shipyard_pnp_ws")

# ── Config ─────────────────────────────────────────────────────────
# Todos overrideables por variable de entorno -- este nodo corre en OTRO
# ordenador que el resto del sistema, asi que las rutas de los modelos
# (pesos YOLO, ROIs, modelos de movimiento de cinta) casi seguro no viven en
# el mismo sitio que en el arbol de desarrollo. Los defaults asumen que los
# colocas junto a este archivo.
BASE_DIR = Path(__file__).parent
MODEL_PATH = Path(os.environ.get("ML_MODEL_PATH", str(BASE_DIR / "best.pt")))
ROIS_PATH = Path(os.environ.get("ML_ROIS_PATH", str(BASE_DIR / "rois.json")))
CAMERA_INDICES = [2, 0, 4, 6]
CONF_THRESHOLD = 0.45
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

SLOT_TABLE = "vision_slot_snapshot"
CONVEYOR_TABLE = "vision_conveyor_snapshot"
SLOT_COLS = [f"s{c}_{r}" for c in range(1, 4) for r in range(1, 7)]
CONVEYOR_COLS = ["conveyor1", "conveyor2", "conveyor3", "conveyor4", "ibs"]

# Claves de vision_conveyor_snapshot -> claves reales de PieceTracker
# (factory/piece_tracker.py PIPELINE_LOCATIONS del repo shipyard_pnp) para
# leer "que pieza se espera aqui" desde /factory/system_state.
LOCATION_KEY_MAP = {
    "conveyor1": "conveyor1",
    "conveyor2": "conveyor2",
    "conveyor3": "c3_location",
    "conveyor4": "c4_location",
    "ibs": "intermediate_blue_stack",
}
# Etiquetas cortas para el panel visual (LOCATION_KEY_MAP tiene la clave real
# de PieceTracker, que para IBS es demasiado larga para el panel de 420px).
DISPLAY_LABELS = {**LOCATION_KEY_MAP, "ibs": "ibs"}

# Task names (cycle_tracker, repo shipyard_pnp) que indican que cada robot
# esta fisicamente ocupando/obstruyendo la zona correspondiente -- ver
# factory/planner/*.py (unloading_rules.py, processing_rules.py,
# classification_rules.py) para los nombres de tarea reales. Se usan como
# techo de seguridad (nunca desbloquea si el robot no tiene la tarea activa);
# el desbloqueo TEMPRANO en si sale de EXPECTED, ver mas abajo.
XARM1_C1S2_TASKS = {"C1S2_TO_C2S1", "C1S2_TO_LASER"}
ROBOT1_C3_TASK = "UNLOAD_C3"
ROBOT1_C4_TASK = "UNLOAD_C4"
ROBOT2_IBS_TASKS = {"CLASSIFY_C2S2_TO_IBS", "IBS_TO_BANTAM"}

# Cada zona de conveyor la tocan DOS entidades distintas -- una la coloca,
# otra la recoge despues -- pero el bloqueo de arriba solo vigilaba a la que
# RECOGE. Descubierto el 2026-07-07: la que COLOCA (xarm1/xarm2 en estos
# casos) nunca bloqueaba la camara durante su propio deposito, asi que
# REALITY podia leerse mal justo en el instante del PLACE. Añadido aqui el
# lado que faltaba de cada zona:
#   conveyor1:    coloca xarm2 (FEED_TO_C1S1)              | recoge xarm1 (XARM1_C1S2_TASKS)
#   conveyor2:    coloca xarm1 (XARM1_C2S1_PLACE_TASKS)     | recoge robot2 (CLASSIFY_C2S2*/IBS)
#   c3_location:  coloca xarm2 (FEED_GREEN_TO_C3)           | recoge robot1 (ROBOT1_C3_TASK)
#   c4_location:  coloca robot2 (ROBOT2_C4_PLACE_TASKS)     | recoge robot1 (ROBOT1_C4_TASK)
# IBS no necesitaba esto: coloca Y recoge robot2 (ROBOT2_IBS_TASKS ya cubre
# ambos extremos).
XARM2_C1S1_TASK = "FEED_TO_C1S1"
XARM2_C3_TASK = "FEED_GREEN_TO_C3"
XARM1_C2S1_PLACE_TASKS = {"C1S2_TO_C2S1", "LASER_TO_C2S1"}
ROBOT2_C4_PLACE_TASKS = {"CLASSIFY_C2S2_TO_C4", "BANTAM_TO_C4"}

# Se probo primero desbloquear por resource_state del robot (PICKING/
# PICK_DONE/PLACING/... via resources.robots en /factory/system_state) --
# DESCARTADO tras revisar shipyard_pnp_ws.resource_state_change en la DB:
# PICK_DONE dura de verdad ~10 ms en el robot real (confirmado con datos
# reales, p.ej. robot2 AT_PICK_POSITION->PICK_DONE->GOING_TO_POSITION en
# 2026-07-07: PICK_DONE duro 0.009s) frente a un muestreo de
# /factory/system_state cada 2s -- la probabilidad de que un muestreo caiga
# justo en esos 10ms es casi nula, asi que el desbloqueo en la practica
# apenas mejoraba nada (seguia esperando esencialmente a PLACING/home).
#
# Arreglado desbloqueando por EXPECTED en vez de por resource_state: en
# cuanto `pipeline.queues` (via factory_supervisor.py, que ya transfiere la
# pieza a una cola "*_gripper" invisible justo en el PICK_DONE real -- ver
# CLAUDE.md del repo shipyard_pnp, seccion sobre register_pick_source) dice
# que el sitio ya esta vacio, se da por bueno el desbloqueo -- a diferencia
# de PICK_DONE, ese "vacio" es un estado que PERSISTE (no un blip de
# milisegundos), asi que cualquier muestreo de los 2s siguientes lo pilla
# sin falta. Ver _on_system_state / _group_prev_count / _group_unblocked_latch.

# Display
WINDOW_COLS = 2
ALL_CAM_ORDER = [0, 6, 2, 4]
CAM_COLORS = {2: (0, 255, 0), 0: (255, 128, 0), 4: (0, 128, 255), 6: (128, 0, 255)}
ROI_ALPHA = 0.20

# Colores BGR para la rejilla "INITIAL STACK" del panel -- misma paleta que
# camera_adapter.py del repo shipyard_pnp (RED/GREEN/BLUE).
STACK_SLOT_COLOR_BGR = {"RED": (0, 0, 200), "GREEN": (0, 160, 0), "BLUE": (200, 90, 0)}

# Supervisor verification -- "lo esperado" en cada sitio se lee de
# /factory/system_state (pipeline.queues, ver LOCATION_KEY_MAP arriba).
PANEL_WIDTH = 420
VERIFY_TIMEOUT = 2.0
VERIFY_TIMEOUT_OVERRIDE = {"conveyor1": 3.0, "conveyor3": 4.0, "conveyor4": 4.0, "ibs": 8.0}
ALARM_DEBOUNCE = {"conveyor4": 5.5}

# Conveyor motion ML
CONVEYOR_MOTION_TOPICS = {
    "conveyor1": "/factory/conveyor_1/status",
    "conveyor2": "/factory/conveyor_2/status",
}
CONVEYOR_ML_MODELS = {
    "conveyor1": Path(os.environ.get("ML_CONVEYOR1_MODEL", str(BASE_DIR / "conveyor_model_c1"))),
    "conveyor2": Path(os.environ.get("ML_CONVEYOR2_MODEL", str(BASE_DIR / "conveyor_model_c2"))),
}
CONVEYOR_ML_CAMS = {
    "conveyor1": 6,
    "conveyor2": 4,
}
CONVEYOR_MOTION_DEBOUNCE = 2.0  # s de mismatch continuo antes de alarmar
# ───────────────────────────────────────────────────────────────────


def utc_now():
    return datetime.now(timezone.utc)


def load_rois(path):
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {
        int(k): [{**r, "name": r["name"].replace(".", "_")} for r in v]
        for k, v in raw.items()
    }


def point_in_polygon(pts, x, y):
    return cv2.pointPolygonTest(
        np.array(pts, dtype=np.float32), (float(x), float(y)), False
    ) >= 0


# ── DB ────────────────────────────────────────────────────────────
def get_conn():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD, connect_timeout=5,
    )
    conn.autocommit = True
    return conn


def ensure_tables(conn):
    for table_name, cols in [(SLOT_TABLE, SLOT_COLS), (CONVEYOR_TABLE, CONVEYOR_COLS)]:
        col_defs = sql.SQL(", ").join(
            sql.SQL("{} TEXT").format(sql.Identifier(c)) for c in cols
        )
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {} ("
                    "id BIGSERIAL PRIMARY KEY, "
                    "run_id TEXT NOT NULL, "
                    "ts TIMESTAMPTZ NOT NULL, "
                    "{}"
                    ");"
                ).format(sql.Identifier(DB_SCHEMA, table_name), col_defs)
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (ts DESC);").format(
                    sql.Identifier(f"{table_name}_ts_idx"),
                    sql.Identifier(DB_SCHEMA, table_name),
                )
            )


def insert_row(conn, table_name, cols, run_id, state):
    col_sql = sql.SQL(", ").join(
        [sql.Identifier("run_id"), sql.Identifier("ts")]
        + [sql.Identifier(c) for c in cols]
    )
    ph_sql = sql.SQL(", ").join([sql.Placeholder()] * (2 + len(cols)))
    values = [run_id, utc_now()] + [state.get(c) for c in cols]
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("INSERT INTO {} ({}) VALUES ({});").format(
                sql.Identifier(DB_SCHEMA, table_name), col_sql, ph_sql
            ),
            values,
        )


# ── Visual ────────────────────────────────────────────────────────
def draw_rois(frame, cam_rois, cam_idx, blocked_rois: set):
    color = CAM_COLORS.get(cam_idx, (0, 255, 0))
    overlay = frame.copy()
    for roi in cam_rois:
        pts = np.array(roi["pts"], dtype=np.int32)
        name = roi.get("name", "")
        is_nb = roi.get("no_block", False)
        blocked = (name in blocked_rois) and not is_nb
        if is_nb:
            fill = (0, 200, 200)
        elif blocked:
            fill = (0, 0, 180)
        else:
            fill = color
        cv2.fillPoly(overlay, [pts], fill)
        cv2.polylines(frame, [pts], isClosed=True, color=fill, thickness=2)
        cx = int(pts[:, 0].mean())
        cy = int(pts[:, 1].mean())
        if is_nb:
            label = f"[NB] {name}"
        elif blocked:
            label = f"{name} [BLOQ]"
        else:
            label = name
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        cv2.rectangle(frame, (cx - 3, cy - th - 3), (cx + tw + 3, cy + 3), (0, 0, 0), -1)
        cv2.putText(frame, label, (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    cv2.addWeighted(overlay, ROI_ALPHA, frame, 1 - ROI_ALPHA, 0, frame)


def draw_detections(frame, boxes, names, cam_rois, blocked_rois: set):
    for box in boxes:
        conf = float(box.conf[0])
        if conf < 0.3:
            continue
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        cls_name = names[int(box.cls[0])]
        for roi in cam_rois:
            if not point_in_polygon(roi["pts"], cx, cy):
                continue
            if roi["name"] in blocked_rois:
                color = (100, 100, 100)  # gris -> bloqueado
            elif conf >= CONF_THRESHOLD:
                color = (0, 255, 0)  # verde -> guardado
            else:
                color = (0, 140, 255)  # naranja -> conf insuficiente
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
            cv2.putText(frame, f"{cls_name} {conf:.2f}", (int(x1), int(y1) - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)


def draw_hud(frame, cam_idx, run_id, status_lines: list):
    color = CAM_COLORS.get(cam_idx, (0, 255, 0))
    cv2.putText(frame, f"Cam {cam_idx} {run_id}", (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    for i, line in enumerate(status_lines):
        cv2.putText(frame, line, (8, 44 + i * 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)


def draw_last_update_legend(mosaic, last_update: dict):
    """Leyenda arriba a la derecha con el ultimo timestamp de cada grupo ROI."""
    _, w = mosaic.shape[:2]
    line_h = 22
    padding = 8
    n_lines = len(last_update)
    box_w = 260
    box_h = n_lines * line_h + padding * 2
    x0 = w - box_w - 10
    y0 = 10

    overlay = mosaic.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + box_w, y0 + box_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.75, mosaic, 0.25, 0, mosaic)
    cv2.rectangle(mosaic, (x0, y0), (x0 + box_w, y0 + box_h), (180, 180, 180), 1)

    for i, (group, ts) in enumerate(last_update.items()):
        ts_str = ts if ts else "-"
        color = (0, 255, 180) if ts else (120, 120, 120)
        text = f"{group}: {ts_str}"
        cy = y0 + padding + (i + 1) * line_h - 4
        cv2.putText(mosaic, text, (x0 + 6, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)


def check_piece_match(supervisor_list, detected_classes):
    """True si lo que ve YOLO concuerda con lo que publica el supervisor.
    supervisor_list: [] | [{color, shape}, ...]
    detected_classes: lista de nombres de clase YOLO
    """
    if not isinstance(supervisor_list, list):
        supervisor_list = []
    if len(supervisor_list) != len(detected_classes):
        return False
    if not supervisor_list:
        return True
    for piece in supervisor_list:
        sup_color = piece.get("color") if isinstance(piece, dict) else None
        sup_shape = piece.get("shape") if isinstance(piece, dict) else None
        matched = any(
            (sup_color is None or sup_color.upper() in cls.upper()) and
            (sup_shape is None or sup_shape.upper() in cls.upper())
            for cls in detected_classes
        )
        if not matched:
            return False
    return True


def build_supervisor_panel(supervisor_data: dict, verify_state: dict,
                            reality: dict, height: int,
                            motion_expected: dict = None,
                            motion_detected: dict = None,
                            motion_mismatch: dict = None,
                            stack_slots: dict = None):
    panel = np.zeros((height, PANEL_WIDTH, 3), dtype=np.uint8)
    x0, y = 8, 12
    col_r = PANEL_WIDTH // 2 + 4  # columna derecha (REALITY)
    font = cv2.FONT_HERSHEY_SIMPLEX

    cv2.putText(panel, "SUPERVISOR", (x0, y + 16), font, 0.6, (200, 200, 200), 2)
    y += 34
    cv2.line(panel, (x0, y), (PANEL_WIDTH - x0, y), (80, 80, 80), 1)
    y += 10

    # cabeceras columnas
    cv2.putText(panel, "EXPECTED", (x0, y + 12), font, 0.38, (140, 140, 140), 1)
    cv2.putText(panel, "REALITY", (col_r, y + 12), font, 0.38, (140, 140, 140), 1)
    y += 18
    cv2.line(panel, (x0, y), (PANEL_WIDTH - x0, y), (50, 50, 50), 1)
    y += 8

    for key, label in DISPLAY_LABELS.items():
        sup = supervisor_data.get(key)
        real = reality.get(key, [])
        mismatch = verify_state.get(key, {}).get("mismatch", False)

        # fila label
        lbl_color = (60, 60, 220) if mismatch else (80, 200, 80)
        cv2.putText(panel, label, (x0, y + 13), font, 0.45, lbl_color, 1)
        if mismatch:
            cv2.putText(panel, "*", (PANEL_WIDTH - 22, y + 14),
                        font, 0.9, (0, 0, 220), 2)
        y += 18

        # fila valores
        if not isinstance(sup, list):
            sup = []
        if not sup:
            exp_lines = ["null"]
            exp_color = (90, 90, 90)
        else:
            exp_lines = [
                f"{p.get('color','?')} {p.get('shape','?')}"
                for p in sup if isinstance(p, dict)
            ] or ["null"]
            exp_color = (0, 210, 210)

        if not real:
            real_lines = ["null"]
            real_color = (90, 90, 90)
        else:
            real_lines = real
            real_color = (0, 210, 100)

        n_lines = max(len(exp_lines), len(real_lines))
        for i in range(n_lines):
            ey = y + i * 14 + 12
            if i < len(exp_lines):
                cv2.putText(panel, exp_lines[i], (x0, ey), font, 0.38, exp_color, 1)
            if i < len(real_lines):
                cv2.putText(panel, real_lines[i], (col_r, ey), font, 0.38, real_color, 1)
        y += n_lines * 14 + 4

        cv2.line(panel, (x0, y), (PANEL_WIDTH - x0, y), (40, 40, 40), 1)
        y += 8

    # ── Seccion conveyor motion ML ─────────────────────────────
    if motion_expected and motion_detected:
        y += 6
        cv2.line(panel, (x0, y), (PANEL_WIDTH - x0, y), (80, 80, 80), 1)
        y += 8
        cv2.putText(panel, "CONVEYOR MOTION", (x0, y + 13), font, 0.5, (200, 200, 200), 1)
        y += 20
        cv2.putText(panel, "EXPECTED", (x0, y + 12), font, 0.38, (140, 140, 140), 1)
        cv2.putText(panel, "ML", (col_r, y + 12), font, 0.38, (140, 140, 140), 1)
        y += 18
        cv2.line(panel, (x0, y), (PANEL_WIDTH - x0, y), (50, 50, 50), 1)
        y += 8
        for mkey in ("conveyor1", "conveyor2"):
            exp = (motion_expected or {}).get(mkey)
            det = (motion_detected or {}).get(mkey)
            mm = (motion_mismatch or {}).get(mkey, False)
            lbl_color = (60, 60, 220) if mm else (80, 200, 80)
            cv2.putText(panel, mkey, (x0, y + 13), font, 0.45, lbl_color, 1)
            if mm:
                cv2.putText(panel, "*", (PANEL_WIDTH - 22, y + 14), font, 0.9, (0, 0, 220), 2)
            y += 18
            exp_str = exp if exp else "-"
            det_str = ("RUNNING" if det.moving else "STOPPED") if det else "-"
            exp_col = (0, 210, 210) if exp else (90, 90, 90)
            det_col = (0, 220, 80) if (det and det.moving) else (60, 60, 200) if det else (90, 90, 90)
            cv2.putText(panel, exp_str, (x0, y + 12), font, 0.38, exp_col, 1)
            cv2.putText(panel, det_str, (col_r, y + 12), font, 0.38, det_col, 1)
            if det:
                cv2.putText(panel, f"{det.confidence:.2f}", (col_r, y + 24), font, 0.33, (120, 120, 120), 1)
            y += 28
        cv2.line(panel, (x0, y), (PANEL_WIDTH - x0, y), (40, 40, 40), 1)
        y += 8

    # ── Seccion INITIAL STACK (vision propia, no viene del supervisor) ──
    if stack_slots is not None:
        y += 6
        cv2.line(panel, (x0, y), (PANEL_WIDTH - x0, y), (80, 80, 80), 1)
        y += 8
        y = draw_stack_grid(panel, x0, y, stack_slots)

    return panel


def draw_mismatch_stars(frame, cam_rois, verify_state: dict):
    for roi in cam_rois:
        if roi.get("no_block"):
            continue
        rname = roi["name"]
        if not verify_state.get(rname, {}).get("mismatch"):
            continue
        pts = np.array(roi["pts"], dtype=np.int32)
        cx = int(pts[:, 0].mean())
        cy = int(pts[:, 1].mean())
        cv2.circle(frame, (cx, cy), 22, (0, 0, 220), -1)
        cv2.putText(frame, "!", (cx - 7, cy + 9),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 3)


def draw_stack_grid(panel, x0: int, y: int, slots: dict) -> int:
    """Rejilla 3x6 (s1_1..s3_6) con la deteccion YOLO EN VIVO de cada slot
    del stack inicial -- el mismo dict `slots` que se publica como
    stack_status. No hay un "expected" util a nivel de slot fisico
    individual (shipyard_pnp solo conoce el orden de colores a alimentar,
    no que color va en que slot exacto, salvo el que esta siendo recogido
    ahora mismo) -- esto es la visualizacion que faltaba, pedida
    explicitamente: una foto en vivo del stack completo, no una
    comparacion columna a columna como el resto del panel. Devuelve la
    nueva coordenada y tras dibujar."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    cell_w, cell_h, gap = 124, 26, 4

    cv2.putText(panel, "INITIAL STACK (YOLO en vivo)", (x0, y + 13), font, 0.5, (200, 200, 200), 1)
    y += 20
    cv2.line(panel, (x0, y), (x0 + 3 * cell_w + 2 * gap, y), (80, 80, 80), 1)
    y += 8

    for row in range(1, 7):
        for col in range(1, 4):
            key = f"s{col}_{row}"
            cls_name = slots.get(key)
            cx = x0 + (col - 1) * (cell_w + gap)
            cy = y + (row - 1) * (cell_h + gap)
            if cls_name:
                color_name = cls_name.split("_")[0].upper()
                bg = STACK_SLOT_COLOR_BGR.get(color_name, (90, 90, 90))
                label = cls_name.replace("_", " ")
            else:
                bg = (35, 35, 35)
                label = f"s{col}.{row}"
            cv2.rectangle(panel, (cx, cy), (cx + cell_w, cy + cell_h), bg, -1)
            cv2.rectangle(panel, (cx, cy), (cx + cell_w, cy + cell_h), (100, 100, 100), 1)
            cv2.putText(panel, label, (cx + 4, cy + cell_h - 8), font, 0.34, (255, 255, 255), 1)

    return y + 6 * (cell_h + gap) + 6


def build_mosaic(frame_map):
    blank = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
    frames = [frame_map.get(idx, blank) for idx in ALL_CAM_ORDER]
    rows = [np.hstack(frames[i:i + WINDOW_COLS]) for i in range(0, len(frames), WINDOW_COLS)]
    return np.vstack(rows)


# ── Nodo ROS2 ─────────────────────────────────────────────────────
class VisionLoggerNode(Node):
    def __init__(self):
        super().__init__("vision_logger")

        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._lock = threading.Lock()

        # ── estado de bloqueo por grupo ───────────────────────────
        self._xarm2_busy_prev = False
        self._trigger_stack = False  # grupo 1: snapshot puntual
        self._blocked_stack = True  # stack bloqueado hasta que xarm2 quede sin ciclo activo

        self._blocked_c1 = False  # grupo 2: conveyor1
        self._blocked_c2 = False  # grupo 3: conveyor2
        self._blocked_c3 = False  # grupo 4: conveyor3 / C3
        self._blocked_c4 = False  # grupo 5: conveyor4 / C4
        self._blocked_ibs = False  # grupo 6: IBS

        # Desbloqueo temprano basado en EXPECTED (pipeline.queues) en vez de
        # en resource_state -- ver comentario junto a XARM1_C1S2_TASKS.
        # _group_prev_count: ultimo recuento de piezas visto en la cola de
        # cada grupo (initial_stack necesita esto porque es una pila de
        # varias piezas, no un slot de una sola -- "vacio" no sirve, hace
        # falta detectar que el recuento BAJO). _group_unblocked_latch:
        # una vez detectado ese "bajo" (o, para los grupos de slot unico,
        # una vez visto vacio) durante el despacho actual, se queda en
        # True el resto del ciclo -- se re-arma solo cuando la tarea deja
        # de estar activa (listo para el siguiente despacho).
        self._group_prev_count = {}
        self._group_unblocked_latch = {}

        # "esperado" por sitio (de /factory/system_state) + verificacion post-desbloqueo
        self._supervisor_data = {k: None for k in LOCATION_KEY_MAP}
        self._verify_state = {
            k: {"timer": None, "mismatch": False, "mismatch_since": None}
            for k in LOCATION_KEY_MAP
        }

        # estado robot para HUD
        self._xarm1_status = "UNKNOWN"
        self._xarm2_status = "UNKNOWN"
        self._robot1_status = "UNKNOWN"
        self._robot2_status = "UNKNOWN"

        # ── DB ────────────────────────────────────────────────────
        try:
            self._conn = get_conn()
            ensure_tables(self._conn)
            self.get_logger().info(f"DB conectada | run_id={self.run_id}")
        except Exception as exc:
            self._conn = None
            self.get_logger().error(f"DB error: {exc}")

        self._prev_slots = {c: None for c in SLOT_COLS}
        self._prev_conveyors = {c: None for c in CONVEYOR_COLS}  # serializado (TEXT o None)
        self._last_reality = {c: [] for c in CONVEYOR_COLS}
        self._stack_status_last_pub = 0.0  # throttle: publish cada 1 s

        # timestamps de ultima actualizacion por grupo
        self._last_update = {
            "Stack (s1.1-s3.6)": None,
            "Conveyor1": None,
            "Conveyor2": None,
            "Conveyor3 / C3": None,
            "Conveyor4 / C4": None,
            "IBS": None,
        }

        # ── Subscripciones ROS2 ───────────────────────────────────
        # run_id sincronizado con factory_supervisor (TRANSIENT_LOCAL = latched,
        # publicado en /factory/run_id -- ver factory_supervisor.py del repo shipyard_pnp)
        _latched_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self.create_subscription(String, "/factory/run_id",
                                  self._on_run_id, _latched_qos)

        # Todo el estado de bloqueo (grupos 1-6) y lo "esperado" por sitio salen
        # de este unico mensaje agregado -- ver system_state_publisher.py del
        # repo shipyard_pnp. Se publica cada 0.5s (bajado desde 2s el
        # 2026-07-07: con 2s, el hueco entre "pieza ya cogida" y "ciclo
        # completo" de los xArms -- ~10s de un ciclo de ~14s total, frente a
        # ~20s+ de un ciclo de robot1/robot2 de ~30s -- se comia casi todo el
        # margen de mejora del desbloqueo temprano; ver CLAUDE.md), asi que
        # un cambio de estado tarda como mucho 0.5s en reflejarse aqui.
        self.create_subscription(String, "/factory/system_state",
                                  self._on_system_state, 10)

        # ── Camaras y modelo ─────────────────────────────────────
        self._rois = load_rois(ROIS_PATH)
        self._model = YOLO(str(MODEL_PATH))
        self._caps = self._open_cameras()
        self._frame_map: dict = {}

        # ── Publisher stack_status ────────────────────────────────
        self._stack_status_pub = self.create_publisher(String, "stack_status", 10)

        # ── Conveyor motion ML detectors ──────────────────────────
        self._motion_detectors: dict = {}
        for _key, _mdir in CONVEYOR_ML_MODELS.items():
            _det = ConveyorDetector(model_dir=str(_mdir))
            try:
                _det.load()
                self.get_logger().info(f"[Motion] Modelo {_key} cargado.")
            except Exception as _e:
                self.get_logger().warn(f"[Motion] Sin modelo para {_key}: {_e}")
            self._motion_detectors[_key] = _det

        self._motion_expected = {k: None for k in CONVEYOR_MOTION_TOPICS}
        self._motion_detected = {k: None for k in CONVEYOR_MOTION_TOPICS}
        self._motion_mismatch = {k: False for k in CONVEYOR_MOTION_TOPICS}
        self._motion_mismatch_since = {k: None for k in CONVEYOR_MOTION_TOPICS}

        for _key, _topic in CONVEYOR_MOTION_TOPICS.items():
            self.create_subscription(
                String, _topic,
                lambda msg, k=_key: self._on_conveyor_status(msg, k), 10
            )

        # ── Hilo de camara ────────────────────────────────────────
        self._running = True
        self._cam_thread = threading.Thread(target=self._camera_loop, daemon=True)
        self._cam_thread.start()
        self.get_logger().info("Vision logger listo.")

    # ── Callbacks ROS2 ────────────────────────────────────────────

    def _on_run_id(self, msg: String):
        new_id = msg.data.strip()
        if new_id and new_id != self.run_id:
            with self._lock:
                self.run_id = new_id
            self.get_logger().info(f"[run_id] sincronizado con factory_supervisor: {new_id}")

    def _on_conveyor_status(self, msg: String, key: str):
        status = msg.data.strip().upper()  # "RUNNING" | "STOPPED"
        with self._lock:
            self._motion_expected[key] = status

    def _set_group_block(self, verify_key: str, group_label: str, was_blocked: bool,
                          now_blocked: bool, reason: str) -> None:
        """Log de transicion + reinicio del timer de verificacion al
        desbloquear un grupo -- misma logica que antes repetida cinco veces,
        ahora en un solo sitio ya que las cinco vienen todas del mismo mensaje."""
        if now_blocked and not was_blocked:
            self.get_logger().info(f"[{group_label}] {verify_key} BLOQUEADO ({reason})")
        elif was_blocked and not now_blocked:
            self._verify_state[verify_key] = {
                "timer": time.time(), "mismatch": False, "mismatch_since": None,
            }
            self.get_logger().info(f"[{group_label}] {verify_key} ACTIVO")

    def _early_unblock(self, group_key: str, current_count: int, task_active: bool) -> bool:
        """Returns True once EXPECTED for `group_key` (a count of pieces in
        the relevant pipeline.queues location) has CHANGED since the
        current dispatch began -- latched True for the rest of this busy
        period, reset the moment `task_active` goes False so the next
        dispatch re-arms cleanly. A change in EITHER direction counts: a
        drop means whoever picks FROM this zone already took the piece; a
        rise means whoever places INTO this zone already dropped theirs off
        (a group can have both a pick-side and a place-side task folded
        into the same `task_active`, see XARM2_C1S1_TASK etc. above). Must
        be called with self._lock held, once per group per message -- see
        comment above XARM1_C1S2_TASKS for why this replaced a
        resource_state-based (PICK_DONE) approach."""
        if not task_active:
            self._group_unblocked_latch[group_key] = False
            self._group_prev_count[group_key] = current_count
            return False
        prev_count = self._group_prev_count.get(group_key)
        if prev_count is not None and current_count != prev_count:
            self._group_unblocked_latch[group_key] = True
        self._group_prev_count[group_key] = current_count
        return self._group_unblocked_latch.get(group_key, False)

    def _on_system_state(self, msg: String):
        """Deriva TODO el estado de bloqueo (grupos 1-6) y lo "esperado" por
        sitio a partir del unico mensaje agregado que publica
        factory_supervisor.py (repo shipyard_pnp)."""
        try:
            payload = json.loads(msg.data)
        except Exception:
            return

        resources = payload.get("resources", {})
        robots = resources.get("robots", {})
        active = payload.get("cycles", {}).get("active_entity_cycles", {})
        queues = payload.get("pipeline", {}).get("queues", {})

        xarm1_c = active.get("xarm1") or {}
        xarm2_c = active.get("xarm2") or {}
        robot1_c = active.get("robot1") or {}
        robot2_c = active.get("robot2") or {}
        xarm1_task = xarm1_c.get("task_name")
        xarm2_task = xarm2_c.get("task_name")
        robot1_task = robot1_c.get("task_name")
        robot2_task = robot2_c.get("task_name")

        with self._lock:
            self._xarm1_status = robots.get("xarm1", "UNKNOWN")
            self._xarm2_status = robots.get("xarm2", "UNKNOWN")
            self._robot1_status = robots.get("robot1", "UNKNOWN")
            self._robot2_status = robots.get("robot2", "UNKNOWN")

            # Desbloqueo temprano: en cuanto EXPECTED (pipeline.queues)
            # cambia en el sitio relevante -- baja porque quien recoge ya
            # se la llevo, o SUBE porque quien coloca ya la deposito -- el
            # grupo se desbloquea ahi mismo, aunque el ciclo siga activo
            # viajando o volviendo a home. Cada zona la tocan dos entidades
            # (una coloca, otra recoge despues); las dos entran en
            # `*_task_active` -- ver el bloque de comentarios junto a
            # XARM1_C1S2_TASKS arriba (2026-07-07: antes solo se vigilaba a
            # la que recoge, asi que el PLACE de xarm1/xarm2 en conveyor1/
            # conveyor2/c3_location nunca bloqueaba nada).
            #
            # El lado que COLOCA solo cuenta como "activo" mientras la pieza
            # ya esta en la pinza -- ver queues["<entidad>_gripper"] (lo
            # llena register_pick_source/_apply_resource_state del lado
            # shipyard_pnp_ws justo en el PICK real, y lo vacia el mismo
            # sitio que hace el transfer_via_gripper al completar el
            # comando). Sin este filtro, task_name solo dispara desde que
            # se DESPACHA la tarea -- que para xarm2 empieza recogiendo del
            # stack inicial (nada que ver con conveyor1/C3 todavia) y para
            # xarm1 puede empezar recogiendo de conveyor1/laser_bed (nada
            # que ver con conveyor2 todavia) -- bloqueando esas zonas
            # muchos segundos antes de que el brazo llegue de verdad,
            # tapando lecturas de piezas YA colocadas por un ciclo anterior
            # que nada tienen que ver con este despacho. Confirmado en la
            # practica: pasaba en conveyor1/conveyor2 (trafico con varias
            # piezas seguidas) pero no se notaba en c3_location (mucho mas
            # esporadico, GREEN-only).
            xarm1_holding = bool(queues.get("xarm1_gripper"))
            xarm2_holding = bool(queues.get("xarm2_gripper"))
            robot2_holding = bool(queues.get("robot2_gripper"))

            c1_task_active = (xarm1_task in XARM1_C1S2_TASKS) or (
                xarm2_task == XARM2_C1S1_TASK and xarm2_holding
            )
            early_c1 = self._early_unblock(
                "c1", len(queues.get("conveyor1", [])), c1_task_active)
            new_blocked_c1 = c1_task_active and not early_c1

            c3_task_active = (robot1_task == ROBOT1_C3_TASK) or (
                xarm2_task == XARM2_C3_TASK and xarm2_holding
            )
            early_c3 = self._early_unblock(
                "c3", len(queues.get("c3_location", [])), c3_task_active)
            new_blocked_c3 = c3_task_active and not early_c3

            c4_task_active = (robot1_task == ROBOT1_C4_TASK) or (
                robot2_task in ROBOT2_C4_PLACE_TASKS and robot2_holding
            )
            early_c4 = self._early_unblock(
                "c4", len(queues.get("c4_location", [])), c4_task_active)
            new_blocked_c4 = c4_task_active and not early_c4

            # IBS no necesita un lado extra: coloca (CLASSIFY_C2S2_TO_IBS) y
            # recoge (IBS_TO_BANTAM) los hace robot2, ambos ya en
            # ROBOT2_IBS_TASKS.
            ibs_task_active = robot2_task in ROBOT2_IBS_TASKS
            early_ibs = self._early_unblock(
                "ibs", len(queues.get("intermediate_blue_stack", [])), ibs_task_active)
            new_blocked_ibs = ibs_task_active and not early_ibs

            # Cualquier tarea CLASSIFY_C2S2* mantiene a robot2 junto a conveyor2
            # (recoge); xarm1 en XARM1_C2S1_PLACE_TASKS tambien, pero solo con
            # la pieza ya en la pinza (coloca, tanto la ruta directa como la
            # de vuelta del laser). IBS_TO_BANTAM no toca conveyor2
            # fisicamente -- su recuento nunca cambia durante ese despacho,
            # asi que ahi se queda bloqueado el ciclo completo tal cual antes
            # (conservador a proposito, sin cambios).
            c2_task_active = (
                ibs_task_active
                or (isinstance(robot2_task, str) and robot2_task.startswith("CLASSIFY_C2S2"))
                or (xarm1_task in XARM1_C2S1_PLACE_TASKS and xarm1_holding)
            )
            early_c2 = self._early_unblock(
                "c2", len(queues.get("conveyor2", [])), c2_task_active)
            new_blocked_c2 = c2_task_active and not early_c2

            # Grupo 1: bloqueado mientras xarm2 tiene ciclo activo Y EXPECTED
            # todavia no refleja que la pieza salio del stack. initial_stack
            # es una pila de varias piezas (no un slot unico), por eso
            # _early_unblock compara RECUENTO, no "vacio". Nadie coloca de
            # vuelta en initial_stack, asi que no necesita lado extra.
            xarm2_any_active = bool(active.get("xarm2"))
            early_stack = self._early_unblock(
                "stack", len(queues.get("initial_stack", [])), xarm2_any_active)
            xarm2_busy = xarm2_any_active and not early_stack

            prev_busy = self._xarm2_busy_prev
            self._xarm2_busy_prev = xarm2_busy
            self._blocked_stack = xarm2_busy
            if prev_busy and not xarm2_busy:
                self._trigger_stack = True
                self.get_logger().info("[G1] xArm2 cogio la pieza del stack (o quedo IDLE): stack ACTIVO + snapshot")

            self._set_group_block("conveyor1", "G2", self._blocked_c1, new_blocked_c1, xarm1_task)
            self._blocked_c1 = new_blocked_c1

            self._set_group_block("conveyor2", "G3", self._blocked_c2, new_blocked_c2, robot2_task)
            self._blocked_c2 = new_blocked_c2

            self._set_group_block("ibs", "G6", self._blocked_ibs, new_blocked_ibs, robot2_task)
            self._blocked_ibs = new_blocked_ibs

            self._set_group_block("conveyor3", "G4", self._blocked_c3, new_blocked_c3, robot1_task)
            self._blocked_c3 = new_blocked_c3

            self._set_group_block("conveyor4", "G5", self._blocked_c4, new_blocked_c4, robot1_task)
            self._blocked_c4 = new_blocked_c4

            # "Esperado" por sitio, desde el pipeline en vivo.
            for key, loc in LOCATION_KEY_MAP.items():
                data = queues.get(loc, [])
                if data != self._supervisor_data.get(key):
                    self._supervisor_data[key] = data
                    self._verify_state[key]["timer"] = time.time()
                    self._verify_state[key]["mismatch"] = False
                    self._verify_state[key]["mismatch_since"] = None
                else:
                    self._supervisor_data[key] = data

    # ── Camaras ───────────────────────────────────────────────────

    def _open_cameras(self):
        caps = {}
        for idx in CAMERA_INDICES:
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            if not cap.isOpened():
                self.get_logger().warn(f"Camara {idx} no disponible")
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            caps[idx] = cap
            self.get_logger().info(f"Camara {idx} abierta")
        return caps

    # ── ROIs bloqueados segun estado actual ───────────────────────

    def _blocked_rois(self) -> set:
        blocked = set()
        if self._blocked_stack:
            blocked.update(SLOT_COLS)  # todos los s1_1...s3_6
        if self._blocked_c1:
            blocked.add("conveyor1")
        if self._blocked_c2:
            blocked.add("conveyor2")
        if self._blocked_c3:
            blocked.add("conveyor3")
        if self._blocked_c4:
            blocked.add("conveyor4")
        if self._blocked_ibs:
            blocked.add("ibs")
        return blocked

    # ── Hilo de camara ────────────────────────────────────────────

    def _camera_loop(self):
        WIN = "Vision Logger ROS | q=salir"
        cv2.namedWindow(WIN)

        while self._running:
            with self._lock:
                blocked = self._blocked_rois()
                do_stack = self._trigger_stack and not self._blocked_stack
                xarm2_idle = not self._blocked_stack
                xarm1_st = self._xarm1_status
                xarm2_st = self._xarm2_status
                robot1_st = self._robot1_status
                robot2_st = self._robot2_status
                verify_snapshot = {k: dict(v) for k, v in self._verify_state.items()}
                sup_snapshot = dict(self._supervisor_data)

            slots = {c: None for c in SLOT_COLS}
            conveyors = {c: [] for c in CONVEYOR_COLS}
            frame_map = {}

            for cam_idx, cap in self._caps.items():
                ret, frame = cap.read()
                if not ret:
                    blank = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
                    cv2.putText(blank, f"Cam {cam_idx}: sin senal", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    frame_map[cam_idx] = blank
                    continue

                cam_rois = self._rois.get(cam_idx, [])
                results = self._model(frame, conf=0.01, verbose=False)
                boxes = results[0].boxes
                names = results[0].names

                no_block_zones = [r for r in cam_rois if r.get("no_block")]

                for box in boxes:
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                    cls_name = names[int(box.cls[0])]
                    matched_names: set = set()  # evita contar la misma deteccion dos veces
                    for roi in cam_rois:
                        rname = roi["name"]
                        is_nb = roi.get("no_block", False)
                        if not point_in_polygon(roi["pts"], cx, cy):
                            continue
                        if not is_nb and rname in blocked:
                            in_no_block = any(
                                point_in_polygon(z["pts"], cx, cy)
                                for z in no_block_zones
                            )
                            if not in_no_block:
                                continue
                        if conf >= CONF_THRESHOLD:
                            if rname in slots:
                                slots[rname] = cls_name
                            elif rname in conveyors and rname not in matched_names:
                                conveyors[rname].append(cls_name)
                                matched_names.add(rname)

                # ── Conveyor motion ML ────────────────────────────
                for _mkey, _mcam in CONVEYOR_ML_CAMS.items():
                    if _mcam == cam_idx:
                        _mstate = self._motion_detectors[_mkey].update(frame)
                        if _mstate is not None:
                            self._motion_detected[_mkey] = _mstate
                            # overlay en frame
                            _mlabel = "RUNNING" if _mstate.moving else "STOPPED"
                            _mcolor = (0, 255, 80) if _mstate.moving else (0, 60, 255)
                            cv2.putText(frame, f"[ML] {_mkey}: {_mlabel} {_mstate.confidence:.2f}",
                                        (8, FRAME_HEIGHT - 12),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, _mcolor, 1)

                # dibujo
                status_lines = [
                    f"xArm1:{xarm1_st} xArm2:{xarm2_st}",
                    f"R1:{robot1_st} R2:{robot2_st}",
                ]
                draw_detections(frame, boxes, names, cam_rois, blocked)
                draw_rois(frame, cam_rois, cam_idx, blocked)
                draw_hud(frame, cam_idx, self.run_id, status_lines)
                frame_map[cam_idx] = frame

            # ── DB escritura ──────────────────────────────────────
            if self._conn:
                try:
                    now_str = datetime.now().strftime("%H:%M:%S")

                    # Grupo 1: snapshot stack en flanco "sin ciclo activo" de xarm2
                    if do_stack:
                        insert_row(self._conn, SLOT_TABLE, SLOT_COLS,
                                   self.run_id, slots)
                        with self._lock:
                            self._trigger_stack = False
                            self._prev_slots = dict(slots)
                            self._last_update["Stack (s1.1-s3.6)"] = now_str
                            # restaurar bloqueo segun estado real de xarm2
                            self._blocked_stack = (self._xarm2_status != "IDLE")
                        self.get_logger().info("[G1] Snapshot stack guardado")
                    # Serializar listas -> TEXT para DB (None si vacio)
                    conveyors_db = {
                        c: (json.dumps(sorted(v)) if v else None)
                        for c, v in conveyors.items()
                    }
                    # Grupos 2-5: conveyors, solo si cambiaron Y hay algo detectado
                    any_detected = any(v for v in conveyors.values())
                    if conveyors_db != self._prev_conveyors and any_detected:
                        insert_row(self._conn, CONVEYOR_TABLE, CONVEYOR_COLS,
                                   self.run_id, conveyors_db)
                        with self._lock:
                            self._prev_conveyors = dict(conveyors_db)
                            if conveyors_db.get("conveyor1"):
                                self._last_update["Conveyor1"] = now_str
                            if conveyors_db.get("conveyor2"):
                                self._last_update["Conveyor2"] = now_str
                            if conveyors_db.get("conveyor3"):
                                self._last_update["Conveyor3 / C3"] = now_str
                            if conveyors_db.get("conveyor4"):
                                self._last_update["Conveyor4 / C4"] = now_str
                            if conveyors_db.get("ibs"):
                                self._last_update["IBS"] = now_str
                        self.get_logger().info(
                            f"[Conv] snapshot guardado: "
                            f"{[k for k, v in conveyors_db.items() if v]}"
                        )
                except Exception as exc:
                    self.get_logger().error(f"DB error: {exc}")

            # ── Actualizar ultima realidad conocida (no bloqueado) ──
            for c in CONVEYOR_COLS:
                if c not in blocked:
                    self._last_reality[c] = conveyors[c]

            # ── Verificacion continua (gracia 2 s post-desbloqueo) ─
            now = time.time()
            for conv, state in verify_snapshot.items():
                if state["timer"] is not None:
                    grace = VERIFY_TIMEOUT_OVERRIDE.get(conv, VERIFY_TIMEOUT)
                    if now - state["timer"] < grace:
                        continue  # dentro de la ventana de gracia post-desbloqueo
                    with self._lock:
                        self._verify_state[conv]["timer"] = None
                    detected = self._last_reality.get(conv, [])
                    expected = sup_snapshot.get(conv)
                    match = check_piece_match(expected, detected)
                    debounce = ALARM_DEBOUNCE.get(conv, 0.0)
                    print(f"[VERIFY] {conv}: match={match} exp={expected} got={detected}", flush=True)
                    if match:
                        with self._lock:
                            self._verify_state[conv]["mismatch"] = False
                            self._verify_state[conv]["mismatch_since"] = None
                    else:
                        since = state.get("mismatch_since") or now
                        if state.get("mismatch_since") is None:
                            with self._lock:
                                self._verify_state[conv]["mismatch_since"] = now
                            since = now
                        if now - since >= debounce:
                            if not state["mismatch"]:
                                self.get_logger().warn(
                                    f"[VERIFY] {conv}: MISMATCH -- expected={expected} yolo={detected}"
                                )
                                with self._lock:
                                    self._verify_state[conv]["mismatch"] = True

            # ── Verificacion motion ML ───────────────────────────────
            with self._lock:
                _motion_exp = dict(self._motion_expected)
                for _mkey in CONVEYOR_MOTION_TOPICS:
                    _exp = _motion_exp.get(_mkey)
                    _det = self._motion_detected.get(_mkey)
                    if _exp is None or _det is None:
                        continue
                    _match = (_exp == "RUNNING") == _det.moving
                    if _match:
                        self._motion_mismatch[_mkey] = False
                        self._motion_mismatch_since[_mkey] = None
                    else:
                        if self._motion_mismatch_since[_mkey] is None:
                            self._motion_mismatch_since[_mkey] = now
                        if now - self._motion_mismatch_since[_mkey] >= CONVEYOR_MOTION_DEBOUNCE:
                            if not self._motion_mismatch[_mkey]:
                                self.get_logger().warn(
                                    f"[Motion] {_mkey}: MISMATCH "
                                    f"expected={_exp} ML={'RUNNING' if _det.moving else 'STOPPED'}"
                                )
                                self._motion_mismatch[_mkey] = True

            # ── Publish stack_status: RETURNING_HOME=cada frame, resto=1 Hz ─
            if xarm2_idle:
                is_returning_home = (xarm2_st == "RETURNING_HOME")
                throttle_ok = is_returning_home or (now - self._stack_status_last_pub) >= 1.0
                if throttle_ok:
                    payload = {k.replace("_", "."): v for k, v in slots.items()}
                    _pub_msg = String()
                    _pub_msg.data = json.dumps(payload)
                    self._stack_status_pub.publish(_pub_msg)
                    if not is_returning_home:
                        self._stack_status_last_pub = now
                    print(f"[stack_status] {_pub_msg.data}", flush=True)

            # ── Display ───────────────────────────────────────────
            mosaic = build_mosaic(frame_map)
            draw_last_update_legend(mosaic, self._last_update)

            with self._lock:
                _sup = dict(self._supervisor_data)
                _ver = {k: dict(v) for k, v in self._verify_state.items()}
            for cam_idx, frame in frame_map.items():
                draw_mismatch_stars(frame, self._rois.get(cam_idx, []), _ver)
            panel = build_supervisor_panel(_sup, _ver, self._last_reality, mosaic.shape[0],
                                            self._motion_expected, self._motion_detected,
                                            self._motion_mismatch, slots)
            mosaic = np.hstack([mosaic, panel])

            cv2.imshow(WIN, mosaic)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                self._running = False
                break
            elif key == ord(' '):
                with self._lock:
                    self._trigger_stack = True
                    self._blocked_stack = False  # forzar desbloqueo puntual
                self.get_logger().info("[G1] Snapshot manual forzado por espacio")

        cv2.destroyAllWindows()

    def destroy_node(self):
        self._running = False
        self._cam_thread.join(timeout=3)
        for cap in self._caps.values():
            cap.release()
        if self._conn and not self._conn.closed:
            self._conn.close()
        super().destroy_node()


# ── Entry point ───────────────────────────────────────────────────
def main(args=None):
    rclpy.init(args=args)
    node = VisionLoggerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
